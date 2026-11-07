import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image

from findie_ai.config import Settings
from findie_ai.contracts import BatchSearchMetadata, ImageEmbeddingMetadata, Query, RedactMetadata, SearchMetadata, Snapshot
from findie_ai.ollama import EmbeddingInputRejected, ModelUnavailable
from findie_ai.worker import Worker


SETTINGS = Settings(service_token='test', revision='a' * 64, redaction_revision='b' * 64, dimensions=2)


@pytest.fixture
def embedding_cache(monkeypatch):
    entries = {}

    async def save(key, value, *, ex):
        assert ex == 300
        entries[key] = value

    client = SimpleNamespace(get=AsyncMock(side_effect=entries.get), set=AsyncMock(side_effect=save),
                             aclose=AsyncMock())
    monkeypatch.setattr("findie_ai.search_cache.Redis.from_url", lambda *_args, **_kwargs: client)
    return entries


def encode(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()


def metadata(**extra):
    return {'schemaVersion': 1, 'modelId': SETTINGS.model_id, 'modelRevision': SETTINGS.revision,
            'deadlineAt': (datetime.now(timezone.utc) + timedelta(seconds=25)).isoformat(), **extra}


def query_metadata(**extra):
    return metadata(processingProfile='text-v1', searchProfileId=SETTINGS.search_profile,
                    searchProfileVersion=1, mode='text', area=None, **{'from': None}, until=None,
                    limit=10, candidateLimit=15) | extra


def test_redaction_accepts_five_minute_deadlines_and_rejects_expired_or_excessive_ones():
    value = metadata(modelId=SETTINGS.redaction_model, modelRevision='b' * 64,
                     imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
                     sourceSha256='a' * 64, processingProfile='redact-v4')
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert 299 < RedactMetadata.model_validate(value | {'deadlineAt': deadline}).remaining() <= 300
    with pytest.raises(ValueError, match='processingProfile'):
        RedactMetadata.model_validate(value | {'processingProfile': 'redact-v2'})
    with pytest.raises(ValueError, match='deadline_too_long'):
        SearchMetadata.model_validate(query_metadata(deadlineAt=deadline)).remaining()
    for seconds, error, message in ((306, ValueError, 'deadline_too_long'), (-1, TimeoutError, 'deadline_expired')):
        deadline = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        with pytest.raises(error, match=message):
            RedactMetadata.model_validate(value | {'deadlineAt': deadline}).remaining()


def test_ocr_image_operations_allow_five_minutes_but_text_and_index_budgets_stay_short():
    deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    image = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
        sourceSha256="a" * 64, dimensions=2, processingProfile="image-v1", deadlineAt=deadline)
    assert 299 < ImageEmbeddingMetadata.model_validate(image).remaining() <= 300
    query = query_metadata(mode="image", processingProfile="image-v1", deadlineAt=deadline)
    assert 299 < SearchMetadata.model_validate(query).remaining() <= 300
    with pytest.raises(ValueError, match="deadline_too_long"):
        SearchMetadata.model_validate(query_metadata(deadlineAt=deadline)).remaining()


def snapshot():
    item_id = str(uuid4())
    title, description = 'Ví đen', 'Nhặt tại phòng E.205'
    return {'schemaVersion': 1, 'itemId': item_id, 'documentVersion': 1, 'kind': 'snapshot',
            'document': {'title': title, 'publicDescription': description, 'foundArea': 'Đại học Sài Gòn',
                         'foundTimePrecision': 'unknown', 'foundOn': None, 'foundFrom': None,
                         'foundUntil': None, 'foundTimezone': 'Asia/Ho_Chi_Minh',
                         'custody': {'kind': 'person', 'displayName': 'Người nhặt'}},
            'sources': [{'kind': 'text', 'id': item_id, 'version': 1,
                         'sha256': hashlib.sha256((title + '\n' + description).encode()).hexdigest(),
                         'processingProfile': 'text-v1'}]}


def index_metadata(value, body):
    return metadata(jobId=str(uuid4()), leaseToken=str(uuid4()), itemId=value['itemId'],
                    documentVersion=value['documentVersion'], snapshotSha256=hashlib.sha256(body).hexdigest(), dimensions=2)


class Message:
    def __init__(self, kind, meta, body, *, durable=False):
        self.type, self.body, self.content_type = kind, body, 'application/json'
        self.headers = {'metadata': encode(meta)}
        self.correlation_id = str(uuid4())
        self.reply_to = SETTINGS.result_queue if durable else 'amq.gen-unit-test'
        self.processed = False
        self.locked = False
        self.events = []

    async def ack(self):
        self.processed = True
        self.locked = True
        self.events.append('ack')

    async def reject(self, requeue=False):
        assert requeue is False
        self.processed = True
        self.locked = True
        self.events.append('reject')


def test_ack_after_commit_and_confirmed_receipt_and_unroutable_is_not_success():
    async def run():
        worker = Worker(SETTINGS)
        value = snapshot()
        body = encode(value)
        message = Message('index.upsert', index_metadata(value, body), body, durable=True)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])

        async def commit(*_args, **_kwargs):
            message.events.append('commit')
            return True

        async def publish(reply, **kwargs):
            assert not message.processed and kwargs['mandatory'] is True
            assert json.loads(reply.headers['metadata'])['committed'] is True
            message.events.append('confirmed')

        worker.store.upsert = commit
        worker.publisher = SimpleNamespace(default_exchange=SimpleNamespace(publish=publish))
        try:
            await worker.handle(message, 'index')
            assert message.events == ['commit', 'confirmed', 'ack']
            message.events.clear()
            message.processed = False
            message.locked = False
            message.body = body
            worker.publisher.default_exchange.publish = AsyncMock(side_effect=RuntimeError('unroutable'))
            await worker.handle(message, 'index')
            assert message.events == ['commit', 'reject']
        finally:
            await worker.close()
    asyncio.run(run())


