import pytest

from findie_ai.evaluate import Case, metrics


def test_metrics_separate_queries_without_a_match_and_handle_empty_results():
    result = metrics([(["b", "a"], {"a", "c"}, 0.01), ([], {"d"}, 0.03), (["a"], set(), 0.02)])
    assert result["hitAt10"] == 0.5
    assert result["recallAt50"] == 0.25
    assert result["mrrAt10"] == 0.25
    assert result["noMatchWithSuggestionsRate"] == 1
    assert result["meanMilliseconds"] == 20
    assert metrics([])["hitAt10"] is None
    with pytest.raises(ValueError):
        Case(text="ví", relevantItemIds=["not-a-uuid"])
