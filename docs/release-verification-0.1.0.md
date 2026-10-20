# Version 0.1.0 verification

Status: published prerelease with actual Amazon collection verified on the deployed
image. Operator testing identified interface and collection-policy corrections
being prepared for version 0.1.1. This report records version 0.1.0 evidence and does
not claim that the later corrections are included in this artifact.

## Artifact and environment

Application and distribution version are `0.1.0`. Published source revision
[`89dff199286117957cb91a5ac59930ca0b7b41c9`](https://github.com/sageframe-no-kaji/vine-search/commit/89dff199286117957cb91a5ac59930ca0b7b41c9)
passed both jobs in [remote CI](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39454283200),
including the actual Docker login-viewer fixture and restart checks.
[Image publication](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39454574705)
succeeded and produced registry index digest
`sha256:b06a0197838e672ffdfc7671a2d1ea94f4d761c7478f7bb2b9e976c28057c6e0`.
An anonymous `linux/arm64` pull of that immutable digest passed at
`2026-10-20T18:33:49+00:00` in 34.394 seconds using a fresh empty Docker credential
configuration without authentication or credential helpers.

Both published architectures were scanned independently, and their finding
tuples match the reviewed local-image inventory: each has 95 package occurrences
across 37 CVEs, with 94 high and one critical occurrence and no populated
`FixedVersion` fields. Both image labels identify source revision `89dff19`.
The [security review](security-review.md) accepts these open findings only within
the documented operator-only private-prerelease boundary.

| Platform | Published manifest digest | Scan captured |
| --- | --- | --- |
| `linux/arm64` | `sha256:5ff34f34152f8d5dad0efc78e2699c6e11a26c303dae51853e3bf83918f8e765` | `2026-10-20T18:34:52+00:00` |
| `linux/amd64` | `sha256:a3413bda1eedcb0a3eedc6e9634b87e24f4ffc87497d54a0ba2601c72d6979fa` | `2026-10-20T18:35:46+00:00` |

The subsequent native-build workflow change at
[`b5649be522bfc21edcb0c10880c1a3d4f54c94e7`](https://github.com/sageframe-no-kaji/vine-search/commit/b5649be522bfc21edcb0c10880c1a3d4f54c94e7)
passed [CI run 39457902891](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39457902891).
It applies to future image builds; the published v0.1.0 artifact remains tied to
`89dff19` and the immutable digest above.

The [v0.1.0 prerelease](https://github.com/sageframe-no-kaji/vine-search/releases/tag/v0.1.0)
is published. Its 638,879-byte installation bundle and checksum were downloaded
anonymously using `curl -q` without credentials and verified at
`2026-10-20T16:30:58+00:00`; the bundle SHA-256 is
`22ba36b4d314b2a097ac136ab565f817222433d6eacd8aba0e3b2f76620796bc`.
All 22 regular files were extracted into a new directory and compared against the
archive. This establishes release-asset access independently of registry access.

The downloaded installation verifier then passed all 14 checks against the
anonymously pulled ARM64 image in 85.3 seconds, finishing at
`2026-10-20T18:35:50+00:00`. It used only the published assets and image, with no
source bind mount. The actual served login fixture passed all seven checks with
zero JavaScript errors; restart, SIGKILL and restoration into a second project's
fresh volumes preserved synthetic records, settings, the queued job and a private
session marker. The backup was mode `0600`, and removing the test containers left
both installations' volumes intact.

The source-history privacy check covered the release revision's four commits and
92 blobs.
Private process documents were removed before the first push; the inspected
published history contains no session material, raw captures or private inventory.
The public GitHub README was inspected in actual Chrome, where all four documented
images loaded with their expected dimensions.

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

The selected Linux AMD64 server anonymously pulled the same immutable registry
index, and both application roles are healthy on preverified ZFS bind mounts.
Runtime inspection confirmed UID 1000, read-only root filesystems and all Linux
capabilities dropped; the web role has only the application-data mount and no
session mount. Snapshot and replication timers were active. Dashboard, bootstrap
and health requests returned HTTP 200 through an encrypted SSH loopback tunnel;
the client tailnet service was stopped, so this does not verify the direct tailnet
route.

On that server, an unlisted Docker bridge peer received HTTP 403 from both the
dashboard and login-viewer WebSocket; forwarding-header spoofing also returned
403. The shipped AMD64 served-login fixture passed all seven lifecycle checks with
zero JavaScript errors at `2026-10-20T18:35:39+00:00`. It used disposable synthetic
pages, a temporary profile and separate display/ports without accessing the
installation's real session or restarting its services. These checks establish
deployment and synthetic login behavior. Subsequent actual Amazon evidence is
recorded separately in the acceptance matrix and account evidence below.

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
| Served Docker login, expiry and headless session reuse | Pass, synthetic Amazon page on ARM64 and AMD64 | Actual Chromium/Xvfb/noVNC; typed input asserted, automatic viewer close, cookie persistence, ownership, reconnect/cancel/timeout and capability rejection; deployed AMD64 fixture passed with zero JavaScript errors and no real-session access |
| API/session/privacy boundaries | Pass for tested attacks | Unsigned/cross-origin writes, hostile Host, viewer capability/WS checks, unsafe URLs/markup, masked secrets, session not mounted in web role; 23 operator-address checks include actual socket tests; deployed unlisted HTTP/WS peers and forwarding spoof received 403 |
| Python dependency audit | Pass | `uv run pip-audit`; no known vulnerabilities found |
| Container dependency audit | Accepted for private prerelease; open findings retained | Both published architecture manifests above were scanned: each matches the reviewed 95 open package occurrences across 37 CVEs, 94 high and 1 critical, with no Debian 13 `FixedVersion` fields. Acceptance requires an operator-only access boundary; [findings and limits](security-review.md) |
| Schema migration and backup validation | Pass, fixtures | Version 1 → 2 migration/reopen; newer schema refused; consistent backup; session/settings round trip; traversal/links/overwrite refusal |
| Restart/crash recovery | Pass, fixtures and published ARM64 image | Transactional single claim, lease recovery, maximum attempts, cancellation retention and persisted outbox; actual Docker restart and SIGKILL retained synthetic settings, tracker, review progress, queued job and private session marker |
| Fresh local image installation and Docker recovery | Pass | 14 checks in 74.88 seconds from fresh release assets without source mounts: setup, HTTP workflows, served login fixture, restart, SIGKILL, private backup, restore into another project's fresh volumes, and uninstall preserving both installations' volumes |
| Fresh public image installation | Pass, ARM64 | Anonymous assets and immutable image pull; all 14 installation/recovery checks passed in 85.3 seconds, including the actual served login fixture, restart, SIGKILL, mode-0600 backup, separate-volume restore and volume-preserving uninstall |
| Public source and CI | Pass | Published revision `89dff19`; both jobs passed in [CI run 39454283200](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39454283200), including 222 tests at 95.12% coverage and actual Docker/noVNC checks |
| Public README and source-history privacy | Pass for inspected artifacts | Four README images loaded in actual Chrome with correct dimensions; the release revision's four commits and 92 blobs passed the privacy check before publication |
| Registry image publication and anonymous pull | Pass, ARM64 pull | [Image publication run 39454574705](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39454574705) succeeded with the index digest recorded above; immutable ARM64 pull passed with a fresh empty credential configuration |
| Prerelease installation assets | Pass | [v0.1.0](https://github.com/sageframe-no-kaji/vine-search/releases/tag/v0.1.0) published; installation bundle and SHA-256 file downloaded anonymously, matched and unpacked into a new directory |
| Actual Amazon login and live RFY/AFA/search/reviews | Pass, observed pages | Operator connected through the served browser; running-service verification passed at 2026-10-20T18:48:26Z. RFY and AFA completed; USB search completed eight pages with 260 observations; reviews captured ten pages and correctly reported incomplete coverage. A specific MFA challenge was not independently observed |
| Deployment on selected server | Pass, private AMD64 deployment | Anonymous immutable pull; both roles healthy on preverified ZFS mounts; UID 1000, read-only roots, dropped capabilities and web/session separation confirmed; dashboard/bootstrap/health returned 200 through encrypted SSH tunnel |
| Direct client tailnet route | Not verified | Client tailnet service was stopped; successful dashboard access used an encrypted SSH loopback tunnel |
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
  --image ghcr.io/sageframe-no-kaji/vine-search@sha256:b06a0197838e672ffdfc7671a2d1ea94f4d761c7478f7bb2b9e976c28057c6e0 \
  --port 18765 --report /path/to/private-install-report.json --with-login
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

The published-image run sampled 51.39 MiB for the idle web process and 66.6 MiB
for the idle collector, with 0.65% and 0.99% CPU respectively. After restoring into
fresh volumes, those samples were 51.11 MiB and 60.2 MiB, with 0.26% and 1.54% CPU.
Its final eight-request HTTP sample had a median of 3.64 ms and maximum of 66.52 ms.
These observations describe the ARM64 Docker Desktop test host, not the deployment
server or live Amazon traffic.

A separate headless-browser run on the same local ARM64 image collected 600
synthetic cards across ten routed HTML pages in 15.893 seconds, including a
deliberate 1.5-second observation hold per page. Eight Docker samples during
collection reached 337.6 MiB of container working-set memory and 78.25% of one CPU.
The container included its normal idle collector service plus a separate Python
fixture driver; the Docker host provided ten logical CPUs and about 7.65 GiB RAM.
The profile was temporary, no authentication file was supplied, and the workload
included no Amazon network observations, real Amazon scripts/images or headed
login viewer.

Separate process-RSS samples reached 77.27 MiB for the resident collector service
and 756.94 MiB summed across all processes. The remainder includes the fixture
driver, Playwright, Chromium and health checks; summing RSS can double-count
shared pages, so these values are not browser-only memory or directly comparable
to the Docker working set. Sampled peaks do not establish instantaneous worst
case resource use or live-account performance.

Image caching is bounded to
200 MB/1,000 files, individual downloads to 5 MB, request bodies to 2 MB, page/runtime
budgets are validated, outbox attempts are bounded, and container logs rotate.
History cleanup is previewed and explicit; it never silently discards observations.

## Actual account evidence and follow-up

The operator signed in through the application's served browser on the selected
server. The collector then reused that session headlessly for real catalog and
review pages. Running-service verification queued normal protected collection
jobs without opening or copying the private profile, completing in 24.809 seconds
on 2026-10-20. RFY and AFA each completed one page; the USB search completed eight
pages with 260 observations, matching the advertised total in the operator's
contemporaneous Amazon screenshot. Review collection captured ten pages and
reported truncated coverage rather than claiming complete account coverage.
Raw account screenshots, session files and inventory remain private.

This verifies those observed Amazon structures and session reuse, not every future
Amazon layout or challenge. A specific MFA challenge, real account-expiry reconnect,
physical-phone operation and external notification delivery were not independently
observed. Operator feedback identified confusing limit wording, an incompatible
queue filter carrying into live search, missing review thumbnails and unwanted-item
visibility controls. Those corrections are being tested for 0.1.1; the 0.1.0 image
is not retroactively described as containing them.