def test_expired_query_model_mismatch_and_disabled_image_query_do_not_call_model_or_store():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        try:
            body = encode({'text': 'ví E.205', 'area': None, 'from': None, 'until': None})
            expired = query_metadata(deadlineAt=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
            await worker.handle(Message('search.hybrid', expired, body), 'query')
            await worker.handle(Message('search.hybrid', query_metadata(modelRevision='b' * 64), body), 'query')
            message = Message('search.hybrid.image', query_metadata(mode='image', processingProfile='image-v1',
                searchProfileId=SETTINGS.image_search_profile), png())
            message.content_type = 'image/png'
            await worker.handle(message, 'image')
            worker.ollama.embed.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
            assert all(call.args[2] is False for call in worker.reply.await_args_list)
        finally:
            await worker.close()
    asyncio.run(run())


def test_raw_failure_drops_body_and_never_routes_to_command_queue():
    async def run():
        worker = Worker(SETTINGS)
        worker.reply = AsyncMock(side_effect=RuntimeError('reply disappeared'))
        try:
            message = Message('image.redact', metadata(), b'raw')
            await worker.handle(message, 'image')
            assert message.events == ['ack']
            message = Message('search.hybrid', query_metadata(), b'{}')
            message.reply_to = SETTINGS.index_queue
            worker.reply.reset_mock()
            await worker.handle(message, 'query')
            assert message.events == ['ack']
            worker.reply.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_public_contract_rejects_private_fields_hash_mismatch_and_blank_query():
    value = snapshot()
    assert 'E.205' in Snapshot.model_validate(value).embedding_text()
    value['document']['privateAnswers'] = ['private']
    with pytest.raises(ValueError):
        Snapshot.model_validate(value)
    value = snapshot()
    value['sources'][0]['sha256'] = 'b' * 64
    with pytest.raises(ValueError):
        Snapshot.model_validate(value)
    with pytest.raises(ValueError):
        Query.model_validate({'text': '   '})
    value = snapshot()
    value['schemaVersion'] = True
    with pytest.raises(ValueError):
        Snapshot.model_validate(value)


def png():
    output = BytesIO()
    with Image.new("RGB", (12, 12), (255, 0, 0)) as image:
        image.save(output, format="PNG")
    return output.getvalue()


def image_job(*, image_count=2, seconds=25):
    value = snapshot()
    raw = png()
    sources = [{"kind": "image", "id": str(uuid4()), "version": 2,
                "sha256": hashlib.sha256(raw).hexdigest(), "processingProfile": "image-v1"}
               for _ in range(image_count)]
    value["sources"].extend(sources)
    body = encode(value)
    meta = index_metadata(value, body)
    meta["deadlineAt"] = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    manifest = Message("index.upsert", meta, body, durable=True)
    parts = []
    for source in sources:
        part = Message("index.source.image", meta | {
            "sourceId": source["id"], "sourceVersion": source["version"],
            "sourceSha256": source["sha256"], "processingProfile": "image-v1",
        }, raw, durable=True)
        part.content_type, part.correlation_id = "image/png", manifest.correlation_id
        parts.append(part)
    return value, manifest, parts


def vector_part(part, *, payload=None):
    meta = json.loads(part.headers["metadata"])
    cached = {"modelId": meta["modelId"], "modelRevision": meta["modelRevision"],
              "dimensions": meta["dimensions"], "sourceSha256": "c" * 64, "vector": [0, 1]}
    body = encode(cached if payload is None else payload)
    message = Message("index.source.vector", meta | {"payloadSha256": hashlib.sha256(body).hexdigest()}, body, durable=True)
    message.correlation_id = part.correlation_id
    return message


@pytest.mark.parametrize(("enabled", "omit_ocr"), [(True, False), (True, True), (False, False)])
def test_original_image_embedding_is_transient_and_never_uses_redacted_pixels(enabled, omit_ocr):
    async def run():
        from findie_ai.images import normalize

        worker = Worker(replace(SETTINGS, image_search_enabled=enabled))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.read_text = AsyncMock(return_value={"text": "MSSV 001234", "hasUnclearText": False})
        worker.ollama.detect_regions = AsyncMock()
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        raw = png()
        meta = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest(), dimensions=2, processingProfile="image-v1")
        if omit_ocr:
            meta["omitOcr"] = True
        message = Message("image.embed", meta, raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            result = worker.reply.await_args.args
            assert result[2] is True
            if enabled:
                normalized = await normalize(raw, "image/png")
                worker.ollama.embed_image.assert_awaited_once_with(normalized)
                expected = {"modelId": SETTINGS.model_id, "modelRevision": SETTINGS.revision,
                    "dimensions": 2, "sourceSha256": meta["sourceSha256"], "vector": [0, 1]}
                if omit_ocr:
                    worker.ollama.read_text.assert_not_awaited()
                else:
                    worker.ollama.read_text.assert_awaited_once_with(normalized)
                    expected["ocr"] = {"text": "MSSV 001234", "hasUnclearText": False,
                        "modelId": SETTINGS.redaction_model, "modelRevision": SETTINGS.redaction_revision,
                        "processingProfile": "ocr-v1"}
                assert result[3] == expected
            else:
                worker.ollama.embed_image.assert_not_awaited()
                worker.ollama.read_text.assert_not_awaited()
                assert result[3] is None
            worker.ollama.detect_regions.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["hash", "dimensions", "model", "inference"])
