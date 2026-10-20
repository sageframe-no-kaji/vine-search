"""Use the served application through Chromium, backed by a fresh real database."""

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from vine_search.config import Config
from vine_search.demo import seed_demo
from vine_search.store import Store
from vine_search.web import create_app


@pytest.fixture
def browser_app(tmp_path: Path) -> Iterator[tuple[str, Store]]:
    seed_demo(tmp_path)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = Config(data_dir=tmp_path, collector_secret="e2e-private-test-secret")
    store = Store(config.database)
    server = uvicorn.Server(
        uvicorn.Config(create_app(config, store), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(url + "/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:
        raise AssertionError("Fixture web server did not start")
    try:
        yield url, store
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def goto(page: Page, url: str, route: str, title: str) -> None:
    page.goto(url + "/#" + route)
    expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()


@pytest.mark.browser
def test_real_ui_search_tracker_review_settings_and_interruption(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    errors: list[str] = []
    with sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        goto(page, url, "discover", "Discover")
        page.locator('#search-form input[name="query"]').fill("2.5 GbE")
        page.locator('#search-form button[type="submit"]').click()
        expect(page.locator("#product-results")).to_contain_text("switch")
        expect(page.locator("#results-count")).to_contain_text("1")

        goto(page, url, "trackers", "Interest trackers")
        page.get_by_role("button", name="New tracker", exact=True).click()
        page.locator('[name="name"]').fill("Browser-tested networking")
        page.locator('[name="phrases"]').fill("switch")
        page.get_by_text("Ranking weights and freshness", exact=True).click()
        page.locator('[name="phrase_weight"]').fill("120")
        page.locator('#tracker-form [type="submit"]').click()
        expect(page.locator("#main")).to_contain_text("Browser-tested networking")
        tracker = next(t for t in store.list_trackers() if t["name"] == "Browser-tested networking")
        assert store.list_products(tracker_id=tracker["id"])["items"][0]["score"] >= 120

        goto(page, url, "reviews", "Review progress")
        select = page.locator("[data-review-progress]").first
        review_id = int(select.get_attribute("data-review-progress") or "0")
        observed = next(r for r in store.list_reviews()["items"] if r["id"] == review_id)[
            "observed_status"
        ]
        select.select_option("submitted")
        expect(page.locator("#toast")).to_contain_text("Local progress saved")
        updated = next(r for r in store.list_reviews()["items"] if r["id"] == review_id)
        assert updated["local_progress"] == "submitted"
        assert updated["observed_status"] == observed

        goto(page, url, "settings", "Settings")
        page.locator('[name="collection_interval_minutes"]').fill("30")
        page.get_by_role("button", name="Save settings", exact=True).click()
        expect(page.locator("#toast")).to_contain_text("Settings saved")
        page.reload()
        expect(page.locator('[name="collection_interval_minutes"]')).to_have_value("30")
        assert store.get_settings()["collection_interval_minutes"] == 30

        goto(page, url, "discover", "Discover")
        page.get_by_role("tab", name="Live Amazon search", exact=True).click()
        page.locator('#search-form input[name="query"]').fill("network")
        page.get_by_role("button", name="Search live", exact=True).click()
        expect(page.locator("#live-job")).to_contain_text("Queued")
        page.reload()
        expect(page.locator("#live-job")).to_contain_text("network")
        assert any(j["kind"] == "search" and j["status"] == "queued" for j in store.list_jobs())
        page.locator("#connection-toggle").click()
        page.get_by_role("button", name="Open login browser", exact=True).click()
        expect(page.locator("#toast")).to_contain_text("Collector unavailable")
        assert store.list_products()["total"] >= 1
        assert errors == []
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [360, 390, 768, 1440])
def test_required_widths_have_no_document_overflow(
    browser_app: tuple[str, Store], width: int
) -> None:
    url, _ = browser_app
    with sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        for route, title in [
            ("discover", "Discover"),
            ("trackers", "Interest trackers"),
            ("reviews", "Review progress"),
            ("settings", "Settings"),
            ("activity", "Activity"),
        ]:
            goto(page, url, route, title)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), route
        browser.close()
