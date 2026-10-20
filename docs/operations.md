# Installation and operation

## Local source build

Use Docker Engine with Compose, or Docker Desktop on a Mac. The browser needs
approximately 1 GB available memory in addition to the host's other services.
Python 3.12 and uv are needed for development commands, not normal image operation.

```sh
uv sync --dev
uv run python -m vine_search setup
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8765/health
```

Setup generates `.env` with a private internal service key. Keep it outside
version control and backups that may be shared publicly. The Compose application
uses two persistent named volumes: `data` for SQLite and image cache; `session` for
the collector-only Chromium profile. Both roles run as UID/GID 1000, with a
read-only image filesystem, dropped capabilities, and bounded logs. The browser
uses Chromium sandboxing.

## First connection and reconnect

Open the dashboard, choose Connect Amazon, then Open login browser. Sign into
Amazon in the embedded server browser and complete any MFA or challenge.
The viewer closes after actual Vine access is detected. A separate-tab link is
available when the embedded browser is too small. Cancel closes the temporary
viewer; a later connection can start again without deleting observations.

When Amazon expires a session, saved history remains usable and the dashboard
offers Reconnect. Disconnect pauses account access while retaining the session;
Disconnect and forget also removes the private profile. Neither deletes history.
No cookie export or extension is required.

## Phone and private network

Keep the default loopback binding when using an SSH tunnel:

```sh
ssh -L 8765:127.0.0.1:8765 your-private-server
```

For direct Tailscale access, set `VINE_SEARCH_BIND` to the server's Tailscale IPv4
address and include that address and the exact private DNS name in
`VINE_SEARCH_ALLOWED_HOSTS`. Restart Compose after editing `.env`, then open
`http://SERVER-TAILSCALE-IP:8765` from a device on the same tailnet. Tailnet access
rules must restrict this service to its operator. Do not bind the dashboard to a
public interface or publish the login service/VNC ports.

For HTTPS, place an authenticated private reverse proxy in front of the dashboard.
Forward WebSocket upgrades and retain the original Host header. The login viewer
resolves against the application origin, including on phones.

## Settings and schedules

Settings changes persist immediately; newly queued work uses the updated
collection configuration. RFY and AFA default to 15-minute polling with five-page,
120-second budgets. Review sync defaults to hourly with a ten-page budget.
Trackers have separate live queries, enablement, intervals and page budgets.
Their phrase mode, exclusions, category restrictions, weights and freshness
thresholds determine actual ranked results.

Collection pause stops scheduled collection without discarding queued work.
Manual collection and live-search requests remain visible in Activity.
Notifications default off. Enabling them establishes a baseline rather than
replaying the existing catalog. The delivery section explains immediate/digest
cadence, quiet hours, timezone, relists and optional review reminders.

Review target dates are either observed Amazon deadlines or a configured personal
target, labeled by source. “Marked submitted” is local progress, not evidence that
Amazon received or approved a review.

Retention settings do not delete history automatically. Preview cleanup, inspect
its scope, and type the confirmation phrase to apply it. Export first if the
history needs to be kept. Reset settings disables delivery and restores behavior
defaults while preserving records and tracker rules.

## Private export and import

Settings offers an application JSON export that excludes credentials. Reviews
offers a narrower metadata export and a previewed JSON import. Import accepts
identity, variants, dates, statuses, approved links and optional ratings/local
progress; it strips review bodies, drafts, notes, photos and credentials.
Duplicate handling is shown before committing, and a changed preview must be
reviewed again.

## Backup and restore

Stop both services before a complete backup. The collector lock prevents reading
an actively changing browser profile; SQLite's backup API creates a consistent
database snapshot. Backups include settings and private session material, so store
the archive with the same care as a login credential.

```sh
docker compose stop
docker compose run --rm --no-deps collector backup /data/backup.tgz
docker compose cp collector:/data/backup.tgz ./vine-search-backup.tgz
chmod 600 vine-search-backup.tgz
docker compose up -d
```

The backup remains in the data volume until explicitly removed. For a source-run
installation:

```sh
uv run python -m vine_search backup data/backups/vine-search.tgz
uv run python -m vine_search restore data/backups/vine-search.tgz \
  --data-dir data/restored-app --session-dir data/restored-session
```

Restore requires fresh empty destination directories and validates the archive
paths, database integrity and schema version before moving restored data into
place. Point a stopped installation at those directories using a Compose volume
override; keep the old volumes until the restored installation is verified.
Restoring never silently overwrites an existing installation.

For a Docker-only restore, create fresh volumes under a different Compose project
name. Stop the original installation to free its port, then run:

```sh
docker compose stop
docker compose -p vine-search-restored run --rm --no-deps \
  -v "$PWD/vine-search-backup.tgz:/backup.tgz:ro" \
  collector restore /backup.tgz --data-dir /data --session-dir /session
docker compose -p vine-search-restored up -d --no-build --wait
curl --fail http://127.0.0.1:8765/health
```

Use `-p vine-search-restored` on subsequent Compose commands for this restored
installation. Its volumes are separate from the original project's volumes.
Inspect the dashboard and reconnect if Amazon no longer accepts the restored
session. To return to the untouched original, stop the restored project and start
the original project. Never run both collectors against the same session volume.

## Updating and rollback

Take a private backup before an update. Select the intended version in
`VINE_SEARCH_IMAGE`, pull it, and recreate the services:

```sh
docker compose pull
docker compose up -d --no-build
docker compose ps
```

Schema migrations preserve existing data. A database from a newer unsupported
schema is rejected rather than treated as empty. For rollback, restore the
pre-update backup into fresh volumes and run the corresponding previous image.
Do not point an older image at a newer database.

`docker compose stop` and `docker compose down` preserve named volumes.
Uninstalling containers does not require deleting records. `down --volumes`
explicitly deletes the volumes and is not an update or normal uninstall command.

## Troubleshooting

| Symptom | Check and action |
| --- | --- |
| Saved results work but login fails | Check collector health and logs; reopen the login browser. |
| Needs login / challenge | Complete the normal Amazon flow; background work waits. |
| Empty live search | Inspect its run status and pages; empty, partial, failed and truncated differ. |
| Layout changed | Preserve history and report sanitized structure; do not repeatedly retry challenges. |
| Notification failure | Check the masked destination configuration and Activity; retry is bounded. |
| Host rejected | Add the exact private host/IP to `VINE_SEARCH_ALLOWED_HOSTS`. |
| Viewer inaccessible after completion | Expected: its capability expires and VNC closes. Reconnect opens a fresh one. |
| Backup says browser is owned | Stop the collector before taking the archive. |

Logs contain operational state rather than page captures or credentials:
`docker compose logs --tail=100 web collector`. Do not include `.env`, session
files, full inventory exports, raw account HTML or private backup archives in
public issue reports.