def test_original_embedding_failure_drops_raw_bytes_without_persisting_or_redacting(failure):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed_image = AsyncMock(side_effect=RuntimeError("unavailable"))
        worker.ollama.read_text = AsyncMock(return_value={"text": "", "hasUnclearText": False})
        worker.reply = AsyncMock(side_effect=RuntimeError("reply unavailable"))
        raw = png()
        meta = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest(), dimensions=2, processingProfile="image-v1")
        if failure == "hash":
            meta["sourceSha256"] = "a" * 64
        elif failure == "dimensions":
            meta["dimensions"] = 3
        elif failure == "model":
            meta["modelRevision"] = "b" * 64
        message = Message("image.embed", meta, raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert not worker.pending
            if failure != "inference":
                worker.ollama.embed_image.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_ocr_failure_does_not_silently_lose_searchable_text_on_upload():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.read_text = AsyncMock(side_effect=RuntimeError("invalid transcription"))
        worker.ollama.embed_image = AsyncMock()
        worker.reply = AsyncMock()
        raw = png()
        meta = metadata(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest(), dimensions=2, processingProfile="image-v1")
        message = Message("image.embed", meta, raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert worker.reply.await_args.args[2] is False
            worker.ollama.embed_image.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("corruption", [None, "profile", "model", "revision", "length", "unclear", "extra"])
def test_cached_ocr_is_bound_to_approved_image_and_validated_before_indexing(corruption):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.ollama.read_text = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job(image_count=1)
        payload = json.loads(vector_part(parts[0]).body)
        ocr = {"text": "MSSV 001234", "hasUnclearText": False, "modelId": SETTINGS.redaction_model,
               "modelRevision": SETTINGS.redaction_revision, "processingProfile": "ocr-v1"}
        if corruption == "profile":
            ocr["processingProfile"] = "unknown"
        elif corruption == "model":
            ocr["modelId"] = "other"
        elif corruption == "revision":
            ocr["modelRevision"] = "c" * 64
        elif corruption == "length":
            ocr["text"] = "x" * 3001
        elif corruption == "unclear":
            ocr["hasUnclearText"] = "false"
        elif corruption == "extra":
            ocr["privateInstructions"] = "unexpected"
        part = vector_part(parts[0], payload=payload | {"ocr": ocr})
        try:
            await worker.handle(manifest, "index")
            worker.ollama.embed.assert_not_awaited()
            await worker.handle(part, "index")
            worker.ollama.embed_image.assert_not_awaited()
            worker.ollama.read_text.assert_not_awaited()
            assert worker.reply.await_args.args[2] is (corruption is None)
            if corruption is None:
                assert worker.store.upsert.await_args.kwargs == {"text_only": False,
                    "ocr": {value["sources"][1]["id"]: "MSSV 001234"}}
                worker.ollama.embed.assert_awaited_once_with(
                    Snapshot.model_validate(value).embedding_text() + "\nOCR ảnh:\nMSSV 001234")
            else:
                worker.ollama.embed.assert_not_awaited()
                worker.store.upsert.assert_not_awaited()
            assert not worker.pending and part.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("error", [None, EmbeddingInputRejected, ModelUnavailable])
def test_index_combines_ocr_in_manifest_order_and_retries_only_rejected_input(error):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(side_effect=[error("test"), [1, 0]] if error else None, return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job()
        texts = ["MSSV 001234", "CCCD 00008765"]
        for index, part in enumerate(parts):
            payload = json.loads(vector_part(part).body)
            payload["ocr"] = {"text": texts[index], "hasUnclearText": False,
                              "modelId": SETTINGS.redaction_model, "modelRevision": SETTINGS.redaction_revision,
                              "processingProfile": "ocr-v1"}
            parts[index] = vector_part(part, payload=payload)
        try:
            await worker.handle(parts[1], "index")
            await worker.handle(manifest, "index")
            worker.ollama.embed.assert_not_awaited()
            await worker.handle(parts[0], "index")
            public_text = Snapshot.model_validate(value).embedding_text()
            expected_inputs = [public_text + "\nOCR ảnh:\n" + "\n".join(texts)]
            if error is EmbeddingInputRejected:
                expected_inputs.append(public_text)
            assert [call.args[0] for call in worker.ollama.embed.await_args_list] == expected_inputs
            worker.ollama.embed_image.assert_not_awaited()
            if error is ModelUnavailable:
                worker.store.upsert.assert_not_awaited()
                assert worker.reply.await_args.args[2] is False
            else:
                worker.store.upsert.assert_awaited_once()
                assert list(worker.store.upsert.await_args.kwargs["ocr"].values()) == texts
                assert worker.store.upsert.await_args.args[2] == {
                    value["itemId"]: [1, 0], **{source["id"]: [0, 1] for source in value["sources"][1:]},
                }
                assert worker.reply.await_args.args[2] is True
        finally:
            await worker.close()
    asyncio.run(run())


def test_index_caps_only_the_appended_ocr_at_the_gateway_character_limit():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        public_text = "mô tả " * 850
        document = SimpleNamespace(embedding_text=lambda: public_text)
        ocr = {str(uuid4()): "a" * 3000 for _ in range(5)}
        try:
            await worker.embed_index_text(document, ocr)
            combined = worker.ollama.embed.await_args.args[0]
            assert combined.startswith(public_text + "\nOCR ảnh:\n")
            assert len(combined) == 20000 and sum(map(len, ocr.values())) == 15000
        finally:
            await worker.close()
    asyncio.run(run())


def test_text_query_includes_image_vector_sources_only_when_image_capability_is_enabled():
    async def run():
        for enabled in (False, True):
            worker = Worker(replace(SETTINGS, image_search_enabled=enabled))
            worker.ollama.embed = AsyncMock(return_value=[1, 0])
            worker.store.search = AsyncMock(return_value=[])
            try:
                await worker.execute("search.hybrid", SearchMetadata.model_validate(query_metadata()),
                    encode({"text": "MSSV 001234"}))
                kwargs = worker.store.search.await_args.kwargs
                assert kwargs["include_images"] is enabled
                worker.ollama.embed.assert_not_awaited()
                assert await kwargs["embed"]() == [1, 0]
                worker.ollama.embed.assert_awaited_once_with("MSSV 001234", query=True)
            finally:
                await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("enabled", [True, False])
def test_index_reuses_original_vectors_and_binds_them_to_approved_display_sources(enabled):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=enabled))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job(image_count=1)
        part = vector_part(parts[0])
        duplicate = vector_part(parts[0])
        try:
            await worker.handle(part, "index")
            await worker.handle(duplicate, "index")
            assert part.body == duplicate.body == b"" and not part.processed
            await worker.handle(manifest, "index")
            worker.ollama.embed_image.assert_not_awaited()
            embeddings = worker.store.upsert.await_args.args[2]
            assert embeddings[value["itemId"]] == [1, 0]
            if enabled:
                assert embeddings[value["sources"][1]["id"]] == [0, 1]
            else:
                assert len(embeddings) == 1
            assert worker.store.upsert.await_args.kwargs == {"text_only": not enabled}
            assert worker.reply.await_args.args[2] is True
            assert manifest.events == part.events == duplicate.events == ["ack"]
            assert not worker.pending
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["checksum", "source", "model", "dimensions", "nan", "zero", "bool", "extra"])
def test_invalid_cached_vector_parts_never_commit_a_projection(corruption):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        _, manifest, parts = image_job(image_count=1)
        part = vector_part(parts[0])
        payload = json.loads(part.body)
        if corruption == "model":
            payload["modelRevision"] = "b" * 64
        elif corruption == "dimensions":
            payload["dimensions"] = 3
        elif corruption == "nan":
            payload["vector"] = [float("nan"), 1]
        elif corruption == "zero":
            payload["vector"] = [0, 0]
        elif corruption == "bool":
            payload["vector"] = [True, 1]
        elif corruption == "extra":
            payload["privateText"] = "not allowed"
        part = vector_part(parts[0], payload=payload)
        if corruption == "checksum":
            part.body += b" "
        elif corruption == "source":
            meta = json.loads(part.headers["metadata"])
            part.headers["metadata"] = encode(meta | {"sourceSha256": "d" * 64})
        try:
            await worker.handle(manifest, "index")
            await worker.handle(part, "index")
            worker.store.upsert.assert_not_awaited()
            worker.ollama.embed_image.assert_not_awaited()
            assert worker.reply.await_args.args[2] is False
            assert manifest.events == part.events == ["ack"]
            assert not worker.pending and part.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


def test_conflicting_original_vector_duplicate_fails_instead_of_replacing_first_vector():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        _, manifest, parts = image_job(image_count=2)
        first = vector_part(parts[0])
        payload = json.loads(first.body)
        second = vector_part(parts[0], payload=payload | {"vector": [1, 0]})
        try:
            await worker.handle(manifest, "index")
            await worker.handle(first, "index")
            await worker.handle(second, "index")
            worker.store.upsert.assert_not_awaited()
            assert worker.reply.await_args.args[2] is False
            assert manifest.events == first.events == second.events == ["ack"]
            assert not worker.pending
        finally:
            await worker.close()
    asyncio.run(run())


def test_max_dimension_original_vectors_fit_reply_and_index_parts():
    async def run():
        settings = replace(SETTINGS, dimensions=16000, image_search_enabled=True)
        worker = Worker(settings)
        vector = [0.0078125] * settings.dimensions
        worker.ollama.embed = AsyncMock(return_value=vector)
        worker.store.upsert = AsyncMock(return_value=True)
        worker.publisher = SimpleNamespace(default_exchange=SimpleNamespace(publish=AsyncMock()))
        value, manifest, parts = image_job(image_count=1)
        meta = json.loads(manifest.headers["metadata"]) | {"dimensions": settings.dimensions}
        manifest.headers["metadata"] = encode(meta)
        part_meta = json.loads(parts[0].headers["metadata"]) | {"dimensions": settings.dimensions}
        parts[0].headers["metadata"] = encode(part_meta)
        payload = {"modelId": settings.model_id, "modelRevision": settings.revision,
                   "dimensions": settings.dimensions, "sourceSha256": "c" * 64, "vector": vector}
        part = vector_part(parts[0], payload=payload)
        assert 65536 < len(part.body) < 1024 * 1024
        try:
            request = Message("image.embed", {}, png())
            await worker.reply(request, {}, True, payload)
            published = worker.publisher.default_exchange.publish.await_args.args[0]
            assert json.loads(published.body) == payload
            await worker.handle(manifest, "index")
            await worker.handle(part, "index")
            assert worker.store.upsert.await_args.args[2][value["sources"][1]["id"]] == vector
            assert manifest.events == part.events == ["ack"]
        finally:
            await worker.close()
    asyncio.run(run())


def test_complete_image_manifest_is_atomic_with_out_of_order_parts_and_duplicate_parts():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job()
        duplicate = Message("index.source.image", json.loads(parts[0].headers["metadata"]), png(), durable=True)
        duplicate.content_type, duplicate.correlation_id = "image/png", manifest.correlation_id
        try:
            await worker.handle(parts[0], "index")
            await worker.handle(duplicate, "index")
            assert not parts[0].processed and not duplicate.processed
            assert parts[0].body == duplicate.body == b""
            await worker.handle(manifest, "index")
            worker.store.upsert.assert_not_awaited()
            worker.reply.assert_not_awaited()
            await worker.handle(parts[1], "index")
            worker.store.upsert.assert_awaited_once()
            embeddings = worker.store.upsert.await_args.args[2]
            assert set(embeddings) == {source["id"] for source in value["sources"]}
            assert worker.ollama.embed_image.await_count == 2
            worker.reply.assert_awaited_once()
            assert worker.reply.await_args.args[2] is True
            assert all(message.events == ["ack"] for message in [manifest, duplicate, *parts])
            assert not worker.pending and worker.pending_bytes == 0
        finally:
            await worker.close()
    asyncio.run(run())


