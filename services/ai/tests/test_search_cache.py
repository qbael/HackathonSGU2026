import asyncio
from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from findie_ai.config import Settings
from findie_ai.search_cache import SearchCache
from findie_ai.store import Store


@pytest.fixture
def cached_store(monkeypatch):
    entries = {}
    cache = SearchCache("redis://127.0.0.1", 60)
    async def save(key, value, *, ex):
        assert ex == 60
        entries[key] = value
    cache.client = SimpleNamespace(get=AsyncMock(side_effect=entries.get), set=AsyncMock(side_effect=save),
                                   aclose=AsyncMock())
    state = SimpleNamespace(version=str(uuid4()))
    class Connection:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            pass
        async def execute(self, statement):
            assert statement == "SELECT version FROM ai_search_state WHERE singleton"
            return SimpleNamespace(fetchone=AsyncMock(return_value={"version": state.version}))
    monkeypatch.setattr("psycopg.AsyncConnection.connect", AsyncMock(return_value=Connection()))
    row = {"item_id": str(uuid4()), "document_version": 1, "source_id": str(uuid4()), "source_version": 1,
           "source_sha256": "a" * 64, "processing_profile": "text-v1", "location_tokens": ["room:e205"]}
    async def query(*args):
        semantic, keyword = args[-3:-1]
        return ({"semantic": [row]} if semantic else {}) | ({"lexical": [row], "locations": [row]} if keyword else {})
    store = Store("test-database", "test-model", "revision", 2, cache=cache)
    store._search_channels = AsyncMock(side_effect=query)
    return store, cache, entries, state


def test_keyword_hit_still_embeds_and_queries_semantic(cached_store):
    async def run():
        store, cache, entries, _ = cached_store
        embed = AsyncMock(return_value=[1, 0])
        first = await store.search("Ví phòng E.205", None, embed=embed)
        assert store._search_channels.await_args.args[-3:-1] == (True, True)
        assert await store.search("Ví phòng E.205", None, embed=embed) == first
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
        assert embed.await_count == store._search_channels.await_count == 2
        cache.client.set.assert_awaited_once()
        (key, value), = entries.items()
        assert key.startswith("findie:search:v1:keyword:")
        assert set(json.loads(value)) == {"lexical", "locations"}
        assert "Ví" not in value
        await store.close()
        cache.client.aclose.assert_awaited_once()
    asyncio.run(run())


def test_cached_candidate_channels_are_fused_with_the_current_weight(cached_store):
    async def run():
        store, _, entries, _ = cached_store
        semantic = {"item_id": str(uuid4()), "document_version": 1, "source_id": str(uuid4()),
                    "source_version": 1, "source_sha256": "a" * 64,
                    "processing_profile": "text-v1", "location_tokens": []}
        keyword = semantic | {"item_id": str(uuid4()), "source_id": str(uuid4())}
        store._search_channels.side_effect = [
            {"semantic": [semantic], "lexical": [keyword], "locations": []},
            {"semantic": [semantic]},
        ]
        embed = AsyncMock(return_value=[1, 0])
        store.semantic_weight = 0.3
        first = await store.search("ví", None, embed=embed)
        assert [hit["itemId"] for hit in first] == [keyword["item_id"], semantic["item_id"]]
        store.semantic_weight = 0.7
        second = await store.search("ví", None, embed=embed)
        assert [hit["itemId"] for hit in second] == [semantic["item_id"], keyword["item_id"]]
        assert len(entries) == 1
    asyncio.run(run())


def test_keyword_normalizes_vietnamese_independently_of_vector(cached_store):
    async def run():
        store, _, entries, _ = cached_store
        await store.search("Ví phòng E.205", [1, 0])
        await store.search("vi phong E205", [0, 1])
        assert len(entries) == 1
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
    asyncio.run(run())


