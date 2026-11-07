import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("local_run", ROOT / "scripts/local_run.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LocalRunTests(unittest.TestCase):
    def test_single_ai_service_keeps_admin_and_business_credentials_out(self):
        environment = {"PATH": "/usr/bin", "AI_SERVICE_TOKEN": "health", "AI_SEARCH_DSN": "runtime",
                       "AI_SEARCH_MIGRATION_DSN": "admin", "Storage__SecretAccessKey": "private",
                       "Authentication__Google__ClientSecret": "private"}
        with patch.object(module, "load_environment", return_value=environment), patch.object(module.os, "chdir"), \
                patch.object(module.os, "execvpe") as execute:
            module.single_service("ai")
        command, arguments, process_environment = execute.call_args.args
        self.assertEqual(command, "uv")
        self.assertIn("findie_ai.main:app", arguments)
        self.assertEqual(process_environment, {"PATH": "/usr/bin", "AI_SERVICE_TOKEN": "health", "AI_SEARCH_DSN": "runtime"})

    def test_runtime_credentials_never_cross_service_boundaries(self):
        environment = {"PATH": "/usr/bin", "HOME": "/tmp", "AI_SEARCH_DSN": "search-runtime",
                       "AI_SEARCH_MIGRATION_DSN": "search-admin", "AI_SERVICE_TOKEN": "service-token",
                       "AI_RABBITMQ_URL": "python-broker", "OLLAMA_API_KEY": "private-model",
                       "AI_REDIS_URL": "redis://cache:secret@127.0.0.1/0", "AI_SEARCH_CACHE_TTL_SECONDS": "60",
                       "ConnectionStrings__Database": "business-runtime", "Storage__SecretAccessKey": "private-r2",
                       "Authentication__Google__ClientSecret": "private-google", "RabbitMq__Uri": "api-broker",
                       "Ai__ServiceToken": "service-token", "POSTGRES_PASSWORD": "admin"}
        ai = module.runtime_environment(environment, "ai")
        api = module.runtime_environment(environment, "api")
        web = module.runtime_environment(environment, "web")
        self.assertEqual(set(ai), {"PATH", "HOME", "AI_SEARCH_DSN", "AI_SERVICE_TOKEN", "AI_RABBITMQ_URL", "OLLAMA_API_KEY",
                                   "AI_REDIS_URL", "AI_SEARCH_CACHE_TTL_SECONDS"})
        self.assertEqual(set(api), {"PATH", "HOME", "ConnectionStrings__Database", "Storage__SecretAccessKey",
                                    "Authentication__Google__ClientSecret", "RabbitMq__Uri", "Ai__ServiceToken"})
        self.assertEqual(web, {"PATH": "/usr/bin", "HOME": "/tmp"})

    def test_shutdown_stops_only_owned_process_group(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            module.stop([owned])
            self.assertIsNotNone(owned.poll())
            self.assertIsNone(unrelated.poll())
        finally:
            module.stop([owned, unrelated])


if __name__ == "__main__":
    unittest.main()