def test_text_only_projection_validates_full_manifest_without_image_inference():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job()
        expected_hash = hashlib.sha256(manifest.body).hexdigest()
        try:
            await worker.handle(parts[0], 'index')
            await worker.handle(manifest, 'index')
            worker.store.upsert.assert_not_awaited()
            worker.reply.assert_not_awaited()
            await worker.handle(parts[1], 'index')
            worker.ollama.embed_image.assert_not_awaited()
            worker.store.upsert.assert_awaited_once()
            committed = worker.store.upsert.await_args
            assert committed.args[:3] == (Snapshot.model_validate(value).model_dump(mode='json'),
                                         expected_hash, {value['itemId']: [1, 0]})
            assert committed.kwargs == {'text_only': True}
            assert worker.reply.await_args.args[1]['snapshotSha256'] == expected_hash
            assert worker.reply.await_args.args[2] is True
            assert all(message.events == ['ack'] and message.body == b'' for message in [manifest, *parts])
            assert not worker.pending and worker.pending_bytes == 0
        finally:
            await worker.close()
    asyncio.run(run())


def test_text_only_projection_still_decodes_hash_matching_image_parts():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock()
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, _, _ = image_job(image_count=1)
        raw = b'not an image'
        source = value['sources'][1]
        source['sha256'] = hashlib.sha256(raw).hexdigest()
        body = encode(value)
        meta = index_metadata(value, body)
        manifest = Message('index.upsert', meta, body, durable=True)
        part = Message('index.source.image', meta | {'sourceId': source['id'], 'sourceVersion': source['version'],
            'sourceSha256': source['sha256'], 'processingProfile': 'image-v1'}, raw, durable=True)
        part.content_type, part.correlation_id = 'image/png', manifest.correlation_id
        try:
            await worker.handle(manifest, 'index')
            await worker.handle(part, 'index')
            worker.store.upsert.assert_not_awaited()
            worker.ollama.embed_image.assert_not_awaited()
            assert worker.reply.await_args.args[2] is False
            assert manifest.events == part.events == ['ack']
            assert not worker.pending and worker.pending_bytes == 0
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize('image_search_enabled', [False, True])
def test_missing_or_corrupt_image_parts_never_commit_and_expire_without_retained_bodies(image_search_enabled):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=image_search_enabled))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        try:
            _, manifest, parts = image_job(image_count=1, seconds=0.04)
            await worker.handle(manifest, "index")
            assert manifest.body == b"" and not manifest.processed
            await asyncio.sleep(0.07)
            assert manifest.events == ["ack"] and not worker.pending
            assert worker.reply.await_args.args[2] is False
            worker.store.upsert.assert_not_awaited()
            _, manifest, parts = image_job(image_count=1)
            await worker.handle(manifest, "index")
            parts[0].body = b"corrupted output"
            await worker.handle(parts[0], "index")
            worker.store.upsert.assert_not_awaited()
            worker.ollama.embed_image.assert_not_awaited()
            assert manifest.events == parts[0].events == ["ack"]
            assert worker.reply.await_args.args[2] is False
            assert not worker.pending
        finally:
            await worker.close()
    asyncio.run(run())


def test_index_assembly_has_bounded_capacity_and_rejects_cross_correlation_parts():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        try:
            jobs = [image_job(image_count=1) for _ in range(3)]
            for _, manifest, _ in jobs:
                await worker.handle(manifest, "index")
            assert len(worker.pending) == 2
            assert jobs[2][1].events == ["ack"]  # A failed receipt releases a bounded outbox retry.
            part = jobs[0][2][0]
            part.correlation_id = str(uuid4())
            receipts_before = worker.reply.await_count
            await worker.handle(part, "index")
            assert part.events == ["reject"]
            assert worker.reply.await_count == receipts_before
            worker.ollama.embed_image.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_image_query_keeps_raw_bytes_out_of_storage_and_redaction_returns_only_output():
    async def run():
        settings = replace(SETTINGS, image_search_enabled=True, redaction_revision="b" * 64)
        worker = Worker(settings)
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.read_text = AsyncMock()
        worker.ollama.detect_regions = AsyncMock(return_value=[{"label": "face", "bbox": [0, 0, 500, 500]}])
        worker.store.search = AsyncMock(return_value=[])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        try:
            raw = png()
            meta = query_metadata(mode="image", processingProfile="image-v1", searchProfileId=settings.image_search_profile)
            message = Message("search.hybrid.image", meta, raw)
            message.content_type = "image/png"
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert worker.store.search.await_args.args[0] == ""
            assert worker.store.search.await_args.kwargs == {"modality": "image", "include_similarity": True}
            assert worker.ollama.embed_image.await_args.kwargs == {}
            worker.ollama.read_text.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
            message = Message("image.redact", metadata(modelId=settings.redaction_model,
                modelRevision=settings.redaction_revision, imageId=str(uuid4()), itemId=str(uuid4()),
                sourceVersion=1, sourceSha256=hashlib.sha256(raw).hexdigest(), processingProfile="redact-v4"), raw)
            message.content_type = "image/png"
            await worker.handle(message, "image")
            response = worker.reply.await_args
            assert response.args[2] is True and response.args[3] != raw
            assert response.args[1]["sha256"] == hashlib.sha256(response.args[3]).hexdigest()
            assert message.events == ["ack"] and message.body == b""
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_deadline_during_inference_and_orphan_parts_release_each_delivery_once():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        async def slow(*_args):
            await asyncio.sleep(0.2)
            return [1, 0]
        worker.ollama.embed = AsyncMock(side_effect=slow)
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        try:
            _, manifest, parts = image_job(image_count=1, seconds=0.04)
            await worker.handle(manifest, "index")
            await worker.handle(parts[0], "index")
            worker.ollama.embed.assert_awaited_once()
            assert manifest.events == parts[0].events == ["ack"] and not worker.pending
            assert worker.reply.await_count == 1 and worker.reply.await_args.args[2] is False
            worker.reply.reset_mock()
            _, _, parts = image_job(image_count=1, seconds=0.02)
            await worker.handle(parts[0], "index")
            await asyncio.sleep(0.04)
            assert parts[0].events == ["reject"] and not worker.pending
            worker.reply.assert_not_awaited()
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_cold_readiness_allows_remote_dependencies_to_complete_within_twelve_seconds(monkeypatch):
    async def run():
        worker = Worker(SETTINGS)
        worker.connection = worker.publisher = worker.consumer = SimpleNamespace(is_closed=False)
        worker.connection.close = AsyncMock()
        worker.materials.channel = worker.connection
        worker.materials.queue = object()
        loop = asyncio.get_running_loop()
        clock = [loop.time()]
        completed = []

        async def dependency(name, seconds, result=None):
            clock[0] += seconds
            await asyncio.sleep(0)
            completed.append(name)
            return result

        worker.store.check = lambda: dependency("database", 1.25)
        worker.ollama.verify_models = lambda: dependency("models", 4)
        worker.ollama.embed = lambda *_args, **_kwargs: dependency("embedding", 3.25, [1, 0])
        try:
            with monkeypatch.context() as patch:
                patch.setattr(loop, "time", lambda: clock[0])
                assert await worker.probe()
            assert completed == ["database", "models", "embedding"]
            assert worker.last_embedding_success is not None
        finally:
            await worker.close()
    asyncio.run(run())


