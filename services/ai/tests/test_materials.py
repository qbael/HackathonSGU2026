import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4

from PIL import Image, PngImagePlugin
from pamqp.encode import field_table
import pytest

from findie_ai.config import Settings
from findie_ai.materials import MAX_MANIFEST, MaterialsClient, MaterialsUnavailable, decode_material
from findie_ai.ollama import ModelUnavailable
from findie_ai.ranking import MAX_SEARCH_CANDIDATES


def fixture():
    output = BytesIO()
    with Image.new("RGB", (640, 320), "blue") as image:
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("note", "safe synthetic fixture")
        image.save(output, format="PNG", pnginfo=metadata)
    image = output.getvalue()
    item, source = str(uuid4()), str(uuid4())
    ref = {"documentVersion": 3, "sourceId": source, "sourceKind": "image",
           "sourceVersion": 2, "sourceSha256": sha256(image).hexdigest()}
    manifest = {"itemId": item, "status": "ready", "title": "Ví xanh", "publicDescription": "Có khóa kéo",
        "image": {key: value for key, value in ref.items() if key != "sourceKind"}
                 | {"contentType": "image/png", "length": len(image)}}
    return manifest, image, {item: [ref]}


def packet(manifest, image=b""):
    header = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode()
    return len(header).to_bytes(4, "big") + header + image


class Message:
    def __init__(self, correlation, metadata, body, *, mime="application/octet-stream", kind="search.materials"):
        self.correlation_id = correlation
        self.headers = {"metadata": json.dumps(metadata).encode()}
        self.body = body
        self.content_type = mime
        self.type = kind
        self.processed = False
        self.acknowledged = False

    async def ack(self):
        self.acknowledged = self.processed = True


def part(correlation, manifest, image=b""):
    return Message(correlation, {"schemaVersion": 1, "succeeded": True, "complete": False,
                   "itemId": manifest["itemId"]}, packet(manifest, image))


def complete(correlation, count):
    return Message(correlation, {"schemaVersion": 1, "succeeded": True, "complete": True},
                   json.dumps({"count": count}).encode(), mime="application/json")


def test_ready_material_checks_provenance_and_creates_only_an_in_memory_thumbnail():
    manifest, image, expected = fixture()
    material = decode_material(packet(manifest, image), expected)
    assert material.item_id == manifest["itemId"] and material.status == "ready"
    assert material.text == "Ví xanh\nCó khóa kéo"
    assert material.source == expected[material.item_id][0]
    with Image.open(BytesIO(material.image)) as thumbnail:
        assert thumbnail.format == "JPEG" and thumbnail.size == (512, 256)
        assert "note" not in thumbnail.info
    assert material.text not in repr(material)
    assert "safe synthetic fixture" not in repr(material)


@pytest.mark.parametrize("status", ["stale", "unavailable"])
def test_non_ready_material_has_no_model_content(status):
    manifest, image, expected = fixture()
    value = {"itemId": manifest["itemId"], "status": status}
    material = decode_material(packet(value), expected)
    assert material.status == status and material.image is None and material.text == ""
    with pytest.raises(ValueError):
        decode_material(packet(value, image), expected)
    with pytest.raises(ValueError):
        decode_material(packet(value | {"image": manifest["image"]}), expected)


@pytest.mark.parametrize(("field", "value"), [
    ("sourceVersion", 3), ("sourceVersion", 0), ("documentVersion", 4),
    ("contentType", "text/html"), ("length", 1), ("length", True),
    ("sourceSha256", "a" * 64), ("sourceId", "invalid-uuid"),
])
def test_image_integrity_and_source_changes_are_rejected(field, value):
    manifest, image, expected = fixture()
    manifest["image"][field] = value
    with pytest.raises(ValueError):
        decode_material(packet(manifest, image), expected)


def test_new_public_image_source_for_a_text_only_candidate_is_allowed():
    manifest, image, expected = fixture()
    item = manifest["itemId"]
    expected[item] = [expected[item][0] | {"sourceId": item, "sourceKind": "text", "sourceSha256": "a" * 64}]
    assert decode_material(packet(manifest, image), expected).source["sourceKind"] == "image"
    manifest["image"]["documentVersion"] += 1
    with pytest.raises(ValueError):
        decode_material(packet(manifest, image), expected)


