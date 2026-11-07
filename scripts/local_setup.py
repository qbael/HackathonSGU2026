"""Prepare the local databases, broker and demo Hub without resetting data."""

from pathlib import Path
import shlex
import subprocess
import tempfile
from urllib.parse import quote, unquote, urlsplit

from init_env import initialize
from db.migrate import identifier, literal


ROOT = Path(__file__).resolve().parents[1]


def load_environment(root=ROOT):
    # .env is trusted shell configuration, as in the existing Makefile targets.
    result = subprocess.run(["sh", "-c", 'set -a; . "$1"; env -0', "sh", str(root / ".env")],
                            capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Cannot load .env; check its shell syntax.")
    return dict(entry.decode().split("=", 1) for entry in result.stdout.split(b"\0") if entry)


def local_connections(environment):
    host = "127.0.0.1:" + environment["POSTGRES_PORT"]
    def dsn(user, password, database):
        return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}/{quote(database, safe='')}"
    return {
        "AI_SEARCH_DSN": dsn(environment["SEARCH_POSTGRES_USER"], environment["SEARCH_POSTGRES_PASSWORD"], environment["SEARCH_POSTGRES_DB"]),
        "AI_SEARCH_MIGRATION_DSN": dsn(environment["POSTGRES_USER"], environment["POSTGRES_PASSWORD"], environment["SEARCH_POSTGRES_DB"]),
        "RabbitMq__Uri": "amqp://" + quote(environment["RABBITMQ_API_USER"], safe="") + ":"
            + quote(environment["RABBITMQ_API_PASSWORD"], safe="") + "@127.0.0.1:" + environment["RABBITMQ_PORT"] + "/%2F",
    }


def complete_local_connections(root, environment):
    missing = {key: value for key, value in local_connections(environment).items() if not environment.get(key)}
    if not missing:
        return environment
    target = root / ".env"
    content = target.read_text().rstrip() + "\n\n# Provisioned local service connections.\n"
    content += "".join(f"{key}={shlex.quote(value)}\n" for key, value in missing.items())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix=".env.", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.replace(target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return environment | missing


def search_preflight(environment):
    admin, runtime = environment["POSTGRES_USER"], environment["SEARCH_POSTGRES_USER"]
    database, password = environment["SEARCH_POSTGRES_DB"], environment["SEARCH_POSTGRES_PASSWORD"]
    if (not all((admin, runtime, database, password)) or "\0" in admin + runtime + database + password
            or max(len(value.encode()) for value in (admin, runtime, database)) > 63
            or runtime in {admin, environment["POSTGRES_APP_USER"]} or database == environment["POSTGRES_DB"]):
        raise ValueError("Search requires a separate database and runtime role with a nonempty password.")
    for key in ("AI_SEARCH_DSN", "AI_SEARCH_MIGRATION_DSN"):
        value = urlsplit(environment[key])
        role = runtime if key == "AI_SEARCH_DSN" else admin
        if (value.scheme not in {"postgresql", "postgres"} or value.hostname not in {"127.0.0.1", "localhost"}
                or value.port != int(environment["POSTGRES_PORT"]) or value.path != "/" + quote(database, safe="")
                or unquote(value.username or "") != role):
            raise ValueError("local-setup only migrates the local Compose search database; custom DSNs were preserved.")
    return admin, runtime, database, password


def psql(container, environment, database, statement):
    result = subprocess.run(["docker", "exec", "-i", container, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
                             "--set", "VERBOSITY=terse", "-U", environment["POSTGRES_USER"], "-d", database],
                            input=statement, text=True, capture_output=True)
    if result.returncode:
        # Never echo SQL errors: a failing role statement can contain its password.
        raise RuntimeError("Local search provisioning failed; verify database/role names and administrator access.")


def provision_search(environment, container):
    admin, runtime, database, password = search_preflight(environment)
    psql(container, environment, environment["POSTGRES_DB"], f"""
SET standard_conforming_strings = on;
SELECT format('CREATE ROLE %I LOGIN', {literal(runtime)})
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(runtime)})
\\gexec
DO $guard$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(runtime)} AND (rolsuper OR rolcreatedb OR rolcreaterole)) THEN
        RAISE EXCEPTION 'Search runtime role must not be an administrator';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba
               WHERE d.datname={literal(database)} AND r.rolname={literal(runtime)}) THEN
        RAISE EXCEPTION 'Existing search database is owned by runtime; prepare an explicit ownership migration';
    END IF;
END $guard$;
ALTER ROLE {identifier(runtime)} PASSWORD {literal(password)};
SELECT format('CREATE DATABASE %I OWNER %I', {literal(database)}, {literal(admin)})
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = {literal(database)})
\\gexec
REVOKE ALL ON DATABASE {identifier(database)} FROM PUBLIC;
GRANT CONNECT ON DATABASE {identifier(database)} TO {identifier(runtime)};
""")
    subprocess.run(["uv", "run", "--project", "services/ai", "--locked", "python", "-m", "findie_ai.migrate"],
                   cwd=ROOT, env=environment | {"PYTHONPATH": "services/ai"}, check=True)
    psql(container, environment, database, f"""
BEGIN;
DO $guard$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner={literal(runtime)}) THEN
        RAISE EXCEPTION 'Existing search tables are owned by runtime; prepare an explicit ownership migration';
    END IF;
END $guard$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO {identifier(runtime)};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {identifier(runtime)};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {identifier(runtime)};
ALTER DEFAULT PRIVILEGES FOR ROLE {identifier(admin)} IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {identifier(runtime)};
ALTER DEFAULT PRIVILEGES FOR ROLE {identifier(admin)} IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO {identifier(runtime)};
COMMIT;
""")
    print("Search database/schema and separate runtime grants ready; existing data preserved.")


def start_infrastructure(environment):
    subprocess.run(["python3", "scripts/init_rabbitmq.py"], cwd=ROOT, env=environment, check=True)
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "db", "rabbitmq", "redis"],
                   cwd=ROOT, env=environment, check=True)
    # Atomic file replacement can leave a running container's bind mount on the old definitions.
    with (ROOT / ".cache/rabbitmq/definitions.json").open("rb") as definitions:
        result = subprocess.run(["docker", "compose", "exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "import_definitions", "/dev/stdin"],
                                cwd=ROOT, env=environment, stdin=definitions, capture_output=True)
    if result.returncode:
        raise RuntimeError("RabbitMQ definitions import failed; check broker health and local provisioning configuration.")
    print("Local RabbitMQ users, permissions and queues synchronized.", flush=True)


def main():
    initialize(ROOT)
    environment = complete_local_connections(ROOT, load_environment())
    search_preflight(environment)
    start_infrastructure(environment)
    subprocess.run(["python3", "scripts/db/migrate.py"], cwd=ROOT, env=environment, check=True)
    container = subprocess.check_output(["docker", "compose", "ps", "-q", "db"], cwd=ROOT, env=environment, text=True).strip()
    provision_search(environment, container)
    subprocess.run(["dotnet", "run", "--project", "apps/api", "--no-launch-profile", "--", "--seed-local"],
                   cwd=ROOT, env=environment | {"ASPNETCORE_ENVIRONMENT": "Development"}, check=True)
    print("Local infrastructure ready. Import Colab model settings, then start services and run make local-doctor.")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        # External command errors may include configuration; report only our own safe diagnostics.
        raise SystemExit(str(error) if isinstance(error, (ValueError, RuntimeError)) else
                         "Local setup failed; check the preceding service step and local configuration.") from None