def test_inflight_old_generation_cannot_repopulate_the_current_cache(cached_store):
    async def run():
        store, _, entries, state = cached_store
        query = store._search_channels.side_effect
        async def concurrent_commit(*args):
            state.version = str(uuid4())
            return await query(*args)
        store._search_channels.side_effect = concurrent_commit
        await store.search("ví", [1, 0])
        store._search_channels.side_effect = query
        await store.search("ví", [1, 0])
        assert store._search_channels.await_args.args[-3:-1] == (True, True)
        assert len(entries) == 2
        await store.search("ví", [1, 0])
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
    asyncio.run(run())


@pytest.mark.parametrize("changed", ["area", "from_date", "until", "include_images", "model", "revision",
                                    "dimensions", "database", "generation"])
def test_cache_identity_isolates_filters_models_modalities_and_index_versions(cached_store, changed):
    async def run():
        store, _, entries, state = cached_store
        await store.search("ví", [1, 0])
        kwargs, vector = {}, [1, 0]
        if changed in {"area", "from_date", "until", "include_images"}:
            kwargs[changed] = {"area": "Quang Trung", "from_date": "2026-10-25", "until": "2026-10-25", "include_images": True}[changed]
        elif changed in {"model", "revision", "dimensions"}:
            identity = list(store.identity)
            index = {"model": 0, "revision": 1, "dimensions": 2}[changed]
            identity[index] = 3 if changed == "dimensions" else "other"
            store.identity = tuple(identity)
            if changed == "dimensions":
                store.dimensions, vector = 3, [1, 0, 0]
        elif changed == "database":
            store.dsn = "other-database"
        else:
            state.version = str(uuid4())
        await store.search("ví", vector, **kwargs)
        assert store._search_channels.await_count == 2
        assert len(entries) == 2
    asyncio.run(run())


def test_output_limit_and_date_representation_reuse_full_candidate_pool(cached_store):
    async def run():
        store, _, _, _ = cached_store
        expected = await store.search("ví", [1, 0], from_date="2026-10-25", limit=1)
        assert await store.search("ví", [1, 0], from_date=date(2026, 10, 25), limit=10) == expected
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
        assert store._search_channels.await_args.args[-1] == 20
    asyncio.run(run())


def test_empty_results_are_cached_and_strategies_only_query_their_branch(cached_store):
    async def run():
        store, cache, entries, _ = cached_store
        store._search_channels.side_effect = [{"lexical": [], "locations": []}, {"semantic": []}]
        assert await store.search("missing", [1, 0], strategy="lexical") == []
        assert store._search_channels.await_args.args[-3:-1] == (False, True)
        assert await store.search("missing", [1, 0], strategy="lexical") == []
        store._search_channels.assert_awaited_once()
        cache.client.get.reset_mock()
        assert await store.search("missing", [1, 0], strategy="semantic") == []
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
        cache.client.get.assert_not_awaited()
        cache.client.set.assert_awaited_once()
        assert len(entries) == 1
    asyncio.run(run())


@pytest.mark.parametrize("failure", [ConnectionError("unavailable"), TimeoutError()])
def test_redis_failure_falls_back_and_does_not_hide_search_errors(cached_store, failure):
    async def run():
        store, cache, _, _ = cached_store
        cache.client.get.side_effect = cache.client.set.side_effect = failure
        assert len(await store.search("ví", [1, 0])) == 1
        store._search_channels.side_effect = RuntimeError("database unavailable")
        with pytest.raises(RuntimeError, match="database unavailable"):
            await store.search("ví", [1, 0])
    asyncio.run(run())


@pytest.mark.parametrize("payload", [b"broken-json", b"[]", b'{"semantic": []}',
                                     b'{"lexical": [{}], "locations": []}',
                                     b'{"lexical": [], "locations": "wrong"}', b"x" * (1024 * 1024 + 1)])
def test_invalid_cache_entries_are_misses(cached_store, payload):
    async def run():
        store, cache, _, _ = cached_store
        cache.client.get.side_effect = None
        cache.client.get.return_value = payload
        assert len(await store.search("ví", [1, 0])) == 1
        store._search_channels.assert_awaited_once()
    asyncio.run(run())


