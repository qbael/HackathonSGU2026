"""Short-lived keyword and location candidates for text search."""

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


class SearchCache:
    def __init__(self, url, ttl):
        self.client = Redis.from_url(url, socket_connect_timeout=0.2, socket_timeout=0.2,
                                     retry=Retry(NoBackoff(), 0))
        self.ttl = ttl

    @staticmethod
    def key(identity):
        digest = sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        return f"findie:search:v1:keyword:{digest}"

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

    async def close(self):
        await self.client.aclose()
