"""Apply EF migrations explicitly, refusing databases with an unknown existing schema."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_TABLES = (
    "app_users", "reception_points", "point_staff", "items", "stored_objects", "item_images",
    "verification_questions", "claims", "claim_answers", "conversations", "messages",
    "intake_requests", "custody_events", "ai_jobs", "item_embeddings", "idempotency_keys",
)


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def migrate(container=None):
    database = os.environ["POSTGRES_DB"]
    administrator = os.environ["POSTGRES_USER"]
    app_user = os.environ["POSTGRES_APP_USER"]
    app_password = os.environ["POSTGRES_APP_PASSWORD"]
    if not app_password or "\x00" in app_password or app_user == administrator:
        raise ValueError("A separate runtime role and nonempty password are required.")
    if not container:
        container = subprocess.check_output(["docker", "compose", "ps", "-q", "db"], cwd=ROOT, text=True).strip()
    if not container:
        raise RuntimeError("Start PostgreSQL with make db-up first.")

    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "migration.sql"
        subprocess.run([
            "dotnet", "ef", "migrations", "script", "--project", str(ROOT / "apps/api"),
            "--idempotent", "--no-transactions", "--output", str(script),
        ], cwd=ROOT, check=True)
        tables = ", ".join(identifier(table) for table in BOOTSTRAP_TABLES)
        table_names = ", ".join(literal(table) for table in BOOTSTRAP_TABLES)
        preflight = f"""
BEGIN;
SET LOCAL standard_conforming_strings = on;
SELECT pg_advisory_xact_lock(643182015);
DO $preflight$
DECLARE existing text[]; expected text[]; name text; populated boolean;
BEGIN
    IF to_regclass('public."__EFMigrationsHistory"') IS NULL THEN
        SELECT array_agg(tablename ORDER BY tablename) INTO existing FROM pg_tables WHERE schemaname = 'public';
        SELECT array_agg(value ORDER BY value) INTO expected FROM unnest(ARRAY[{table_names}]) AS value;
        IF existing IS NOT NULL THEN
            IF existing IS DISTINCT FROM expected THEN
                RAISE EXCEPTION 'Unknown schema; refusing automatic migration. Back up and prepare a data migration.';
            END IF;
            LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE;
            FOREACH name IN ARRAY existing LOOP
                EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I LIMIT 1)', name) INTO populated;
                IF populated THEN
                    RAISE EXCEPTION 'Bootstrap contains data; refusing migration. Prepare an explicit data migration.';
                END IF;
            END LOOP;
            DROP TABLE {tables};
        END IF;
    END IF;
END $preflight$;
"""
        # Credentials travel on stdin; psql error context must not echo the role password.
        privileges = f"""
SELECT format('CREATE ROLE %I LOGIN', {literal(app_user)})
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(app_user)})
\\gexec
ALTER ROLE {identifier(app_user)} PASSWORD {literal(app_password)};
GRANT CONNECT ON DATABASE {identifier(database)} TO {identifier(app_user)};
GRANT USAGE ON SCHEMA public TO {identifier(app_user)};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {identifier(app_user)};
REVOKE ALL ON TABLE "__EFMigrationsHistory" FROM {identifier(app_user)};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {identifier(app_user)};
COMMIT;
"""
        result = subprocess.run([
            "docker", "exec", "-i", container, "psql", "-X", "-v", "ON_ERROR_STOP=1",
            "--set", "VERBOSITY=terse", "-U", administrator, "-d", database,
        ], input=preflight + script.read_text(encoding="utf-8-sig") + privileges, text=True, capture_output=True)
        if result.returncode:
            detail = result.stderr.replace(app_password.replace("'", "''"), "[redacted]").replace(app_password, "[redacted]")
            raise RuntimeError("Migration rolled back: " + detail.strip())
    print("Applied EF migrations and runtime role grants; existing data preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", help="PostgreSQL container; defaults to the Compose db service")
    migrate(parser.parse_args().container)
