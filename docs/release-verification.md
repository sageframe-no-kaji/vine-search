# Version 0.1.0 verification

Status: implementation candidate; final acceptance is blocked by missing authorized
Amazon access. Synthetic verification does not establish live Amazon compatibility.
Public distribution and installation results are recorded below as they are
observed. This report does not declare the release finished.

## Artifact and environment

The initial application implementation is committed as `48aafb2`. Application and
distribution version are `0.1.0`; the packaging, access-control and recovery changes
verified below retain that candidate version. The released source revision and
registry digest will be recorded after the registry workflow and anonymous pull
have completed.

The clean local installation run completed at `2026-10-20T16:01:43+00:00` against
Linux ARM64 image ID
`sha256:ad9c47f824fe7adcd4d39410dff762f2921b1c0531765f7a60e2f771a776b82c`.
All 14 installation and recovery checks passed in 74.88 seconds. This local image
ID is not evidence of a published registry manifest or anonymous pull.

Local verification ran on macOS 27.0.1, Apple Silicon, Python 3.12.10 and Docker
Desktop/Engine 28.5.1. Local Linux container evidence is `linux/arm64`.
The independent UI review used actual Chromium at 360, 390, 768 and 1440 pixels.
No physical phone was used. Tests use synthetic products, review records and
Amazon-shaped pages; screenshots are labeled demonstration data.

## Acceptance matrix

| Acceptance item | State | Observed evidence |
| --- | --- | --- |
| Lint and strict types | Pass | `uv run ruff check .`; `uv run mypy src`, 16 source files |
| Unit, integration and browser tests | Pass | 222 passed; 95.12% branch-aware coverage after the access-control and backup corrections; enforced floor remains 90% |
| Repeatable fixture command | Pass | `python -m vine_search.verify --mode fixture --report data/fixture-verification.json`; actual pytest/browser run, exit 0 |
| Independent integrated UI review | Pass | 34 assertions, zero JavaScript errors; five corrections resolved in one batch; [review](qa-review.md) |
| Required responsive widths and actual screenshots | Pass | Five views at all four widths; [desktop](images/discovery-desktop.png), [mobile](images/discovery-mobile.png), [reviews](images/reviews-desktop.png), [settings](images/settings-desktop.png) |
| Design documentation | Pass | Independent documenter reconciled shipped tokens, components and responsive behavior with [DESIGN.md](../DESIGN.md) |
| Durable identity, scoped coverage and live-job membership | Pass, fixtures | Real SQLite; repeated/cross-scope captures, partial/truncated runs and exact job membership |
| Tracker ranking and settings persistence | Pass, fixtures | CRUD, exclusions, unknown categories, any/all phrases, editable weights, pause and reset |
| Observed review status and local progress separation | Pass, fixtures | Pagination adapters, imports stripped to whitelist, duplicate preview, local changes and count/filter refresh |
| Local notification receiver | Pass | Actual loopback HTTP receiver; baseline, dedup, quiet hours, digest, bounded retry and durable outbox |
| Served Docker login, expiry and headless session reuse | Pass, synthetic Amazon page | Actual Chromium/Xvfb/noVNC; typed input asserted, automatic viewer close, cookie persistence, ownership, reconnect/cancel/timeout and capability rejection |
| API/session/privacy boundaries | Pass for tested attacks | Unsigned/cross-origin writes, hostile Host, viewer capability/WS checks, unsafe URLs/markup, masked secrets, session not mounted in web role; 23 operator-address checks include actual socket tests and forwarding-header spoof rejection |
| Python dependency audit | Pass | `uv run pip-audit`; no known vulnerabilities found |
| Container dependency audit | Accepted for private prerelease; final image audit pending | Independent review accepted the intermediate Debian 13 image's 95 open package occurrences across 37 CVEs under an operator-only access boundary; 94 high, 1 critical, no Debian 13 `FixedVersion` fields in that capture; [findings and limits](security-review.md) |
| Schema migration and backup validation | Pass, fixtures | Version 1 → 2 migration/reopen; newer schema refused; consistent backup; session/settings round trip; traversal/links/overwrite refusal |
| Restart/crash recovery | Pass, fixtures and local image | Transactional single claim, lease recovery, maximum attempts, cancellation retention and persisted outbox; actual Docker restart and SIGKILL retained synthetic settings, tracker, review progress, queued job and private session marker |
| Fresh local image installation and Docker recovery | Pass | 14 checks in 74.88 seconds from fresh release assets without source mounts: setup, HTTP workflows, served login fixture, restart, SIGKILL, private backup, restore into another project's fresh volumes, and uninstall preserving both installations' volumes |
| Fresh public image installation | Not run | Requires anonymous registry pull and the same installation/recovery exercise against that published image |
| Public repository, CI, image and prerelease | Not run | Publication follows local packaging/privacy checks |
| Actual Amazon/MFA and live RFY/AFA/search/reviews | Blocked | No authorized dedicated session supplied; live command exits 2 with `blocked` |
| Deployment on selected server | Storage prepared; deployment pending | Protected service dataset created and mounted with application ownership; service installation waits for the published image |
| Physical phone | Not run | Resized desktop browser is separate evidence |
| Optional external notification destination | Not configured | No destination supplied or external notification sent |

