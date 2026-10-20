"Independent bounded notification delivery with durable deduplication and leases."

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .models import Json, parse_time, stamp
from .store import Store


def in_quiet_hours(settings: Json, now: str | datetime | None = None) -> bool:
    start, end = settings["quiet_start"], settings["quiet_end"]
    if not start or start == end:
        return False
    local = parse_time(now).astimezone(ZoneInfo(settings["timezone"])).strftime("%H:%M")
    return bool(start <= local < end if start < end else local >= start or local < end)


class NotificationWorker:
    def __init__(self, store: Store, *, client: httpx.Client | None = None):
        self.store = store
        self.client = client

    def _claim(self, now: str, settings: Json) -> list[Json]:
        with self.store.connect(write=True) as db:
            db.execute(
                (
                    "UPDATE notifications SET status=CASE WHEN attempts>=5 THEN 'failed' "
                    "ELSE 'pending' END,error='Delivery interrupted; outcome "
                    "unknown',lease_until=NULL WHERE status='sending' AND lease_until<=?"
                ),
                (now,),
            )
            tests = db.execute(
                (
                    "SELECT * FROM notifications WHERE status='pending' AND kind='test' "
                    "AND available_at<=? ORDER BY id LIMIT 1"
                ),
                (now,),
            ).fetchall()
            rows = tests
            if (
                not tests
                and settings["notifications_enabled"]
                and not in_quiet_hours(settings, now)
            ):
                rows = db.execute(
                    (
                        "SELECT * FROM notifications WHERE status='pending' AND kind!='test' "
                        "AND available_at<=? ORDER BY id LIMIT 50"
                    ),
                    (now,),
                ).fetchall()
                if (
                    rows
                    and settings["notification_cadence"] == "digest"
                    and parse_time(rows[0]["created_at"])
                    + timedelta(minutes=settings["digest_minutes"])
                    > parse_time(now)
                ):
                    rows = []
                elif settings["notification_cadence"] == "immediate":
                    rows = rows[:1]
            for row in rows:
                db.execute(
                    (
                        "UPDATE notifications SET "
                        "status='sending',attempts=attempts+1,lease_until=? WHERE id=?"
                    ),
                    (stamp(parse_time(now) + timedelta(minutes=2)), row["id"]),
                )
            return [self.store._notification(row) for row in rows]

    def _deliver(self, settings: Json, rows: list[Json]) -> None:
        alerts = [{"id": row["id"], "kind": row["kind"], **row["payload"]} for row in rows]
        headers = {
            "User-Agent": "VineSearch/1.0",
            "Idempotency-Key": "vine-" + "-".join(str(row["id"]) for row in rows),
        }
        if settings["notification_secret"]:
            headers["Authorization"] = "Bearer " + settings["notification_secret"]
        client = self.client or httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)
        try:
            if settings["notification_adapter"] == "ntfy":
                headers["Title"] = (
                    "VineSearch" if len(rows) == 1 else f"VineSearch: {len(rows)} updates"
                )
                body = "\n\n".join(
                    str(alert.get("title", "VineSearch update"))
                    + "\n"
                    + str(
                        alert.get("message")
                        or alert.get("url")
                        or alert.get("observed_status")
                        or ""
                    )
                    for alert in alerts
                )
                response = client.post(
                    settings["notification_url"], content=body.encode("utf-8"), headers=headers
                )
            else:
                response = client.post(
                    settings["notification_url"],
                    json={"source": "VineSearch", "count": len(alerts), "alerts": alerts},
                    headers=headers,
                )
            if not 200 <= response.status_code < 300:
                raise DeliveryError(f"Destination returned HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            # Do not persist request URLs, tokens, response bodies, or repr(exception).
            raise DeliveryError(f"Delivery network failure ({type(exc).__name__})") from exc
        finally:
            if self.client is None:
                client.close()

    def run_once(self, now: str | datetime | None = None) -> Json:
        when = stamp(now)
        settings = self.store.get_settings(include_secrets=True)
        if not settings["notification_url"]:
            return {"sent": 0, "failed": 0, "status": "unconfigured"}
        self.store.queue_review_reminders(now=when)
        rows = self._claim(when, settings)
        if not rows:
            return {"sent": 0, "failed": 0, "status": "idle"}
        error: str | None = None
        try:
            self._deliver(settings, rows)
        except DeliveryError as exc:
            error = str(exc)
        with self.store.connect(write=True) as db:
            for row in rows:
                attempts = row["attempts"] + 1
                if error:
                    status = "failed" if attempts >= 5 else "pending"
                    next_at = stamp(
                        parse_time(when) + timedelta(seconds=min(3600, 30 * 2 ** (attempts - 1)))
                    )
                    db.execute(
                        (
                            "UPDATE notifications SET "
                            "status=?,available_at=?,error=?,lease_until=NULL WHERE id=? AND "
                            "status='sending'"
                        ),
                        (status, next_at, error, row["id"]),
                    )
                else:
                    db.execute(
                        (
                            "UPDATE notifications SET "
                            "status='sent',sent_at=?,error=NULL,lease_until=NULL WHERE id=? AND "
                            "status='sending'"
                        ),
                        (when, row["id"]),
                    )
        return {
            "sent": len(rows) if not error else 0,
            "failed": len(rows) if error else 0,
            "status": "retrying"
            if error and any(row["attempts"] < 4 for row in rows)
            else "failed"
            if error
            else "sent",
            "error": error,
        }

    def run_forever(self, *, poll_seconds: float = 5) -> None:
        if not 0.1 <= poll_seconds <= 60:
            raise ValueError("poll_seconds must be between 0.1 and 60")
        while True:
            self.run_once()
            time.sleep(poll_seconds)


class DeliveryError(Exception):
    """Sanitized error suitable for local delivery status."""
