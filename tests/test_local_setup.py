import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import local_setup
import local_doctor


def environment():
    return {
        "POSTGRES_DB": "business", "POSTGRES_USER": "administrator", "POSTGRES_PASSWORD": "admin :@'password",
        "POSTGRES_PORT": "5432", "POSTGRES_APP_USER": "business_app",
        "SEARCH_POSTGRES_DB": "search", "SEARCH_POSTGRES_USER": "search_app", "SEARCH_POSTGRES_PASSWORD": "search @'password",
        "RABBITMQ_API_USER": "api", "RABBITMQ_API_PASSWORD": "broker @password", "RABBITMQ_PORT": "5672",
    }


class LocalSetupTest(unittest.TestCase):
    def test_connections_encode_passwords_keep_custom_credentials_and_repeat_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = "Authentication__Google__ClientSecret='kept google secret'\nStorage__SecretAccessKey='kept R2 secret'\n"
            (root / ".env").write_text(original)
            configured = local_setup.complete_local_connections(root, environment())
            self.assertIn("search%20%40%27password", configured["AI_SEARCH_DSN"])
            self.assertNotEqual(configured["AI_SEARCH_DSN"], configured["AI_SEARCH_MIGRATION_DSN"])
            self.assertTrue((root / ".env").read_text().startswith(original))
            first = (root / ".env").read_text()
            loaded = local_setup.load_environment(root)
            self.assertEqual(loaded["AI_SEARCH_DSN"], configured["AI_SEARCH_DSN"])
            local_setup.complete_local_connections(root, environment() | loaded)
            self.assertEqual((root / ".env").read_text(), first)
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)

    def test_custom_connection_is_not_replaced_or_migrated(self):
        configured = environment() | local_setup.local_connections(environment())
        configured["AI_SEARCH_DSN"] = "postgresql://custom:secret@remote.example/custom"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("# existing configuration\n")
            self.assertEqual(local_setup.complete_local_connections(root, configured), configured)
            with self.assertRaisesRegex(ValueError, "only migrates the local"):
                local_setup.search_preflight(configured)

    def test_search_role_and_database_must_be_separate(self):
        for changed in ({"SEARCH_POSTGRES_USER": "administrator"}, {"SEARCH_POSTGRES_USER": "business_app"},
                        {"SEARCH_POSTGRES_DB": "business"}, {"SEARCH_POSTGRES_PASSWORD": ""}):
            values = environment() | changed
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                local_setup.search_preflight(values | local_setup.local_connections(values))

    def test_search_runtime_dsn_cannot_use_administrator(self):
        values = environment() | local_setup.local_connections(environment())
        values["AI_SEARCH_DSN"] = values["AI_SEARCH_MIGRATION_DSN"]
        with self.assertRaisesRegex(ValueError, "only migrates the local"):
            local_setup.search_preflight(values)

    def test_provisioning_errors_never_echo_password_or_sql(self):
        values = environment()
        result = subprocess.CompletedProcess([], 1, stdout="", stderr=values["SEARCH_POSTGRES_PASSWORD"])
        with patch.object(local_setup.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "provisioning failed") as raised:
                local_setup.psql("test", values, "search", "ALTER ROLE password='secret'")
        self.assertNotIn(values["SEARCH_POSTGRES_PASSWORD"], str(raised.exception))


