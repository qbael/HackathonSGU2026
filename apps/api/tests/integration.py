"""Run API/Identity/schema checks against a disposable PostgreSQL container."""

import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from local_setup import local_connections, provision_search


def run():
    name = "findie-test-" + secrets.token_hex(6)
    broker_name = name + "-broker"
    database = "findie_test_" + secrets.token_hex(6)
    password = secrets.token_hex(24)
    app_password = secrets.token_hex(24)
    environment = os.environ | {
        "POSTGRES_DB": database, "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": password,
        "POSTGRES_APP_USER": "findie_app", "POSTGRES_APP_PASSWORD": app_password,
        "ConnectionStrings__Database": f"Host=127.0.0.1;Database={database};Username=postgres;Password={password}",
    }
    try:
        subprocess.run([
            "docker", "run", "--detach", "--rm", "--name", name,
            "--env", "POSTGRES_DB", "--env", "POSTGRES_USER", "--env", "POSTGRES_PASSWORD",
            "--publish", "127.0.0.1::5432", "pgvector/pgvector:0.8.2-pg17-trixie",
        ], env=environment, check=True, capture_output=True, text=True)
        deadline = time.monotonic() + 30
        while subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", database],
                             capture_output=True).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Disposable PostgreSQL did not become ready.")
            time.sleep(0.25)
        port = subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True).strip().rsplit(":", 1)[1]
        connection = f"Host=127.0.0.1;Port={port};Database={database};Username=postgres;Password={password}"
        environment["ConnectionStrings__Database"] = connection

        def sql(statement):
            return subprocess.check_output([
                "docker", "exec", "-i", name, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", database, "-At",
            ], input=statement, text=True).strip()

        def migrate(success=True):
            result = subprocess.run(["python3", "scripts/db/migrate.py", "--container", name], cwd=ROOT,
                                    env=environment, text=True, capture_output=True)
            if (result.returncode == 0) != success:
                raise AssertionError("Unexpected migration result: " + result.stdout + result.stderr)

        # Exercise the legacy-schema guard and its rollback on the same disposable database.
        sql((ROOT / "docs/database/database-schema.sql").read_text())
        user_id = "00000000-0000-0000-0000-000000000001"
        sql(f"INSERT INTO app_users (id, auth_issuer, auth_subject, display_name) VALUES ('{user_id}', 'test', 'test', 'Keep me');")
        migrate(success=False)
        assert sql("SELECT display_name FROM app_users;") == "Keep me", "guard must preserve existing data"
        assert sql('SELECT count(*) FROM pg_tables WHERE schemaname = \'public\';') == "16"
        sql("DELETE FROM app_users;")
        migrate()
        migrate()
        assert sql('SELECT count(*) FROM pg_tables WHERE schemaname = \'public\';') == "23", "22 app tables plus migration history"
        search_environment = environment | {
            "POSTGRES_PORT": port, "SEARCH_POSTGRES_DB": database + "_search",
            "SEARCH_POSTGRES_USER": "findie_search_app", "SEARCH_POSTGRES_PASSWORD": secrets.token_hex(24),
            "RABBITMQ_API_USER": "unused", "RABBITMQ_API_PASSWORD": "unused", "RABBITMQ_PORT": "5672",
        }
        search_environment |= local_connections(search_environment)
        provision_search(search_environment, name)
        search_db = search_environment["SEARCH_POSTGRES_DB"]
        def search_sql(statement):
            return subprocess.check_output([
                "docker", "exec", "-i", name, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", search_db, "-At",
            ], input=statement, text=True).strip()
        search_sql(f"INSERT INTO ai_items (item_id, document_version, snapshot_sha256, tombstone) VALUES ('{user_id}', 1, '{'a' * 64}', true);")
        provision_search(search_environment, name)
        assert search_sql("SELECT count(*) FROM ai_items;") == "1", "repeated local search migration preserves data"
        assert search_sql("SELECT has_table_privilege('findie_search_app', 'ai_items', 'SELECT, INSERT, UPDATE, DELETE') "
                          "AND NOT has_schema_privilege('findie_search_app', 'public', 'CREATE');") == "t", "search runtime has DML but no schema ownership"
        environment["ConnectionStrings__Database"] = f"Host=127.0.0.1;Port={port};Database={database};Username=findie_app;Password={app_password}"
        environment["Logging__LogLevel__Default"] = "Warning"
        environment["Logging__LogLevel__Microsoft.AspNetCore"] = "Warning"
        environment["Logging__LogLevel__Microsoft.EntityFrameworkCore.Database.Command"] = "None"
        environment["Logging__LogLevel__Microsoft.AspNetCore.Routing.EndpointRoutingMiddleware"] = "Error"
        environment["Logging__LogLevel__Microsoft.AspNetCore.Mvc.Filters.RequestSizeLimitFilter"] = "Error"
        broker_password = secrets.token_hex(24)
        broker_env = environment | {"RABBITMQ_DEFAULT_USER": "findie_test", "RABBITMQ_DEFAULT_PASS": broker_password}
        subprocess.run([
            "docker", "run", "--detach", "--rm", "--name", broker_name,
            "--env", "RABBITMQ_DEFAULT_USER", "--env", "RABBITMQ_DEFAULT_PASS",
            "--env", "RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS=+S 2:2 -rabbit max_message_size 33554432",
            "--publish", "127.0.0.1::5672",
            "rabbitmq@sha256:76412b1ed2865b88ed01b4a504f72e888842f2089a7527743d325ce7c9d3a43b",
        ], env=broker_env, check=True, capture_output=True, text=True)
        broker_port = subprocess.check_output(["docker", "port", broker_name, "5672/tcp"], text=True).strip().rsplit(":", 1)[1]
        broker_deadline = time.monotonic() + 45
        while True:
            try:
                with socket.create_connection(("127.0.0.1", int(broker_port)), timeout=1) as probe:
                    probe.sendall(b"AMQP\x00\x00\x09\x01")
                    if probe.recv(8):
                        break
            except OSError:
                pass
            if time.monotonic() >= broker_deadline:
                raise RuntimeError("Disposable RabbitMQ did not become ready.")
            time.sleep(0.25)
        environment["FINDIE_TEST_BROKER_URI"] = f"amqp://findie_test:{broker_password}@127.0.0.1:{broker_port}/"
        subprocess.run(["dotnet", "run", "--project", "apps/api/tests/integration", "--no-launch-profile"],
                       cwd=ROOT, env=environment, check=True)
        subprocess.run(["uv", "run", "--project", "services/ai", "--locked", "python", "apps/api/tests/cross_service.py"],
                       cwd=ROOT, env=search_environment | environment | {"AI_SEARCH_DSN": search_environment["AI_SEARCH_DSN"]}, check=True)
        seed_command = ["dotnet", "run", "--project", "apps/api", "--no-build", "--no-launch-profile", "--", "--seed-local",
                        "--staff-email", "owner@example.test"]
        subprocess.run(seed_command, cwd=ROOT, env=environment | {"ASPNETCORE_ENVIRONMENT": "Development"}, check=True)
        production_seed = subprocess.run(seed_command, cwd=ROOT, env=environment | {"ASPNETCORE_ENVIRONMENT": "Production"},
                                         capture_output=True, text=True)
        assert production_seed.returncode != 0 and "allowed only in Development" in production_seed.stderr, "CLI seed is development-only"
        print("PASS: bootstrap/search data preserved; repeated migrations safe; separate runtime roles and local Hub seed verified")
    finally:
        subprocess.run(["docker", "rm", "--force", broker_name], capture_output=True)
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)


if __name__ == "__main__":
    run()
