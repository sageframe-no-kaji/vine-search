from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from vine_search import amazon
from vine_search.amazon import (
    ORIGIN,
    CollectionCancelledError,
    amazon_url,
    collect,
    image_url,
    load_page,
    parse_catalog,
    parse_reviews,
    queue_url,
    review_sections,
    signed_in_vine,
)

URL = queue_url("rfy")
REVIEW_URL = f"{ORIGIN}/vine/vine-reviews"
CATALOG = """
<div id="vvp-items-grid-container">1-1 of 1 results
<div id="vvp-items-grid"><div class="vvp-item-tile">
 <input data-asin="B000000001">
 <div class="vvp-item-product-title-container">
 <span class="a-truncate-full">Small Network Switch &amp; Adapter</span></div>
 <img src="https://m.media-amazon.com/images/I/synthetic.jpg">
</div></div></div>
"""
REVIEWS = """
<a href="/vine/vine-reviews?review-type=pending_review">Awaiting Review</a>
<a href="/vine/vine-reviews?review-type=completed">Reviewed (1)</a>
<table id="vvp-reviews-table"><thead><tr><th>Item</th><th>Order date</th>
<th>Status</th></tr></thead><tbody>
<tr data-order-id="synthetic-order"><td class="vvp-reviews-table--text-col">
<a href="/dp/B000000001">Network switch</a>
<span class="vvp-reviews-table--variation">Black</span></td>
<td class="vvp-reviews-table--date-col">October 15, 2026</td><td>Pending approval</td>
<td><a href="/review/create-review?asin=B000000001&amp;orderID=synthetic-order">Review item</a></td>
</tr></tbody></table>
"""


def next_link(url: str) -> str:
    return f'<ul class="a-pagination"><li class="a-last"><a href="{url}">Next</a></li></ul>'


class FakePage:
    def __init__(self, documents: dict[str, str | Exception], *, redirect: str = "") -> None:
        self.documents = documents
        self.url = ""
        self.redirect = redirect
        self.visited: list[str] = []
        self.fail_wait = False

    async def goto(self, url: str, **_: Any) -> None:
        self.visited.append(url)
        self.url = self.redirect or url
        value = self.documents.get(url, "")
        if isinstance(value, Exception):
            raise value

    def locator(self, _: str) -> FakePage:
        return self

    @property
    def first(self) -> FakePage:
        return self

    async def wait_for(self, **_: Any) -> None:
        if self.fail_wait:
            raise TimeoutError()

    async def content(self) -> str:
        value = self.documents.get(self.url, "")
        return value if isinstance(value, str) else ""


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/vine/vine-items",
        "https://www.amazon.com.evil.example/vine/vine-items",
        "http://www.amazon.com/vine/vine-items",
        "https://www.amazon.com:444/vine/vine-items",
        "https://user@www.amazon.com/vine/vine-items",
        "https://www.amazon.com:invalid/vine/vine-items",
    ],
)
def test_navigation_rejects_non_amazon_origin(url: str) -> None:
    assert amazon_url(url) is None
    assert not signed_in_vine(CATALOG, url)


def test_product_identity_unknown_category_and_safe_links() -> None:
    parsed = parse_catalog(CATALOG, URL)
    assert parsed.state == "ok"
    assert parsed.advertised_count == 1
    assert parsed.products[0] == {
        "asin": "B000000001",
        "marketplace": "amazon.com",
        "title": "Small Network Switch & Adapter",
        "image_url": "https://m.media-amazon.com/images/I/synthetic.jpg",
        "product_url": "https://www.amazon.com/dp/B000000001",
        "vine_url": URL,
        "category": None,
    }
    assert signed_in_vine(CATALOG, URL)
    assert not signed_in_vine(CATALOG, f"{ORIGIN}/ap/signin?return_to=/vine/")


