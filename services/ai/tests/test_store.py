import asyncio
import hashlib
import json
import os
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from findie_ai.store import SnapshotConflict, Store
from findie_ai.search_cache import SearchCache


@pytest.fixture
def store():
    dsn = os.environ.get("AI_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set AI_TEST_DATABASE_URL to run PostgreSQL/pgvector integration checks.")
    schema = "ai_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema},public")
    result = Store(scoped_dsn, "test-embedding", "revision-1", 3)
    try:
        asyncio.run(result.migrate())
        yield result
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def snapshot(description="Ví đen, nhặt tại phòng học E.205", *, item_id=None, version=1,
             area="Trường đại học Sài Gòn", found_on="2026-10-25", found_from=None, found_until=None,
             title="Ví màu đen"):
    item_id = item_id or str(uuid4())
    return {
        "schemaVersion": 1, "itemId": item_id, "documentVersion": version, "kind": "snapshot",
        "document": {
            "title": title, "publicDescription": description, "foundArea": area,
            "foundTimePrecision": "date", "foundOn": found_on, "foundFrom": found_from,
            "foundUntil": found_until, "foundTimezone": "Asia/Ho_Chi_Minh", "custody": {},
        },
        "sources": [{"kind": "text", "id": item_id, "version": version,
                     "sha256": hashlib.sha256((title + "\n" + description).encode()).hexdigest(),
                     "processingProfile": "text-v1"}],
    }


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def deadline():
    return datetime.now(timezone.utc) + timedelta(seconds=30)


def test_keyword_candidate_outside_semantic_twenty_receives_measured_similarity(store):
    async def run():
        store.semantic_weight = 0.3
        for _ in range(20):
            await put(store, snapshot("Đồ mẫu không có nhãn hiệu", title="Đồ mẫu"))
        target = snapshot("Tai nghe mẫu ZXMODEL", title="ZXMODEL")
        await put(store, target, vector=(0.7, 0.714142842854285, 0.0))
        hits = await store.search("ZXMODEL", [1, 0, 0], include_similarity=True)
        hit = next(value for value in hits if value["itemId"] == target["itemId"])
        assert hit["similarity"] == pytest.approx(0.7, abs=1e-6)
    asyncio.run(run())


@pytest.fixture
def redis_url():
    url = os.environ.get("AI_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set AI_TEST_REDIS_URL to run real Redis search cache checks.")
    return url


def test_redis_keyword_cache_and_invalidation_follow_committed_index_changes(store, redis_url):
    async def run():
        cache = SearchCache(redis_url, 60)
        store.cache = cache
        store._search_channels = AsyncMock(wraps=store._search_channels)
        cache.put = AsyncMock(wraps=cache.put)
        embed = AsyncMock(return_value=[1, 0, 0])
        try:
            value = snapshot()
            await put(store, value)
            first = await store.search("ví E.205", None, embed=embed)
            assert first[0]["itemId"] == value["itemId"]
            assert store._search_channels.await_args.args[-3:-1] == (True, True)
            assert await store.search("ví E.205", None, embed=embed) == first
            assert store._search_channels.await_args.args[-3:-1] == (True, False)
            assert embed.await_count == store._search_channels.await_count == 2
            cache.put.assert_awaited_once()
            key = cache.put.await_args.args[0]
            assert key.startswith("findie:search:v1:keyword:")
            assert 0 < await cache.client.ttl(key) <= 60
            # Invalid writes roll back the generation alongside the previous projection.
            invalid = with_images(snapshot(item_id=value["itemId"], version=2), count=1)
            invalid["sources"][1]["processingProfile"] = "unknown"
            with pytest.raises(ValueError):
                await store.upsert(invalid, checksum(invalid), {source["id"]: [1, 0, 0] for source in invalid["sources"]}, deadline())
            assert await store.search("ví E.205", None, embed=embed) == first
            assert store._search_channels.await_args.args[-3:-1] == (True, False)
            cache.put.assert_awaited_once()
            # A writer with no reachable Redis must still invalidate another worker's warm cache.
            offline = Store(store.dsn, *store.identity[:3], cache=SearchCache("redis://127.0.0.1:1", 60))
            try:
                updated = snapshot(item_id=value["itemId"], version=2, description="Ví màu đen đã cập nhật")
                await put(offline, updated)
                assert (await offline.search("ví E.205", [1, 0, 0]))[0]["documentVersion"] == 2
            finally:
                await offline.close()
            assert (await store.search("ví E.205", None, embed=embed))[0]["documentVersion"] == 2
            assert store._search_channels.await_args.args[-3:-1] == (True, True)
            assert cache.put.await_args.args[0] != key
            tombstone = {**updated, "kind": "tombstone", "documentVersion": 3, "document": None, "sources": []}
            await store.remove(tombstone, checksum(tombstone), deadline())
            assert await store.search("ví E.205", None, embed=embed) == []
            assert store._search_channels.await_args.args[-3:-1] == (True, True)
            # An empty keyword pool cannot hide an item published later.
            new = snapshot()
            await put(store, new)
            assert (await store.search("ví E.205", None, embed=embed))[0]["itemId"] == new["itemId"]
        finally:
            await store.close()
    asyncio.run(run())


