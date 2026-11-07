import asyncio
import json
import math
from hashlib import sha256
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from findie_ai.ranking import MAX_SEARCH_CANDIDATES, location_tokens, normalize_text, rank_candidates


class SnapshotConflict(ValueError):
    pass


class Store:
    def __init__(self, dsn, model_id, revision, dimensions, processing_profile="text-v1", *,
                 cache=None, semantic_weight=0.6):
        self.dsn = dsn
        self.identity = (model_id, revision, dimensions, processing_profile)
        self.dimensions = dimensions
        self.cache = cache
        self.semantic_weight = semantic_weight

    async def close(self):
        if self.cache:
            await self.cache.close()

    async def migrate(self):
        async with await psycopg.AsyncConnection.connect(self.dsn) as connection:
            await connection.execute(Path(__file__).with_name("schema.sql").read_text())

    async def check(self):
        async with await psycopg.AsyncConnection.connect(self.dsn) as connection:
            await connection.execute("""SELECT d.embedding <=> d.embedding, i.document_version
                                        FROM ai_documents d JOIN ai_items i USING (item_id)
                                        CROSS JOIN ai_search_state s LIMIT 0""")

    def _vector(self, vector):
        if len(vector) != self.dimensions or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in vector
        ) or not any(vector):
            raise ValueError("Embedding must contain the configured number of finite, nonzero values.")
        return json.dumps(vector, allow_nan=False)

    async def upsert(self, snapshot, snapshot_hash, embedding, deadline, *, text_only=False, ocr=None):
        sources = snapshot["sources"]
        if not isinstance(embedding, dict):
            if len(sources) != 1 or sources[0]["kind"] != "text":
                raise ValueError("All snapshot sources require embeddings.")
            embedding = {str(sources[0]["id"]): embedding}
        expected = {str(source["id"]) for source in sources if not text_only or source["kind"] == "text"}
        if len({str(source["id"]) for source in sources}) != len(sources) or set(embedding) != expected:
            raise ValueError("Embedding sources must match the enabled projection of the complete manifest.")
        vectors = {source_id: self._vector(vector) for source_id, vector in embedding.items()}
        ocr = {} if ocr is None else ocr
        image_ids = {str(source["id"]) for source in sources if source["kind"] == "image"}
        if (not isinstance(ocr, dict) or not set(ocr) <= image_ids & set(vectors)
                or any(not isinstance(value, str) or len(value) > 3000 for value in ocr.values())):
            raise ValueError("OCR must be bounded text tied to enabled image sources.")
        return await self._write(snapshot, snapshot_hash, vectors, deadline, ocr=ocr)

    async def remove(self, snapshot, snapshot_hash, deadline):
        return await self._write(snapshot, snapshot_hash, None, deadline)

    async def _write(self, snapshot, snapshot_hash, embedding, deadline, *, ocr=None):
        ocr = {} if ocr is None else ocr
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("Index command deadline expired.")
        item_id, version = snapshot["itemId"], snapshot["documentVersion"]
        tombstone = embedding is None
        async with asyncio.timeout(remaining):
            async with await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row) as connection:
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(item_id),))
                cursor = await connection.execute(
                    "SELECT document_version, snapshot_sha256, tombstone FROM ai_items WHERE item_id = %s",
                    (item_id,),
                )
                current = await cursor.fetchone()
                if current and current["document_version"] > version:
                    return False
                if current and current["document_version"] == version:
                    if current["snapshot_sha256"] != snapshot_hash or current["tombstone"] != tombstone:
                        raise SnapshotConflict("Same document version has a different snapshot.")
                else:
                    await connection.execute(
                        """INSERT INTO ai_items (item_id, document_version, snapshot_sha256, tombstone)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (item_id) DO UPDATE SET document_version = EXCLUDED.document_version,
                           snapshot_sha256 = EXCLUDED.snapshot_sha256, tombstone = EXCLUDED.tombstone""",
                        (item_id, version, snapshot_hash, tombstone),
                    )
                    await connection.execute("DELETE FROM ai_documents WHERE item_id = %s", (item_id,))
                if not tombstone:
                    document = snapshot["document"]
                    description_terms = normalize_text(document["publicDescription"])
                    if ocr:
                        description_terms += " " + " ".join(
                            normalize_text(ocr[str(source["id"])]) for source in snapshot["sources"]
                            if str(source["id"]) in ocr
                        )
                    # A replay may reindex a new model namespace, preserving other current namespaces.
                    await connection.execute(
                        "DELETE FROM ai_documents WHERE item_id = %s AND model_id = %s AND model_revision = %s AND dimensions = %s",
                        (item_id, *self.identity[:3]),
                    )
                    for source in snapshot["sources"]:
                        if (source["kind"], source["processingProfile"]) not in {
                            ("text", "text-v1"), ("image", "image-v1")
                        }:
                            raise ValueError("Invalid source modality.")
                        if str(source["id"]) not in embedding:
                            continue
                        await connection.execute(
                        """INSERT INTO ai_documents (item_id, model_id, model_revision, dimensions,
                           processing_profile, document_version, source_id, source_version, source_sha256,
                           found_area, found_on, found_from, found_until, search_terms, location_tokens, embedding)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           setweight(to_tsvector('simple', %s), 'A') ||
                           setweight(to_tsvector('simple', %s), 'B') ||
                           setweight(to_tsvector('simple', %s), 'C'), %s, %s::vector)
                           """,
                        (item_id, *self.identity[:3], source["processingProfile"], version,
                         source["id"], source["version"], source["sha256"],
                         document["foundArea"], document.get("foundOn"), document.get("foundFrom"),
                         document.get("foundUntil"),
                         normalize_text(document["title"]) if source["kind"] == "text" else "",
                         description_terms if source["kind"] == "text" else "",
                         normalize_text(document["foundArea"]) if source["kind"] == "text" else "",
                         location_tokens(document["title"] + " " + document["publicDescription"]) if source["kind"] == "text" else [],
                         embedding[str(source["id"])]),
                        )
                if datetime.now(timezone.utc) >= deadline:
                    raise TimeoutError("Index command deadline expired before commit.")
                # Commit invalidation with the index, including replays that enable image sources.
                await connection.execute("UPDATE ai_search_state SET version = gen_random_uuid() WHERE singleton")
            return True

    async def search(self, text, vector, area=None, from_date=None, until=None, limit=MAX_SEARCH_CANDIDATES, *, strategy="hybrid",
                     modality="text", include_images=False, embed=None, outside_area=False, include_similarity=False):
        if not 1 <= limit <= MAX_SEARCH_CANDIDATES:
            raise ValueError(f"Candidate limit must be between 1 and {MAX_SEARCH_CANDIDATES}.")
        if strategy not in {"hybrid", "semantic", "lexical"}:
            raise ValueError("Unknown evaluation strategy.")
        if modality not in {"text", "image"}:
            raise ValueError("Unknown search modality.")
        vector = self._vector(vector) if vector is not None else None
        if vector is None and embed is None:
            raise ValueError("Search requires a vector or embedding callback.")
        first = date.fromisoformat(from_date) if isinstance(from_date, str) else from_date
        last = date.fromisoformat(until) if isinstance(until, str) else until
        if first and last and first > last:
            raise ValueError("Invalid date filter.")
        local_timezone = timezone(timedelta(hours=7))
        start = datetime.combine(first, time.min, local_timezone) if first else None
        end = datetime.combine(last + timedelta(days=1), time.min, local_timezone) if last else None
        tokens = location_tokens(text) if modality == "text" else []
        lexical_query = " | ".join(dict.fromkeys(normalize_text(text).split())) if modality == "text" else ""
        # Retrieve a bounded pool before the requested output limit so fusion keeps both ranks.
        pool_limit = MAX_SEARCH_CANDIDATES
        profiles = ["image-v1"] if modality == "image" else ["text-v1", "image-v1"] if include_images else ["text-v1"]
        channels = {"semantic": [], "lexical": [], "locations": []}
        need_semantic = modality == "image" or strategy != "lexical" or include_similarity
        need_keyword = modality == "text" and strategy != "semantic"
        keyword_key = None
        # shortcut: exact vector scan favors recall; add ANN only after measuring corpus size and recall.
        async with await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row, autocommit=True) as connection:
            if self.cache and need_keyword:
                cursor = await connection.execute("SELECT version FROM ai_search_state WHERE singleton")
                version = str((await cursor.fetchone())["version"])
                identity = (sha256(self.dsn.encode()).hexdigest(), version, self.identity, profiles, pool_limit,
                            area, outside_area, first.isoformat() if first else None, last.isoformat() if last else None)
                keyword_key = self.cache.key((*identity, lexical_query, tokens))
                cached = await self.cache.get(keyword_key)
                if cached is not None:
                    channels.update(cached)
                    need_keyword = False
            if need_semantic and vector is None:
                vector = self._vector(await embed())
            if need_semantic or need_keyword:
                fresh = await self._search_channels(connection, profiles, area, outside_area, first, start, last, end,
                    vector, lexical_query, tokens, need_semantic, need_keyword, pool_limit)
                channels.update(fresh)
                if keyword_key and need_keyword:
                    await self.cache.put(keyword_key, {name: channels[name] for name in ("lexical", "locations")})
            if modality == "image":
                hits = rank_candidates(channels["semantic"], [], [], [], limit)
            elif strategy != "hybrid":
                hits = rank_candidates(channels[strategy], [], [], [], limit)
            else:
                hits = rank_candidates(channels["semantic"], channels["lexical"], channels["locations"], tokens, limit,
                                       semantic_weight=self.semantic_weight)
            if include_similarity:
                similarities = {str(row["item_id"]): row["similarity"] for row in channels["semantic"]}
                missing = [hit["itemId"] for hit in hits if hit["itemId"] not in similarities]
                if missing:
                    # Keyword hits outside the semantic pool still need measured, query-specific cosine.
                    cursor = await connection.execute("""SELECT d.item_id,
                        max(1 - (d.embedding <=> %s::vector)) AS similarity
                        FROM ai_documents d JOIN ai_items i USING (item_id)
                        WHERE d.item_id = ANY(%s::uuid[]) AND NOT i.tombstone
                          AND d.document_version = i.document_version
                          AND (d.model_id, d.model_revision, d.dimensions) = (%s, %s, %s)
                          AND d.processing_profile = ANY(%s::text[])
                        GROUP BY d.item_id""", (vector, missing, *self.identity[:3], profiles))
                    similarities.update({str(row["item_id"]): row["similarity"] for row in await cursor.fetchall()})
                for hit in hits:
                    hit["similarity"] = similarities.get(hit["itemId"], -1.0)
        return hits

    async def _search_channels(self, connection, profiles, area, outside_area, first, start, last, end, vector,
                               lexical_query, tokens, need_semantic, need_keyword, pool_limit):
        cursor = await connection.execute(
            """WITH eligible AS MATERIALIZED (
                SELECT d.* FROM ai_documents d JOIN ai_items i USING (item_id)
                WHERE (%s::text IS NULL OR (strpos(lower(d.found_area), lower(%s)) > 0) <> %s)
                  AND NOT i.tombstone AND d.document_version = i.document_version
                  AND (d.model_id, d.model_revision, d.dimensions) = (%s, %s, %s)
                  AND d.processing_profile = ANY(%s::text[])
                  AND (%s::date IS NULL OR d.found_on >= %s OR coalesce(d.found_until, d.found_from) >= %s)
                  AND (%s::date IS NULL OR d.found_on <= %s OR d.found_from < %s)
            ), nearest_source AS (
                SELECT *, 1 - (embedding <=> %s::vector) AS similarity,
                    row_number() OVER (PARTITION BY item_id ORDER BY embedding <=> %s::vector, source_id) AS source_rank
                FROM eligible WHERE %s
            ), semantic AS (
                SELECT *, row_number() OVER (ORDER BY embedding <=> %s::vector, item_id) AS rank
                FROM nearest_source WHERE source_rank = 1 ORDER BY rank LIMIT %s
            ), lexical_sources AS (
                SELECT *, ts_rank_cd(search_terms, to_tsquery('simple', %s)) AS lexical_score,
                    row_number() OVER (PARTITION BY item_id ORDER BY ts_rank_cd(search_terms, to_tsquery('simple', %s)) DESC, source_id) AS lexical_source_rank
                FROM eligible WHERE %s AND search_terms @@ to_tsquery('simple', %s)
            ), lexical AS (
                SELECT *, row_number() OVER (ORDER BY lexical_score DESC, item_id) AS rank
                FROM lexical_sources WHERE lexical_source_rank = 1 ORDER BY rank LIMIT %s
            ), locations AS (
                SELECT *, row_number() OVER (ORDER BY ts_rank_cd(search_terms, to_tsquery('simple', %s)) DESC, item_id) AS rank
                FROM eligible WHERE %s AND processing_profile = 'text-v1' AND location_tokens && %s::text[] ORDER BY rank LIMIT %s
            )
            SELECT 'semantic' AS channel, item_id, document_version, source_id, source_version, source_sha256, processing_profile, location_tokens, similarity, rank FROM semantic
            UNION ALL
            SELECT 'lexical', item_id, document_version, source_id, source_version, source_sha256, processing_profile, location_tokens, NULL::double precision, rank FROM lexical
            UNION ALL
            SELECT 'locations', item_id, document_version, source_id, source_version, source_sha256, processing_profile, location_tokens, NULL::double precision, rank FROM locations
            ORDER BY channel, rank""",
            (area, area, outside_area, *self.identity[:3], profiles,
             first, first, start, last, last, end, vector, vector, need_semantic, vector, pool_limit,
             lexical_query, lexical_query, need_keyword, lexical_query, pool_limit, lexical_query, need_keyword, tokens, pool_limit),
        )
        channels = {name: [] for name in (("semantic",) if need_semantic else ())
                    + (("lexical", "locations") if need_keyword else ())}
        for row in await cursor.fetchall():
            channels[row["channel"]].append(row)
        return channels
