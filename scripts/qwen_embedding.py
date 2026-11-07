"""Pinned Qwen text/image/joint embedding for the Colab gateway; no model import on CPU."""

import base64
import binascii
import hashlib
import importlib.metadata as metadata
import importlib.util
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import warnings


MODEL_ID = "Qwen/Qwen3-VL-Embedding-2B"
MODEL_REVISION = "9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda"
SOURCE_SHA256 = "8ffa74a1a6bb759610c57865ea416fd4daf9936cb787520e1112a3e1d547f36a"
DIMENSIONS = 2048
PACKAGE_PINS = {
    "transformers": "4.57.3", "accelerate": "1.12.0", "qwen-vl-utils": "0.0.14",
    "huggingface-hub": "0.36.0", "numpy": "2.2.6", "pillow": "11.3.0",
}
PROFILE = {
    "id": "findie-embedding-colab-v1", "instruction": "Represent the user's input.",
    "dimension": DIMENSIONS, "normalization": "L2", "pooling": "last_nonpadding_token",
    "dtype": "float16", "attention": "sdpa", "max_length": 2048,
    "min_pixels": 4 * 32 * 32, "max_pixels": 256 * 32 * 32,
    "image_patch_size": 16, "image_max_edge": 1024, "batch_size": 1, "source_version": 1,
}
# This fingerprints the pinned Hugging Face revision and inference profile, not an Ollama manifest.
MODEL_DIGEST = hashlib.sha256(json.dumps({
    "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
    "processor_revision": MODEL_REVISION, "inference_source_sha256": SOURCE_SHA256,
    "profile": PROFILE, "packages": PACKAGE_PINS,
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_PIXELS = 20_000_000


def _decode_image(encoded):
    from PIL import Image, ImageOps

    if not isinstance(encoded, str) or not 0 < len(encoded) <= 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Image must be base64, at most 10 MiB decoded.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid base64 image.") from None
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError("Image must be at most 10 MiB.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(BytesIO(raw)) as candidate:
                if candidate.format not in {"JPEG", "PNG", "WEBP"} or getattr(candidate, "n_frames", 1) != 1:
                    raise ValueError("A static JPEG, PNG or WebP image is required.")
                if not 0 < candidate.width * candidate.height <= MAX_SOURCE_PIXELS:
                    raise ValueError("Image exceeds 20 megapixels.")
                candidate.verify()
            with Image.open(BytesIO(raw)) as candidate:
                oriented = ImageOps.exif_transpose(candidate).convert("RGB")
                oriented.thumbnail((PROFILE["image_max_edge"], PROFILE["image_max_edge"]), Image.Resampling.LANCZOS)
                return Image.frombytes("RGB", oriented.size, oriented.tobytes())
        except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError("Invalid image.") from None


def _validate_vector(vector):
    if not isinstance(vector, list) or len(vector) != DIMENSIONS or any(
        type(value) not in (int, float) or not math.isfinite(value) for value in vector
    ):
        raise ValueError("Embedding must contain 2048 finite values.")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Embedding must have a finite, nonzero norm.")
    return [value / norm for value in vector]


class QwenEmbedding:
    model_id = MODEL_ID
    digest = MODEL_DIGEST
    dimensions = DIMENSIONS
    supports_image_text = True

    def __init__(self):
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("Qwen embedding requires a CUDA GPU runtime.")
        for name, version in PACKAGE_PINS.items():
            if metadata.version(name) != version:
                raise RuntimeError(f"Install the pinned dependency {name}=={version} and restart the runtime.")
        import torch.nn.functional as F
        from huggingface_hub import hf_hub_download, snapshot_download
        from qwen_vl_utils import process_vision_info

        source_path = hf_hub_download(MODEL_ID, "scripts/qwen3_vl_embedding.py", revision=MODEL_REVISION)
        if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() != SOURCE_SHA256:
            raise RuntimeError("Qwen inference source checksum mismatch; refusing to import it.")
        spec = importlib.util.spec_from_file_location("findie_qwen_embedding_official", source_path)
        official = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = official
        spec.loader.exec_module(official)
        model_path = snapshot_download(
            MODEL_ID, revision=MODEL_REVISION, ignore_patterns=["*.md", ".gitattributes", "scripts/*"]
        )
        self.model = official.Qwen3VLForEmbedding.from_pretrained(
            model_path, torch_dtype=torch.float16, attn_implementation="sdpa",
            low_cpu_mem_usage=True, trust_remote_code=False, use_safetensors=True,
        ).to("cuda").eval()
        self.processor = official.Qwen3VLProcessor.from_pretrained(model_path, padding_side="right")
        self.torch, self.F, self.process_vision_info = torch, F, process_vision_info

    def embed(self, value):
        if isinstance(value, str) and value.strip() and len(value) <= 20000:
            content = [{"type": "text", "text": value}]
        elif isinstance(value, dict) and set(value) in ({"image"}, {"image", "text"}):
            if "text" in value and (not isinstance(value["text"], str) or not value["text"].strip()
                                    or len(value["text"]) > 5000):
                raise ValueError("Joint image text must contain 1 to 5000 characters.")
            content = [{"type": "image", "image": _decode_image(value["image"]),
                        "min_pixels": PROFILE["min_pixels"], "max_pixels": PROFILE["max_pixels"]}]
            if "text" in value:
                content.append({"type": "text", "text": value["text"]})
        else:
            raise ValueError("Use nonblank text of at most 20000 characters or one base64 image with optional text.")
        conversation = [
            {"role": "system", "content": [{"type": "text", "text": PROFILE["instruction"]}]},
            {"role": "user", "content": content},
        ]
        with self.torch.inference_mode():
            prompt = self.processor.apply_chat_template([conversation], add_generation_prompt=True, tokenize=False)
            images, videos = self.process_vision_info([conversation], image_patch_size=PROFILE["image_patch_size"])
            if any(part["type"] == "image" for part in content) and not images:
                raise RuntimeError("Image preprocessing failed; no text fallback is allowed.")
            inputs = self.processor(
                text=prompt, images=images, videos=videos, padding=True, do_resize=False, return_tensors="pt",
            )
            if inputs.input_ids.shape[1] > PROFILE["max_length"]:
                raise ValueError("Input exceeds the token budget; truncation is disabled.")
            inputs = inputs.to("cuda")
            output = self.model(**inputs, use_cache=False)
            last = inputs.attention_mask.shape[1] - 1 - inputs.attention_mask.flip(1).argmax(1)
            pooled = output.last_hidden_state[self.torch.arange(last.shape[0], device=last.device), last]
            vector = self.F.normalize(pooled.float(), p=2, dim=-1)[0].cpu().tolist()
            return _validate_vector(vector)