@pytest.mark.parametrize(
    ("html", "url", "state"),
    [
        ("<input id='ap_password'>", f"{ORIGIN}/ap/signin", "needs_login"),
        ("<input id='ap_email'>", URL, "needs_login"),
        ("<input id='captchacharacters'>", URL, "challenge"),
        ("<p>Solve this puzzle</p>", URL, "challenge"),
        ("<div id='cvf-page-content'></div>", URL, "challenge"),
        ("<p>Oops</p>", URL, "layout_changed"),
        ("<div id='vvp-items-grid'></div>", URL, "layout_changed"),
        ("<div id='vvp-items-grid'>No items available</div>", URL, "empty"),
        (CATALOG, "https://evil.example/", "invalid_host"),
        (CATALOG, f"{ORIGIN}/other", "invalid_host"),
    ],
)
def test_empty_login_challenge_layout_are_not_confused(html: str, url: str, state: str) -> None:
    assert parse_catalog(html, url).state == state
    if state in {"needs_login", "challenge"}:
        assert not signed_in_vine(html, url)


def test_broken_tile_cannot_manufacture_complete_scan() -> None:
    broken = CATALOG.replace('data-asin="B000000001"', 'data-asin="invalid"')
    assert parse_catalog(broken, URL).state == "layout_changed"
    assert (
        parse_catalog(CATALOG.replace("Small Network Switch &amp; Adapter", ""), URL).state
        == "layout_changed"
    )


def test_product_link_fallback_and_category_are_observed() -> None:
    html = CATALOG.replace('data-asin="B000000001"', "").replace(
        '<div class="vvp-item-tile">',
        '<div class="vvp-item-tile" data-category="Electronics"><a href="/dp/B000000001">Item</a>',
    )
    result = parse_catalog(html, URL)
    assert result.products[0]["asin"] == "B000000001"
    assert result.products[0]["category"] == "Electronics"
    rec = html.replace('href="/dp/B000000001"', 'data-recommendation-id="en#B000000002#42"')
    assert parse_catalog(rec, URL).products[0]["asin"] == "B000000002"


@pytest.mark.parametrize(
    "next_url",
    ["https://evil.example/", "/vine/vine-reviews", "/vine/vine-items?queue=encore"],
)
def test_pagination_rejects_scope_changes(next_url: str) -> None:
    result = parse_catalog(CATALOG + next_link(next_url), URL)
    assert result.state == "layout_changed"
    assert len(result.products) == 1


def test_search_scope_is_encoded_and_required() -> None:
    assert queue_url("search", "network & tools") == (
        "https://www.amazon.com/vine/vine-items?queue=encore&search=network+%26+tools"
    )
    assert "last_chance" in queue_url("afa")
    with pytest.raises(ValueError):
        queue_url("orders")
    with pytest.raises(ValueError):
        queue_url("search")


def test_review_preserves_actual_status_order_identity_and_section_source() -> None:
    result = parse_reviews(REVIEWS, REVIEW_URL, "reviewed")
    record = result.reviews[0]
    assert record["order_date"] == "2026-10-15"
    assert record["external_id"] == "synthetic-order"
    assert record["observed_status"] == "Pending approval"
    assert record["variant"] == "Black"
    assert record["source"] == "amazon:reviewed"
    assert "orderID=synthetic-order" in record["review_url"]
    assert review_sections(REVIEWS, REVIEW_URL) == {
        "awaiting_review": f"{REVIEW_URL}?review-type=pending_review",
        "reviewed": f"{REVIEW_URL}?review-type=completed",
    }


