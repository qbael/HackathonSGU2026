"""Import the notebook's public model configuration; prompt for its private token."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"OLLAMA_BASE_URL", "AI_EMBEDDING_MODEL", "AI_EMBEDDING_REVISION", "AI_EMBEDDING_DIMENSIONS",
          "AI_EMBEDDING_QUERY_INSTRUCTION", "AI_REDACTION_MODEL", "AI_REDACTION_REVISION",
          "AI_IMAGE_SEARCH_ENABLED", "AI_IMAGE_SEARCH_PROFILE"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def settings(config, token):
    if not isinstance(config, dict) or set(config) != FIELDS:
        raise ValueError("Use findie-colab.json exported by notebook 04; unexpected or missing fields.")
    endpoint = urlsplit(str(config["OLLAMA_BASE_URL"]))
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"}):
        raise ValueError("OLLAMA_BASE_URL must be the HTTPS ngrok origin without a path or credentials.")
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("Use the same private token of at least 32 ASCII characters as in Colab.")
    if type(config["AI_EMBEDDING_DIMENSIONS"]) is not int or not 1 <= config["AI_EMBEDDING_DIMENSIONS"] <= 16000:
        raise ValueError("Invalid embedding dimensions.")
    for field in ("AI_EMBEDDING_REVISION", "AI_REDACTION_REVISION"):
        if not isinstance(config[field], str) or not re.fullmatch(r"[a-f0-9]{64}", config[field]):
            raise ValueError("Both model revisions must be full SHA-256 digests.")
    for field in ("AI_EMBEDDING_MODEL", "AI_REDACTION_MODEL"):
        if not isinstance(config[field], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", config[field]):
            raise ValueError("Invalid model name.")
    if config["AI_IMAGE_SEARCH_ENABLED"] is not True or config["AI_IMAGE_SEARCH_PROFILE"] != "image-only-v1":
        raise ValueError("The full-stack export must enable native image search with image-only-v1.")
    instruction = config["AI_EMBEDDING_QUERY_INSTRUCTION"]
    if not isinstance(instruction, str) or len(instruction) > 2000 or any(ord(c) < 32 for c in instruction):
        raise ValueError("Invalid embedding instruction.")
    result = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items()}
    result["OLLAMA_BASE_URL"] = config["OLLAMA_BASE_URL"].rstrip("/")
    result |= {"OLLAMA_API_KEY": token,
               "Ai__EmbeddingModelId": result["AI_EMBEDDING_MODEL"],
               "Ai__EmbeddingRevision": result["AI_EMBEDDING_REVISION"],
               "Ai__EmbeddingDimensions": result["AI_EMBEDDING_DIMENSIONS"],
               "AI_TEXT_SEARCH_PROFILE": "text-description-v1",
               "Ai__TextSearchProfile": "text-description-v1",
               "Ai__ImageSearchProfile": result["AI_IMAGE_SEARCH_PROFILE"],
               "Ai__RedactionModelId": result["AI_REDACTION_MODEL"],
               "Ai__RedactionRevision": result["AI_REDACTION_REVISION"],
               "Ai__RedactionProfile": "redact-v4"}
    return result


def verify(values):
    headers = {"Authorization": "Bearer " + values["OLLAMA_API_KEY"], "ngrok-skip-browser-warning": "1"}
    try:
        request = Request(values["OLLAMA_BASE_URL"] + "/api/tags", headers=headers)
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError()
        models = json.loads(data)["models"]
        if not isinstance(models, list) or not all(isinstance(model, dict) for model in models):
            raise ValueError()
        for prefix in ("AI_EMBEDDING", "AI_REDACTION"):
            if not any(m.get("name") == values[prefix + "_MODEL"]
                       and str(m.get("digest", "")).removeprefix("sha256:") == values[prefix + "_REVISION"] for m in models):
                raise ValueError()
    except HTTPError as error:
        error.close()
        raise ValueError("Could not verify the ngrok token and both model revisions; .env was kept unchanged.") from None
    except (URLError, OSError, ValueError, KeyError, TypeError):
        raise ValueError("Could not verify the ngrok token and both model revisions; .env was kept unchanged.") from None


def write_env(path, values):
    previous = path.read_text(encoding="utf-8")
    # Remove earlier assignments and append after credential variables to preserve shell expansion order.
    pattern = r"^[ \t]*(?:export[ \t]+)?(" + "|".join(re.escape(k) for k in values) + r")=.*(?:\n|$)"
    content = re.sub(pattern, "", previous, flags=re.MULTILINE).rstrip() + "\n\n# Ollama session imported by configure_ollama.py.\n"
    content += "\n".join(f"{k}={shlex.quote(v)}" for k, v in values.items()) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".env.", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="findie-colab.json downloaded from notebook 04")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        token = getpass.getpass("Private FINDIE_OLLAMA_TOKEN entered in Colab: ")
        values = settings(config, token)
        verify(values)
        write_env(ROOT / ".env", values)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print("Imported model configuration; token stored only in local .env (0600). Restart make local-run.")
    print("Model changes require make local-reindex after the worker is ready.")


if __name__ == "__main__":
    main()