def test_redis_keyword_ttl_expiry_runs_keyword_search_again(store, redis_url):
    async def run():
        cache = SearchCache(redis_url, 1)
        store.cache = cache
        store._search_channels = AsyncMock(wraps=store._search_channels)
        embed = AsyncMock(return_value=[1, 0, 0])
        try:
            await put(store, snapshot())
            expected = await store.search("ví", None, embed=embed)
            assert await store.search("ví", None, embed=embed) == expected
            assert store._search_channels.await_args.args[-3:-1] == (True, False)
            await asyncio.sleep(1.1)
            assert await store.search("ví", None, embed=embed) == expected
            assert store._search_channels.await_args.args[-3:-1] == (True, True)
            assert embed.await_count == store._search_channels.await_count == 3
        finally:
            await store.close()
    asyncio.run(run())


async def put(store, value, vector=(1.0, 0.0, 0.0)):
    return await store.upsert(value, checksum(value), list(vector), deadline())


def test_room_hall_retrieval_and_date_filters_precede_candidate_limit(store):
    async def run():
        room = snapshot()
        hall = snapshot("Ví màu đen nhặt được tại sảnh hội trường A")
        wrong_room = snapshot("Ví màu đen nhặt tại phòng E.206")
        for value, vector in [(room, [0.8, 0.2, 0]), (hall, [0.8, 0.1, 0.1]), (wrong_room, [1, 0, 0])]:
            await put(store, value, vector)
        for _ in range(5):
            await put(store, snapshot(found_on="2026-10-23"))
        result = await store.search("vi den phong E205", [1, 0, 0], "SÀI GÒN", "2026-10-25", "2026-10-25", 2)
        assert result[0]["itemId"] == room["itemId"]
        assert len(result) == 2
        result = await store.search("vi den sanh hoi truong A", [1, 0, 0], "Sài Gòn", "2026-10-25", None, 2)
        assert result[0]["itemId"] == hall["itemId"]
        assert result[0]["sourceSha256"] == hall["sources"][0]["sha256"]
    asyncio.run(run())


def test_filter_date_overlap_matches_vietnam_timezone_and_excludes_unknown(store):
    async def run():
        inside = snapshot(found_on=None, found_from="2026-10-24T17:00:00Z")
        interval = snapshot(found_on=None, found_from="2026-10-24T10:00:00Z", found_until="2026-10-24T18:00:00Z")
        outside_before = snapshot(found_on=None, found_from="2026-10-24T16:59:59Z")
        outside_after = snapshot(found_on=None, found_from="2026-10-25T17:00:00Z")
        unknown = snapshot(found_on=None)
        for value in [inside, interval, outside_before, outside_after, unknown]:
            await put(store, value)
        result = await store.search("ví", [1, 0, 0], from_date="2026-10-25", until="2026-10-25")
        assert {row["itemId"] for row in result} == {inside["itemId"], interval["itemId"]}
    asyncio.run(run())


def test_wrong_object_in_matching_room_and_punctuation_only_query(store):
    async def run():
        wallet = snapshot("Ví màu đen nhặt tại phòng E.206")
        laptop = snapshot("Máy tính xách tay tại phòng E.205", title="Máy tính xách tay")
        await put(store, wallet)
        await put(store, laptop, [0.1, 0.9, 0])
        result = await store.search("ví màu đen phòng E.205", [1, 0, 0])
        assert result[0]["itemId"] == wallet["itemId"]
        assert len(await store.search("...!?", [1, 0, 0])) == 2
    asyncio.run(run())


