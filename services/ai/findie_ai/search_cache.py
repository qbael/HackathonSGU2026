"""Short-lived search candidates and account-scoped embeddings in Redis."""

import asyncio
from hashlib import sha256
import json
import logging
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError


log = logging.getLogger(__name__)


class Candidate(BaseModel):
    item_id: UUID
    document_version: Annotated[int, Field(strict=True, gt=0)]
    source_id: UUID
    source_version: Annotated[int, Field(strict=True, gt=0)]
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    processing_profile: Literal["text-v1", "image-v1"]
    location_tokens: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=200)]


ROWS = TypeAdapter(Annotated[list[Candidate], Field(max_length=200)])
EMBEDDING = TypeAdapter(Annotated[list[Annotated[float, Field(strict=True, allow_inf_nan=False)]],
                                Field(min_length=1, max_length=16000)])


class SearchCache:
    def __init__(self, url, ttl):
        self.client = Redis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2,
                                     retry=Retry(NoBackoff(), 0))
        self.ttl = ttl

    @staticmethod
    def key(identity, *, namespace="keyword"):
        digest = sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        return f"findie:search:v1:{namespace}:{digest}"

    async def get(self, key):
        try:
            async with asyncio.timeout(0.3):
                value = await self.client.get(key)
            if value is None:
                return None
            if len(value) > 1024 * 1024:
                raise ValueError("Oversized cache entry")
            value = json.loads(value)
            if not isinstance(value, dict) or set(value) != {"lexical", "locations"}:
                raise ValueError("Invalid cached channels")
            return {channel: ROWS.dump_python(ROWS.validate_python(rows), mode="json") for channel, rows in value.items()}
        except (RedisError, TimeoutError, ValueError):
            log.warning("Search cache read unavailable or invalid; using PostgreSQL.")
            return None

    async def put(self, key, value):
        try:
            async with asyncio.timeout(0.3):
                await self.client.set(key, json.dumps(value, default=str, separators=(",", ":")), ex=self.ttl)
        except (RedisError, TimeoutError):
            log.warning("Search cache write unavailable; returning PostgreSQL results.")

    @staticmethod
    def _embedding(value, dimensions):
        vector = EMBEDDING.validate_python(value)
        if len(vector) != dimensions or not any(vector):
            raise ValueError("Invalid cached embedding")
        return vector

    async def get_embedding(self, key, dimensions):
        try:
            async with asyncio.timeout(0.3):
                value = await self.client.get(key)
            if value is None:
                return None
            if len(value) > 1024 * 1024:
                raise ValueError("Oversized cache entry")
            return self._embedding(json.loads(value), dimensions)
        except (RedisError, TimeoutError, ValueError, RecursionError):
            log.warning("Embedding cache read unavailable or invalid; using model inference.")
            return None

    async def put_embedding(self, key, vector, dimensions):
        try:
            value = json.dumps(self._embedding(vector, dimensions), allow_nan=False, separators=(",", ":"))
            async with asyncio.timeout(0.3):
                await self.client.set(key, value, ex=300)
        except (RedisError, TimeoutError, ValueError):
            log.warning("Embedding cache write unavailable or invalid; returning model output.")

    async def close(self):
        await self.client.aclose()
