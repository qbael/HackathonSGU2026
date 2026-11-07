import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import uuid4

import pytest

from findie_ai.config import Settings
from findie_ai.contracts import SearchMetadata
from findie_ai.materials import Material
from findie_ai.ollama import ModelUnavailable
from findie_ai.worker import Worker


def fixture():
    settings = Settings(service_token="test", dimensions=2, revision="a" * 64,
                        reranker_revision="b" * 64)
    candidates = [{"itemId": str(uuid4()), "documentVersion": 1, "sourceId": str(uuid4()),
                   "sourceVersion": 1, "sourceSha256": "a" * 64, "sourceKind": "text"} for _ in range(20)]
    rankings = [[hit | {"similarity": 0.8} for hit in candidates]]
    materials = {hit["itemId"]: Material(hit["itemId"], "ready", "Ví đen", b"safe processed fixture", {
        "sourceId": str(uuid4()), "documentVersion": 1, "sourceVersion": 1,
        "sourceSha256": "b" * 64, "sourceKind": "image"}) for hit in candidates}
    metadata = SearchMetadata(schemaVersion=1, modelId=settings.model_id, modelRevision=settings.revision,
        processingProfile="text-v1", searchProfileId=settings.search_profile, searchProfileVersion=1,
        mode="text", limit=10, candidateLimit=20, deadlineAt=datetime.now(timezone.utc) + timedelta(seconds=45))
    return settings, candidates, rankings, materials, metadata


def test_material_channel_failure_triggers_worker_reconnect_even_when_main_channels_are_open():
    async def run():
        settings, *_ = fixture()
        worker = Worker(settings)
        worker.connection = worker.publisher = worker.consumer = SimpleNamespace(is_closed=False, close=AsyncMock())
        worker.materials.channel = SimpleNamespace(is_closed=False, close=AsyncMock())
        worker.materials.queue = object()
        try:
            assert worker.connected
            worker.materials.channel.is_closed = True
            assert not worker.connected
        finally:
            await worker.close()
    asyncio.run(run())


def test_model_scores_the_entire_twenty_item_pool_and_can_promote_the_last_item(monkeypatch):
    async def run():
        settings, candidates, rankings, materials, metadata = fixture()
        worker = Worker(settings)
        worker.materials.fetch = AsyncMock(return_value=materials)
        async def score(_ollama, _settings, values, text, query_images, deadline):
            assert len(values) == 20 and text == "ví đen" and not query_images
            assert 0 < (deadline - datetime.now(timezone.utc)).total_seconds() <= 15
            return {key: {"image": None, "text": 0.99 if key == candidates[-1]["itemId"] else 0.2} for key in values}
        model = AsyncMock(side_effect=score)
        monkeypatch.setattr("findie_ai.worker.rerank", model)
        try:
            result = await worker.evaluate_search(candidates, rankings, metadata, text="ví đen", text_index=0)
            assert result["rankingMethod"] == "reranker"
            assert [hit["itemId"] for hit in result["candidates"]] == [candidates[-1]["itemId"]]
            assert result["candidates"][0]["relevanceScore"] == 0.99
            assert materials[candidates[-1]["itemId"]].source in result["candidates"][0]["sources"]
            assert len(worker.materials.fetch.await_args.args[0]) == 20
        finally:
            await worker.close()
    asyncio.run(run())


def test_all_twenty_qualified_items_reach_api_without_an_early_ten_item_limit(monkeypatch):
    async def run():
        settings, candidates, rankings, materials, metadata = fixture()
        worker = Worker(settings)
        worker.materials.fetch = AsyncMock(return_value=materials)
        monkeypatch.setattr("findie_ai.worker.rerank", AsyncMock(return_value={
            key: {"image": None, "text": 0.9} for key in materials}))
        try:
            result = await worker.evaluate_search(candidates, rankings, metadata, text="ví", text_index=0)
            assert len(result["candidates"]) == 20
            assert all(hit["textRelevant"] and not hit["imageRelevant"] for hit in result["candidates"])
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", [ModelUnavailable("test"), TimeoutError()])
def test_failed_model_uses_whole_similarity_pool_and_never_restores_stale_items(monkeypatch, failure):
    async def run():
        settings, candidates, rankings, materials, metadata = fixture()
        materials[candidates[0]["itemId"]] = Material(candidates[0]["itemId"], "stale")
        worker = Worker(settings)
        worker.materials.fetch = AsyncMock(return_value=materials)
        monkeypatch.setattr("findie_ai.worker.rerank", AsyncMock(side_effect=failure))
        try:
            result = await worker.evaluate_search(candidates, rankings, metadata, text="ví", text_index=0)
            assert result["rankingMethod"] == "similarity_fallback"
            assert len(result["candidates"]) == 19
            assert candidates[0]["itemId"] not in {hit["itemId"] for hit in result["candidates"]}
            assert all(hit["relevanceScore"] == 0.8 and "sources" not in hit for hit in result["candidates"])
        finally:
            await worker.close()
    asyncio.run(run())


def test_unconfigured_model_does_not_fetch_images_and_all_low_scores_return_empty():
    async def run():
        settings, candidates, rankings, _, metadata = fixture()
        worker = Worker(replace(settings, reranker_revision=""))
        worker.materials.fetch = AsyncMock()
        rankings = [[hit | {"similarity": 0.2} for hit in candidates]]
        try:
            result = await worker.evaluate_search(candidates, rankings, metadata, text="ví", text_index=0)
            assert result == {"candidates": [], "rankingMethod": "similarity_fallback"}
            worker.materials.fetch.assert_not_awaited()
        finally:
            await worker.close()
    asyncio.run(run())


def test_public_request_cancellation_is_not_converted_into_similarity_success(monkeypatch):
    async def run():
        settings, candidates, rankings, materials, metadata = fixture()
        worker = Worker(settings)
        worker.materials.fetch = AsyncMock(side_effect=asyncio.CancelledError())
        try:
            with pytest.raises(asyncio.CancelledError):
                await worker.evaluate_search(candidates, rankings, metadata, text="ví", text_index=0)
        finally:
            await worker.close()
    asyncio.run(run())