class LocalInfrastructureTest(unittest.TestCase):
    def test_first_and_repeated_start_import_fresh_host_definitions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definitions = root / ".cache/rabbitmq/definitions.json"
            commands, imported = [], []
            values = {"PATH": "/usr/bin"}

            def execute(command, **kwargs):
                commands.append(command)
                self.assertEqual(kwargs["cwd"], root)
                self.assertIs(kwargs["env"], values)
                if command == ["python3", "scripts/init_rabbitmq.py"]:
                    definitions.parent.mkdir(parents=True, exist_ok=True)
                    replacement = definitions.with_suffix(".new")
                    replacement.write_bytes(b'{"permissions":[' + str(len(imported)).encode() + b']}')
                    replacement.replace(definitions)
                elif "up" in command:
                    self.assertTrue(definitions.exists())
                    self.assertIn("--wait", command)
                else:
                    self.assertEqual(command, ["docker", "compose", "exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "import_definitions", "/dev/stdin"])
                    self.assertTrue(kwargs["capture_output"])
                    imported.append(kwargs["stdin"].read())
                return subprocess.CompletedProcess(command, 0)

            with patch.object(local_setup, "ROOT", root), patch.object(local_setup.subprocess, "run", side_effect=execute), \
                    contextlib.redirect_stdout(io.StringIO()):
                local_setup.start_infrastructure(values)
                local_setup.start_infrastructure(values)
            self.assertEqual(imported, [b'{"permissions":[0]}', b'{"permissions":[1]}'])
            self.assertEqual(len(commands), 6)

    def test_import_failure_reports_safe_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definitions = root / ".cache/rabbitmq/definitions.json"
            definitions.parent.mkdir(parents=True)
            definitions.write_bytes(b"{}")
            results = [subprocess.CompletedProcess([], code, stdout=b"private-output", stderr=b"private-error")
                       for code in (0, 0, 1)]
            with patch.object(local_setup, "ROOT", root), patch.object(local_setup.subprocess, "run", side_effect=results), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(RuntimeError, "RabbitMQ definitions import failed") as raised:
                    local_setup.start_infrastructure({})
            self.assertNotIn("private", str(raised.exception) + output.getvalue())


class LocalDoctorTest(unittest.TestCase):
    def configured(self):
        values = environment() | local_setup.local_connections(environment())
        for key in ("Authentication__Google__ClientId", "Authentication__Google__ClientSecret", "Storage__Endpoint", "Storage__Bucket",
                    "Storage__AccessKeyId", "Storage__SecretAccessKey", "AI_RABBITMQ_URL"):
            values[key] = "configured"
        values |= {"AI_SERVICE_TOKEN": "test-token", "Ai__ServiceToken": "test-token", "AI_IMAGE_SEARCH_ENABLED": "true"}
        for python_key, api_key, value in (
            ("AI_EMBEDDING_MODEL", "Ai__EmbeddingModelId", "model"), ("AI_EMBEDDING_REVISION", "Ai__EmbeddingRevision", "a" * 64),
            ("AI_EMBEDDING_DIMENSIONS", "Ai__EmbeddingDimensions", "768"), ("AI_REDACTION_MODEL", "Ai__RedactionModelId", "vision"),
            ("AI_REDACTION_REVISION", "Ai__RedactionRevision", "b" * 64), ("AI_IMAGE_SEARCH_PROFILE", "Ai__ImageSearchProfile", "image-only-v1"),
            ("AI_TEXT_SEARCH_PROFILE", "Ai__TextSearchProfile", "text-description-v1"),
        ):
            values[python_key] = values[api_key] = value
        return values

    def test_missing_or_mismatched_model_revision_is_not_ready(self):
        values = self.configured()
        self.assertTrue(all(check[1] for check in local_doctor.configuration_checks(values)))
        values["Ai__RedactionRevision"] = "latest"
        self.assertFalse(all(check[1] for check in local_doctor.configuration_checks(values)))

    def test_liveness_or_incomplete_capabilities_cannot_make_the_stack_ready(self):
        def response(url, headers=None):
            if "/api/queues/" in url:
                return [{"name": name, "consumers": 1} for name in ("findie.ai.commands", "findie.ai.query", "findie.ai.image", "findie.api.results")]
            if url.endswith("/v1/status"):
                return {"inferenceReady": True, "capabilities": {"textSearch": True, "imageSearch": False, "imageRedaction": False}}
            if url.endswith("/api/system/status"):
                return {"database": "ready", "ai": "ready", "features": {"authentication": True, "storage": True}}
            if url.endswith("/health/ready"):
                return {"status": "ready"}
            raise AssertionError("Doctor must not use health/live")
        with patch.object(local_doctor, "get_json", side_effect=response), patch.object(local_doctor, "schema_ready", return_value=True), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(local_doctor.run(self.configured(), "http://127.0.0.1:5080"), 1)
        self.assertIn("FAIL AI dependencies", output.getvalue())
        self.assertNotIn("test-token", output.getvalue())

    def test_full_ready_requires_running_identity_and_all_consumers(self):
        values = self.configured()
        def response(url, headers=None):
            if "/api/queues/" in url:
                return [{"name": name, "consumers": 1} for name in ("findie.ai.commands", "findie.ai.query", "findie.ai.image", "findie.api.results")]
            if url.endswith("/v1/status"):
                return {"inferenceReady": True, "capabilities": {"textSearch": True, "imageSearch": True, "imageRedaction": True},
                        "models": {"embedding": "model", "redaction": "vision"}, "modelRevision": "a" * 64,
                        "redactionRevision": "b" * 64, "redactionProfileId": "redact-v4",
                        "embeddingDimensions": 768, "searchProfileId": "text-description-v1",
                        "imageSearchProfileId": "image-only-v1"}
            if url.endswith("/api/system/status"):
                return {"database": "ready", "ai": "ready", "features": {"authentication": True, "storage": True}}
            return {"status": "ready"}
        with patch.object(local_doctor, "get_json", side_effect=response), patch.object(local_doctor, "schema_ready", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(local_doctor.run(values, "http://127.0.0.1:5080"), 0)
            values["Ai__RedactionProfile"] = "redact-v2"
            self.assertEqual(local_doctor.run(values, "http://127.0.0.1:5080"), 1)
            values["Ai__RedactionProfile"] = "redact-v4"
            values["AI_EMBEDDING_MODEL"] = values["Ai__EmbeddingModelId"] = "changed-after-worker-start"
            self.assertEqual(local_doctor.run(values, "http://127.0.0.1:5080"), 1)


if __name__ == "__main__":
    unittest.main()
