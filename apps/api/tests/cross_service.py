"""Run the .NET/Python bridge with real AMQP/PostgreSQL and an explicit Ollama test double."""

import asyncio
import base64
from http.server import ThreadingHTTPServer
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import aio_pika
from PIL import Image, PngImagePlugin


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/ai"))
spec = importlib.util.spec_from_file_location("ollama_fixture", ROOT / "services/ai/tests/integration.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


async def provision(broker):
    async with await aio_pika.connect(broker) as connection:
        channel = await connection.channel()
        for name in ("findie.ai.commands", "findie.api.results"):
            await channel.declare_queue(name, durable=True)


def run():
    broker = os.environ["FINDIE_TEST_BROKER_URI"]
    asyncio.run(provision(broker))
    token = secrets.token_hex(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), fixture.OllamaStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        worker_port = listener.getsockname()[1]
    environment = os.environ | {
        "AI_SERVICE_TOKEN": token, "AI_RABBITMQ_URL": broker,
        "OLLAMA_BASE_URL": f"http://127.0.0.1:{server.server_port}", "OLLAMA_API_KEY": "",
        "AI_EMBEDDING_MODEL": fixture.MODEL, "AI_EMBEDDING_REVISION": fixture.REVISION,
        "AI_EMBEDDING_DIMENSIONS": str(fixture.DIMENSIONS), "AI_EMBEDDING_QUERY_INSTRUCTION": "test instruction",
        "AI_REDACTION_MODEL": fixture.REDACTION_MODEL, "AI_REDACTION_REVISION": fixture.REDACTION_REVISION,
        "AI_TEXT_SEARCH_PROFILE": "text-description-v1", "AI_IMAGE_SEARCH_ENABLED": "true", "AI_IMAGE_SEARCH_PROFILE": "image-only-v1",
        "AI_INDEX_QUEUE": "findie.ai.commands", "AI_RESULT_QUEUE": "findie.api.results",
        "AI_QUERY_QUEUE": "findie.ai.query", "AI_IMAGE_QUEUE": "findie.ai.image", "PYTHONPATH": str(ROOT / "services/ai"),
        "Ai__EmbeddingModelId": fixture.MODEL, "Ai__EmbeddingRevision": fixture.REVISION,
        "Ai__EmbeddingDimensions": str(fixture.DIMENSIONS), "Ai__TextSearchProfile": "text-description-v1",
        "Ai__RedactionModelId": fixture.REDACTION_MODEL, "Ai__RedactionRevision": fixture.REDACTION_REVISION,
        "Ai__RedactionProfile": "redact-v4", "Ai__ImageSearchProfile": "image-only-v1",
    }
    image = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "BRIDGE-PRIVATE-METADATA")
    with Image.new("RGB", (20, 20), "red") as synthetic:
        synthetic.save(image, format="PNG", pnginfo=metadata)
    environment["FINDIE_TEST_IMAGE_BASE64"] = base64.b64encode(image.getvalue()).decode()
    worker = None
    with tempfile.TemporaryFile() as logs:
        try:
            worker = subprocess.Popen([sys.executable, "-m", "uvicorn", "findie_ai.main:app", "--host", "127.0.0.1",
                "--port", str(worker_port), "--log-level", "warning", "--no-access-log"], cwd=ROOT,
                env=environment, stdout=logs, stderr=logs)
            deadline = time.monotonic() + 45
            while True:
                if worker.poll() is not None:
                    raise RuntimeError("Python bridge worker exited before readiness.")
                try:
                    request = Request(f"http://127.0.0.1:{worker_port}/v1/status", headers={"X-Service-Token": token})
                    with urlopen(request, timeout=2) as response:
                        status = json.load(response)
                        if status.get("inferenceReady") and all(status["capabilities"].values()):
                            break
                except (HTTPError, URLError, TimeoutError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Python bridge worker did not report full model readiness.")
                time.sleep(0.25)
            subprocess.run(["dotnet", "run", "--project", "apps/api/tests/integration", "--no-build", "--no-launch-profile",
                            "--", "--cross-service-only"], cwd=ROOT, env=environment, check=True)
        finally:
            if worker:
                worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        logs.seek(0)
        if b"Traceback" in logs.read():
            raise RuntimeError("Python bridge worker emitted an unhandled exception.")


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        raise SystemExit(f"Cross-service bridge failed ({type(error).__name__}); model and worker logs were not exposed.") from None
