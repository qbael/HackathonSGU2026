import asyncio
from hashlib import sha256
from io import BytesIO
import struct
import zlib

import numpy as np
from PIL import Image, ImageDraw, PngImagePlugin
import pytest

from findie_ai.images import MAX_BYTES, Regions, coarse_preview, normalize, redact, reviewed_mask


def encoded(format="PNG", *, size=(80, 60), **options):
    buffer = BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(buffer, format=format, **options)
    return buffer.getvalue()


def test_coarse_preview_accepts_uniform_tiles_and_rejects_hidden_detail():
    with Image.new("RGB", (12, 4), "white") as grid:
        grid.putpixel((1, 1), (0, 42, 85))
        with grid.resize((192, 64), Image.Resampling.NEAREST) as image:
            valid = BytesIO()
            image.save(valid, format="PNG")
            output, metadata = coarse_preview(valid.getvalue(), "image/png")
            assert metadata["sha256"] == sha256(output).hexdigest()
            assert (metadata["width"], metadata["height"], metadata["sensitiveRegions"]) == (192, 64, [])
            image.putpixel((17, 17), (1, 2, 3))
            detailed = BytesIO()
            image.save(detailed, format="PNG")
            with pytest.raises(ValueError, match="invalid_coarse_preview"):
                coarse_preview(detailed.getvalue(), "image/png")


class Detector:
    def __init__(self, regions, refined=(), documents=()):
        self.regions = regions
        self.refined = refined
        self.documents = documents
        self.input = None
        self.calls = []
        self.document_calls = []

    async def detect_regions(self, image, *, address_only=False, document_only=False):
        self.input = image
        self.calls.append((image, address_only))
        if document_only:
            self.document_calls.append(image)
            if isinstance(self.documents, Exception):
                raise self.documents
            return self.documents
        if address_only and isinstance(self.refined, Exception):
            raise self.refined
        return self.refined if address_only else self.regions


def test_redaction_masks_real_pixels_and_returns_matching_clean_metadata():
    body = encoded()
    detector = Detector([{"label": "face", "bbox": [250, 250, 750, 750]}])
    output, metadata = asyncio.run(redact(detector, body, "image/png"))
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[15:45, 20:60] == 0).all()
        assert (pixels[0, 0] == 255).all()
        assert image.size == (80, 60) and not image.getexif() and not image.info
    assert detector.input == body
    assert len(detector.calls) == 2
    assert metadata == {"contentType": "image/png", "sha256": sha256(output).hexdigest(),
                        "byteSize": len(output), "width": 80, "height": 60,
                        "sensitiveRegions": [{"label": "face", "bbox": [250, 250, 750, 750]}]}
    assert output != body


def test_empty_broad_pass_still_masks_faces_and_passport_numbers_from_focused_pass():
    regions = [
        {"label": "face", "bbox": [50, 250, 250, 750]},
        {"label": "passport_number", "bbox": [400, 300, 800, 375]},
        {"label": "mrz", "bbox": [0, 800, 1000, 1000]},
    ]
    detector = Detector([], documents=regions)
    output, metadata = asyncio.run(redact(detector, encoded(size=(400, 240)), "image/png"))
    assert len(detector.document_calls) == 1
    assert metadata["sensitiveRegions"] == regions[:2]
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[60:180, 20:100] == 0).all()
        assert (pixels[72:90, 160:320] == 0).all()
        assert (pixels[192:240, :] == 255).all()
        assert (pixels[100:120, 160:320] == 255).all()


def test_empty_broad_pass_does_not_skip_a_failing_document_check():
    detector = Detector([], documents=RuntimeError("document_detection_unavailable"))
    with pytest.raises(RuntimeError, match="document_detection_unavailable"):
        asyncio.run(redact(detector, encoded(), "image/png"))


def test_face_only_result_checks_printed_document_fields_before_masking():
    face = {"label": "face", "bbox": [50, 250, 250, 750]}
    identifier = {"label": "identity_number", "bbox": [400, 300, 800, 375]}
    code = {"label": "qr_code", "bbox": [850, 100, 950, 250]}
    detector = Detector([face], documents=[identifier, code])
    output, metadata = asyncio.run(redact(detector, encoded(size=(400, 240)), "image/png"))
    assert metadata["sensitiveRegions"] == [face, identifier, code]
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[72:90, 160:256] == 0).all()
        assert (pixels[72:90, 256:320] == 255).all()
        assert (pixels[24:60, 340:380] == 0).all()


