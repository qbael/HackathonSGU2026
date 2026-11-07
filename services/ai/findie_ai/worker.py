"""Bounded AMQP indexing, image processing and search; input images stay in RAM."""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import random
import ssl
import time
from uuid import UUID

import aio_pika

from . import images
from .contracts import (BatchSearchMetadata, ImageEmbeddingMetadata, IndexImageMetadata, IndexMetadata, IndexVectorMetadata,
                        OriginalEmbedding, Query, RedactMetadata, SearchMetadata, Snapshot)
from .ollama import EmbeddingInputRejected, ModelUnavailable, OCR_PROFILE, Ollama
from .store import Store
from .search_cache import SearchCache
from .ranking import MAX_SEARCH_CANDIDATES, fuse_rankings
from .materials import MaterialsClient, sources as candidate_sources, thumbnail
from .quality import select_candidates
from .reranker import rerank


log = logging.getLogger(__name__)
MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_INDEX_TEXT_CHARS = 20000


class Worker:
    def __init__(self, settings):
        self.settings = settings
        self.ollama = Ollama(settings)
        self.store = Store(settings.search_dsn, settings.model_id, settings.revision, settings.dimensions,
            cache=SearchCache(settings.redis_url, settings.search_cache_ttl_seconds) if settings.redis_url else None,
            semantic_weight=settings.semantic_weight)
        self.connection = self.publisher = self.consumer = None
        self.capacity = asyncio.Semaphore(1)
        self.pending = {}
        self.pending_bytes = 0
        self.last_embedding_success = None
        self.materials = MaterialsClient(settings)

    @property
    def connected(self):
        return bool(self.connection and not self.connection.is_closed and self.publisher
                    and not self.publisher.is_closed and self.consumer and not self.consumer.is_closed
                    and self.materials.channel and not self.materials.channel.is_closed and self.materials.queue)

    async def close(self):
        self.clear_pending()
        await self.materials.close()
        if self.connection:
            await self.connection.close()
        await self.ollama.close()
        await self.store.close()

    @staticmethod
    def drop_body(message):
        if not getattr(message, "locked", False):
            message.body = b""

    def clear_pending(self):
        for state in self.pending.values():
            state["timer"].cancel()
            state["vectors"].clear()
            state["ocr"].clear()
            for message in state["messages"]:
                self.drop_body(message)
        self.pending.clear()
        # In-flight callbacks still own their byte reservations until their finally blocks run.

    async def probe(self):
        if not self.connected:
            return False
        try:
            async with asyncio.timeout(12):
                await self.store.check()
                await self.ollama.verify_models()
                needs_probe = self.last_embedding_success is None or time.monotonic() - self.last_embedding_success > 15
                if needs_probe and not self.ollama.lock.locked():
                    await self.ollama.embed("Kiểm tra kết nối tìm đồ thất lạc.", query=True)
                    self.last_embedding_success = time.monotonic()
            return self.last_embedding_success is not None
        except Exception:
            return False

    async def run(self):
        delay = 1
        while True:
            try:
                self.connection = await aio_pika.connect(
                    self.settings.rabbitmq_url, timeout=5, heartbeat=30,
                    ssl_context=ssl.create_default_context() if self.settings.rabbitmq_url.startswith("amqps:") else None,
                )
                async with self.connection:
                    self.publisher = await self.connection.channel(publisher_confirms=True, on_return_raises=True)
                    self.consumer = await self.connection.channel()
                    # Two manifests plus their five image parts must fit without waiting for ACKs.
                    await self.consumer.set_qos(prefetch_count=12)
                    index = await self.consumer.declare_queue(self.settings.index_queue, passive=True)
                    await self.consumer.declare_queue(self.settings.result_queue, passive=True)
                    query = await self.consumer.declare_queue(
                        self.settings.query_queue, exclusive=True, auto_delete=True,
                        arguments={"x-message-ttl": 45000, "x-max-length": 32, "x-max-length-bytes": 2 * 1024 * 1024},
                    )
                    image = await self.consumer.declare_queue(
                        self.settings.image_queue, exclusive=True, auto_delete=True,
                        arguments={"x-message-ttl": 955000, "x-max-length": 4, "x-max-length-bytes": 32 * 1024 * 1024},
                    )
                    await index.consume(lambda message: self.handle(message, "index"))
                    await query.consume(lambda message: self.handle(message, "query"))
                    await image.consume(lambda message: self.handle(message, "image"))
                    await self.materials.start(self.connection)
                    delay = 1
                    while self.connected:
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Broker exceptions may contain credentials; never log exception or message bodies.
                log.warning("AI broker unavailable; reconnecting.")
            finally:
                self.clear_pending()
                await self.materials.close()
                if self.connection and not self.connection.is_closed:
                    await self.connection.close()
                self.connection = self.publisher = self.consumer = None
            await asyncio.sleep(delay + random.random() / 4)
            delay = min(delay * 2, 30)

    async def cached_embedding(self, scope, input_key, embed):
        cache, key = self.store.cache, None
        if cache is not None and scope is not None:
            key = cache.key((sha256(self.settings.search_dsn.encode()).hexdigest(), str(scope),
                self.settings.model_id, self.settings.revision, self.settings.dimensions,
                self.settings.search_profile, self.settings.image_search_profile, input_key), namespace="embedding")
            if (cached := await cache.get_embedding(key, self.settings.dimensions)) is not None:
                return cached

        vector = await embed()
        self.last_embedding_success = time.monotonic()
        if key is not None:
            await cache.put_embedding(key, vector, self.settings.dimensions)
        return vector

    async def embed_text(self, text, scope, *, query=False):
        instruction = self.settings.query_instruction if query else ""
        key = ("text", instruction, sha256(text.encode()).hexdigest())
        return await self.cached_embedding(scope, key,
            lambda: self.ollama.embed(text, **({"query": True} if query else {})))

    async def embed_image(self, normalized, scope):
        return await self.cached_embedding(scope, ("image-v1", sha256(normalized).hexdigest()),
            lambda: self.ollama.embed_image(normalized))

    def identity(self, metadata):
        redaction = isinstance(metadata, RedactMetadata)
        model = self.settings.redaction_model if redaction else self.settings.model_id
        revision = self.settings.redaction_revision if redaction else self.settings.revision
        if metadata.modelId != model or metadata.modelRevision != revision:
            raise ValueError("model_configuration_mismatch")
        if isinstance(metadata, (IndexMetadata, ImageEmbeddingMetadata)) and metadata.dimensions != self.settings.dimensions:
            raise ValueError("dimension_configuration_mismatch")
        if isinstance(metadata, SearchMetadata):
            profile = self.settings.search_profile if metadata.mode == "text" else self.settings.image_search_profile
            if metadata.searchProfileId != profile:
                raise ValueError("search_profile_mismatch")
        if (isinstance(metadata, BatchSearchMetadata) or isinstance(metadata, SearchMetadata) and metadata.mode == "image") and not self.settings.image_search_enabled:
            raise ModelUnavailable("image_search_disabled")

    async def search_rankings(self, requests, *, text_index=None, query_images=None):
        rankings, prepared, vectors, preferred_ids = [], [], {}, set()
        for index, (metadata, body, content_type) in enumerate(requests):
            async with asyncio.timeout(metadata.remaining()):
                kwargs = {"include_similarity": True}
                if metadata.mode == "text":
                    query = Query.model_validate_json(body)
                    if (query.area, query.from_, query.until) != (metadata.area, metadata.from_, metadata.until):
                        raise ValueError("filter_mismatch")

                    async def embed(text=query.text, scope=metadata.cacheScope, index=index):
                        if index not in vectors:
                            vectors[index] = await self.embed_text(text, scope, query=True)
                        return vectors[index]

                    args = (query.text, None, query.area, query.from_, query.until, metadata.candidateLimit)
                    kwargs.update(include_images=self.settings.image_search_enabled, embed=embed)
                else:
                    normalized = await images.normalize(body, content_type)
                    if query_images is not None:
                        query_images.append(await asyncio.to_thread(thumbnail, normalized, "image/png"))
                    vector = await self.embed_image(normalized, metadata.cacheScope)
                    args = ("", vector, metadata.area, metadata.from_, metadata.until, metadata.candidateLimit)
                    kwargs["modality"] = "image"
                rankings.append(await self.store.search(*args, **kwargs))
                if metadata.area:
                    preferred_ids.update(hit["itemId"] for hit in rankings[-1])
                prepared.append((args, kwargs))
                metadata.remaining()

        image_matches, text_matches = set(), set()
        # shortcut: cosine thresholds need calibration on labelled queries for the deployed model.
        for index, ranking in enumerate(rankings):
            threshold = self.settings.min_text_similarity if index == text_index else self.settings.min_image_similarity
            matches = {hit["itemId"] for hit in ranking if hit.get("similarity", -1.0) >= threshold}
            (text_matches if index == text_index else image_matches).update(matches)
        confident = image_matches | text_matches
        if metadata.area and not confident:
            for ranking, (args, kwargs) in zip(rankings, prepared):
                outside = await self.store.search(*args, **kwargs, outside_area=True)
                # Weak local hits must not consume the entire pool before expansion.
                ranking[:] = outside[:args[5]]
            preferred_ids.clear()
        return rankings, preferred_ids

    async def evaluate_search(self, candidates, rankings, metadata, *, text=None, query_images=(),
                              text_index=None, preferred_ids=()):
        """Score the complete bounded pool before the API applies its display limit."""
        scores = {}
        for index, ranking in enumerate(rankings):
            kind = "text" if index == text_index else "image"
            for hit in ranking:
                values = scores.setdefault(hit["itemId"], {"image": None, "text": None})
                similarity = hit.get("similarity", -1.0)
                if values[kind] is None or similarity > values[kind]:
                    values[kind] = similarity
        candidates = [{key: value for key, value in hit.items() if key != "similarity"} for hit in candidates]
        method = "similarity_fallback"
        minimum_image, minimum_text = self.settings.min_image_similarity, self.settings.min_text_similarity
        if candidates and self.settings.reranker_revision:
            deadline = min(metadata.deadlineAt - timedelta(seconds=0.25), datetime.now(timezone.utc) + timedelta(seconds=15))
            try:
                async with asyncio.timeout(max(0, (deadline - datetime.now(timezone.utc)).total_seconds())):
                    materials = await self.materials.fetch(candidates, deadline)
                    candidates = [hit for hit in candidates if materials[hit["itemId"]].status != "stale"]
                    if any(value.status == "unavailable" for value in materials.values()):
                        raise ModelUnavailable("materials_unavailable")
                    ready = {key: value for key, value in materials.items() if value.status == "ready"}
                    model_scores = await rerank(self.ollama, self.settings, ready, text, query_images, deadline) if ready else {}
                    evaluated = []
                    for candidate in candidates:
                        refs = list(candidate_sources(candidate))
                        source = ready[candidate["itemId"]].source
                        if source not in refs:
                            refs.append(source)
                        evaluated.append(candidate | {"sources": refs})
                    candidates, scores = evaluated, model_scores
                    minimum_image, minimum_text = self.settings.rerank_min_image_score, self.settings.rerank_min_text_score
                    method = "reranker"
            except Exception as error:
                stale_ids = getattr(error, "stale_ids", ()) or getattr(error.__cause__, "stale_ids", ())
                candidates = [hit for hit in candidates if hit["itemId"] not in stale_ids]
                # Never mix an incomplete model batch with cosine scores.
                log.warning("Search reranking unavailable (%s); using similarity filtering.", type(error).__name__)
        return {"candidates": select_candidates(candidates, scores, min_image=minimum_image, min_text=minimum_text,
                    relative_ratio=self.settings.relative_score_ratio, preferred_ids=preferred_ids), "rankingMethod": method}

    async def execute(self, kind, metadata, body, content_type="application/json"):
        self.identity(metadata)
        if kind == "search.hybrid.images":
            if sum(image.length for image in metadata.images) != len(body):
                raise ValueError("image_lengths_mismatch")
            common = metadata.model_dump(mode="python", by_alias=True,
                exclude={"processingProfile", "mode", "searchProfileId"})
            common["cacheScope"] = metadata.cacheScope

            def branch(mode, payload, mime):
                seconds = 300 if mode == "image" else 30
                query = SearchMetadata.model_validate(common | {
                    "processingProfile": mode + "-v1", "mode": mode, "candidateLimit": MAX_SEARCH_CANDIDATES,
                    "searchProfileId": self.settings.image_search_profile if mode == "image" else self.settings.search_profile,
                    "deadlineAt": min(metadata.deadlineAt, datetime.now(timezone.utc) + timedelta(seconds=seconds)),
                })
                return query, payload, mime

            def requests():
                offset = 0
                for image in metadata.images:
                    yield branch("image", body[offset:offset + image.length], image.contentType)
                    offset += image.length
                if metadata.text:
                    query = Query(text=metadata.text, area=metadata.area, **{"from": metadata.from_}, until=metadata.until)
                    yield branch("text", query.model_dump_json(by_alias=True).encode(), "application/json")

            query_images = []
            text_index = len(metadata.images) if metadata.text else None
            rankings, preferred_ids = await self.search_rankings(requests(), text_index=text_index, query_images=query_images)
            weights = [1.0] * len(rankings)
            if metadata.text:
                weights[-1] = 0.5
            metadata.remaining()
            candidates = fuse_rankings(rankings, metadata.candidateLimit, weights=weights,
                text_index=text_index, preferred_ids=preferred_ids)
            return await self.evaluate_search(candidates, rankings, metadata, text=metadata.text,
                query_images=query_images, text_index=text_index, preferred_ids=preferred_ids)
        if kind == "image.embed":
            if sha256(body).hexdigest() != metadata.sourceSha256:
                raise ValueError("source_hash_mismatch")
            if metadata.coarsePreview:
                if not metadata.omitOcr:
                    raise ValueError("invalid_coarse_preview")
                normalized, _ = await asyncio.to_thread(images.coarse_preview, body, content_type)
            else:
                normalized = await images.normalize(body, content_type)
            if not self.settings.image_search_enabled:
                return None
            ocr = None if metadata.omitOcr else await self.ollama.read_text(normalized)
            vector = await self.embed_image(normalized, metadata.cacheScope)
            return OriginalEmbedding(modelId=metadata.modelId, modelRevision=metadata.modelRevision,
                dimensions=metadata.dimensions, sourceSha256=metadata.sourceSha256, vector=vector,
                ocr=None if ocr is None else {**ocr, "modelId": self.settings.redaction_model,
                     "modelRevision": self.settings.redaction_revision, "processingProfile": OCR_PROFILE}).model_dump(exclude_none=True)
        if kind == "image.redact":
            if sha256(body).hexdigest() != metadata.sourceSha256:
                raise ValueError("source_hash_mismatch")
            if metadata.coarsePreview:
                return await asyncio.to_thread(images.coarse_preview, body, content_type)
            if metadata.reviewedRegions is not None:
                return await asyncio.to_thread(images.reviewed_mask, body, content_type, metadata.reviewedRegions)
            return await images.redact(self.ollama, body, content_type)
        if kind in {"search.hybrid", "search.hybrid.image"}:
            if metadata.mode != ("text" if kind == "search.hybrid" else "image"):
                raise ValueError("search_modality_mismatch")
            query_images = []
            text_index = 0 if metadata.mode == "text" else None
            rankings, preferred_ids = await self.search_rankings([(metadata, body, content_type)],
                text_index=text_index, query_images=query_images)
            metadata.remaining()
            return await self.evaluate_search(rankings[0], rankings, metadata,
                text=Query.model_validate_json(body).text if metadata.mode == "text" else None,
                query_images=query_images, text_index=text_index, preferred_ids=preferred_ids)
        snapshot = self.snapshot(kind, metadata, body)
        if kind == "index.upsert":
            if any(source.kind == "image" for source in snapshot.sources):
                raise ValueError("image_parts_required")
            vector = await self.embed_text(snapshot.embedding_text(), metadata.cacheScope)
            committed = await self.store.upsert(snapshot.model_dump(mode="json"), metadata.snapshotSha256, vector, metadata.deadlineAt)
        else:
            committed = await self.store.remove(snapshot.model_dump(mode="json"), metadata.snapshotSha256, metadata.deadlineAt)
        if not committed:
            raise ValueError("snapshot_superseded")
        return {}

    @staticmethod
    def snapshot(kind, metadata, body):
        if sha256(body).hexdigest() != metadata.snapshotSha256:
            raise ValueError("snapshot_hash_mismatch")
        snapshot = Snapshot.model_validate_json(body)
        if (snapshot.itemId, snapshot.documentVersion, snapshot.kind) != (
                metadata.itemId, metadata.documentVersion, "snapshot" if kind == "index.upsert" else "tombstone"):
            raise ValueError("snapshot_identity_mismatch")
        return snapshot

    async def expire(self, key, state):
        await asyncio.sleep(max(0, (state["deadline"] - datetime.now(timezone.utc)).total_seconds()))
        await self.finish(key, state, TimeoutError("parts_deadline_expired"))

    async def collect(self, message, metadata):
        """Retain only bounded metadata/vectors and ACK handles between parts."""
        key = (metadata.jobId, metadata.leaseToken)
        if self.pending_bytes + len(message.body) > 60 * 1024 * 1024:
            raise ValueError("index_capacity_exhausted")
        common = (metadata.cacheScope, metadata.model_dump(
            exclude={"deadlineAt", "sourceId", "sourceVersion", "sourceSha256", "processingProfile", "payloadSha256"}))
        state = self.pending.get(key)
        if state is None:
            if len(self.pending) >= 2:
                raise ValueError("index_capacity_exhausted")
            state = {"common": common, "deadline": metadata.deadlineAt, "manifest": None,
                     "metadata": None, "parts": {}, "part_checksums": {}, "validated_parts": set(), "vectors": {}, "ocr": {}, "messages": [], "finishing": False,
                     "correlation": message.correlation_id, "reply_to": message.reply_to}
            self.pending[key] = state
            state["timer"] = asyncio.create_task(self.expire(key, state))
        if state["common"] != common or state["correlation"] != message.correlation_id or state["reply_to"] != message.reply_to:
            raise ValueError("index_part_identity_mismatch")
        if len(state["messages"]) >= 12:
            raise ValueError("index_capacity_exhausted")
        state["messages"].append(message)
        size = len(message.body)
        self.pending_bytes += size
        if metadata.deadlineAt < state["deadline"]:
            state["deadline"] = metadata.deadlineAt
            state["timer"].cancel()
            state["timer"] = asyncio.create_task(self.expire(key, state))
        try:
            if isinstance(metadata, IndexImageMetadata):
                source_id = str(metadata.sourceId)
                identity = (metadata.sourceVersion, metadata.sourceSha256, metadata.processingProfile)
                checksum = metadata.payloadSha256 if isinstance(metadata, IndexVectorMetadata) else metadata.sourceSha256
                if sha256(message.body).hexdigest() != checksum:
                    raise ValueError("source_hash_mismatch")
                cached = None
                if isinstance(metadata, IndexVectorMetadata):
                    cached = OriginalEmbedding.model_validate_json(message.body)
                    if (cached.modelId, cached.modelRevision, cached.dimensions) != (
                            metadata.modelId, metadata.modelRevision, metadata.dimensions):
                        raise ValueError("cached_embedding_identity_mismatch")
                    if cached.ocr is not None and (cached.ocr.modelId, cached.ocr.modelRevision) != (
                            self.settings.redaction_model, self.settings.redaction_revision):
                        raise ValueError("cached_ocr_identity_mismatch")
                if source_id in state["parts"]:
                    if state["parts"][source_id] != identity or state["part_checksums"][source_id] != checksum:
                        raise ValueError("source_conflict")
                    return
                if len(state["parts"]) >= 5:
                    raise ValueError("too_many_image_parts")
                state["parts"][source_id] = identity
                state["part_checksums"][source_id] = checksum
                self.validate_parts(state)
                async with asyncio.timeout(metadata.remaining()), self.capacity:
                    metadata.remaining()
                    if cached is not None:
                        if self.settings.image_search_enabled:
                            state["vectors"][source_id] = cached.vector
                            if cached.ocr is not None:
                                state["ocr"][source_id] = cached.ocr.text
                    else:
                        normalized = await images.normalize(message.body, message.content_type)
                        if self.settings.image_search_enabled:
                            state["vectors"][source_id] = await self.embed_image(normalized, metadata.cacheScope)
                state["validated_parts"].add(source_id)
            else:
                snapshot = self.snapshot("index.upsert", metadata, message.body)
                if state["manifest"] is not None:
                    return
                state["manifest"], state["metadata"] = snapshot, metadata
                self.validate_parts(state)
            if self.pending.get(key) is state:
                await self.finish(key, state)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self.finish(key, state, error)
        finally:
            self.drop_body(message)
            self.pending_bytes = max(0, self.pending_bytes - size)

    @staticmethod
    def validate_parts(state):
        if state["manifest"] is None:
            return
        expected = {str(source.id): (source.version, source.sha256, source.processingProfile)
                    for source in state["manifest"].sources if source.kind == "image"}
        if any(expected.get(source_id) != identity for source_id, identity in state["parts"].items()):
            raise ValueError("image_manifest_mismatch")

    async def embed_index_text(self, snapshot, ocr, scope=None):
        public_text = snapshot.embedding_text()
        private_text = "\n".join(text for text in ocr.values() if text.strip())
        if private_text:
            prefix = public_text + "\nOCR ảnh:\n"
            combined = prefix + private_text[:MAX_INDEX_TEXT_CHARS - len(prefix)]
            try:
                return await self.embed_text(combined, scope)
            except EmbeddingInputRejected:
                # Keep full OCR in lexical search when the gateway rejects the semantic input budget.
                pass
        return await self.embed_text(public_text, scope)

    async def finish(self, key, state, error=None):
        if self.pending.get(key) is not state or state["finishing"]:
            return
        snapshot = state["manifest"]
        if error is None:
            if snapshot is None:
                return
            images = {str(source.id) for source in snapshot.sources if source.kind == "image"}
            image_vectors = images if self.settings.image_search_enabled else set()
            if state["validated_parts"] != images or set(state["vectors"]) != image_vectors:
                return
        state["finishing"] = True
        if state["timer"] is not asyncio.current_task():
            state["timer"].cancel()
        manifest = next((message for message in state["messages"] if message.type == "index.upsert"), None)
        try:
            if error is None:
                try:
                    remaining = (state["deadline"] - datetime.now(timezone.utc)).total_seconds()
                    async with asyncio.timeout(max(0, remaining)):
                        source_ids = [str(source.id) for source in snapshot.sources]
                        ocr = {source_id: state["ocr"][source_id] for source_id in source_ids if source_id in state["ocr"]}
                        async with self.capacity:
                            vector = await self.embed_index_text(snapshot, ocr, state["metadata"].cacheScope)
                        vectors = dict(state["vectors"]) | {str(snapshot.itemId): vector}
                        committed = await self.store.upsert(snapshot.model_dump(mode="json"),
                            state["metadata"].snapshotSha256, vectors, state["deadline"],
                            text_only=not self.settings.image_search_enabled, **({"ocr": ocr} if ocr else {}))
                        if not committed:
                            raise ValueError("snapshot_superseded")
                except Exception as failure:
                    error = failure
            if manifest is None:
                raise ValueError("manifest_missing")
            code = "model_unavailable" if isinstance(error, ModelUnavailable) else "processing_failed" if error else None
            await self.reply(manifest, state["metadata"].model_dump(mode="json", by_alias=True), error is None, {}, code)
            for message in state["messages"]:
                if not message.processed:
                    self.drop_body(message)
                    await message.ack()
        except asyncio.CancelledError:
            raise
        except Exception:
            for message in state["messages"]:
                if not message.processed:
                    try:
                        self.drop_body(message)
                        await message.reject(requeue=False)
                    except Exception:
                        pass
        finally:
            self.pending.pop(key, None)
            state["vectors"].clear()
            state["ocr"].clear()
            for message in state["messages"]:
                self.drop_body(message)

    async def handle(self, message, lane):
        kind = message.type
        batch = kind == "search.hybrid.images"
        durable = lane == "index" and kind in {"index.upsert", "index.remove", "index.source.image", "index.source.vector"}
        metadata = None
        failure_reply_allowed = True
        try:
            header = message.headers.get("metadata")
            if isinstance(header, str):
                header = header.encode("utf-8")
            if not isinstance(header, (bytes, bytearray)) or len(header) > 16384 or not 0 < len(message.body) <= (30 if batch else 10) * 1024 * 1024:
                raise ValueError("invalid_message_size")
            UUID(message.correlation_id)
            if durable:
                if message.reply_to != self.settings.result_queue:
                    raise ValueError("invalid_reply_route")
            elif not message.reply_to or not message.reply_to.startswith("amq.gen-") or len(message.reply_to) > 255:
                raise ValueError("invalid_reply_route")
            image = kind in {"index.source.image", "image.embed", "image.redact", "search.hybrid.image"}
            if not ((durable and (image or message.content_type == "application/json"))
                    or lane == "query" and kind == "search.hybrid" and message.content_type == "application/json"
                    or lane == "image" and (kind in {"image.embed", "image.redact", "search.hybrid.image"} or batch)):
                raise ValueError("unsupported_operation")
            json_limit = 1024 * 1024 if kind == "index.source.vector" else 65536
            if (batch and message.content_type != "application/octet-stream"
                    or not batch and (image and message.content_type not in MIMES or not image and len(message.body) > json_limit)):
                raise ValueError("invalid_content_type_or_size")
            model = (IndexVectorMetadata if kind == "index.source.vector" else
                     IndexImageMetadata if kind == "index.source.image" else IndexMetadata if durable else
                     ImageEmbeddingMetadata if kind == "image.embed" else RedactMetadata if kind == "image.redact" else
                     BatchSearchMetadata if batch else SearchMetadata)
            metadata = model.model_validate_json(header)
            self.identity(metadata)
            remaining = metadata.remaining()
            if kind in {"index.upsert", "index.source.image", "index.source.vector"}:
                await self.collect(message, metadata)
                return
            async with asyncio.timeout(remaining):
                async with self.capacity:
                    metadata.remaining()
                    result = await self.execute(kind, metadata, message.body, message.content_type)
            response_metadata = metadata.model_dump(mode="json", by_alias=True)
            if kind == "image.redact":
                result, output_metadata = result
                response_metadata.update(output_metadata)
            failure_reply_allowed = False
            await self.reply(message, response_metadata, True, result)
            self.drop_body(message)
            await message.ack()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if message.processed:
                return
            if isinstance(metadata, IndexMetadata):
                key = (metadata.jobId, metadata.leaseToken)
                state = self.pending.get(key)
                if state is not None:
                    if message in state["messages"]:
                        await self.finish(key, state, error)
                        return
                    failure_reply_allowed = False
            if metadata is not None and kind not in {"index.source.image", "index.source.vector"} and failure_reply_allowed:
                code = "model_unavailable" if isinstance(error, ModelUnavailable) else "processing_failed"
                try:
                    await self.reply(message, metadata.model_dump(mode="json", by_alias=True), False, {}, code)
                    self.drop_body(message)
                    await message.ack()
                    return
                except Exception:
                    pass
            if not message.processed:
                try:
                    if durable:
                        self.drop_body(message)
                        await message.reject(requeue=False)
                    else:
                        self.drop_body(message)
                        await message.ack()  # Private raw/query bytes must never enter a DLQ.
                except Exception:
                    pass
        finally:
            self.drop_body(message)

    async def reply(self, message, metadata, succeeded, result, error_code=None):
        durable = message.type in {"index.upsert", "index.remove"}
        response = {**metadata, "kind": message.type, "succeeded": succeeded}
        if durable:
            response["committed"] = succeeded
        if error_code:
            response["errorCode"] = error_code
        binary = isinstance(result, bytes)
        payload = result if binary else json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        limit = 10 * 1024 * 1024 if binary else 1024 * 1024 if message.type in {
            "image.embed", "search.hybrid", "search.hybrid.image", "search.hybrid.images"} else 262144
        if len(payload) > limit:
            raise ValueError("response_too_large")
        header = json.dumps(response, separators=(",", ":"))
        if len(header.encode()) > 16384:
            raise ValueError("response_metadata_too_large")
        await self.publisher.default_exchange.publish(
            aio_pika.Message(
                payload, type=message.type, correlation_id=message.correlation_id,
                content_type=metadata["contentType"] if binary else "application/json", headers={"metadata": header},
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT if durable else aio_pika.DeliveryMode.NOT_PERSISTENT,
                expiration=60,
            ), routing_key=message.reply_to, mandatory=True, timeout=3,
        )
