import asyncio
import pytest
from fastapi.testclient import TestClient

from findie_ai.config import Settings
from findie_ai.main import app


def test_redaction_defaults_select_the_instruct_model(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.delenv("AI_REDACTION_MODEL", raising=False)
    assert Settings(service_token="test").redaction_model == "qwen3-vl:4b-instruct"
    assert Settings.from_env().redaction_model == "qwen3-vl:4b-instruct"


def test_unconfigured_internal_status_requires_secret_and_reports_not_ready(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "unit-test-service-token")
    monkeypatch.delenv("AI_SEARCH_DSN", raising=False)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/status").status_code == 401
        assert client.get("/v1/status", headers={"X-Service-Token": "wrong"}).status_code == 401
        headers = {"X-Service-Token": "unit-test-service-token"}
        response = client.get("/v1/status", headers=headers)
        assert response.status_code == 200
        assert response.json()["inferenceReady"] is False
        assert response.json()["embeddingDimensions"] == 2048
        assert response.json()["execution"] == "ollama"
        assert response.json()["redactionProfileId"] == "redact-v4"
        assert response.json()["capabilities"]["imageSearch"] is False
        assert response.json()["capabilities"]["imageRedaction"] is False
        assert client.get("/health/ready", headers=headers).status_code == 503
        assert "unit-test-service-token" not in response.text


def test_startup_rejects_missing_service_secret(monkeypatch):
    monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="AI_SERVICE_TOKEN"):
        with TestClient(app):
            pass


def test_readiness_depends_on_live_dependency_probe(monkeypatch):
    class DependencyProbe:
        available = True

        def __init__(self, _settings):
            pass

        async def run(self):
            await asyncio.Future()

        async def probe(self):
            return self.available

        async def close(self):
            pass

    monkeypatch.setenv("AI_SERVICE_TOKEN", "test")
    monkeypatch.setenv("AI_SEARCH_DSN", "dbname=findie_search")
    monkeypatch.setenv("AI_RABBITMQ_URL", "amqp://127.0.0.1")
    monkeypatch.setenv("AI_EMBEDDING_REVISION", "a" * 64)
    monkeypatch.setenv("AI_IMAGE_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AI_REDACTION_REVISION", "b" * 64)
    monkeypatch.setattr("findie_ai.main.Worker", DependencyProbe)
    with TestClient(app) as client:
        headers = {"X-Service-Token": "test"}
        assert client.get("/health/ready", headers=headers).status_code == 200
        assert client.get("/v1/status", headers=headers).json()["inferenceReady"] is True
        assert client.get("/v1/status", headers=headers).json()["capabilities"] == {
            "textSearch": True, "imageSearch": True, "imageRedaction": True}
        DependencyProbe.available = False
        assert client.get("/health/ready", headers=headers).status_code == 503
        assert client.get("/v1/status", headers=headers).json()["inferenceReady"] is False
        assert client.get("/v1/status", headers=headers).json()["capabilities"] == {
            "textSearch": False, "imageSearch": False, "imageRedaction": False}