def test_passport_result_masks_signature_and_leaves_mrz_visible():
    face = {"label": "face", "bbox": [50, 250, 250, 750]}
    number = {"label": "passport_number", "bbox": [400, 300, 800, 375]}
    mrz = {"label": "mrz", "bbox": [0, 800, 1000, 1000]}
    signature = {"label": "signature", "bbox": [400, 600, 800, 700]}
    detector = Detector([face, number], documents=[number, mrz, signature])
    body = encoded(size=(400, 240))
    output, metadata = asyncio.run(redact(detector, body, "image/png"))
    assert detector.document_calls == [body]
    assert metadata["sensitiveRegions"] == [face, number, signature]
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[72:90, 160:320] == 0).all()
        assert (pixels[192:240, :] == 255).all()
        assert (pixels[144:168, 160:320] == 0).all()
        assert (pixels[100:120, 160:320] == 255).all()


@pytest.mark.parametrize("label", ["mrz", "qr_code", "barcode"])
def test_cropped_document_without_face_still_checks_other_printed_fields(label):
    initial = {"label": label, "bbox": [0, 800, 1000, 1000]}
    number = {"label": "passport_number", "bbox": [400, 300, 800, 375]}
    detector = Detector([initial], documents=[number])
    _, metadata = asyncio.run(redact(detector, encoded(), "image/png"))
    assert len(detector.document_calls) == 1
    assert metadata["sensitiveRegions"] == ([initial, number] if label != "mrz" else [number])


@pytest.mark.parametrize("label", ["passport_number", "signature"])
def test_passport_fields_are_fully_masked_and_comparison_text_stays_visible(label):
    buffer = BytesIO()
    with Image.new("RGB", (400, 240), "white") as source:
        ImageDraw.Draw(source).text((100, 10), "SAMPLE HOLDER 01/01/2000", fill="black")
        original = np.array(source)
        source.save(buffer, format="PNG")
    region = {"label": label, "bbox": [250, 250, 750, 750]}
    output, metadata = asyncio.run(redact(Detector([region]), buffer.getvalue(), "image/png"))
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[60:180, 100:300] == 0).all()
        np.testing.assert_array_equal(pixels[:50], original[:50])
        np.testing.assert_array_equal(pixels[:, :90], original[:, :90])
    assert metadata["sensitiveRegions"] == [region]


def test_false_mrz_cannot_cover_cccd_number_name_or_birth_date():
    face = {"label": "face", "bbox": [50, 400, 250, 750]}
    number = {"label": "identity_number", "bbox": [350, 400, 850, 450]}
    address = {"label": "address", "bbox": [300, 700, 900, 900]}
    code = {"label": "qr_code", "bbox": [850, 200, 950, 350]}
    false_mrz = {"label": "mrz", "bbox": [300, 400, 900, 900]}
    detector = Detector([face, number, address, code, false_mrz], documents=[false_mrz])
    output, metadata = asyncio.run(redact(detector, encoded(size=(400, 200)), "image/png"))
    assert metadata["sensitiveRegions"] == [face, number, address, code]
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[110:130, 140:340] == 255).all()
        assert (pixels[80:90, 140:260] == 0).all()
        assert (pixels[80:90, 260:340] == 255).all()
        assert (pixels[145:175, 125:350] == 0).all()
        assert (pixels[85:145, 25:95] == 0).all()
        assert (pixels[42:68, 342:378] == 0).all()


def test_document_pass_deduplicates_before_enforcing_total_region_limit():
    faces = [{"label": "face", "bbox": [index * 10, 0, index * 10 + 1, 1]} for index in range(31)]
    number = {"label": "passport_number", "bbox": [250, 250, 750, 350]}
    detector = Detector(faces + [number], documents=[number])
    _, metadata = asyncio.run(redact(detector, encoded(), "image/png"))
    assert metadata["sensitiveRegions"] == faces + [number]
    detector.documents.append({"label": "signature", "bbox": [250, 500, 750, 600]})
    with pytest.raises(ValueError):
        asyncio.run(redact(detector, encoded(), "image/png"))