def test_readiness_does_not_queue_inference_behind_a_busy_model_after_warmup():
    async def run():
        worker = Worker(SETTINGS)
        worker.connection = worker.publisher = worker.consumer = SimpleNamespace(is_closed=False)
        worker.connection.close = AsyncMock()
        worker.materials.channel = worker.connection
        worker.materials.queue = object()
        worker.store.check = AsyncMock()
        worker.ollama.verify_models = AsyncMock()
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        try:
            assert await worker.probe()
            worker.ollama.embed.assert_awaited_once()
            worker.last_embedding_success = time.monotonic() - 20
            async with worker.ollama.lock:
                assert await asyncio.wait_for(worker.probe(), timeout=0.1)
            worker.ollama.embed.assert_awaited_once()
            worker.store.check.assert_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_tombstone_commit_with_unconfirmed_receipt_rejects_without_false_commit_receipt():
    async def run():
        worker = Worker(SETTINGS)
        value = snapshot()
        value.update(kind="tombstone", document=None, sources=[])
        body = encode(value)
        message = Message("index.remove", index_metadata(value, body), body, durable=True)
        worker.store.remove = AsyncMock(return_value=True)
        worker.reply = AsyncMock(side_effect=[RuntimeError("unroutable"), None])
        try:
            await worker.handle(message, "index")
            worker.store.remove.assert_awaited_once()
            worker.reply.assert_awaited_once()
            assert worker.reply.await_args.args[2] is True
            assert message.events == ["reject"] and message.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


def test_reconnect_keeps_inflight_byte_reservations_until_each_callback_finishes():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        started, release_first, release_second = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0
        async def blocked(_body):
            nonlocal calls
            calls += 1
            started.set()
            await (release_first if calls == 1 else release_second).wait()
            return [0, 1]
        worker.ollama.embed_image = blocked
        tasks = []
        try:
            _, _, parts = image_job(image_count=1)
            first = asyncio.create_task(worker.handle(parts[0], "index"))
            tasks.append(first)
            await started.wait()
            worker.clear_pending()
            _, _, later_parts = image_job(image_count=1)
            second = asyncio.create_task(worker.handle(later_parts[0], "index"))
            tasks.append(second)
            await asyncio.sleep(0)
            retained_size = len(later_parts[0].body)
            assert retained_size > 0
            release_first.set()
            await first
            assert worker.pending_bytes == retained_size
            release_second.set()
            await second
            assert worker.pending_bytes == 0
        finally:
            release_first.set()
            release_second.set()
            await asyncio.gather(*tasks)
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("search_first", [False, True])
def test_upload_and_search_reuse_normalized_image_vectors_without_caching_ocr(monkeypatch, embedding_cache, search_first):
    from findie_ai import images
    from PIL.PngImagePlugin import PngInfo

    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True, redis_url="redis://127.0.0.1/0"))
        normalize = AsyncMock(wraps=images.normalize)
        monkeypatch.setattr(images, "normalize", normalize)
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.read_text = AsyncMock(return_value={"text": "MSSV 001234", "hasUnclearText": False})
        worker.store.search = AsyncMock(return_value=[])
        raw = png()
        output, chunks = BytesIO(), PngInfo()
        chunks.add_text("description", "different metadata, same pixels")
        with Image.open(BytesIO(raw)) as image:
            image.save(output, format="PNG", pnginfo=chunks)
        alternate = output.getvalue()
        assert raw != alternate
        scope = uuid4()
        upload = ImageEmbeddingMetadata.model_validate(metadata(
            imageId=uuid4(), itemId=uuid4(), sourceVersion=1, sourceSha256=hashlib.sha256(raw).hexdigest(),
            dimensions=2, processingProfile="image-v1", cacheScope=scope))
        query = SearchMetadata.model_validate(query_metadata(
            mode="image", processingProfile="image-v1", searchProfileId=SETTINGS.image_search_profile,
            cacheScope=scope))
        try:
            if search_first:
                await worker.execute("search.hybrid.image", query, alternate, "image/png")
                worker.ollama.read_text.assert_not_awaited()
            posted = await worker.execute("image.embed", upload, raw, "image/png")
            assert posted["vector"] == [0, 1] and posted["ocr"]["text"] == "MSSV 001234"
            if not search_first:
                await worker.execute("search.hybrid.image", query, alternate, "image/png")
            worker.ollama.read_text.assert_awaited_once()

            duplicate = upload.model_copy(update={"imageId": uuid4(), "itemId": uuid4(), "sourceVersion": 2,
                "sourceSha256": hashlib.sha256(alternate).hexdigest()})
            repeated = await worker.execute("image.embed", duplicate, alternate, "image/png")
            assert repeated["sourceSha256"] == duplicate.sourceSha256 and repeated["vector"] == [0, 1]
            without_ocr = await worker.execute("image.embed", upload.model_copy(update={"omitOcr": True}), raw, "image/png")
            assert "ocr" not in without_ocr and worker.ollama.read_text.await_count == 2
            await worker.execute("search.hybrid.image", query.model_copy(update={"area": "Quận 5"}), raw, "image/png")
            worker.store.search.assert_awaited_with("", [0, 1], "Quận 5", None, None, 15, modality="image", include_similarity=True, outside_area=True)
            assert worker.store.search.await_count == 3
            worker.ollama.embed_image.assert_awaited_once()
            assert normalize.await_count == 5 and len(embedding_cache) == 1
            assert "MSSV" not in " ".join(embedding_cache.values())
        finally:
            await worker.close()
    asyncio.run(run())


def test_image_cache_hits_keep_input_validation_and_isolate_pixels_and_accounts(embedding_cache):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True, redis_url="redis://127.0.0.1/0"))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.read_text = AsyncMock()
        worker.store.search = AsyncMock(return_value=[])
        output = BytesIO()
        with Image.new("RGB", (256, 256), (255, 0, 0)) as image:
            image.save(output, format="PNG")
        raw, scope = output.getvalue(), uuid4()
        query = SearchMetadata.model_validate(query_metadata(
            mode="image", processingProfile="image-v1", searchProfileId=SETTINGS.image_search_profile,
            cacheScope=scope))
        upload = ImageEmbeddingMetadata.model_validate(metadata(
            imageId=uuid4(), itemId=uuid4(), sourceVersion=1, sourceSha256=hashlib.sha256(raw).hexdigest(),
            dimensions=2, processingProfile="image-v1", cacheScope=scope, omitOcr=True))
        try:
            await worker.execute("search.hybrid.image", query, raw, "image/png")
            invalid_uploads = [(upload.model_copy(update={"sourceSha256": "f" * 64}), raw, "image/png", "source_hash_mismatch"),
                (upload, raw, "image/jpeg", "invalid_image"),
                (upload.model_copy(update={"coarsePreview": True}), raw, "image/png", "invalid_coarse_preview"),
                (upload.model_copy(update={"sourceSha256": hashlib.sha256(b"invalid").hexdigest()}),
                 b"invalid", "image/png", "invalid_image")]
            for meta, body, mime, error in invalid_uploads:
                with pytest.raises(ValueError, match=error):
                    await worker.execute("image.embed", meta, body, mime)
            for body, mime in ((raw, "image/jpeg"), (b"invalid", "image/png")):
                with pytest.raises(ValueError, match="invalid_image"):
                    await worker.execute("search.hybrid.image", query, body, mime)
            worker.ollama.embed_image.assert_awaited_once()
            worker.store.search.assert_awaited_once()
            worker.ollama.read_text.assert_not_awaited()
            assert len(embedding_cache) == 1

            output = BytesIO()
            with Image.new("RGB", (12, 12), (0, 0, 255)) as image:
                image.save(output, format="PNG")
            await worker.execute("search.hybrid.image", query, output.getvalue(), "image/png")
            assert worker.ollama.embed_image.await_count == 2
            other_account = query.model_copy(update={"cacheScope": uuid4()})
            await worker.execute("search.hybrid.image", other_account, raw, "image/png")
            assert worker.ollama.embed_image.await_count == 3 and len(embedding_cache) == 3
        finally:
            await worker.close()
    asyncio.run(run())


