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

## Translations

The interface is written in English. `static/i18n.js` translates the rendered
text through catalogs keyed by that English text, so new or changed English
needs no translation work: anything missing from a catalog stays English.
`static/locales/fr.js` holds the French strings (strict JSON; `{n}` matches a
number, other `{name}` placeholders any text within a sentence) and
`static/locales/fr.help.js` the French help topics. Mark listing or user text
with `translate="no"`. In a French browser, `VINE_I18N.missing` in the console
lists untranslated text. `tests/test_i18n.py` flags catalog entries whose
English words no longer exist; update or delete those entries. To add a
language, copy both locale files and load them in `templates/index.html`.

See [architecture](docs/architecture.md), [design](DESIGN.md) and
[release verification](docs/release-verification.md).
