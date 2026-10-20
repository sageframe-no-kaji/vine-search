"""Browser regressions for local visibility, review photos and collection explanations."""

import base64
from datetime import UTC, datetime

import pytest
from playwright.sync_api import Route, expect, sync_playwright

from test_e2e import browser_app as browser_app
from test_e2e import goto
from vine_search.store import Store


@pytest.mark.browser
def test_local_hide_restore_and_bulk_selection_persist(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    original_count = store.list_products()["total"]
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        goto(page, url, "discover", "Discover")
        first = page.locator("[data-product-id]").first
        product_id = int(first.get_attribute("data-product-id") or "0")
        first.locator("[data-record-visibility]").click()
        expect(page.locator(f'[data-product-id="{product_id}"]')).to_have_count(0)
        assert store.list_products()["total"] == original_count - 1
        page.reload()
        expect(page.locator('[data-visibility-filter="products"]')).to_have_value("visible")
        expect(page.locator(f'[data-product-id="{product_id}"]')).to_have_count(0)

        page.get_by_label("Product visibility", exact=True).select_option("hidden")
        hidden = page.locator(f'[data-product-id="{product_id}"]')
        expect(hidden).to_contain_text("Hidden")
        hidden.locator("[data-record-visibility]").click()
        expect(page.get_by_role("heading", name="No hidden products in this view")).to_be_visible()
        assert store.list_products()["total"] == original_count
        page.get_by_label("Product visibility", exact=True).select_option("visible")
        page.locator('[data-select-displayed="products"]').check()
        expect(page.locator('[data-selection-count="products"]')).to_have_text(
            f"{original_count} selected"
        )
        page.get_by_role("button", name="Hide selected", exact=True).click()
        expect(page.locator("[data-product-id]")).to_have_count(0)
        assert store.list_products(visibility="hidden")["total"] == original_count
        page.get_by_label("Product visibility", exact=True).select_option("hidden")
        page.locator('[data-select-displayed="products"]').check()
        page.get_by_role("button", name="Restore selected", exact=True).click()
        expect(page.locator("[data-product-id]")).to_have_count(0)
        assert store.list_products()["total"] == original_count

        goto(page, url, "reviews", "Review progress")
        original_reviews = store.list_reviews()["items"]
        first_review = page.locator("[data-review-id]").first
        review_id = int(first_review.get_attribute("data-review-id") or "0")
        first_review.locator("[data-record-visibility]").click()
        expect(page.locator(f'[data-review-id="{review_id}"]')).to_have_count(0)
        page.get_by_label("Review visibility", exact=True).select_option("all")
        hidden_review = page.locator(f'[data-review-id="{review_id}"]')
        expect(hidden_review).to_contain_text("Hidden")
        hidden_review.locator("[data-select-record]").check()
        expect(page.get_by_role("button", name="Hide selected", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="Restore selected", exact=True)).to_be_enabled()
        page.locator('[data-select-displayed="reviews"]').check()
        page.get_by_role("button", name="Hide selected", exact=True).click()
        expect(page.locator(".hidden-label")).to_have_count(len(original_reviews))
        assert store.list_reviews()["total"] == 0
        page.get_by_label("Review visibility", exact=True).select_option("hidden")
        page.locator('[data-select-displayed="reviews"]').check()
        page.get_by_role("button", name="Restore selected", exact=True).click()
        expect(page.locator("[data-review-id]")).to_have_count(0)
        restored = store.list_reviews()["items"]
        assert {(r["id"], r["local_progress"], r["observed_status"]) for r in restored} == {
            (r["id"], r["local_progress"], r["observed_status"]) for r in original_reviews
        }
        assert store.list_products()["total"] == original_count
        assert errors == []
        browser.close()


@pytest.mark.browser
def test_review_thumbnail_uses_proxy_and_respects_hidden_images(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    job = store.enqueue_job("reviews")
    store.record_review_scan(
        job["id"],
        [
            {
                "external_id": "synthetic-photo-review",
                "asin": "B012345679",
                "title": "Photo-bearing test product",
                "observed_status": "Awaiting review",
                "image_url": "https://m.media-amazon.com/images/I/synthetic-test.jpg",
            }
        ],
    )
    review = next(
        r for r in store.list_reviews()["items"] if r["external_id"] == "synthetic-photo-review"
    )
    pixel = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/cS8"
        "AAAAASUVORK5CYII="
    )
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page()
        page.route(
            "**/api/reviews/*/image",
            lambda route: route.fulfill(status=200, content_type="image/png", body=pixel),
        )
        goto(page, url, "reviews", "Review progress")
        image = page.locator(f'[data-review-id="{review["id"]}"] .review-image img')
        expect(image).to_have_attribute("src", f"/api/reviews/{review['id']}/image")
        expect(image).to_be_visible()
        store.update_settings({"image_mode": "hidden"})
        page.reload()
        row = page.locator(f'[data-review-id="{review["id"]}"]')
        expect(row).to_contain_text("Images hidden")
        expect(row.locator("img")).to_have_count(0)
        browser.close()


@pytest.mark.browser
def test_bulk_hide_only_changes_displayed_page(browser_app: tuple[str, Store]) -> None:
    url, store = browser_app
    job = store.enqueue_job("afa")
    store.record_scan(
        job["id"],
        [{"asin": f"B0PAGE{i:04d}", "title": f"Synthetic page item {i}"} for i in range(30)],
    )
    total = store.list_products()["total"]
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page()
        goto(page, url, "discover", "Discover")
        expect(page.locator("[data-product-id]")).to_have_count(24)
        displayed = {
            int(value)
            for value in page.locator("[data-product-id]").evaluate_all(
                "nodes => nodes.map(node => node.dataset.productId)"
            )
        }
        page.locator('[data-select-displayed="products"]').check()
        page.get_by_role("button", name="Hide selected", exact=True).click()
        expect(page.locator("#results-count")).to_contain_text(str(total - 24))
        assert {p["id"] for p in store.list_products(visibility="hidden")["items"]} == displayed
        assert store.list_products()["total"] == total - 24
        browser.close()


@pytest.mark.browser
def test_limit_reasons_counts_and_manual_search_explanation(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    for query, reason in [
        ("Page-limited synthetic search", "page_budget"),
        ("Time-limited synthetic search", "runtime_budget"),
        ("Earlier synthetic search", None),
    ]:
        job = store.enqueue_job("search", query=query)
        store.update_job(
            job["id"],
            status="truncated",
            progress={"pages": 5, "observed": 180, "stop_reason": reason},
            result={"count": 180},
            error="Legacy ambiguous budget message",
        )
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 900})
        goto(page, url, "activity", "Activity")
        for query, label in [
            ("Page-limited synthetic search", "Page limit reached"),
            ("Time-limited synthetic search", "Time limit reached"),
            ("Earlier synthetic search", "Search incomplete"),
        ]:
            row = page.locator(".activity-row").filter(
                has=page.get_by_role("heading", name=f"Search: {query}", exact=True)
            )
            expect(row).to_contain_text(label)
            expect(row).to_contain_text("180 items saved from 5 completed pages")
            expect(row).not_to_contain_text("Legacy ambiguous budget")
        goto(page, url, "discover", "Discover")
        page.get_by_role("tab", name="Live Amazon search", exact=True).click()
        expect(page.locator(".search-hint")).to_contain_text("every Additional Items page")
        expect(page.locator(".search-hint")).not_to_contain_text("budget")
        goto(page, url, "settings", "Settings")
        expect(page.locator("#collection-settings")).to_contain_text(
            "All searches continue through every available result page"
        )
        expect(page.locator("#collection-settings")).not_to_contain_text("truncated")
        browser.close()