def test_review_prefers_full_title_decodes_entities_and_keeps_product_thumbnail() -> None:
    title = (
        '<span class="a-truncate"><span class="a-truncate-full">'
        "Maker&amp;#39;s switch &amp;amp; adapter"
        '</span><span class="a-truncate-cut" aria-hidden="true">Maker&amp;#39;s swi…</span></span>'
    )
    html = REVIEWS.replace("Network switch</a>", title + "</a>").replace(
        '<td class="vvp-reviews-table--text-col">',
        '<td><a href="/dp/B000000001">'
        '<img src="https://m.media-amazon.com/images/I/synthetic-review.jpg">'
        '</a></td><td class="vvp-reviews-table--text-col">',
    )
    record = parse_reviews(html, REVIEW_URL, "awaiting_review").reviews[0]
    assert record["title"] == "Maker's switch & adapter"
    assert record["image_url"] == "https://m.media-amazon.com/images/I/synthetic-review.jpg"
    assert record["asin"] == "B000000001"
    assert record["external_id"] == "synthetic-order"


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ('<img src="https://evil.example/tracker.jpg">', None),
        ('<img src="data:image/png;base64,AA==">', None),
        (
            '<img src="data:image/png;base64,AA==" '
            'data-src="https://m.media-amazon.com/images/I/synthetic-review.jpg">',
            "https://m.media-amazon.com/images/I/synthetic-review.jpg",
        ),
        ("", None),
    ],
)
def test_review_images_require_an_allowed_source(image: str, expected: str | None) -> None:
    html = REVIEWS.replace("Network switch</a>", "Network switch</a>" + image)
    assert parse_reviews(html, REVIEW_URL, "reviewed").reviews[0]["image_url"] == expected


def test_catalog_decodes_encoded_title_without_duplicate_short_text() -> None:
    html = CATALOG.replace(
        "Small Network Switch &amp; Adapter",
        "Maker&amp;#39;s switch &amp;amp; adapter",
    ).replace("</span></div>", '</span><span class="a-truncate-cut">Maker…</span></div>')
    assert parse_catalog(html, URL).products[0]["title"] == "Maker's switch & adapter"


def test_review_unknown_and_awaiting_are_distinct() -> None:
    html = REVIEWS.replace("<th>Status</th>", "<th>Unknown</th>")
    assert parse_reviews(html, REVIEW_URL, "reviewed").reviews[0]["observed_status"] == "unknown"
    assert (
        parse_reviews(html, REVIEW_URL, "awaiting_review").reviews[0]["observed_status"]
        == "Awaiting Review"
    )
    assert parse_reviews("<input id='ap_email'>", REVIEW_URL, "reviewed").state == "needs_login"
    assert parse_reviews("", REVIEW_URL, "reviewed").state == "layout_changed"
    assert (
        parse_reviews(
            "<table id='vvp-reviews-table'>No reviews</table>", REVIEW_URL, "reviewed"
        ).state
        == "empty"
    )
    assert (
        parse_reviews("<table id='vvp-reviews-table'></table>", REVIEW_URL, "reviewed").state
        == "layout_changed"
    )


def test_review_date_fallback_raw_status_and_unsafe_links() -> None:
    html = (
        REVIEWS.replace('class="vvp-reviews-table--date-col"', "")
        .replace("October 15, 2026", "10/15/2026")
        .replace("<td>Pending approval</td>", '<td class="vvp-review-status">Rejected</td>')
        .replace('data-order-id="synthetic-order"', "")
    )
    record = parse_reviews(html, REVIEW_URL, "reviewed").reviews[0]
    assert record["order_date"] == "2026-10-15"
    assert record["observed_status"] == "Rejected"
    assert record["external_id"] == "synthetic-order"
    html += next_link("/vine/vine-items?queue=potluck")
    assert parse_reviews(html, REVIEW_URL, "reviewed").state == "layout_changed"


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("https://m.media-amazon.com/image.jpg", True),
        ("https://images-na.ssl-images-amazon.com/image.jpg", True),
        ("https://evil.example/image.jpg", False),
        ("javascript:alert(1)", False),
        ("https://media-amazon.com.evil.example/image.jpg", False),
    ],
)
def test_image_host_allowlist(value: str, valid: bool) -> None:
    assert bool(image_url(value)) is valid


async def test_paginated_run_and_configured_truncation() -> None:
    second = URL + "&page=2"
    page = FakePage({URL: CATALOG + next_link(second), second: CATALOG})
    result = await collect(page, "rfy", page_budget=1)
    assert result.status == "truncated" and result.pages == 1
    assert result.stop_reason == "page_budget"
    assert result.error == (
        "Page limit reached (1 page). Retained 1 item from 1 completed page; more pages remain."
    )
    assert result.section_pages == {"rfy": 1}
    result = await collect(page, "rfy", page_budget=2)
    assert result.status == "complete" and result.pages == 2
    assert len(result.products) == 2
    assert result.advertised_count == 1
    assert result.stop_reason is None
    assert result.error is None


