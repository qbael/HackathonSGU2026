import asyncio

import pytest

from findie_ai.config import Settings
from findie_ai.worker import Worker


@pytest.mark.parametrize(("value", "expected"), [(None, 0.6), ("0.7", 0.7), ("0", 0.0), ("1", 1.0)])
def test_search_semantic_weight_defaults_and_environment_override(monkeypatch, value, expected):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.delenv("AI_SEARCH_SEMANTIC_WEIGHT", raising=False)
    if value is not None:
        monkeypatch.setenv("AI_SEARCH_SEMANTIC_WEIGHT", value)
    assert Settings.from_env().semantic_weight == expected


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-0.01", "1.01", "not-a-number", ""])
def test_search_semantic_weight_rejects_invalid_environment_values(monkeypatch, value):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.setenv("AI_SEARCH_SEMANTIC_WEIGHT", value)
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.01, 1.01])
def test_search_semantic_weight_validation_applies_to_direct_settings(value):
    with pytest.raises(ValueError):
        Settings(service_token="test", semantic_weight=value)


def test_worker_passes_search_semantic_weight_to_store():
    async def run():
        worker = Worker(Settings(service_token="test", semantic_weight=0.7))
        try:
            assert worker.store.semantic_weight == 0.7
        finally:
            await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["image", "text"])
@pytest.mark.parametrize("value", ["0.6", "0", "1", "0.75"])
def test_area_similarity_threshold_environment(monkeypatch, kind, value):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.setenv(f"AI_SEARCH_MIN_{kind.upper()}_SIMILARITY", value)
    assert getattr(Settings.from_env(), f"min_{kind}_similarity") == float(value)


@pytest.mark.parametrize("kind", ["image", "text"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-0.01", "1.01", "bad", ""])
def test_area_similarity_threshold_rejects_invalid_values(monkeypatch, kind, value):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.setenv(f"AI_SEARCH_MIN_{kind.upper()}_SIMILARITY", value)
    with pytest.raises(ValueError):
        Settings.from_env()
