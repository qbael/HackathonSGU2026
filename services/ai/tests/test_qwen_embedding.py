import base64
import ast
from contextlib import nullcontext
import hashlib
import importlib.util
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("qwen_embedding", ROOT / "scripts/qwen_embedding.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Tensor(np.ndarray):
    device = "cpu"

    def flip(self, dimension):
        return np.flip(self, axis=dimension)

    def float(self):
        return self.astype(np.float32)

    def cpu(self):
        return self


class Inputs(dict):
    def __getattr__(self, name):
        return self[name]

    def to(self, device):
        assert device == "cuda"
        return self


def picture(image, **kwargs):
    output = BytesIO()
    image.save(output, **kwargs)
    return base64.b64encode(output.getvalue()).decode("ascii")


def fake_embedder():
    embedder = module.QwenEmbedding.__new__(module.QwenEmbedding)
    embedder.torch = SimpleNamespace(inference_mode=nullcontext, arange=lambda size, device: np.arange(size))
    embedder.F = SimpleNamespace(normalize=lambda value, p, dim: value / np.linalg.norm(value, axis=dim, keepdims=True))
    inputs = Inputs(input_ids=np.array([[1, 2, 0]]).view(Tensor),
                    attention_mask=np.array([[1, 1, 0]]).view(Tensor))
    embedder.processor = Mock(return_value=inputs)
    embedder.processor.apply_chat_template.return_value = "chat template"
    embedder.process_vision_info = Mock(return_value=(None, None))
    hidden = np.zeros((1, 3, 2048), dtype=np.float32).view(Tensor)
    hidden[0, 1, 3] = 2
    hidden[0, 2, 7] = 3
    embedder.model = Mock(return_value=SimpleNamespace(last_hidden_state=hidden))
    return embedder


class QwenEmbeddingTests(unittest.TestCase):
    def test_pinned_identity_includes_profile_and_matches_notebook01(self):
        self.assertEqual(module.MODEL_ID, "Qwen/Qwen3-VL-Embedding-2B")
        self.assertEqual(module.DIMENSIONS, 2048)
        self.assertTrue(module.QwenEmbedding.supports_image_text)
        self.assertRegex(module.MODEL_DIGEST, r"^[a-f0-9]{64}$")
        provenance = {
            "model_id": module.MODEL_ID, "model_revision": module.MODEL_REVISION,
            "processor_revision": module.MODEL_REVISION, "inference_source_sha256": module.SOURCE_SHA256,
            "profile": module.PROFILE, "packages": module.PACKAGE_PINS,
        }
        self.assertEqual(module.MODEL_DIGEST, hashlib.sha256(
            json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        notebook = json.loads((ROOT / "notebooks/colab/01_qwen_embedding.ipynb").read_text())
        source = "".join("".join(cell["source"]) for cell in notebook["cells"])
        self.assertIn(module.MODEL_REVISION, source)
        self.assertIn(module.SOURCE_SHA256, source)
        self.assertEqual(module.PROFILE["instruction"], "Represent the user's input.")

    def test_constructor_requires_gpu_and_checks_source_before_import(self):
        fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        with patch.dict(sys.modules, {"torch": fake_torch}):
            with self.assertRaisesRegex(RuntimeError, "CUDA"):
                module.QwenEmbedding()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.py"
            source.write_text('raise AssertionError("Untrusted source was executed")')
            functional = SimpleNamespace()
            fake_torch.cuda.is_available = lambda: True
            fake_torch.nn = SimpleNamespace(functional=functional)
            hub = SimpleNamespace(hf_hub_download=Mock(return_value=str(source)), snapshot_download=Mock())
            with patch.dict(sys.modules, {
                "torch": fake_torch, "torch.nn": fake_torch.nn, "torch.nn.functional": functional,
                "huggingface_hub": hub, "qwen_vl_utils": SimpleNamespace(process_vision_info=Mock()),
            }), patch.object(module.metadata, "version", side_effect=module.PACKAGE_PINS.__getitem__):
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    module.QwenEmbedding()
            hub.hf_hub_download.assert_called_once_with(
                module.MODEL_ID, "scripts/qwen3_vl_embedding.py", revision=module.MODEL_REVISION)
            hub.snapshot_download.assert_not_called()

    def test_rejects_invalid_inputs_before_inference(self):
        embedder = fake_embedder()
        for value in (None, True, 3, [], "", "  ", "a" * 20001,
                      {}, {"text": "hello"}, {"image": "abcd", "text": "hello"},
                      {"image": "abcd", "text": None}, {"image": "abcd", "text": True},
                      {"image": "abcd", "text": ""}, {"image": "abcd", "text": "  "},
                      {"image": "abcd", "text": "a" * 5001},
                      {"image": "abcd", "text": "hello", "extra": "not allowed"},
                      {"image": 3}, {"image": "https://example.test/image.png"},
                      {"image": "file:///tmp/image.png"}, {"image": "YWJj\n"},
                      {"image": ""}, {"image": base64.b64encode(b"not an image").decode()}):
            with self.subTest(value=str(value)[:80]), self.assertRaises(ValueError):
                embedder.embed(value)
        embedder.model.assert_not_called()
        embedder.processor.assert_not_called()

    def test_image_decode_is_bounded_oriented_and_removes_metadata(self):
        exif = Image.Exif()
        exif[274], exif[270] = 6, "private metadata"
        encoded = picture(Image.new("RGB", (30, 20), "white"), format="JPEG", exif=exif)
        clean = module._decode_image(encoded)
        self.assertEqual(clean.size, (20, 30))
        self.assertEqual(clean.mode, "RGB")
        self.assertFalse(clean.info)
        self.assertFalse(clean.getexif())
        resized = module._decode_image(picture(Image.new("RGB", (1200, 600)), format="PNG"))
        self.assertEqual(resized.size, (1024, 512))
        animated = picture(Image.new("RGB", (16, 16), "red"), format="PNG", save_all=True,
                           append_images=[Image.new("RGB", (16, 16), "blue")], duration=100)
        for unsupported in (animated, picture(Image.new("RGB", (16, 16)), format="GIF")):
            with self.assertRaisesRegex(ValueError, "static"):
                module._decode_image(unsupported)
        with patch.object(module, "MAX_SOURCE_PIXELS", 100):
            with self.assertRaisesRegex(ValueError, "megapixel"):
                module._decode_image(encoded)
        with patch.object(module, "MAX_IMAGE_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "10 MiB"):
                module._decode_image(encoded)

    def test_manual_encoding_pools_last_nonpadding_token_and_normalizes(self):
        embedder = fake_embedder()
        vector = embedder.embed("Ví da đen tại phòng E.205")
        self.assertEqual(len(vector), 2048)
        self.assertEqual(vector[3], 1)
        self.assertEqual(vector[7], 0)
        self.assertAlmostEqual(math.hypot(*vector), 1)
        conversation = embedder.processor.apply_chat_template.call_args.args[0][0]
        self.assertEqual(conversation[0]["content"][0]["text"], module.PROFILE["instruction"])
        embedder.processor.apply_chat_template.assert_called_once_with(
            [conversation], add_generation_prompt=True, tokenize=False)
        self.assertFalse(embedder.model.call_args.kwargs["use_cache"])
        self.assertFalse(embedder.processor.call_args.kwargs["do_resize"])
        self.assertNotIn("truncation", embedder.processor.call_args.kwargs)

    def test_image_encoding_requires_vision_and_rejects_token_overflow(self):
        image = {"image": picture(Image.new("RGB", (32, 32)), format="PNG")}
        embedder = fake_embedder()
        with self.assertRaisesRegex(RuntimeError, "preprocessing"):
            embedder.embed(image)
        embedder.model.assert_not_called()
        embedder.process_vision_info.return_value = ([Image.new("RGB", (32, 32))], None)
        self.assertEqual(embedder.embed(image)[3], 1)
        content = embedder.process_vision_info.call_args.args[0][0][1]["content"][0]
        self.assertIsInstance(content["image"], Image.Image)
        self.assertEqual(content["max_pixels"], module.PROFILE["max_pixels"])
        embedder.model.reset_mock()
        embedder.processor.return_value["input_ids"] = np.ones((1, 2049)).view(Tensor)
        with self.assertRaisesRegex(ValueError, "token budget"):
            embedder.embed("short text")
        embedder.model.assert_not_called()

    def test_joint_encoding_sends_both_modalities_through_one_forward_pass(self):
        embedder = fake_embedder()
        image = Image.new("RGB", (32, 32))
        embedder.process_vision_info.return_value = ([image], None)
        value = {"image": picture(image, format="PNG"), "text": "Thẻ sinh viên. MSSV: 12345678"}
        vector = embedder.embed(value)
        self.assertEqual(vector[3], 1)
        self.assertAlmostEqual(math.hypot(*vector), 1)
        embedder.model.assert_called_once()
        embedder.processor.assert_called_once()
        content = embedder.process_vision_info.call_args.args[0][0][1]["content"]
        self.assertEqual([part["type"] for part in content], ["image", "text"])
        self.assertEqual(content[1]["text"], value["text"])
        self.assertIsInstance(content[0]["image"], Image.Image)
        self.assertEqual(embedder.processor.call_args.kwargs["images"], [image])

    def test_joint_encoding_never_falls_back_to_text_or_truncates(self):
        embedder = fake_embedder()
        value = {"image": picture(Image.new("RGB", (32, 32)), format="PNG"), "text": "a" * 5000}
        with self.assertRaisesRegex(RuntimeError, "preprocessing"):
            embedder.embed(value)
        embedder.model.assert_not_called()
        embedder.process_vision_info.return_value = ([Image.new("RGB", (32, 32))], None)
        self.assertEqual(embedder.embed(value)[3], 1)
        embedder.model.reset_mock()
        embedder.processor.return_value["input_ids"] = np.ones((1, 2049)).view(Tensor)
        with self.assertRaisesRegex(ValueError, "token budget"):
            embedder.embed(value)
        embedder.model.assert_not_called()

    def test_notebook01_joint_helper_matches_single_forward_input_contract(self):
        notebook = json.loads((ROOT / "notebooks/colab/01_qwen_embedding.ipynb").read_text())
        source = next("".join(cell["source"]) for cell in notebook["cells"]
                      if "embedding-validation" in cell.get("metadata", {}).get("tags", []))
        node = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "encode_one")
        node.decorator_list = []
        embedder = fake_embedder()
        scope = {"np": np, "Image": Image, "PROFILE": module.PROFILE, "INSTRUCTION": module.PROFILE["instruction"],
                 "processor": embedder.processor, "process_vision_info": embedder.process_vision_info,
                 "torch": embedder.torch, "model": embedder.model, "F": embedder.F,
                 "validate_vector": lambda vector: vector}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "notebook-joint-helper", "exec"), scope)
        image = Image.new("RGB", (32, 32))
        embedder.process_vision_info.return_value = ([image], None)
        # The notebook uses numpy() on the final tensor, whereas the gateway returns a list.
        with patch.object(Tensor, "numpy", create=True, new=lambda value: np.asarray(value)):
            vector = scope["encode_one"](image=image, text="MSSV: 12345678")
        self.assertEqual(vector[3], 1)
        embedder.model.assert_called_once()
        content = embedder.process_vision_info.call_args.args[0][0][1]["content"]
        self.assertEqual([part["type"] for part in content], ["image", "text"])
        self.assertEqual(content[1]["text"], "MSSV: 12345678")
        for text in ("", " ", True, "a" * 5001):
            with self.subTest(text=str(text)[:20]), self.assertRaises(ValueError):
                scope["encode_one"](image=image, text=text)

    def test_invalid_vectors_never_escape(self):
        for value in ([0.] * 2048, [1.] * 3, [True] * 2048,
                      [math.nan] * 2048, [math.inf] * 2048, [1e308] * 2048):
            with self.subTest(value=value[:3]), self.assertRaises(ValueError):
                module._validate_vector(value)
        self.assertAlmostEqual(math.hypot(*module._validate_vector([1.] * 2048)), 1)


if __name__ == "__main__":
    unittest.main()
