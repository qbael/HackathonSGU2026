import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("init_env", ROOT / "scripts/init_env.py")
init_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_env)
spec = importlib.util.spec_from_file_location("init_rabbitmq", ROOT / "scripts/init_rabbitmq.py")
init_rabbitmq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_rabbitmq)


class BootstrapTest(unittest.TestCase):
    def test_redis_defaults_use_custom_port_and_preserve_existing_cache_url(self):
        for existing in ("", "AI_REDIS_URL=rediss://custom.example/2\n"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".env.example").write_text((ROOT / ".env.example").read_text())
                (root / ".env").write_text("REDIS_PORT=6385\n" + existing)
                self.assertTrue(init_env.initialize(root))
                expected = "rediss://custom.example/2" if existing else "redis://127.0.0.1:6385/0"
                result = subprocess.run(["sh", "-c", '. "$1"; test "$AI_REDIS_URL" = "$2" && test "$AI_SEARCH_CACHE_TTL_SECONDS" = 60',
                                         "sh", str(root / ".env"), expected], capture_output=True)
                self.assertEqual(result.returncode, 0)
                self.assertFalse(init_env.initialize(root))

    def test_env_has_private_unique_secrets_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            self.assertTrue(init_env.initialize(root))
            first = (root / ".env").read_text()
            self.assertNotIn("GENERATE_", first)
            passwords = re.findall(r"^RABBITMQ_(?:ADMIN|API|AI)_PASSWORD=([a-f0-9]{48})$", first, re.MULTILINE)
            self.assertEqual(len(set(passwords)), 3)
            self.assertRegex(first, r"(?m)^RabbitMq__Uri=$")
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
            self.assertFalse(init_env.initialize(root))
            self.assertEqual((root / ".env").read_text(), first)

    def test_exported_and_indented_settings_keep_their_effective_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            (root / ".env").write_text('export POSTGRES_PASSWORD=existing-secret\n Authentication__Google__ClientId=custom-client\nexport Authentication__Google__ClientSecret=custom-secret\n')
            self.assertTrue(init_env.initialize(root))
            result = subprocess.run(["sh", "-c", '. "$1"; test "$POSTGRES_PASSWORD" = existing-secret && test "$Authentication__Google__ClientId" = custom-client && test "$Authentication__Google__ClientSecret" = custom-secret',
                                     "sh", str(root / ".env")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_env_gains_separate_roles_without_replacing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            old = 'POSTGRES_PASSWORD=existing-secret\nAI_SERVICE_TOKEN=existing-ai-token\nConnectionStrings__Database="Host=127.0.0.1;Port=${POSTGRES_PORT};Database=${POSTGRES_DB};Username=${POSTGRES_USER};Password=${POSTGRES_PASSWORD};Timeout=5"\n'
            (root / ".env").write_text(old)
            self.assertTrue(init_env.initialize(root))
            updated = (root / ".env").read_text()
            self.assertIn("POSTGRES_PASSWORD=existing-secret\n", updated)
            self.assertIn("AI_SERVICE_TOKEN=existing-ai-token\n", updated)
            self.assertIn("Username=${POSTGRES_APP_USER};Password=${POSTGRES_APP_PASSWORD}", updated)
            self.assertLess(updated.index("POSTGRES_APP_PASSWORD="), updated.index("ConnectionStrings__Database="))
            self.assertNotIn("GENERATE_", updated)
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
            self.assertFalse(init_env.initialize(root))

    def test_legacy_broker_settings_expand_after_separate_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            (root / ".env").write_text('POSTGRES_PASSWORD=existing-secret\nRABBITMQ_API_PASSWORD=kept-api-secret\n'
                                       'export RabbitMq__Uri=""\n AI_RABBITMQ_URL=${RabbitMq__Uri}\n')
            self.assertTrue(init_env.initialize(root))
            result = subprocess.run(["sh", "-c", '. "$1"; test "$POSTGRES_PASSWORD" = existing-secret '
                                     '&& test "$RABBITMQ_API_PASSWORD" = kept-api-secret '
                                     '&& test -z "$RabbitMq__Uri" '
                                     '&& test "$AI_RABBITMQ_URL" = "amqp://findie_ai:${RABBITMQ_AI_PASSWORD}@127.0.0.1:5672/%2F" '
                                     '&& test "$RabbitMq__Uri" != "$AI_RABBITMQ_URL"', "sh", str(root / ".env")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = (root / ".env").read_text()
            self.assertIn('export RabbitMq__Uri=""\n', updated)
            self.assertLess(updated.index("RABBITMQ_PORT="), updated.index('export RabbitMq__Uri=""'))
            self.assertFalse(init_env.initialize(root))

    def test_custom_broker_connections_and_credentials_are_preserved(self):
        for worker_uri in ("${RabbitMq__Uri}", "amqps://worker.example.test/%2F"):
            with self.subTest(worker_uri=worker_uri), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".env.example").write_text((ROOT / ".env.example").read_text())
                old = f'RabbitMq__Uri=amqps://broker.example.test/%2F\nAI_RABBITMQ_URL={worker_uri}\nRABBITMQ_AI_PASSWORD=custom-worker-secret\n'
                (root / ".env").write_text(old)
                self.assertTrue(init_env.initialize(root))
                self.assertTrue((root / ".env").read_text().startswith(old))
                self.assertFalse(init_env.initialize(root))


class RabbitMqBootstrapTest(unittest.TestCase):
    def test_definitions_have_verified_hashes_and_runtime_permissions(self):
        environment = {f"RABBITMQ_{role}_{field}": value for role in ("ADMIN", "API", "AI")
                       for field, value in (("USER", "findie_" + role.lower()), ("PASSWORD", "test-secret-" + role))}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment, clear=True):
            root = Path(directory)
            source = root / "docs/api/rabbitmq-definitions.json"
            source.parent.mkdir(parents=True)
            source.write_text((ROOT / "docs/api/rabbitmq-definitions.json").read_text())
            target = init_rabbitmq.initialize(root)
            definitions = json.loads(target.read_text())
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(definitions["queues"], json.loads(source.read_text())["queues"])
            self.assertEqual(len(definitions["users"]), 3)
            for user, role in zip(definitions["users"], ("ADMIN", "API", "AI")):
                password = environment[f"RABBITMQ_{role}_PASSWORD"]
                value = base64.b64decode(user["password_hash"], validate=True)
                self.assertEqual(len(value), 36)
                self.assertEqual(value[4:], hashlib.sha256(value[:4] + password.encode()).digest())
                self.assertNotIn(password, target.read_text())
                self.assertNotIn("password", user)
                self.assertEqual(user["hashing_algorithm"], "rabbit_password_hashing_sha256")
                self.assertEqual(user["tags"], ["administrator"] if role == "ADMIN" else [])
            permissions = {item["user"]: item for item in definitions["permissions"]}
            api, ai = permissions["findie_api"], permissions["findie_ai"]
            for resource in ("amq.gen-example", "findie.api.results"):
                self.assertRegex(resource, api["read"])
            self.assertRegex("amq.gen-example", api["configure"])
            self.assertRegex("findie.api.materials", api["configure"])
            self.assertRegex("findie.api.materials", api["read"])
            self.assertNotRegex("findie.ai.commands", api["configure"])
            self.assertNotRegex("findie.ai.commands", api["read"])
            for permission in (api, ai):
                self.assertRegex("amq.default", permission["write"])
                self.assertNotRegex("findie.ai.dead", permission["read"])
                self.assertNotRegex("findie.ai.dlx", permission["write"])
            self.assertRegex("findie.api.results", ai["write"])
            self.assertNotRegex("findie.api.results", ai["read"])
            for resource in ("findie.ai.query", "findie.ai.image", "findie.ai.materials.results"):
                self.assertRegex(resource, ai["configure"])
                self.assertRegex(resource, ai["read"])
            self.assertRegex("findie.ai.commands", ai["read"])
            self.assertNotRegex("findie.ai.commands", ai["configure"])

    def test_invalid_credentials_do_not_write_definitions(self):
        environment = {f"RABBITMQ_{role}_{field}": value for role in ("ADMIN", "API", "AI")
                       for field, value in (("USER", "findie_" + role.lower()), ("PASSWORD", "test-secret-" + role))}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docs/api/rabbitmq-definitions.json"
            source.parent.mkdir(parents=True)
            source.write_text((ROOT / "docs/api/rabbitmq-definitions.json").read_text())
            for changed in ({"RABBITMQ_AI_PASSWORD": ""}, {"RABBITMQ_AI_USER": "findie_admin"},
                            {"RABBITMQ_API_PASSWORD": "GENERATE_RABBITMQ_API_PASSWORD"}):
                with self.subTest(changed=changed), patch.dict(os.environ, environment | changed, clear=True):
                    with self.assertRaises(ValueError):
                        init_rabbitmq.initialize(root)
                    self.assertFalse((root / ".cache/rabbitmq/definitions.json").exists())


if __name__ == "__main__":
    unittest.main()