def test_versions_conflicts_tombstones_and_deadline_rollback(store):
    async def run():
        value = snapshot()
        assert await put(store, value)
        assert await put(store, value)
        conflicting = snapshot("Mô tả khác", item_id=value["itemId"])
        with pytest.raises(SnapshotConflict):
            await put(store, conflicting)
        tombstone = {"schemaVersion": 1, "itemId": value["itemId"], "documentVersion": 2,
                     "kind": "tombstone", "document": None, "sources": []}
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert not await put(store, value)
        assert not await store.search("ví", [1, 0, 0])
        expired = snapshot()
        with pytest.raises(TimeoutError):
            await store.upsert(expired, checksum(expired), [1, 0, 0], datetime.now(timezone.utc) - timedelta(seconds=1))
        assert not await store.search("ví", [1, 0, 0])
    asyncio.run(run())


def test_model_namespaces_do_not_mix_vectors_and_new_revision_can_reindex(store):
    async def run():
        value = snapshot()
        await put(store, value)
        other = Store(store.dsn, "other-embedding", "revision-2", 2)
        assert await other.search("ví", [1, 0]) == []
        assert await other.upsert(value, checksum(value), [1, 0], deadline())
        assert len(await other.search("ví", [1, 0])) == 1
        assert len(await store.search("ví", [1, 0, 0])) == 1
        newer = snapshot(item_id=value["itemId"], version=2)
        assert await other.upsert(newer, checksum(newer), [1, 0], deadline())
        assert await store.search("ví", [1, 0, 0]) == []
    asyncio.run(run())


def test_concurrent_versions_keep_newest_and_reject_invalid_vectors(store):
    async def run():
        old = snapshot()
        new = snapshot(item_id=old["itemId"], version=2)
        await asyncio.gather(put(store, new), put(store, old))
        result = await store.search("ví", [1, 0, 0])
        assert result[0]["documentVersion"] == 2
        for vector in ([1, 0], [0, 0, 0], [float("nan"), 0, 0], [True, 0, 0]):
            with pytest.raises(ValueError):
                await put(store, snapshot(), vector)
    asyncio.run(run())


def with_images(value, count=2):
    value["sources"].extend({"kind": "image", "id": str(uuid4()), "version": 2,
        "sha256": str(index + 1) * 64, "processingProfile": "image-v1"} for index in range(count))
    return value


def test_multisource_snapshot_is_atomic_and_image_search_deduplicates_with_provenance(store):
    async def run():
        value = with_images(snapshot())
        sources = value["sources"]
        vectors = {sources[0]["id"]: [1, 0, 0], sources[1]["id"]: [0, 1, 0], sources[2]["id"]: [0, 0.8, 0.2]}
        with pytest.raises(ValueError):
            await store.upsert(value, checksum(value), {sources[0]["id"]: [1, 0, 0]}, deadline())
        assert await store.search("ví", [1, 0, 0]) == []
        assert await store.upsert(value, checksum(value), vectors, deadline())
        text = await store.search("ví", [1, 0, 0])
        images = await store.search("room E206 MUST NOT ADD LEXICAL SCORE", [0, 1, 0], modality="image")
        assert len(text) == len(images) == 1
        assert text[0]["sourceId"] == sources[0]["id"]
        assert images[0]["sourceId"] == sources[1]["id"]
        assert images[0]["sourceVersion"] == 2 and images[0]["sourceSha256"] == sources[1]["sha256"]
        assert (await store.search("", [0, 1, 0], area="other", limit=1, modality="image", outside_area=True))[0]["itemId"] == value["itemId"]
        assert await store.search("", [0, 1, 0], from_date="2026-10-26", limit=1, modality="image") == []
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            rows = await (await db.execute("SELECT processing_profile, search_terms::text, location_tokens FROM ai_documents")).fetchall()
            assert len(rows) == 3
            assert all(not terms and not locations for profile, terms, locations in rows if profile == "image-v1")
        # Same snapshot is replayable and an independent model revision may reindex every source.
        await store.upsert(value, checksum(value), vectors, deadline())
        other = Store(store.dsn, "new", "revision", 2)
        await other.upsert(value, checksum(value), {source["id"]: [1, 0] for source in sources}, deadline())
        assert len(await other.search("", [1, 0], modality="image")) == 1
        newer = snapshot(item_id=value["itemId"], version=2)
        await put(store, newer)
        assert await other.search("", [1, 0], modality="image") == []
        assert await store.search("", [0, 1, 0], modality="image") == []
    asyncio.run(run())


