import asyncio
from contextlib import asynccontextmanager
import json
from uuid import uuid4

import pytest
from pamqp.encode import field_table

from findie_ai.config import Settings
from findie_ai.evaluate import Case, evaluate_production, metrics, query_images, search_command, validate_cases
from findie_ai.ranking import MAX_SEARCH_CANDIDATES


def test_metrics_separate_queries_without_a_match_and_handle_empty_results():
    result = metrics([(["b", "a"], {"a", "c"}, 0.01), ([], {"d"}, 0.03), (["a"], set(), 0.02)])
    assert result["hitAt10"] == 0.5
    assert result[f"candidateRecallAt{MAX_SEARCH_CANDIDATES}"] == 0.25
    assert result["mrrAt10"] == 0.25
    assert result["noMatchWithSuggestionsRate"] == 1
    assert result["meanMilliseconds"] == 20
    assert result["precisionReturned"] == pytest.approx(1 / 3)
    assert result["recallReturned"] == 0.25
    assert result["positiveQueriesWithNoResultsRate"] == 0.5
    assert result["meanReturnedCount"] == 1
    assert result["p50Milliseconds"] == 20
    assert result["p95Milliseconds"] == 30
    assert metrics([])["hitAt10"] is None
    with pytest.raises(ValueError):
        Case(text="ví", relevantItemIds=["not-a-uuid"])


def test_returned_precision_counts_unique_items_and_empty_metrics_remain_defined():
    result = metrics([(["a", "a"], {"a"}, 0.01, "reranker"),
                      ([], {"b"}, 0.02, "similarity_fallback")], candidate_pool=False)
    assert result["precisionReturned"] == 1
    assert result["recallReturned"] == 0.5
    assert result["fallbackRate"] == 0.5
    assert result[f"candidateRecallAt{MAX_SEARCH_CANDIDATES}"] is None
    empty = metrics([([], set(), 0.01)])
    assert empty["precisionReturned"] is None
    assert empty["noMatchWithSuggestionsRate"] == 0
    assert empty["meanReturnedCount"] == 0


@pytest.mark.parametrize("values", [
    {"mode": "text", "text": " "},
    {"mode": "text", "text": "ví", "images": ["safe.png"]},
    {"mode": "image", "images": []},
    {"mode": "image", "images": ["safe.png"], "text": "ví"},
    {"mode": "combined", "images": ["safe.png"]},
    {"mode": "combined", "text": "ví"},
    {"mode": "image", "images": ["../outside.png"]},
    {"mode": "image", "images": ["/outside.png"]},
    {"mode": "image", "images": [".env"]},
    {"mode": "image", "images": ["https://example.com/safe.png"]},
    {"mode": "text", "text": "ví", "from": "2026-11-02", "until": "2026-11-01"},
])
def test_evaluation_cases_validate_modalities_fixture_paths_and_filters(values):
    with pytest.raises(ValueError):
        Case(**values, relevantItemIds=[])


def test_duplicate_relevance_labels_are_rejected():
    item = uuid4()
    with pytest.raises(ValueError):
        Case(text="ví", relevantItemIds=[item, item])


def test_calibration_and_test_cannot_share_relevant_items_or_case_ids():
    item = uuid4()
    with pytest.raises(ValueError):
        validate_cases([Case(text="ví đen", split="calibration", relevantItemIds=[item]),
                        Case(text="vi den", split="test", relevantItemIds=[item])])
    with pytest.raises(ValueError):
        validate_cases([Case(caseId="duplicate", text="ví", relevantItemIds=[])] * 2)
    validate_cases([Case(text="ví", split="calibration", relevantItemIds=[item]),
                    Case(text="mũ", split="test", relevantItemIds=[uuid4()])])


def test_fixture_reader_rejects_symlinks_outside_the_corpus_and_empty_images(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"safe synthetic fixture")
    (corpus / "linked.png").symlink_to(outside)
    with pytest.raises(ValueError):
        query_images(Case(mode="image", images=["linked.png"], relevantItemIds=[]), corpus)
    (corpus / "empty.png").write_bytes(b"")
    with pytest.raises(ValueError):
        query_images(Case(mode="image", images=["empty.png"], relevantItemIds=[]), corpus)


