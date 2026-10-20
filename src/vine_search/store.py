"Transactional SQLite domain layer shared by the web and serial collector roles."

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .matching import normalized, rank_all, rank_product
from .models import (
    DEFAULT_SETTINGS,
    JOB_KINDS,
    LOCAL_PROGRESS,
    REVIEW_FIELDS,
    TERMINAL_STATUSES,
    Json,
    clean_product,
    integer,
    parse_time,
    safe_amazon_url,
    stamp,
    text_value,
    utcnow,
    validate_settings,
    validate_tracker,
)

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL,
updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, marketplace TEXT NOT NULL, asin TEXT NOT NULL, title TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT '', variant TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL
DEFAULT '',
 product_url TEXT NOT NULL, vine_url TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL,
last_seen TEXT NOT NULL,
 UNIQUE(marketplace,asin));
CREATE VIRTUAL TABLE IF NOT EXISTS product_fts USING
fts5(title,category,asin,content='products',content_rowid='id');
CREATE TRIGGER IF NOT EXISTS product_ai AFTER INSERT ON products BEGIN
 INSERT INTO product_fts(rowid,title,category,asin)
VALUES(new.id,new.title,new.category,new.asin); END;
CREATE TRIGGER IF NOT EXISTS product_ad AFTER DELETE ON products BEGIN
 INSERT INTO product_fts(product_fts,rowid,title,category,asin)
VALUES('delete',old.id,old.title,old.category,old.asin); END;
CREATE TRIGGER IF NOT EXISTS product_au AFTER UPDATE ON products BEGIN
 INSERT INTO product_fts(product_fts,rowid,title,category,asin)
VALUES('delete',old.id,old.title,old.category,old.asin);
 INSERT INTO product_fts(rowid,title,category,asin)
VALUES(new.id,new.title,new.category,new.asin); END;
CREATE TABLE IF NOT EXISTS trackers (id INTEGER PRIMARY KEY, data TEXT NOT NULL, created_at
TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, query TEXT NOT NULL DEFAULT '', tracker_id
INTEGER,
 source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL,
started_at TEXT,
 finished_at TEXT, progress TEXT NOT NULL DEFAULT '{}', error TEXT, result TEXT NOT NULL
DEFAULT '{}',
 payload TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0, worker_id TEXT,
 lease_until TEXT, available_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status,available_at,id);
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, job_id INTEGER, scope TEXT NOT NULL, kind TEXT NOT NULL, query TEXT
NOT NULL,
 status TEXT NOT NULL, pages INTEGER NOT NULL, observed_count INTEGER NOT NULL,
advertised_count INTEGER,
 started_at TEXT NOT NULL, finished_at TEXT NOT NULL, error TEXT);
CREATE INDEX IF NOT EXISTS runs_scope ON runs(scope,finished_at);
CREATE TABLE IF NOT EXISTS sightings (
 run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 scope TEXT NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY(run_id,product_id));
CREATE TABLE IF NOT EXISTS memberships (
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, scope TEXT NOT NULL,
 present INTEGER NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, episode INTEGER
NOT NULL DEFAULT 1,
 PRIMARY KEY(product_id,scope));
CREATE TABLE IF NOT EXISTS scopes (scope TEXT PRIMARY KEY, baseline_complete INTEGER NOT NULL
DEFAULT 0, completed_at TEXT);
CREATE TABLE IF NOT EXISTS alert_seen (
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
 seen_at TEXT NOT NULL, PRIMARY KEY(product_id,tracker_id));
CREATE TABLE IF NOT EXISTS alert_history (
 marketplace TEXT NOT NULL, asin TEXT NOT NULL,
 tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
 seen_at TEXT NOT NULL, PRIMARY KEY(marketplace,asin,tracker_id));
CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, payload TEXT NOT
NULL,
 status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, available_at TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, sent_at TEXT, error TEXT, lease_until TEXT);
