from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from vine_search.models import parse_time, stamp
from vine_search.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "reviews.sqlite", seed=False)


def review(**extra: Any) -> dict[str, Any]:
    return {
        "title": "Synthetic drill",
        "asin": "B000000001",
        "variant": "Blue",
        "order_date": "2026-01-01",
        "observed_status": "Awaiting Review",
        **extra,
    }


def sync(store: Store, records: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    job = store.enqueue_job("reviews")
    return store.record_review_scan(job["id"], records, **kwargs)


def test_observed_and_local_status_independent_partial_absence_preserves(store: Store) -> None:
    sync(store, [review(external_id="order-a"), review(external_id="order-b")])
    records = store.list_reviews()
    assert records["total"] == 2
    first = records["items"][0]
    updated = store.set_review_progress(first["id"], "submitted")
    assert updated["observed_status"] == "Awaiting Review"
    sync(store, [], status="partial")
    assert store.list_reviews()["counts"] == {"Awaiting Review": 2}
    sync(store, [review(external_id="order-a", observed_status="Rejected")])
    first = store.list_reviews(status="Rejected")["items"][0]
    assert first["local_progress"] == "submitted"
    assert store.list_reviews()["total"] == 2
    assert store.list_reviews()["coverage"][0]["status"] == "complete"
    assert len(store.export_reviews()) == 2


def test_provisional_binding_and_personal_target_label(store: Store) -> None:
    sync(store, [review()])
    provisional = store.list_reviews()["items"][0]
    assert provisional["identity_quality"] == "provisional" and provisional["target_date"] is None
    store.set_review_progress(provisional["id"], "in_progress")
    sync(store, [review(external_id="observed-order")])
    bound = store.list_reviews()["items"][0]
    assert bound["id"] == provisional["id"] and bound["identity_quality"] == "observed"
    assert bound["local_progress"] == "in_progress"
    store.update_settings({"review_personal_target_days": 30})
    bound = store.list_reviews()["items"][0]
    assert bound["target_kind"] == "personal" and bound["target_date"] == "2026-01-31"
    assert bound["overdue"] and bound["age_days"] > 30
    sync(store, [review(external_id="observed-order", observed_deadline="2026-02-10")])
    assert store.list_reviews()["items"][0]["target_kind"] == "amazon"
    assert store.list_reviews()["items"][0]["target_date"] == "2026-02-10"


def test_import_whitelist_preview_duplicates_and_original_untouched(store: Store) -> None:
    original = review(
        external_id="import-a",
        body="PRIVATE REVIEW BODY",
        draft="PRIVATE DRAFT",
        notes="PRIVATE NOTES",
        photos=["private.jpg"],
        password="secret",
        approval_records=["private"],
        rating=4,
    )
    records = [original, original.copy(), review(title="Invalid", order_date="bad date")]
    preview = store.preview_review_import(records)
    assert preview["accepted"] == 2 and preview["duplicates"] == 1 and len(preview["rejected"]) == 1
    assert set(preview["ignored_fields"]) == {
        "body",
        "draft",
        "notes",
        "photos",
        "password",
        "approval_records",
    }
    assert "PRIVATE" not in str(preview["records"])
    with pytest.raises(ValueError, match="preview changed"):
        store.import_reviews(records, preview_hash="wrong")
    result = store.import_reviews(records, preview_hash=preview["preview_hash"])
    assert result == {"imported": 1, "updated": 0, "rejected": 1}
    exported = store.export_reviews()
    assert exported[0]["source"] == "import" and exported[0]["rating"] == 4
    assert "PRIVATE" not in str(store.export_data())
    assert original["body"] == "PRIVATE REVIEW BODY" and original["password"] == "secret"
    duplicate = store.preview_review_import([original])
    assert duplicate["duplicates"] == 1
    assert store.import_reviews([original], preview_hash=duplicate["preview_hash"])["updated"] == 1
    # Reusing an old preview after inventory changed is refused.
    with pytest.raises(ValueError):
        store.import_reviews(records, preview_hash=preview["preview_hash"])


def test_import_cannot_replace_current_amazon_truth(store: Store) -> None:
    sync(store, [review(external_id="order-a", observed_status="Reviewed")])
    records = [review(external_id="order-a", observed_status="Awaiting Review")]
    preview = store.preview_review_import(records)
    store.import_reviews(records, preview_hash=preview["preview_hash"])
    assert store.list_reviews()["items"][0]["observed_status"] == "Reviewed"


def test_amazon_source_filter_groups_sections_without_changing_provenance(store: Store) -> None:
    sources = ["amazon", "amazon:awaiting_review", "amazon:reviewed", "amazon-other"]
    sync(
        store,
        [
            review(external_id=f"source-{index}", source=source)
            for index, source in enumerate(sources)
        ],
    )
    imported = [review(external_id="imported-order")]
    preview = store.preview_review_import(imported)
    store.import_reviews(imported, preview_hash=preview["preview_hash"])
    observed = store.list_reviews(source="AMAZON")
    assert observed["total"] == 3
    assert {row["source"] for row in observed["items"]} == set(sources[:3])
    assert store.list_reviews(source="amazon:reviewed")["total"] == 1
    assert store.list_reviews(source="import")["total"] == 1
    hidden_id = next(row["id"] for row in observed["items"] if row["source"] == "amazon:reviewed")
    store.set_visibility("reviews", [hidden_id], True)
    assert store.list_reviews(source="amazon")["total"] == 2
    assert store.list_reviews(source="amazon", visibility="hidden")["total"] == 1
    assert store.list_reviews(source="amazon", visibility="all", limit=1, offset=1)["total"] == 3
    assert Store(store.path).get_review(hidden_id)["source"] == "amazon:reviewed"


@pytest.mark.parametrize(
    "extra",
    [
        {"marketplace": "amazon.co.uk"},
        {"title": ""},
        {"asin": "no"},
        {"order_date": "2026-01-32"},
        {"observed_deadline": "tomorrow"},
        {"review_url": "https://evil.test/phish"},
        {"rating": 6},
        {"local_progress": "approved"},
    ],
)
def test_review_import_invalid_rows_are_previewed_not_saved(
    store: Store, extra: dict[str, Any]
) -> None:
    preview = store.preview_review_import([review(**extra)])
    assert preview["accepted"] == 0 and len(preview["rejected"]) == 1
    assert store.list_reviews()["total"] == 0


def test_review_filters_unknown_status_sort_bounds_and_missing(store: Store) -> None:
    sync(
        store,
        [
            review(title="Z product", asin="", order_date="", observed_status="Unavailable"),
            review(title="A product", observed_status="unknown"),
        ],
        status="truncated",
        pages=2,
    )
    assert store.list_reviews(query="A product")["total"] == 1
    assert store.list_reviews(source="amazon")["total"] == 2
    assert store.list_reviews(status="Unavailable")["items"][0]["age_days"] is None
    for order in ("title", "newest", "recent", "due"):
        assert store.list_reviews(sort=order, limit=1)["total"] == 2
    record = store.list_reviews()["items"][0]
    store.set_review_progress(record["id"], "in_progress")
    assert store.list_reviews(local_progress="in_progress")["total"] == 1
    for kwargs in ({"sort": "fake"}, {"local_progress": "fake"}, {"limit": 0}):
        with pytest.raises(ValueError):
            store.list_reviews(**kwargs)
    with pytest.raises(KeyError):
        store.set_review_progress(100, "submitted")
    with pytest.raises(ValueError):
        store.set_review_progress(1, "approved")
    with pytest.raises(ValueError):
        store.preview_review_import([{}] * 10001)
    assert store.preview_review_import([42])["rejected"]  # type: ignore[list-item]
    with pytest.raises(ValueError):
        store.record_review_scan(store.enqueue_job("rfy")["id"], [])
    with pytest.raises(ValueError):
        store.record_scan(store.enqueue_job("reviews")["id"], [])


def test_review_reminders_targets_repeats_unknown_and_local_submission(store: Store) -> None:
    now = parse_time()
    sync(
        store,
        [
            review(external_id="a", order_date=(now.date() - timedelta(days=40)).isoformat()),
            review(external_id="b", observed_status="Reviewed"),
            review(external_id="c", observed_status="unknown"),
            review(external_id="d", order_date=""),
        ],
    )
    assert store.queue_review_reminders(now=now) == 0
    store.update_settings(
        {
            "notification_url": "http://127.0.0.1:9999/test",
            "notifications_enabled": True,
            "review_reminders_enabled": True,
        }
    )
    assert store.queue_review_reminders(now=now) == 1
    assert store.queue_review_reminders(now=now + timedelta(days=1)) == 0
    assert store.queue_review_reminders(now=now + timedelta(days=8)) == 1
    record = store.list_reviews(status="Awaiting Review")["items"][0]
    store.set_review_progress(record["id"], "submitted")
    assert store.queue_review_reminders(now=now + timedelta(days=16)) == 0
    reminder = store.list_notifications()[0]
    assert reminder["payload"]["target_kind"] is None
    assert reminder["payload"]["target_date"] is None
    assert stamp(now) == reminder["created_at"] or reminder["created_at"] > stamp(now)
