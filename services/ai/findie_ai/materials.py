"""Fetch public candidate material from the API over transient AMQP replies."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import logging
from uuid import UUID, uuid4

import aio_pika
from PIL import Image
from pydantic import Field

from . import images
from .contracts import Contract, Digest, Version
from .ollama import ModelUnavailable
from .ranking import MAX_SEARCH_CANDIDATES


MAX_MANIFEST = 65536
SOURCE_FIELDS = ("documentVersion", "sourceId", "sourceKind", "sourceVersion", "sourceSha256")
log = logging.getLogger(__name__)


def sources(candidate):
    return candidate.get("sources") or [{key: candidate[key] for key in SOURCE_FIELDS}]


def thumbnail(body, mime):
    """Keep model payloads bounded without writing an image or retaining metadata."""
    with Image.fromarray(images._decode(body, mime)) as image:
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue()


class MaterialImage(Contract):
    sourceId: UUID
    sourceVersion: Version
    sourceSha256: Digest
    documentVersion: Version
    contentType: str
    length: int = Field(strict=True, ge=1, le=images.MAX_BYTES)


class MaterialManifest(Contract):
    itemId: UUID
    status: str
    title: str | None = Field(default=None, max_length=200)
    publicDescription: str | None = Field(default=None, max_length=5000)
    image: MaterialImage | None = None


@dataclass
class Material:
    item_id: str
    status: str
    text: str = field(default="", repr=False)
    image: bytes | None = field(default=None, repr=False)
    source: dict | None = None


class MaterialsUnavailable(ModelUnavailable):
    def __init__(self, stale_ids=()):
        super().__init__("materials_unavailable")
        self.stale_ids = frozenset(stale_ids)


def decode_material(body, expected):
    if not 4 < len(body) <= images.MAX_BYTES + MAX_MANIFEST + 4:
        raise ValueError("invalid_material_size")
    length = int.from_bytes(body[:4], "big")
    if not 0 < length <= MAX_MANIFEST or len(body) < 4 + length:
        raise ValueError("invalid_material_manifest")
    manifest = MaterialManifest.model_validate_json(body[4:4 + length])
    item_id = str(manifest.itemId)
    if item_id not in expected or manifest.status not in {"ready", "stale", "unavailable"}:
        raise ValueError("unexpected_material")
    image = body[4 + length:]
    if manifest.status != "ready":
        if image or manifest.image is not None:
            raise ValueError("invalid_material_status")
        return Material(item_id, manifest.status)
    source = manifest.image
    if (source is None or manifest.title is None or manifest.publicDescription is None
            or len(image) != source.length or sha256(image).hexdigest() != source.sourceSha256
            or source.contentType not in images.MIME_FORMATS
            or any(ref["documentVersion"] != source.documentVersion for ref in expected[item_id])):
        raise ValueError("invalid_material_source")
    reference = {"documentVersion": source.documentVersion, "sourceId": str(source.sourceId),
                 "sourceVersion": source.sourceVersion, "sourceSha256": source.sourceSha256, "sourceKind": "image"}
    if any(ref["sourceId"] == reference["sourceId"] and any(ref[key] != reference[key] for key in SOURCE_FIELDS)
           for ref in expected[item_id]):
        raise ValueError("material_source_changed")
    return Material(item_id, "ready", manifest.title + "\n" + manifest.publicDescription,
                    thumbnail(image, source.contentType), reference)


class MaterialsClient:
    def __init__(self, settings):
        self.settings = settings
        self.channel = self.queue = None
        self.pending = {}

    async def start(self, connection):
        self.channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        await self.channel.set_qos(prefetch_count=1)
        self.queue = await self.channel.declare_queue(self.settings.materials_reply_queue,
            exclusive=True, auto_delete=True, arguments={"x-message-ttl": 15000,
                "x-max-length": 4, "x-max-length-bytes": 32 * 1024 * 1024,
                "x-overflow": "reject-publish"})
        await self.queue.consume(self.receive)

    async def close(self):
        for state in self.pending.values():
            if not state["future"].done():
                state["future"].set_exception(ModelUnavailable("materials_unavailable"))
        self.pending.clear()
        if self.channel and not self.channel.is_closed:
            await self.channel.close()
        self.channel = self.queue = None

    async def fetch(self, candidates, deadline):
        if not self.channel or self.channel.is_closed or not self.queue:
            raise ModelUnavailable("materials_unavailable")
        if not 0 < len(candidates) <= MAX_SEARCH_CANDIDATES:
            raise ValueError("invalid_material_candidates")
        expected = {candidate["itemId"]: sources(candidate) for candidate in candidates}
        if len(expected) != len(candidates):
            raise ValueError("duplicate_material_candidate")
        seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        if seconds <= 0:
            raise TimeoutError("materials_deadline_expired")
        correlation = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        state = {"expected": expected, "materials": {}, "future": future}
        self.pending[correlation] = state
        try:
            async with asyncio.timeout(seconds):
                await self.channel.default_exchange.publish(aio_pika.Message(
                    json.dumps({"candidates": [{"itemId": key, "sources": refs} for key, refs in expected.items()]},
                               separators=(",", ":")).encode(),
                    type="search.materials", correlation_id=correlation, reply_to=self.queue.name,
                    content_type="application/json", delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT,
                    expiration=max(0.001, seconds), headers={"metadata": json.dumps({"schemaVersion": 1,
                        "deadlineAt": deadline.isoformat()})}),
                    routing_key=self.settings.materials_queue, mandatory=True, timeout=min(3, seconds))
                return await future
        except asyncio.CancelledError as error:
            # The outer scoring deadline may cancel this RPC before its own timeout fires.
            error.stale_ids = frozenset(key for key, value in state["materials"].items() if value.status == "stale")
            raise
        except Exception as error:
            log.warning("Candidate material RPC failed (%s).", type(error).__name__)
            raise MaterialsUnavailable(key for key, value in state["materials"].items()
                                       if value.status == "stale") from None
        finally:
            self.pending.pop(correlation, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()
            state["materials"].clear()

    async def receive(self, message):
        state = self.pending.get(message.correlation_id)
        phase = "header"
        try:
            if not state or state["future"].done():
                return
            header = message.headers.get("metadata")
            if isinstance(header, str):
                header = header.encode()
            if not isinstance(header, (bytes, bytearray)) or len(header) > 16384 or message.type != "search.materials":
                raise ValueError("invalid_material_reply")
            metadata = json.loads(header)
            if (not isinstance(metadata, dict) or type(metadata.get("schemaVersion")) is not int
                    or metadata["schemaVersion"] != 1 or metadata.get("succeeded") is not True):
                raise ValueError("invalid_material_reply")
            if metadata.get("complete") is True:
                phase = "completion"
                if message.content_type != "application/json" or len(message.body) > 1024:
                    raise ValueError("invalid_material_completion")
                count = json.loads(message.body)["count"]
                if type(count) is not int or count != len(state["expected"]) or set(state["materials"]) != set(state["expected"]):
                    raise ValueError("incomplete_materials")
                state["future"].set_result(dict(state["materials"]))
            else:
                phase = "decode"
                if metadata.get("complete") is not False or message.content_type != "application/octet-stream":
                    raise ValueError("invalid_material_reply")
                material = await asyncio.to_thread(decode_material, message.body, state["expected"])
                phase = "identity"
                if metadata.get("itemId") != material.item_id or material.item_id in state["materials"]:
                    raise ValueError("duplicate_material_reply")
                state["materials"][material.item_id] = material
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            log.warning("Candidate material reply failed (%s, %s).", phase, type(error).__name__)
            if state and not state["future"].done():
                state["future"].set_exception(ModelUnavailable("invalid_materials"))
        finally:
            message.body = b""
            if not message.processed:
                await message.ack()