def test_existing_primary_key_upgrade_preserves_text_data_and_is_repeatable(store):
    async def run():
        value = snapshot()
        await put(store, value)
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            await db.execute("ALTER TABLE ai_documents DROP CONSTRAINT ai_documents_pkey")
            await db.execute("ALTER TABLE ai_documents ADD PRIMARY KEY (model_id, model_revision, dimensions, processing_profile, item_id)")
        await store.migrate()
        await store.migrate()
        assert (await store.search("ví", [1, 0, 0]))[0]["itemId"] == value["itemId"]
        full = with_images(snapshot(item_id=value["itemId"], version=2))
        await store.upsert(full, checksum(full), {source["id"]: [1, 0, 0] for source in full["sources"]}, deadline())
        assert len(await store.search("", [1, 0, 0], modality="image")) == 1
    asyncio.run(run())


def test_private_ocr_is_searchable_on_the_text_source_and_survives_description_edits(store):
    async def run():
        value = with_images(snapshot(title="Thẻ nhặt được", description="Thẻ màu xanh"), count=2)
        vectors = {value["itemId"]: [1, 0, 0],
                   value["sources"][1]["id"]: [0, 1, 0], value["sources"][2]["id"]: [0, 1, 0]}
        image_id = value["sources"][1]["id"]
        private_text = "MSSV 0012345678"
        ocr = {image_id: private_text, value["sources"][2]["id"]: private_text}
        assert await store.upsert(value, checksum(value), vectors, deadline(), ocr=ocr)
        hits = await store.search("0012345678", [1, 0, 0], strategy="lexical")
        assert len(hits) == 1 and hits[0]["itemId"] == value["itemId"]
        assert hits[0]["sourceKind"] == "text"
        assert hits[0]["sourceId"] == value["itemId"]
        assert hits[0]["sourceSha256"] == value["sources"][0]["sha256"]
        assert "0012345678" not in json.dumps(hits) and "ocr" not in hits[0]
        edited = snapshot(title="Thẻ nhặt được", description="Mô tả đã cập nhật", item_id=value["itemId"], version=2)
        edited["sources"].extend(value["sources"][1:])
        assert await store.upsert(edited, checksum(edited), vectors, deadline(), ocr=ocr)
        hits = await store.search("0012345678", [1, 0, 0], include_images=True, strategy="lexical")
        assert len(hits) == 1 and hits[0]["documentVersion"] == 2 and hits[0]["sourceKind"] == "text"
        assert hits[0]["sourceSha256"] == edited["sources"][0]["sha256"]
        text_hits = await store.search("cập nhật", [1, 0, 0], strategy="lexical")
        assert text_hits[0]["sourceKind"] == "text"
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            terms = await (await db.execute("SELECT processing_profile, search_terms::text FROM ai_documents WHERE item_id=%s", (value["itemId"],))).fetchall()
            assert "0012345678" in next(text for profile, text in terms if profile == "text-v1")
            assert all(not text for profile, text in terms if profile == "image-v1")
        tombstone = {**edited, "documentVersion": 3, "kind": "tombstone", "document": None, "sources": []}
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert await store.search("0012345678", [1, 0, 0], include_images=True) == []
    asyncio.run(run())


def test_ocr_projection_rejects_unbounded_unknown_or_disabled_image_sources(store):
    async def run():
        value = with_images(snapshot(), count=1)
        vectors = {source["id"]: [1, 0, 0] for source in value["sources"]}
        image_id = value["sources"][1]["id"]
        for ocr in ({value["itemId"]: "private"}, {str(uuid4()): "unknown"}, {image_id: "x" * 3001}, {image_id: True}):
            with pytest.raises(ValueError, match="OCR"):
                await store.upsert(value, checksum(value), vectors, deadline(), ocr=ocr)
        with pytest.raises(ValueError, match="OCR"):
            await store.upsert(value, checksum(value), {value["itemId"]: [1, 0, 0]}, deadline(), text_only=True, ocr={image_id: "MSSV"})
        assert await store.search("private", [1, 0, 0], include_images=True) == []
    asyncio.run(run())


