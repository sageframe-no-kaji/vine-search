"""Interface catalogs stay valid, current and applied in a French browser."""

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from test_e2e import browser_app as browser_app
from vine_search.store import Store

PACKAGE = Path(__file__).parents[1] / "src" / "vine_search"
STATIC = PACKAGE / "static"
PLACEHOLDER = re.compile(r"\{\w+\}")


def catalog(language: str) -> dict[str, str]:
    source = (STATIC / "locales" / f"{language}.js").read_text()
    body = source[source.index("= {") + 2 : source.rindex("};") + 1]
    strings: dict[str, str] = json.loads(body)["strings"]
    return strings


WORD = re.compile(r"[A-Za-z\u2019']+")
# Text Amazon shows (observed review statuses) rather than application text.
AMAZON_TEXT = {"Pending approval", "Not approved"}


def english_words() -> set[str]:
    files = [STATIC / name for name in ("app.js", "help.js", "i18n.js")]
    files += [PACKAGE / "templates" / "index.html", *sorted(PACKAGE.glob("*.py"))]
    return {word.lower() for path in files for word in WORD.findall(path.read_text())}


def test_french_catalog_placeholders_match() -> None:
    for source, target in catalog("fr").items():
        assert sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(target)), source


def test_french_catalog_has_no_stale_entries() -> None:
    """Each catalog key only uses words that still occur in the English source.

    Keys are often composed from several source fragments (plurals, f-strings),
    so the check is per word. A failure means English text changed: update or
    delete that entry. Text missing from a catalog simply stays English.
    """
    words = english_words()
    stale = [
        key
        for key in catalog("fr")
        if key not in AMAZON_TEXT
        and any(word.lower() not in words for word in WORD.findall(PLACEHOLDER.sub(" ", key)))
    ]
    assert stale == []


def test_french_help_covers_known_topics() -> None:
    english = set(re.findall(r'id: "(\w+)"', (STATIC / "help.js").read_text()))
    french = set(re.findall(r"^  (\w+): \{", (STATIC / "locales" / "fr.help.js").read_text(), re.M))
    assert french <= english
    assert french


@pytest.mark.browser
def test_french_browser_sees_a_translated_interface(
    browser_app: tuple[str, Store],
) -> None:
    url, _ = browser_app
    errors: list[str] = []
    with sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch()
        page = browser.new_page(locale="fr-FR")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/#discover")
        expect(page.get_by_role("heading", name="Découvrir", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("lang", "fr-FR")
        expect(page).to_have_title("VineSearch · Découvrir")
        expect(page.locator("#results-count")).to_contain_text("produits dans l\u2019historique")
        # Listing titles are data and stay as Amazon showed them.
        expect(page.locator(".product-title").first).not_to_be_empty()
        page.goto(url + "/#help?topic=reviews")
        expect(page.locator("#help-topic-title")).to_have_text(
            "Avis, imports et progression locale"
        )
        page.goto(url + "/#settings")
        page.locator("#language-select").select_option("en")
        expect(page.get_by_role("heading", name="Settings", exact=True)).to_be_visible()
        browser.close()
    assert errors == []
