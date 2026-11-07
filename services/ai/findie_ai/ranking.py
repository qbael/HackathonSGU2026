"""Deterministic Vietnamese lexical and precise-location signals."""

import re
import unicodedata


MAX_SEARCH_CANDIDATES = 30


def normalize_text(text: str) -> str:
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
        if not unicodedata.combining(char)
    )
    text = re.sub(r"\b([a-z]{1,3})[.\-]+(\d{1,4})\b", r"\1\2", text)
    text = re.sub(r"\b([a-z])\s+(\d{1,4})\b", r"\1\2", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def location_tokens(text: str) -> list[str]:
    text = normalize_text(text)
    rooms = re.findall(r"\b[a-z]{1,3}\d{1,4}\b", text)
    numbered_rooms = re.findall(r"\bphong(?: hoc)? (\d{1,4})\b", text)
    halls = re.findall(r"\bhoi truong ([a-z0-9]+)\b", text)
    return sorted({*("room:" + room for room in rooms + numbered_rooms),
                   *("hall:" + hall for hall in halls)})


def rank_candidates(semantic, lexical, locations, query_locations, limit=MAX_SEARCH_CANDIDATES, *, semantic_weight=0.6):
    """Fuse exact cosine and lexical ranks with a bounded location tie-break."""
    candidates, scores = {}, {}
    # shortcut: location weight is a regression baseline; calibrate it on labelled Findie queries.
    # Keep the primary weight total at two so the location signal retains its scale.
    for channel, weight in ((semantic, 2 * semantic_weight), (lexical, 2 * (1 - semantic_weight)), (locations, 0.03)):
        if weight == 0:
            continue
        for rank, candidate in enumerate(channel, 1):
            item_id = str(candidate["item_id"])
            candidates[item_id] = candidate
            scores[item_id] = scores.get(item_id, 0.0) + weight / (60 + rank)
    query_locations = set(query_locations)
    ordered = sorted(candidates, key=lambda item_id: (
        -scores[item_id],
        -len(query_locations.intersection(candidates[item_id]["location_tokens"])), item_id,
    ))
    return [{
        "itemId": item_id,
        "documentVersion": candidates[item_id]["document_version"],
        "sourceId": str(candidates[item_id]["source_id"]),
        "sourceKind": "image" if candidates[item_id].get("processing_profile") == "image-v1" else "text",
        "sourceVersion": candidates[item_id]["source_version"],
        "sourceSha256": candidates[item_id]["source_sha256"],
    } for item_id in ordered[:min(limit, MAX_SEARCH_CANDIDATES)]]


def fuse_rankings(rankings, limit=MAX_SEARCH_CANDIDATES, *, weights=None, text_index=None, preferred_ids=()):
    """Order combined, image-only, then text-only hits, retaining their evidence."""
    candidates = {}
    for idx, ranking in enumerate(rankings):
        w = weights[idx] if weights else 1.0
        seen = set()
        for rank, candidate in enumerate(ranking, 1):
            item_id = candidate["itemId"]
            if item_id in seen:
                continue
            seen.add(item_id)
            fused = candidates.setdefault(item_id, {"itemId": item_id, "score": 0.0,
                "imageScore": 0.0, "textScore": 0.0, "sources": []})
            contribution = w / (60 + rank)
            fused["imageScore" if idx != text_index else "textScore"] += contribution
            fused["score"] = fused["imageScore"] + fused["textScore"]
            source = {key: candidate[key] for key in (
                "documentVersion", "sourceId", "sourceKind", "sourceVersion", "sourceSha256")}
            if source not in fused["sources"]:
                fused["sources"].append(source)
    ranked = sorted(candidates.values(), key=lambda candidate: (
        0 if candidate["imageScore"] and candidate["textScore"] else 1 if candidate["imageScore"] else 2,
        -candidate["score"], -candidate["imageScore"], -candidate["textScore"], candidate["itemId"],
    ))
    # Select with area priority, then preserve the group/score wire order checked by the API.
    selected = sorted(ranked, key=lambda candidate: candidate["itemId"] not in preferred_ids)
    selected_ids = {candidate["itemId"] for candidate in selected[:min(limit, MAX_SEARCH_CANDIDATES)]}
    return [candidate for candidate in ranked if candidate["itemId"] in selected_ids]