async def test_partial_failed_login_and_loop_detection() -> None:
    second = URL + "&page=2"
    page = FakePage({URL: CATALOG + next_link(second), second: TimeoutError()})
    result = await collect(page, "rfy")
    assert result.status == "partial" and result.pages == 1
    assert len(result.products) == 1
    assert result.stop_reason is None
    assert result.error == "Page load failed (TimeoutError); no absence inferred."
    page.documents[URL] = TimeoutError()
    assert (await collect(page, "rfy")).status == "failed"
    page.documents[URL] = "<input id='captchacharacters'>"
    assert (await collect(page, "rfy")).status == "needs_login"
    page.documents[URL] = CATALOG + next_link(URL)
    assert (await collect(page, "rfy")).status == "partial"


async def test_cancel_retains_captured_observations() -> None:
    async def cancel(_: dict[str, Any]) -> None:
        raise CollectionCancelledError()

    result = await collect(FakePage({URL: CATALOG}), "rfy", progress=cancel)
    assert result.status == "cancelled" and len(result.products) == 1


async def test_review_scan_traverses_both_observed_sections() -> None:
    sections = review_sections(REVIEWS, REVIEW_URL)
    page = FakePage({REVIEW_URL: REVIEWS, **dict.fromkeys(sections.values(), REVIEWS)})
    result = await collect(page, "reviews")
    assert result.status == "complete" and result.pages == 2
    assert {r["source"] for r in result.reviews} == {"amazon:awaiting_review", "amazon:reviewed"}
    result = await collect(page, "reviews", page_budget=1)
    assert result.status == "truncated"
    assert result.section_pages == {"awaiting_review": 1, "reviewed": 0}
    page.documents[REVIEW_URL] = "<input id='ap_password'>"
    assert (await collect(page, "reviews")).status == "needs_login"
    page.documents[REVIEW_URL] = "<table id='vvp-reviews-table'>No reviews</table>"
    assert (await collect(page, "reviews")).status == "failed"


async def test_review_budget_interleaves_sections_and_finishes_only_when_both_end() -> None:
    sections = review_sections(REVIEWS, REVIEW_URL)
    documents = {REVIEW_URL: REVIEWS}
    expected_visits = [REVIEW_URL]
    for index in range(1, 4):
        for section, initial in sections.items():
            url = initial if index == 1 else initial + f"&page={index}"
            status = "Awaiting Review" if section == "awaiting_review" else "Published"
            document = REVIEWS.replace("Pending approval", status)
            document = document.replace("synthetic-order", f"synthetic-{section}-{index}")
            documents[url] = document + (
                next_link(initial + f"&page={index + 1}") if index < 3 else ""
            )
            expected_visits.append(url)
    page = FakePage(documents)
    result = await collect(page, "reviews", page_budget=5)
    assert page.visited == expected_visits[:6]
    assert result.status == "truncated" and result.stop_reason == "page_budget"
    assert result.pages == 5 and len(result.reviews) == 5
    assert result.section_pages == {"awaiting_review": 3, "reviewed": 2}
    assert {r["observed_status"] for r in result.reviews} == {"Awaiting Review", "Published"}
    complete = await collect(FakePage(documents), "reviews", page_budget=6)
    assert complete.status == "complete" and complete.stop_reason is None
    assert complete.section_pages == {"awaiting_review": 3, "reviewed": 3}
    assert len(complete.reviews) == 6