@pytest.mark.parametrize("change", ["external-item", "unknown-status", "missing-image", "missing-text", "wrong-image-format"])
def test_invalid_ready_manifests_and_external_item_ids_are_rejected(change):
    manifest, image, expected = fixture()
    if change == "external-item":
        manifest["itemId"] = str(uuid4())
    elif change == "unknown-status":
        manifest["status"] = "private"
    elif change == "missing-image":
        manifest.pop("image")
    elif change == "missing-text":
        manifest.pop("publicDescription")
    else:
        manifest["image"]["contentType"] = "image/jpeg"
    with pytest.raises(ValueError):
        decode_material(packet(manifest, image), expected)


@pytest.mark.parametrize("body", [b"", b"\0\0\0\0", b"\0\0\0\5{}",
    (MAX_MANIFEST + 1).to_bytes(4, "big") + b"{}", b"\0\0\0\2[]"])
def test_binary_manifest_bounds_and_shape_are_validated(body):
    with pytest.raises(ValueError):
        decode_material(body, {})


@pytest.mark.parametrize("header_type", [bytes, bytearray, str])
def test_fetch_collects_all_twenty_parts_without_a_display_limit_and_acks_each_packet(header_type):
    async def run():
        client = MaterialsClient(Settings(service_token="test"))
        manifests = [{"itemId": str(uuid4()), "status": "stale"} for _ in range(MAX_SEARCH_CANDIDATES)]
        candidates = [{"itemId": value["itemId"], "sources": [{"sourceId": value["itemId"]}]}
                      for value in manifests]
        seen = []

        class Channel:
            is_closed = False
            default_exchange = None

            def __init__(self):
                self.default_exchange = self

            async def publish(self, request, **kwargs):
                assert field_table(request.headers), "material headers must serialize on the AMQP wire"
                assert request.type == "search.materials" and request.reply_to == "findie.ai.materials.results"
                assert kwargs["routing_key"] == "findie.api.materials" and kwargs["mandatory"]
                assert len(json.loads(request.body)["candidates"]) == MAX_SEARCH_CANDIDATES
                assert request.delivery_mode.value == 1
                assert json.loads(request.headers["metadata"])["schemaVersion"] == 1
                for manifest in manifests:
                    message = part(request.correlation_id, manifest)
                    header = message.headers["metadata"]
                    message.headers["metadata"] = header.decode() if header_type is str else header_type(header)
                    await client.receive(message)
                    seen.append(message)
                message = complete(request.correlation_id, MAX_SEARCH_CANDIDATES)
                header = message.headers["metadata"]
                message.headers["metadata"] = header.decode() if header_type is str else header_type(header)
                await client.receive(message)
                seen.append(message)

        client.channel = Channel()
        client.queue = type("Queue", (), {"name": "findie.ai.materials.results"})()
        result = await client.fetch(candidates, datetime.now(timezone.utc) + timedelta(seconds=15))
        assert len(result) == MAX_SEARCH_CANDIDATES
        assert all(value.status == "stale" for value in result.values())
        assert client.pending == {}
        assert all(message.acknowledged and message.body == b"" for message in seen)
        late = part("not-an-active-correlation", manifests[0])
        await client.receive(late)
        assert late.acknowledged and late.body == b""

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["list-header", "boolean-version", "oversize-header", "failed", "wrong-type", "wrong-id", "duplicate",
                                      "early-completion", "wrong-count", "malformed-body"])
