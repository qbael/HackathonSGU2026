"""Create local development secrets without overwriting existing configuration."""

from pathlib import Path
import os
import re
import secrets
import tempfile


def initialize(root: Path) -> bool:
    target = root / ".env"
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace("GENERATE_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_APP_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_SEARCH_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_AI_SERVICE_TOKEN", secrets.token_hex(32))
    for role in ("ADMIN", "API", "AI"):
        content = content.replace(f"GENERATE_RABBITMQ_{role}_PASSWORD", secrets.token_hex(24))
    try:
        with open(target, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
            file.write(content)
    except FileExistsError:
        previous = target.read_text(encoding="utf-8")
        present = dict(re.findall(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z_0-9]*)=(.*)$", previous, re.MULTILINE))
        defaults = {match[1]: line for line in content.splitlines()
                    if (match := re.match(r"^([A-Za-z_][A-Za-z_0-9]*)=", line))}
        missing = {key: line for key, line in defaults.items() if key not in present}
        old_connection = 'ConnectionStrings__Database="Host=127.0.0.1;Port=${POSTGRES_PORT};Database=${POSTGRES_DB};Username=${POSTGRES_USER};Password=${POSTGRES_PASSWORD};Timeout=5"'
        if old_connection in previous.splitlines():
            previous = previous.replace(old_connection, "# Runtime connection moved below the service credentials.")
            missing["ConnectionStrings__Database"] = defaults["ConnectionStrings__Database"]
        broker_value = present.get("RabbitMq__Uri", "").strip().strip("\"'")
        new_credentials = any(key.startswith("RABBITMQ_") for key in missing)
        if new_credentials and not broker_value and "RabbitMq__Uri" in present:
            pattern = r"^[ \t]*(?:export[ \t]+)?RabbitMq__Uri=.*$"
            missing["RabbitMq__Uri"] = re.findall(pattern, previous, re.MULTILINE)[-1]
            previous = re.sub(pattern, "# .NET RabbitMQ setting moved below the service credentials.", previous, flags=re.MULTILINE)
        ai_default = defaults["AI_RABBITMQ_URL"].split("=", 1)[1]
        ai_value = present.get("AI_RABBITMQ_URL", "").strip().strip("\"'")
        if (ai_value == ai_default and new_credentials) or (not broker_value and ai_value == "${RabbitMq__Uri}"):
            # Shell interpolation must happen after the newly added credentials.
            previous = re.sub(r"^[ \t]*(?:export[ \t]+)?AI_RABBITMQ_URL=.*$",
                              "# Python RabbitMQ URI moved below the service credentials.", previous, flags=re.MULTILINE)
            missing["AI_RABBITMQ_URL"] = defaults["AI_RABBITMQ_URL"]
        if not missing:
            return False
        updated = previous.rstrip() + "\n\n# Added missing service settings.\n" + "\n".join(missing.values()) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix=".env.", delete=False) as file:
                temporary = Path(file.name)
                file.write(updated)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True
    return True


if __name__ == "__main__":
    created = initialize(Path(__file__).resolve().parents[1])
    print("Initialized .env settings; existing secrets preserved." if created else ".env already exists; kept unchanged.")