async def test_finished_review_section_releases_remaining_budget_without_inventing_status() -> None:
    sections = review_sections(REVIEWS, REVIEW_URL)
    awaiting, reviewed = sections["awaiting_review"], sections["reviewed"]
    following = reviewed + "&page=2"
    documents = {
        REVIEW_URL: REVIEWS,
        awaiting: '<table id="vvp-reviews-table">No reviews</table>',
        reviewed: REVIEWS.replace("<th>Status</th>", "<th>Other</th>") + next_link(following),
        following: REVIEWS.replace("<th>Status</th>", "<th>Other</th>"),
    }
    result = await collect(FakePage(documents), "reviews", page_budget=3)
    assert result.status == "complete" and result.pages == 3
    assert result.section_pages == {"awaiting_review": 1, "reviewed": 2}
    assert {r["observed_status"] for r in result.reviews} == {"unknown"}


async def test_review_failure_retains_first_section_and_does_not_claim_completeness() -> None:
    sections = review_sections(REVIEWS, REVIEW_URL)
    awaiting, reviewed = sections["awaiting_review"], sections["reviewed"]
    following = awaiting + "&page=2"
    page = FakePage(
        {
            REVIEW_URL: REVIEWS,
            awaiting: REVIEWS + next_link(following),
            reviewed: PlaywrightTimeoutError("private page details"),
            following: REVIEWS,
        }
    )
    result = await collect(page, "reviews")
    assert result.status == "partial" and result.stop_reason is None
    assert result.section_pages == {"awaiting_review": 1, "reviewed": 0}
    assert page.visited == [REVIEW_URL, awaiting, reviewed]
    assert len(result.reviews) == 1
    assert result.error == "Page load failed (TimeoutError); no absence inferred."