@pytest.mark.parametrize("documents,error", [
    (RuntimeError("document_detection_unavailable"), RuntimeError),
    ([{"label": "unknown", "bbox": [0, 0, 100, 100]}], ValueError),
    ([{"label": "mrz", "bbox": [0, 0, 100.5, 100]}], ValueError),
    ([{"label": "mrz", "bbox": [0, 0, 0, 0]}], ValueError),
])
def test_document_pass_errors_do_not_return_partially_masked_output(documents, error):
    detector = Detector([{"label": "passport_number", "bbox": [250, 250, 750, 350]}], documents=documents)
    with pytest.raises(error):
        asyncio.run(redact(detector, encoded(), "image/png"))


def test_selected_fields_leave_other_comparison_details_visible():
    detector = Detector([
        {"label": "face", "bbox": [50, 250, 250, 750]},
        {"label": "identity_number", "bbox": [400, 300, 800, 375]},
        {"label": "phone", "bbox": [400, 500, 800, 575]},
        {"label": "qr_code", "bbox": [850, 100, 950, 250]},
    ])
    output, metadata = asyncio.run(redact(detector, encoded(size=(400, 240)), "image/png"))
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[72:90, 160:256] == 0).all()
        assert (pixels[72:90, 256:320] == 255).all()
        assert (pixels[120:138, 160:256] == 0).all()
        assert (pixels[120:138, 256:320] == 255).all()
        assert (pixels[60:180, 20:100] == 0).all()
        assert (pixels[24:60, 340:380] == 0).all()
        assert (pixels[100:110, 160:320] == 255).all()
        assert (pixels[72:90, 120:150] == 255).all()
        assert (pixels[72:90, 154:158] == 255).all()
        assert (pixels[72:90, 158:160] == 0).all()
        assert (pixels[:15] == 255).all()
    assert len(metadata["sensitiveRegions"]) == 4


@pytest.mark.parametrize("label", ["identity_number", "identifier_number", "phone"])
@pytest.mark.parametrize("bbox,start,cut,end", [
    ([100, 250, 900, 750], 10, 58, 90),
    ([0, 250, 1000, 750], 0, 60, 100),
    ([990, 250, 1000, 750], 99, 100, 100),
])
def test_numeric_masks_cover_prefix_and_preserve_suffix_without_internal_padding(label, bbox, start, cut, end):
    detector = Detector([{"label": label, "bbox": bbox}])
    output, metadata = asyncio.run(redact(detector, encoded(size=(100, 40)), "image/png"))
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[10:30, start:cut] == 0).all()
        assert (pixels[10:30, cut:end] == 255).all()
    assert metadata["sensitiveRegions"] == [{"label": label, "bbox": bbox}]


def test_numeric_suffix_does_not_override_an_overlapping_full_privacy_mask():
    detector = Detector([
        {"label": "face", "bbox": [500, 250, 1000, 750]},
        {"label": "identity_number", "bbox": [0, 250, 1000, 750]},
    ])
    output, _ = asyncio.run(redact(detector, encoded(size=(100, 40)), "image/png"))
    with Image.open(BytesIO(output)) as image:
        assert (np.array(image)[10:30, :] == 0).all()


def test_address_refinement_uses_original_crop_and_maps_outward_to_full_image():
    buffer = BytesIO()
    with Image.new("RGB", (200, 100), (80, 120, 160)) as original:
        original.save(buffer, format="PNG")
    initial = {"label": "address", "bbox": [400, 600, 800, 800]}
    detector = Detector([initial], [{"label": "address", "bbox": [101, 99, 901, 899]}])
    output, metadata = asyncio.run(redact(detector, buffer.getvalue(), "image/png"))
    assert [address_only for _, address_only in detector.calls] == [False, True]
    with Image.open(BytesIO(detector.calls[1][0])) as crop:
        assert crop.size == (160, 60)
        assert (np.array(crop) == [80, 120, 160]).all()
    assert metadata["sensitiveRegions"] == [initial, {"label": "address", "bbox": [280, 459, 921, 940]}]
    with Image.open(BytesIO(output)) as image:
        assert image.getpixel((100, 50)) == (0, 0, 0)
        assert image.getpixel((81, 78)) == (0, 0, 0)
        assert image.getpixel((100, 30)) == (80, 120, 160)


