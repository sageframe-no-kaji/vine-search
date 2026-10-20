# Version 0.1.1 verification

Status: implementation under verification. The deployed 0.1.0 prerelease remains
available while this patch is checked. Its separate [historical report](release-verification-0.1.0.md)
records actual Amazon login, session reuse, RFY/AFA collection, an eight-page
USB search with 260 observations, and a bounded review sync. Those observations
do not establish that this patch's new product-details adapter works live.

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
| Both architecture inventories and dependency audit | Pending | Prior image's audit is not reused without comparing the actual new artifacts |
| Publication and anonymous image/asset access | Pending | New patch artifact not yet published |
| Upgrade with existing session/settings/history | Pending | Preserve user data; backup first; do not restart active work |
| Actual Amazon search/reviews and new details lookup | Pending | Verify the deployed patch through its single browser owner |
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
