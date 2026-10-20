# VineSearch

Build and maintain the complete self-hosted single-account Vine discovery application.
The canonical public architecture is `docs/architecture.md`; the private execution
record lives in ignored `ho-process/`. Read K6 there first when it exists.

## Implementation

Use Python 3.11+, uv, src layout, FastAPI, SQLite, Playwright, and plain browser JavaScript.
Ruff formats and checks the source; mypy runs in strict mode; meaningful pytest
coverage has an enforced 90% floor. Do not lower gates or hide production paths.
The Ho language baseline is instantiated here so public contributors need no private
home-directory imports. Installed private skills guide the initial build only.

Keep the web process separate from the browser owner. Only the collector receives
the session/profile volume. Treat source observations as scoped and timestamped;
partial scans never establish global disappearance. Observed Amazon review status
is independent of local review progress.

Use neutral ground `#f4f5f7`, surface `#fbfcfd`, ink, restrained terracotta interactions,
IBM Plex Sans/Mono and selected DM Serif Display headings. No cream backgrounds.
Escape listing text and allowlist external image/navigation hosts. Protect writes.

## Verification and publication

Run `uv run ruff check .`, `uv run mypy src`, `uv run pytest`, and integrated fixture
verification. Live account, container, external delivery, and physical phone evidence
are separate categories. Never relabel fixtures as live verification.
Source publication is authorized under `sageframe-no-kaji/vine-search`; publish only
after the release gate. No private process, sessions, raw captures, or inventory in
source history or images. Keep runtime files in ignored `data/`.

## Ho process

K1/K2/K4/K6 reside in `ho-process/kamae-N-vine-search-*.md`, K3 is root README.md,
and K5 documents reside in `ho-process/hos/`. Before implementation, author the
bounded ho. On close fill Results/Reflect, mark complete, append K4 build record,
refresh K6 with COMPLETED / NEXT / ACTION ITEMS / BLOCKS / PROJECT LIFECYCLE,
and regenerate the ignored metadata roster. The nested private process repository
has no public remote. Use subagents for independent implementation and review.