def test_invalid_or_incomplete_replies_fail_the_whole_fetch_and_are_acknowledged(failure):
    async def run():
        client = MaterialsClient(Settings(service_token="test"))
        manifest, image, expected = fixture()
        correlation = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        state = {"expected": expected, "materials": {}, "future": future}
        client.pending[correlation] = state
        message = part(correlation, manifest, image)
        if failure == "list-header":
            message.headers["metadata"] = b"[]"
        elif failure == "boolean-version":
            message.headers["metadata"] = b'{"schemaVersion":true,"succeeded":true,"complete":false}'
        elif failure == "oversize-header":
            message.headers["metadata"] = "ế" * 6000
        elif failure == "failed":
            message.headers["metadata"] = b'{"schemaVersion":1,"succeeded":false}'
        elif failure == "wrong-type":
            message.type = "index.upsert"
        elif failure == "wrong-id":
            header = json.loads(message.headers["metadata"])
            message.headers["metadata"] = json.dumps(header | {"itemId": str(uuid4())}).encode()
        elif failure == "duplicate":
            await client.receive(part(correlation, manifest, image))
        elif failure == "early-completion":
            message = complete(correlation, 1)
        elif failure == "wrong-count":
            await client.receive(message)
            message = complete(correlation, 2)
        elif failure == "malformed-body":
            message.body = b"invalid binary payload"
        await client.receive(message)
        with pytest.raises(ModelUnavailable, match="invalid_materials"):
            await future
        assert message.acknowledged and message.body == b""
        ignored = complete(correlation, 1)
        await client.receive(ignored)
        assert ignored.acknowledged

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["malformed", "timeout", "outer-timeout"])
def test_failed_collection_keeps_known_stale_ids_for_fallback(failure):
    async def run():
        client = MaterialsClient(Settings(service_token="test"))
        item = str(uuid4())

        class Channel:
            is_closed = False
            default_exchange = None

            def __init__(self):
                self.default_exchange = self

            async def publish(self, request, **_kwargs):
                await client.receive(part(request.correlation_id, {"itemId": item, "status": "stale"}))
                if failure == "malformed":
                    message = complete(request.correlation_id, 2)
                    await client.receive(message)
                else:
                    await asyncio.Event().wait()

        client.channel = Channel()
        client.queue = type("Queue", (), {"name": "findie.ai.materials.results"})()
        with pytest.raises(TimeoutError if failure == "outer-timeout" else MaterialsUnavailable) as error:
            async with asyncio.timeout(0.02 if failure == "outer-timeout" else 1):
                await client.fetch([{"itemId": item, "sources": [{"sourceId": item}]}],
                                   datetime.now(timezone.utc) + timedelta(seconds=0.5 if failure == "outer-timeout" else 0.02))
        cause = error.value.__cause__ if failure == "outer-timeout" else error.value
        assert cause.stale_ids == {item}
        assert client.pending == {}

    asyncio.run(run())


def test_caller_cancellation_is_not_converted_to_a_fallback_failure():
    async def run():
        client = MaterialsClient(Settings(service_token="test"))

        class Channel:
            is_closed = False
            default_exchange = None

            def __init__(self):
                self.default_exchange = self

            async def publish(self, *_args, **_kwargs):
                raise asyncio.CancelledError()

        client.channel = Channel()
        client.queue = type("Queue", (), {"name": "findie.ai.materials.results"})()
        with pytest.raises(asyncio.CancelledError):
            await client.fetch([{"itemId": "safe", "sources": [{"sourceId": "safe"}]}],
                               datetime.now(timezone.utc) + timedelta(seconds=15))
        assert client.pending == {}

    asyncio.run(run())


def test_result_queue_rejects_overflow_instead_of_dropping_a_material_chunk():
    async def run():
        client = MaterialsClient(Settings(service_token="test"))

        class Channel:
            async def set_qos(self, **kwargs):
                assert kwargs == {"prefetch_count": 1}

            async def declare_queue(self, name, **kwargs):
                assert name == "findie.ai.materials.results"
                assert kwargs["exclusive"] and kwargs["auto_delete"]
                assert kwargs["arguments"]["x-overflow"] == "reject-publish"
                assert kwargs["arguments"]["x-max-length"] == 4
                return self

            async def consume(self, callback):
                assert callback == client.receive

        class Connection:
            async def channel(self, **kwargs):
                assert kwargs["publisher_confirms"] and kwargs["on_return_raises"]
                return Channel()

        await client.start(Connection())

    asyncio.run(run())


def test_unavailable_or_expired_client_does_not_publish_and_close_rejects_pending_fetch():
    async def run():
        client = MaterialsClient(Settings(service_token="test"))
        with pytest.raises(ModelUnavailable):
            await client.fetch([], datetime.now(timezone.utc))
        client.channel = type("Channel", (), {"is_closed": False})()
        client.queue = object()
        with pytest.raises(TimeoutError):
            await client.fetch([{"itemId": "safe", "sources": [{"sourceId": "safe"}]}], datetime.now(timezone.utc))
        assert client.pending == {}
        future = asyncio.get_running_loop().create_future()
        client.pending["safe"] = {"future": future}
        client.channel = None
        await client.close()
        with pytest.raises(ModelUnavailable, match="materials_unavailable"):
            await future
        assert client.pending == {}

    asyncio.run(run())
