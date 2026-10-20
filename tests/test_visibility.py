"""Reversible local hiding must preserve observed records and review obligations."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from vine_search.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "visibility.sqlite", seed=False)


def populate(store: Store) -> tuple[int, list[int], list[int]]:
    job = store.enqueue_job("search", query="synthetic")
    store.record_scan(
        job["id"],
        [
            {
                "asin": f"B00000000{number}",
                "title": f"Synthetic switch {number}",
                "image_url": f"https://m.media-amazon.com/{number}.jpg",
            }
            for number in (1, 2)
        ],
    )
    review_job = store.enqueue_job("reviews")
    store.record_review_scan(
        review_job["id"],
        [
            {
                "external_id": f"order-{number}",
                "asin": f"B00000000{number}",
                "title": f"Synthetic review {number}",
                "observed_status": "Awaiting Review" if number == 1 else "Reviewed",
                "source": "amazon:awaiting_review" if number == 1 else "amazon:reviewed",
                "order_date": "2026-01-01",
            }
            for number in (1, 2)
        ],
    )
    return (
        job["id"],
        sorted(p["id"] for p in store.list_products()["items"]),
        sorted(r["id"] for r in store.list_reviews()["items"]),
    )


def test_visibility_is_independent_and_preserves_history_and_rescans(store: Store) -> None:
    job_id, products, reviews = populate(store)
    before_product = store.get_product(products[0])
    before_review = store.set_review_progress(reviews[0], "in_progress")
    assert store.set_visibility("products", products, True)["updated"] == 2
    assert store.list_products()["total"] == 0
    assert store.list_reviews()["total"] == 2
    hidden = store.list_products(visibility="hidden", job_id=job_id, query="switch")
    assert hidden["total"] == 2
    assert hidden["items"][0]["hidden"] is True
    assert hidden["coverage"][0]["observed_count"] == 2
    after_product = store.get_product(products[0])
    for field in ("id", "asin", "first_seen", "last_seen", "sources"):
        assert after_product[field] == before_product[field]
    assert store.set_visibility("products", products, True)["updated"] == 0
    assert store.get_product(products[0])["hidden_at"] == after_product["hidden_at"]
    assert store.set_visibility("reviews", [reviews[0]], True)["updated"] == 1
    visible_reviews = store.list_reviews()
    assert visible_reviews["total"] == 1
    assert visible_reviews["counts"] == {"Reviewed": 1}
    hidden_reviews = store.list_reviews(visibility="hidden")
    assert hidden_reviews["counts"] == {"Awaiting Review": 1}
    assert hidden_reviews["items"][0]["local_progress"] == before_review["local_progress"]
    assert hidden_reviews["items"][0]["observed_status"] == before_review["observed_status"]
    assert store.list_reviews(visibility="all")["total"] == 2
    assert store.dashboard()["products"] == 0
    assert store.dashboard()["products_hidden"] == 2
    assert store.dashboard()["reviews"] == 1
    assert store.dashboard()["reviews_hidden"] == 1
    populate(store)
    reopened = Store(store.path)
    assert reopened.list_products()["total"] == 0
    assert reopened.get_review(reviews[0])["hidden"] is True
    assert reopened.get_review(reviews[0])["local_progress"] == "in_progress"
    with reopened.connect() as db:
        assert db.execute("SELECT count(*) FROM sightings").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM review_observations").fetchone()[0] == 4
    reopened.set_visibility("products", products, False)
    reopened.set_visibility("reviews", [reviews[0]], False)
    assert reopened.get_product(products[0])["hidden_at"] is None
    assert reopened.get_review(reviews[0])["hidden_at"] is None
    assert reopened.list_products(query="switch")["total"] == 2
    assert reopened.list_reviews()["total"] == 2


@pytest.mark.parametrize(
    ("resource", "ids", "hidden"),
    [
        ("other", [1], True),
        ("products", [], True),
        ("products", [1] * 201, True),
        ("products", [1, 1], True),
        ("products", [True], True),
        ("products", [0], True),
        ("products", [-1], True),
        ("products", ["1"], True),
        ("products", [2**63], True),
        ("products", "1", True),
        ("products", [1], "true"),
        ("products", [1], 1),
    ],
)
def test_visibility_rejects_invalid_batches_before_writing(
    store: Store, resource: str, ids: Any, hidden: Any
) -> None:
    populate(store)
    with pytest.raises(ValueError):
        store.set_visibility(resource, ids, hidden)
    assert store.list_products()["total"] == 2


@pytest.mark.parametrize("resource", ["products", "reviews"])
def test_missing_id_rolls_back_whole_batch_and_filter_is_validated(
    store: Store, resource: str
) -> None:
    _, products, reviews = populate(store)
    identities = products if resource == "products" else reviews
    with pytest.raises(KeyError):
        store.set_visibility(resource, [identities[0], 99999], True)
    listing = store.list_products if resource == "products" else store.list_reviews
    assert listing()["total"] == 2
    with pytest.raises(ValueError):
        listing(visibility="deleted")


def test_schema_two_upgrade_preserves_data_and_is_concurrent_safe(store: Store) -> None:
    _, products, reviews = populate(store)
    store.set_review_progress(reviews[0], "submitted")
    store.update_settings({"collection_interval_minutes": 60})
    tracker = store.save_tracker({"name": "Keep tracker", "phrases": ["switch"]})
    with store.connect(write=True) as db:
        for table in ("products", "reviews"):
            db.execute(f"ALTER TABLE {table} DROP COLUMN hidden")
            db.execute(f"ALTER TABLE {table} DROP COLUMN hidden_at")
        db.execute("ALTER TABLE reviews DROP COLUMN image_url")
        db.execute("PRAGMA user_version=2")
        before = {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("sightings", "review_observations", "jobs", "runs", "settings")
        }
    with ThreadPoolExecutor(max_workers=4) as workers:
        upgraded = list(workers.map(lambda _: Store(store.path), range(4)))
    reopened = upgraded[0]
    assert reopened.get_product(products[0])["hidden"] is False
    assert reopened.get_review(reviews[0])["hidden"] is False
    assert reopened.get_review(reviews[0])["local_progress"] == "submitted"
    assert reopened.list_products(query="switch")["total"] == 2
    assert reopened.get_settings()["collection_interval_minutes"] == 60
    assert reopened.list_trackers()[0]["id"] == tracker["id"]
    with reopened.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        for table, expected in before.items():
            assert [
                tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")
            ] == expected


def test_review_thumbnail_provenance_fallback_and_import_remain_separate(store: Store) -> None:
    _, _, reviews = populate(store)
    record = store.get_review(reviews[0])
    assert record["image_url"] == "https://m.media-amazon.com/1.jpg"
    assert record["source"] == "amazon:awaiting_review"
    job = store.enqueue_job("reviews")
    store.record_review_scan(
        job["id"],
        [
            {
                "external_id": "order-1",
                "title": "Synthetic review 1",
                "image_url": "https://images-na.ssl-images-amazon.com/observed.jpg",
            }
        ],
    )
    assert store.get_review(reviews[0])["image_url"].endswith("observed.jpg")
    imported = [
        {
            "external_id": "order-1",
            "title": "Import",
            "image_url": "https://evil.example/private-photo",
            "photos": ["private-photo"],
            "hidden": True,
        }
    ]
    preview = store.preview_review_import(imported)
    assert set(preview["ignored_fields"]) == {"image_url", "photos", "hidden"}
    assert "private-photo" not in str(preview["records"])
    store.import_reviews(imported, preview_hash=preview["preview_hash"])
    assert store.get_review(reviews[0])["image_url"].endswith("observed.jpg")
    assert store.get_review(reviews[0])["hidden"] is False
    with pytest.raises(KeyError):
        store.get_review(99999)


def test_hidden_review_retains_reminder_obligation(store: Store) -> None:
    _, _, reviews = populate(store)
    store.update_settings(
        {
            "notification_url": "http://127.0.0.1:9999/test",
            "notifications_enabled": True,
            "review_reminders_enabled": True,
        }
    )
    store.set_visibility("reviews", [reviews[0]], True)
    assert store.queue_review_reminders() == 1
    store.set_review_progress(reviews[0], "submitted")
    assert store.queue_review_reminders() == 0


def test_hidden_records_and_thumbnails_survive_backup_restore(store: Store, tmp_path: Path) -> None:
    _, products, reviews = populate(store)
    store.set_visibility("products", products, True)
    store.set_visibility("reviews", reviews, True)
    store.set_review_progress(reviews[0], "in_progress")
    before = store.get_review(reviews[0])
    backup = tmp_path / "private-backup.sqlite"
    store.backup(backup)
    target = tmp_path / "restored.sqlite"
    Store.restore(backup, target)
    restored = Store(target)
    assert restored.list_products()["total"] == restored.list_reviews()["total"] == 0
    assert restored.list_products(visibility="hidden")["total"] == 2
    for key in ("hidden", "hidden_at", "identity", "local_progress", "image_url"):
        assert restored.get_review(reviews[0])[key] == before[key]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "https://m.media-amazon.com.evil.example/image",
        "https://user:password@m.media-amazon.com/image",
    ],
)
def test_observed_review_thumbnail_rejects_untrusted_navigation(store: Store, url: str) -> None:
    job = store.enqueue_job("reviews")
    with pytest.raises(ValueError):
        store.record_review_scan(job["id"], [{"title": "Synthetic", "image_url": url}])
    assert store.list_reviews()["total"] == 0


def test_all_searches_are_exhaustive_and_keep_manual_schedule_identity(store: Store) -> None:
    scheduled = store.enqueue_job(
        "search", query="switch", source="schedule", payload={"exhaustive": False}
    )
    manual = store.enqueue_job("search", query="switch", payload={"exhaustive": False})
    assert scheduled["id"] != manual["id"]
    assert scheduled["payload"]["exhaustive"] is True
    assert manual["payload"]["exhaustive"] is True
    assert store.enqueue_job("search", query="SWITCH")["id"] == manual["id"]
    assert store.enqueue_job("search", query="switch", source="schedule")["id"] == scheduled["id"]
    assert Store(store.path).get_job(manual["id"])["payload"]["exhaustive"] is True
    assert Store(store.path).get_job(scheduled["id"])["payload"]["exhaustive"] is True
    queue = store.enqueue_job("rfy", payload={"exhaustive": True})
    assert queue["payload"]["exhaustive"] is False
    store.record_scan(manual["id"], [], pages=10001)
    assert store.get_job(manual["id"])["progress"]["pages"] == 10001
