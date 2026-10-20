"Deterministic matching with explanations derived from observed fields only."

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any

from .models import Json, parse_time


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def rank_product(product: Json, tracker: Json, *, now: str | datetime | None = None) -> Json:
    reasons: list[str] = []
    if not tracker.get("enabled", True):
        return {"matched": False, "score": 0, "reasons": ["Tracker paused"]}
    title = normalized(str(product.get("title", "")))
    excluded = [p for p in tracker.get("exclusions", []) if normalized(p) in title]
    if excluded:
        return {
            "matched": False,
            "score": 0,
            "reasons": [f"Excluded phrase: {p}" for p in excluded],
        }
    phrases = tracker.get("phrases", [])
    matched = [p for p in phrases if normalized(p) in title]
    if phrases and (
        (tracker.get("phrase_mode") == "all" and len(matched) != len(phrases)) or not matched
    ):
        return {"matched": False, "score": 0, "reasons": ["Required phrases did not match"]}
    categories = tracker.get("categories", [])
    category = normalized(str(product.get("category") or ""))
    if categories and (not category or category not in {normalized(c) for c in categories}):
        return {
            "matched": False,
            "score": 0,
            "reasons": [
                "Observed category unknown" if not category else "Observed category outside tracker"
            ],
        }
    age = max(0.0, (parse_time(now) - parse_time(product.get("last_seen"))).total_seconds() / 3600)
    freshness = int(tracker.get("freshness_hours", 168))
    if age > freshness:
        return {
            "matched": False,
            "score": 0,
            "reasons": [f"Last observed more than {freshness} hours ago"],
        }
    score = float(len(matched)) * int(tracker.get("phrase_weight", 30))
    reasons.extend(f"Phrase “{p}” +{tracker.get('phrase_weight', 30)}" for p in matched)
    if categories:
        score += int(tracker.get("category_weight", 20))
        reasons.append(
            f"Observed category {product.get('category')} +{tracker.get('category_weight', 20)}"
        )
    recency = round(int(tracker.get("freshness_weight", 10)) * max(0, 1 - age / freshness), 1)
    score += recency
    if recency:
        reasons.append(f"Recent observation +{recency:g}")
    return {
        "matched": score >= tracker.get("min_score", 1),
        "score": round(score, 1),
        "reasons": reasons,
    }


def rank_all(product: Json, trackers: list[Json], *, now: str | datetime | None = None) -> Json:
    matches: list[dict[str, Any]] = []
    for tracker in trackers:
        result = rank_product(product, tracker, now=now)
        if result["matched"]:
            matches.append({"tracker_id": tracker["id"], "name": tracker["name"], **result})
    matches.sort(key=lambda item: (-item["score"], item["tracker_id"]))
    return {
        **product,
        "score": matches[0]["score"] if matches else 0,
        "reasons": matches[0]["reasons"] if matches else [],
        "matches": matches,
    }