def test_legacy_index_reuses_duplicate_image_vectors_for_later_upload_and_search(embedding_cache):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True, redis_url="redis://127.0.0.1/0"))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.read_text = AsyncMock()
        worker.store.search = AsyncMock(return_value=[])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        value, manifest, parts = image_job(image_count=2)
        raw, scope = png(), uuid4()
        for message in [manifest, *parts]:
            message.headers["metadata"] = encode(json.loads(message.headers["metadata"]) | {"cacheScope": str(scope)})
        try:
            await worker.handle(parts[0], "index")
            await worker.handle(manifest, "index")
            await worker.handle(parts[1], "index")
            assert worker.reply.await_args.args[2] is True
            vectors = worker.store.upsert.await_args.args[2]
            assert all(vectors[source["id"]] == [0, 1] for source in value["sources"][1:])
            assert all(message.events == ["ack"] for message in [manifest, *parts])

            upload = ImageEmbeddingMetadata.model_validate(metadata(
                imageId=uuid4(), itemId=uuid4(), sourceVersion=1, sourceSha256=hashlib.sha256(raw).hexdigest(),
                dimensions=2, processingProfile="image-v1", cacheScope=scope, omitOcr=True))
            assert (await worker.execute("image.embed", upload, raw, "image/png"))["vector"] == [0, 1]
            query = SearchMetadata.model_validate(query_metadata(
                mode="image", processingProfile="image-v1", searchProfileId=SETTINGS.image_search_profile,
                cacheScope=scope))
            await worker.execute("search.hybrid.image", query, raw, "image/png")
            worker.ollama.embed_image.assert_awaited_once()
            worker.ollama.read_text.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("instruction", ["", SETTINGS.query_instruction])
def test_text_embedding_cache_respects_the_index_and_search_model_inputs(instruction, embedding_cache):
    async def run():
        worker = Worker(replace(SETTINGS, query_instruction=instruction, redis_url="redis://127.0.0.1/0"))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.store.upsert = AsyncMock(return_value=True)
        worker.reply = AsyncMock()
        scope = uuid4()
        value = snapshot()
        text = Snapshot.model_validate(value).embedding_text()
        body = encode(value)
        manifest = Message("index.upsert", index_metadata(value, body) | {"cacheScope": str(scope)}, body, durable=True)

        async def search(_text, _vector, _area, *_args, embed, **_kwargs):
            assert await embed() == [1, 0]
            return []

        worker.store.search = AsyncMock(side_effect=search)
        try:
            await worker.handle(manifest, "index")
            worker.store.upsert.assert_awaited_once()
            assert worker.reply.await_args.args[2] is True
            worker.ollama.embed.assert_awaited_once_with(text)

            for area in ("Quận 1", "Quận 5"):
                query = SearchMetadata.model_validate(query_metadata(area=area, cacheScope=scope))
                await worker.execute("search.hybrid", query, encode({"text": text, "area": area}))
            assert [call.args[2] for call in worker.store.search.await_args_list] == ["Quận 1", "Quận 1", "Quận 5", "Quận 5"]
            assert worker.ollama.embed.await_count == (2 if instruction else 1)
            if instruction:
                worker.ollama.embed.assert_awaited_with(text, query=True)
        finally:
            await worker.close()
    asyncio.run(run())


def test_reviewed_coordinates_use_full_local_masks_without_vision_inference():
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.detect_regions = AsyncMock(side_effect=AssertionError("reviewed coordinates must not be inferred again"))
        buffer = BytesIO()
        Image.new("RGB", (100, 80), "white").save(buffer, format="PNG")
        body = buffer.getvalue()
        regions = [{"label": "identity_number", "bbox": [200, 250, 800, 750]}]
        meta = RedactMetadata.model_validate(metadata(modelId=SETTINGS.redaction_model,
            modelRevision=SETTINGS.redaction_revision, imageId=str(uuid4()), itemId=str(uuid4()),
            sourceVersion=1, sourceSha256=hashlib.sha256(body).hexdigest(), processingProfile="redact-v4", reviewedRegions=regions))
        try:
            output, details = await worker.execute("image.redact", meta, body, "image/png")
            with Image.open(BytesIO(output)) as image:
                assert image.getpixel((75, 40)) == (0, 0, 0)
                assert image.getpixel((5, 5)) == (255, 255, 255)
            assert details["sensitiveRegions"] == regions
            worker.ollama.detect_regions.assert_not_called()
            with pytest.raises(ValueError, match="conflicting_redaction_modes"):
                RedactMetadata.model_validate(meta.model_dump() | {"coarsePreview": True})
        finally:
            await worker.ollama.close()
    asyncio.run(run())


def batch_metadata(*, count=2, text="ví đen", **extra):
    return query_metadata(
        processingProfile="multimodal-v1", mode="combined" if text and text.strip() else "image",
        searchProfileId="multimodal-fusion-v1" if text and text.strip() else "image-fusion-v1",
        deadlineAt=(datetime.now(timezone.utc) + timedelta(seconds=940)).isoformat(),
        images=[{"contentType": "image/png", "length": len(png())}] * count, text=text) | extra


@pytest.mark.parametrize("extra", [
    {"images": []}, {"images": [{"contentType": "image/png", "length": 1}] * 4},
    *({"images": [{"contentType": "image/png", "length": value}]} for value in (0, True, 10 * 1024 * 1024 + 1)),
    {"images": [{"contentType": "application/octet-stream", "length": 1}]},
    {"text": "x" * 2001}, {"text": " ", "mode": "combined", "searchProfileId": "multimodal-fusion-v1"},
    {"mode": "text"}, {"processingProfile": "text-v1"},
    {"searchProfileId": "image-fusion-v1"}, {"from": "2026-11-02", "until": "2026-11-01"},
    {"candidateLimit": 21}, {"limit": 11},
])
def test_batch_search_contract_rejects_invalid_framing_modes_and_filters(extra):
    with pytest.raises(ValueError):
        BatchSearchMetadata.model_validate(batch_metadata(**extra))


@pytest.mark.parametrize("limit", [0, 21, True])
def test_single_search_contract_rejects_candidate_limits_outside_pool(limit):
    with pytest.raises(ValueError):
        SearchMetadata.model_validate(query_metadata(candidateLimit=limit))


def test_batch_deadlines_and_private_query_fields_are_bounded():
    query = BatchSearchMetadata.model_validate(batch_metadata(
        deadlineAt=datetime.now(timezone.utc) + timedelta(seconds=955)))
    assert 954 < query.remaining() <= 955
    assert not {"text", "images", "cacheScope"} & query.model_dump().keys()
    for seconds, error in ((961, ValueError), (-1, TimeoutError)):
        invalid = query.model_copy(update={"deadlineAt": datetime.now(timezone.utc) + timedelta(seconds=seconds)})
        with pytest.raises(error):
            invalid.remaining()
    assert BatchSearchMetadata.model_validate(batch_metadata(text=" ")).text is None