CREATE INDEX IF NOT EXISTS notifications_ready ON notifications(status,available_at);
CREATE TABLE IF NOT EXISTS connection (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedule (scope TEXT PRIMARY KEY, due_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, identity_quality TEXT NOT NULL,
 external_id TEXT NOT NULL DEFAULT '', asin TEXT NOT NULL DEFAULT '', marketplace TEXT NOT NULL
DEFAULT 'amazon.com',
 title TEXT NOT NULL, variant TEXT NOT NULL DEFAULT '', order_date TEXT NOT NULL DEFAULT '',
 observed_status TEXT NOT NULL DEFAULT 'unknown', observed_deadline TEXT NOT NULL DEFAULT '',
 product_url TEXT NOT NULL DEFAULT '', review_url TEXT NOT NULL DEFAULT '', rating INTEGER,
 source TEXT NOT NULL DEFAULT 'amazon', local_progress TEXT NOT NULL DEFAULT 'not_started',
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reviews_order ON reviews(order_date,id);
CREATE TABLE IF NOT EXISTS review_observations (
 id INTEGER PRIMARY KEY, review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
 run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL, observed_status TEXT NOT NULL, source
TEXT NOT NULL, observed_at TEXT NOT NULL);
"""


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(row: sqlite3.Row | None) -> Json:
    if row is None:
        raise KeyError("Record not found")
    return dict(row)


def _job(row: sqlite3.Row | None) -> Json:
    data = _row(row)
    for key in ("progress", "result", "payload"):
        data[key] = json.loads(data[key])
    return data


def _tracker(row: sqlite3.Row | None) -> Json:
    data = _row(row)
    return {**json.loads(data.pop("data")), **data}


class Store:
    def __init__(self, db_path: str | Path, *, seed: bool = True):
        self.path = Path(db_path)
        if str(db_path) == ":memory:":
            raise ValueError("Use a temporary file for shared durable SQLite state")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize(seed)

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self, seed: bool) -> None:
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError(
                    f"Database schema {version} is newer than supported {SCHEMA_VERSION}; "
                    "restore with a compatible release"
                )
            if version == 0:
                tables = {
                    r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if tables and "settings" not in tables:
                    raise ValueError(
                        "Unrecognized database; refusing to initialize over existing data"
                    )
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif version == 1:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS alert_history (marketplace TEXT NOT NULL, "
                    "asin TEXT NOT NULL, tracker_id INTEGER NOT NULL REFERENCES trackers(id) "
                    "ON DELETE CASCADE, seen_at TEXT NOT NULL, "
                    "PRIMARY KEY(marketplace,asin,tracker_id))"
                )
                db.execute(
                    "INSERT OR IGNORE INTO alert_history SELECT p.marketplace,p.asin,"
                    "a.tracker_id,a.seen_at FROM alert_seen a JOIN products p ON p.id=a.product_id"
                )
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            now = parse_time().isoformat()
            is_new = db.execute("SELECT 1 FROM settings").fetchone() is None
            db.execute(
                "INSERT OR IGNORE INTO settings VALUES(1,?,?)", (_dump(DEFAULT_SETTINGS), now)
            )
            db.execute(
                "INSERT OR IGNORE INTO connection VALUES(1,?)",
                (
                    _dump(
                        {
                            "state": "disconnected",
                            "message": "Connect Amazon to begin collection",
                            "last_success": None,
                            "updated_at": now,
                        }
                    ),
                ),
            )
            if is_new and seed:
                examples = [
                    (
                        "Networking",
                        "network switch",
                        ["ethernet", "network switch", "router", "wifi"],
                        ["case"],
                    ),
                    ("Electronics", "usb c", ["usb", "charger", "electronics", "adapter"], []),
                    ("Making & tools", "tools", ["tool", "solder", "clamp", "drill"], []),
                    (
                        "Home improvement",
                        "home improvement",
                        ["faucet", "lighting", "shelf", "hardware"],
                        [],
                    ),
                    (
                        "Family activities",
                        "family games",
                        ["board game", "puzzle", "craft", "outdoor game"],
                        [],
                    ),
                ]
                for name, query, phrases, exclusions in examples:
                    tracker = validate_tracker(
                        {"name": name, "query": query, "phrases": phrases, "exclusions": exclusions}
                    )
                    db.execute(
                        "INSERT INTO trackers(data,created_at,updated_at) VALUES(?,?,?)",
                        (_dump(tracker), now, now),
                    )

    def _settings(self, db: sqlite3.Connection) -> Json:
        return {
            **DEFAULT_SETTINGS,
            **json.loads(db.execute("SELECT data FROM settings WHERE id=1").fetchone()[0]),
        }

    def get_settings(self, *, include_secrets: bool = False) -> Json:
        with self.connect() as db:
            result = self._settings(db)
        if not include_secrets:
            result["notification_secret_configured"] = bool(result["notification_secret"])
            result["notification_secret"] = "***" if result["notification_secret"] else ""
            result["notification_url_configured"] = bool(result["notification_url"])
            result["notification_url"] = "***" if result["notification_url"] else ""
        return result

    def update_settings(self, patch: Json) -> Json:
        with self.connect(write=True) as db:
            before = self._settings(db)
            after = validate_settings(before, patch)
            db.execute(
                "UPDATE settings SET data=?,updated_at=? WHERE id=1", (_dump(after), utcnow())
            )
            if not before["notifications_enabled"] and after["notifications_enabled"]:
                db.execute(
                    (
                        "INSERT OR IGNORE INTO alert_history "
                        "SELECT p.marketplace,p.asin,t.id,? FROM products p "
                        "CROSS JOIN trackers t"
                    ),
                    (utcnow(),),
                )
            schedule_keys = {
                "collection_interval_minutes",
                "review_sync_interval_minutes",
                "collection_enabled",
                "rfy_enabled",
                "afa_enabled",
                "review_sync_enabled",
            }
            if schedule_keys.intersection(patch):
                db.execute("DELETE FROM schedule")
        return self.get_settings()

    def reset_settings(self) -> Json:
        return self.update_settings(dict(DEFAULT_SETTINGS))

    def list_trackers(self) -> list[Json]:
        with self.connect() as db:
            return [_tracker(r) for r in db.execute("SELECT * FROM trackers ORDER BY id")]

    def get_tracker(self, tracker_id: int) -> Json:
        with self.connect() as db:
            return _tracker(
                db.execute("SELECT * FROM trackers WHERE id=?", (tracker_id,)).fetchone()
            )

    def save_tracker(self, data: Json, tracker_id: int | None = None) -> Json:
        with self.connect(write=True) as db:
            previous = (
                _tracker(db.execute("SELECT * FROM trackers WHERE id=?", (tracker_id,)).fetchone())
                if tracker_id is not None
                else None
            )
            tracker = validate_tracker(data, previous)
            now = parse_time().isoformat()
            if tracker_id is None:
                tracker_id = int(
                    db.execute(
                        "INSERT INTO trackers(data,created_at,updated_at) VALUES(?,?,?)",
                        (_dump(tracker), now, now),
                    ).lastrowid
                    or 0
                )
            else:
                db.execute(
                    "UPDATE trackers SET data=?,updated_at=? WHERE id=?",
                    (_dump(tracker), now, tracker_id),
                )
            db.execute(
                "INSERT OR IGNORE INTO alert_history SELECT marketplace,asin,?,? FROM products",
                (tracker_id, now),
            )
            db.execute("DELETE FROM schedule WHERE scope=?", (f"tracker:{tracker_id}",))
        return self.get_tracker(tracker_id)

    def delete_tracker(self, tracker_id: int) -> None:
        with self.connect(write=True) as db:
            if db.execute("DELETE FROM trackers WHERE id=?", (tracker_id,)).rowcount == 0:
                raise KeyError("Tracker not found")
            db.execute("DELETE FROM schedule WHERE scope=?", (f"tracker:{tracker_id}",))
            db.execute(
                (
                    "UPDATE jobs SET status='cancelled',finished_at=?,error='Tracker "
                    "deleted' WHERE tracker_id=? AND status='queued'"
                ),
                (utcnow(), tracker_id),
            )

    def enqueue_job(
        self,
        kind: str,
        *,
        query: str = "",
        tracker_id: int | None = None,
        source: str = "manual",
        payload: Json | None = None,
    ) -> Json:
        with self.connect(write=True) as db:
            return self._enqueue(
                db, kind, query=query, tracker_id=tracker_id, source=source, payload=payload
            )

    def _enqueue(
        self,
        db: sqlite3.Connection,
        kind: str,
        *,
        query: str = "",
        tracker_id: int | None = None,
        source: str = "manual",
        payload: Json | None = None,
        now: str | None = None,
    ) -> Json:
        if kind not in JOB_KINDS:
            raise ValueError("Unknown collection job kind")
        query = text_value(query, "query", 200)
        if kind == "search" and not query:
            raise ValueError("Live search requires a query")
        if kind != "search" and query:
            raise ValueError("Only search jobs accept a query")
        if (
            tracker_id is not None
            and db.execute("SELECT 1 FROM trackers WHERE id=?", (tracker_id,)).fetchone() is None
        ):
            raise KeyError("Tracker not found")
        source = text_value(source, "source", 50)
        existing = db.execute(
            (
                "SELECT * FROM jobs WHERE kind=? AND lower(query)=lower(?) AND status "
                "IN ('queued','running') ORDER BY id LIMIT 1"
            ),
            (kind, query),
        ).fetchone()
        if existing:
            return _job(existing)
        settings = self._settings(db)
        snapshot = {
            key: settings[key]
            for key in ("page_budget", "runtime_budget_seconds", "review_page_budget")
        }
        if payload:
            if not isinstance(payload, dict):
                raise ValueError("Job payload must be an object")
            if len(_dump(payload)) > 10000:
                raise ValueError("Job payload too large")
            snapshot.update(payload)
        integer(snapshot["page_budget"], "page_budget", 1, 100)
        integer(snapshot["review_page_budget"], "review_page_budget", 1, 100)
        integer(snapshot["runtime_budget_seconds"], "runtime_budget_seconds", 15, 1800)
        now = now or utcnow()
        cursor = db.execute(
            (
                "INSERT INTO jobs(kind,query,tracker_id,source,created_at,payload,"
                "available_at) VALUES(?,?,?,?,?,?,?)"
            ),
            (kind, query, tracker_id, source, now, _dump(snapshot), now),
        )
        return _job(db.execute("SELECT * FROM jobs WHERE id=?", (cursor.lastrowid,)).fetchone())

    def get_job(self, job_id: int) -> Json:
        with self.connect() as db:
            return _job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list_jobs(self, limit: int = 50) -> list[Json]:
        integer(limit, "limit", 1, 500)
        with self.connect() as db:
            return [
                _job(r) for r in db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
            ]

    def claim_job(self, worker_id: str, *, now: str | datetime | None = None) -> Json | None:
        when = stamp(now)
        with self.connect(write=True) as db:
            self._recover(db, when)
            if db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                return None
            state = json.loads(db.execute("SELECT data FROM connection WHERE id=1").fetchone()[0])[
                "state"
            ]
            settings = self._settings(db)
            blocked = state in {"disconnected", "needs_login", "challenge", "connecting", "failed"}
            row = db.execute(
                (
                    "SELECT * FROM jobs WHERE status='queued' AND available_at<=? AND (?=0 "
                    "OR kind IN ('login','disconnect')) "
                    "AND (source!='schedule' OR (?=1 AND ("
                    "(kind='rfy' AND ?=1) OR (kind='afa' AND ?=1) OR "
                    "(kind='reviews' AND ?=1) OR (kind='search' AND EXISTS("
                    "SELECT 1 FROM trackers t WHERE t.id=jobs.tracker_id "
                    "AND json_extract(t.data,'$.enabled')=1 "
                    "AND json_extract(t.data,'$.schedule_enabled')=1))))) "
                    "ORDER BY CASE WHEN kind IN "
                    "('login','disconnect') THEN 0 ELSE 1 END,id LIMIT 1"
                ),
                (
                    when,
                    int(blocked),
                    int(settings["collection_enabled"]),
                    int(settings["rfy_enabled"]),
                    int(settings["afa_enabled"]),
                    int(settings["review_sync_enabled"]),
                ),
            ).fetchone()
            if row is None:
                return None
            lease = stamp(parse_time(when) + timedelta(minutes=5))
            db.execute(
                (
                    "UPDATE jobs SET status='running',started_at=COALESCE(started_at,"
                    "?),attempts=attempts+1,worker_id=?,lease_until=? WHERE id=?"
                ),
                (when, worker_id, lease, row["id"]),
            )
            return _job(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def heartbeat_job(self, job_id: int, worker_id: str, progress: Json | None = None) -> None:
        with self.connect(write=True) as db:
            count = db.execute(
                (
                    "UPDATE jobs SET lease_until=?,progress=COALESCE(?,progress) WHERE "
                    "id=? AND worker_id=? AND status='running'"
                ),
                (
                    stamp(parse_time() + timedelta(minutes=5)),
                    _dump(progress) if progress is not None else None,
                    job_id,
                    worker_id,
                ),
            ).rowcount
            if not count:
                raise ValueError("Job is no longer owned by this worker")

    def _recover(self, db: sqlite3.Connection, now: str) -> int:
        rows = db.execute(
            "SELECT id,attempts FROM jobs WHERE status='running' AND lease_until<?", (now,)
        ).fetchall()
        for row in rows:
            failed = row["attempts"] >= 3
            db.execute(
                (
                    "UPDATE jobs SET status=?,worker_id=NULL,lease_until=NULL,"
                    "available_at=?,finished_at=?,error=? WHERE id=?"
                ),
                (
                    "failed" if failed else "queued",
                    now,
                    now if failed else None,
                    "Worker lease expired; retry limit reached"
                    if failed
                    else "Interrupted job recovered",
                    row["id"],
                ),
            )
        return len(rows)

    def recover_jobs(self, *, now: str | datetime | None = None) -> int:
        with self.connect(write=True) as db:
            return self._recover(db, stamp(now))

    def update_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        progress: Json | None = None,
        error: str | None = None,
        result: Json | None = None,
    ) -> Json:
        if status is not None and status not in TERMINAL_STATUSES | {"queued", "running"}:
            raise ValueError("Invalid job status")
        with self.connect(write=True) as db:
            existing = _job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if existing["status"] in TERMINAL_STATUSES and status and status != existing["status"]:
                raise ValueError("A completed job cannot change status")
            db.execute(
                (
                    "UPDATE jobs SET status=COALESCE(?,status),progress=COALESCE(?,"
                    "progress),error=COALESCE(?,error),result=COALESCE(?,result),"
                    "finished_at=CASE WHEN ? THEN ? ELSE finished_at END,"
                    "lease_until=CASE WHEN ? THEN NULL ELSE lease_until END WHERE id=?"
                ),
                (
                    status,
                    _dump(progress) if progress is not None else None,
                    text_value(error, "error", 1000) if error is not None else None,
                    _dump(result) if result is not None else None,
                    status in TERMINAL_STATUSES,
                    utcnow(),
                    status in TERMINAL_STATUSES,
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def set_connection(
        self, state: str, *, message: str = "", last_success: str | None = None
    ) -> Json:
        if state not in {
            "disconnected",
            "connecting",
            "connected",
            "needs_login",
            "challenge",
            "failed",
        }:
            raise ValueError("Invalid connection state")
        with self.connect(write=True) as db:
            previous = json.loads(
                db.execute("SELECT data FROM connection WHERE id=1").fetchone()[0]
            )
            data = {
                "state": state,
                "message": text_value(message, "message", 1000),
                "last_success": stamp(last_success)
                if last_success
                else previous.get("last_success"),
                "updated_at": utcnow(),
            }
            if state == "connected" and not last_success:
                data["last_success"] = utcnow()
            db.execute("UPDATE connection SET data=? WHERE id=1", (_dump(data),))
            return data

    def get_connection(self) -> Json:
        with self.connect() as db:
            return json.loads(db.execute("SELECT data FROM connection WHERE id=1").fetchone()[0])  # type: ignore[no-any-return]

    def schedule_due(self, *, now: str | datetime | None = None) -> list[Json]:
        when = stamp(now)
        created: list[Json] = []
        with self.connect(write=True) as db:
            settings = self._settings(db)
            if not settings["collection_enabled"]:
                return []
            plans: list[tuple[str, str, str, int | None, int, Json]] = []
            for kind in ("rfy", "afa"):
                if settings[f"{kind}_enabled"]:
                    plans.append(
                        (kind, kind, "", None, settings["collection_interval_minutes"], {})
                    )
            if settings["review_sync_enabled"]:
                plans.append(
                    ("reviews", "reviews", "", None, settings["review_sync_interval_minutes"], {})
                )
            for row in db.execute("SELECT * FROM trackers"):
                tracker = _tracker(row)
                if tracker["enabled"] and tracker["schedule_enabled"]:
                    plans.append(
                        (
                            f"tracker:{tracker['id']}",
                            "search",
                            tracker["query"],
                            tracker["id"],
                            tracker["interval_minutes"],
                            {"page_budget": tracker["page_budget"]},
                        )
                    )
            for scope, kind, query, tracker_id, minutes, payload in plans:
                due = db.execute("SELECT due_at FROM schedule WHERE scope=?", (scope,)).fetchone()
                if due and due[0] > when:
                    continue
                job = self._enqueue(
                    db,
                    kind,
                    query=query,
                    tracker_id=tracker_id,
                    source="schedule",
                    payload=payload,
                    now=when,
                )
                created.append(job)
                db.execute(
                    (
                        "INSERT INTO schedule VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET "
                        "due_at=excluded.due_at"
                    ),
                    (scope, stamp(parse_time(when) + timedelta(minutes=minutes))),
                )
        return created

    def _new_run(
        self,
        db: sqlite3.Connection,
        job: Json,
        status: str,
        pages: int,
        count: int,
        advertised: int | None,
        error: str | None,
        now: str,
    ) -> Json:
        if status not in TERMINAL_STATUSES:
            raise ValueError("Scan must have a terminal status")
        integer(pages, "pages", 0, 10000)
        if advertised is not None:
            integer(advertised, "advertised_count", 0, 10000000)
        if job["status"] in TERMINAL_STATUSES:
            raise ValueError("Job already completed")
        scope = job["kind"] + (":" + normalized(job["query"]) if job["query"] else "")
        cursor = db.execute(
            (
                "INSERT INTO runs(job_id,scope,kind,query,status,pages,"
                "observed_count,advertised_count,started_at,finished_at,error) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                job["id"],
                scope,
                job["kind"],
                job["query"],
                status,
                pages,
                count,
                advertised,
                job["started_at"] or job["created_at"],
                now,
                error,
            ),
        )
        return _row(db.execute("SELECT * FROM runs WHERE id=?", (cursor.lastrowid,)).fetchone())

    def _close_job(self, db: sqlite3.Connection, job_id: int, run: Json) -> None:
        db.execute(
            (
                "UPDATE jobs SET status=?,finished_at=?,lease_until=NULL,result=?,"
                "error=?,progress=? WHERE id=?"
            ),
            (
                run["status"],
                run["finished_at"],
                _dump({"run_id": run["id"], "count": run["observed_count"], "scope": run["scope"]}),
                run["error"],
                _dump({"pages": run["pages"], "observed": run["observed_count"]}),
                job_id,
            ),
        )

    def record_scan(
        self,
        job_id: int,
        products: list[Json],
        *,
        status: str = "complete",
        pages: int = 1,
        advertised_count: int | None = None,
        error: str | None = None,
        now: str | datetime | None = None,
    ) -> Json:
        when = stamp(now)
        cleaned = {p["asin"]: p for p in (clean_product(item) for item in products)}
        with self.connect(write=True) as db:
            job = _job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if job["kind"] not in {"rfy", "afa", "search"}:
                raise ValueError("This job does not collect products")
            run = self._new_run(db, job, status, pages, len(cleaned), advertised_count, error, when)
            scope = run["scope"]
            baseline = db.execute(
                "SELECT baseline_complete FROM scopes WHERE scope=?", (scope,)
            ).fetchone()
            is_baseline = not baseline or not baseline[0]
            db.execute("INSERT OR IGNORE INTO scopes(scope) VALUES(?)", (scope,))
            settings = self._settings(db)
            trackers = [_tracker(row) for row in db.execute("SELECT * FROM trackers")]
            observed: list[int] = []
            for product in cleaned.values():
                db.execute(
                    (
                        "INSERT INTO products(marketplace,asin,title,category,variant,"
                        "image_url,product_url,vine_url,first_seen,last_seen) "
                        "VALUES(:marketplace,:asin,:title,:category,:variant,:image_url,"
                        ":product_url,:vine_url,:first_seen,:last_seen) ON "
                        "CONFLICT(marketplace,asin) DO UPDATE SET title=excluded.title,"
                        "category=CASE WHEN excluded.category='' THEN products.category "
                        "ELSE excluded.category END,variant=CASE WHEN excluded.variant='' "
                        "THEN products.variant ELSE excluded.variant END,image_url=CASE "
                        "WHEN excluded.image_url='' THEN products.image_url ELSE "
                        "excluded.image_url END,product_url=excluded.product_url,"
                        "vine_url=CASE WHEN excluded.vine_url='' THEN products.vine_url "
                        "ELSE excluded.vine_url END,last_seen=excluded.last_seen"
                    ),
                    {**product, "first_seen": when, "last_seen": when},
                )
                stored = _row(
                    db.execute(
                        "SELECT * FROM products WHERE marketplace=? AND asin=?",
                        (product["marketplace"], product["asin"]),
                    ).fetchone()
                )
                product_id = stored["id"]
                observed.append(product_id)
                membership = db.execute(
                    "SELECT present,episode FROM memberships WHERE product_id=? AND scope=?",
                    (product_id, scope),
                ).fetchone()
                relisted = membership is not None and not membership["present"]
                episode = membership["episode"] + int(relisted) if membership else 1
                db.execute(
                    (
                        "INSERT INTO memberships VALUES(?,?,1,?,?,?) ON "
                        "CONFLICT(product_id,scope) DO UPDATE SET "
                        "present=1,last_seen=excluded.last_seen,episode=excluded.episode"
                    ),
                    (product_id, scope, when, when, episode),
                )
                db.execute(
                    "INSERT OR IGNORE INTO sightings VALUES(?,?,?,?)",
                    (run["id"], product_id, scope, when),
                )
                for tracker in trackers:
                    seen = db.execute(
                        "SELECT 1 FROM alert_history WHERE marketplace=? AND asin=? "
                        "AND tracker_id=?",
                        (stored["marketplace"], stored["asin"], tracker["id"]),
                    ).fetchone()
                    eligible = not is_baseline and (
                        not seen or (relisted and settings["notify_relists"])
                    )
                    match = rank_product(stored, tracker, now=when)
                    if (
                        eligible
                        and settings["notifications_enabled"]
                        and tracker["notify"]
                        and match["matched"]
                    ):
                        key = (
                            f"product:{stored['marketplace']}:{stored['asin']}:"
                            f"tracker:{tracker['id']}:{tracker['created_at']}"
                        ) + (f":relist:{scope}:{episode}" if seen else "")
                        self._queue_alert(
                            db,
                            key,
                            "match",
                            {
                                "product_id": product_id,
                                "title": stored["title"],
                                "asin": stored["asin"],
                                "url": stored["vine_url"] or stored["product_url"],
                                "tracker_id": tracker["id"],
                                "tracker": tracker["name"],
                                "score": match["score"],
                                "reasons": match["reasons"],
                                "relisted": relisted,
                            },
                            when,
                        )
                    db.execute(
                        "INSERT OR IGNORE INTO alert_history VALUES(?,?,?,?)",
                        (stored["marketplace"], stored["asin"], tracker["id"], when),
                    )
            if status == "complete":
                db.execute(
                    (
                        "UPDATE memberships SET present=0 WHERE scope=? AND product_id NOT IN "
                        "(SELECT product_id FROM sightings WHERE run_id=?)"
                    ),
                    (scope, run["id"]),
                )
            if status in {"complete", "truncated"}:
                db.execute(
                    "UPDATE scopes SET baseline_complete=1,completed_at=? WHERE scope=?",
                    (when, scope),
                )
            self._close_job(db, job_id, run)
            return run

    def list_runs(self, limit: int = 30) -> list[Json]:
        integer(limit, "limit", 1, 500)
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
            ]

    def _coverage(self, db: sqlite3.Connection, *, reviews: bool = False) -> list[Json]:
        clause = "kind='reviews'" if reviews else "kind!='reviews'"
        return [
            dict(r)
            for r in db.execute(
                "SELECT * FROM runs WHERE id IN (SELECT max(id) FROM runs "
                f"WHERE {clause} GROUP BY scope) ORDER BY finished_at DESC"
            )
        ]

    def _product(self, db: sqlite3.Connection, row: sqlite3.Row) -> Json:
        product = dict(row)
        product["sources"] = [
            dict(r)
            for r in db.execute(
                (
                    "SELECT scope,present,first_seen,last_seen,episode FROM memberships "
                    "WHERE product_id=? ORDER BY scope"
                ),
                (row["id"],),
            )
        ]
        return product

    def list_products(
        self,
        *,
        query: str = "",
        source: str = "",
        tracker_id: int | None = None,
        category: str = "",
        sort: str = "rank",
        limit: int = 60,
        offset: int = 0,
        min_score: float | None = None,
        freshness_hours: int | None = None,
        job_id: int | None = None,
    ) -> Json:
        integer(limit, "limit", 1, 200)
        integer(offset, "offset", 0, 1000000)
        if sort not in {"rank", "newest", "recent", "title"}:
            raise ValueError("Unknown product sort")
        query = text_value(query, "query", 200)
        filters: list[str] = []
        args: list[Any] = []
        if job_id is not None:
            self.get_job(job_id)
            filters.append(
                "EXISTS(SELECT 1 FROM sightings s JOIN runs r ON r.id=s.run_id "
                "WHERE s.product_id=p.id AND r.job_id=?)"
            )
            args.append(job_id)
        if query:
            terms = re.findall(r"\w+", query, re.UNICODE)
            if not terms:
                return {
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "coverage": self.list_runs(),
                }
            filters.append("p.id IN (SELECT rowid FROM product_fts WHERE product_fts MATCH ?)")
            args.append(" AND ".join('"' + t.replace('"', '""') + '"*' for t in terms))
        if source:
            filters.append(
                "EXISTS(SELECT 1 FROM memberships m WHERE m.product_id=p.id AND "
                "(m.scope=? OR m.scope LIKE ? ESCAPE '\\'))"
            )
            args.extend(
                [
                    source,
                    source.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ":%",
                ]
            )
        if category:
            filters.append("lower(p.category)=lower(?)")
            args.append(category)
        if freshness_hours is not None:
            integer(freshness_hours, "freshness_hours", 1, 8760)
            filters.append("p.last_seen>=?")
            args.append(stamp(parse_time() - timedelta(hours=freshness_hours)))
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            trackers = [_tracker(r) for r in db.execute("SELECT * FROM trackers")]
            if tracker_id is not None:
                trackers = [t for t in trackers if t["id"] == tracker_id]
                if not trackers:
                    raise KeyError("Tracker not found")
            products = [
                rank_all(dict(r), trackers)
                for r in db.execute("SELECT p.* FROM products p" + where, args)
            ]
            if tracker_id is not None:
                products = [p for p in products if p["matches"]]
            if min_score is not None:
                if (
                    isinstance(min_score, bool)
                    or not isinstance(min_score, (int, float))
                    or min_score < 0
                ):
                    raise ValueError("min_score must be nonnegative")
                products = [p for p in products if p["score"] >= min_score]
            if sort == "rank":
                products.sort(key=lambda p: (p["score"], p["last_seen"], p["id"]), reverse=True)
            elif sort in {"newest", "recent"}:
                products.sort(
                    key=lambda p: (
                        p["first_seen"] if sort == "newest" else p["last_seen"],
                        p["id"],
                    ),
                    reverse=True,
                )
            else:
                products.sort(key=lambda p: (p["title"].casefold(), p["id"]))
            items = products[offset : offset + limit]
            for item in items:
                item["sources"] = [
                    dict(r)
                    for r in db.execute(
                        (
                            "SELECT scope,present,first_seen,last_seen,episode FROM memberships "
                            "WHERE product_id=? ORDER BY scope"
                        ),
                        (item["id"],),
                    )
                ]
            return {
                "items": items,
                "total": len(products),
                "limit": limit,
                "offset": offset,
                "coverage": (
                    [dict(r) for r in db.execute("SELECT * FROM runs WHERE job_id=?", (job_id,))]
                    if job_id is not None
                    else self._coverage(db)
                ),
            }

    def get_product(self, product_id: int) -> Json:
        with self.connect() as db:
            row = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None:
                raise KeyError("Product not found")
            return rank_all(
                self._product(db, row), [_tracker(r) for r in db.execute("SELECT * FROM trackers")]
            )

    def _clean_review(self, item: Json, *, imported: bool = False) -> Json:
        if not isinstance(item, dict):
            raise ValueError("Each review record must be an object")
        clean = {key: item[key] for key in REVIEW_FIELDS if key in item}
        clean["title"] = text_value(clean.get("title", ""), "title", 1000, empty=False)
        clean["marketplace"] = clean.get("marketplace") or "amazon.com"
        if clean["marketplace"] != "amazon.com":
            raise ValueError("Only amazon.com is supported")
        for key, maximum in (
            ("external_id", 200),
            ("variant", 500),
            ("observed_status", 100),
            ("source", 100),
        ):
            clean[key] = text_value(
                clean.get(key)
                or ("unknown" if key == "observed_status" else "amazon" if key == "source" else ""),
                key,
                maximum,
            )
        asin = text_value(clean.get("asin") or "", "ASIN", 10).upper()
        if asin and not re.fullmatch(r"[A-Z0-9]{10}", asin):
            raise ValueError("ASIN must contain 10 letters or digits")
        clean["asin"] = asin
        for key in ("order_date", "observed_deadline"):
            value = clean.get(key) or ""
            if value:
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError(f"{key} must be YYYY-MM-DD")
                date.fromisoformat(value)
            clean[key] = value
        clean["product_url"] = safe_amazon_url(
            clean.get("product_url") or (f"https://www.amazon.com/dp/{asin}" if asin else "")
        )
        clean["review_url"] = safe_amazon_url(clean.get("review_url", ""))
        rating = clean.get("rating")
        clean["rating"] = integer(rating, "rating", 1, 5) if rating is not None else None
        progress = clean.get("local_progress", "not_started")
        if progress not in LOCAL_PROGRESS:
            raise ValueError("Invalid local progress")
        clean["local_progress"] = progress
        if imported:
            clean["source"] = "import"
        if clean["external_id"]:
            clean["identity"] = "amazon.com:external:" + clean["external_id"]
            clean["identity_quality"] = "observed"
        else:
            identity_parts = [
                clean["asin"],
                normalized(clean["title"]),
                normalized(clean["variant"]),
                clean["order_date"],
            ]
            clean["identity"] = (
                "amazon.com:provisional:"
                + hashlib.sha256(_dump(identity_parts).encode()).hexdigest()
            )
            clean["identity_quality"] = "provisional"
        return clean

    def _upsert_review(
        self, db: sqlite3.Connection, clean: Json, when: str, run_id: int | None = None
    ) -> tuple[int, bool]:
        existing = db.execute(
            "SELECT id FROM reviews WHERE identity=?", (clean["identity"],)
        ).fetchone()
        # A later observed order ID may bind an unambiguous provisional record.
        if existing is None and clean["identity_quality"] == "observed" and clean["order_date"]:
            candidates = db.execute(
                (
                    "SELECT id FROM reviews WHERE identity_quality='provisional' AND "
                    "asin=? AND title=? AND variant=? AND order_date=?"
                ),
                (clean["asin"], clean["title"], clean["variant"], clean["order_date"]),
            ).fetchall()
            if len(candidates) == 1:
                existing = candidates[0]
                db.execute(
                    (
                        "UPDATE reviews SET identity=?,identity_quality='observed',"
                        "external_id=? WHERE id=?"
                    ),
                    (clean["identity"], clean["external_id"], existing["id"]),
                )
        if existing:
            # Imported metadata cannot overwrite observed Amazon truth on an existing record.
            row = _row(db.execute("SELECT * FROM reviews WHERE id=?", (existing["id"],)).fetchone())
            if clean["source"] == "import" and row["source"] != "import":
                return int(existing["id"]), False
            fields = [
                "external_id",
                "asin",
                "title",
                "variant",
                "order_date",
                "observed_status",
                "observed_deadline",
                "product_url",
                "review_url",
                "rating",
                "source",
            ]
            updates = {
                key: clean[key] if clean[key] not in (None, "") else row[key] for key in fields
            }
            db.execute(
                "UPDATE reviews SET "
                + ",".join(key + "=?" for key in fields)
                + ",last_seen=? WHERE id=?",
                [updates[key] for key in fields] + [when, existing["id"]],
            )
            review_id = int(existing["id"])
        else:
            fields = [
                "identity",
                "identity_quality",
                "external_id",
                "asin",
                "marketplace",
                "title",
                "variant",
                "order_date",
                "observed_status",
                "observed_deadline",
                "product_url",
                "review_url",
                "rating",
                "source",
                "local_progress",
            ]
            cursor = db.execute(
                "INSERT INTO reviews("
                + ",".join(fields)
                + ",first_seen,last_seen) VALUES("
                + ",".join("?" for _ in range(len(fields) + 2))
                + ")",
                [clean[key] for key in fields] + [when, when],
            )
            review_id = int(cursor.lastrowid or 0)
        db.execute(
            (
                "INSERT INTO review_observations(review_id,run_id,observed_status,"
                "source,observed_at) VALUES(?,?,?,?,?)"
            ),
            (review_id, run_id, clean["observed_status"], clean["source"], when),
        )
        return review_id, existing is None

    def record_review_scan(
        self,
        job_id: int,
        records: list[Json],
        *,
        status: str = "complete",
        pages: int = 1,
        source: str = "amazon",
        now: str | datetime | None = None,
        error: str | None = None,
    ) -> Json:
        when = stamp(now)
        source = text_value(source, "source", 100)
        cleaned = [self._clean_review({**item, "source": source}) for item in records]
        with self.connect(write=True) as db:
            job = _job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if job["kind"] != "reviews":
                raise ValueError("This job does not collect reviews")
            run = self._new_run(db, job, status, pages, len(cleaned), None, error, when)
            for item in cleaned:
                self._upsert_review(db, item, when, run["id"])
            self._close_job(db, job_id, run)
            return run

    def _review(
        self, row: sqlite3.Row, settings: Json, *, now: str | datetime | None = None
    ) -> Json:
        record = dict(row)
        today = parse_time(now).date()
        order = date.fromisoformat(record["order_date"]) if record["order_date"] else None
        record["age_days"] = max(0, (today - order).days) if order else None
        target = record["observed_deadline"]
        kind = "amazon" if target else None
        if not target and order and settings["review_personal_target_days"]:
            target = (order + timedelta(days=settings["review_personal_target_days"])).isoformat()
            kind = "personal"
        record["target_date"] = target or None
        record["target_kind"] = kind
        record["overdue"] = bool(target and date.fromisoformat(target) < today)
        return record

    def list_reviews(
        self,
        *,
        status: str = "",
        local_progress: str = "",
        source: str = "",
        query: str = "",
        sort: str = "oldest",
        limit: int = 100,
        offset: int = 0,
    ) -> Json:
        integer(limit, "limit", 1, 500)
        integer(offset, "offset", 0, 1000000)
        if sort not in {"oldest", "newest", "recent", "title", "due"}:
            raise ValueError("Unknown review sort")
        if local_progress and local_progress not in LOCAL_PROGRESS:
            raise ValueError("Invalid local progress")
        query = text_value(query, "query", 200)
        filters: list[str] = []
        args: list[Any] = []
        for key, value in (
            ("observed_status", status),
            ("local_progress", local_progress),
            ("source", source),
        ):
            if value:
                filters.append(f"lower({key})=lower(?)")
                args.append(value)
        if query:
            filters.append("instr(lower(title || ' ' || asin || ' ' || variant),lower(?))>0")
            args.append(query)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            settings = self._settings(db)
            rows = [
                self._review(row, settings)
                for row in db.execute("SELECT * FROM reviews" + where, args)
            ]
            if sort == "oldest":
                rows.sort(key=lambda r: (r["order_date"] or "9999", r["id"]))
            elif sort in {"newest", "recent"}:
                rows.sort(
                    key=lambda r: (
                        r["order_date"] if sort == "newest" else r["last_seen"],
                        r["id"],
                    ),
                    reverse=True,
                )
            elif sort == "due":
                rows.sort(key=lambda r: (r["target_date"] or "9999", r["id"]))
            else:
                rows.sort(key=lambda r: r["title"].casefold())
            counts = {
                row["observed_status"]: row["n"]
                for row in db.execute(
                    "SELECT observed_status,count(*) n FROM reviews GROUP BY observed_status"
                )
            }
            return {
                "items": rows[offset : offset + limit],
                "total": len(rows),
                "counts": counts,
                "coverage": self._coverage(db, reviews=True),
                "limit": limit,
                "offset": offset,
            }

    def set_review_progress(self, review_id: int, progress: str) -> Json:
        if progress not in LOCAL_PROGRESS:
            raise ValueError("Invalid local progress")
        with self.connect(write=True) as db:
            if not db.execute(
                "UPDATE reviews SET local_progress=? WHERE id=?", (progress, review_id)
            ).rowcount:
                raise KeyError("Review record not found")
            row = db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
            assert row is not None
            return self._review(row, self._settings(db))

    def preview_review_import(self, records: list[Json]) -> Json:
        if not isinstance(records, list) or len(records) > 10000:
            raise ValueError("Import must contain a list of at most 10000 records")
        accepted: list[Json] = []
        rejected: list[Json] = []
        ignored: set[str] = set()
        duplicates = 0
        seen: set[str] = set()
        with self.connect() as db:
            for index, item in enumerate(records):
                try:
                    if isinstance(item, dict):
                        ignored.update(set(item) - REVIEW_FIELDS)
                    clean = self._clean_review(item, imported=True)
                    existing = db.execute(
                        "SELECT id FROM reviews WHERE identity=?", (clean["identity"],)
                    ).fetchone()
                    action = (
                        "duplicate"
                        if clean["identity"] in seen
                        else "update"
                        if existing
                        else "insert"
                    )
                    if action != "insert":
                        duplicates += 1
                    seen.add(clean["identity"])
                    accepted.append(
                        {
                            **clean,
                            "action": action,
                            "existing_id": existing[0] if existing else None,
                        }
                    )
                except (ValueError, TypeError) as exc:
                    rejected.append({"index": index, "error": str(exc)})
        result = {
            "accepted": len(accepted),
            "duplicates": duplicates,
            "rejected": rejected,
            "ignored_fields": sorted(ignored),
            "records": accepted,
        }
        result["preview_hash"] = hashlib.sha256(_dump(result).encode()).hexdigest()
        return result

    def import_reviews(self, records: list[Json], *, preview_hash: str) -> Json:
        preview = self.preview_review_import(records)
        if not preview_hash or preview_hash != preview["preview_hash"]:
            raise ValueError("Import preview changed; preview these records again before importing")
        inserted = updated = 0
        with self.connect(write=True) as db:
            for item in preview["records"]:
                if item["action"] == "duplicate":
                    continue
                _, is_new = self._upsert_review(db, item, utcnow())
                inserted += int(is_new)
                updated += int(not is_new)
        return {"imported": inserted, "updated": updated, "rejected": len(preview["rejected"])}

    def export_reviews(self) -> list[Json]:
        with self.connect() as db:
            return [
                {key: row[key] for key in sorted(REVIEW_FIELDS)}
                for row in db.execute("SELECT * FROM reviews ORDER BY id")
            ]

    def _queue_alert(
        self, db: sqlite3.Connection, key: str, kind: str, payload: Json, now: str
    ) -> None:
        db.execute(
            (
                "INSERT OR IGNORE INTO "
                "notifications(dedupe_key,kind,payload,created_at,available_at) "
                "VALUES(?,?,?,?,?)"
            ),
            (key, kind, _dump(payload), now, now),
        )

    def queue_notification_test(self) -> Json:
        with self.connect(write=True) as db:
            if not self._settings(db)["notification_url"]:
                raise ValueError("Configure a notification destination first")
            pending = db.execute(
                "SELECT * FROM notifications WHERE kind='test' AND status IN ('pending','sending')"
            ).fetchone()
            if pending:
                return self._notification(pending)
            now = utcnow()
            self._queue_alert(
                db,
                "test:"
                + stamp()
                + ":"
                + str(db.execute("SELECT COALESCE(max(id),0)+1 FROM notifications").fetchone()[0]),
                "test",
                {
                    "title": "VineSearch delivery test",
                    "message": (
                        "This test confirms delivery from your private VineSearch installation."
                    ),
                },
                now,
            )
            return self._notification(
                db.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 1").fetchone()
            )

    def _notification(self, row: sqlite3.Row | None) -> Json:
        data = _row(row)
        data["payload"] = json.loads(data["payload"])
        return data

    def list_notifications(self, limit: int = 50) -> list[Json]:
        integer(limit, "limit", 1, 500)
        with self.connect() as db:
            return [
                self._notification(row)
                for row in db.execute(
                    "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
                )
            ]

    def queue_review_reminders(self, *, now: str | datetime | None = None) -> int:
        when = stamp(now)
        count = 0
        with self.connect(write=True) as db:
            settings = self._settings(db)
            if not settings["notifications_enabled"] or not settings["review_reminders_enabled"]:
                return 0
            for row in db.execute(
                "SELECT * FROM reviews WHERE local_progress!='submitted'"
            ).fetchall():
                record = self._review(row, settings, now=when)
                status = normalized(record["observed_status"])
                if status not in {
                    "awaiting review",
                    "pending review",
                    "not yet reviewed",
                    "rejected",
                    "not approved",
                    "awaiting_review",
                }:
                    continue
                age = record["age_days"]
                target_due = (
                    record["target_date"]
                    and record["target_date"] <= parse_time(when).date().isoformat()
                )
                if not target_due and (age is None or age < settings["review_reminder_age_days"]):
                    continue
                latest = db.execute(
                    (
                        "SELECT created_at FROM notifications WHERE kind='review_reminder' AND "
                        "json_extract(payload,'$.review_id')=? ORDER BY id DESC LIMIT 1"
                    ),
                    (record["id"],),
                ).fetchone()
                if latest and parse_time(latest[0]) + timedelta(
                    days=settings["review_reminder_repeat_days"]
                ) > parse_time(when):
                    continue
                self._queue_alert(
                    db,
                    f"review:{record['id']}:{when}",
                    "review_reminder",
                    {
                        "review_id": record["id"],
                        "title": record["title"],
                        "observed_status": record["observed_status"],
                        "age_days": age,
                        "target_date": record["target_date"],
                        "target_kind": record["target_kind"],
                        "url": record["review_url"] or record["product_url"],
                    },
                    when,
                )
                count += 1
        return count

    def dashboard(self) -> Json:
        with self.connect() as db:
            return {
                "products": db.execute("SELECT count(*) FROM products").fetchone()[0],
                "reviews": db.execute("SELECT count(*) FROM reviews").fetchone()[0],
                "jobs": {
                    row["status"]: row["n"]
                    for row in db.execute("SELECT status,count(*) n FROM jobs GROUP BY status")
                },
                "connection": json.loads(
                    db.execute("SELECT data FROM connection WHERE id=1").fetchone()[0]
                ),
                "coverage": self._coverage(db),
                "notification_counts": {
                    row["status"]: row["n"]
                    for row in db.execute(
                        "SELECT status,count(*) n FROM notifications GROUP BY status"
                    )
                },
                "schedule": [
                    dict(row) for row in db.execute("SELECT * FROM schedule ORDER BY due_at")
                ],
            }

    def export_data(self) -> Json:
        with self.connect() as db:
            return {
                "schema_version": SCHEMA_VERSION,
                "exported_at": utcnow(),
                "settings": {
                    key: value
                    for key, value in self._settings(db).items()
                    if key not in {"notification_secret", "notification_url"}
                },
                "products": [
                    self._product(db, row)
                    for row in db.execute("SELECT * FROM products ORDER BY id")
                ],
                "trackers": [
                    _tracker(row) for row in db.execute("SELECT * FROM trackers ORDER BY id")
                ],
                "reviews": self.export_reviews(),
                "runs": [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY id")],
            }

    def retention_preview(self, days: int | None = None) -> Json:
        with self.connect() as db:
            days = days if days is not None else self._settings(db)["retention_days"]
            integer(days, "retention_days", 7, 3650)
            cutoff = stamp(parse_time() - timedelta(days=days))
            return {
                "days": days,
                "cutoff": cutoff,
                "products": db.execute(
                    "SELECT count(*) FROM products WHERE last_seen<?", (cutoff,)
                ).fetchone()[0],
                "runs": db.execute(
                    "SELECT count(*) FROM runs WHERE finished_at<?", (cutoff,)
                ).fetchone()[0],
                "notifications": db.execute(
                    (
                        "SELECT count(*) FROM notifications WHERE status IN ('sent','failed') "
                        "AND created_at<?"
                    ),
                    (cutoff,),
                ).fetchone()[0],
                "reviews": 0,
                "confirmation": "DELETE HISTORY",
            }

    def apply_retention(self, *, confirm: str, days: int | None = None) -> Json:
        if confirm != "DELETE HISTORY":
            raise ValueError("Explicit DELETE HISTORY confirmation is required")
        preview = self.retention_preview(days)
        with self.connect(write=True) as db:
            cutoff = preview["cutoff"]
            db.execute("DELETE FROM products WHERE last_seen<?", (cutoff,))
            db.execute("DELETE FROM runs WHERE finished_at<?", (cutoff,))
            db.execute(
                "DELETE FROM jobs WHERE finished_at<? AND status NOT IN ('running','queued')",
                (cutoff,),
            )
            db.execute(
                "DELETE FROM notifications WHERE status IN ('sent','failed') AND created_at<?",
                (cutoff,),
            )
        return preview

    def delete_data(self, *, confirm: str) -> Json:
        if confirm != "DELETE ALL DATA":
            raise ValueError("Explicit DELETE ALL DATA confirmation is required")
        with self.connect(write=True) as db:
            if db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                raise ValueError("Stop active collection before deleting data")
            for table in (
                "sightings",
                "memberships",
                "alert_seen",
                "alert_history",
                "products",
                "review_observations",
                "reviews",
                "notifications",
                "runs",
                "jobs",
                "scopes",
                "schedule",
            ):
                db.execute(f"DELETE FROM {table}")
        return {"deleted": True, "settings_preserved": True, "trackers_preserved": True}

    def backup(self, destination: str | Path) -> str:
        target = Path(destination)
        if target.exists():
            raise ValueError("Backup destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            backup = sqlite3.connect(target)
            try:
                source.backup(backup)
                backup.commit()
            finally:
                backup.close()
        target.chmod(0o600)
        return str(target)

    @staticmethod
    def restore(backup: str | Path, destination: str | Path) -> str:
        source_path, target = Path(backup), Path(destination)
        if not source_path.is_file() or target.exists():
            raise ValueError("Restore requires an existing backup and a new destination")
        source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
        try:
            version = source.execute("PRAGMA user_version").fetchone()[0]
            if (
                not 1 <= version <= SCHEMA_VERSION
                or source.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise ValueError("Backup schema or integrity is not supported")
            tables = {
                r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"settings", "products", "trackers", "jobs", "reviews", "runs"} <= tables:
                raise ValueError("Backup is missing required application tables")
            target.parent.mkdir(parents=True, exist_ok=True)
            output = sqlite3.connect(target)
            try:
                source.backup(output)
                output.commit()
            finally:
                output.close()
        finally:
            source.close()
        target.chmod(0o600)
        return str(target)
