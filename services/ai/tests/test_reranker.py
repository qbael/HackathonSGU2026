import asyncio
import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from findie_ai.config import Settings
from findie_ai.materials import Material
from findie_ai.ollama import ModelUnavailable
from findie_ai.ranking import MAX_SEARCH_CANDIDATES
from findie_ai.reranker import rerank


SETTINGS = Settings(service_token="test", reranker_revision="b" * 64)


def materials():
    return {item: Material(item, "ready", "Safe synthetic description", b"synthetic image bytes")
            for item in (str(uuid4()) for _ in range(MAX_SEARCH_CANDIDATES))}


def rows(values, *, image=True, text=True):
    return [{"itemId": item, "imageScore": 0.9 if image else None, "textScore": 0.8 if text else None}
            for item in values]


@pytest.mark.parametrize(("text", "images"), [("ví đen", [b"safe synthetic query"]),
                                                (None, [b"safe synthetic query"]), ("ví đen", [])])
def test_all_twenty_candidates_are_scored_in_one_model_request_with_separate_modality_scores(text, images):
    async def run():
        values = materials()
        model = type("Model", (), {})()
        model._verify_revision = AsyncMock()
        model._json = AsyncMock(return_value={"model": SETTINGS.reranker_model,
                                              "scores": rows(values, image=bool(images), text=bool(text))})
        deadline = datetime.now(timezone.utc) + timedelta(seconds=15)
        result = await rerank(model, SETTINGS, values, text, images, deadline)
        assert len(result) == MAX_SEARCH_CANDIDATES and set(result) == set(values)
        method, path, payload = model._json.await_args.args
        assert (method, path) == ("POST", "api/rerank")
        assert len(payload["candidates"]) == MAX_SEARCH_CANDIDATES
        assert payload["deadlineAt"] == deadline.isoformat()
        assert payload["images"] == [base64.b64encode(image).decode() for image in images]
        assert all(candidate["text"] == "Safe synthetic description" for candidate in payload["candidates"])
        assert model._verify_revision.await_count == 2
        model._verify_revision.assert_awaited_with(SETTINGS.reranker_model, SETTINGS.reranker_revision)
        assert all(score == {"image": 0.9 if images else None, "text": 0.8 if text else None}
                   for score in result.values())

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing-row", "duplicate-row", "unknown-item", "wrong-model", "missing-modality",
    "nan", "infinity", "negative", "above-one", "boolean", "string", "unexpected-image-score", "missing-key"])
def test_any_incomplete_or_invalid_score_rejects_the_entire_rerank_response(failure):
    async def run():
        values = materials()
        image_query = failure != "unexpected-image-score"
        scores = rows(values, image=image_query)
        result = {"model": SETTINGS.reranker_model, "scores": scores}
        if failure == "missing-row":
            scores.pop()
        elif failure == "duplicate-row":
            scores[-1] = scores[0]
        elif failure == "unknown-item":
            scores[-1]["itemId"] = str(uuid4())
        elif failure == "wrong-model":
            result["model"] = "different-model"
        elif failure == "missing-modality":
            scores[-1]["textScore"] = None
        elif failure == "unexpected-image-score":
            scores[-1]["imageScore"] = 0.9
        elif failure == "missing-key":
            scores[-1].pop("textScore")
        else:
            scores[-1]["textScore"] = {"nan": float("nan"), "infinity": float("inf"), "negative": -0.01,
                "above-one": 1.01, "boolean": True, "string": "0.9"}[failure]
        model = type("Model", (), {})()
        model._verify_revision = AsyncMock()
        model._json = AsyncMock(return_value=result)
        with pytest.raises(ModelUnavailable, match="invalid_rerank_scores"):
            await rerank(model, SETTINGS, values, "safe query", [b"safe image"] if image_query else [],
                         datetime.now(timezone.utc) + timedelta(seconds=15))

    asyncio.run(run())


def test_model_failure_and_revision_change_are_not_converted_to_partial_scores():
    async def run():
        values = materials()
        model = type("Model", (), {})()
        model._verify_revision = AsyncMock(side_effect=[None, ModelUnavailable("model_revision_mismatch")])
        model._json = AsyncMock(return_value={"model": SETTINGS.reranker_model, "scores": rows(values)})
        with pytest.raises(ModelUnavailable, match="model_revision_mismatch"):
            await rerank(model, SETTINGS, values, "safe query", [b"safe image"], datetime.now(timezone.utc))
        model._verify_revision = AsyncMock()
        model._json = AsyncMock(side_effect=ModelUnavailable("model_busy"))
        with pytest.raises(ModelUnavailable, match="model_busy"):
            await rerank(model, SETTINGS, values, "safe query", [], datetime.now(timezone.utc))

    asyncio.run(run())
