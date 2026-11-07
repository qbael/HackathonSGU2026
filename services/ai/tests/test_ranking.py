import pytest

from findie_ai.ranking import fuse_rankings, location_tokens, normalize_text, rank_candidates


def candidate(item_id, description):
    return {
        "item_id": item_id, "document_version": 2, "source_id": item_id,
        "source_version": 1, "source_sha256": "a" * 64,
        "location_tokens": location_tokens(description),
    }


def test_vietnamese_accents_and_room_punctuation():
    assert normalize_text("Đại học Sài Gòn; phòng E.205") == "dai hoc sai gon phong e205"
    assert location_tokens("phòng học E.205") == location_tokens("phong E205") == location_tokens("E 205")
    assert location_tokens("Nhặt tại sảnh hội trường A") == location_tokens("sanh hoi truong a") == ["hall:a"]
    assert location_tokens("phòng 205") == ["room:205"]
    assert normalize_text("Ví đen 2 ngăn") == "vi den 2 ngan"
    assert location_tokens("Ví đen 2 ngăn") == []


def test_exact_room_wins_over_similar_embedding_without_losing_source_identity():
    wrong = candidate("wrong", "Ví đen nhặt tại phòng E.206")
    correct = candidate("correct", "Ví đen nhặt tại phòng E.205")
    result = rank_candidates([wrong, correct], [correct, wrong], [correct], location_tokens("vi den E205"))
    assert [row["itemId"] for row in result] == ["correct", "wrong"]
    assert result[0] == {
        "itemId": "correct", "documentVersion": 2, "sourceId": "correct",
        "sourceKind": "text",
        "sourceVersion": 1, "sourceSha256": "a" * 64,
    }


def test_hall_accents_and_candidate_deduplication():
    wrong = candidate("wrong", "Sảnh hội trường B")
    correct = candidate("correct", "Sảnh hội trường A")
    result = rank_candidates([wrong, correct], [correct, wrong], [correct], location_tokens("sanh hoi truong A"), limit=1)
    assert [row["itemId"] for row in result] == ["correct"]


def test_matching_room_does_not_override_agreement_on_the_object():
    wallet = candidate("wallet", "Ví màu đen ở phòng E.206")
    laptop = candidate("laptop", "Máy tính xách tay ở phòng E.205")
    result = rank_candidates([wallet, laptop], [wallet, laptop], [laptop], location_tokens("ví màu đen E205"))
    assert result[0]["itemId"] == "wallet"


def test_rrf_rewards_agreement_and_favors_semantic_on_disagreement():
    keyword_only, semantic_only, shared = [candidate(name, "") for name in ("a", "b", "c")]
    result = rank_candidates([semantic_only, shared], [keyword_only, shared], [], [])
    assert [row["itemId"] for row in result] == ["c", "b", "a"]


@pytest.mark.parametrize(("semantic_weight", "expected"), [(0.3, ["keyword", "semantic"]),
                                                         (0.7, ["semantic", "keyword"])])
def test_rrf_configured_weight_reverses_preference_when_the_channels_disagree(semantic_weight, expected):
    semantic, keyword = [candidate(name, "") for name in ("semantic", "keyword")]
    result = rank_candidates([semantic, keyword], [keyword, semantic], [], [], semantic_weight=semantic_weight)
    assert [row["itemId"] for row in result] == expected


@pytest.mark.parametrize(("semantic_weight", "expected"), [(0, ["keyword", "shared"]),
                                                         (1, ["semantic", "shared"])])
def test_zero_weight_channel_does_not_contribute_candidates_or_replace_source(semantic_weight, expected):
    semantic, keyword, shared = [candidate(name, "") for name in ("semantic", "keyword", "shared")]
    semantic_shared = shared | {"source_id": "semantic-source"}
    keyword_shared = shared | {"source_id": "keyword-source"}
    result = rank_candidates([semantic, semantic_shared], [keyword, keyword_shared], [], [],
                             semantic_weight=semantic_weight)
    assert [row["itemId"] for row in result] == expected
    assert result[1]["sourceId"] == ("semantic-source" if semantic_weight == 1 else "keyword-source")


