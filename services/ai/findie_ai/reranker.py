"""Bounded model scoring over in-memory material; no generated ratings or image storage."""

import base64
import math

from .ollama import ModelUnavailable


async def rerank(ollama, settings, materials, text, query_images, deadline):
    await ollama._verify_revision(settings.reranker_model, settings.reranker_revision)
    payload = {"model": settings.reranker_model, "text": text,
        "images": [base64.b64encode(value).decode("ascii") for value in query_images],
        "deadlineAt": deadline.isoformat(), "candidates": [{"itemId": value.item_id, "text": value.text,
            "image": base64.b64encode(value.image).decode("ascii") if value.image else None}
            for value in materials.values()]}
    data = await ollama._json("POST", "api/rerank", payload)
    await ollama._verify_revision(settings.reranker_model, settings.reranker_revision)
    expected = set(materials)
    try:
        if data["model"] != settings.reranker_model or len(data["scores"]) != len(expected):
            raise ValueError()
        scores = {}
        for row in data["scores"]:
            if row["itemId"] not in expected or row["itemId"] in scores:
                raise ValueError()
            values = {"image": row["imageScore"], "text": row["textScore"]}
            for kind, present in (("image", bool(query_images)), ("text", bool(text))):
                value = values[kind]
                if (present and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1)
                        or not present and value is not None):
                    raise ValueError()
            scores[row["itemId"]] = values
        return scores
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ModelUnavailable("invalid_rerank_scores") from None
