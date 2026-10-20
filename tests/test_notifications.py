from __future__ import annotations

import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from vine_search.models import DEFAULT_SETTINGS, parse_time, stamp
from vine_search.notifications import NotificationWorker, in_quiet_hours
from vine_search.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "outbox.sqlite", seed=False)


def product(number: int) -> dict[str, Any]:
    return {"asin": f"B{number:09}", "title": f"Ethernet switch {number}"}


def scan(store: Store, numbers: list[int], *, kind: str = "rfy", status: str = "complete") -> None:
    job = store.enqueue_job(kind)
    store.record_scan(job["id"], [product(n) for n in numbers], status=status)


def configured(store: Store) -> dict[str, Any]:
    tracker = store.save_tracker({"name": "Networking", "phrases": ["ethernet"], "notify": True})
    store.update_settings(
        {
            "notification_url": "https://example.test/private-token",
            "notification_secret": "secret",
            "notifications_enabled": True,
        }
    )
    return tracker


def test_partial_initial_baseline_no_flood_and_cross_queue_dedup(store: Store) -> None:
    configured(store)
    scan(store, [1], status="partial")
    scan(store, [1, 2])
    assert store.list_notifications() == []
    scan(store, [1, 2, 3])
    assert len(store.list_notifications()) == 1
    scan(store, [])
    scan(store, [1, 2, 3])
    scan(store, [], kind="afa")
    scan(store, [1, 2, 3], kind="afa")
    assert len(store.list_notifications()) == 1
    assert store.list_notifications()[0]["payload"]["asin"] == "B000000003"


def test_relist_is_opt_in_requires_complete_same_scope_absence(store: Store) -> None:
    configured(store)
    scan(store, [1])
    store.update_settings({"notify_relists": True})
    scan(store, [], status="partial")
    scan(store, [1])
    assert store.list_notifications() == []
    scan(store, [])
    scan(store, [1])
    assert len(store.list_notifications()) == 1
    assert store.list_notifications()[0]["payload"]["relisted"]
    scan(store, [1])
    assert len(store.list_notifications()) == 1


def test_rule_edit_and_enabling_destination_do_not_replay_history(store: Store) -> None:
    scan(store, [1])
    tracker = configured(store)
    scan(store, [1])
    assert store.list_notifications() == []
    store.save_tracker({"phrase_weight": 100}, tracker["id"])
    scan(store, [1, 2])
    assert len(store.list_notifications()) == 1
    assert store.list_notifications()[0]["payload"]["score"] == 110


def test_local_http_receiver_test_delivery_and_no_repeat(store: Store) -> None:
    received: list[dict[str, Any]] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append(
                {
                    "json": json.loads(body),
                    "auth": self.headers.get("Authorization"),
                    "key": self.headers.get("Idempotency-Key"),
                }
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        store.update_settings(
            {
                "notification_url": f"http://127.0.0.1:{server.server_port}/hook",
                "notification_secret": "local-test",
            }
        )
        test = store.queue_notification_test()
        assert store.queue_notification_test()["id"] == test["id"]
        assert NotificationWorker(store).run_once()["sent"] == 1
        assert received[0]["json"]["alerts"][0]["kind"] == "test"
        assert received[0]["auth"] == "Bearer local-test"
        assert received[0]["key"] == f"vine-{test['id']}"
        assert NotificationWorker(Store(store.path)).run_once()["sent"] == 0
        assert len(received) == 1 and store.list_notifications()[0]["status"] == "sent"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_failure_backoff_bounded_secret_free_and_restart(store: Store) -> None:
    configured(store)
    store.queue_notification_test()
    calls: list[httpx.Request] = []

    def failing(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="private response with secret")

    client = httpx.Client(transport=httpx.MockTransport(failing))
    now = parse_time()
    for attempt in range(1, 6):
        result = NotificationWorker(Store(store.path), client=client).run_once(now=now)
        assert result["failed"] == 1
        row = store.list_notifications()[0]
        assert row["attempts"] == attempt
        assert "secret" not in row["error"] and "private-token" not in str(row)
        if attempt < 5:
            assert NotificationWorker(store, client=client).run_once(now=now)["failed"] == 0
            now = parse_time(row["available_at"])
    assert row["status"] == "failed" and len(calls) == 5
    assert (
        NotificationWorker(store, client=client).run_once(now=now + timedelta(days=1))["sent"] == 0
    )
    client.close()


def test_timeout_sanitized_and_redirect_not_success(store: Store) -> None:
    configured(store)
    store.queue_notification_test()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret at https://example.test/private-token", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        result = NotificationWorker(store, client=client).run_once()
    assert result["error"] == "Delivery network failure (ReadTimeout)"
    next_at = store.list_notifications()[0]["available_at"]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(302, headers={"Location": "https://evil.test"})
        )
    ) as client:
        result = NotificationWorker(store, client=client).run_once(now=next_at)
    assert result["error"] == "Destination returned HTTP 302"