def test_no_redis_config_and_image_search_use_existing_database_path(cached_store):
    async def run():
        store, cache, entries, _ = cached_store
        await store.search("", [1, 0], modality="image")
        cache.client.get.assert_not_awaited()
        assert not entries
        store.cache = None
        await store.search("ví", [1, 0])
        cache.client.get.assert_not_awaited()
        assert store._search_channels.await_count == 2
    asyncio.run(run())


def test_invalid_inputs_still_fail_on_cache_hit(cached_store):
    async def run():
        store, _, _, _ = cached_store
        await store.search("ví", [1, 0])
        for vector, kwargs in (([float("nan"), 0], {}), ([0, 0], {}), ([1, 0], {"limit": 31}),
                               ([1, 0], {"strategy": "invalid"}), ([1, 0], {"modality": "invalid"}),
                               ([1, 0], {"from_date": "2026-10-26", "until": "2026-10-25"})):
            with pytest.raises(ValueError):
                await store.search("ví", vector, **kwargs)
        store._search_channels.assert_awaited_once()
    asyncio.run(run())


def test_cache_cancellation_propagates(cached_store):
    async def run():
        store, cache, _, _ = cached_store
        cache.client.get.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await store.search("ví", [1, 0])
        store._search_channels.assert_not_awaited()
    asyncio.run(run())


def test_cache_settings_from_environment_and_safe_repr(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.setenv("AI_REDIS_URL", "rediss://cache:secret@redis.example/1")
    monkeypatch.setenv("AI_SEARCH_CACHE_TTL_SECONDS", "90")
    settings = Settings.from_env()
    assert settings.redis_url == "rediss://cache:secret@redis.example/1"
    assert settings.search_cache_ttl_seconds == 90
    assert "secret" not in repr(settings)
    assert Settings(service_token="test").redis_url == ""


@pytest.mark.parametrize("kwargs", [{"search_cache_ttl_seconds": 0}, {"search_cache_ttl_seconds": 3601},
    {"redis_url": "http://localhost"}, {"redis_url": "redis://external.example"}, {"redis_url": "redis:///0"},
    {"redis_url": "redis://localhost/0?socket_timeout=100"}, {"redis_url": "redis://localhost/0#fragment"}])
def test_cache_configuration_validation(kwargs):
    with pytest.raises(ValueError, match="AI_(REDIS_URL|SEARCH_CACHE_TTL_SECONDS)"):
        Settings(service_token="test", **kwargs)



def test_area_priority_has_separate_keyword_candidates(cached_store):
    async def run():
        store, _, entries, _ = cached_store
        first = await store.search("ví", [1, 0], area="Quang Trung")
        assert await store.search("ví", [1, 0], area="Chợ Quán") == first
        assert store._search_channels.await_args.args[-3:-1] == (True, True)
        assert len(entries) == 2
        assert await store.search("ví", [1, 0], area="Quang Trung") == first
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
    asyncio.run(run())



def test_inside_and_outside_area_keyword_pools_have_separate_cache_entries(cached_store):
    async def run():
        store, _, entries, _ = cached_store
        first = await store.search("ví", [1, 0], area="quang trung")
        await store.search("ví", [1, 0], area="quang trung", outside_area=True)
        assert len(entries) == 2
        assert store._search_channels.await_args.args[3] is True
        assert await store.search("ví", [1, 0], area="quang trung") == first
        assert store._search_channels.await_args.args[3] is False
        assert store._search_channels.await_args.args[-3:-1] == (True, False)
    asyncio.run(run())


def test_legacy_cache_pool_larger_than_twenty_is_rejected(cached_store):
    async def run():
        store, cache, entries, _ = cached_store
        await store.search("ví", [1, 0])
        payload = json.loads(next(iter(entries.values())))
        payload["lexical"] *= 21
        cache.client.get.side_effect = None
        cache.client.get.return_value = json.dumps(payload)
        await store.search("ví", [1, 0])
        assert store._search_channels.await_args.args[-3:-1] == (True, True)
    asyncio.run(run())
