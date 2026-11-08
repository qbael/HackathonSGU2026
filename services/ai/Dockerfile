FROM ghcr.io/astral-sh/uv:0.9.8 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsS https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /usr/local/share/rds-ca.pem \
    && useradd --uid 1654 --create-home worker
COPY services/ai/pyproject.toml services/ai/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY services/ai/findie_ai/ findie_ai/
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER worker
EXPOSE 8000
ENTRYPOINT ["uvicorn", "findie_ai.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
