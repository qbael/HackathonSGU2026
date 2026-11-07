"""Small authenticated, inference-only gateway for an interactive model session."""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener, ProxyHandler


MAX_REQUEST = 16 * 1024 * 1024
MAX_RESPONSE = 2 * 1024 * 1024
GENERATE_TIMEOUT = 300


class NoGatewayRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def check_gateway(base_url, token, revisions):
    endpoint = base_url.rstrip("/") + "/api/tags"
    request = Request(endpoint, headers={"Authorization": "Bearer " + token,
                                        "ngrok-skip-browser-warning": "1", "Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), NoGatewayRedirect())
    for attempt in range(5):
        try:
            with opener.open(request, timeout=15) as response:
                data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ValueError()
            result = json.loads(data)
            models = {entry["name"]: str(entry["digest"]).removeprefix("sha256:")
                      for entry in result["models"]}
            if models != revisions:
                raise ValueError()
            return result
        except HTTPError as error:
            with error:
                body = error.read(4096).decode("utf-8", "replace")
            code = re.search(r"\bERR_NGROK_\d+\b", error.headers.get("ngrok-error-code", "") + " " + body)
            if error.code == 404 and code and code[0] == "ERR_NGROK_3200" and attempt < 4:
                time.sleep(1)
                continue
            # Only return a machine error code; upstream pages can contain private content.
            marker = code[0] if code else "không có mã lỗi ngrok"
            if error.code == 502 and not code:
                try:
                    failure = json.loads(body)
                except (ValueError, RecursionError):
                    failure = None
                if isinstance(failure, dict) and failure.get("error") in (
                        "ollama_unavailable", "ollama_timeout", "ollama_http_error"):
                    marker = failure["error"]
                    upstream_status = failure.get("upstreamStatus")
                    if marker == "ollama_http_error" and type(upstream_status) is int and 100 <= upstream_status <= 599:
                        marker += f" (Ollama HTTP {upstream_status})"
            raise RuntimeError(f"{endpoint}: HTTP {error.code}, {marker}.") from None
        except (URLError, OSError):
            raise RuntimeError(f"Không kết nối được {endpoint}; kiểm tra gateway và ngrok đang chạy.") from None
        except (ValueError, KeyError, TypeError):
            raise RuntimeError(f"{endpoint}: model/digest trả về không khớp cấu hình phiên.") from None


def gateway(token, models, *, address=("127.0.0.1", 11435), upstream="http://127.0.0.1:11434", embedding=None, reranker=None):
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("Use an ASCII token of at least 32 characters without whitespace.")
    if not models or any(not isinstance(m, str) or not m for m in models):
        raise ValueError("Explicit model names are required.")
    if not upstream.startswith("http://127.0.0.1:"):
        raise ValueError("The upstream must be the private loopback Ollama server.")
    allowed_models = frozenset(models)
    if embedding is not None and embedding.model_id not in allowed_models:
        raise ValueError("The embedding model must be explicitly allowed.")
    if reranker is not None and reranker.model_id not in allowed_models:
        raise ValueError("The reranker model must be explicitly allowed.")
    capacity = threading.BoundedSemaphore(1)
    opener = build_opener(ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Request headers/bodies and model output must never enter logs.

        def respond(self, status, payload):
            try:
                body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
            except (ValueError, TypeError, OverflowError):
                status, body = 502, b'{"error":"ollama_unavailable"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            if self.path == "/api/generate":
                self.send_header("X-Findie-Inference-Timeout-Seconds", str(GENERATE_TIMEOUT))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def handle_api(self):
            self.connection.settimeout(10)
            supplied = self.headers.get("Authorization", "").encode("utf-8")
            if not hmac.compare_digest(supplied, ("Bearer " + token).encode("ascii")):
                return self.respond(401, {"error": "unauthorized"})
            if (self.command, self.path) not in {("GET", "/api/tags"), ("POST", "/api/show"),
                                               ("POST", "/api/embed"), ("POST", "/api/generate"), ("POST", "/api/rerank")}:
                return self.respond(404, {"error": "unsupported_route"})
            if self.headers.get("Transfer-Encoding"):
                return self.respond(400, {"error": "content_length_required"})
            body = None
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_REQUEST:
                        return self.respond(413, {"error": "request_too_large"})
                    if self.headers.get_content_type() != "application/json":
                        return self.respond(415, {"error": "json_required"})
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError()
                    payload = json.loads(body)
                    if not isinstance(payload, dict) or payload.get("model") not in allowed_models:
                        return self.respond(400, {"error": "model_not_allowed"})
                    if payload.get("stream", False) is not False:
                        return self.respond(400, {"error": "streaming_not_supported"})
                except (ValueError, TypeError, TimeoutError, OSError):
                    return self.respond(400, {"error": "invalid_request"})
            qwen_request = embedding is not None and self.command == "POST" and payload["model"] == embedding.model_id
            rerank_request = reranker is not None and self.command == "POST" and payload["model"] == reranker.model_id
            if self.path == "/api/rerank" and not rerank_request:
                return self.respond(400, {"error": "operation_not_supported"})
            if rerank_request:
                if self.path == "/api/show":
                    return self.respond(200, {"capabilities": ["rerank", "vision"]})
                if self.path != "/api/rerank":
                    return self.respond(400, {"error": "operation_not_supported"})
            if qwen_request:
                if self.path == "/api/generate":
                    return self.respond(400, {"error": "operation_not_supported"})
                if self.path == "/api/show":
                    capabilities = ["embedding", "vision"]
                    if getattr(embedding, "supports_image_text", False):
                        capabilities.append("image_text")
                    return self.respond(200, {"capabilities": capabilities})
                if (("dimensions" in payload and (type(payload["dimensions"]) is not int
                                                 or payload["dimensions"] != embedding.dimensions))
                        or payload.get("truncate", False) is not False):
                    return self.respond(400, {"error": "invalid_embedding_options"})
            inference = self.path in {"/api/embed", "/api/generate", "/api/rerank"}
            if inference and not capacity.acquire(blocking=False):
                return self.respond(429, {"error": "model_busy"})
            status = 200
            try:
                if rerank_request:
                    try:
                        scores = reranker.rerank(payload)
                    except ValueError:
                        status, result = 400, {"error": "invalid_rerank_input"}
                    else:
                        requested = {candidate["itemId"] for candidate in payload["candidates"]}
                        if (not isinstance(scores, list) or len(scores) != len(requested)
                                or {row.get("itemId") for row in scores if isinstance(row, dict)} != requested
                                or any(not isinstance(row, dict) or set(row) != {"itemId", "imageScore", "textScore"}
                                       or any(row[key] is not None and (type(row[key]) not in (float, int)
                                              or not math.isfinite(row[key]) or not 0 <= row[key] <= 1)
                                              for key in ("imageScore", "textScore")) for row in scores)):
                            raise RuntimeError("Invalid reranker response.")
                        result = {"model": reranker.model_id, "scores": scores}
                elif qwen_request:
                    try:
                        vector = embedding.embed(payload.get("input"))
                    except ValueError:
                        status, result = 400, {"error": "invalid_embedding_input"}
                    else:
                        result = {"model": embedding.model_id, "embeddings": [vector]}
                else:
                    request = Request(upstream + self.path, data=body,
                                      headers={"Content-Type": "application/json"}, method=self.command)
                    with opener.open(request, timeout=GENERATE_TIMEOUT if self.path == "/api/generate" else 25) as response:
                        data = response.read(MAX_RESPONSE + 1)
                        if len(data) > MAX_RESPONSE:
                            raise ValueError()
                        result = json.loads(data)
                    if self.path == "/api/tags":
                        result = {"models": [m for m in result["models"] if m.get("name") in allowed_models]}
                        if embedding is not None:
                            result["models"] = [m for m in result["models"] if m.get("name") != embedding.model_id]
                            result["models"].append({"name": embedding.model_id, "digest": "sha256:" + embedding.digest})
                        if reranker is not None:
                            result["models"] = [m for m in result["models"] if m.get("name") != reranker.model_id]
                            result["models"].append({"name": reranker.model_id, "digest": "sha256:" + reranker.digest})
            except HTTPError as error:
                error.close()
                status, result = 502, {"error": "ollama_http_error", "upstreamStatus": error.code}
            except TimeoutError:
                status, result = (504, {"error": "rerank_timeout"}) if rerank_request else (502, {"error": "ollama_timeout"})
            except URLError as error:
                status, result = 502, {"error": "ollama_timeout" if isinstance(error.reason, TimeoutError) else "ollama_unavailable"}
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, MemoryError):
                status, result = 502, {"error": "rerank_unavailable" if rerank_request else "ollama_unavailable"}
            finally:
                if inference:
                    capacity.release()
            return self.respond(status, result)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = handle_api

    return ThreadingHTTPServer(address, Handler)
