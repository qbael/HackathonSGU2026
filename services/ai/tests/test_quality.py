import pytest

from findie_ai.quality import select_candidates


def hits(*names):
    return [{"itemId": name, "score": 1 / (61 + rank), "sources": [{"sourceId": name}]}
            for rank, name in enumerate(names)]


def test_relative_floor_keeps_the_strong_cluster_without_padding_or_mutating_rrf():
    candidates = hits("a", "b", "c", "d")
    scores = {name: {"image": value} for name, value in zip("abcd", (0.92, 0.89, 0.86, 0.52))}
    result = select_candidates(candidates, scores, min_image=0.5)
    assert [hit["itemId"] for hit in result] == ["a", "b", "c"]
    assert result[0]["score"] == candidates[0]["score"]
    assert result[0]["sources"] == candidates[0]["sources"]
    assert "relevanceScore" not in candidates[0]


def test_one_strong_query_modality_is_enough_and_groups_use_qualified_evidence():
    result = select_candidates(hits("image", "text", "both", "weak"), {
        "image": {"image": 0.9, "text": 0.2},
        "text": {"image": 0.1, "text": 0.95},
        "both": {"image": 0.7, "text": 0.7},
        "weak": {"image": 0.59, "text": 0.59},
    })
    assert [hit["itemId"] for hit in result] == ["both", "image", "text"]
    assert (result[1]["imageRelevant"], result[1]["textRelevant"]) == (True, False)
    assert result[2]["relevanceScore"] == 0.95


def test_local_and_remote_groups_have_separate_relative_baselines():
    result = select_candidates(hits("local", "remote", "weak-remote"), {
        "local": {"text": 0.6}, "remote": {"text": 0.99}, "weak-remote": {"text": 0.6},
    }, preferred_ids={"local"})
    assert [hit["itemId"] for hit in result] == ["remote", "local"]


def test_threshold_and_relative_boundary_ties_are_inclusive():
    result = select_candidates(hits("b", "a", "c"), {
        "a": {"image": 0.8}, "b": {"image": 0.6}, "c": {"image": 0.6},
    })
    assert [hit["itemId"] for hit in result] == ["a", "b", "c"]
    assert select_candidates(hits("a"), {"a": {"text": 0.6}})[0]["relevanceScore"] == 0.6


def test_every_candidate_in_twenty_item_pool_is_evaluated_before_any_display_limit():
    candidates = hits(*(str(index) for index in range(20)))
    scores = {str(index): {"text": 0.1} for index in range(20)}
    scores["19"] = {"text": 0.9}
    assert [hit["itemId"] for hit in select_candidates(candidates, scores)] == ["19"]
    assert len(select_candidates(candidates, {str(index): {"text": 0.8} for index in range(20)})) == 20


def test_equal_relevance_retains_the_retrieval_order_and_lexical_tiebreak():
    candidates = hits("z-exact-model", "a-general")
    result = select_candidates(candidates, {hit["itemId"]: {"text": 0.9} for hit in candidates})
    assert [hit["itemId"] for hit in result] == ["z-exact-model", "a-general"]


def test_empty_missing_negative_and_all_weak_scores_return_no_matches():
    assert select_candidates([], {}) == []
    assert select_candidates(hits("a", "b", "c"), {
        "a": {"text": -1}, "b": {"image": 0.1, "text": None},
    }) == []
    with pytest.raises(ValueError):
        select_candidates(hits("a", "a"), {"a": {"image": 0.8}})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.01, 1.01, True, "0.8"])
def test_invalid_scores_are_rejected(value):
    with pytest.raises(ValueError):
        select_candidates(hits("a"), {"a": {"text": value}})


@pytest.mark.parametrize("field", ["min_image", "min_text", "relative_ratio"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01, 1.01, True])
def test_invalid_thresholds_are_rejected(field, value):
    with pytest.raises(ValueError):
        select_candidates([], {}, **{field: value})