## Commands and evidence boundaries

```sh
uv sync --locked --dev
uv run playwright install chromium
uv run ruff check .
uv run mypy src
uv run pytest --cov-report=json:data/coverage.json
uv run python -m vine_search.verify --mode fixture --report data/fixture-verification.json
uv run python -m vine_search.verify --mode live --report data/live-verification.json
uv run pip-audit
docker compose config --quiet
docker compose build
docker compose up -d --wait
docker compose exec -T collector python /app/docker/verify-login.py
python docker/verify-install.py --directory /path/to/fresh-release-assets \
  --image ghcr.io/sageframe-no-kaji/vine-search:0.1.0 --port 18765 \
  --report /path/to/private-install-report.json
```

Fixture verification runs the actual suite and writes its command, result, timing
and evidence scope. The container verifier uses disposable synthetic Amazon routes
inside a temporary profile while exercising the real desktop and proxy stack.
The installation verifier uses an already-pulled image and fresh release assets,
separate named Compose projects and named volumes, with no source bind mount.
It exercises HTTP writes with CSRF protection, restart, SIGKILL, a private backup
and restoration into separate volumes, and retains the original volumes.
Live verification uses the installation's dedicated profile or an explicitly
supplied `VINE_SEARCH_AUTH_FILE`; it never reads everyday browser profiles.
It visits RFY, AFA, Additional Items search and reviews with a two-page budget and
publishes counts/status only. Missing authentication is a non-passing result.

Coverage supports regression assessment; it does not prove production correctness,
Amazon selector fidelity, security, a functioning phone, or successful delivery
to an unconfigured external service. Raw account/session material and working
evidence stay outside the public repository.

## Responsiveness and resource observations

On the local native app with 15 synthetic products, 20 requests per endpoint gave
p95 responses of 2.1 ms for the shell, 27.8 ms for bootstrap, 3.8 ms for title search,
2.8 ms for reviews and 1.9 ms for trackers. With a separate disposable database of
5,000 synthetic products, ranked retrieval of 60 rows had a median of 66.3 ms
(maximum 70.1 ms over ten runs); a selective title search had a median of 1.1 ms
(maximum 2.6 ms). Ingesting those products in one synthetic scan took 0.352 seconds.
These are local measurements, not a throughput guarantee.

The successful local-image installation run sampled 51.19 MiB for the idle web
process and 60.24 MiB for the idle collector, with 0.35% and 0.42% CPU respectively.
After restoration, the samples were 51.09 MiB and 61.16 MiB, with 0.20% and 1.19%
CPU. The final eight-request HTTP sample had a median of 3.45 ms and maximum of
77.74 ms. These are brief idle samples on the local Docker host.
Active-browser resource use and fresh public-image recovery remain separate
installation measurements. Image caching is bounded to
200 MB/1,000 files, individual downloads to 5 MB, request bodies to 2 MB, page/runtime
budgets are validated, outbox attempts are bounded, and container logs rotate.
History cleanup is previewed and explicit; it never silently discards observations.

## Remaining live gate

The operator must sign into Amazon through the served login browser, including
any MFA/challenge, or supply an authorized dedicated state file privately.
Then run live verification and inspect actual paging, selectors, review sections
and account expiry/reconnect on the deployment. No ordering or review posting is
part of acceptance. Until that evidence exists, this is a prerelease candidate,
not a verified finished Amazon integration.
