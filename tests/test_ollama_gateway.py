import importlib.util
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ollama_gateway", ROOT / "scripts/ollama_gateway.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TOKEN = "a" * 48


class GatewayTests(unittest.TestCase):
    def test_check_gateway_verifies_models_and_reports_private_ngrok_errors(self):
        revisions = {"embedding": "a" * 64, "redaction": "b" * 64}
        catalog = {"models": [{"name": name, "digest": "sha256:" + digest}
                               for name, digest in revisions.items()]}
        status = 200
        payload = json.dumps(catalog).encode()
        error_code = None
        recover_after = 0
        requests = []

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization"),
                                 self.headers.get("ngrok-skip-browser-warning")))
                if len(requests) <= recover_after:
                    self.send_response(404)
                    self.send_header("ngrok-error-code", "ERR_NGROK_3200")
                    self.end_headers()
                    return
                self.send_response(status)
                if error_code:
                    self.send_header("ngrok-error-code", error_code)
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(module.check_gateway(base_url, TOKEN, revisions), catalog)
            self.assertEqual(requests, [("/api/tags", "Bearer " + TOKEN, "1")])
            catalog["models"][0]["digest"] = "c" * 64
            payload = json.dumps(catalog).encode()
            with self.assertRaises(RuntimeError):
                module.check_gateway(base_url, TOKEN, revisions)
            catalog["models"][0]["digest"] = "a" * 64
            payload = json.dumps(catalog).encode()
            requests.clear()
            recover_after = 2
            with patch.object(module.time, "sleep") as sleep:
                self.assertEqual(module.check_gateway(base_url, TOKEN, revisions), catalog)
                self.assertEqual(sleep.call_count, 2)
            self.assertEqual(len(requests), 3)
            recover_after = 0
            status = 404
            for error_code in ("ERR_NGROK_3200", None):
                with self.subTest(error_code=error_code):
                    payload = ("ERR_NGROK_3200 private upstream output " + TOKEN).encode()
                    requests.clear()
                    with patch.object(module.time, "sleep") as sleep, self.assertRaises(RuntimeError) as error:
                        module.check_gateway(base_url, TOKEN, revisions)
                    self.assertEqual(len(requests), 5)
                    self.assertEqual(sleep.call_count, 4)
                    message = str(error.exception)
                    self.assertIn("404", message)
                    self.assertIn("ERR_NGROK_3200", message)
                    self.assertNotIn(TOKEN, message)
                    self.assertNotIn("private upstream output", message)
            for status, error_code in ((404, None), (502, "ERR_NGROK_3200")):
                with self.subTest(status=status, error_code=error_code):
                    payload = ("private upstream output " + TOKEN).encode()
                    requests.clear()
                    with patch.object(module.time, "sleep") as sleep, self.assertRaises(RuntimeError):
                        module.check_gateway(base_url, TOKEN, revisions)
                    self.assertEqual(len(requests), 1)
                    sleep.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_check_gateway_reports_only_safe_upstream_502_details(self):
        base_url = "http://127.0.0.1:11435"
        endpoint = base_url + "/api/tags"
        cases = (
            ({"error": "ollama_unavailable", "upstreamStatus": 403}, "ollama_unavailable"),
            ({"error": "ollama_timeout"}, "ollama_timeout"),
            ({"error": "ollama_http_error", "upstreamStatus": 503}, "ollama_http_error (Ollama HTTP 503)"),
            ({"error": "ollama_http_error", "upstreamStatus": True}, "ollama_http_error"),
            ({"error": "ollama_http_error", "upstreamStatus": "503"}, "ollama_http_error"),
            ({"error": "ollama_http_error", "upstreamStatus": 999}, "ollama_http_error"),
            ({"error": "private upstream output " + TOKEN}, "không có mã lỗi ngrok"),
        )
        for payload, marker in cases:
            with self.subTest(payload=payload):
                body = json.dumps({**payload, "detail": "private upstream output " + TOKEN}).encode()
                opener = Mock()
                opener.open.side_effect = HTTPError(endpoint, 502, "Bad Gateway", {}, BytesIO(body))
                with patch.object(module, "build_opener", return_value=opener), self.assertRaises(RuntimeError) as error:
                    module.check_gateway(base_url, TOKEN, {})
                self.assertEqual(str(error.exception), f"{endpoint}: HTTP 502, {marker}.")
                opener.open.assert_called_once()

    def test_check_gateway_does_not_follow_redirect_with_bearer_token(self):
        requests = []

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(302 if self.path == "/api/tags" else 200)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirect-target")
                self.end_headers()
                self.wfile.write(b'{"models": []}')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "302"):
                module.check_gateway(f"http://127.0.0.1:{server.server_port}", TOKEN,
                                     {"embedding": "a" * 64})
            self.assertEqual(requests, [("/api/tags", "Bearer " + TOKEN)])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_qwen_runtime_identity_dispatch_limits_and_private_errors(self):
        model = "Qwen/Qwen3-VL-Embedding-2B"
        vector = [1.0] + [0.0] * 2047
        embedding = SimpleNamespace(model_id=model, digest="b" * 64, dimensions=2048,
                                    embed=Mock(return_value=vector))
        calls = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                calls.append(self.path)
                body = json.dumps({"models": [{"name": model, "digest": "wrong"},
                                               {"name": "redaction", "digest": "a" * 64},
                                               {"name": "private"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                calls.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"model":"redaction","done":true}')

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        opener = module.build_opener(module.ProxyHandler({}))
        opener.open = Mock(wraps=opener.open)
        with patch.object(module, "build_opener", return_value=opener):
            proxy = module.gateway(TOKEN, [model, "redaction"], address=("127.0.0.1", 0),
                                   upstream=f"http://127.0.0.1:{upstream.server_port}", embedding=embedding)
        servers = [upstream, proxy]
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for thread in threads:
            thread.start()
        release = threading.Event()
        try:
            def request(path, payload=None, token=TOKEN, headers=None):
                data = None if payload is None else json.dumps(payload).encode()
                req = Request(f"http://127.0.0.1:{proxy.server_port}" + path, data=data,
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                       **(headers or {})})
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status, json.load(response)
                except HTTPError as error:
                    with error:
                        return error.code, json.load(error)

            payload = {"model": model, "input": "search"}
            self.assertEqual(request("/api/embed", payload, token="bad")[0], 401)
            self.assertEqual(request("/api/embed", payload,
                                     headers={"Content-Length": str(module.MAX_REQUEST + 1)})[0], 413)
            self.assertEqual(request("/api/generate", payload)[0], 400)
            self.assertEqual(request("/api/embed", {**payload, "stream": True})[0], 400)
            for dimensions in (768, True, 2048.0, "2048"):
                self.assertEqual(request("/api/embed", {**payload, "dimensions": dimensions})[0], 400)
            for truncate in (True, None, 0):
                self.assertEqual(request("/api/embed", {**payload, "truncate": truncate})[0], 400)
            embedding.embed.assert_not_called()
            self.assertEqual(calls, [])
            status, catalog = request("/api/tags")
            self.assertEqual(status, 200)
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 25)
            self.assertEqual(catalog["models"], [{"name": "redaction", "digest": "a" * 64},
                                                {"name": model, "digest": "sha256:" + embedding.digest}])
            self.assertEqual(request("/api/show", {"model": model}),
                             (200, {"capabilities": ["embedding", "vision"]}))
            embedding.supports_image_text = True
            self.assertEqual(request("/api/show", {"model": model}),
                             (200, {"capabilities": ["embedding", "vision", "image_text"]}))
            for value in ("search", {"image": "native-image-base64"},
                          {"image": "native-image-base64", "text": "Thẻ sinh viên. MSSV: 12345678"}):
                self.assertEqual(request("/api/embed", {**payload, "input": value, "dimensions": 2048,
                                                        "truncate": False}),
                                 (200, {"model": model, "embeddings": [vector]}))
                embedding.embed.assert_called_with(value)
            for error, status in ((ValueError("secret input"), 400),
                                  (RuntimeError("secret runtime"), 502), (MemoryError("secret OOM"), 502)):
                embedding.embed.side_effect = error
                result = request("/api/embed", payload)
                self.assertEqual(result[0], status)
                self.assertNotIn("secret", json.dumps(result[1]))
            self.assertEqual(calls, ["/api/tags"])

            entered = threading.Event()

            def blocking_embed(_value):
                entered.set()
                self.assertTrue(release.wait(3))
                return vector

            embedding.embed.side_effect = blocking_embed
            result = []
            worker = threading.Thread(target=lambda: result.append(request("/api/embed", payload)))
            worker.start()
            self.assertTrue(entered.wait(2))
            self.assertEqual(request("/api/embed", payload)[0], 429)
            self.assertEqual(request("/api/generate", {"model": "redaction"})[0], 429)
            release.set()
            worker.join(timeout=3)
            self.assertEqual(result[0][0], 200)
            self.assertEqual(request("/api/generate", {"model": "redaction"})[0], 200)
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 300)
            self.assertEqual(calls[-1], ("/api/generate", {"model": "redaction"}))
        finally:
            release.set()
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_auth_allowlist_limits_and_private_errors(self):
        calls = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                calls.append(self.path)
                body = json.dumps({"models": [{"name": "allowed", "digest": "a" * 64}, {"name": "private"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                calls.append(self.path)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'secret upstream prompt/credential')

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        opener = module.build_opener(module.ProxyHandler({}))
        with patch.object(module, "build_opener", return_value=opener):
            proxy = module.gateway(TOKEN, ["allowed"], address=("127.0.0.1", 0),
                                   upstream=f"http://127.0.0.1:{upstream.server_port}")
        servers = [upstream, proxy]
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for thread in threads:
            thread.start()
        try:
            def request(path, payload=None, token=TOKEN, headers=None, method=None):
                data = None if payload is None else json.dumps(payload).encode()
                req = Request(f"http://127.0.0.1:{proxy.server_port}" + path, data=data, method=method,
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", **(headers or {})})
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status, json.load(response), response.headers
                except HTTPError as error:
                    with error:
                        return error.code, json.load(error), error.headers

            self.assertEqual(request("/api/tags", token="bad")[0], 401)
            self.assertEqual(request("/api/pull", {"model": "allowed"})[0], 404)
            self.assertEqual(request("/api/tags?token=bad")[0], 404)
            self.assertEqual(request("/api/embed", {"model": "private"})[0], 400)
            self.assertEqual(request("/api/embed", {"model": "allowed", "stream": True})[0], 400)
            self.assertEqual(request("/api/embed", {"model": "allowed"}, headers={"Content-Length": str(module.MAX_REQUEST + 1)})[0], 413)
            self.assertEqual(calls, [])
            status, body, headers = request("/api/tags")
            self.assertEqual(status, 200)
            self.assertEqual([m["name"] for m in body["models"]], ["allowed"])
            self.assertIsNone(headers.get("X-Findie-Inference-Timeout-Seconds"))
            status, body, headers = request("/api/generate", {"model": "allowed"})
            self.assertEqual(status, 502)
            self.assertEqual(body, {"error": "ollama_http_error", "upstreamStatus": 500})
            self.assertEqual(headers["X-Findie-Inference-Timeout-Seconds"], "300")
            for error, expected in ((TimeoutError("secret timeout"), "ollama_timeout"),
                                    (URLError(TimeoutError("secret timeout")), "ollama_timeout"),
                                    (URLError("secret upstream failure"), "ollama_unavailable")):
                with self.subTest(error=type(error)), patch.object(opener, "open", side_effect=error):
                    status, body, headers = request("/api/generate", {"model": "allowed"})
                    self.assertEqual(status, 502)
                    self.assertEqual(body, {"error": expected})
                    self.assertEqual(headers["X-Findie-Inference-Timeout-Seconds"], "300")
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_reranker_dispatch_catalog_errors_and_shared_capacity(self):
        item_id = "fd000000-0000-0000-0000-000000000001"
        scores = [{"itemId": item_id, "imageScore": None, "textScore": 0.9}]
        reranker = SimpleNamespace(model_id="reranker", digest="c" * 64, rerank=Mock(return_value=scores))
        calls = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                calls.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"models":[{"name":"redaction","digest":"a"}]}')

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        proxy = module.gateway(TOKEN, ["reranker", "redaction"], address=("127.0.0.1", 0),
                               upstream=f"http://127.0.0.1:{upstream.server_port}", reranker=reranker)
        servers = [upstream, proxy]
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
        for thread in threads:
            thread.start()
        release = threading.Event()
        try:
            def request(path, payload=None, token=TOKEN):
                req = Request(f"http://127.0.0.1:{proxy.server_port}" + path,
                              data=None if payload is None else json.dumps(payload).encode(),
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status, json.load(response)
                except HTTPError as error:
                    with error:
                        return error.code, json.load(error)

            payload = {"model": "reranker", "text": "ví", "images": [],
                       "candidates": [{"itemId": item_id, "text": "ví đen"}], "deadlineAt": "test"}
            self.assertEqual(request("/api/rerank", payload, token="wrong")[0], 401)
            self.assertEqual(request("/api/rerank", payload | {"model": "redaction"})[0], 400)
            self.assertEqual(request("/api/embed", {"model": "reranker"})[0], 400)
            self.assertEqual(request("/api/show", {"model": "reranker"}),
                             (200, {"capabilities": ["rerank", "vision"]}))
            self.assertIn({"name": "reranker", "digest": "sha256:" + reranker.digest},
                          request("/api/tags")[1]["models"])
            self.assertEqual(request("/api/rerank", payload), (200, {"model": "reranker", "scores": scores}))
            self.assertEqual(calls, ["/api/tags"])
            for error, status in ((ValueError("private input"), 400), (TimeoutError("private deadline"), 504),
                                  (RuntimeError("private CUDA"), 502)):
                reranker.rerank.side_effect = error
                result = request("/api/rerank", payload)
                self.assertEqual(result[0], status)
                self.assertNotIn("private", json.dumps(result[1]))
            reranker.rerank.side_effect = None
            for invalid in ([], scores * 2, [scores[0] | {"textScore": float("nan")}],
                            [scores[0] | {"textScore": True}], [scores[0] | {"itemId": "other"}]):
                reranker.rerank.return_value = invalid
                self.assertEqual(request("/api/rerank", payload)[0], 502)
            entered = threading.Event()

            def block(_payload):
                entered.set()
                release.wait(3)
                return scores

            reranker.rerank.side_effect = block
            result = []
            thread = threading.Thread(target=lambda: result.append(request("/api/rerank", payload)))
            thread.start()
            self.assertTrue(entered.wait(2))
            self.assertEqual(request("/api/generate", {"model": "redaction"})[0], 429)
            release.set()
            thread.join(timeout=3)
            self.assertEqual(result[0][0], 200)
        finally:
            release.set()
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_notebook_proxy_matches_tested_source_and_has_no_saved_outputs(self):
        notebook = json.loads((ROOT / "notebooks/colab/04_full_stack_ollama_ngrok.ipynb").read_text())
        for tag, filename in (("gateway-source", "ollama_gateway.py"), ("qwen-source", "qwen_embedding.py"), ("reranker-source", "qwen_reranker.py")):
            source = next("".join(c["source"]) for c in notebook["cells"]
                          if tag in c["metadata"].get("tags", []))
            self.assertEqual(source, (ROOT / "scripts" / filename).read_text())
        for i, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])
                compile("".join(cell["source"]), f"cell{i}", "exec")

    def test_notebook_gateway_start_uses_fresh_config_with_current_token_on_rerun(self):
        notebook = json.loads((ROOT / "notebooks/colab/04_full_stack_ollama_ngrok.ipynb").read_text())
        source = next("".join(c["source"]) for c in notebook["cells"]
                      if "gateway-start" in c["metadata"].get("tags", []))
        poisoned_default = SimpleNamespace(auth_token={"invalid": "default"}, ngrok_path={"invalid": "path"})
        conf = SimpleNamespace(
            get_default=Mock(return_value=poisoned_default),
            PyngrokConfig=Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs)),
        )
        events = []
        public_url = "https://example.ngrok.app"

        def connect(*, addr, proto, inspect, pyngrok_config):
            events.append(("connect", pyngrok_config.auth_token))
            return SimpleNamespace(public_url=public_url)

        ngrok = Mock()
        ngrok.kill.side_effect = lambda *, pyngrok_config: events.append(("kill", pyngrok_config.auth_token))
        ngrok.connect.side_effect = connect
        servers = [Mock(), Mock(), Mock()]
        check_gateway = Mock(return_value={"models": [{}, {}]})
        revisions = {"embedding": "b" * 64, "redaction": "c" * 64}
        namespace = {
            "gateway": Mock(side_effect=servers),
            "threading": SimpleNamespace(Thread=Mock()),
            "ensure_ollama_ready": Mock(),
            "FINDIE_OLLAMA_TOKEN": TOKEN,
            "EMBEDDING_MODEL": "embedding",
            "REDACTION_MODEL": "redaction",
            "qwen_embedding": object(),
            "check_gateway": check_gateway,
            "revisions": revisions,
        }
        output = StringIO()
        tokens = ("ngrok-secret-first", "ngrok-secret-second")
        configs = []
        with patch.dict("sys.modules", {"pyngrok": SimpleNamespace(conf=conf, ngrok=ngrok)}), redirect_stdout(output):
            for token in tokens:
                namespace["NGROK_AUTHTOKEN"] = token
                exec(source, namespace)
                configs.append(namespace["ngrok_config"])
                conf.PyngrokConfig.assert_called_with(auth_token=token)
                ngrok.kill.assert_called_with(pyngrok_config=configs[-1])
                ngrok.connect.assert_called_with(addr="http://127.0.0.1:11435", proto="http", inspect=False,
                                                 pyngrok_config=configs[-1])
            self.assertIsNot(configs[0], configs[1])
            self.assertEqual(conf.PyngrokConfig.call_count, 2)
            self.assertEqual([config.auth_token for config in configs], list(tokens))
            conf.get_default.assert_not_called()
            self.assertEqual(events, [("kill", tokens[0]), ("connect", tokens[0]),
                                      ("kill", tokens[1]), ("connect", tokens[1])])
            servers[0].shutdown.assert_called_once_with()
            servers[0].server_close.assert_called_once_with()
            ngrok.set_auth_token.assert_not_called()
            self.assertEqual(check_gateway.call_count, 4)
            for local, remote in zip(check_gateway.call_args_list[::2], check_gateway.call_args_list[1::2]):
                self.assertEqual(local.args, ("http://127.0.0.1:11435", TOKEN, revisions))
                self.assertEqual(remote.args, (public_url, TOKEN, revisions))
            public_url = "http://example.ngrok.app"
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                exec(source, namespace)
            self.assertEqual(check_gateway.call_count, 5)
            self.assertEqual(check_gateway.call_args.args, ("http://127.0.0.1:11435", TOKEN, revisions))
        for token in (*tokens, TOKEN):
            self.assertNotIn(token, output.getvalue())


    def test_notebook_gateway_rejects_invalid_ngrok_token_before_stopping_services(self):
        notebook = json.loads((ROOT / "notebooks/colab/04_full_stack_ollama_ngrok.ipynb").read_text())
        source = next("".join(c["source"]) for c in notebook["cells"]
                      if "gateway-start" in c["metadata"].get("tags", []))
        invalid_tokens = (None, {"token": "private-token"}, 123, True, b"private-token", "", " ",
                          "private token", "private-token\n", "private-tokén")
        for index, token in enumerate(invalid_tokens):
            with self.subTest(case=index):
                ngrok, conf, server = Mock(), Mock(), Mock()
                namespace = {
                    "NGROK_AUTHTOKEN": token,
                    "ensure_ollama_ready": Mock(),
                    "gateway_server": server,
                    "gateway": Mock(),
                    "check_gateway": Mock(),
                }
                output = StringIO()
                with patch.dict("sys.modules", {"pyngrok": SimpleNamespace(conf=conf, ngrok=ngrok)}), redirect_stdout(output):
                    with self.assertRaisesRegex(ValueError, "NGROK_AUTHTOKEN") as raised:
                        exec(source, namespace)
                self.assertNotIn("private-token", str(raised.exception))
                self.assertEqual(output.getvalue(), "")
                namespace["ensure_ollama_ready"].assert_not_called()
                namespace["gateway"].assert_not_called()
                namespace["check_gateway"].assert_not_called()
                server.shutdown.assert_not_called()
                server.server_close.assert_not_called()
                conf.PyngrokConfig.assert_not_called()
                conf.get_default.assert_not_called()
                ngrok.kill.assert_not_called()
                ngrok.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