def test_production_commands_cover_text_image_and_combined_without_a_ten_candidate_shortlist(tmp_path):
    settings = Settings(service_token="test", revision="a" * 64, image_search_enabled=True)
    (tmp_path / "safe.png").write_bytes(b"synthetic image bytes validated by the worker")
    cases = [Case(text="  ví đen  ", relevantItemIds=[]),
             Case(mode="image", images=["safe.png"], relevantItemIds=[]),
             Case(mode="combined", images=["safe.png", "safe.png"], text="ví đen", relevantItemIds=[])]
    commands = [search_command(case, settings, tmp_path) for case in cases]
    assert [command[0] for command in commands] == ["search.hybrid", "search.hybrid.image", "search.hybrid.images"]
    assert [command[4] for command in commands] == [45, 315, 955]
    assert all(command[1]["candidateLimit"] == MAX_SEARCH_CANDIDATES for command in commands)
    assert json.loads(commands[0][2])["text"] == "ví đen"
    assert commands[2][1]["images"] == [{"length": 45, "contentType": "image/png"}] * 2
    assert commands[2][2] == (tmp_path / "safe.png").read_bytes() * 2


def test_production_evaluation_reports_worker_results_and_fallbacks_by_mode_and_split(monkeypatch, tmp_path):
    import findie_ai.evaluate as module

    item = str(uuid4())
    requests = []

    class Message:
        @asynccontextmanager
        async def process(self, **_kwargs):
            yield

    class Channel:
        default_exchange = None
        name = "amq.gen-evaluation"

        def __init__(self):
            self.default_exchange = self

        async def set_qos(self, **_kwargs):
            pass

        async def declare_queue(self, *_args, **kwargs):
            assert kwargs["exclusive"] and kwargs["auto_delete"]
            return self

        async def consume(self, callback):
            self.receive = callback

        async def publish(self, command, **kwargs):
            assert field_table(command.headers), "evaluation headers must serialize on the AMQP wire"
            requests.append((command, kwargs))
            metadata = json.loads(command.headers["metadata"])
            image = metadata["mode"] == "image"
            response = Message()
            response.correlation_id = command.correlation_id
            response.headers = {"metadata": json.dumps(metadata | {"succeeded": True, "kind": command.type})}
            response.body = json.dumps({"candidates": [] if image else [{"itemId": item}],
                "rankingMethod": "similarity_fallback" if image else "reranker"}).encode()
            await self.receive(response)

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def channel(self, **_kwargs):
            return Channel()

    async def connect(*_args, **_kwargs):
        return Connection()

    monkeypatch.setattr(module.aio_pika, "connect", connect)
    (tmp_path / "safe.png").write_bytes(b"synthetic fixture")
    cases = [Case(text="ví", split="calibration", relevantItemIds=[item]),
             Case(mode="image", images=["safe.png"], relevantItemIds=[])]
    result = asyncio.run(evaluate_production(cases,
        Settings(service_token="test", revision="a" * 64), tmp_path, "amqp://localhost"))
    assert result["scope"] == "python_quality_before_dotnet_eligibility_and_time_bonus"
    assert result["candidateLimit"] == MAX_SEARCH_CANDIDATES
    assert result["results"]["text"]["precisionReturned"] == 1
    assert result["results"]["image"]["fallbackRate"] == 1
    assert result["results"]["image"]["noMatchWithSuggestionsRate"] == 0
    assert set(result["splits"]) == {"calibration", "test"}
    assert all(request[0].headers["metadata"] for request in requests)
    assert [request[1]["routing_key"] for request in requests] == ["findie.ai.query", "findie.ai.image"]


def test_production_evaluation_rejects_plain_amqp_outside_loopback(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(evaluate_production([Case(text="ví", relevantItemIds=[])],
            Settings(service_token="test"), tmp_path, "amqp://broker.example"))
