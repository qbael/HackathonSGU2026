"""One-time broker bootstrap on the application host, with temporary secret-write permissions."""
import base64
import json
import secrets
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def aws(*args, value=None):
    result = subprocess.run(["aws", *args, "--region", "ap-southeast-1", "--output", "json"], input=value, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Broker secret operation failed: " + args[1])
    return json.loads(result.stdout)


def main():
    host = sys.argv[1]
    credentials = json.loads(aws("secretsmanager", "get-secret-value", "--secret-id", "findie/production/broker-admin")["SecretString"])
    authorization = "Basic " + base64.b64encode((credentials["username"] + ":" + credentials["password"]).encode()).decode()
    def request(path, method, value):
        with urlopen(Request("https://" + host + path, data=json.dumps(value).encode(), method=method,
                headers={"Authorization": authorization, "Content-Type": "application/json"}), timeout=15) as response:
            response.read()
    permissions = {
        "api": (r"^(amq\.gen-.*|findie\.api\.materials)$", r"^amq\.default$", r"^(amq\.gen-.*|findie\.api\.(results|materials))$"),
        "worker": (r"^findie\.ai\.(query|image|materials\.results)$", r"^(amq\.default|findie\.api\.results)$", r"^findie\.ai\.(commands|query|image|materials\.results)$")}
    for role, (configure, write, read) in permissions.items():
        secret_id = "findie/production/" + role
        config = json.loads(aws("secretsmanager", "get-secret-value", "--secret-id", secret_id)["SecretString"])
        key = "RabbitMq__Uri" if role == "api" else "AI_RABBITMQ_URL"
        if config.get(key):
            from urllib.parse import urlsplit, unquote
            password = unquote(urlsplit(config[key]).password or "")
        else:
            password = secrets.token_hex(32)
        username = "findie_" + role
        deadline = time.monotonic() + 900
        while True:
            try:
                request("/api/users/" + username, "PUT", {"password": password, "tags": ""})
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Broker management endpoint is unavailable.") from None
                time.sleep(5)
        request("/api/permissions/%2F/" + username, "PUT", {"configure": configure, "write": write, "read": read})
        config[key] = "amqps://" + username + ":" + password + "@" + host + ":5671/%2F"
        aws("secretsmanager", "put-secret-value", "--secret-id", secret_id, "--secret-string", "file:///dev/stdin", value=json.dumps(config))
    # Reuse the repository's safe indexing queues and bounded DLQ, never original-image queues.
    definitions = json.loads(base64.b64decode(sys.argv[2]))
    request("/api/definitions", "POST", definitions)
    print("Broker service accounts, ACLs and indexing queues are ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        raise SystemExit("Broker provisioning failed: " + message + "; secret details suppressed.") from None
