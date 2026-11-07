"""Run the three local application processes; stop only processes started here."""

import argparse
import os
import signal
import socket
import subprocess
import time

from local_doctor import configuration_checks, get_json
from local_setup import ROOT, load_environment


def runtime_environment(environment, service):
    # Each process receives only its own credentials, including when the caller sourced .env.
    platform = {key: value for key, value in environment.items() if key in {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "TMPDIR", "TEMP", "TMP",
        "LD_LIBRARY_PATH", "SSL_CERT_FILE", "SSL_CERT_DIR", "UV_CACHE_DIR", "DOTNET_ROOT", "NODE_EXTRA_CA_CERTS"}}
    for key, value in environment.items():
        if service == "ai" and (key.startswith("AI_") and key not in {"AI_SEARCH_MIGRATION_DSN", "AI_TEST_DATABASE_URL"}
                                or key in {"OLLAMA_BASE_URL", "OLLAMA_API_KEY"}):
            platform[key] = value
        if service == "api" and (key.startswith(("Ai__", "Authentication__", "Storage__", "RabbitMq__", "Logging__", "Admin"))
                                 or key in {"ConnectionStrings__Database", "ADMIN_EMAILS", "AdminEmails"}):
            platform[key] = value
    return platform


def stop(processes):
    for process in reversed(processes):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def wait_ready(process, url, ready, *, headers=None, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A local service exited before becoming ready; check its preceding output.")
        data = get_json(url, headers)
        if ready(data):
            return
        time.sleep(1)
    raise RuntimeError("A local service did not become ready. Check Colab/ngrok, model config and database migrations.")


def single_service(service):
    commands = {
        "ai": ["uv", "run", "--project", "services/ai", "--locked", "uvicorn", "findie_ai.main:app",
               "--app-dir", "services/ai", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
        "api": ["dotnet", "run", "--project", "apps/api", "--no-launch-profile"],
        "web": ["npm", "run", "dev", "--prefix", "apps/web"],
    }
    environment = runtime_environment(load_environment(), service)
    if service == "api":
        environment |= {"ASPNETCORE_ENVIRONMENT": "Development", "ASPNETCORE_URLS": "http://127.0.0.1:5080"}
    os.chdir(ROOT)
    os.execvpe(commands[service][0], commands[service], environment)


def main():
    environment = load_environment()
    missing = [name for name, passed, _ in configuration_checks(environment) if not passed]
    if missing:
        raise RuntimeError("Full local configuration missing: " + ", ".join(missing)
                           + ". Run make local-setup and import notebook 04 with scripts/configure_ollama.py.")
    for port in (5173, 5080, 8000):
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is already in use; stop that service before make local-run.")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "db", "rabbitmq", "redis"], cwd=ROOT, env=environment, check=True)
    subprocess.run(["dotnet", "build", "apps/api", "--no-restore", "--verbosity", "quiet"], cwd=ROOT, env=environment, check=True)
    processes = []

    def start(service, command, extra=None):
        process = subprocess.Popen(command, cwd=ROOT, env=runtime_environment(environment, service) | (extra or {}), start_new_session=True)
        processes.append(process)
        return process

    def terminated(_signal, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, terminated)
    try:
        print("Starting AI worker and verifying remote models…", flush=True)
        ai = start("ai", ["uv", "run", "--project", "services/ai", "--locked", "uvicorn", "findie_ai.main:app",
                    "--app-dir", "services/ai", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"])
        wait_ready(ai, environment.get("Ai__BaseUrl", "http://127.0.0.1:8000").rstrip("/") + "/v1/status",
                   lambda data: isinstance(data, dict) and data.get("inferenceReady") is True
                   and all(data.get("capabilities", {}).get(key) is True for key in ("textSearch", "imageSearch", "imageRedaction")),
                   headers={"X-Service-Token": environment["AI_SERVICE_TOKEN"]})
        api = start("api", ["dotnet", "run", "--project", "apps/api", "--no-build", "--no-launch-profile"],
                    {"ASPNETCORE_ENVIRONMENT": "Development", "ASPNETCORE_URLS": "http://127.0.0.1:5080"})
        wait_ready(api, "http://127.0.0.1:5080/health/ready", lambda data: isinstance(data, dict) and data.get("status") == "ready")
        web = start("web", ["npm", "run", "dev", "--prefix", "apps/web"])
        wait_ready(web, "http://127.0.0.1:5173/api/system/status",
                   lambda data: isinstance(data, dict) and data.get("database") == "ready" and data.get("ai") == "ready")
        print("Findie ready: http://127.0.0.1:5173 — Ctrl+C stops web/API/worker; database volumes are kept.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("A service stopped; the other processes started here have been stopped too.")
    except KeyboardInterrupt:
        print("Stopping local application processes…", flush=True)
    finally:
        stop(processes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=("ai", "api", "web"), help="run one service with only its own credentials")
    arguments = parser.parse_args()
    try:
        single_service(arguments.service) if arguments.service else main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error) if isinstance(error, RuntimeError) else "Local startup failed; see preceding output.") from None