def test_multimodal_rrf_deduplicates_each_ranking_and_keeps_all_contributing_sources():
    first, second = rank_candidates([candidate(name, "") for name in ("first", "second")], [], [], [])
    image = first | {"sourceId": "image", "sourceKind": "image"}
    older = first | {"documentVersion": 1}
    hits = fuse_rankings([[image, image, second], [second, first], [older]])
    assert [hit["itemId"] for hit in hits] == ["first", "second"]
    assert hits[0]["score"] == pytest.approx(2 / 61 + 1 / 62)
    assert hits[1]["score"] == pytest.approx(1 / 63 + 1 / 61)
    assert hits[0]["sources"] == [{key: source[key] for key in (
        "documentVersion", "sourceId", "sourceKind", "sourceVersion", "sourceSha256")}
        for source in (image, first, older)]
    assert len(fuse_rankings([[image], [image]], limit=1)[0]["sources"]) == 1
    assert fuse_rankings([[], []]) == []
    assert len(fuse_rankings([[first, second]], limit=1)) == 1


def test_multimodal_fusion_caps_all_query_branches_at_thirty_candidates():
    first = rank_candidates([candidate(str(index), "") for index in range(30)], [], [], [])
    second = rank_candidates([candidate(str(index), "") for index in range(30, 60)], [], [], [])
    hits = fuse_rankings([first, second])
    assert len(hits) == 30
    assert len({hit["itemId"] for hit in hits}) == 30
    assert len(fuse_rankings([first, second], limit=100)) == 30



def test_combined_then_image_then_text_groups_precede_score_and_limit():
    rows = {name: rank_candidates([candidate(name, "")], [], [], [])[0]
            for name in ("combined", "image", "text")}
    # Text-query evidence can also come from an image source.
    rows["text"]["sourceKind"] = "image"
    hits = fuse_rankings([
        [rows["image"], rows["image"], rows["combined"]],
        [rows["text"], rows["combined"]],
    ], weights=[0.1, 1.0], text_index=1)
    assert [hit["itemId"] for hit in hits] == ["combined", "image", "text"]
    assert hits[1]["score"] < hits[2]["score"]
    assert hits[1]["score"] == pytest.approx(0.1 / 61)
    assert hits[2]["imageScore"] == 0
    assert hits[2]["textScore"] == pytest.approx(1 / 61)
    assert all(hit["score"] == hit["imageScore"] + hit["textScore"] for hit in hits)
    assert len({hit["itemId"] for hit in hits}) == len(hits)
    assert fuse_rankings([[rows["image"], rows["combined"]], [rows["text"], rows["combined"]]],
                         1, text_index=1)[0]["itemId"] == "combined"


def test_fusion_sorts_each_group_by_its_score():
    rows = {name: rank_candidates([candidate(name, "")], [], [], [])[0]
            for name in ("shared-a", "shared-b", "image-a", "image-b", "text-a", "text-b")}
    hits = fuse_rankings([
        [rows[name] for name in ("image-a", "shared-a", "image-b", "shared-b")],
        [rows[name] for name in ("text-a", "shared-a", "text-b", "shared-b")],
    ], weights=[1.0, 0.5], text_index=1)
    assert [hit["itemId"] for hit in hits] == [
        "shared-a", "shared-b", "image-a", "image-b", "text-a", "text-b"]



def test_both_query_branches_with_image_sources_still_form_combined_group():
    hit = rank_candidates([candidate("bottle", "")], [], [], [])[0] | {"sourceKind": "image"}
    image_hit = hit | {"sourceId": "photo-one"}
    text_hit = hit | {"sourceId": "photo-two"}
    result = fuse_rankings([[image_hit], [text_hit]], weights=[1.0, 0.5], text_index=1)
    assert len(result) == 1
    assert result[0]["imageScore"] == pytest.approx(1 / 61)
    assert result[0]["textScore"] == pytest.approx(0.5 / 61)
    assert {source["sourceId"] for source in result[0]["sources"]} == {"photo-one", "photo-two"}


@pytest.mark.parametrize("local_kind", ["image", "text"])
def test_area_priority_selects_local_hits_before_global_cap_without_changing_wire_order(local_kind):
    outside = rank_candidates([candidate(str(index), "") for index in range(30)], [], [], [])
    local = rank_candidates([candidate("local", "")], [], [], [])[0]
    image, text = ([local], []) if local_kind == "image" else ([], [local])
    hits = fuse_rankings([outside + image, outside + text], 30, weights=[1.0, 0.5],
                         text_index=1, preferred_ids={"local"})
    assert len(hits) == 30 and hits[-1]["itemId"] == "local"
    assert all(hit["imageScore"] and hit["textScore"] for hit in hits[:-1])
    assert hits[-1]["imageScore" if local_kind == "image" else "textScore"] > 0
    assert {ref["sourceId"] for ref in hits[-1]["sources"]} == {"local"}
