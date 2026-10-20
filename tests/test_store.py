from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from vine_search.models import DEFAULT_SETTINGS, clean_product, parse_time, stamp
from vine_search.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.sqlite", seed=False)


def product(number: int = 1, **extra: Any) -> dict[str, Any]:
    return {"asin": f"B{number:09}", "title": f"Ethernet network switch {number}", **extra}


def scan(store: Store, products: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    kind = kwargs.pop("kind", "rfy")
    query = kwargs.pop("query", "")
    job = store.enqueue_job(kind, query=query)
    return store.record_scan(job["id"], products, **kwargs)


def test_seeded_reopen_does_not_duplicate_or_reset(tmp_path: Path) -> None:
    path = tmp_path / "new.sqlite"
    store = Store(path)
    assert len(store.list_trackers()) == 5
    store.update_settings({"collection_interval_minutes": 30})
    reopened = Store(path)
    assert len(reopened.list_trackers()) == 5
    assert reopened.get_settings()["collection_interval_minutes"] == 30
    assert reopened.get_connection()["state"] == "disconnected"


def test_future_schema_and_foreign_database_refused_without_changes(tmp_path: Path) -> None:
    future = tmp_path / "future.sqlite"
    with sqlite3.connect(future) as connection:
        connection.execute("PRAGMA user_version=99")
        connection.execute("CREATE TABLE precious(value TEXT)")
        connection.execute("INSERT INTO precious VALUES ('keep')")
    with pytest.raises(ValueError, match="newer"):
        Store(future)
    with sqlite3.connect(future) as connection:
        assert connection.execute("SELECT value FROM precious").fetchone()[0] == "keep"
        connection.execute("PRAGMA user_version=0")
    with pytest.raises(ValueError, match="Unrecognized"):
        Store(future)
    with pytest.raises(ValueError, match="temporary file"):
        Store(":memory:")


@pytest.mark.parametrize(
    "patch",
    [
        {"collection_interval_minutes": 4},
        {"collection_interval_minutes": True},
        {"page_budget": 101},
        {"runtime_budget_seconds": 10},
        {"review_page_budget": 0},
        {"collection_enabled": "true"},
        {"notification_adapter": "email"},
        {"notification_adapter": []},
        {"notification_secret": "token\ninjected-header"},
        {"timezone": "Bad/Timezone"},
        {"quiet_start": "25:00", "quiet_end": "06:00"},
        {"quiet_start": "22:00"},
        {"notifications_enabled": True},
        {"notification_url": "file:///secrets"},
        {"notification_url": "https://user:pass@example.test"},
        {"notification_url": "https://example.test/#token"},
        {"notification_adapter": "ntfy", "notification_url": "https://example.test"},
        {"unknown_setting": 1},
        {"image_mode": "arbitrary"},
        {"retention_days": 1},
    ],
)
def test_settings_reject_invalid_atomically(store: Store, patch: dict[str, Any]) -> None:
    before = store.get_settings()
    with pytest.raises(ValueError):
        store.update_settings(patch)
    assert store.get_settings() == before


def test_secrets_masked_preserved_and_export_excluded(store: Store) -> None:
    settings = store.update_settings(
        {
            "notification_url": "https://example.test/private-hook",
            "notification_secret": "private-token",
            "notifications_enabled": True,
        }
    )
    assert settings["notification_secret"] == settings["notification_url"] == "***"
    assert settings["notification_url_configured"] and settings["notification_secret_configured"]
    store.update_settings({"notification_secret": "***", "notification_url": "***"})
    assert store.get_settings(include_secrets=True)["notification_secret"] == "private-token"
    assert "private-token" not in str(store.export_data())
    assert "private-hook" not in str(store.export_data())
    assert store.reset_settings()["notifications_enabled"] is False
    assert store.get_settings(include_secrets=True) == DEFAULT_SETTINGS


def test_product_identity_scope_absence_fts_and_partial_rollback(store: Store) -> None:
    first = scan(store, [product(1), product(1), product(2)], now="2026-01-01T00:00:00Z")
    assert first["observed_count"] == 2
    scan(store, [product(1, category="Electronics")], kind="afa", now="2026-01-02T00:00:00Z")
    scan(store, [], status="partial", now="2026-01-03T00:00:00Z")
    one = store.get_product(1)
    assert one["first_seen"] == "2026-01-01T00:00:00+00:00"
    assert one["last_seen"] == "2026-01-02T00:00:00+00:00"
    assert len(one["sources"]) == 2 and all(s["present"] for s in one["sources"])
    scan(store, [], now="2026-01-04T00:00:00Z")
    one = store.get_product(1)
    assert {s["scope"]: s["present"] for s in one["sources"]} == {"afa": 1, "rfy": 0}
    assert store.list_products(query='switch " OR * --')["total"] == 0
    assert store.list_products(query="ethernet")["total"] == 2
    assert store.list_products(query="***")["total"] == 0
    assert store.list_products(source="afa", category="Electronics")["total"] == 1
    assert store.list_products(source="rfy")["total"] == 2  # Historical membership retained.
    assert (
        store.list_products(limit=1, offset=1)["items"][0]["id"]
        != store.list_products(limit=1)["items"][0]["id"]
    )
    job = store.enqueue_job("rfy")
    with pytest.raises(ValueError):
        store.record_scan(job["id"], [product(3), {"asin": "bad", "title": "bad"}])
    assert store.list_products()["total"] == 2
    assert store.get_job(job["id"])["status"] == "queued"


def test_metadata_update_and_history_sorts(store: Store) -> None:
    scan(
        store,
        [
            product(
                1,
                title="Zinc USB charger",
                category="Tools",
                image_url="https://m.media-amazon.com/a.jpg",
                vine_url="https://www.amazon.com/vine/vine-items",
            )
        ],
        now=stamp(parse_time() - timedelta(hours=3)),
    )
    scan(store, [product(2, title="Alpha drill")])
    scan(store, [product(1, title="Updated USB charger")])
    assert store.get_product(1)["category"] == "Tools"
    assert store.get_product(1)["image_url"].endswith("a.jpg")
    assert store.list_products(query="zinc")["total"] == 0
    assert store.list_products(query="updated")["total"] == 1
    assert store.list_products(sort="title")["items"][0]["title"] == "Alpha drill"
    assert store.list_products(sort="newest")["total"] == 2
    assert store.list_products(sort="recent", freshness_hours=1)["total"] == 2
    assert store.list_products(min_score=1000)["total"] == 0
    with pytest.raises(KeyError):
        store.get_product(900)


def test_tracker_crud_filters_and_validation(store: Store) -> None:
    tracker = store.save_tracker(
        {"name": "Switches", "phrases": ["switch"], "exclusions": ["cover"]}
    )
    scan(store, [product(1), product(2, title="switch cover")])
    results = store.list_products(tracker_id=tracker["id"])
    assert results["total"] == 1 and results["items"][0]["score"] > 30
    changed = store.save_tracker({"phrase_weight": 100}, tracker["id"])
    assert changed["phrase_weight"] == 100
    assert store.list_products(tracker_id=tracker["id"])["items"][0]["score"] > 100
    store.save_tracker({"enabled": False}, tracker["id"])
    assert store.list_products(tracker_id=tracker["id"])["total"] == 0
    job = store.enqueue_job("search", query="switch", tracker_id=tracker["id"])
    store.delete_tracker(tracker["id"])
    assert store.get_job(job["id"])["status"] == "cancelled"
    with pytest.raises(KeyError):
        store.get_tracker(tracker["id"])
    with pytest.raises(KeyError):
        store.delete_tracker(tracker["id"])
    with pytest.raises(KeyError):
        store.list_products(tracker_id=tracker["id"])


@pytest.mark.parametrize(
    "data",
    [
        {"name": ""},
        {"enabled": 1},
        {"phrases": "abc"},
        {"phrases": [""]},
        {"phrases": ["x"] * 51},
        {"phrase_mode": "maybe"},
        {"min_score": -1},
        {"freshness_hours": 0},
        {"page_budget": 101},
        {"schedule_enabled": True},
        {"arbitrary": 1},
    ],
)
def test_tracker_invalid_settings(store: Store, data: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        store.save_tracker(data)
    assert store.list_trackers() == []


def test_serial_claim_crash_retry_and_terminal_immutability(store: Store) -> None:
    store.set_connection("connected")
    first = store.enqueue_job("rfy")
    assert store.enqueue_job("rfy")["id"] == first["id"]
    second = store.enqueue_job("afa")
    now = parse_time() + timedelta(seconds=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: store.claim_job(worker, now=now), ["one", "two"]))
    assert sum(item is not None for item in claims) == 1
    owner = next(item for item in claims if item is not None)
    store.heartbeat_job(first["id"], owner["worker_id"], {"pages": 2})
    assert store.get_job(first["id"])["progress"] == {"pages": 2}
    with pytest.raises(ValueError):
        store.heartbeat_job(first["id"], "intruder")
    for attempt in (2, 3):
        now += timedelta(minutes=6)
        assert store.recover_jobs(now=now) == 1
        claimed = store.claim_job("recovered", now=now)
        assert claimed and claimed["attempts"] == attempt
    now += timedelta(minutes=6)
    store.recover_jobs(now=now)
    assert store.get_job(first["id"])["status"] == "failed"
    claim = store.claim_job("next", now=now)
    assert claim and claim["id"] == second["id"]
    store.update_job(second["id"], status="complete", result={"count": 0}, progress={"pages": 1})
    with pytest.raises(ValueError):
        store.update_job(second["id"], status="queued")
    with pytest.raises(ValueError):
        store.record_scan(second["id"], [])


def test_auth_gate_login_priority_and_resume(store: Store) -> None:
    store.enqueue_job("rfy")
    assert store.claim_job("collector") is None
    login = store.enqueue_job("login")
    claimed = store.claim_job("collector")
    assert claimed and claimed["id"] == login["id"]
    store.update_job(login["id"], status="complete")
    store.set_connection("connected", last_success="2026-01-01T00:00:00Z")
    assert store.claim_job("collector") is not None
    store.set_connection("needs_login", message="Reconnect")
    assert store.get_connection()["last_success"] == "2026-01-01T00:00:00+00:00"
    with pytest.raises(ValueError):
        store.set_connection("invented")


def test_schedule_durable_scoped_and_snapshot_settings(store: Store) -> None:
    tracker = store.save_tracker(
        {"name": "Search", "query": "switch", "schedule_enabled": True, "page_budget": 2}
    )
    now = parse_time()
    jobs = store.schedule_due(now=now)
    assert {j["kind"] for j in jobs} == {"rfy", "afa", "reviews", "search"}
    search = next(job for job in jobs if job["kind"] == "search")
    assert search["tracker_id"] == tracker["id"]
    assert search["payload"]["exhaustive"] is True
    assert search["payload"]["page_budget"] == 5  # Legacy tracker limit is not scheduled.
    assert Store(store.path).schedule_due(now=now + timedelta(minutes=1)) == []
    store.update_settings({"page_budget": 9})
    assert store.get_job(jobs[0]["id"])["payload"]["page_budget"] == 5
    store.update_settings({"collection_enabled": False})
    assert store.schedule_due(now=now + timedelta(days=1)) == []
    assert store.dashboard()["schedule"] == []


@pytest.mark.parametrize(
    "data",
    [
        {"asin": "x", "title": "ok"},
        {"asin": "B000000001", "title": ""},
        {"asin": "B000000001", "title": "x", "marketplace": "amazon.co.uk"},
        {"asin": "B000000001", "title": "x", "product_url": "javascript:alert(1)"},
        {"asin": "B000000001", "title": "x", "image_url": "https://evil.test/a"},
        {"asin": "B000000001", "title": "x", "product_url": "https://www.amazon.com.evil.test/a"},
        {"asin": "B000000001", "title": "x", "product_url": "https://user@www.amazon.com/a"},
    ],
)
def test_product_identity_and_navigation_allowlist(data: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        clean_product(data)


def test_backup_restore_retention_and_explicit_delete(store: Store, tmp_path: Path) -> None:
    scan(store, [product(1)], now="2020-01-01T00:00:00Z")
    scan(store, [product(2)])
    store.save_tracker({"name": "Retained tracker"})
    backup = tmp_path / "backup.sqlite"
    assert store.backup(backup) == str(backup)
    assert backup.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        store.backup(backup)
    restored = tmp_path / "restored.sqlite"
    Store.restore(backup, restored)
    assert Store(restored).list_products()["total"] == 2
    with pytest.raises(ValueError):
        Store.restore(backup, restored)
    assert store.retention_preview(30)["products"] == 1
    with pytest.raises(ValueError):
        store.apply_retention(confirm="yes")
    store.update_settings({"retention_days": 7})
    assert store.list_products()["total"] == 2
    store.apply_retention(confirm="DELETE HISTORY", days=30)
    assert store.list_products()["total"] == 1
    assert store.list_products(query="switch")["total"] == 1
    with pytest.raises(ValueError):
        store.delete_data(confirm="yes")
    store.set_connection("connected")
    store.enqueue_job("afa")
    store.claim_job("owner")
    with pytest.raises(ValueError, match="Stop active"):
        store.delete_data(confirm="DELETE ALL DATA")
    for job in store.list_jobs():
        if job["status"] == "running":
            store.update_job(job["id"], status="cancelled")
    assert store.delete_data(confirm="DELETE ALL DATA")["settings_preserved"]
    assert store.list_products()["total"] == 0
    assert len(store.list_trackers()) == 1
    assert Store(restored).list_products()["total"] == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "arbitrary"},
        {"kind": "search"},
        {"kind": "rfy", "query": "not allowed"},
        {"kind": "rfy", "payload": {"x": "a" * 11000}},
    ],
)
def test_invalid_jobs(store: Store, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        store.enqueue_job(**kwargs)


def test_invalid_page_bounds_and_job_lookups(store: Store) -> None:
    with pytest.raises(KeyError):
        store.get_job(999)
    with pytest.raises(KeyError):
        store.enqueue_job("search", query="usb", tracker_id=999)
    for kwargs in ({"sort": "fake"}, {"limit": 0}, {"offset": -1}, {"min_score": -1}):
        with pytest.raises(ValueError):
            store.list_products(**kwargs)
    job = store.enqueue_job("rfy")
    with pytest.raises(ValueError):
        store.update_job(job["id"], status="invented")
    with pytest.raises(ValueError):
        store.record_scan(job["id"], [], pages=-1)
    assert store.list_runs() == []


def test_live_job_filter_returns_only_observed_membership(store: Store) -> None:
    historical = scan(store, [product(1, title="Old ethernet result")])
    job = store.enqueue_job("search", query="ethernet")
    assert store.list_products(job_id=job["id"])["total"] == 0
    store.record_scan(
        job["id"], [product(2, title="Current compatible adapter")], status="truncated"
    )
    results = store.list_products(job_id=job["id"])
    assert results["total"] == 1 and results["items"][0]["asin"] == "B000000002"
    assert results["coverage"][0]["status"] == "truncated"
    scan(store, [product(3)], kind="search", query="ethernet")
    assert store.list_products(job_id=job["id"])["items"][0]["asin"] == "B000000002"
    assert store.list_products(job_id=historical["job_id"])["total"] == 1


def test_pause_preserves_queued_scheduled_jobs_until_resume(store: Store) -> None:
    store.set_connection("connected")
    store.schedule_due()
    store.update_settings({"collection_enabled": False})
    assert store.claim_job("owner") is None
    assert all(job["status"] == "queued" for job in store.list_jobs())
    manual = store.enqueue_job("search", query="manual search")
    claimed = store.claim_job("owner")
    assert claimed and claimed["id"] == manual["id"]
    store.update_job(manual["id"], status="complete")
    store.update_settings({"collection_enabled": True, "rfy_enabled": False})
    claimed = store.claim_job("owner")
    assert claimed and claimed["kind"] == "afa"


def test_v1_upgrade_preserves_products_and_notification_baseline(store: Store) -> None:
    tracker = store.save_tracker({"name": "Existing"})
    scan(store, [product(1)])
    with store.connect(write=True) as db:
        db.execute("INSERT INTO alert_seen VALUES(?,?,?)", (1, tracker["id"], stamp()))
        db.execute("DROP TABLE alert_history")
        db.execute("PRAGMA user_version=1")
    upgraded = Store(store.path)
    assert upgraded.list_products()["total"] == 1
    with upgraded.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT asin FROM alert_history").fetchone()[0] == "B000000001"
    assert upgraded.list_trackers()[0]["name"] == "Existing"