def test_batch_search_reuses_image_and_hybrid_text_paths_then_fuses_before_reply(monkeypatch, embedding_cache):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True, redis_url="redis://127.0.0.1/0"))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.read_text = AsyncMock()
        worker.reply = AsyncMock()
        item_id, image_id = str(uuid4()), str(uuid4())
        image = {"itemId": item_id, "documentVersion": 2, "sourceId": image_id,
                 "sourceKind": "image", "sourceVersion": 1, "sourceSha256": "a" * 64}
        text = image | {"sourceId": item_id, "sourceKind": "text"}
        rankings = iter([[image | {"similarity": 0.8}], [image | {"similarity": 0.8}], [text | {"similarity": 0.8}]])

        async def search(*_args, **kwargs):
            if "embed" in kwargs:
                assert await kwargs["embed"]() == [1, 0]
            return next(rankings)

        worker.store.search = AsyncMock(side_effect=search)
        timeouts, original_timeout = [], asyncio.timeout

        def timeout(seconds):
            timeouts.append(seconds)
            return original_timeout(seconds)

        monkeypatch.setattr(asyncio, "timeout", timeout)
        message = Message("search.hybrid.images", batch_metadata(cacheScope=str(uuid4()), area="Quận 1"), png() * 2)
        message.content_type = "application/octet-stream"
        try:
            await worker.handle(message, "image")
            assert message.events == ["ack"] and message.body == b""
            assert worker.reply.await_count == 1 and worker.reply.await_args.args[2] is True
            candidate = worker.reply.await_args.args[3]["candidates"][0]
            assert candidate["itemId"] == item_id and candidate["score"] == pytest.approx(2.5 / 61)
            assert candidate["imageScore"] == pytest.approx(2 / 61)
            assert candidate["textScore"] == pytest.approx(0.5 / 61)
            assert {source["sourceKind"] for source in candidate["sources"]} == {"image", "text"}
            assert len(candidate["sources"]) == 2
            assert worker.store.search.await_count == 3
            assert all(call.args[2] == "Quận 1" for call in worker.store.search.await_args_list)
            worker.ollama.embed_image.assert_awaited_once()
            worker.ollama.embed.assert_awaited_once_with("ví đen", query=True)
            worker.ollama.read_text.assert_not_awaited()
            budgets = [seconds for seconds in timeouts if seconds > 1]
            assert len(budgets) == 4 and all(299 < seconds <= 300 for seconds in budgets[1:3])
            assert 29 < budgets[3] <= 30
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["length", "disabled", "lane", "mime", "branch"])
def test_batch_failures_never_return_partial_candidates_or_keep_raw_bytes(failure):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=failure != "disabled"))
        worker.reply = AsyncMock()
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.store.search = AsyncMock(side_effect=[[], ModelUnavailable("unavailable")])
        message = Message("search.hybrid.images", batch_metadata(text=None), png() * (1 if failure == "length" else 2))
        message.content_type = "image/png" if failure == "mime" else "application/octet-stream"
        try:
            await worker.handle(message, "query" if failure == "lane" else "image")
            assert message.events == ["ack"] and message.body == b""
            if failure in {"lane", "mime"}:
                worker.reply.assert_not_awaited()
            else:
                assert worker.reply.await_args.args[2:4] == (False, {})
            if failure != "branch":
                worker.ollama.embed_image.assert_not_awaited()
                worker.store.search.assert_not_awaited()
            else:
                assert worker.store.search.await_count == 2
        finally:
            await worker.close()
    asyncio.run(run())


def test_batch_image_branch_timeout_cancels_inference(monkeypatch):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        cancelled = asyncio.Event()

        async def blocked(_image):
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()

        worker.ollama.embed_image = blocked
        worker.store.search = AsyncMock()
        original_timeout = asyncio.timeout
        monkeypatch.setattr(asyncio, "timeout", lambda _seconds: original_timeout(0.01))
        try:
            with pytest.raises(TimeoutError):
                await worker.execute("search.hybrid.images", BatchSearchMetadata.model_validate(batch_metadata(count=1, text=None)),
                                     png(), "application/octet-stream")
            assert cancelled.is_set()
            worker.store.search.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["text", "image"])
@pytest.mark.parametrize("candidate_limit", [1, 20])
def test_single_search_returns_requested_bounded_candidate_pool(mode, candidate_limit):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        candidates = [{"itemId": str(uuid4()), "similarity": 0.9} for _ in range(20)]

        async def search(*args, **kwargs):
            assert args[5] == candidate_limit
            return candidates[:args[5]]

        worker.store.search = AsyncMock(side_effect=search)
        query = SearchMetadata.model_validate(query_metadata(mode=mode, processingProfile=mode + "-v1",
            searchProfileId=SETTINGS.search_profile if mode == "text" else SETTINGS.image_search_profile,
            candidateLimit=candidate_limit))
        try:
            body = encode({"text": "ví đen"}) if mode == "text" else png()
            response = await worker.execute("search.hybrid" if mode == "text" else "search.hybrid.image",
                query, body, "application/json" if mode == "text" else "image/png")
            assert [hit["itemId"] for hit in response["candidates"]] == [hit["itemId"] for hit in candidates[:candidate_limit]]
            assert all(hit["relevanceScore"] == 0.9 for hit in response["candidates"])
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("reply_limit", [15, 20])
def test_batch_limits_reply_after_fusion_without_truncating_internal_rankings(reply_limit):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        shared_id = str(uuid4())

        def candidate(item_id, kind):
            return {"itemId": item_id, "documentVersion": 1, "sourceId": item_id if kind == "text" else str(uuid4()),
                    "sourceKind": kind, "sourceVersion": 1, "sourceSha256": "a" * 64, "similarity": 0.9}

        image_hits = [candidate(str(uuid4()), "image") for _ in range(15)] + [candidate(shared_id, "image")]
        text_hits = [candidate(str(uuid4()), "text") for _ in range(15)] + [candidate(shared_id, "text")]

        async def search(*args, **kwargs):
            assert args[5] == 20
            return image_hits if kwargs.get("modality") == "image" else text_hits

        worker.store.search = AsyncMock(side_effect=search)
        worker.reply = AsyncMock()
        message = Message("search.hybrid.images", batch_metadata(count=1, candidateLimit=reply_limit), png())
        message.content_type = "application/octet-stream"
        try:
            await worker.handle(message, "image")
            assert worker.reply.await_args.args[2] is True
            hits = worker.reply.await_args.args[3]["candidates"]
            assert len(hits) == min(reply_limit, 31) and hits[0]["itemId"] == shared_id
            assert hits[0]["score"] == pytest.approx(1.5 / 76)
            assert hits[0]["imageScore"] == pytest.approx(1 / 76)
            assert hits[0]["textScore"] == pytest.approx(0.5 / 76)
            assert len(hits[0]["sources"]) == 2
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["text", "image"])
@pytest.mark.parametrize(("score", "threshold", "expand"), [(0.59, 0.6, True), (0.6, 0.6, False),
                                                          (0.7, 0.8, True), (None, 0.6, True)])
