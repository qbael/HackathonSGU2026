import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from findie_ai.config import Settings
from findie_ai.contracts import SavedSearchMetadata, SavedSearchQuery
from findie_ai.ollama import ModelUnavailable
from findie_ai.store import Store
from findie_ai.worker import Worker
from test_store import checksum, deadline, put, snapshot, store, with_images


SETTINGS = Settings(service_token="test", revision="a" * 64, dimensions=3, image_search_enabled=True)


def embedding(**changes):
    return {"modelId": SETTINGS.model_id, "modelRevision": SETTINGS.revision, "dimensions": 3,
            "sourceSha256": "b" * 64, "vector": [0.0, 1.0, 0.0]} | changes


def metadata(**changes):
    return SavedSearchMetadata.model_validate({"schemaVersion": 1, "modelId": SETTINGS.model_id,
        "modelRevision": SETTINGS.revision, "dimensions": SETTINGS.dimensions,
        "deadlineAt": datetime.now(timezone.utc) + timedelta(seconds=25), "cacheScope": uuid4()} | changes)


@pytest.mark.parametrize("value", [
    {}, {"text": "  "}, {"text": 5}, {"text": "a" * 2001},
    {"images": [embedding()] * 4}, {"images": [embedding(vector=[0.0, 0.0, 0.0])]},
    {"images": [embedding(vector=[float("nan"), 0.0, 0.0])]},
    {"images": [embedding(dimensions=2)]},
    {"images": [embedding(ocr={"text": "private", "hasUnclearText": False, "modelId": "ocr",
                              "modelRevision": "v1", "processingProfile": "ocr-v1"})]},
    {"text": "ví", "from": "2026-11-02", "until": "2026-11-01"},
    {"text": "ví", "until": "9999-12-31"}, {"text": "ví", "afterItemId": "invalid"},
])
def test_saved_query_rejects_invalid_or_sensitive_inputs(value):
    with pytest.raises(ValueError):
        SavedSearchQuery.model_validate(value)


def test_saved_query_trims_text_and_allows_images_without_a_description():
    assert SavedSearchQuery.model_validate({"text": "  ví đen  "}).text == "ví đen"
    assert SavedSearchQuery.model_validate({"text": " ", "images": [embedding()]}).text is None
    assert 24 < metadata().remaining() <= 25
    with pytest.raises(ValueError, match="deadline_too_long"):
        metadata(deadlineAt=datetime.now(timezone.utc) + timedelta(seconds=36)).remaining()


def test_worker_searches_with_private_vectors_and_never_reranks_or_loads_originals():
    async def run():
        worker = Worker(SETTINGS)
        worker.embed_text = AsyncMock(return_value=[1.0, 0.0, 0.0])
        worker.evaluate_search = AsyncMock()
        expected = {"candidates": [], "nextAfter": None}
        worker.store.saved_matches = AsyncMock(return_value=expected)
        meta = metadata()
        cursor = uuid4()
        try:
            result = await worker.execute("search.saved", meta, json.dumps({"text": "  ví đen ",
                "images": [embedding()], "from": "2026-10-25", "until": "2026-11-08",
                "afterItemId": str(cursor)}).encode())
            assert result == expected
            worker.embed_text.assert_awaited_once_with("ví đen", meta.cacheScope, query=True)
            worker.store.saved_matches.assert_awaited_once_with([1.0, 0.0, 0.0], [[0.0, 1.0, 0.0]],
                from_date=date(2026, 10, 25), until=date(2026, 11, 8), after_item_id=cursor)
            worker.evaluate_search.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("change", [{"modelId": "other"}, {"modelRevision": "c" * 64},
                                    {"dimensions": 2, "vector": [1.0, 0.0]}])
def test_saved_image_identity_must_match_the_deployed_model(change):
    async def run():
        worker = Worker(SETTINGS)
        worker.store.saved_matches = AsyncMock()
        try:
            with pytest.raises(ValueError, match="saved_embedding_configuration_mismatch"):
                await worker.execute("search.saved", metadata(), json.dumps({"images": [embedding(**change)]}).encode())
            worker.store.saved_matches.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_saved_metadata_dimensions_and_disabled_image_search_fail_closed():
    async def run():
        worker = Worker(replace(SETTINGS, image_search_enabled=False))
        try:
            with pytest.raises(ValueError, match="dimension_configuration_mismatch"):
                worker.identity(metadata(dimensions=2))
            with pytest.raises(ModelUnavailable, match="image_search_disabled"):
                await worker.execute("search.saved", metadata(), json.dumps({"images": [embedding()]}).encode())
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("dimensions", [4096, 16000])
def test_saved_query_lane_accepts_bounded_vector_json_larger_than_interactive_text_limit(dimensions):
    async def run():
        worker = Worker(replace(SETTINGS, dimensions=dimensions))
        meta = metadata(dimensions=dimensions)
        body = json.dumps({"images": [embedding(dimensions=dimensions, vector=[-0.12345678901234568] * dimensions)] * 3}).encode()
        assert 65536 < len(body) < 2 * 1024 * 1024
        if dimensions == 16000:
            assert len(body) > 1024 * 1024
        message = SimpleNamespace(type="search.saved", content_type="application/json", body=body,
            headers={"metadata": meta.model_dump_json()}, correlation_id=str(uuid4()), reply_to="amq.gen-test",
            processed=False, locked=False, ack=AsyncMock(), reject=AsyncMock())
        worker.reply = AsyncMock()
        worker.store.saved_matches = AsyncMock(return_value={"candidates": [], "nextAfter": None})
        try:
            await worker.handle(message, "query")
            worker.store.saved_matches.assert_awaited_once()
            assert worker.reply.await_args.args[2] is True
            message.ack.assert_awaited_once()
            message.reject.assert_not_awaited()
            assert message.body == b""
        finally:
            await worker.close()
    asyncio.run(run())


