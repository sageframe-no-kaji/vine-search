# Contributing

Use Python 3.12 and uv. Install the locked development environment and Chromium:

```sh
uv sync --dev
uv run playwright install chromium
uv run pre-commit install
uv run ruff check .
uv run mypy src
uv run pytest
uv run python -m vine_search.verify --mode fixture --report data/fixture-verification.json
```

Keep fixtures synthetic and distinguish parser/browser fixtures from real Amazon
evidence. Add behavior tests for identity, partial scans, authentication boundaries
and delivery/restart failure paths. The application uses server-side Python and
plain JavaScript; a frontend compilation service is not needed.

Report reproducible defects with the app/image version, browser and sanitized
steps. Never attach sessions, cookies, `.env`, full account HTML, personal inventory
or review drafts. For an issue involving a private session boundary, describe the
affected endpoint and reproduction without including credentials.

See [architecture](docs/architecture.md), [design](DESIGN.md) and
[release verification](docs/release-verification.md).
