# Internal application contract

All times are UTC ISO 8601 strings. `Store(db_path)` initializes/migrates SQLite and uses a fresh connection per operation. Public methods return JSON-compatible dictionaries/lists. Bad input raises `ValueError`; missing identities raise `KeyError`. Each product is identified by `marketplace` (default `amazon.com`) plus observed `asin` (10 uppercase alphanumerics). Listing URLs are constrained to Amazon; image URLs to Amazon image hosts.

## Collector / durable jobs

- `enqueue_job(kind, *, query='', tracker_id=None, source='manual', payload=None) -> job`. Kinds `rfy`, `afa`, `search`, `reviews`, `login`, `disconnect`; search requires query. Browser settings are snapshotted in payload. Duplicate queued/running scope returns existing job.
- `claim_job(worker_id, *, now=None) -> job | None`: transactionally claims one queued job only when no unexpired running job exists. `heartbeat_job(id, worker_id, progress=None)` extends its lease. `recover_jobs(*, now=None)` requeues expired claims up to the bounded attempt count, then fails them.
- `update_job(id, *, status=None, progress=None, error=None, result=None) -> job`; terminal statuses `complete`, `partial`, `truncated`, `failed`, `needs_login`, `cancelled`. `get_job(id)`, `list_jobs(limit=50)`.
- `record_scan(job_id, products, *, status='complete', pages=1, advertised_count=None, error=None, now=None) -> run`: atomically upserts products/sightings and closes a job. Scope is kind + normalized query. Only complete scans mark absence within that scope. Product input: `{asin,title,marketplace?,image_url?,product_url?,vine_url?,category?,variant?}`. Initial completed scope is a notification baseline, including earlier partial pages. Later additions can alert; defaults suppress cross-scope/repeated/relist replay.
- `record_review_scan(job_id, records, *, status='complete', pages=1, source='amazon', now=None) -> run`: review input shape below. Never infers completion from disappearance.
- `schedule_due(*, now=None) -> list[job]`: schedules enabled RFY/AFA, tracker searches and review sync from durable due times. `set_connection(state, *, message='', last_success=None)` and `get_connection()`. States `disconnected`, `connecting`, `connected`, `needs_login`, `challenge`, `failed`.

Job shape: `{id,kind,query,tracker_id,source,status,created_at,started_at,finished_at,progress,error,result,payload,attempts,worker_id,lease_until}`. Run shape: `{id,job_id,scope,kind,query,status,pages,observed_count,advertised_count,started_at,finished_at,error}`.

## Web / discovery / settings

- `get_settings(*, include_secrets=False) -> dict`; default read masks secrets as `***` and includes `notification_secret_configured`. `update_settings(patch) -> dict`; `reset_settings() -> dict`. Flat settings keys and exact defaults are in `models.DEFAULT_SETTINGS`. Changes apply to newly queued jobs; pending delivery observes current delivery settings. Enabling notifications or editing trackers baselines existing products and never replays history.
- `list_products(*, query='', source='', tracker_id=None, category='', sort='rank', limit=60, offset=0, min_score=None, freshness_hours=None) -> {items,total,limit,offset,coverage}`. Sort `rank`, `newest`, `recent`, `title`. Each item adds `id,first_seen,last_seen,sources,score,reasons,matches`. History search is local FTS, never catalog search. `get_product(id) -> dict`.
- `list_trackers()`, `get_tracker(id)`, `save_tracker(data, tracker_id=None)`, `delete_tracker(id)`. Fields `{id,name,enabled,query,phrases,phrase_mode,exclusions,categories,phrase_weight,category_weight,freshness_weight,min_score,freshness_hours,notify,schedule_enabled,interval_minutes,page_budget}`. Lists are strings. `phrase_mode` is `any` or `all`; empty phrases match all unless excluded/category-restricted. Matching is deterministic; unknown category never satisfies a category restriction. Example trackers are editable instance records.
- `dashboard() -> {products,reviews,jobs,connection,coverage,notification_counts}`; `list_runs(limit=30)`.
- `export_data() -> dict`; `retention_preview(days=None) -> dict`; `apply_retention(*, confirm, days=None) -> dict` requires literal `DELETE HISTORY`; `delete_data(*, confirm)` requires `DELETE ALL DATA`.
- `backup(destination) -> path`: SQLite consistent backup; `Store.restore(backup, destination)` validates version/integrity before replacement, requires destination not exist.

## Review records

`list_reviews(*, status='', local_progress='', source='', query='', sort='oldest', limit=100, offset=0) -> {items,total,counts,coverage}`; `set_review_progress(id, progress) -> record`; local values `not_started`, `in_progress`, `submitted`. Observed status remains independent.