def test_single_area_search_expands_only_below_cosine_threshold(mode, score, threshold, expand):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True,
                               min_image_similarity=threshold, min_text_similarity=threshold))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        local = [{"itemId": "local", "similarity": score}] if score is not None else []
        async def search(*args, **kwargs):
            assert args[2] == "Quang Trung" and tuple(str(value) for value in args[3:5]) == ("2026-01-01", "2026-01-02")
            if mode == "text":
                assert await kwargs["embed"]() == [1, 0]
            else:
                assert args[1] == [0, 1]
            return [{"itemId": "remote", "similarity": 0.99}] if kwargs.get("outside_area") else local.copy()
        worker.store.search = AsyncMock(side_effect=search)
        query = SearchMetadata.model_validate(query_metadata(mode=mode, processingProfile=mode + "-v1",
            searchProfileId=SETTINGS.search_profile if mode == "text" else SETTINGS.image_search_profile,
            area="Quang Trung", **{"from": "2026-01-01"}, until="2026-01-02"))
        body = Query(text="bình trắng", area=query.area, **{"from": query.from_}, until=query.until).model_dump_json(by_alias=True).encode() if mode == "text" else png()
        try:
            result = await worker.execute("search.hybrid" if mode == "text" else "search.hybrid.image", query, body,
                                          "application/json" if mode == "text" else "image/png")
            expected = ["remote"] if expand else ["local"]
            assert [hit["itemId"] for hit in result["candidates"]] == expected
            assert result["candidates"][0]["relevanceScore"] == (0.99 if expand else score)
            assert worker.store.search.await_count == 1 + expand
            (worker.ollama.embed if mode == "text" else worker.ollama.embed_image).assert_awaited_once()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize(("image_score", "text_score", "same_item", "expand"), [
    (0.6, 0.6, True, False), (0.9, 0.59, True, False), (0.59, 0.9, True, False),
    (0.1, 0.2, True, True), (0.9, 0.9, False, False),
])
def test_combined_area_search_keeps_local_results_when_either_input_matches(image_score, text_score, same_item, expand):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed = AsyncMock(return_value=[1, 0])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        def candidate(item_id, kind, similarity):
            return {"itemId": item_id, "documentVersion": 1, "sourceId": item_id + kind,
                    "sourceKind": kind, "sourceVersion": 1, "sourceSha256": "a" * 64, "similarity": similarity}
        async def search(*args, **kwargs):
            if "embed" in kwargs:
                assert await kwargs["embed"]() == [1, 0]
            kind = "image" if kwargs.get("modality") == "image" else "text"
            if kwargs.get("outside_area"):
                assert worker.store.search.await_count >= 3
                return [candidate("remote", kind, 0.99)]
            return [candidate("local" if same_item or kind == "image" else "other-local", kind,
                              image_score if kind == "image" else text_score)]
        worker.store.search = AsyncMock(side_effect=search)
        try:
            query = BatchSearchMetadata.model_validate(batch_metadata(count=1, text="bình trắng", area="Quang Trung"))
            hits = (await worker.execute("search.hybrid.images", query, png(), "application/octet-stream"))["candidates"]
            assert any(hit["itemId"] == "remote" for hit in hits) is expand
            assert worker.store.search.await_count == (4 if expand else 2)
            assert len({hit["itemId"] for hit in hits}) == len(hits)
            assert all("similarity" not in hit and all("similarity" not in ref for ref in hit["sources"]) for hit in hits)
            worker.ollama.embed.assert_awaited_once()
            worker.ollama.embed_image.assert_awaited_once()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("with_area", [False, True])
def test_batch_union_caps_at_twenty_and_discards_weak_local_hits(with_area):
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        def hit(item_id, kind):
            return {"itemId": item_id, "documentVersion": 1, "sourceId": item_id + kind,
                    "sourceKind": kind, "sourceVersion": 1, "sourceSha256": "a" * 64, "similarity": 0.9}
        async def search(*args, **kwargs):
            assert args[5] == 20
            kind = "image" if kwargs.get("modality") == "image" else "text"
            if with_area and not kwargs.get("outside_area"):
                return [] if kind == "image" else [hit("local", kind) | {"similarity": 0.2}]
            prefix = "remote" if with_area else str(worker.store.search.await_count)
            return [hit(prefix + str(index), kind) for index in range(20)]
        worker.store.search = AsyncMock(side_effect=search)
        count = 1 if with_area else 3
        query = BatchSearchMetadata.model_validate(batch_metadata(count=count, candidateLimit=20,
            area="Quang Trung" if with_area else None))
        try:
            hits = (await worker.execute("search.hybrid.images", query, png() * count, "application/octet-stream"))["candidates"]
            assert len(hits) == len({hit["itemId"] for hit in hits}) == 20
            assert worker.store.search.await_count == 4
            if with_area:
                assert all(hit["itemId"] != "local" for hit in hits)
                assert all(hit["imageRelevant"] and hit["textRelevant"] for hit in hits)
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("error,code", [
    (ModelUnavailable("invalid_regions"), "invalid_regions"),
    (ModelUnavailable("invalid_ocr"), "invalid_ocr"),
    (ModelUnavailable("invalid_ocr_truncated"), "invalid_ocr_truncated"),
    (ModelUnavailable("invalid_ocr_json"), "invalid_ocr_json"),
    (ModelUnavailable("invalid_ocr_too_long"), "invalid_ocr_too_long"),
    (ModelUnavailable("invalid_ocr_schema"), "invalid_ocr_schema"),
    (ModelUnavailable("invalid_ocr_private output"), "model_unavailable"),
    (ModelUnavailable("invalid_embedding"), "invalid_embedding"),
    (ModelUnavailable("private model output"), "model_unavailable"),
    (ValueError("private image data"), "processing_failed"),
    (TimeoutError(), "deadline_expired"),
])
def test_image_failure_returns_only_allowlisted_diagnostics_and_discards_original(error, code):
    async def run():
        worker = Worker(SETTINGS)
        raw = png()
        message = Message("image.redact", metadata(modelId=SETTINGS.redaction_model,
            modelRevision=SETTINGS.redaction_revision, imageId=str(uuid4()), itemId=str(uuid4()),
            sourceVersion=1, sourceSha256=hashlib.sha256(raw).hexdigest(), processingProfile="redact-v4"), raw)
        message.content_type = "image/png"
        worker.execute = AsyncMock(side_effect=error)
        worker.reply = AsyncMock()
        try:
            await worker.handle(message, "image")
            assert worker.reply.await_args.args[2:] == (False, {}, code)
            assert message.body == b"" and message.events == ["ack"]
        finally:
            await worker.close()
    asyncio.run(run())


def test_recovered_truncated_ocr_preserves_searchable_lines_and_runs_redaction_separately():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=True))
        worker.ollama._json = AsyncMock(side_effect=[
            {"models": [{"name": SETTINGS.redaction_model, "digest": SETTINGS.redaction_revision}]},
            {"model": SETTINGS.redaction_model, "done": True, "done_reason": "length",
             "response": '{"text":"SAMPLE ID 001234\\nSAMPLE DATE 01/01/2000\\nUNFINISHED 00'},
            {"models": [{"name": SETTINGS.redaction_model, "digest": SETTINGS.redaction_revision}]},
        ])
        worker.ollama.embed_image = AsyncMock(return_value=[0, 1])
        worker.ollama.detect_regions = AsyncMock(return_value=[{"label": "face", "bbox": [0, 0, 500, 500]}])
        worker.store.upsert = AsyncMock()
        worker.reply = AsyncMock()
        raw = png()
        identity = dict(imageId=str(uuid4()), itemId=str(uuid4()), sourceVersion=1,
            sourceSha256=hashlib.sha256(raw).hexdigest())
        message = Message("image.embed", metadata(**identity, dimensions=2, processingProfile="image-v1"), raw)
        message.content_type = "image/png"
        try:
            await worker.handle(message, "image")
            result = worker.reply.await_args.args
            assert result[2] is True
            assert result[3]["ocr"] == {"text": "SAMPLE ID 001234\nSAMPLE DATE 01/01/2000", "hasUnclearText": True,
                "modelId": SETTINGS.redaction_model, "modelRevision": SETTINGS.redaction_revision, "processingProfile": "ocr-v1"}
            assert result[3]["vector"] == [0, 1]
            assert message.body == b"" and message.events == ["ack"]
            worker.ollama.detect_regions.assert_not_awaited()
            assert worker.ollama._json.await_count == 3
            redaction = Message("image.redact", metadata(**identity, modelId=SETTINGS.redaction_model,
                modelRevision=SETTINGS.redaction_revision, processingProfile="redact-v4"), raw)
            redaction.content_type = "image/png"
            await worker.handle(redaction, "image")
            result = worker.reply.await_args.args
            assert result[2] is True and result[3] != raw
            assert result[1]["sensitiveRegions"] == [{"label": "face", "bbox": [0, 0, 500, 500]}]
            assert redaction.body == b"" and redaction.events == ["ack"]
            worker.store.upsert.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())
