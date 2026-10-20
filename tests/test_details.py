"""Read-only detail lookup contracts, including a real browser with synthetic routes."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Page, async_playwright

from test_amazon import CATALOG, URL, FakePage
from test_collector import make_worker
from vine_search.amazon import (
    CollectionCancelledError,
    Scan,
    lookup_details,
    parse_catalog,
    parse_product_details,
)

PAYLOAD = {"product_id": 1, "asin": "B000000001", "vine_url": URL}
DETAILS = """
<div role="dialog" aria-label="Product Details" id="product-details" hidden>
  <h2>Product Details</h2>
  <a href="/dp/B000000001">Maker&amp;#39;s adapter</a>
  <img src="https://m.media-amazon.com/images/I/synthetic-details.jpg">
  <ul><li>Connects a synthetic device.</li><li>Includes an adapter.</li></ul>
  <label for="color">Color</label><select id="color">
    <option value="">Select a color</option><option value="black">Black</option>
    <option value="blue" selected>Blue</option><option value="red" disabled>Red</option>
  </select>
  <div>Estimated Taxable Value: <span>$9.89</span></div>
  <button onclick="window.requested += 1">Request product</button>
  <button onclick="window.requested += 1">Submit order</button>
</div>
"""


def details_page(*, button: str = "See details", dialog: str = DETAILS) -> str:
    return (
        CATALOG.replace(
            "</div></div></div>",
            f"""<button onclick="window.opened += 1;
              document.getElementById('product-details').hidden=false">{button}</button>
              </div></div></div>""",
        )
        + dialog
        + "<script>window.requested=0; window.opened=0;</script>"
    )


@pytest.fixture
async def browser_page() -> AsyncIterator[Page]:
    async with async_playwright() as tools:
        browser = await tools.chromium.launch()
        page = await browser.new_page()
        await page.route("**/*", lambda route: route.abort())
        yield page
        await browser.close()


def test_dialog_observations_preserve_label_value_variants_and_identity() -> None:
    product = parse_catalog(CATALOG, URL).products[0]
    result = parse_product_details(DETAILS, product, product_id=1)
    assert result["asin"] == "B000000001" and result["product_id"] == 1
    assert result["title"] == "Maker's adapter"
    assert result["state"] == "observed"
    assert result["image_url"] == "https://m.media-amazon.com/images/I/synthetic-details.jpg"
    assert result["description"] == "Connects a synthetic device.\nIncludes an adapter."
    assert result["etv_label"] == "Estimated Taxable Value" and result["etv"] == "$9.89"
    assert result["variants"] == [
        {"name": "Color", "selected": "Blue", "options": ["Black", "Blue"]}
    ]
    assert result["availability"] is None and result["message"] is None
    assert result["observed_at"].endswith("+00:00")


def test_missing_etv_is_unknown_and_unavailable_is_an_observation() -> None:
    product = parse_catalog(CATALOG, URL).products[0]
    html = DETAILS.replace("Estimated Taxable Value:", "Retail price:")
    result = parse_product_details(html, product, product_id=1)
    assert result["etv"] is None and result["etv_label"] is None
    assert result["state"] == "observed"
    assert "did not display" in result["message"]
    result = parse_product_details(html + "<p>Currently unavailable</p>", product, product_id=1)
    assert result["state"] == "unavailable" and result["availability"] == "Currently unavailable"
    with pytest.raises(ValueError, match="no readable product content"):
        parse_product_details("<h2>Product Details</h2>", product, product_id=1)


def test_dialog_identity_requires_matching_asin_or_observed_parent_selection() -> None:
    product = parse_catalog(CATALOG, URL).products[0]
    html = DETAILS.replace("/dp/B000000001", "/dp/B000000002")
    with pytest.raises(ValueError, match="different product"):
        parse_product_details(html, product, product_id=1)
    with pytest.raises(ValueError, match="different product"):
        parse_product_details(html, {**product, "is_parent_asin": True}, product_id=1)
    html = html.replace('value="blue" selected', 'value="B000000002" selected')
    with pytest.raises(ValueError, match="different product"):
        parse_product_details(html, product, product_id=1)
    result = parse_product_details(html, {**product, "is_parent_asin": True}, product_id=1)
    assert result["asin"] == "B000000001"
    assert result["message"] == ("Details show selected variant B000000002 of this parent product.")
    assert result["etv"] == "$9.89"


def test_description_excludes_dropdown_choices_and_untrusted_images() -> None:
    product = parse_catalog(CATALOG, URL).products[0]
    html = (
        DETAILS.replace(
            "https://m.media-amazon.com/images/I/synthetic-details.jpg",
            "https://evil.example/track",
        )
        + '<ul role="listbox"><li role="option">Not a description</li></ul>'
        + '<select aria-label="Size"><option value="">Choose</option>'
        "<option>Small</option></select>"
    )
    result = parse_product_details(html, product, product_id=1)
    assert result["image_url"] == product["image_url"]
    assert "Not a description" not in result["description"]
    assert result["variants"][1] == {"name": "Size", "selected": None, "options": ["Small"]}


@pytest.mark.browser
async def test_lookup_clicks_only_matching_see_details_and_reads_live_selection(
    browser_page: Page,
) -> None:
    html = details_page().replace(
        "document.getElementById('product-details').hidden=false",
        "document.getElementById('product-details').hidden=false;"
        "document.getElementById('color').value='black'",
    )
    await browser_page.route(URL, lambda route: route.fulfill(body=html, content_type="text/html"))
    stages = []

    async def progress(data: dict[str, Any]) -> None:
        stages.append(data["stage"])

    result = await lookup_details(browser_page, PAYLOAD, progress=progress)
    assert result.status == "complete" and result.error is None
    assert result.details and result.details["etv"] == "$9.89"
    assert result.details["variants"][0]["selected"] == "Black"
    assert stages == ["opening_listing", "finding_product", "opening_details", "reading_details"]
    assert await browser_page.evaluate("window.opened") == 1
    assert await browser_page.evaluate("window.requested") == 0
    # Reading the clone must not select a different variant on the actual page.
    assert await browser_page.locator("#color").input_value() == "black"


@pytest.mark.browser
async def test_lookup_waits_for_etv_value_after_dialog_and_label_appear(browser_page: Page) -> None:
    dialog = DETAILS.replace("<span>$9.89</span>", '<span id="delayed-etv"></span>')
    html = details_page(dialog=dialog).replace(
        "document.getElementById('product-details').hidden=false",
        "document.getElementById('product-details').hidden=false;"
        "setTimeout(() => { document.getElementById('delayed-etv').textContent='$9.89'; }, 100)",
    )
    await browser_page.route(URL, lambda route: route.fulfill(body=html, content_type="text/html"))
    result = await lookup_details(browser_page, PAYLOAD)
    assert result.status == "complete" and result.details and result.details["etv"] == "$9.89"
    assert await browser_page.evaluate("window.requested") == 0


@pytest.mark.browser
@pytest.mark.parametrize("semantic", [True, False])
async def test_lookup_selects_one_dialog_inside_nested_popover(
    browser_page: Page, semantic: bool
) -> None:
    dialog = DETAILS if semantic else DETAILS.replace('role="dialog"', 'class="a-popover"')
    html = details_page(dialog=f'<div class="a-popover">{dialog}</div>')
    await browser_page.route(URL, lambda route: route.fulfill(body=html, content_type="text/html"))
    result = await lookup_details(browser_page, PAYLOAD)
    assert result.status == "complete" and result.details and result.details["etv"] == "$9.89"
    assert await browser_page.evaluate("window.requested") == 0


@pytest.mark.browser
async def test_lookup_refuses_modal_for_a_different_product(browser_page: Page) -> None:
    html = details_page(dialog=DETAILS.replace("/dp/B000000001", "/dp/B000000002"))
    await browser_page.route(URL, lambda route: route.fulfill(body=html, content_type="text/html"))
    result = await lookup_details(browser_page, PAYLOAD)
    assert result.status == "failed" and result.details is None
    assert await browser_page.evaluate("window.requested") == 0


@pytest.mark.browser
async def test_lookup_rejects_oversized_details_before_completing_job(browser_page: Page) -> None:
    options = "".join(f'<option value="{index}">Variant {index}</option>' for index in range(101))
    html = details_page(dialog=DETAILS.replace("</select>", options + "</select>"))
    await browser_page.route(URL, lambda route: route.fulfill(body=html, content_type="text/html"))
    result = await lookup_details(browser_page, PAYLOAD)
    assert result.status == "failed" and result.details is None
    assert await browser_page.evaluate("window.requested") == 0


@pytest.mark.browser
@pytest.mark.parametrize("button", ["Request product", "See details and request product"])
async def test_lookup_never_substitutes_an_ordering_or_ambiguous_control(
    browser_page: Page, button: str
) -> None:
    await browser_page.route(
        URL, lambda route: route.fulfill(body=details_page(button=button), content_type="text/html")
    )
    result = await lookup_details(browser_page, PAYLOAD)
    assert result.status == "failed" and "See details control" in str(result.error)
    assert await browser_page.evaluate("window.opened") == 0
    assert await browser_page.evaluate("window.requested") == 0


@pytest.mark.browser
async def test_lookup_reports_stale_item_without_clicking_other_cards(browser_page: Page) -> None:
    html = details_page().replace("B000000001", "B000000002")
    await browser_page.route(URL, lambda route: route.fulfill(body=html, content_type="text/html"))
    result = await lookup_details(browser_page, PAYLOAD)
    assert result.status == "complete" and result.details
    assert result.details["state"] == "unavailable"
    assert result.details["etv"] is None
    assert await browser_page.evaluate("window.opened") == 0


@pytest.mark.browser
async def test_lookup_cancellation_prevents_dialog_action(browser_page: Page) -> None:
    await browser_page.route(
        URL, lambda route: route.fulfill(body=details_page(), content_type="text/html")
    )

    async def cancel(data: dict[str, Any]) -> None:
        if data["stage"] == "opening_details":
            raise CollectionCancelledError()

    result = await lookup_details(browser_page, PAYLOAD, progress=cancel)
    assert result.status == "cancelled" and result.details is None
    assert await browser_page.evaluate("window.opened") == 0


@pytest.mark.parametrize(
    ("html", "status"),
    [("<input id='ap_password'>", "needs_login"), ("Unexpected document", "failed")],
)
async def test_lookup_authentication_and_layout_failures(html: str, status: str) -> None:
    page = FakePage({URL: html})
    assert (await lookup_details(page, PAYLOAD)).status == status


async def test_lookup_rejects_untrusted_snapshot_and_sanitizes_page_errors() -> None:
    page = FakePage({URL: TimeoutError("private session details")})
    assert (
        await lookup_details(page, {**PAYLOAD, "vine_url": "https://evil.example"})
    ).status == "failed"
    assert page.visited == []
    result = await lookup_details(page, PAYLOAD)
    assert result.status == "failed"
    assert result.error == "Product details could not be read (TimeoutError)."


async def test_details_accepts_same_saved_listing_path_with_trailing_slash() -> None:
    url = URL.replace("/vine/vine-items?", "/vine/vine-items/?")
    result = await lookup_details(
        FakePage({url: '<div id="vvp-items-grid">No products available</div>'}),
        {**PAYLOAD, "vine_url": url},
    )
    assert result.status == "complete"
    assert result.details and result.details["state"] == "unavailable"


async def test_collector_details_result_is_serial_and_does_not_write_scan_history(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    worker.store.set_connection("connected")
    seed = worker.store.enqueue_job("rfy")
    worker.store.record_scan(seed["id"], parse_catalog(CATALOG, URL).products)
    product = worker.store.list_products()["items"][0]
    job = worker.store.enqueue_product_details(product["id"])
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed and claimed["id"] == job["id"]
    before_runs = worker.store.list_runs()
    detail = parse_product_details(DETAILS, product, product_id=product["id"])
    lookup = AsyncMock(return_value=Scan("complete", pages=1, details=detail))
    monkeypatch.setattr("vine_search.collector.lookup_details", lookup)
    result = await worker.execute(claimed)
    assert result.details == detail
    assert worker.store.get_job(job["id"])["result"] == detail
    assert worker.store.list_runs() == before_runs
    assert not worker.owner.lock.locked()