Record whitelist: `{external_id?,asin?,marketplace?,title,variant?,order_date?,observed_status?,observed_deadline?,product_url?,review_url?,rating?,source?}`. Observed status retains raw source text, unknown stays unknown. Multiple orders use external_id where observed; otherwise provisional identity is title + variant + order_date + asin. Records add `{id,identity,identity_quality,first_seen,last_seen,local_progress,age_days,target_date,target_kind,overdue}`. Dates YYYY-MM-DD. Targets are only observed deadlines or configured personal targets, with kind explicit.

`preview_review_import(records) -> {accepted,duplicates,rejected,ignored_fields,records,preview_hash}` strips all non-whitelist fields; no review/draft/body/note/media/auth data is persisted. `import_reviews(records, *, preview_hash) -> {imported,updated}` requires hash matching current preview and record content. `export_reviews() -> list[record]` uses the same whitelist plus local progress. Import never mutates original records.

## Notification service

`NotificationWorker(store).run_once(now=None) -> dict` independently claims and delivers bounded outbox work; network requests occur outside DB locks. `store.queue_notification_test() -> outbox row`; `store.list_notifications(limit=50)`; `store.queue_review_reminders(now=None)`. Destinations support webhook JSON and ntfy. Configuration requires explicit enablement; secrets are never present in returned outbox rows. Quiet hours use configured IANA timezone; start=end disables quiet hours. Digest batches bounded pending rows; failures retry with bounded exponential backoff and stop after five attempts. Network delivery has timeout and redirects disabled. No external destination is contacted by default.

## Integrated behavior and schema revision 2

`list_products` also accepts `job_id=None`. A selected job filters by its immutable run/sighting membership; its `coverage` contains only that run. A queued job returns no observed products. Live search callers pass `job_id` and leave `query=''`, because Amazon can return relevant results whose title does not repeat the query. Later scans do not change that job's membership. Returned metadata is the latest observed product metadata, and the run reports its own capture time.

Read settings mask both `notification_secret` and the entire `notification_url` with `***`; `notification_secret_configured` and `notification_url_configured` report presence. Sending `***` preserves a stored value, omitting it also preserves it, and an empty string explicitly clears it. Read/export APIs omit delivery credentials and destination paths from exported data. A consistent SQLite backup contains private settings and is created with mode 0600; it belongs in private operator storage.

Schema 2 adds marketplace/ASIN notification identity tombstones, migrated from schema 1 without deleting products/settings. Explicit retention removes old products/runs and completed delivery records, but retains minimal alert identities so recollecting a pruned ASIN does not replay it. `DELETE ALL DATA` clears those tombstones as part of its explicit reset; settings and tracker definitions remain. Unknown newer schema versions are rejected before writes. Supported backups are checked for schema/integrity and restored only to a new destination; reopening a schema-1 database performs its supported migration.

The initial completed or budget-truncated run establishes a scope's notification baseline. An interrupted partial run does not establish it. Only complete scans mark absence, so a truncated baseline can support later new-product alerts without inventing disappearance. Default alerts are once per ASIN/tracker; opted-in relist alerts require completed comparable absence in that same scope. Tracker edits and enabling delivery baseline existing identities.

Pausing collection pauses scheduled jobs while preserving their queue records; explicit manual searches remain available. Individual queue/tracker switches are checked when scheduled jobs are claimed, and deleted trackers cancel their pending jobs. New jobs snapshot page/runtime budgets, validated even when supplied by an internal caller.

Delivery runs outside the browser job loop and database transactions. Each HTTP request carries an `Idempotency-Key`. Delivery is at least once when a process dies after the destination receives a request but before SQLite records success; a compatible webhook can use the key to deduplicate that ambiguity. Retries stop after five attempts. Failed response bodies/URLs are not logged or persisted; delivery status contains only HTTP status or a network exception class. Digest groups at most 50 alerts; ordinary immediate delivery claims one at a time; user-requested destination tests bypass quiet hours and do not require ordinary notifications to be enabled.

Verification for this layer: `tests/test_store.py`, `tests/test_matching.py`, `tests/test_reviews.py`, and `tests/test_notifications.py` cover concurrent claims, lease recovery, schema upgrade, consistent backup/restore, scoped/truncated captures, exact live-job membership, no-replay retention, observed/manual review separation, import whitelisting, local HTTP delivery, quiet hours/digest, retries and secret masking. These tests use synthetic records and a loopback HTTP receiver; they do not claim real Amazon access or external notification delivery.
