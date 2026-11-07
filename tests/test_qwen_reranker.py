"""CPU contract checks; no model import, download, or image persistence."""

from datetime import datetime, timedelta, timezone
import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qwen_reranker", ROOT / "scripts/qwen_reranker.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def payload(**changes):
    return {"model": module.RERANKER_MODEL_ID, "text": "ví màu đen", "images": [],
            "candidates": [{"itemId": str(uuid4()), "text": "Ví da màu đen"}],
            "deadlineAt": (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat(), **changes}


class RerankerTests(unittest.TestCase):
    def reranker(self):
        model = module.QwenReranker.__new__(module.QwenReranker)
        model.decode_image = Mock(side_effect=lambda value: Mock(name=value))
        model._score = Mock(return_value=0.8)
        return model

    def test_text_and_image_scores_remain_independent_and_use_best_query_image(self):
        model = self.reranker()
        request = payload(images=["front", "back"])
        request["candidates"][0]["image"] = "processed"
        model._score.side_effect = [0.2, 0.9, 0.7]
        result = model.rerank(request)
        self.assertEqual(result, [{"itemId": request["candidates"][0]["itemId"], "imageScore": 0.9, "textScore": 0.7}])
        self.assertEqual(model._score.call_count, 3)
        for call in model._score.call_args_list[:2]:
            self.assertEqual([part["type"] for part in call.args[0]], ["image"])
        self.assertEqual([part["type"] for part in model._score.call_args.args[0]], ["text"])
        for call in model._score.call_args_list:
            self.assertEqual([part["type"] for part in call.args[1]], ["image", "text"])
        for call in model.decode_image.mock_calls:
            self.assertNotIn("http", str(call))

    def test_all_twenty_candidates_are_scored_and_twenty_one_is_rejected(self):
        request = payload(candidates=[{"itemId": str(uuid4()), "text": "Ví"} for _ in range(20)])
        model = self.reranker()
        self.assertEqual(len(model.rerank(request)), 20)
        self.assertEqual(model._score.call_count, 20)
        request["candidates"].append({"itemId": str(uuid4()), "text": "Ví"})
        with self.assertRaises(ValueError):
            self.reranker().rerank(request)

    def test_input_validation_precedes_inference(self):
        request = payload()
        changes = [
            {"model": "other"}, {"unknown": True}, {"text": 1}, {"text": "x" * 2001},
            {"images": ["x"] * 4}, {"text": "", "images": []}, {"candidates": []},
            {"candidates": [{"itemId": "invalid", "text": "Ví"}]},
            {"candidates": request["candidates"] * 2},
            {"candidates": [{"itemId": str(uuid4()), "text": "x" * 5202}]},
            {"deadlineAt": "2026-01-01T00:00:00"},
            {"deadlineAt": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()},
        ]
        for change in changes:
            with self.subTest(change=list(change)):
                model = self.reranker()
                with self.assertRaises(ValueError):
                    model.rerank(request | change)
                model._score.assert_not_called()

    def test_deadline_never_returns_partial_scores(self):
        model = self.reranker()
        request = payload(candidates=[{"itemId": str(uuid4()), "text": "Ví"} for _ in range(2)])
        with patch.object(module, "remaining", side_effect=[15, 14, 13, 12, TimeoutError("expired")]):
            with self.assertRaises(TimeoutError):
                model.rerank(request)
        self.assertEqual(model._score.call_count, 1)

    def test_notebook_optional_model_reuses_weights_and_recovers_from_failure(self):
        notebook = json.loads((ROOT / "notebooks/colab/04_full_stack_ollama_ngrok.ipynb").read_text())
        source = next("".join(cell["source"]) for cell in notebook["cells"]
                      if "reranker-load" in cell.get("metadata", {}).get("tags", []))
        runtime = {"RERANKER_MODEL_ID": module.RERANKER_MODEL_ID, "RERANKER_DIGEST": module.RERANKER_DIGEST,
                   "revisions": {"embedding": "keep"}, "_decode_image": Mock(), "synthetic_image": "safe-demo"}
        loaded = SimpleNamespace(model_id=module.RERANKER_MODEL_ID, digest=module.RERANKER_DIGEST, rerank=Mock())
        runtime["QwenReranker"] = Mock(return_value=loaded)
        with redirect_stdout(StringIO()):
            exec(source, runtime)
            exec(source, runtime)
        runtime["QwenReranker"].assert_called_once()
        self.assertIs(runtime["qwen_reranker"], loaded)
        loaded.rerank.side_effect = RuntimeError("private upstream details")
        output = StringIO()
        torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=Mock()))
        with patch.dict("sys.modules", {"torch": torch}), redirect_stdout(output):
            exec(source, runtime)
        self.assertIsNone(runtime["qwen_reranker"])
        self.assertEqual(runtime["revisions"], {"embedding": "keep"})
        self.assertNotIn("private", output.getvalue())
        torch.cuda.empty_cache.assert_called_once()

    def test_notebook_export_contains_only_public_optional_model_configuration(self):
        notebook = json.loads((ROOT / "notebooks/colab/04_full_stack_ollama_ngrok.ipynb").read_text())
        source = next("".join(cell["source"]) for cell in notebook["cells"]
                      if "export" in cell.get("metadata", {}).get("tags", []))
        config_spec = importlib.util.spec_from_file_location("safe_model_settings", ROOT / "scripts/configure_ollama.py")
        config_module = importlib.util.module_from_spec(config_spec)
        config_spec.loader.exec_module(config_module)
        for loaded in (None, SimpleNamespace(digest=module.RERANKER_DIGEST)):
            with self.subTest(enabled=loaded is not None), tempfile.TemporaryDirectory() as directory:
                scope = {"json": json, "Path": Path, "WORK": Path(directory),
                         "tunnel": SimpleNamespace(public_url="https://example.ngrok.app"),
                         "EMBEDDING_MODEL": "embedding", "REDACTION_MODEL": "redaction", "DIMENSIONS": 2048,
                         "revisions": {"embedding": "a" * 64, "redaction": "b" * 64}, "qwen_reranker": loaded}
                with patch.dict("sys.modules", {"google.colab": SimpleNamespace(files=Mock())}), redirect_stdout(StringIO()):
                    exec(source, scope)
                exported = json.loads((Path(directory) / "findie-colab.json").read_text())
                self.assertEqual(exported["AI_RERANKER_REVISION"], module.RERANKER_DIGEST if loaded else "")
                self.assertNotIn("OLLAMA_API_KEY", exported)
                self.assertEqual(config_module.settings(exported, "s" * 40)["AI_RERANKER_MODEL"], module.RERANKER_MODEL_ID)

    def test_invalid_image_never_becomes_text_only(self):
        model = self.reranker()
        model.decode_image.side_effect = ValueError("bad image")
        with self.assertRaises(ValueError):
            model.rerank(payload(images=["invalid-image"]))
        model._score.assert_not_called()


if __name__ == "__main__":
    unittest.main()
