# Version 0.1.1 verification

Status: deployed and verified on the existing private installation on 2026-10-20.
The operator requested stopping at the running update; fresh 0.1.1 installation/
recovery and the remaining AMD64 audit are still pending. This is a prerelease,
not a claim that every distribution gate is complete. The separate
[0.1.0 report](release-verification-0.1.0.md) retains its historical evidence.

Runtime source: `fc4eedd47ad75a677ee1ec709fb54cc4775ef19e`.
[CI](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39484247316) and
[native image publication](https://github.com/sageframe-no-kaji/vine-search/actions/runs/39484246991)
passed. The immutable image index is
`sha256:1497e3b8f64981afa962b2cf2b329187ab5b38543a08317c7231ff676e810742`.

Actual running-service verification passed in 27.839 seconds: RFY 7 items/1 page,
AFA 17/1, USB 259/8 with complete pagination, and reviews 92/10 with explicitly
incomplete coverage at the configured review limit. A separate product-details
job verified the stored ASIN and returned a description and observed taxable value.
No product was requested and no review was submitted.

The upgrade took a private backup, migrated schema 2 to 3 and verified unchanged
settings, tracker records, product identities/first-seen dates and local review
progress. The initial connection check requested login; opening the normal login
flow reused the saved session and confirmed Vine access without credential entry.

## Changes being accepted

Manual and scheduled searches traverse every Amazon-exposed page without page
or total-time limits. RFY/AFA collection and reviews retain separate bounds. Product/review records have
independent hide and restore controls, including selected-item batches. Review
pictures follow the configured image privacy mode. Product titles and Open product
use the ordinary product URL; See details requests a read-only, product-specific
Vine lookup through the serial collector. The tracker editor and Help pages
explain literal matching, scoring, schedules and notifications and preserve failed
submissions. Live verification can use the running service's protected queue.

## Acceptance matrix

| Check | State | Evidence boundary |
| --- | --- | --- |
| Lint, strict types, complete pytest suite and 90% coverage floor | Pass | Ruff check/format, strict mypy (16 source files), 369 tests; 95.63% branch-aware coverage |
| Integrated fixture command | Pass | 369 tests passed in the repeatable fixture command; 50.407 seconds; synthetic evidence only |
| Independent review of changed behavior | Pass for reviewed paths | Cancellation/finalization and in-flight save/navigation races corrected; identity and write boundaries reviewed |
| Browser regressions and responsive captures | Pass, synthetic | 17 browser cases plus two independent save-race cases; 39 captures at 360/390/768/1440px, zero overflow or JavaScript errors |
| Schema 1/2 to 3 migration | Targeted tests pass | Preserves observations, progress and prior notification identity |
| Tracker save and reload | Regression checks pass; original cause unconfirmed | Failed requests and accepted-but-unconfirmed saves preserve entries; returned identity confirmed in fresh list; navigation cannot duplicate an in-flight create |
| Fresh published image install, restart, crash, backup and restore | Pending | Must use the new artifact and fresh volumes |
| Both architecture inventories and dependency audit | ARM64 complete; AMD64 audit pending | ARM64 inventories match its previous artifact; same 95 high/critical occurrences across 37 CVEs, no new or removed findings |
| Publication and anonymous image/asset access | Published prerelease | Both native images published; ARM64 anonymous immutable pull verified; fresh public-bundle installation remains pending |
| Upgrade with existing session/settings/history | Pass | Private backup, preserved records, schema migration, healthy services and saved-session reuse |
| Actual Amazon search/reviews and new details lookup | Pass within stated scope | Complete USB pagination and exact-item details; review sync remains bounded and incomplete |
| External notification destination | Not configured | No external destination supplied or message sent |
| Physical phone | Not run | Resized browser evidence remains separate |

## Reproduce

```sh
uv sync --locked --dev
uv run playwright install chromium
uv run ruff check .
uv run mypy src
uv run pytest --cov-report=json:data/coverage.json
uv run python -m vine_search.verify --mode fixture --report data/fixture-verification.json
uv run pip-audit
```

For an already connected running service:

```sh
uv run python -m vine_search.verify --mode live --url http://127.0.0.1:8765 \
  --report data/live-verification.json
```

The command queues ordinary jobs and verifies their saved scope and outcomes.
Missing authentication or failed required evidence is a non-passing result.
Bounded review sync may demonstrate page compatibility with incomplete coverage;
it does not establish a complete account review list. A wait timeout leaves the
underlying job visible in Activity. The standalone mode without `--url` must not
run alongside a collector that owns the same profile.

Reports, real inventory, private session material and raw account captures remain
outside public source. Public screenshots use synthetic records. Coverage and
HTTP success alone do not establish visual fidelity, live selector compatibility,
external notification delivery or a functioning phone.
