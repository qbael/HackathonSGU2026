"""Replay current public snapshots/tombstones after intentionally changing models."""

import subprocess

from local_doctor import get_json
from local_setup import ROOT, load_environment, psql


def main():
    environment = load_environment()
    status = get_json(environment.get("Ai__BaseUrl", "http://127.0.0.1:8000").rstrip("/") + "/v1/status",
                      {"X-Service-Token": environment["AI_SERVICE_TOKEN"]})
    if not isinstance(status, dict) or status.get("inferenceReady") is not True:
        raise RuntimeError("Start the configured worker and verify readiness before replaying current snapshots.")
    if (status.get("models", {}).get("embedding") != environment.get("Ai__EmbeddingModelId")
            or status.get("modelRevision") != environment.get("Ai__EmbeddingRevision")):
        raise RuntimeError("Worker and API model identities differ; restart with the imported configuration.")
    container = subprocess.check_output(["docker", "compose", "ps", "-q", "db"], cwd=ROOT, env=environment, text=True).strip()
    if not container:
        raise RuntimeError("Start the local database first.")
    psql(container, environment, environment["POSTGRES_DB"], """
BEGIN;
WITH latest AS (
  SELECT DISTINCT ON (item_id) id FROM index_outbox ORDER BY item_id, document_version DESC
)
UPDATE index_outbox AS job
SET status = 'pending', attempts = 0, next_attempt_at = now(), lease_token = NULL,
    lease_until = NULL, finished_at = NULL, last_error_code = NULL
FROM latest
WHERE job.id = latest.id
  AND (job.status <> 'running' OR job.lease_until <= now())
  AND (job.event_kind = 'tombstone'
       OR EXISTS (SELECT 1 FROM items i WHERE i.id = job.item_id
           AND i.document_version = job.document_version
           AND i.publication_state = 'published' AND i.lifecycle = 'active'));
COMMIT;
""")
    print("Current public snapshots/tombstones scheduled for replay; active leases and user data were preserved.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, RuntimeError) else "Local reindex could not access the configured services.") from None