def test_digest_batches_after_interval_and_quiet_hours_preserve(store: Store) -> None:
    configured(store)
    store.update_settings(
        {
            "notification_cadence": "digest",
            "digest_minutes": 5,
            "quiet_start": "00:00",
            "quiet_end": "23:59",
        }
    )
    scan(store, [])
    scan(store, [1, 2, 3])
    payloads: list[dict[str, Any]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    now = parse_time()
    with httpx.Client(transport=httpx.MockTransport(capture)) as client:
        worker = NotificationWorker(store, client=client)
        assert worker.run_once(now=now)["sent"] == 0
        store.update_settings({"quiet_start": "", "quiet_end": ""})
        assert worker.run_once(now=now)["sent"] == 0
        assert worker.run_once(now=now + timedelta(minutes=6))["sent"] == 3
    assert len(payloads) == 1 and payloads[0]["count"] == 3
    assert all(row["status"] == "sent" for row in store.list_notifications())


@pytest.mark.parametrize(
    ("start", "end", "when", "expected"),
    [
        ("22:00", "07:00", "2026-01-01T23:00:00Z", True),
        ("22:00", "07:00", "2026-01-01T12:00:00Z", False),
        ("09:00", "17:00", "2026-01-01T12:00:00Z", True),
        ("09:00", "17:00", "2026-01-01T18:00:00Z", False),
        ("09:00", "09:00", "2026-01-01T09:00:00Z", False),
    ],
)
def test_quiet_hours_windows(start: str, end: str, when: str, expected: bool) -> None:
    assert (
        in_quiet_hours({**DEFAULT_SETTINGS, "quiet_start": start, "quiet_end": end}, when)
        is expected
    )
    assert in_quiet_hours(
        {
            **DEFAULT_SETTINGS,
            "quiet_start": "22:00",
            "quiet_end": "07:00",
            "timezone": "America/New_York",
        },
        "2026-01-02T04:00:00Z",
    )


def test_ntfy_utf8_delivery_and_claim_recovery(store: Store) -> None:
    configured(store)
    store.update_settings(
        {"notification_adapter": "ntfy", "notification_url": "https://ntfy.example.test/topic"}
    )
    test = store.queue_notification_test()
    with store.connect(write=True) as db:
        db.execute(
            "UPDATE notifications SET status='sending',attempts=1,lease_until=? WHERE id=?",
            (stamp(parse_time() - timedelta(minutes=1)), test["id"]),
        )
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(capture)) as client:
        assert NotificationWorker(store, client=client).run_once()["sent"] == 1
    assert requests[0].headers["Title"] == "VineSearch"
    assert b"delivery test" in requests[0].content
    assert store.list_notifications()[0]["attempts"] == 2
    assert (
        NotificationWorker(Store(store.path.parent / "empty.sqlite")).run_once()["status"]
        == "unconfigured"
    )
    with pytest.raises(ValueError):
        NotificationWorker(store).run_forever(poll_seconds=0)
    with pytest.raises(ValueError):
        Store(store.path.parent / "other.sqlite").queue_notification_test()


def test_truncated_baseline_can_alert_later_without_inventing_absence(store: Store) -> None:
    configured(store)
    scan(store, [1], status="truncated")
    scan(store, [2], status="truncated")
    assert len(store.list_notifications()) == 1
    assert store.list_notifications()[0]["payload"]["asin"] == "B000000002"
    assert store.get_product(1)["sources"][0]["present"] == 1


def test_explicit_retention_preserves_dedup_but_new_asin_can_alert(store: Store) -> None:
    configured(store)
    job = store.enqueue_job("rfy")
    store.record_scan(job["id"], [product(1)], now="2020-01-01T00:00:00Z")
    store.apply_retention(confirm="DELETE HISTORY", days=30)
    assert store.list_products()["total"] == 0
    scan(store, [1, 2])
    assert len(store.list_notifications()) == 1
    assert store.list_notifications()[0]["payload"]["asin"] == "B000000002"
