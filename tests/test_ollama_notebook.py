"""CPU checks of Ollama notebooks; no model download or network."""

import ast
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks/colab/03_ollama_search.ipynb"
INSTALL_NOTEBOOKS = (NOTEBOOK, NOTEBOOK.with_name("04_full_stack_ollama_ngrok.ipynb"))


def tagged_source(tag, path=NOTEBOOK):
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return next("".join(cell["source"]) for cell in notebook["cells"]
                if tag in cell["metadata"].get("tags", []))


class OllamaNotebookTests(unittest.TestCase):
    def test_full_stack_restarts_exited_ollama_before_opening_gateway(self):
        notebook = INSTALL_NOTEBOOKS[1]
        install = ast.parse(tagged_source("install", notebook))
        ensure = next(node for node in install.body if isinstance(node, ast.FunctionDef)
                      and node.name == "ensure_ollama_ready")
        with tempfile.TemporaryDirectory() as directory:
            api = Mock(side_effect=[ConnectionRefusedError(), {"models": []}, {"models": []}])
            run = Mock()
            stopped = SimpleNamespace(poll=Mock(return_value=0))
            scope = {"ollama_api": api, "ollama_process": stopped, "ollama_env": {},
                     "WORK": Path(directory), "subprocess": run, "time": Mock(),
                     "NGROK_AUTHTOKEN": "test-ngrok-token"}
            exec(compile(ast.Module(body=[ensure], type_ignores=[]), "<ollama-startup>", "exec"), scope)
            startup = tagged_source("gateway-start", notebook)
            exec(startup.split('\nif "gateway_server"', 1)[0], scope)
            scope["ensure_ollama_ready"]()
            run.Popen.assert_called_once()
            self.assertEqual(run.Popen.call_args.args[0], ["ollama", "serve"])
            self.assertIs(scope["ollama_process"], run.Popen.return_value)
            self.assertEqual(api.call_args_list, [call("/api/tags", timeout=1)] * 3)

    def test_full_stack_redaction_matches_runtime_fields_prompt_and_options(self):
        root = NOTEBOOK.parents[2]
        source = tagged_source("inference-check", INSTALL_NOTEBOOKS[1])
        scope = {}
        exec(source.split("\n\ndef chunk", 1)[0], scope)
        image_tree = ast.parse((root / "services/ai/findie_ai/images.py").read_text(encoding="utf-8"))
        region = next(node for node in image_tree.body if isinstance(node, ast.ClassDef) and node.name == "Region")
        labels = next(node.annotation.slice for node in region.body
                      if isinstance(node, ast.AnnAssign) and node.target.id == "label")
        self.assertEqual(scope["REGIONS_SCHEMA"]["$defs"]["Region"]["properties"]["label"]["enum"],
                         list(ast.literal_eval(labels)))
        ollama_tree = ast.parse((root / "services/ai/findie_ai/ollama.py").read_text(encoding="utf-8"))
        prompt = next(ast.literal_eval(value.orelse if isinstance(value, ast.IfExp) else value)
                      for node in ast.walk(ollama_tree) if isinstance(node, ast.Dict)
                      for key, value in zip(node.keys, node.values)
                      if isinstance(key, ast.Constant) and key.value == "prompt")
        self.assertEqual(scope["REDACTION_PROMPT"], prompt)
        runtime_options = next(ast.literal_eval(value) for node in ast.walk(ollama_tree) if isinstance(node, ast.Dict)
                               for key, value in zip(node.keys, node.values)
                               if isinstance(key, ast.Constant) and key.value == "options")
        notebook_options = next(ast.literal_eval(value) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Dict)
                                for key, value in zip(node.keys, node.values)
                                if isinstance(key, ast.Constant) and key.value == "options")
        self.assertEqual(notebook_options, runtime_options)

    def test_full_stack_redaction_requires_integer_box_coordinates(self):
        source = tagged_source("inference-check", INSTALL_NOTEBOOKS[1])
        scope = {}
        exec(source.split("\n\ndef chunk", 1)[0], scope)
        bbox = scope["REGIONS_SCHEMA"]["$defs"]["Region"]["properties"]["bbox"]
        self.assertTrue(all(coordinate["type"] == "integer" for coordinate in bbox["prefixItems"]))
        validation = source[source.index('for region in regions["regions"]:'):source.index("\ncurrent =")]
        for coordinate in (0, 0.5, True):
            scope["regions"] = {"regions": [{"label": "identity_number", "bbox": [coordinate, 0, 100, 100]}]}
            with self.subTest(coordinate=coordinate):
                if type(coordinate) is int:
                    exec(validation, scope)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Vision bbox sai schema"):
                        exec(validation, scope)

    def test_qwen_dependency_install_requires_restart_before_loading(self):
        notebook = INSTALL_NOTEBOOKS[1]
        scope = {}
        exec(tagged_source("qwen-source", notebook), scope)
        versions = scope["PACKAGE_PINS"] | {"torch": "2.8.0", "torchvision": "0.23.0", "torchaudio": "2.8.0"}
        versions["transformers"] = "5.0.0"
        source = tagged_source("qwen-setup", notebook)

        def install(*_args, **kwargs):
            self.assertTrue(kwargs["check"])
            versions.update(scope["PACKAGE_PINS"])

        with patch.object(scope["sys"], "version_info", (3, 13, 0)), \
                patch.object(scope["metadata"], "version", side_effect=versions.__getitem__), \
                patch("subprocess.run", side_effect=install) as run:
            for _attempt in range(2):
                with self.assertRaisesRegex(RuntimeError, "Restart session"):
                    exec(source, scope)
            run.assert_called_once()
            self.assertTrue(scope["_qwen_restart_required"])
            with self.assertRaisesRegex(RuntimeError, "Restart session"):
                exec(tagged_source("qwen-load", notebook), scope)
            scope.pop("_qwen_restart_required")
            exec(source, scope)
            run.assert_called_once()

    def test_full_stack_reuses_loaded_qwen_and_rejects_changed_profile(self):
        notebook = INSTALL_NOTEBOOKS[1]
        scope = {}
        exec(tagged_source("qwen-source", notebook), scope)
        loaded = SimpleNamespace(model_id=scope["MODEL_ID"], digest=scope["MODEL_DIGEST"], dimensions=2048,
                                 supports_image_text=True)
        loader = Mock(return_value=loaded)
        scope.update(QwenEmbedding=loader, EMBEDDING_MODEL=loaded.model_id, revisions={})
        source = tagged_source("qwen-load", notebook)
        source = source[source.index('if "qwen_embedding" not in globals():'):]
        exec(source, scope)
        exec(source, scope)
        loader.assert_called_once_with()
        self.assertEqual(scope["revisions"][loaded.model_id], scope["MODEL_DIGEST"])
        scope["MODEL_DIGEST"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "không khớp"):
            exec(source, scope)
        scope["MODEL_DIGEST"] = loaded.digest
        loaded.supports_image_text = False
        with self.assertRaisesRegex(RuntimeError, "Wrapper Qwen cũ"):
            exec(source, scope)

    def test_full_stack_exports_qwen_identity_without_credentials(self):
        notebook = INSTALL_NOTEBOOKS[1]
        runtime = {}
        exec(tagged_source("qwen-source", notebook), runtime)
        with tempfile.TemporaryDirectory() as directory:
            scope = {
                "json": json, "WORK": Path(directory),
                "tunnel": SimpleNamespace(public_url="https://example.ngrok.app"),
                "EMBEDDING_MODEL": runtime["MODEL_ID"], "DIMENSIONS": runtime["DIMENSIONS"],
                "REDACTION_MODEL": "qwen3-vl:4b-instruct",
                "revisions": {runtime["MODEL_ID"]: runtime["MODEL_DIGEST"], "qwen3-vl:4b-instruct": "b" * 64},
                "NGROK_AUTHTOKEN": "private-ngrok-token", "FINDIE_OLLAMA_TOKEN": "private-gateway-token",
            }
            files = Mock()
            with patch.dict("sys.modules", {"google.colab": SimpleNamespace(files=files)}):
                exec(tagged_source("export", notebook), scope)
            output = (Path(directory) / "findie-colab.json").read_text()
            config = json.loads(output)
            self.assertEqual(config["AI_EMBEDDING_MODEL"], "Qwen/Qwen3-VL-Embedding-2B")
            self.assertEqual(config["AI_EMBEDDING_REVISION"], runtime["MODEL_DIGEST"])
            self.assertEqual(config["AI_EMBEDDING_DIMENSIONS"], 2048)
            self.assertEqual(config["AI_EMBEDDING_QUERY_INSTRUCTION"], "")
            self.assertNotIn(scope["NGROK_AUTHTOKEN"], output)
            self.assertNotIn(scope["FINDIE_OLLAMA_TOKEN"], output)
            files.download.assert_called_once_with(str(Path(directory) / "findie-colab.json"))

    def installation(self, notebook, directory):
        installer = b"pinned installer"
        scope = {
            "hashlib": hashlib, "shutil": Mock(), "subprocess": Mock(),
            "os": Mock(), "urllib": Mock(), "WORK": Path(directory),
            "OLLAMA_VERSION": "test-version",
            "INSTALLER_SHA256": hashlib.sha256(installer).hexdigest(),
        }
        scope["subprocess"].CalledProcessError = subprocess.CalledProcessError
        scope["subprocess"].PIPE = subprocess.PIPE
        scope["subprocess"].STDOUT = subprocess.STDOUT
        scope["os"].environ = {"PATH": "/usr/bin"}
        scope["urllib"].request.urlopen.return_value = io.BytesIO(installer)
        source = tagged_source("install", notebook).split("\nsubprocess.run([sys.executable", 1)[0]
        return source, scope

    def test_installer_provisions_missing_zstd_and_preserves_version(self):
        for notebook in INSTALL_NOTEBOOKS:
            for uid in (0, 1000):
                for has_zstd in (False, True):
                    with self.subTest(notebook=notebook.name, uid=uid, zstd=has_zstd), tempfile.TemporaryDirectory() as directory:
                        source, scope = self.installation(notebook, directory)
                        scope["os"].geteuid.return_value = uid
                        scope["shutil"].which.side_effect = lambda name: name != "zstd" or has_zstd
                        exec(source, scope)
                        expected = [call(["nvidia-smi"], check=True)]
                        if not has_zstd:
                            apt = ["apt-get"] if uid == 0 else ["sudo", "apt-get"]
                            expected += [call([*apt, "update"], check=True),
                                         call([*apt, "install", "-y", "zstd"], check=True)]
                        expected.append(call(["sh", str(Path(directory) / "install.sh")],
                                             env=scope["ollama_env"], check=True,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
                        self.assertEqual(scope["subprocess"].run.call_args_list, expected)
                        self.assertEqual(scope["ollama_env"]["OLLAMA_VERSION"], "test-version")

    def test_installation_stops_on_checksum_or_package_failure(self):
        for notebook in INSTALL_NOTEBOOKS:
            for failure in ("checksum", "package"):
                with self.subTest(notebook=notebook.name, failure=failure), tempfile.TemporaryDirectory() as directory:
                    source, scope = self.installation(notebook, directory)
                    scope["os"].geteuid.return_value = 0
                    scope["shutil"].which.side_effect = lambda name: name != "zstd"
                    if failure == "checksum":
                        scope["INSTALLER_SHA256"] = "0" * 64
                        error = RuntimeError
                    else:
                        scope["subprocess"].run.side_effect = [None, subprocess.CalledProcessError(1, ["apt-get", "update"])]
                        error = subprocess.CalledProcessError
                    with self.assertRaises(error):
                        exec(source, scope)
                    self.assertFalse((Path(directory) / "install.sh").exists())
                    self.assertNotIn("ollama_env", scope)

    def test_installer_failure_exposes_captured_output(self):
        for notebook in INSTALL_NOTEBOOKS:
            with self.subTest(notebook=notebook.name), tempfile.TemporaryDirectory() as directory:
                source, scope = self.installation(notebook, directory)
                scope["shutil"].which.return_value = "/usr/bin/tool"
                scope["subprocess"].run.side_effect = [None, subprocess.CalledProcessError(
                    1, ["sh", "install.sh"], output="ERROR: This version requires zstd for extraction.")]
                with self.assertRaisesRegex(RuntimeError, "requires zstd"):
                    exec(source, scope)

    def helpers(self, api=None):
        scope = {"math": math, "MODEL": "test-model:1", "DIMENSIONS": 2,
                 "ollama_api": api, "QUERY_INSTRUCTION": "test instruction"}
        exec(tagged_source("embedding-helpers"), scope)
        return scope

    def test_python_cells_are_valid_and_outputs_are_cleared(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "python3")
        for index, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])
                compile("".join(cell["source"]), f"{NOTEBOOK.name}:cell{index}", "exec")

    def test_embedding_rejects_invalid_vectors_and_truncation(self):
        api = Mock(return_value={"model": "test-model:1", "embeddings": [[3, 4]]})
        scope = self.helpers(api)
        self.assertEqual(scope["embed"](["Ví đen phòng E.205"]), [[0.6, 0.8]])
        api.assert_called_once_with("/api/embed", {
            "model": "test-model:1", "input": ["Ví đen phòng E.205"],
            "dimensions": 2, "truncate": False,
        })
        for invalid in ([0, 0], [1], [math.nan, 1], [math.inf, 1], [True, 1], ["1", 1]):
            with self.subTest(vector=invalid), self.assertRaises(ValueError):
                scope["validate_vector"](invalid, 2)
        for invalid in ([], [""], [" "], [1], "query"):
            with self.subTest(query=invalid), self.assertRaises(ValueError):
                scope["embed"](invalid)
        api.return_value = {"model": "test-model:1", "embeddings": []}
        with self.assertRaisesRegex(ValueError, "số lượng"):
            scope["embed"](["E.205"])

    def test_ranking_is_deterministic_and_rejects_bad_dimensions(self):
        rank = self.helpers()["rank_documents"]
        records = [{"id": "b", "description": "E.206"}, {"id": "a", "description": "E.205"}]
        self.assertEqual([row["id"] for row in rank([1, 0], [[2, 0], [3, 0]], records)], ["a", "b"])
        with self.assertRaises(ValueError):
            rank([1, 0], [[1, 0]], records)
        with self.assertRaises(ValueError):
            rank([1, 0], [[1], [1, 0]], records)

    def test_digest_mismatch_stops_before_inference(self):
        scope = {
            "subprocess": Mock(), "ollama_env": {}, "MODEL": "test-model:1",
            "EXPECTED_REVISION": "a" * 64,
            "ollama_api": Mock(return_value={"models": [{"name": "test-model:1", "digest": "b" * 64}]}),
        }
        with self.assertRaisesRegex(RuntimeError, "Digest"):
            exec(tagged_source("model-identity"), scope)

    def test_export_contains_only_allowlisted_configuration_and_sample_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = {
                "json": json, "WORK": Path(directory), "MODEL": "test-model:1",
                "observed_revision": "a" * 64, "DIMENSIONS": 2,
                "runtime_version": "test", "QUERY_INSTRUCTION": "test instruction",
                "QUERY": "private arbitrary query", "OLLAMA_API_KEY": "secret credential",
                "DOWNLOAD_RESULTS": False, "sample_evaluation": [{"query": "synthetic E.205"}],
            }
            exec(tagged_source("export"), scope)
            output = (Path(directory) / "findie-ollama-sample.json").read_text(encoding="utf-8")
            self.assertNotIn(scope["OLLAMA_API_KEY"], output)
            self.assertNotIn(scope["QUERY"], output)
            self.assertEqual(json.loads(output)["sample_cases"], scope["sample_evaluation"])


if __name__ == "__main__":
    unittest.main()
