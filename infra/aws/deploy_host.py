"""SSM host deployment. Secret values stay in memory and never enter command arguments or logs."""
import json
import os
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError("Deployment command failed: " + args[0])
    return result.stdout


def secret(name, region, environment=None):
    return run(["aws", "secretsmanager", "get-secret-value", "--secret-id", name, "--region", region,
                "--query", "SecretString", "--output", "text"], text=True, env=environment).strip()


def configuration(role, region, domain, worker, redis):
    config = json.loads(secret("findie/production/" + ("api" if role == "app" else "worker"), region))
    token = secret("findie/production/service-token", region)
    required = ("ConnectionStrings__Database", "Authentication__Google__ClientId", "Authentication__Google__ClientSecret",
                "Storage__Endpoint", "Storage__Bucket", "Storage__AccessKeyId", "Storage__SecretAccessKey", "RabbitMq__Uri",
                "Ai__EmbeddingRevision", "Ai__RedactionRevision") if role == "app" else (
                "AI_SEARCH_DSN", "AI_RABBITMQ_URL", "OLLAMA_BASE_URL", "OLLAMA_API_KEY", "AI_EMBEDDING_REVISION", "AI_REDACTION_REVISION")
    missing = [key for key in required if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        raise ValueError("Missing secret fields: " + ", ".join(missing))
    if role == "app":
        config.update(Ai__BaseUrl="http://" + worker + ":8000", Ai__ServiceToken=token, Ai__TimeoutSeconds="15",
                      Ai__PrivateHttpImages="true", Ai__AsyncJobs="true", AllowedHosts=domain + ";localhost;127.0.0.1",
                      ForwardedHosts=domain, DataProtection__KeyPath="/keys", Logging__LogLevel__Default="Warning")
    else:
        config.update(AI_SERVICE_TOKEN=token, AI_REDIS_URL="rediss://" + redis + ":6379/0")
    if any(not isinstance(v, str) or "\x00" in v or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", k) for k, v in config.items()):
        raise ValueError("Invalid server configuration shape.")
    return config, token


def healthy(port, path, token):
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}{path}", headers={"X-Service-Token": token}), timeout=18) as response:
            return response.status == 200
    except Exception:
        return False


def main():
    role, image, domain, worker, redis, action, migration_role = sys.argv[1:]
    if role not in {"app", "worker"} or not re.fullmatch(r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/findie-" + role + r":[a-f0-9]{40}", image):
        raise ValueError("Invalid role or immutable image.")
    region, registry = image.split(".")[3], image.split("/")[0]
    name, previous = "findie-" + role, "findie-" + role + "-previous"
    if action == "rollback":
        existing = run(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True).splitlines()
        if previous in existing:
            run(["docker", "rm", "-f", name])
            run(["docker", "rename", previous, name])
            run(["docker", "start", name])
        print("Rollback complete: " + role)
        return
    if action == "migrate":
        credentials = json.loads(run(["aws", "sts", "assume-role", "--role-arn", migration_role,
            "--role-session-name", "findie-migration", "--region", region, "--output", "json"], text=True))["Credentials"]
        environment = os.environ | {"AWS_ACCESS_KEY_ID": credentials["AccessKeyId"], "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"], "AWS_SESSION_TOKEN": credentials["SessionToken"]}
        config = json.loads(secret("findie/production/migration", region, environment))
        if not all(config.get(key) for key in ("ConnectionStrings__Database", "AI_SEARCH_MIGRATION_DSN")):
            raise ValueError("Configure separate migration credentials before deployment.")
        snapshot = "findie-predeploy-" + image.rsplit(":", 1)[1]
        existing = json.loads(run(["aws", "rds", "describe-db-snapshots", "--db-instance-identifier", "findie-postgres", "--region", region,
                                  "--query", "DBSnapshots[].DBSnapshotIdentifier", "--output", "json"], text=True, env=environment))
        if snapshot not in existing:
            run(["aws", "rds", "create-db-snapshot", "--db-instance-identifier", "findie-postgres", "--db-snapshot-identifier", snapshot, "--region", region], env=environment)
        run(["aws", "rds", "wait", "db-snapshot-available", "--db-snapshot-identifier", snapshot, "--region", region], env=environment)
        token = ""
    else:
        config, token = configuration(role, region, domain, worker, redis)
    password = run(["aws", "ecr", "get-login-password", "--region", region])
    try:
        run(["docker", "login", "--username", "AWS", "--password-stdin", registry], input=password)
        run(["docker", "pull", image])
    finally:
        run(["docker", "logout", registry])
    if action == "migrate":
        args = ["docker", "run", "--rm", "--read-only", "--log-driver", "none", "--cap-drop", "ALL", "--ulimit", "core=0",
                "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m"]
        key = "ConnectionStrings__Database" if role == "app" else "AI_SEARCH_MIGRATION_DSN"
        command = ["--migrate"] if role == "app" else ["python", "-m", "findie_ai.migrate"]
        if role == "worker": args += ["--entrypoint", "/app/.venv/bin/python"]
        if role == "worker": command = ["-m", "findie_ai.migrate"]
        run(args + ["--env", key, image] + command, env=os.environ | {key: config[key]})
        print("Migration complete: " + role)
        return
    existing = run(["docker", "ps", "-a", "--format", "{{.Names}}"], text=True).splitlines()
    if previous in existing:
        run(["docker", "rm", "-f", previous])
    rollback = name in existing
    if rollback:
        run(["docker", "stop", "--time", "60", name])
        run(["docker", "rename", name, previous])
    port = 8080 if role == "app" else 8000
    args = ["docker", "run", "-d", "--name", name, "--restart", "unless-stopped", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--ulimit", "core=0", "--log-driver", "none",
            "--memory", "1200m" if role == "app" else "2500m", "--memory-swap", "1200m" if role == "app" else "2500m",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=256m", "--publish", f"{port}:{port}"]
    if role == "app":
        args += ["--volume", "/var/lib/findie/keyring:/keys"]
    for key in config:
        args += ["--env", key]
    try:
        run(args + [image], env=os.environ | config)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if healthy(port, "/health/ready" if role == "app" else "/health/live", token):
                if role == "worker" and not healthy(port, "/health/ready", token):
                    print("Worker is live; inference dependencies are unavailable.")
                if role == "app" and not healthy(port, "/health/live", token):
                    raise RuntimeError("Application smoke check failed.")
                print("Deployment ready: " + role + " " + image.rsplit(":", 1)[1])
                return
            time.sleep(3)
        raise RuntimeError("Readiness check failed.")
    except Exception:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        if rollback:
            run(["docker", "rename", previous, name])
            run(["docker", "start", name])
        raise RuntimeError("Deployment failed; previous container restored if available.") from None


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Only our fixed messages and configuration key names may reach SSM output.
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else "Deployment failed.", file=sys.stderr)
        sys.exit(1)
