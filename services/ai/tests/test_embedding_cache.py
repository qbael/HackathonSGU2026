import asyncio
from dataclasses import replace
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from findie_ai.config import Settings
from findie_ai.ollama import ModelUnavailable
from findie_ai.search_cache import SearchCache
from findie_ai.worker import Worker


SETTINGS = Settings(service_token="test", search_dsn="test-database", redis_url="redis://127.0.0.1",
                    revision="a" * 64, dimensions=2)


@pytest.fixture
def redis_backend(monkeypatch):
    state = SimpleNamespace(now=0, entries={}, clients=[])

    def connect(*_args, **_kwargs):
        async def get(key):
            entry = state.entries.get(key)
            if entry is None or entry[1] <= state.now:
                state.entries.pop(key, None)
                return None
            return entry[0]

        async def set_(key, value, *, ex):
            state.entries[key] = (value.encode() if isinstance(value, str) else value, state.now + ex)

        client = SimpleNamespace(get=AsyncMock(side_effect=get), set=AsyncMock(side_effect=set_),
                                 aclose=AsyncMock())
        state.clients.append(client)
        return client

    monkeypatch.setattr("findie_ai.search_cache.Redis.from_url", connect)
    return state


def test_embedding_cache_preserves_precision_and_expires_independently_of_keyword_ttl(redis_backend):
    async def run():
        cache = SearchCache(SETTINGS.redis_url, 60)
        identity = ["same-input"]
        key = cache.key(identity, namespace="embedding")
        assert key.startswith("findie:search:v1:embedding:")
        assert cache.key(identity).startswith("findie:search:v1:keyword:")
        assert key != cache.key(identity)
        assert await cache.get_embedding(key, 2) is None
        vector = [0.12345678901234568, 0.9876543210987654]
        await cache.put_embedding(key, vector, 2)
        args, kwargs = cache.client.set.await_args
        assert args[0] == key and kwargs == {"ex": 300}
        assert json.loads(args[1]) == vector
        assert await cache.get_embedding(key, 2) == vector
        redis_backend.now = 299
        assert await cache.get_embedding(key, 2) == vector
        redis_backend.now = 300
        assert await cache.get_embedding(key, 2) is None
        await cache.close()
        cache.client.aclose.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("payload", [b"broken-json", b"null", b"{}", b"[1]", b"[1,0,0]",
                                     b"[true,0]", b'["1",0]', b"[null,0]", b"[0,0]",
                                     b"[NaN,0]", b"[Infinity,0]", b"[1e999,0]", b"[" * 1100 + b"]" * 1100,
                                     b"x" * (1024 * 1024 + 1)])
def test_invalid_embedding_cache_entries_are_misses(redis_backend, payload):
    async def run():
        cache = SearchCache(SETTINGS.redis_url, 60)
        cache.client.get.side_effect = None
        cache.client.get.return_value = payload
        assert await cache.get_embedding("embedding-key", 2) is None
        await cache.close()

    asyncio.run(run())


@pytest.mark.parametrize("vector", [[1.0], [0.0, 0.0], [True, 0.0], ["1", 0.0],
                                    [float("nan"), 0.0], [float("inf"), 0.0]])
def test_invalid_embeddings_are_not_written(redis_backend, vector):
    async def run():
        cache = SearchCache(SETTINGS.redis_url, 60)
        await cache.put_embedding("embedding-key", vector, 2)
        cache.client.set.assert_not_awaited()
        await cache.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [ConnectionError("unavailable"), TimeoutError()])
def test_embedding_cache_outages_are_misses_and_writes_do_not_fail(redis_backend, failure):
    async def run():
        cache = SearchCache(SETTINGS.redis_url, 60)
        cache.client.get.side_effect = cache.client.set.side_effect = failure
        assert await cache.get_embedding("embedding-key", 2) is None
        await cache.put_embedding("embedding-key", [1.0, 0.0], 2)
        await cache.close()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["get", "set"])
def test_embedding_cache_cancellation_propagates(redis_backend, operation):
    async def run():
        cache = SearchCache(SETTINGS.redis_url, 60)
        getattr(cache.client, operation).side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            if operation == "get":
                await cache.get_embedding("embedding-key", 2)
            else:
                await cache.put_embedding("embedding-key", [1.0, 0.0], 2)
        await cache.close()

    asyncio.run(run())


def test_two_workers_share_embeddings_until_redis_ttl_expires(redis_backend):
    async def run():
        first, second = Worker(SETTINGS), Worker(SETTINGS)
        scope = uuid4()
        embed = AsyncMock(return_value=[0.12345678901234568, 0.9876543210987654])
        try:
            original = await first.cached_embedding(scope, ("text", "input-hash"), embed)
            assert await second.cached_embedding(scope, ("text", "input-hash"), embed) == original
            embed.assert_awaited_once()
            redis_backend.now = 300
            assert await second.cached_embedding(scope, ("text", "input-hash"), embed) == original
            assert embed.await_count == 2
        finally:
            await first.close()
            await second.close()
        for client in redis_backend.clients:
            client.aclose.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("changed", ["search_dsn", "model_id", "revision", "dimensions", "search_profile",
                                    "image_search_profile", "scope", "input"])
