"""Reject weak matches without treating reciprocal ranks as relevance scores."""

import math


def select_candidates(candidates, scores, *, min_image=0.6, min_text=0.6,
                      relative_ratio=0.75, preferred_ids=()):
    """Apply OR modality gates and a relative floor within each area/evidence group."""
    for value in (min_image, min_text, relative_ratio):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Quality thresholds must be finite values between zero and one.")
    for modalities in scores.values():
        for value in modalities.values():
            if value is not None and (type(value) not in (int, float)
                    or not math.isfinite(value) or not -1 <= value <= 1):
                raise ValueError("Similarity scores must be finite values between minus one and one.")

    preferred_ids = set(preferred_ids)
    qualified, best = [], {}
    seen = set()
    for position, candidate in enumerate(candidates):
        item_id = candidate["itemId"]
        if item_id in seen:
            raise ValueError("Quality selection requires unique candidate items.")
        seen.add(item_id)
        values = scores.get(item_id, {})
        image, text = values.get("image"), values.get("text")
        image_relevant = image is not None and image >= min_image
        text_relevant = text is not None and text >= min_text
        if not image_relevant and not text_relevant:
            continue
        relevance = max(value for value, relevant in ((image, image_relevant), (text, text_relevant)) if relevant)
        group = 0 if image_relevant and text_relevant else 1 if image_relevant else 2
        bucket = (item_id in preferred_ids, group)
        best[bucket] = max(best.get(bucket, 0), relevance)
        hit = candidate | {"relevanceScore": relevance, "imageRelevant": image_relevant,
                           "textRelevant": text_relevant}
        qualified.append((hit, bucket, image, text, position))

    retained = [value for value in qualified
                if value[0]["relevanceScore"] + 1e-12 >= relative_ratio * best[value[1]]]
    # Area affects the rejection baseline; the API applies area priority to this wire order.
    retained.sort(key=lambda value: (value[1][1], -value[0]["relevanceScore"],
                  -(value[2] if value[2] is not None else -1),
                  -(value[3] if value[3] is not None else -1), value[4]))
    return [hit for hit, _, _, _, _ in retained]
