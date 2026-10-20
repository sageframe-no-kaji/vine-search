# Installation and operation

## Published image

Download and unpack the versioned installation bundle linked in the README, then
run `sh docker/install.sh` from that directory. It uses the published image for
configuration creation and both runtime roles, so the host needs Docker and
Compose without Python or a developer checkout. The bundle includes the Chromium
security profile required by Compose. Keep those files together when updating.
An existing .env image selection is preserved. An explicit VINE_SEARCH_IMAGE
override is saved atomically so subsequent Compose commands use the same image;
other settings remain unchanged.

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

Set `VINE_SEARCH_ALLOWED_CLIENTS` to a comma-separated list of the operator's
device IPs or trusted CIDR networks to enforce that boundary in the application
as well. For example,
`127.0.0.1/32,::1/128,100.100.100.10/32` permits loopback health checks and one
operator device; replace the example address with the actual device address.
Include each required IPv4/IPv6 address and keep both loopback entries for health
checks. Empty means no application client-address restriction, while invalid
addresses or CIDRs fail startup. Use network addresses with host bits cleared
for CIDRs, such as `192.0.2.0/24`.

The allowlist covers all HTTP routes and the login-viewer WebSocket. It uses the
connection peer address and ignores `X-Forwarded-For`, `Forwarded` and similar
headers; IPv4-mapped IPv6 peers are matched against their IPv4 address. The shipped
web command disables Uvicorn proxy-header processing, and custom ASGI launchers
must also disable it to preserve this boundary.

The supported transport configuration is HTTP inside the encrypted Tailscale or
SSH connection. HTTPS termination by a reverse proxy needs additional explicit
origin configuration: current same-origin checks compare the browser origin with
the application's connection scheme, and forwarded scheme headers are ignored.
Do not re-enable arbitrary forwarding headers to work around that mismatch.
Any reverse proxy must enforce its own operator authentication or network policy,
because the application allowlist sees the proxy's connection address.

## Settings and schedules

Settings changes persist when saved; newly queued work uses the updated
collection configuration. RFY and AFA default to 15-minute polling with five-page,
120-second budgets. Review sync defaults to hourly with a ten-page budget.
Trackers have separate live queries, enablement and intervals.
Their phrase mode, exclusions, category restrictions, weights and freshness
thresholds determine actual ranked results.

Manual and scheduled searches traverse every result page Amazon exposes without
a page or total-time limit. Each navigation still has a timeout.
Cancel a long search in Activity; completed observations remain in history.
Login, queue collection, search, review sync and product-detail lookups share
one browser owner. Waiting work is visible in Activity, and the dashboard
remains usable while the browser is busy.

Use Help in the app for tracker examples, matching and score rules, schedule
setup, saved-draft behavior and notification instructions.

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

Take a private backup before an update. With the new installation bundle, select
the intended version explicitly; the installer persists it in .env before startup:

```sh
VINE_SEARCH_IMAGE=ghcr.io/sageframe-no-kaji/vine-search:0.1.1 sh docker/install.sh
```

An immutable `@sha256:` reference can replace the version tag. Alternatively,
edit `VINE_SEARCH_IMAGE` in .env yourself, then pull and recreate the services:

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
| Results collected but none shown | Clear the local tracker, freshness, score and visibility filters. Live search has a fixed Additional Items source. |
| Tracker does not save | Read the inline error; provide a name, valid numeric ranges, and an Amazon query when scheduling is enabled. Failed submissions retain entered fields. |
| Vine details unavailable | The item may have moved or disappeared since collection. Run a fresh search, then retry its details; Open product still opens the ordinary product page. |
| Layout changed | Preserve history and report sanitized structure; do not repeatedly retry challenges. |
| Notification failure | Check the masked destination configuration and Activity; retry is bounded. |
| Host rejected | Add the exact private host/IP to `VINE_SEARCH_ALLOWED_HOSTS`. |
| Viewer inaccessible after completion | Expected: its capability expires and VNC closes. Reconnect opens a fresh one. |
| Backup says browser is owned | Stop the collector before taking the archive. |

Logs contain operational state rather than page captures or credentials:
`docker compose logs --tail=100 web collector`. Do not include `.env`, session
files, full inventory exports, raw account HTML or private backup archives in
public issue reports.

## Live verification

Verify a running installation through its dashboard URL so the verifier shares
the normal durable queue and does not compete for the collector's profile:

```sh
uv run python -m vine_search.verify --mode live --url http://127.0.0.1:8765 \
  --wait-seconds 1800 --report data/live-verification.json
```

Use the reachable private or tunneled URL for a remote server. This command
queues RFY, AFA, a manual USB search, and review sync, then checks their recorded
scope, state and page counts. It records sanitized counts and version metadata;
it does not export credentials or inventory. The account must already be
connected, and a demonstration installation cannot pass as live evidence.

The USB search must finish without a page or total-time limit. Bounded RFY/AFA and
review runs can establish compatibility while reporting incomplete coverage;
their successful verification does not claim a complete catalog or review list.
The command's wait limit only limits how long verification waits. If it expires,
the queued work remains visible in Activity and is not automatically cancelled.

The mode without `--url` opens the dedicated profile directly and requires the
collector to be stopped. It is intended for standalone diagnosis, not a second
browser owner alongside a running installation. Keep reports and any captures
private unless they have been inspected and sanitized.
