"""Bounded in-memory decoding, metadata removal and solid privacy masks."""

import asyncio
from hashlib import sha256
from io import BytesIO
import math
from typing import Annotated, Literal

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator


# Explicit Pillow limit to guard against DecompressionBomb DoS attacks
Image.MAX_IMAGE_PIXELS = 25_000_000

MAX_BYTES = 10 * 1024 * 1024
MIME_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
Coordinate = Annotated[int, Field(strict=True, ge=0, le=1000)]


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["face", "identity_number", "identifier_number", "passport_number", "mrz", "signature", "phone", "address", "qr_code", "barcode"]
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]

    @model_validator(mode="after")
    def ordered(self):
        if self.bbox[0] >= self.bbox[2] or self.bbox[1] >= self.bbox[3]:
            raise ValueError("invalid_region")
        return self


class ReviewedRegion(Region):
    label: Literal["face", "identity_number", "identifier_number", "passport_number", "mrz", "signature", "phone", "address", "qr_code", "barcode", "text"]


class Regions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regions: list[Region] = Field(max_length=32)


def _decode(body, content_type):
    if content_type not in MIME_FORMATS or not body or len(body) > MAX_BYTES:
        raise ValueError("invalid_image")
    try:
        # nosemgrep: findie-python-pillow-unbounded-open
        with Image.open(BytesIO(body), formats=list(MIME_FORMATS.values())) as source:
            width, height = source.size
            if (source.format != MIME_FORMATS[content_type] or getattr(source, "n_frames", 1) != 1
                    or max(width, height) > 10000 or width * height > 25_000_000):
                raise ValueError("invalid_image")
            source.load()
            with ImageOps.exif_transpose(source) as oriented:
                # shortcut: 1600px bounds model payloads; evaluate small-region recall before increasing it.
                oriented.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                with oriented.convert("RGBA") as rgba, Image.new("RGB", rgba.size, "white") as image:
                    image.paste(rgba, mask=rgba.getchannel("A"))
                    return np.array(image)
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("invalid_image") from None


def _encode(image):
    output = BytesIO()
    with Image.fromarray(image) as clean:
        clean.save(output, format="PNG")
    data = output.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError("output_too_large")
    return data


async def normalize(body: bytes, content_type: str) -> bytes:
    return await asyncio.to_thread(lambda: _encode(_decode(body, content_type)))


def coarse_preview(body: bytes, content_type: str) -> tuple[bytes, dict]:
    if content_type != "image/png":
        raise ValueError("invalid_coarse_preview")
    image = _decode(body, content_type)
    height, width = image.shape[:2]
    if not 64 <= width <= 192 or not 64 <= height <= 192 or width % 16 or height % 16:
        raise ValueError("invalid_coarse_preview")
    tiles = image.reshape(height // 16, 16, width // 16, 16, 3)
    if not np.all(tiles == tiles[:, :1, :, :1, :]):
        raise ValueError("invalid_coarse_preview")
    output = _encode(image)
    return output, {"contentType": "image/png", "sha256": sha256(output).hexdigest(),
                    "byteSize": len(output), "width": width, "height": height, "sensitiveRegions": []}


def _mask(image, regions, *, partial_identifiers=True):
    height, width = image.shape[:2]
    for region in regions:
        padding = max(2, math.ceil(min(width, height) / (200 if region.label in {"qr_code", "barcode"} else 500)))
        x1, y1, x2, y2 = region.bbox
        left, top = max(0, math.floor(x1 * width / 1000) - padding), max(0, math.floor(y1 * height / 1000) - padding)
        right, bottom = min(width - 1, math.ceil(x2 * width / 1000) + padding - 1), min(height - 1, math.ceil(y2 * height / 1000) + padding - 1)
        if partial_identifiers and region.label in {"identity_number", "identifier_number", "phone"}:
            # shortcut: bbox width approximates the last 40% of horizontal digits; use digit boxes for rotated/exact suffixes.
            right = min(width - 1, math.ceil((x1 + (x2 - x1) * 0.6) * width / 1000) - 1)
        cv2.rectangle(image, (left, top), (right, bottom), (0, 0, 0), thickness=cv2.FILLED)
    return _encode(image)


def reviewed_mask(body: bytes, content_type: str, regions) -> tuple[bytes, dict]:
    # Development importer binds these manually reviewed coordinates to the exact input hash.
    if content_type != "image/png" or len(regions) > 32:
        raise ValueError("invalid_reviewed_masks")
    regions = [ReviewedRegion.model_validate(region) for region in regions]
    image = _decode(body, content_type)
    height, width = image.shape[:2]
    output = _mask(image, regions, partial_identifiers=False)
    return output, {"contentType": "image/png", "sha256": sha256(output).hexdigest(),
                    "byteSize": len(output), "width": width, "height": height,
                    "sensitiveRegions": [region.model_dump(mode="json") for region in regions]}


async def redact(ollama, body: bytes, content_type: str) -> tuple[bytes, dict]:
    image = await asyncio.to_thread(_decode, body, content_type)
    height, width = image.shape[:2]
    clean = await asyncio.to_thread(_encode, image)
    regions = [region for region in Regions(regions=await ollama.detect_regions(clean)).regions if region.label != "mrz"]
    if not regions or any(region.label in {"face", "identity_number", "identifier_number", "passport_number", "signature", "qr_code", "barcode"}
           for region in regions):
        # An empty broad pass can also miss a whole document; confirm with the focused pass.
        document_regions = [region for region in Regions(regions=await ollama.detect_regions(clean, document_only=True)).regions
                            if region.label != "mrz"]
        regions = Regions(regions=list({(region.label, region.bbox): region
                                        for region in [*regions, *document_regions]}.values())).regions
    addresses = [region.bbox for region in regions if region.label == "address"]
    if addresses:
        left = math.floor(min(box[0] for box in addresses) * width / 1000)
        top = math.floor(min(box[1] for box in addresses) * height / 1000)
        right = math.ceil(max(box[2] for box in addresses) * width / 1000)
        bottom = math.ceil(max(box[3] for box in addresses) * height / 1000)
        margin_x, margin_y = (right - left) // 2, bottom - top
        left, top = max(0, left - margin_x), max(0, top - margin_y)
        right, bottom = min(width, right + margin_x), min(height, bottom + margin_y)
        crop = await asyncio.to_thread(_encode, image[top:bottom, left:right])
        refined = Regions(regions=await ollama.detect_regions(crop, address_only=True)).regions
        for region in refined:
            if region.label != "address":
                raise ValueError("invalid_address_region")
            x1, y1, x2, y2 = region.bbox
            regions.append(Region(label="address", bbox=(
                math.floor((left * 1000 + x1 * (right - left)) / width),
                math.floor((top * 1000 + y1 * (bottom - top)) / height),
                math.ceil((left * 1000 + x2 * (right - left)) / width),
                math.ceil((top * 1000 + y2 * (bottom - top)) / height),
            )))
        regions = Regions(regions=list({(region.label, region.bbox): region for region in regions}.values())).regions
    output = await asyncio.to_thread(_mask, image, regions)
    return output, {
        "contentType": "image/png", "sha256": sha256(output).hexdigest(), "byteSize": len(output),
        "width": width, "height": height, "sensitiveRegions": [region.model_dump(mode="json") for region in regions],
    }