def cosine_vector(score):
    return [score, math.sqrt(1 - score * score), 0.0]


def test_saved_store_threshold_is_inclusive_and_excludes_weak_and_wrong_namespace_sources(store):
    async def run():
        values = [snapshot() for _ in range(3)]
        for value, score in zip(values, [0.8499, 0.85, 0.8501]):
            await put(store, value, cosine_vector(score))
        foreign = Store(store.dsn, "other-model", "revision-1", 3)
        await put(foreign, snapshot())
        result = await store.saved_matches([1.0, 0.0, 0.0], [])
        assert {hit["itemId"] for hit in result["candidates"]} == {value["itemId"] for value in values[1:]}
        boundary = next(hit for hit in result["candidates"] if hit["itemId"] == values[1]["itemId"])
        assert boundary["relevanceScore"] == pytest.approx(0.85, abs=1e-6)
        assert boundary["sources"][0]["sourceKind"] == "text"
    asyncio.run(run())


def test_saved_store_combined_score_averages_text_with_best_image_and_requires_both(store):
    async def run():
        matching = with_images(snapshot(), count=2)
        weak_image = with_images(snapshot(), count=1)
        no_image = snapshot()
        for value, text_score, image_score in [(matching, 0.9, 0.9), (weak_image, 1.0, 0.6)]:
            vectors = {source["id"]: cosine_vector(text_score if source["kind"] == "text" else image_score)
                       for source in value["sources"]}
            if len(value["sources"]) == 3:
                vectors[value["sources"][-1]["id"]] = [0.0, 0.0, 1.0]
            await store.upsert(value, checksum(value), vectors, deadline())
        await put(store, no_image)
        result = await store.saved_matches([1.0, 0.0, 0.0], [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        assert [hit["itemId"] for hit in result["candidates"]] == [matching["itemId"]]
        hit = result["candidates"][0]
        assert hit["relevanceScore"] == pytest.approx(0.95, abs=1e-6)
        assert {source["sourceKind"] for source in hit["sources"]} == {"text", "image"}
        assert next(source for source in hit["sources"] if source["sourceKind"] == "image")["sourceId"] == matching["sources"][-1]["id"]
        images = await store.saved_matches(None, [[0.0, 0.0, 1.0]])
        assert [hit["itemId"] for hit in images["candidates"]] == [matching["itemId"]]
        assert images["candidates"][0]["relevanceScore"] == pytest.approx(1.0)
    asyncio.run(run())


def test_saved_store_pages_beyond_twenty_and_one_hundred_and_honors_dates_tombstones_and_versions(store):
    async def run():
        values = [snapshot(item_id=str(UUID(int=index + 1))) for index in range(105)]
        for value in values:
            await put(store, value)
        outdated = snapshot(item_id=str(UUID(int=200)), found_on="2026-10-24")
        returned = snapshot(item_id=str(UUID(int=201)))
        stale = snapshot(item_id=str(UUID(int=202)))
        for value in [outdated, returned, stale]:
            await put(store, value)
        await store.remove(returned | {"kind": "tombstone", "documentVersion": 2, "document": None, "sources": []},
                           "f" * 64, deadline())
        import psycopg
        async with await psycopg.AsyncConnection.connect(store.dsn, autocommit=True) as db:
            await db.execute("UPDATE ai_items SET document_version=2 WHERE item_id=%s", (stale["itemId"],))
        first = await store.saved_matches([1.0, 0.0, 0.0], [], from_date=date(2026, 10, 25), until=date(2026, 10, 25))
        assert len(first["candidates"]) == 100 and first["nextAfter"] == values[99]["itemId"]
        second = await store.saved_matches([1.0, 0.0, 0.0], [], from_date=date(2026, 10, 25), until=date(2026, 10, 25),
                                           after_item_id=UUID(first["nextAfter"]))
        assert [hit["itemId"] for hit in first["candidates"] + second["candidates"]] == [value["itemId"] for value in values]
        assert second["nextAfter"] is None
    asyncio.run(run())
