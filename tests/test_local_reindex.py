import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("local_reindex", ROOT / "scripts/local_reindex.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReindexTests(unittest.TestCase):
    def test_unready_or_changed_model_cannot_reset_jobs(self):
        environment = {"AI_SERVICE_TOKEN": "test", "Ai__EmbeddingModelId": "current", "Ai__EmbeddingRevision": "a" * 64}
        for status in (None, {"inferenceReady": False},
                       {"inferenceReady": True, "models": {"embedding": "old"}, "modelRevision": "a" * 64},
                       {"inferenceReady": True, "models": {"embedding": "current"}, "modelRevision": "b" * 64}):
            with self.subTest(status=status), patch.object(module, "load_environment", return_value=environment), \
                    patch.object(module, "get_json", return_value=status), \
                    patch.object(module.subprocess, "check_output") as database, patch.object(module, "psql") as sql:
                with self.assertRaises(RuntimeError):
                    module.main()
                database.assert_not_called()
                sql.assert_not_called()


if __name__ == "__main__":
    unittest.main()