@pytest.mark.browser
def test_history_queue_filter_cannot_hide_a_live_search(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    products = [
        {
            "asin": "B0USBTEST1",
            "title": "Synthetic USB adapter",
            "product_url": "https://www.amazon.com/dp/B0USBTEST1",
            "vine_url": "https://www.amazon.com/vine/vine-items?search=USB",
        },
        {"asin": "B0USBTEST2", "title": "Synthetic USB cable"},
    ]
    earlier = store.enqueue_job("search", query="Another synthetic query")
    store.record_scan(earlier["id"], products)
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        goto(page, url, "discover", "Discover")
        page.get_by_role("button", name="Available for all", exact=True).click()
        expect(page.locator('[data-source="afa"]')).to_have_attribute("aria-pressed", "true")
        page.get_by_role("tab", name="Live Amazon search", exact=True).click()
        expect(page.locator("[data-source]")).to_have_count(4)
        expect(page.locator('[data-source="afa"]')).not_to_be_visible()
        expect(page.locator("#product-results")).to_contain_text("Additional Items")
        page.locator('#search-form input[name="query"]').fill("USB live scope regression")
        page.get_by_role("button", name="Search live", exact=True).click()
        expect(page.locator("#live-job")).to_contain_text("Queued")
        job = next(j for j in store.list_jobs() if j["query"] == "USB live scope regression")
        assert job["payload"]["exhaustive"] is True
        store.record_scan(
            job["id"],
            products,
            pages=2,
        )
        expect(page.locator("#live-job")).to_contain_text("Complete", timeout=12000)
        expect(page.locator("[data-product-id]")).to_have_count(2)
        expect(page.locator("#results-count")).to_contain_text("2 of 2 collected items")
        adapter = page.locator(".product-card").filter(
            has=page.get_by_role("link", name="Synthetic USB adapter", exact=True)
        )
        expect(adapter.locator(".product-title a")).to_have_attribute(
            "href", "https://www.amazon.com/dp/B0USBTEST1"
        )
        expect(adapter.get_by_role("link", name="Open product", exact=True)).to_have_attribute(
            "href", "https://www.amazon.com/dp/B0USBTEST1"
        )
        expect(adapter.locator(".product-source")).to_have_text("Additional items")
        page.locator("#score-filter").fill("1000")
        page.locator("#score-filter").blur()
        expect(page.locator("#results-count")).to_contain_text("0 of 2 collected items")
        expect(page.get_by_role("heading", name="No products match these filters")).to_be_visible()
        page.get_by_role("button", name="Clear filters", exact=True).click()
        expect(page.locator("[data-product-id]")).to_have_count(2)
        expect(page.locator("#score-filter")).to_have_value("")
        browser.close()


@pytest.mark.browser
def test_product_details_are_read_only_durable_and_null_etv_is_unavailable(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        goto(page, url, "discover", "Discover")
        page.get_by_role("button", name="See details", exact=True).first.click()
        dialog = page.get_by_role("dialog", name="Product details", exact=True)
        expect(dialog).to_contain_text("Waiting for the Amazon browser")
        job = next(j for j in store.list_jobs() if j["kind"] == "details")
        result = {
            "product_id": job["payload"]["product_id"],
            "asin": job["payload"]["asin"],
            "state": "observed",
            "title": "Synthetic observed details",
            "image_url": "",
            "description": "A description <script>window.UNSAFE_DETAIL=true</script>",
            "etv": "$9.89",
            "etv_label": "Estimated Taxable Value",
            "variants": [{"name": "Color", "selected": "Gray", "options": ["Gray", "Blue"]}],
            "availability": None,
            "observed_at": datetime.now(UTC).isoformat(),
            "message": None,
        }
        store.update_job(job["id"], status="complete", result=result)
        expect(dialog).to_contain_text("$9.89", timeout=12000)
        expect(dialog).to_contain_text("Observed options: Gray")
        expect(dialog.locator(".detail-description")).to_contain_text(
            "<script>window.UNSAFE_DETAIL=true</script>"
        )
        assert page.evaluate("typeof window.UNSAFE_DETAIL") == "undefined"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        dialog.get_by_role("button", name="Close", exact=True).click()
        assert len([j for j in store.list_jobs() if j["kind"] == "details"]) == 1

        store.update_job(job["id"], result={**result, "etv": None})
        goto(page, url, "activity", "Activity")
        page.get_by_role("button", name="View details", exact=True).click()
        expect(dialog.locator(".detail-etv dd")).to_have_text("Unavailable")
        expect(dialog).not_to_contain_text("$0")
        assert len([j for j in store.list_jobs() if j["kind"] == "details"]) == 1
        dialog.get_by_role("button", name="Refresh details", exact=True).click()
        expect(dialog).to_contain_text("Waiting for the Amazon browser")
        dialog.get_by_role("button", name="Cancel request", exact=True).click()
        expect(dialog).to_contain_text("Details request cancelled")
        assert store.list_jobs()[0]["status"] == "cancelled"
        assert errors == []
        browser.close()


@pytest.mark.browser
def test_tracker_instructions_explain_rules_without_saving_example(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    initial = store.list_trackers()
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page()
        goto(page, url, "trackers", "Interest trackers")
        editor = page.locator("#tracker-editor")
        expect(editor).to_contain_text("A label only; this does not search or filter titles")
        expect(editor).to_contain_text("case does not matter")
        expect(editor).to_contain_text("Any matching exclusion removes the product")
        expect(editor).to_contain_text("not a percentage or confidence estimate")
        expect(editor).to_contain_text("Only products seen within the last 168 hours qualify")
        page.get_by_text("Worked example: network racks", exact=True).click()
        expect(page.locator(".tracker-example")).to_contain_text("server rack")
        expect(page.locator(".tracker-example")).to_contain_text("wine rack")
        expect(page.locator('#tracker-form [name="name"]')).to_have_value("")
        expect(page.locator('#tracker-form [name="query"]')).to_have_value("")
        assert store.list_trackers() == initial
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("confirmation_failure", ["missing", "request"])
def test_tracker_save_keeps_known_id_and_draft_until_read_confirmation(
    browser_app: tuple[str, Store], confirmation_failure: str
) -> None:
    url, store = browser_app
    original = store.list_trackers()
    interception = {"block_read": False, "posts": 0}
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        goto(page, url, "trackers", "Interest trackers")

        def intercept(route: Route) -> None:
            if route.request.method == "POST":
                interception["posts"] += 1
                interception["block_read"] = True
                assert "page_budget" not in route.request.post_data_json
                route.continue_()
            elif route.request.method == "GET" and interception["block_read"]:
                if confirmation_failure == "missing":
                    route.fulfill(json=original)
                else:
                    route.fulfill(status=503, json={"detail": "Synthetic list refresh failed"})
            else:
                route.continue_()

        page.route("**/api/trackers", intercept)
        page.locator('#tracker-form [name="name"]').fill("Read-confirmed rack tracker")
        page.locator('#tracker-form [name="query"]').fill("network rack")
        page.locator('#tracker-form [name="phrases"]').fill('10 inch rack\n10-inch rack\n10" rack')
        page.get_by_role("button", name="Save tracker", exact=True).click()
        expect(page.locator("#tracker-save-status")).to_contain_text(
            "confirmation is still pending"
        )
        expect(page.locator('#tracker-form [name="name"]')).to_have_value(
            "Read-confirmed rack tracker"
        )
        saved = next(t for t in store.list_trackers() if t["name"] == "Read-confirmed rack tracker")
        expect(page.locator("#tracker-form")).to_have_attribute("data-id", str(saved["id"]))
        assert interception["posts"] == 1
        interception["block_read"] = False
        page.get_by_role("button", name="Retry list refresh", exact=True).click()
        expect(page.locator("#tracker-save-status")).to_contain_text(
            "Confirmed in the saved tracker list"
        )
        expect(page.locator("#editor-heading")).to_have_text("Edit tracker")
        expect(page.locator('#tracker-form [name="name"]')).to_have_value(
            "Read-confirmed rack tracker"
        )
        assert interception["posts"] == 1
        assert len(store.list_trackers()) == len(original) + 1
        page.reload()
        expect(page.locator(".tracker-list")).to_contain_text("Read-confirmed rack tracker")
        assert store.get_tracker(saved["id"])["phrases"] == [
            "10 inch rack",
            "10-inch rack",
            '10" rack',
        ]
        browser.close()


@pytest.mark.browser
def test_tracker_inflight_save_survives_navigation_without_duplicate_create(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    initial_count = len(store.list_trackers())
    held: list[Route] = []
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page()
        goto(page, url, "trackers", "Interest trackers")

        def hold_save(route: Route) -> None:
            if route.request.method == "POST":
                held.append(route)
            else:
                route.continue_()

        page.route("**/api/trackers", hold_save)
        page.locator('#tracker-form [name="name"]').fill("One in-flight tracker")
        page.get_by_role("button", name="Save tracker", exact=True).click()
        expect(page.get_by_role("button", name="Save tracker", exact=True)).to_be_disabled()
        page.locator('[data-nav="reviews"]').click()
        expect(page.get_by_role("heading", name="Review progress", exact=True)).to_be_visible()
        page.locator('[data-nav="trackers"]').click()
        expect(page.locator('#tracker-form [name="name"]')).to_have_value("One in-flight tracker")
        expect(page.get_by_role("button", name="Save tracker", exact=True)).to_be_disabled()
        expect(page.locator("#tracker-save-status")).to_contain_text("Saving this tracker")
        # A submitted form must also respect the lock, not just its disabled button.
        page.locator("#tracker-form").evaluate("form => form.requestSubmit()")
        assert len(held) == 1
        page.locator('#tracker-form [name="phrases"]').fill("later unsaved edit")
        held[0].continue_()
        expect(page.locator("#tracker-save-status")).to_contain_text(
            "Confirmed in the saved tracker list"
        )
        expect(page.locator("#tracker-save-status")).to_contain_text(
            "later edits are still unsaved"
        )
        expect(page.locator('#tracker-form [name="phrases"]')).to_have_value("later unsaved edit")
        expect(page.get_by_role("button", name="Save tracker", exact=True)).to_be_enabled()
        assert len(held) == 1
        assert len(store.list_trackers()) == initial_count + 1
        page.get_by_role("button", name="Save tracker", exact=True).click()
        expect(page.locator("#tracker-save-status")).to_contain_text(
            "Confirmed in the saved tracker list"
        )
        assert len(held) == 1
        assert len(store.list_trackers()) == initial_count + 1
        saved = next(t for t in store.list_trackers() if t["name"] == "One in-flight tracker")
        assert saved["phrases"] == ["later unsaved edit"]
        browser.close()


@pytest.mark.browser
def test_tracker_validation_request_failure_and_navigation_preserve_draft(
    browser_app: tuple[str, Store],
) -> None:
    url, store = browser_app
    original_count = len(store.list_trackers())
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        goto(page, url, "trackers", "Interest trackers")
        page.locator('#tracker-form [name="name"]').fill("Unsaved rack draft")
        page.locator('#tracker-form [name="phrases"]').fill("10-inch rack")
        page.get_by_text("Ranking weights and freshness", exact=True).click()
        page.locator('[name="phrase_weight"]').fill("")
        page.get_by_text("Ranking weights and freshness", exact=True).click()
        page.get_by_role("button", name="Save tracker", exact=True).click()
        expect(page.locator("#tracker-form .inline-disclosure")).to_have_attribute("open", "")
        expect(page.locator('[name="phrase_weight"]')).to_be_focused()
        expect(page.locator("#tracker-form-error")).to_contain_text("Per matching phrase")
        assert len(store.list_trackers()) == original_count
        page.locator('[name="phrase_weight"]').fill("30")
        page.route(
            "**/api/trackers",
            lambda route: (
                route.fulfill(status=503, json={"detail": "Synthetic tracker save unavailable"})
                if route.request.method == "POST"
                else route.continue_()
            ),
        )
        page.get_by_role("button", name="Save tracker", exact=True).click()
        expect(page.locator("#tracker-form-error")).to_contain_text(
            "Synthetic tracker save unavailable"
        )
        expect(page.locator('#tracker-form [name="name"]')).to_have_value("Unsaved rack draft")
        page.locator('[data-nav="reviews"]').click()
        expect(page.get_by_role("heading", name="Review progress", exact=True)).to_be_visible()
        page.locator('[data-nav="trackers"]').click()
        expect(page.locator('#tracker-form [name="name"]')).to_have_value("Unsaved rack draft")
        expect(page.locator('#tracker-form [name="phrases"]')).to_have_value("10-inch rack")
        with page.context.expect_page() as popup:
            page.get_by_role("link", name="Read tracker help", exact=True).click()
        help_page = popup.value
        expect(
            help_page.get_by_role("heading", name="Set up a tracker", exact=True)
        ).to_be_visible()
        help_page.close()
        expect(page.locator('#tracker-form [name="name"]')).to_have_value("Unsaved rack draft")
        assert errors == []
        assert len(store.list_trackers()) == original_count
        browser.close()


@pytest.mark.browser
def test_help_topics_links_and_versioned_assets_are_read_only(
    browser_app: tuple[str, Store],
) -> None:
    url, _ = browser_app
    with sync_playwright() as tools:
        browser = tools.chromium.launch()
        page = browser.new_page(viewport={"width": 360, "height": 800})
        writes: list[str] = []
        page.on(
            "request",
            lambda request: (
                writes.append(request.url) if request.method not in {"GET", "HEAD"} else None
            ),
        )
        page.goto(url + "/help")
        expect(page.get_by_role("heading", name="Help", exact=True)).to_be_visible()
        for asset in ["app.js", "help.js", "app.css"]:
            attribute = "href" if asset.endswith(".css") else "src"
            expect(page.locator(f'[{attribute}^="/static/{asset}"]')).to_have_attribute(
                attribute,
                f"/static/{asset}?v=" + page.request.get(url + "/health").json()["version"],
            )
        topics = page.evaluate("window.VINE_HELP_TOPICS.map(({id,title}) => ({id,title}))")
        valid_topics = {topic["id"] for topic in topics}
        assert len(topics) >= 12
        for topic in topics:
            page.locator("#help-topic").select_option(topic["id"])
            expect(page.locator("#help-topic-title")).to_have_text(topic["title"])
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            links = page.locator(".help-content a").evaluate_all(
                "nodes => nodes.map(node => node.getAttribute('href'))"
            )
            assert all(
                link.split("topic=")[1] in valid_topics
                for link in links
                if link.startswith("#help?topic=")
            )
        page.locator("#help-topic").select_option("schedules")
        expect(page.locator(".help-content")).to_contain_text("Every search")
        expect(page.locator(".help-content")).to_contain_text("no page cap or total time limit")
        assert writes == []
        browser.close()
