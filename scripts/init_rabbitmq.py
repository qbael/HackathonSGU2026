"""Generate local RabbitMQ boot definitions with salted password hashes."""

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile


def initialize(root: Path) -> Path:
    definitions = json.loads((root / "docs/api/rabbitmq-definitions.json").read_text(encoding="utf-8"))
    definitions["users"] = []
    definitions["permissions"] = []
    permissions = {
        "ADMIN": (".*", ".*", ".*"),
        "API": (r"^amq\.gen-.*$", r"^amq\.default$", r"^(amq\.gen-.*|findie\.api\.results)$"),
        # RabbitMQ 4.3.1+ requires a permission even for the passive result-queue check.
        "AI": (r"^findie\.ai\.(query|image)$", r"^(amq\.default|findie\.api\.results)$",
               r"^findie\.ai\.(commands|query|image)$"),
    }
    names = set()
    for role, (configure, write, read) in permissions.items():
        username = os.environ.get(f"RABBITMQ_{role}_USER", "")
        password = os.environ.get(f"RABBITMQ_{role}_PASSWORD", "")
        if (not username.strip() or not password or password.startswith("GENERATE_")
                or any(ord(character) < 32 or ord(character) == 127 for character in username + password)):
            raise ValueError(f"Set valid RABBITMQ_{role}_USER and RABBITMQ_{role}_PASSWORD before provisioning.")
        if username in names:
            raise ValueError("RabbitMQ administrator, API and AI users must be distinct.")
        names.add(username)
        salt = secrets.token_bytes(4)
        password_hash = base64.b64encode(salt + hashlib.sha256(salt + password.encode("utf-8")).digest()).decode("ascii")
        definitions["users"].append({"name": username, "password_hash": password_hash,
                                     "hashing_algorithm": "rabbit_password_hashing_sha256",
                                     "tags": ["administrator"] if role == "ADMIN" else []})
        definitions["permissions"].append({"user": username, "vhost": "/", "configure": configure,
                                           "write": write, "read": read})

    target = root / ".cache/rabbitmq/definitions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o755)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=".definitions.", delete=False) as file:
            temporary = Path(file.name)
            json.dump(definitions, file, indent=2)
            file.write("\n")
        temporary.chmod(0o644)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    initialize(Path(__file__).resolve().parents[1])
    print("Generated RabbitMQ boot definitions with password hashes.")
