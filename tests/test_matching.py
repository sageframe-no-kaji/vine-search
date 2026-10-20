from __future__ import annotations

from typing import Any

import pytest

from vine_search.matching import normalized, rank_all, rank_product
from vine_search.models import validate_tracker

NOW = "2026-01-03T12:00:00Z"
PRODUCT: dict[str, Any] = {
    "title": "USB-C Ethernet adapter",
    "category": "Electronics",
    "last_seen": NOW,
}


def test_unicode_phrase_all_and_exclusion_contract() -> None:
    assert normalized("\uff35\uff33\uff22   C") == "usb c"
    tracker = validate_tracker(
        {
            "phrases": ["usb", "ethernet"],
            "phrase_mode": "all",
            "phrase_weight": 25,
            "freshness_weight": 10,
        }
    )
    match = rank_product(PRODUCT, tracker, now=NOW)
    assert match["matched"] and match["score"] == 60
    assert len(match["reasons"]) == 3
    tracker["exclusions"] = ["adapter"]
    assert rank_product(PRODUCT, tracker, now=NOW)["matched"] is False
    tracker["exclusions"] = []
    tracker["phrases"].append("switch")
    assert rank_product(PRODUCT, tracker, now=NOW)["matched"] is False
    tracker["phrase_mode"] = "any"
    assert rank_product(PRODUCT, tracker, now=NOW)["matched"] is True


@pytest.mark.parametrize("category", ["", None, "Tools"])
def test_unknown_category_never_satisfies_restriction(category: str | None) -> None:
    tracker = validate_tracker({"categories": ["Electronics"], "phrases": ["usb"]})
    result = rank_product({**PRODUCT, "category": category}, tracker, now=NOW)
    assert not result["matched"] and result["score"] == 0


def test_observed_category_weights_freshness_threshold_pause() -> None:
    tracker = validate_tracker(
        {
            "phrases": ["USB"],
            "categories": ["electronics"],
            "category_weight": 40,
            "freshness_hours": 24,
        }
    )
    assert rank_product(PRODUCT, tracker, now=NOW)["score"] == 80
    old = {**PRODUCT, "last_seen": "2026-01-01T00:00:00Z"}
    assert not rank_product(old, tracker, now=NOW)["matched"]
    tracker["min_score"] = 100
    assert not rank_product(PRODUCT, tracker, now=NOW)["matched"]
    tracker["enabled"] = False
    assert rank_product(PRODUCT, tracker, now=NOW)["reasons"] == ["Tracker paused"]


def test_rank_selects_best_reason_set_stably() -> None:
    trackers = [
        {**validate_tracker({"name": "low", "phrases": ["usb"]}), "id": 2},
        {**validate_tracker({"name": "high", "phrases": ["usb"], "phrase_weight": 90}), "id": 1},
    ]
    ranked = rank_all(PRODUCT, trackers, now=NOW)
    assert ranked["score"] == 100
    assert ranked["matches"][0]["name"] == "high"
    assert rank_all(PRODUCT, [], now=NOW)["reasons"] == []
    tracker = validate_tracker({"phrases": [], "freshness_weight": 0, "min_score": 0})
    assert rank_product(PRODUCT, tracker, now=NOW)["matched"]