@pytest.mark.parametrize("phase", ["catalog", "next_page", "review_navigation", "review_section"])
async def test_runtime_deadline_cancels_waiting_page_and_retains_completed_pages(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    clock_calls = 0

    def monotonic() -> float:
        nonlocal clock_calls
        clock_calls += 1
        # Advance only the collector's clock, leaving the event loop clock real.
        # Its actual timeout then cancels the stalled page after 10 milliseconds.
        return 0 if clock_calls == 1 else 9.99

    monkeypatch.setattr(amazon, "time", SimpleNamespace(monotonic=monotonic))
    sections = review_sections(REVIEWS, REVIEW_URL)
    second = URL + "&page=2"
    stalled = {
        "catalog": URL,
        "next_page": second,
        "review_navigation": REVIEW_URL,
        "review_section": sections["awaiting_review"],
    }[phase]
    cancelled = asyncio.Event()

    class StalledPage(FakePage):
        async def goto(self, url: str, **kwargs: Any) -> None:
            if url == stalled:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            await super().goto(url, **kwargs)

    page = StalledPage(
        {
            URL: CATALOG + next_link(second),
            REVIEW_URL: REVIEWS,
            **dict.fromkeys(sections.values(), REVIEWS),
        }
    )
    result = await collect(
        page, "reviews" if phase.startswith("review") else "rfy", runtime_budget=10
    )
    expected_pages = 1 if phase == "next_page" else 0
    assert cancelled.is_set()
    assert result.status == "truncated" and result.stop_reason == "runtime_budget"
    assert result.pages == expected_pages
    assert len(result.products) == expected_pages
    retained = (
        "1 item from 1 completed page" if expected_pages else "0 items from 0 completed pages"
    )
    assert (
        result.error
        == f"Time limit reached (10 seconds). Retained {retained}; collection is incomplete."
    )


async def test_runtime_expiry_between_pages_does_not_start_another_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(amazon, "time", SimpleNamespace(monotonic=lambda: clock.now))
    second = URL + "&page=2"
    page = FakePage({URL: CATALOG + next_link(second), second: CATALOG})

    async def progress(details: dict[str, Any]) -> None:
        assert details["section_pages"] == {"rfy": 1}
        clock.now = 10

    result = await collect(page, "rfy", runtime_budget=10, progress=progress)
    assert result.status == "truncated" and result.stop_reason == "runtime_budget"
    assert result.elapsed_seconds == 10
    assert result.pages == 1 and len(result.products) == 1
    assert page.visited == [URL]


async def test_exhaustive_search_traverses_every_page_past_both_configured_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(amazon, "time", SimpleNamespace(monotonic=lambda: clock.now))
    initial = queue_url("search", "adapter")
    documents: dict[str, str | Exception] = {}
    # Exceed even the old maximum configurable page limit, with a synthetic clock
    # beyond the configured runtime after the first page. Every link is observed.
    urls = [initial] + [initial + f"&page={index}" for index in range(2, 103)]
    for index, url in enumerate(urls):
        documents[url] = CATALOG.replace("B000000001", f"B{index:09d}") + (
            next_link(urls[index + 1]) if index + 1 < len(urls) else ""
        )
    progress_pages = []

    async def progress(details: dict[str, Any]) -> None:
        assert details["exhaustive"] is True
        progress_pages.append(details["pages"])
        clock.now += 121

    page = FakePage(documents)
    result = await collect(
        page,
        "search",
        "adapter",
        page_budget=1,
        runtime_budget=10,
        exhaustive=False,  # Legacy callers cannot turn exhaustive search off.
        progress=progress,
    )
    assert result.status == "complete" and result.stop_reason is None
    assert result.exhaustive is True and result.elapsed_seconds == 102 * 121
    assert result.pages == len(result.products) == 102
    assert page.visited == urls and progress_pages == list(range(1, 103))


@pytest.mark.parametrize("failure", ["cancel", "timeout", "repeated", "challenge"])
async def test_exhaustive_search_still_obeys_page_and_operator_safeguards(failure: str) -> None:
    initial = queue_url("search", "adapter")
    second = initial + "&page=2"
    documents = {
        initial: CATALOG + next_link(initial if failure == "repeated" else second),
        second: "<input id='captchacharacters'>" if failure == "challenge" else CATALOG,
    }
    page = FakePage(documents)
    if failure == "timeout":
        page.documents[second] = PlaywrightTimeoutError("private page details")

    async def progress(_: dict[str, Any]) -> None:
        if failure == "cancel":
            raise CollectionCancelledError()

    result = await collect(
        page, "search", "adapter", page_budget=1, exhaustive=True, progress=progress
    )
    assert (
        result.status
        == {
            "cancel": "cancelled",
            "timeout": "partial",
            "repeated": "partial",
            "challenge": "needs_login",
        }[failure]
    )
    assert result.stop_reason is None
    assert result.pages == 1 and len(result.products) == 1


async def test_exhaustive_page_load_has_a_timeout_even_without_a_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the real asyncio cancellation, shortening only this page's ceiling.
    original_wait_for = asyncio.wait_for
    limits = []

    async def fast_wait_for(awaitable: Any, timeout: float) -> Any:
        limits.append(timeout)
        return await original_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(amazon.asyncio, "wait_for", fast_wait_for)
    cancelled = asyncio.Event()

    class StalledPage(FakePage):
        async def goto(self, url: str, **kwargs: Any) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    result = await collect(StalledPage({}), "search", "adapter", exhaustive=True)
    assert limits == [60] and cancelled.is_set()
    assert result.status == "failed" and result.stop_reason is None
    assert result.error == "Page load failed (TimeoutError); no absence inferred."


async def test_load_unrecognised_document_and_bounds() -> None:
    page = FakePage({URL: "Unexpected content"})
    page.fail_wait = True
    assert await load_page(page, URL) == ("Unexpected content", URL)
    with pytest.raises(ValueError):
        await load_page(page, "http://localhost/secrets")
    with pytest.raises(ValueError):
        await collect(page, "rfy", page_budget=0)
    with pytest.raises(ValueError):
        await collect(page, "rfy", runtime_budget=1)
    with pytest.raises(ValueError):
        await collect(page, "reviews", exhaustive=True)
    assert (await collect(page, "rfy")).status == "failed"
    page.documents[REVIEW_URL] = TimeoutError()
    review = await collect(page, "reviews")
    assert review.status == "failed"
    assert review.error == "Review navigation failed (TimeoutError)."