@pytest.mark.parametrize("box,size,crop_size,mapped", [
    ([0, 0, 200, 200], (80, 60), (24, 24), [0, 0, 300, 400]),
    ([800, 0, 1000, 200], (80, 60), (24, 24), [700, 0, 1000, 400]),
    ([0, 800, 200, 1000], (80, 60), (24, 24), [0, 600, 300, 1000]),
    ([800, 800, 1000, 1000], (80, 60), (24, 24), [700, 600, 1000, 1000]),
    ([500, 500, 501, 501], (1, 1), (1, 1), [0, 0, 1000, 1000]),
])
def test_address_crop_clamps_edges_and_keeps_at_least_one_pixel(box, size, crop_size, mapped):
    detector = Detector([{"label": "address", "bbox": box}],
                        [{"label": "address", "bbox": [0, 0, 1000, 1000]}])
    _, metadata = asyncio.run(redact(detector, encoded(size=size), "image/png"))
    with Image.open(BytesIO(detector.calls[1][0])) as crop:
        assert crop.size == crop_size
    assert metadata["sensitiveRegions"][-1] == {"label": "address", "bbox": mapped}


def test_address_refinement_deduplicates_exact_boxes_and_keeps_the_total_bounded():
    address = {"label": "address", "bbox": [0, 0, 1000, 1000]}
    detector = Detector([address], [address, address])
    _, metadata = asyncio.run(redact(detector, encoded(), "image/png"))
    assert metadata["sensitiveRegions"] == [address]
    faces = [{"label": "face", "bbox": [index * 10, 0, index * 10 + 1, 1]} for index in range(31)]
    detector = Detector(faces + [{"label": "address", "bbox": [0, 250, 1000, 750]}], [address])
    with pytest.raises(ValueError):
        asyncio.run(redact(detector, encoded(), "image/png"))


@pytest.mark.parametrize("refined,error", [
    (RuntimeError("refinement_unavailable"), RuntimeError),
    ([{"label": "face", "bbox": [0, 0, 100, 100]}], ValueError),
    ([{"label": "address", "bbox": [0, 0, 100.5, 100]}], ValueError),
])
def test_address_refinement_errors_do_not_return_partially_masked_output(refined, error):
    detector = Detector([{"label": "address", "bbox": [250, 250, 750, 750]}], refined)
    with pytest.raises(error):
        asyncio.run(redact(detector, encoded(), "image/png"))


@pytest.mark.parametrize("label", ["qr_code", "barcode"])
def test_codes_cover_truncated_edges_without_covering_nearby_text(label):
    buffer = BytesIO()
    with Image.new("RGB", (1200, 1000), "white") as source:
        draw = ImageDraw.Draw(source)
        for x in range(90, 308, 6):
            draw.rectangle((x, 566, x + 2, 638), fill="black")
        draw.text((90, 641), "NGUYEN VAN THU 01/01/2000", fill="black")
        original = np.array(source)
        source.save(buffer, format="PNG")
    detector = Detector([
        {"label": label, "bbox": [75, 560, 258, 635]},
        {"label": "phone", "bbox": [400, 560, 600, 635]},
    ])
    output, _ = asyncio.run(redact(detector, buffer.getvalue(), "image/png"))
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[637:640, 90:308] == 0).all()
        assert (original[643:665, 90:400] != 255).any()
        np.testing.assert_array_equal(pixels[643:665, 90:400], original[643:665, 90:400])
        assert (pixels[637:640, 480:720] == 255).all()


def test_no_pii_still_reencodes_strips_metadata_and_applies_exif_orientation():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private input"
    body = encoded("JPEG", size=(80, 60), exif=exif, comment=b"private comment")
    output, metadata = asyncio.run(redact(Detector([]), body, "image/jpeg"))
    assert output != body and b"private" not in output and metadata["sensitiveRegions"] == []
    with Image.open(BytesIO(output)) as image:
        assert image.size == (60, 80) and image.format == "PNG"
        assert not image.getexif() and not image.info


