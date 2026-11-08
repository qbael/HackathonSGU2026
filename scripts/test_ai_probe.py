"""Diagnose AI worker probe: Store, Ollama connectivity, model revisions, and embeddings."""

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/ai"))

import aio_pika
import httpx2 as httpx
from findie_ai.config import Settings
from findie_ai.worker import Worker


async def main():
    settings = Settings.from_env()
    worker = Worker(settings)

    print("==================== [1] KIỂM TRA STORE (SEARCH DB) ====================")
    try:
        await worker.store.check()
        print("-> Store check: PASS")
    except Exception as exc:
        print(f"-> Store check FAIL: {type(exc).__name__}: {exc}")

    print("\n==================== [2] KIỂM TRA RABBITMQ BROKER ====================")
    try:
        conn = await aio_pika.connect(settings.rabbitmq_url, timeout=5)
        print("-> RabbitMQ connection: PASS")
        await conn.close()
    except Exception as exc:
        print(f"-> RabbitMQ connection FAIL: {type(exc).__name__}: {exc}")

    print("\n==================== [3] KIỂM TRA OLLAMA BASE URL ====================")
    parsed_url = urlsplit(settings.ollama_base_url)
    safe_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    print(f"Target Origin: {safe_origin}")

    models_data = None
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url + "/",
            timeout=15,
            headers={
                "ngrok-skip-browser-warning": "true",
                **({"Authorization": f"Bearer {settings.ollama_api_key}"} if settings.ollama_api_key else {}),
            },
        ) as client:
            resp = await client.get("api/tags")
            print(f"-> HTTP Status code: {resp.status_code}")
            if resp.status_code == 200:
                models_data = resp.json().get("models", [])
                print(f"-> Số lượng model đang có trên Ollama: {len(models_data)}")
                for m in models_data:
                    digest = str(m.get("digest", "")).removeprefix("sha256:")[:12] + "..."
                    print(f"   * {m.get('name')} (digest: {digest})")
            else:
                print(f"-> Response text (rút gọn): {resp.text[:300]}")
    except httpx.ConnectError as exc:
        print(f"-> ConnectError (Không kết nối được ngrok/server): {exc}")
    except httpx.TimeoutException as exc:
        print(f"-> Timeout (Quá 15 giây không phản hồi): {exc}")
    except Exception as exc:
        print(f"-> Lỗi HTTP khác: {type(exc).__name__}: {exc}")

    print("\n==================== [4] KIỂM TRA MODEL REVISIONS ====================")
    if models_data is not None:
        expected_models = [
            ("Embedding", settings.model_id, settings.revision),
            ("Redaction", settings.redaction_model, settings.redaction_revision),
        ]
        if settings.reranker_revision:
            expected_models.append(("Reranker", settings.reranker_model, settings.reranker_revision))

        for label, model_name, revision in expected_models:
            clean_rev = revision.removeprefix("sha256:")
            matches = [m for m in models_data if m.get("name") == model_name]
            if not matches:
                print(f"-> {label} '{model_name}': KHÔNG TÌM THẤY TRÊN OLLAMA!")
            else:
                actual_digest = str(matches[0].get("digest", "")).removeprefix("sha256:")
                if actual_digest == clean_rev:
                    print(f"-> {label} '{model_name}': KHỚP REVISION (PASS)")
                else:
                    print(f"-> {label} '{model_name}': LỆCH REVISION!")
                    print(f"   Expected: {clean_rev}")
                    print(f"   Actual:   {actual_digest}")

    print("\n==================== [5] KIỂM TRA VERIFY_MODELS & EMBED ====================")
    try:
        await worker.ollama.verify_models()
        print("-> Ollama verify_models: PASS")
    except Exception as exc:
        print(f"-> Ollama verify_models FAIL: {type(exc).__name__}: {exc}")

    try:
        res = await worker.ollama.embed("Kiểm tra kết nối tìm đồ thất lạc.", query=True)
        print(f"-> Ollama embed: PASS (vector length: {len(res)})")
    except Exception as exc:
        print(f"-> Ollama embed FAIL: {type(exc).__name__}: {exc}")

    await worker.close()
    print("\n==================== HOÀN TẤT CHẨN ĐOÁN ====================")


if __name__ == "__main__":
    asyncio.run(main())
