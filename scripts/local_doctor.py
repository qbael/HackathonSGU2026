"""Check the full local stack; liveness alone never means ready."""

import argparse
import base64
import json
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from local_setup import ROOT, load_environment


def configuration_checks(environment):
    def filled(*keys):
        return all(environment.get(key, "").strip() and not environment[key].startswith("GENERATE_") for key in keys)
    checks = [
        ("Google OAuth", filled("Authentication__Google__ClientId", "Authentication__Google__ClientSecret"),
         "configured only; verify consent by signing in through the web app"),
        ("Private R2", filled("Storage__Endpoint", "Storage__Bucket", "Storage__AccessKeyId", "Storage__SecretAccessKey"),
         "configured only; verify credentials and private access with a real image upload/review"),
        ("Search connections", filled("AI_SEARCH_DSN", "AI_SEARCH_MIGRATION_DSN", "AI_RABBITMQ_URL", "RabbitMq__Uri"),
         "run make local-setup to provision local database and broker connections"),
        ("Service token", filled("AI_SERVICE_TOKEN") and environment.get("Ai__ServiceToken") == environment.get("AI_SERVICE_TOKEN"),
         ".NET and Python must use the same nonempty service token"),
        ("Image search enabled", environment.get("AI_IMAGE_SEARCH_ENABLED", "").lower() == "true",
         "import the full Colab model configuration"),
    ]
    for name, python_key, api_key in (
        ("Embedding model", "AI_EMBEDDING_MODEL", "Ai__EmbeddingModelId"),
        ("Embedding revision", "AI_EMBEDDING_REVISION", "Ai__EmbeddingRevision"),
        ("Embedding dimensions", "AI_EMBEDDING_DIMENSIONS", "Ai__EmbeddingDimensions"),
        ("Redaction model", "AI_REDACTION_MODEL", "Ai__RedactionModelId"),
        ("Redaction revision", "AI_REDACTION_REVISION", "Ai__RedactionRevision"),
        ("Text search profile", "AI_TEXT_SEARCH_PROFILE", "Ai__TextSearchProfile"),
        ("Image search profile", "AI_IMAGE_SEARCH_PROFILE", "Ai__ImageSearchProfile"),
    ):
        value = environment.get(python_key, "")
        valid = bool(value) and value == environment.get(api_key)
        if "REVISION" in python_key:
            valid = valid and bool(re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", value))
        elif "DIMENSIONS" in python_key:
            valid = valid and value.isdigit() and 1 <= int(value) <= 16000
        checks.append((name, valid, "Python and .NET settings must match the pinned Colab model configuration"))
    return checks


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def get_json(url, headers=None):
    try:
        endpoint = urlsplit(url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or endpoint.password:
            return None
        with build_opener(NoRedirect).open(Request(url, headers=headers or {}), timeout=20) as response:
            body = response.read(1024 * 1024 + 1)
            return json.loads(body) if len(body) <= 1024 * 1024 else None
    except (OSError, HTTPError, URLError, ValueError):
        return None


def schema_ready(environment, database, sql):
    try:
        container = subprocess.check_output(["docker", "compose", "ps", "-q", "db"], cwd=ROOT,
                                            env=environment, text=True, stderr=subprocess.DEVNULL).strip()
        if not container:
            return False
        result = subprocess.run(["docker", "exec", "-i", container, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1",
                                 "-U", environment["POSTGRES_USER"], "-d", database],
                                input=sql, text=True, capture_output=True, timeout=15)
        return result.returncode == 0 and result.stdout.strip() == "t"
    except (OSError, KeyError, subprocess.SubprocessError):
        return False


def run(environment, api_url):
    checks = configuration_checks(environment)
    checks.append(("Business database schema", schema_ready(environment, environment.get("POSTGRES_DB", "findie"),
        "SELECT to_regclass('public.items') IS NOT NULL AND to_regclass('public.index_outbox') IS NOT NULL "
        "AND to_regclass('public.\"__EFMigrationsHistory\"') IS NOT NULL;"), "run make local-setup"))
    checks.append(("Search database schema", schema_ready(environment, environment.get("SEARCH_POSTGRES_DB", "findie_search"),
        "SELECT to_regclass('public.ai_items') IS NOT NULL AND to_regclass('public.ai_documents') IS NOT NULL "
        "AND to_regclass('public.ai_search_state') IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector');"), "run make local-setup"))
    checks.append(("Demo Hub staff", schema_ready(environment, environment.get("POSTGRES_DB", "findie"),
        "SELECT EXISTS (SELECT 1 FROM point_staff s JOIN reception_points p ON p.id=s.point_id "
        "JOIN app_users u ON u.id=s.user_id WHERE p.active AND s.revoked_at IS NULL "
        "AND s.can_receive AND s.can_return AND u.disabled_at IS NULL);"),
        "sign in with Google, then make local-seed STAFF_EMAIL=your-email"))

    credentials = environment.get("RABBITMQ_ADMIN_USER", "") + ":" + environment.get("RABBITMQ_ADMIN_PASSWORD", "")
    queues = get_json("http://127.0.0.1:" + environment.get("RABBITMQ_MANAGEMENT_PORT", "15672") + "/api/queues/%2F",
                      {"Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()})
    expected = {environment.get("AI_" + kind.upper() + "_QUEUE", name) for kind, name in (
        ("index", "findie.ai.commands"), ("query", "findie.ai.query"), ("image", "findie.ai.image"), ("result", "findie.api.results"))}
    consumed = {queue.get("name") for queue in queues if isinstance(queue, dict) and queue.get("consumers", 0) > 0} if isinstance(queues, list) else set()
    checks.append(("RabbitMQ queues and consumers", expected <= consumed,
                   "start the broker, API and full AI worker; all command/query/image/result queues need consumers"))

    ai_url = environment.get("Ai__BaseUrl", "http://127.0.0.1:8000").rstrip("/")
    status = get_json(ai_url + "/v1/status", {"X-Service-Token": environment.get("AI_SERVICE_TOKEN", "")})
    capabilities = status.get("capabilities", {}) if isinstance(status, dict) else {}
    checks.append(("AI dependencies and model capabilities", isinstance(status, dict) and status.get("inferenceReady") is True
                   and isinstance(capabilities, dict)
                   and all(capabilities.get(key) is True for key in ("textSearch", "imageSearch", "imageRedaction")),
                   "authenticated /v1/status must report inferenceReady and all three capabilities"))
    models = status.get("models", {}) if isinstance(status, dict) else {}
    identity_matches = isinstance(status, dict) and isinstance(models, dict) and all((
        models.get("embedding") == environment.get("AI_EMBEDDING_MODEL"),
        models.get("redaction") == environment.get("AI_REDACTION_MODEL"),
        status.get("modelRevision") == environment.get("AI_EMBEDDING_REVISION"),
        status.get("redactionRevision") == environment.get("AI_REDACTION_REVISION"),
        status.get("redactionProfileId") == environment.get("Ai__RedactionProfile", "redact-v4"),
        str(status.get("embeddingDimensions")) == environment.get("AI_EMBEDDING_DIMENSIONS"),
        status.get("searchProfileId") == environment.get("AI_TEXT_SEARCH_PROFILE"),
        status.get("imageSearchProfileId") == environment.get("AI_IMAGE_SEARCH_PROFILE"),
    ))
    checks.append(("Running AI model identity", identity_matches,
                   "restart API/worker after importing Colab settings; live model identities must match .env"))
    ready = get_json(api_url.rstrip("/") + "/health/ready")
    checks.append(("API database readiness", isinstance(ready, dict) and ready.get("status") == "ready",
                   "start the API with the provisioned runtime connection"))
    api = get_json(api_url.rstrip("/") + "/api/system/status")
    features = api.get("features", {}) if isinstance(api, dict) else {}
    checks.append(("API dependency status", isinstance(api, dict) and api.get("database") == "ready" and api.get("ai") == "ready"
                   and isinstance(features, dict) and features.get("authentication") is True and features.get("storage") is True,
                   "API must report database/AI ready and authentication/storage configured"))
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
    print("Google consent, real R2 output/private ACL and search quality still require the documented browser acceptance flow.")
    return 0 if all(passed for _, passed, _ in checks) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:5080")
    arguments = parser.parse_args()
    try:
        raise SystemExit(run(load_environment(), arguments.api_url))
    except (OSError, RuntimeError):
        raise SystemExit("FAIL: local configuration could not be loaded. Run make local-setup first.") from None