def test_normalization_bounds_size_removes_text_chunks_and_flattens_hidden_pixels():
    chunks = PngImagePlugin.PngInfo()
    chunks.add_text("note", "private input")
    output = asyncio.run(normalize(encoded(size=(3200, 100), pnginfo=chunks), "image/png"))
    with Image.open(BytesIO(output)) as image:
        assert image.size == (1600, 50) and not image.info
    assert b"private" not in output
    buffer = BytesIO()
    with Image.new("RGBA", (2, 2), (255, 0, 0, 0)) as image:
        image.save(buffer, format="PNG")
    output = asyncio.run(normalize(buffer.getvalue(), "image/png"))
    with Image.open(BytesIO(output)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("body,mime", [
    (b"", "image/png"), (b"not an image", "image/png"), (encoded(), "image/jpeg"),
    (encoded("GIF"), "image/png"), (encoded(), "image/gif"),
    (encoded()[:40], "image/png"), (b"x" * (MAX_BYTES + 1), "image/png"),
])
def test_invalid_input_fails_before_model_call(body, mime):
    detector = Detector([])
    with pytest.raises(ValueError):
        asyncio.run(redact(detector, body, mime))
    assert detector.input is None


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_supported_image_formats_normalize_to_clean_png(format, mime):
    output = asyncio.run(normalize(encoded(format), mime))
    with Image.open(BytesIO(output)) as image:
        assert image.format == "PNG" and image.size == (80, 60) and not image.info


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_animation_is_rejected_before_decode(format, mime):
    buffer = BytesIO()
    with Image.new("RGB", (5, 5), "white") as first, Image.new("RGB", (5, 5), "black") as second:
        first.save(buffer, format=format, save_all=True, append_images=[second], duration=100, loop=0)
    with pytest.raises(ValueError):
        asyncio.run(normalize(buffer.getvalue(), mime))


def test_pixel_axis_limits_are_rejected_before_decode():
    for width, height in ((10001, 1), (7000, 6000)):
        body = bytearray(encoded())
        body[16:24] = struct.pack(">II", width, height)
        body[29:33] = struct.pack(">I", zlib.crc32(body[12:29]))
        with pytest.raises(ValueError):
            asyncio.run(normalize(bytes(body), "image/png"))


@pytest.mark.parametrize("region", [
    {"label": "face", "bbox": [0, 0, float("nan"), 100]},
    {"label": "face", "bbox": [0, 0, float("inf"), 100]},
    {"label": "face", "bbox": [0, 0, 1001, 100]},
    {"label": "face", "bbox": [50, 0, 40, 100]},
    {"label": "face", "bbox": [0, 20, 100, 20]},
    {"label": "face", "bbox": [False, 0, 100, 100]},
    {"label": "face", "bbox": ["0", 0, 100, 100]},
    {"label": "face", "bbox": [0, 0, 100.5, 100]},
    {"label": "unknown", "bbox": [0, 0, 100, 100]},
    {"label": "identity_document", "bbox": [0, 0, 1000, 1000]},
    {"label": "payment_card", "bbox": [0, 0, 1000, 1000]},
    {"label": "personal_text", "bbox": [0, 0, 100, 100]},
    {"label": "name", "bbox": [0, 0, 100, 100]},
    {"label": "birth_date", "bbox": [0, 0, 100, 100]},
    {"label": "face", "bbox": [0, 0, 100, 100], "text": "private input"},
])
def test_untrusted_regions_fail_closed(region):
    with pytest.raises(ValueError):
        asyncio.run(redact(Detector([region]), encoded(), "image/png"))


def test_region_count_is_bounded():
    with pytest.raises(ValueError):
        Regions(regions=[{"label": "face", "bbox": [0, 0, 100, 100]}] * 33)


def test_model_error_does_not_return_raw_input_as_output():
    class BrokenDetector:
        async def detect_regions(self, _image):
            raise RuntimeError("model_unavailable")

    with pytest.raises(RuntimeError, match="model_unavailable"):
        asyncio.run(redact(BrokenDetector(), encoded(), "image/png"))


@pytest.mark.parametrize("label", ["identity_number", "passport_number", "mrz", "signature"])
def test_reviewed_masks_cover_complete_fields_without_changing_surrounding_pixels(label):
    regions = [{"label": label, "bbox": [250, 250, 750, 750]}]
    output, metadata = reviewed_mask(encoded(size=(400, 240)), "image/png", regions)
    with Image.open(BytesIO(output)) as image:
        pixels = np.array(image)
        assert (pixels[60:180, 100:300] == 0).all()
        assert (pixels[:50] == 255).all()
        assert (pixels[:, :90] == 255).all()
        assert image.size == (400, 240) and not image.info
    assert metadata["sha256"] == sha256(output).hexdigest()
    assert metadata["sensitiveRegions"] == regions
    empty, _ = reviewed_mask(encoded(), "image/png", [])
    assert empty == encoded()
    with pytest.raises(ValueError):
        reviewed_mask(encoded(), "image/png", [{"label": "face", "bbox": [750, 0, 250, 1000]}])
    with pytest.raises(ValueError):
        reviewed_mask(encoded("JPEG"), "image/jpeg", regions)
    with pytest.raises(ValueError):
        reviewed_mask(encoded(), "image/png", regions * 33)