def test_text_only_projection_advances_full_snapshot_and_can_replay_with_image_vectors(store):
    async def run():
        old = snapshot()
        await put(store, old)
        full = with_images(snapshot(item_id=old['itemId'], version=2))
        snapshot_hash = checksum(full)
        text_vectors = {full['itemId']: [1, 0, 0]}
        assert await store.upsert(full, snapshot_hash, text_vectors, deadline(), text_only=True)
        hits = await store.search('ví', [1, 0, 0])
        assert len(hits) == 1 and hits[0]['documentVersion'] == 2
        assert hits[0]['sourceId'] == full['itemId'] and hits[0]['sourceVersion'] == 2
        assert hits[0]['sourceSha256'] == full['sources'][0]['sha256']
        assert await store.search('', [1, 0, 0], modality='image') == []
        async with await psycopg.AsyncConnection.connect(store.dsn) as db:
            row = await (await db.execute('SELECT document_version, snapshot_sha256 FROM ai_items WHERE item_id = %s',
                (full['itemId'],))).fetchone()
            assert row == (2, snapshot_hash)
        vectors = {source['id']: [1, 0, 0] for source in full['sources']}
        assert await store.upsert(full, snapshot_hash, vectors, deadline())
        assert len(await store.search('', [1, 0, 0], modality='image')) == 1
        tombstone = {'itemId': full['itemId'], 'documentVersion': 3, 'sources': [], 'document': None, 'kind': 'tombstone'}
        assert await store.remove(tombstone, checksum(tombstone), deadline())
        assert not await store.upsert(full, snapshot_hash, text_vectors, deadline(), text_only=True)
        assert not await store.upsert(full, snapshot_hash, vectors, deadline())
        assert await store.search('ví', [1, 0, 0]) == []
        assert await store.search('', [1, 0, 0], modality='image') == []
    asyncio.run(run())


@pytest.mark.parametrize('text_only', [False, True])
def test_bad_later_source_rolls_back_watermark_and_keeps_previous_projection(store, text_only):
    async def run():
        old = snapshot()
        await put(store, old)
        invalid = with_images(snapshot(item_id=old["itemId"], version=2), count=1)
        invalid["sources"][1]["processingProfile"] = "unknown-profile"
        with pytest.raises(ValueError):
            await store.upsert(invalid, checksum(invalid), {source["id"]: [1, 0, 0] for source in invalid["sources"]
                if not text_only or source["kind"] == "text"}, deadline(), text_only=text_only)
        result = await store.search("ví", [1, 0, 0])
        assert len(result) == 1 and result[0]["documentVersion"] == 1
        assert result[0]["sourceSha256"] == old["sources"][0]["sha256"]
    asyncio.run(run())


def test_area_scopes_filter_text_and_image_candidates_before_ranking(store):
    async def run():
        local = with_images(snapshot(area="Đường Quang Trung"), count=1)
        outside = with_images(snapshot(area="Trường Đại học Sài Gòn, Chợ Quán"), count=1)
        for value in (local, outside):
            await store.upsert(value, checksum(value),
                {source["id"]: [1, 0, 0] for source in value["sources"]}, deadline())
        for modality in ("text", "image"):
            for outside_area, expected in ((False, local), (True, outside)):
                hits = await store.search("ví", [1, 0, 0], area="quang trung", modality=modality,
                                          outside_area=outside_area, include_similarity=True)
                assert [hit["itemId"] for hit in hits] == [expected["itemId"]]
                assert hits[0]["similarity"] == pytest.approx(1)
                assert await store.search("ví", [1, 0, 0], area="quang trung", from_date="2026-10-26",
                                          modality=modality, outside_area=outside_area) == []
    asyncio.run(run())


def test_area_filter_precedes_channel_pool_limit_and_keeps_actual_cosine(store):
    async def run():
        local = with_images(snapshot(title="Bình nước", description="Bình trắng",
                                     area="Đường Quang Trung"), count=1)
        await store.upsert(local, checksum(local),
            {source["id"]: [0.1, 0.9, 0] for source in local["sources"]}, deadline())
        outside_ids = set()
        for _ in range(31):
            outside = with_images(snapshot(area="Chợ Quán"), count=1)
            outside_ids.add(outside["itemId"])
            await store.upsert(outside, checksum(outside),
                {source["id"]: [1, 0, 0] for source in outside["sources"]}, deadline())
        for modality in ("text", "image"):
            hits = await store.search("ví", [1, 0, 0], area="quang trung", limit=10,
                                      modality=modality, include_similarity=True)
            assert [hit["itemId"] for hit in hits] == [local["itemId"]]
            assert hits[0]["similarity"] == pytest.approx(0.1 / (0.1 ** 2 + 0.9 ** 2) ** 0.5)
            outside = await store.search("ví", [1, 0, 0], area="quang trung", limit=10,
                                         modality=modality, outside_area=True)
            assert len(outside) == 10
            assert all(hit["itemId"] in outside_ids for hit in outside)
    asyncio.run(run())
