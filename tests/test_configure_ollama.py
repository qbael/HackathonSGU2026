import importlib.util
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("configure_ollama", ROOT / "scripts/configure_ollama.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfigTests(unittest.TestCase):
    def config(self):
        return {"OLLAMA_BASE_URL": "https://example.ngrok-free.app", "AI_EMBEDDING_MODEL": "Qwen/Qwen3-VL-Embedding-2B",
                "AI_EMBEDDING_REVISION": "a" * 64, "AI_EMBEDDING_DIMENSIONS": 2048,
                "AI_EMBEDDING_QUERY_INSTRUCTION": "", "AI_REDACTION_MODEL": "qwen3-vl:4b-instruct",
                "AI_REDACTION_REVISION": "b" * 64, "AI_IMAGE_SEARCH_ENABLED": True,
                "AI_IMAGE_SEARCH_PROFILE": "image-only-v1"}

    def test_rejects_injected_config_and_invalid_identity(self):
        for change in ({"OLLAMA_BASE_URL": "http://remote"}, {"OLLAMA_BASE_URL": "https://user:pass@host"},
                       {"AI_EMBEDDING_DIMENSIONS": True}, {"AI_REDACTION_REVISION": ""},
                       {"AI_EMBEDDING_MODEL": "$(touch stolen)"}, {"AI_IMAGE_SEARCH_ENABLED": False},
                       {"OLLAMA_API_KEY": "secret in public export"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.settings(self.config() | change, "s" * 40)

    def test_optional_reranker_public_configuration_is_validated(self):
        config = self.config() | {"AI_RERANKER_MODEL": "Qwen/Qwen3-VL-Reranker-2B", "AI_RERANKER_REVISION": "c" * 64}
        self.assertEqual(module.settings(config, "s" * 40)["AI_RERANKER_REVISION"], "c" * 64)
        self.assertEqual(module.settings(self.config(), "s" * 40)["AI_RERANKER_REVISION"], "")
        self.assertEqual(module.settings(config | {"AI_RERANKER_REVISION": ""}, "s" * 40)["AI_RERANKER_REVISION"], "")
        for change in ({"AI_RERANKER_MODEL": "$(unsafe)"}, {"AI_RERANKER_REVISION": "short"},
                       {"AI_RERANKER_REVISION": None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.settings(config | change, "s" * 40)
        with self.assertRaises(ValueError):
            module.settings(self.config() | {"AI_RERANKER_REVISION": "c" * 64}, "s" * 40)

    def test_verification_checks_optional_reranker_revision(self):
        config = self.config() | {"AI_RERANKER_MODEL": "Qwen/Qwen3-VL-Reranker-2B", "AI_RERANKER_REVISION": "c" * 64}
        values = module.settings(config, "s" * 40)
        catalog = {"models": [{"name": config[prefix + "_MODEL"], "digest": "sha256:" + config[prefix + "_REVISION"]}
                              for prefix in ("AI_EMBEDDING", "AI_REDACTION")]}
        opener = Mock()
        with patch.object(module, "build_opener", return_value=opener):
            opener.open.return_value = BytesIO(json.dumps(catalog).encode())
            with self.assertRaises(ValueError):
                module.verify(values)
            catalog["models"].append({"name": config["AI_RERANKER_MODEL"], "digest": "sha256:" + "c" * 64})
            opener.open.return_value = BytesIO(json.dumps(catalog).encode())
            module.verify(values)

    def test_atomic_import_preserves_secrets_and_shell_quotes_token(self):
        token = "test'$`$(bad)" + "s" * 40
        values = module.settings(self.config(), token)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("GOOGLE_SECRET='keep me'\nexport Ai__EmbeddingRevision=''\nAI_EMBEDDING_MODEL=old\n"
                            "AI_TEXT_SEARCH_PROFILE=custom-profile\nAi__TextSearchProfile=custom-profile\n")
            module.write_env(path, values)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("GOOGLE_SECRET='keep me'", path.read_text())
            read_env = f"import os,json; print(json.dumps({{k:os.environ[k] for k in {['GOOGLE_SECRET', *values]!r}}}))"
            result = subprocess.run(["bash", "-c", 'set -a; . "$1"; python3 -c "$2"', "bash", str(path), read_env],
                                    capture_output=True, text=True, check=True)
            parsed = json.loads(result.stdout)
            self.assertEqual(parsed["OLLAMA_API_KEY"], token)
            self.assertEqual(parsed["GOOGLE_SECRET"], "keep me")
            for python_field, api_field, expected in (
                    ("AI_EMBEDDING_MODEL", "Ai__EmbeddingModelId", "Qwen/Qwen3-VL-Embedding-2B"),
                    ("AI_EMBEDDING_REVISION", "Ai__EmbeddingRevision", "a" * 64),
                    ("AI_EMBEDDING_DIMENSIONS", "Ai__EmbeddingDimensions", "2048"),
                    ("AI_REDACTION_MODEL", "Ai__RedactionModelId", "qwen3-vl:4b-instruct"),
                    ("AI_REDACTION_REVISION", "Ai__RedactionRevision", "b" * 64)):
                self.assertEqual(parsed[python_field], expected)
                self.assertEqual(parsed[api_field], expected)
            self.assertEqual(parsed["AI_EMBEDDING_QUERY_INSTRUCTION"], "")
            self.assertEqual(parsed["Ai__RedactionProfile"], "redact-v4")
            self.assertEqual(values["AI_TEXT_SEARCH_PROFILE"], values["Ai__TextSearchProfile"])
            self.assertNotIn("custom-profile", path.read_text())

    def test_model_verification_rejects_redirect_without_forwarding_bearer(self):
        destination_calls = []

        class Destination(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                destination_calls.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)

        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/api/tags")
                self.end_headers()

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        servers = (destination, redirect)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
        for thread in threads:
            thread.start()
        try:
            values = module.settings(self.config(), "s" * 40)
            values["OLLAMA_BASE_URL"] = f"http://127.0.0.1:{redirect.server_port}"
            with self.assertRaisesRegex(ValueError, "kept unchanged"):
                module.verify(values)
            self.assertEqual(destination_calls, [])
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
