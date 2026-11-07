"""Read-only retrieval evaluation over an already indexed, labelled test corpus."""

import argparse
import asyncio
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import UUID

from pydantic import Field, TypeAdapter

from .config import Settings
from .contracts import Query
from .ollama import Ollama
from .store import Store


class Case(Query):
    relevantItemIds: list[UUID] = Field(max_length=1000)


def metrics(rows):
    positive = [(hits, relevant) for hits, relevant, _ in rows if relevant]
    negative = [(hits, relevant) for hits, relevant, _ in rows if not relevant]
    return {
        "queries": len(rows),
        "positiveQueries": len(positive),
        "hitAt10": mean(bool(set(hits[:10]) & relevant) for hits, relevant in positive) if positive else None,
        "recallAt50": mean(len(set(hits[:50]) & relevant) / len(relevant) for hits, relevant in positive) if positive else None,
        "mrrAt10": mean(next((1 / rank for rank, item in enumerate(hits[:10], 1) if item in relevant), 0)
                        for hits, relevant in positive) if positive else None,
        "noMatchQueries": len(negative),
        "noMatchWithSuggestionsRate": mean(bool(hits) for hits, _ in negative) if negative else None,
        "meanMilliseconds": mean(elapsed for _, _, elapsed in rows) * 1000 if rows else None,
    }


async def evaluate(cases, settings):
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
                    hits = await store.search(case.text, vector, case.area, case.from_, case.until, strategy=mode)
                    elapsed = perf_counter() - started + (embedding_time if mode != "lexical" else 0)
                    rows[mode].append(([hit["itemId"] for hit in hits], {str(item) for item in case.relevantItemIds}, elapsed))
    finally:
        await model.close()
    return {"model": settings.model_id, "revision": settings.revision, "dimensions": settings.dimensions,
            "searchProfile": settings.search_profile, "semanticWeight": settings.semantic_weight,
            "scope": "retrieval_before_dotnet_eligibility",
            "results": {mode: metrics(values) for mode, values in rows.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path, help="JSON array of text/area/from/until/relevantItemIds.")
    args = parser.parse_args()
    if args.cases.stat().st_size > 10 * 1024 * 1024:
        parser.error("Evaluation file exceeds 10 MiB.")
    try:
        cases = TypeAdapter(list[Case]).validate_json(args.cases.read_bytes())
        if not cases or len(cases) > 10000:
            raise ValueError()
    except ValueError:
        parser.error("Invalid evaluation cases; use 1–10000 validated labelled queries.")
    settings = Settings.from_env()
    if not settings.search_dsn or not settings.revision:
        parser.error("Configure AI_SEARCH_DSN and AI_EMBEDDING_REVISION.")
    try:
        result = asyncio.run(evaluate(cases, settings))
    except Exception:
        raise SystemExit("Evaluation failed; check the model, search database and case filters.") from None
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
