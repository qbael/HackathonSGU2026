"""Evaluate labelled retrieval baselines or the complete Python search path via AMQP.

Production mode needs a running API/material provider and AI worker, plus
AI_EVALUATION_RABBITMQ_URL credentials allowed to declare a temporary reply queue.
Image fixtures must be synthetic or approved processed images, never saved user uploads.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import ssl
from statistics import mean, median
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import aio_pika
from pydantic import Field, TypeAdapter, model_validator

from .config import Settings, loopback
from .contracts import BatchSearchMetadata, Contract, Query, SearchMetadata
from .ollama import Ollama
from .ranking import MAX_SEARCH_CANDIDATES
from .store import Store


class Case(Contract):
    caseId: str | None = Field(default=None, min_length=1, max_length=200)
    split: Literal["calibration", "test"] = "test"
    mode: Literal["text", "image", "combined"] = "text"
    text: str | None = Field(default=None, max_length=2000)
    images: list[str] = Field(default_factory=list, max_length=3)
    area: str | None = Field(default=None, max_length=200)
    from_: date | None = Field(default=None, alias="from")
    until: date | None = None
    relevantItemIds: list[UUID] = Field(max_length=1000)

    @model_validator(mode="after")
    def valid(self):
        self.text = self.text.strip() or None if self.text is not None else None
        if (self.mode == "text" and (not self.text or self.images)
                or self.mode == "image" and (not self.images or self.text)
                or self.mode == "combined" and (not self.images or not self.text)):
            raise ValueError("Evaluation mode must match the supplied text and image fixtures.")
        if (self.from_ == date.min or self.until == date.max
                or self.from_ and self.until and self.from_ > self.until):
            raise ValueError("Invalid evaluation date range.")
        if len(set(self.relevantItemIds)) != len(self.relevantItemIds):
            raise ValueError("Relevant item labels must be unique.")
        for value in self.images:
            path = Path(value)
            if (not value or "://" in value or path.is_absolute() or ".." in path.parts
                    or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
                raise ValueError("Use relative synthetic or approved processed image fixtures.")
        return self


def validate_cases(cases):
    if not cases or len(cases) > 10000:
        raise ValueError("Use 1–10000 labelled queries.")
    identifiers = [case.caseId for case in cases if case.caseId is not None]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Evaluation case IDs must be unique.")
    calibration = {item for case in cases if case.split == "calibration" for item in case.relevantItemIds}
    test = {item for case in cases if case.split == "test" for item in case.relevantItemIds}
    if calibration & test:
        raise ValueError("Calibration and test must not share relevant items.")


def metrics(rows, *, candidate_pool=True):
    # A row is (unique item IDs, relevant IDs, seconds[, ranking method]).
    queries = [(list(dict.fromkeys(row[0])), row[1]) for row in rows]
    positive = [(hits, relevant) for hits, relevant in queries if relevant]
    negative = [(hits, relevant) for hits, relevant in queries if not relevant]
    returned = sum(len(hits) for hits, _ in queries)
    methods = [row[3] for row in rows if len(row) > 3]
    elapsed = [row[2] * 1000 for row in rows]
    return {
        "queries": len(rows),
        "positiveQueries": len(positive),
        "hitAt10": mean(bool(set(hits[:10]) & relevant) for hits, relevant in positive) if positive else None,
        f"candidateRecallAt{MAX_SEARCH_CANDIDATES}": mean(
            len(set(hits[:MAX_SEARCH_CANDIDATES]) & relevant) / len(relevant)
            for hits, relevant in positive) if positive and candidate_pool else None,
        "mrrAt10": mean(next((1 / rank for rank, item in enumerate(hits[:10], 1) if item in relevant), 0)
                        for hits, relevant in positive) if positive else None,
        "precisionReturned": sum(len(set(hits) & relevant) for hits, relevant in queries) / returned if returned else None,
        "recallReturned": mean(len(set(hits) & relevant) / len(relevant)
                               for hits, relevant in positive) if positive else None,
        "positiveQueriesWithNoResultsRate": mean(not hits for hits, _ in positive) if positive else None,
        "noMatchQueries": len(negative),
        "noMatchWithSuggestionsRate": mean(bool(hits) for hits, _ in negative) if negative else None,
        "meanReturnedCount": mean(len(hits) for hits, _ in queries) if queries else None,
        "meanMilliseconds": mean(elapsed) if elapsed else None,
        "p50Milliseconds": median(elapsed) if elapsed else None,
        "p95Milliseconds": sorted(elapsed)[math.ceil(0.95 * len(elapsed)) - 1] if elapsed else None,
        "fallbackRate": mean(method == "similarity_fallback" for method in methods) if methods else None,
    }


async def evaluate(cases, settings):
    validate_cases(cases)
    if any(case.mode != "text" for case in cases):
        raise ValueError("Use --production to evaluate image or combined queries.")
    model = Ollama(settings)
    store = Store(settings.search_dsn, settings.model_id, settings.revision, settings.dimensions,
                  semantic_weight=settings.semantic_weight)
    rows = {mode: [] for mode in ("semantic", "lexical", "hybrid")}
    try:
        for case in cases:
            async with asyncio.timeout(30):
                started = perf_counter()
                vector = await model.embed(case.text, query=True)
                embedding_time = perf_counter() - started
                for mode in rows:
                    started = perf_counter()
                    hits = await store.search(case.text, vector, case.area, case.from_, case.until,
                        strategy=mode, include_images=settings.image_search_enabled)
                    elapsed = perf_counter() - started + (embedding_time if mode != "lexical" else 0)
                    rows[mode].append(([hit["itemId"] for hit in hits], {str(item) for item in case.relevantItemIds}, elapsed))
    finally:
        await model.close()
        await store.close()
    return {"model": settings.model_id, "revision": settings.revision, "dimensions": settings.dimensions,
            "searchProfile": settings.search_profile, "semanticWeight": settings.semantic_weight,
            "scope": "retrieval_before_dotnet_eligibility",
            "results": {mode: metrics(values) for mode, values in rows.items()}}


def query_images(case, base_dir):
    """Read bounded corpus fixtures without accepting URLs or paths outside the corpus."""
    directory = base_dir.resolve()
    result = []
    for name in case.images:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not 0 < path.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError("Invalid evaluation image fixture.")
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[path.suffix.lower()]
        result.append((path.read_bytes(), mime))
    return result


def search_command(case, settings, base_dir):
    images = query_images(case, base_dir)
    seconds = 955 if case.mode == "combined" or len(images) > 1 else 315 if images else 45
    metadata = {"schemaVersion": 1, "modelId": settings.model_id, "modelRevision": settings.revision,
        "searchProfileVersion": 1, "mode": case.mode, "area": case.area,
        "from": case.from_.isoformat() if case.from_ else None,
        "until": case.until.isoformat() if case.until else None, "limit": 10,
        "candidateLimit": MAX_SEARCH_CANDIDATES,
        "deadlineAt": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}
    if case.mode == "text":
        metadata.update(processingProfile="text-v1", searchProfileId=settings.search_profile)
        query = Query(text=case.text, area=case.area, **{"from": case.from_}, until=case.until)
        body, mime, kind = query.model_dump_json(by_alias=True).encode(), "application/json", "search.hybrid"
        SearchMetadata.model_validate(metadata)
    elif case.mode == "image" and len(images) == 1:
        metadata.update(processingProfile="image-v1", searchProfileId=settings.image_search_profile)
        (body, mime), kind = images[0], "search.hybrid.image"
        SearchMetadata.model_validate(metadata)
    else:
        metadata.update(processingProfile="multimodal-v1",
            searchProfileId="multimodal-fusion-v1" if case.text else "image-fusion-v1",
            text=case.text, images=[{"length": len(body), "contentType": mime} for body, mime in images])
        body, mime, kind = b"".join(body for body, _ in images), "application/octet-stream", "search.hybrid.images"
        BatchSearchMetadata.model_validate(metadata)
    return kind, metadata, body, mime, seconds


async def evaluate_production(cases, settings, base_dir, broker_url):
    validate_cases(cases)
    endpoint = urlsplit(broker_url)
    if endpoint.scheme not in {"amqp", "amqps"} or endpoint.scheme == "amqp" and not loopback(endpoint.hostname):
        raise ValueError("Evaluation requires AMQPS, or AMQP on loopback.")
    connection = await aio_pika.connect(broker_url, timeout=5,
        ssl_context=ssl.create_default_context() if endpoint.scheme == "amqps" else None)
    rows, splits = {}, {}
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        await channel.set_qos(prefetch_count=1)
        reply = await channel.declare_queue("", exclusive=True, auto_delete=True,
            arguments={"x-message-ttl": 60000, "x-max-length": 4, "x-max-length-bytes": 2 * 1024 * 1024})
        pending = {}

        async def receive(message):
            async with message.process(requeue=False):
                waiter = pending.get(message.correlation_id)
                if waiter is None or waiter.done():
                    return
                try:
                    header = message.headers.get("metadata")
                    if not isinstance(header, (str, bytes)) or len(header) > 16384 or len(message.body) > 1024 * 1024:
                        raise ValueError("Invalid evaluation reply size.")
                    waiter.set_result((json.loads(header), json.loads(message.body)))
                except (TypeError, ValueError):
                    waiter.set_exception(ValueError("Invalid evaluation reply."))

        await reply.consume(receive)
        for case in cases:
            kind, metadata, body, mime, seconds = search_command(case, settings, base_dir)
            correlation = str(uuid4())
            waiter = asyncio.get_running_loop().create_future()
            pending[correlation] = waiter
            started = perf_counter()
            try:
                await channel.default_exchange.publish(aio_pika.Message(body=body,
                    headers={"metadata": json.dumps(metadata)}, type=kind, correlation_id=correlation,
                    reply_to=reply.name, content_type=mime, expiration=timedelta(seconds=seconds),
                    delivery_mode=aio_pika.DeliveryMode.NOT_PERSISTENT),
                    routing_key=settings.query_queue if kind == "search.hybrid" else settings.image_queue,
                    mandatory=True, timeout=5)
                header, result = await asyncio.wait_for(waiter, timeout=seconds + 5)
                if (not isinstance(header, dict) or header.get("succeeded") is not True or header.get("kind") != kind
                        or any(header.get(field) != metadata[field] for field in (
                            "schemaVersion", "modelId", "modelRevision", "searchProfileId", "searchProfileVersion", "mode"))
                        or not isinstance(result, dict) or result.get("rankingMethod") not in {"reranker", "similarity_fallback"}):
                    raise ValueError("Search did not return a valid production evaluation response.")
                candidates = result.get("candidates")
                if not isinstance(candidates, list) or len(candidates) > MAX_SEARCH_CANDIDATES:
                    raise ValueError("Invalid production candidate count.")
                hits = [str(UUID(candidate["itemId"])) for candidate in candidates]
                if len(set(hits)) != len(hits):
                    raise ValueError("Duplicate production candidates.")
                row = (hits, {str(item) for item in case.relevantItemIds}, perf_counter() - started, result["rankingMethod"])
                rows.setdefault(case.mode, []).append(row)
                splits.setdefault(case.split, {}).setdefault(case.mode, []).append(row)
            finally:
                pending.pop(correlation, None)
                if not waiter.done():
                    waiter.cancel()
                body = b""
    return {"model": settings.model_id, "revision": settings.revision, "dimensions": settings.dimensions,
        "scope": "python_quality_before_dotnet_eligibility_and_time_bonus",
        "candidateLimit": MAX_SEARCH_CANDIDATES,
        "results": {mode: metrics(values, candidate_pool=False) for mode, values in rows.items()},
        "splits": {split: {mode: metrics(values, candidate_pool=False) for mode, values in modes.items()}
                   for split, modes in splits.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path, help="JSON labelled cases; image fixtures are relative to this file.")
    parser.add_argument("--production", action="store_true",
        help="Evaluate the actual Python worker via AMQP; requires AI_EVALUATION_RABBITMQ_URL with temporary reply-queue permissions.")
    args = parser.parse_args()
    try:
        if args.cases.suffix.lower() != ".json" or args.cases.name.startswith(".env"):
            raise ValueError()
        if args.cases.stat().st_size > 10 * 1024 * 1024:
            parser.error("Evaluation file exceeds 10 MiB.")
        cases = TypeAdapter(list[Case]).validate_json(args.cases.read_bytes())
        validate_cases(cases)
    except (OSError, ValueError):
        parser.error("Invalid evaluation cases; use 1–10000 validated labelled queries.")
    settings = Settings.from_env()
    if not settings.revision or not args.production and not settings.search_dsn:
        parser.error("Configure AI_SEARCH_DSN and AI_EMBEDDING_REVISION.")
    broker_url = os.environ.get("AI_EVALUATION_RABBITMQ_URL", "")
    if args.production and not broker_url:
        parser.error("Configure AI_EVALUATION_RABBITMQ_URL with temporary reply-queue permissions.")
    if not args.production and any(case.mode != "text" for case in cases):
        parser.error("Image and combined cases require --production.")
    try:
        result = asyncio.run(evaluate_production(cases, settings, args.cases.parent, broker_url)
                            if args.production else evaluate(cases, settings))
    except Exception:
        raise SystemExit("Evaluation failed; check the model, search database and case filters.") from None
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