def test_worker_embedding_identity_isolates_inputs_scopes_and_configuration(redis_backend, changed):
    async def run():
        settings = SETTINGS
        if changed not in {"scope", "input"}:
            settings = replace(SETTINGS, **{changed: 3 if changed == "dimensions" else
                                           "b" * 64 if changed == "revision" else "other"})
        first, second = Worker(SETTINGS), Worker(settings)
        scope = uuid4()
        embed = AsyncMock(return_value=[1.0, 0.0])
        other_embed = AsyncMock(return_value=[0.0, 1.0] + ([0.0] if changed == "dimensions" else []))
        try:
            await first.cached_embedding(scope, ("text", "input-hash"), embed)
            result = await second.cached_embedding(uuid4() if changed == "scope" else scope,
                ("text", "different-hash" if changed == "input" else "input-hash"), other_embed)
            assert result == other_embed.return_value
            other_embed.assert_awaited_once()
            assert len(redis_backend.entries) == 2
        finally:
            await first.close()
            await second.close()

    asyncio.run(run())


def test_text_embedding_identity_keeps_query_instruction_and_exact_text(redis_backend):
    async def run():
        worker = Worker(SETTINGS)
        worker.ollama.embed = AsyncMock(return_value=[1.0, 0.0])
        scope = uuid4()
        try:
            for text, query in (("Ví đen", False), ("Ví đen", False), ("Ví đen", True),
                                ("Ví đen", True), ("Vi den", True)):
                await worker.embed_text(text, scope, query=query)
            assert worker.ollama.embed.await_count == 3
            assert len(redis_backend.entries) == 3
            assert "Ví đen" not in " ".join(redis_backend.entries)
        finally:
            await worker.close()

    asyncio.run(run())


@pytest.mark.parametrize("disabled", ["scope", "redis"])
def test_missing_scope_or_redis_bypasses_embedding_cache(redis_backend, disabled):
    async def run():
        worker = Worker(replace(SETTINGS, redis_url="") if disabled == "redis" else SETTINGS)
        scope = None if disabled == "scope" else uuid4()
        embed = AsyncMock(return_value=[1.0, 0.0])
        try:
            for _ in range(2):
                assert await worker.cached_embedding(scope, "same-input", embed) == [1.0, 0.0]
            assert embed.await_count == 2
            assert not redis_backend.entries
            for client in redis_backend.clients:
                client.get.assert_not_awaited()
                client.set.assert_not_awaited()
        finally:
            await worker.close()

    asyncio.run(run())


def test_failed_embedding_is_not_cached(redis_backend):
    async def run():
        worker = Worker(SETTINGS)
        embed = AsyncMock(side_effect=[ModelUnavailable("unavailable"), [1.0, 0.0]])
        scope = uuid4()
        try:
            with pytest.raises(ModelUnavailable):
                await worker.cached_embedding(scope, "same-input", embed)
            assert not redis_backend.entries
            assert await worker.cached_embedding(scope, "same-input", embed) == [1.0, 0.0]
            assert await worker.cached_embedding(scope, "same-input", embed) == [1.0, 0.0]
            assert embed.await_count == 2
        finally:
            await worker.close()

    asyncio.run(run())


def test_real_redis_shares_expires_and_replaces_corrupt_embeddings():
    redis_url = os.environ.get("AI_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("Requires disposable Redis via AI_TEST_REDIS_URL")

    async def run():
        settings = replace(SETTINGS, redis_url=redis_url)
        first, second = Worker(settings), Worker(settings)
        scope, key = uuid4(), None
        embed = AsyncMock(return_value=[0.12345678901234568, 0.9876543210987654])
        cache = first.store.cache
        cache.put_embedding = AsyncMock(wraps=cache.put_embedding)
        try:
            original = await first.cached_embedding(scope, "real-redis-test", embed)
            key = cache.put_embedding.await_args.args[0]
            assert await second.cached_embedding(scope, "real-redis-test", embed) == original
            embed.assert_awaited_once()
            assert 0 < await cache.client.ttl(key) <= 300

            await cache.client.pexpire(key, 1)
            async with asyncio.timeout(1):
                while await cache.client.exists(key):
                    await asyncio.sleep(0.01)
            assert await second.cached_embedding(scope, "real-redis-test", embed) == original
            assert embed.await_count == 2

            await cache.client.set(key, b"[NaN,0]", ex=300)
            assert await first.cached_embedding(scope, "real-redis-test", embed) == original
            assert embed.await_count == 3
            assert await cache.get_embedding(key, 2) == original
        finally:
            try:
                if key is not None:
                    await cache.client.delete(key)
            finally:
                await first.close()
                await second.close()

    asyncio.run(run())
