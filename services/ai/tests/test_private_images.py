import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from findie_ai.main import app


def test_private_images_require_auth_validate_and_return_only_processed_bytes(monkeypatch):
    monkeypatch.setenv('AI_SERVICE_TOKEN', 'unit-token')
    monkeypatch.delenv('AI_SEARCH_DSN', raising=False)
    calls = []

    async def execute(kind, metadata, body, content_type):
        calls.append((kind, body, content_type))
        return b'processed-output', {'contentType': 'image/webp'}

    metadata = {'schemaVersion': 1, 'modelId': 'model', 'modelRevision': 'a' * 64,
                'deadlineAt': (datetime.now(timezone.utc) + timedelta(seconds=25)).isoformat(),
                'imageId': str(uuid4()), 'itemId': str(uuid4()), 'sourceVersion': 1,
                'sourceSha256': 'b' * 64, 'processingProfile': 'redact-v4'}
    headers = {'X-Service-Token': 'unit-token', 'Content-Type': 'image/png',
               'X-Ai-Metadata': base64.b64encode(json.dumps(metadata).encode()).decode()}
    with TestClient(app) as client:
        app.state.worker = SimpleNamespace(connected=True, capacity=asyncio.Semaphore(1), identity=lambda _: None, execute=execute)
        assert client.post('/v1/images/image.redact', content=b'raw').status_code == 401
        assert client.post('/v1/images/index.upsert', headers=headers, content=b'raw').status_code == 404
        bad = headers | {'X-Ai-Metadata': 'malformed'}
        assert client.post('/v1/images/image.redact', headers=bad, content=b'raw').status_code == 503
        assert not calls
        response = client.post('/v1/images/image.redact', headers=headers, content=b'private-original')
        assert response.status_code == 200
        size = int.from_bytes(response.content[:4], 'big')
        reply = json.loads(response.content[4:4 + size])
        assert reply['succeeded'] and reply['kind'] == 'image.redact'
        assert response.content[4 + size:] == b'processed-output'
        assert b'private-original' not in response.content
        assert calls == [('image.redact', b'private-original', 'image/png')]
        assert response.headers['cache-control'] == 'no-store'
        app.state.worker.connected = False
        assert client.post('/v1/images/image.redact', headers=headers, content=b'raw').status_code == 503
