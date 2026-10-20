"""Read-only Amazon Vine adapter. All navigation starts at a fixed Amazon origin.

Selectors are deliberately conservative: unrecognised documents are errors, never
empty catalogs. Collection retains a bounded, scoped account observation, not a
claim about global availability.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from vine_search.models import clean_product_details

ORIGIN = "https://www.amazon.com"
ASIN = re.compile(r"^[A-Z0-9]{10}$")
QUEUES = {"rfy": "potluck", "afa": "last_chance", "search": "encore"}
PRODUCT_CARDS = ".vvp-item-tile"
REVIEW_ROWS = "#vvp-reviews-table tbody tr, .vvp-reviews-table tbody tr"


@dataclass
class ParsedPage:
    state: str
    products: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    next_url: str | None = None
    advertised_count: int | None = None
    message: str = ""


@dataclass
class Scan:
    status: str
    products: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    advertised_count: int | None = None
    error: str | None = None
    stop_reason: str | None = None
    section_pages: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0
    exhaustive: bool = False
    details: dict[str, Any] | None = None


class CollectionCancelledError(Exception):
    """The operator cancelled a durable collection job."""


class RuntimeBudgetReachedError(Exception):
    """The overall collection deadline cancelled a page load."""


def clean(value: Any, limit: int = 1500) -> str:
    return " ".join(str(value or "").split())[:limit]


def amazon_url(value: str, base: str = ORIGIN) -> str | None:
    try:
        candidate = urljoin(base, value)
        parsed = urlparse(candidate)
        invalid = (
            parsed.scheme != "https"
            or parsed.hostname not in {"amazon.com", "www.amazon.com"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        )
    except ValueError:
        return None
    if invalid:
        return None
    return candidate


def image_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.hostname.endswith(".media-amazon.com") or parsed.hostname in {
        "images-na.ssl-images-amazon.com",
        "images.amazon.com",
    }:
        return value
    return None


def queue_url(kind: str, query: str = "") -> str:
    if kind not in QUEUES:
        raise ValueError("Unknown Vine queue")
    if kind == "search" and not query.strip():
        raise ValueError("A live search needs a query")
    args = {"queue": QUEUES[kind]}
    if kind == "search":
        args["search"] = query.strip()[:200]
    return f"{ORIGIN}/vine/vine-items?{urlencode(args)}"


def signed_in_vine(html: str, url: str) -> bool:
    """Require actual Amazon host, Vine path, and authenticated Vine content."""
    if not amazon_url(url) or not urlparse(url).path.startswith("/vine/"):
        return False
    soup = BeautifulSoup(html, "html.parser")
    if _auth_state(soup, url):
        return False
    return (
        soup.select_one(
            "#vvp-items-grid, #vvp-reviews-table, .vvp-reviews-table, "
            "#vvp-orders-table, #vvp-account-details"
        )
        is not None
    )


def _auth_state(soup: BeautifulSoup, url: str) -> str | None:
    text = soup.get_text(" ", strip=True).lower()
    path = urlparse(url).path
    if soup.select_one("#captchacharacters, form[action*='validateCaptcha'], #cvf-page-content"):
        return "challenge"
    if any(value in text for value in ("enter the characters you see", "solve this puzzle")):
        return "challenge"
    if "/ap/" in path or soup.select_one("#ap_email, #ap_password, form[name='signIn']"):
        return "needs_login"
    return None


def _page_state(soup: BeautifulSoup, url: str) -> str | None:
    if not amazon_url(url) or not urlparse(url).path.startswith("/vine/"):
        return "needs_login" if _auth_state(soup, url) else "invalid_host"
    return _auth_state(soup, url)


def _next(soup: BeautifulSoup, url: str) -> str | None:
    node = soup.select_one(
        ".a-pagination .a-last:not(.a-disabled) a[href], "
        "a.s-pagination-next:not(.s-pagination-disabled)[href], a[rel='next'][href]"
    )
    if node is None:
        return None
    candidate = amazon_url(str(node.get("href", "")), url)
    if candidate is None:
        raise ValueError("Pagination left the Amazon Vine origin")
    old, new = urlparse(url), urlparse(candidate)
    if old.path != new.path:
        raise ValueError("Pagination changed the Vine section")
    old_query, new_query = parse_qs(old.query), parse_qs(new.query)
    for key in ("queue", "search", "review-type"):
        if old_query.get(key) != new_query.get(key):
            raise ValueError("Pagination changed the collection scope")
    return candidate


def _count(soup: BeautifulSoup) -> int | None:
    node = soup.select_one("#vvp-items-grid-container, #vvp-items-grid, #vvp-reviews-table")
    text = (node.parent if node and node.parent else soup).get_text(" ", strip=True)
    match = re.search(r"\bof\s+(?:over\s+)?([\d,]+)\s+(?:results|items|reviews)\b", text, re.I)
    return int(match.group(1).replace(",", "")) if match else None


def _asin(node: Tag) -> str | None:
    candidates = [node, *node.select("[data-asin], [data-recommendation-id]")]
    for item in candidates:
        value = str(item.get("data-asin", "")).upper()
        if ASIN.fullmatch(value):
            return value
        rec = str(item.get("data-recommendation-id", ""))
        match = re.search(r"(?:#|:|_)([A-Z0-9]{10})(?:#|:|_|$)", rec)
        if match:
            return match.group(1)
    for link in [node, *node.select("a[href]")]:
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", str(link.get("href")))
        if match:
            return match.group(1)
    return None


def _product_title(node: Tag | None) -> str:
    if node is None:
        return ""
    full = node.select_one(".a-truncate-full")
    # Amazon renders both the full text and its shortened visual copy. The DOM
    # parser decodes HTML once; some product titles contain another encoded layer.
    return clean(unescape((full if full is not None else node).get_text(" ", strip=True)))


def _product_image(node: Tag) -> str | None:
    for img in node.select("img"):
        for attribute in ("src", "data-src"):
            candidate = image_url(str(img.get(attribute, "")))
            if candidate:
                return candidate
    return None


def parse_catalog(html: str, url: str) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    state = _page_state(soup, url)
    if state:
        return ParsedPage(state, message="Amazon sign-in or page access is required.")
    grid = soup.select_one("#vvp-items-grid")
    if grid is None:
        return ParsedPage(
            "layout_changed", message="The expected Vine product grid was not present."
        )
    products: list[dict[str, Any]] = []
    cards = grid.select(PRODUCT_CARDS)
    for card in cards:
        asin = _asin(card)
        title_node = card.select_one(".vvp-item-product-title-container .a-truncate-full")
        if title_node is None:
            title_node = card.select_one(".vvp-item-product-title-container, a.a-link-normal")
        title = _product_title(title_node)
        if not asin or not title:
            return ParsedPage(
                "layout_changed",
                products=products,
                message="A Vine tile lacked a readable identity or title.",
            )
        category = card.get("data-category")
        products.append(
            {
                "asin": asin,
                "marketplace": "amazon.com",
                "title": title,
                "image_url": _product_image(card),
                "product_url": f"{ORIGIN}/dp/{asin}",
                "vine_url": url,
                "category": clean(category) or None,
            }
        )
    if not cards:
        text = soup.get_text(" ", strip=True).lower()
        empty = any(
            value in text
            for value in (
                "no items available",
                "no products available",
                "no results",
                "we couldn't find",
                "there are no",
                "0 results",
            )
        )
        if not empty:
            return ParsedPage(
                "layout_changed", message="An empty grid had no explicit empty-results message."
            )
    try:
        following = _next(soup, url)
    except ValueError as exc:
        return ParsedPage("layout_changed", products=products, message=str(exc))
    return ParsedPage(
        "ok" if products else "empty", products, next_url=following, advertised_count=_count(soup)
    )


def _date(value: str) -> str | None:
    value = clean(value)
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def review_sections(html: str, url: str) -> dict[str, str]:
    """Discover review tabs from actual links instead of guessing query values."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, str] = {}
    for link in soup.select("a[href]"):
        label = clean(link.get_text(" ", strip=True)).lower()
        href = amazon_url(str(link.get("href")), url)
        if href is None or urlparse(href).path != "/vine/vine-reviews":
            continue
        if "awaiting review" in label or "pending review" in label:
            result["awaiting_review"] = href
        elif label == "reviewed" or re.fullmatch(r"reviewed\s*\([\d,]+\)", label):
            result["reviewed"] = href
    return result


def parse_reviews(html: str, url: str, section: str) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    state = _page_state(soup, url)
    if state:
        return ParsedPage(state, message="Amazon sign-in or page access is required.")
    table = soup.select_one("#vvp-reviews-table, .vvp-reviews-table")
    if table is None:
        return ParsedPage(
            "layout_changed", message="The expected Vine review table was not present."
        )
    records: list[dict[str, Any]] = []
    rows = table.select("tbody tr") or table.select("tr")
    headers = [
        clean(n.get_text(" ", strip=True)).lower() for n in table.select("thead th, thead td")
    ]
    for row in rows:
        if row.select_one("th") or not row.select("td"):
            continue
        title_nodes = row.select(
            ".vvp-reviews-table--text-col a, a[href*='/dp/'], a[href*='/gp/product/']"
        )
        if not title_nodes:
            continue
        # The product thumbnail can link to the same ASIN before the text cell.
        title_node = next((node for node in title_nodes if _product_title(node)), title_nodes[0])
        title = _product_title(title_node)
        if not title:
            return ParsedPage(
                "layout_changed", reviews=records, message="A review row had no product title."
            )
        asin = _asin(row)
        cells = row.select("td")
        date_node = row.select_one(".vvp-reviews-table--date-col, [data-order-date]")
        order_date = _date(clean(date_node.get_text(" ", strip=True))) if date_node else None
        if order_date is None:
            for cell in cells:
                order_date = _date(cell.get_text(" ", strip=True))
                if order_date:
                    break
        status_node = row.select_one(".vvp-reviews-table--review-status, .vvp-review-status")
        status = clean(status_node.get_text(" ", strip=True)) if status_node else ""
        if not status:
            for index, header in enumerate(headers):
                if "status" in header and index < len(cells):
                    status = clean(cells[index].get_text(" ", strip=True))
                    break
        # A tab is provenance. Only the awaiting tab itself proves awaiting status.
        if not status:
            status = "Awaiting Review" if section == "awaiting_review" else "unknown"
        review_link: str | None = None
        external: str | None = clean(row.get("data-order-id") or row.get("data-review-id")) or None
        for anchor in row.select("a[href]"):
            href = amazon_url(str(anchor.get("href")), url)
            if not href:
                continue
            if any(
                value in urlparse(href).path
                for value in ("/review/", "/review/create", "/customer-reviews/")
            ):
                review_link = href
                query = parse_qs(urlparse(href).query)
                observed_ids = query.get("orderID") or query.get("orderId") or []
                external = external or (observed_ids[0] if observed_ids else None)
        variant_node = row.select_one(".vvp-reviews-table--variation, .vvp-item-product-variation")
        records.append(
            {
                "external_id": external,
                "asin": asin,
                "title": title,
                "image_url": _product_image(row),
                "variant": clean(variant_node.get_text(" ", strip=True)) if variant_node else None,
                "order_date": order_date,
                "observed_status": status,
                "product_url": f"{ORIGIN}/dp/{asin}"
                if asin
                else amazon_url(str(title_node.get("href", "")), url),
                "review_url": review_link,
                "source": f"amazon:{section}",
            }
        )
    if not records and not any(
        phrase in soup.get_text(" ", strip=True).lower()
        for phrase in ("no reviews", "no items", "no products", "there are no", "0 reviews")
    ):
        return ParsedPage(
            "layout_changed", message="No readable review rows or explicit empty state."
        )
    try:
        following = _next(soup, url)
    except ValueError as exc:
        return ParsedPage("layout_changed", reviews=records, message=str(exc))
    return ParsedPage(
        "ok" if records else "empty",
        reviews=records,
        next_url=following,
        advertised_count=_count(soup),
    )


async def load_page(page: Any, url: str) -> tuple[str, str]:
    if not amazon_url(url) or not urlparse(url).path.startswith("/vine/"):
        raise ValueError("Only observed Amazon Vine pages may be collected")
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    # Parse actual error documents when the expected selectors never appear.
    with contextlib.suppress(Exception):
        await page.locator(
            "#vvp-items-grid, #vvp-reviews-table, .vvp-reviews-table, "
            "#ap_email, #ap_password, #captchacharacters, #cvf-page-content"
        ).first.wait_for(state="attached", timeout=15_000)
    return await page.content(), str(page.url)


async def _load_before_deadline(page: Any, url: str, deadline: float | None) -> tuple[str, str]:
    if deadline is None:
        return await asyncio.wait_for(load_page(page, url), timeout=60)
    timeout = asyncio.timeout(max(0, deadline - time.monotonic()))
    try:
        async with timeout:
            return await load_page(page, url)
    except TimeoutError:
        if timeout.expired():
            raise RuntimeBudgetReachedError() from None
        raise


def parse_product_details(html: str, product: dict[str, Any], *, product_id: int) -> dict[str, Any]:
    """Read a single already-open dialog; missing ETV remains unknown, never zero."""
    soup = BeautifulSoup(html, "html.parser")
    text = clean(unescape(soup.get_text(" ", strip=True)), 20_000)
    title_node = next(
        (
            node
            for node in soup.select("a[href*='/dp/'], a[href*='/gp/product/']")
            if _product_title(node) and amazon_url(str(node.get("href", "")))
        ),
        None,
    )
    etv = re.search(
        r"(Estimated\s+(?:Taxable|Tax)\s+Value)\s*:\s*((?:US\s*)?\$\s*[\d,]+(?:\.\d{2})?)",
        text,
        re.I,
    )
    descriptions = [
        clean(unescape(node.get_text(" ", strip=True)), 1500)
        for node in soup.select("ul li")
        if node.get("role") != "option" and not node.find_parent(attrs={"role": "listbox"})
    ]
    variants = []
    for select in soup.select("select"):
        label = soup.find("label", attrs={"for": select.get("id")}) if select.get("id") else None
        name = (
            clean(unescape(label.get_text(" ", strip=True)))
            if isinstance(label, Tag)
            else clean(select.get("aria-label") or select.get("name") or "Option", 100)
        )
        options = select.select("option")
        selected = select.select_one("option[selected]")
        if selected is None and options:
            selected = options[0]
        variants.append(
            {
                "name": name,
                "selected": clean(unescape(selected.get_text(" ", strip=True)))
                if selected is not None and selected.get("value") != ""
                else None,
                "options": [
                    clean(unescape(option.get_text(" ", strip=True)))
                    for option in options
                    if option.get("value") != "" and not option.has_attr("disabled")
                ],
            }
        )
    unavailable = re.search(
        r"(?:This item is no longer available|Currently unavailable|"
        r"This product is no longer available)",
        text,
        re.I,
    )
    if title_node is None and not (etv or descriptions or variants or unavailable):
        raise ValueError("The product details dialog has no readable product content")
    variant_message = ""
    dialog_asin = _asin(title_node) if title_node is not None else None
    if dialog_asin and dialog_asin != product["asin"]:
        selected_asins = {
            str(node.get("value"))
            for node in soup.select("select option[selected][value]")
            if ASIN.fullmatch(str(node.get("value")))
        }
        if not product.get("is_parent_asin") or dialog_asin not in selected_asins:
            raise ValueError("The details dialog identifies a different product")
        variant_message = f"Details show selected variant {dialog_asin} of this parent product. "
    return {
        "product_id": product_id,
        "asin": product["asin"],
        "state": "unavailable" if unavailable else "observed",
        "title": _product_title(title_node) or product["title"],
        "image_url": _product_image(soup) or product.get("image_url"),
        "description": "\n".join(descriptions)[:6000],
        "etv": clean(etv.group(2)) if etv else None,
        "etv_label": clean(etv.group(1)) if etv else None,
        "variants": variants,
        "availability": clean(unavailable.group()) if unavailable else None,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "message": clean(
            variant_message
            + (
                "Amazon reports that this item is unavailable."
                if unavailable
                else (
                    ""
                    if etv
                    else (
                        "Amazon did not display an estimated taxable value "
                        "for the current selection."
                    )
                )
            )
        )
        or None,
    }


async def lookup_details(page: Any, payload: dict[str, Any], *, progress: Any = None) -> Scan:
    """Activate only an exact card's See details button, never an ordering control."""
    scan = Scan("failed")
    started = time.monotonic()
    asin, url = str(payload["asin"]), str(payload["vine_url"])
    if (
        not ASIN.fullmatch(asin)
        or not amazon_url(url)
        or urlparse(url).path.rstrip("/") != "/vine/vine-items"
    ):
        scan.error = "Product details require a saved Amazon Vine listing."
        return scan

    async def report(stage: str) -> None:
        if progress:
            await progress({"pages": scan.pages, "observed": 0, "stage": stage})

    try:
        async with asyncio.timeout(90):
            await report("opening_listing")
            html, actual_url = await _load_before_deadline(page, url, None)
            parsed = parse_catalog(html, actual_url)
            if parsed.state not in {"ok", "empty"}:
                scan.status = (
                    "needs_login" if parsed.state in {"needs_login", "challenge"} else "failed"
                )
                scan.error = f"{parsed.state}: {parsed.message}"
                return scan
            scan.pages = 1
            await report("finding_product")
            product = next((item for item in parsed.products if item["asin"] == asin), None)
            if product is None:
                scan.status = "complete"
                scan.details = {
                    "product_id": payload["product_id"],
                    "asin": asin,
                    "state": "unavailable",
                    "title": "",
                    "image_url": None,
                    "description": "",
                    "etv": None,
                    "etv_label": None,
                    "variants": [],
                    "availability": None,
                    "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "message": (
                        "This item is no longer on its observed Vine page. Refresh the search."
                    ),
                }
                return scan
            cards = BeautifulSoup(html, "html.parser").select("#vvp-items-grid .vvp-item-tile")
            matches = [index for index, card in enumerate(cards) if _asin(card) == asin]
            if len(matches) != 1:
                scan.error = "The Vine page did not identify one matching product card."
                return scan
            card = page.locator("#vvp-items-grid .vvp-item-tile").nth(matches[0])
            current_card = BeautifulSoup(
                await card.evaluate("node => node.outerHTML"), "html.parser"
            ).select_one(PRODUCT_CARDS)
            if current_card is None or _asin(current_card) != asin:
                scan.error = "The Vine listing changed before its details could be opened."
                return scan
            product["is_parent_asin"] = any(
                str(node.get("data-is-parent-asin", "")).lower() == "true"
                for node in (current_card, *current_card.select("[data-is-parent-asin]"))
            )
            button = card.get_by_role("button", name=re.compile(r"^See details$", re.I))
            if await button.count() != 1 or not await button.is_enabled():
                scan.error = "The matching product has no available See details control."
                return scan
            await report("opening_details")
            await button.click(timeout=10_000)
            heading = re.compile(r"Product Details", re.I)
            await (
                page.locator("[role='dialog']:visible, .a-popover:visible")
                .filter(has_text=heading)
                .first.wait_for(state="visible", timeout=15_000)
            )
            semantic = page.locator("[role='dialog']:visible").filter(has_text=heading)
            dialog = semantic.filter(has_not=semantic)
            if await dialog.count() == 0:
                popovers = page.locator(".a-popover:visible").filter(has_text=heading)
                dialog = popovers.filter(has_not=popovers)
            if await dialog.count() != 1:
                scan.error = "Amazon did not identify one product details dialog."
                return scan
            # Dialog shells and ETV labels can precede the value's network response.
            # Missing ETV remains valid for a dialog requiring a variant selection.
            with contextlib.suppress(Exception):
                await dialog.get_by_text(
                    re.compile(
                        r"Estimated\s+(?:Taxable|Tax)\s+Value\s*:\s*(?:US\s*)?\$\s*\d"
                        r"|Currently unavailable|no longer available",
                        re.I,
                    )
                ).first.wait_for(state="visible", timeout=10_000)
            current_html = await page.content()
            state = _page_state(BeautifulSoup(current_html, "html.parser"), str(page.url))
            if state:
                scan.status = "needs_login" if state in {"needs_login", "challenge"} else "failed"
                scan.error = f"{state}: Amazon could not provide product details."
                return scan
            await report("reading_details")
            # Reflect live select properties in a detached clone without changing
            # the Amazon page or making a variant-selection request.
            dialog_html = await dialog.evaluate(
                """node => {
                    const clone = node.cloneNode(true);
                    const originals = node.querySelectorAll('select');
                    clone.querySelectorAll('select').forEach((select, index) => {
                        Array.from(select.options).forEach((option, position) => {
                            option.toggleAttribute('selected',
                                originals[index].options[position].selected);
                        });
                    });
                    return clone.outerHTML;
                }"""
            )
            scan.details = clean_product_details(
                parse_product_details(dialog_html, product, product_id=payload["product_id"]),
                product_id=payload["product_id"],
                asin=asin,
            )
            scan.status = "complete"
            return scan
    except CollectionCancelledError:
        scan.status, scan.error = "cancelled", "Product details lookup cancelled."
    except Exception as exc:
        scan.error = f"Product details could not be read ({type(exc).__name__})."
        with contextlib.suppress(Exception):
            state = _page_state(BeautifulSoup(await page.content(), "html.parser"), str(page.url))
            if state in {"needs_login", "challenge"}:
                scan.status = "needs_login"
                scan.error = f"{state}: Amazon needs your attention before details can be read."
    finally:
        scan.elapsed_seconds = round(time.monotonic() - started, 3)
    return scan


async def collect(
    page: Any,
    kind: str,
    query: str = "",
    *,
    page_budget: int = 5,
    runtime_budget: int = 120,
    exhaustive: bool = False,
    progress: Any = None,
) -> Scan:
    if exhaustive and kind != "search":
        raise ValueError("Only a live search can request every result page")
    # Keep the legacy argument compatible, but no search caller can restore a cap.
    exhaustive = kind == "search"
    if not exhaustive and (not 1 <= page_budget <= 100 or not 10 <= runtime_budget <= 1800):
        raise ValueError("Collection budget outside supported bounds")
    scan = Scan("failed", exhaustive=exhaustive)
    started = time.monotonic()
    deadline = None if exhaustive else started + runtime_budget

    def finish(status: str, error: str | None = None) -> Scan:
        scan.status, scan.error = status, error
        scan.elapsed_seconds = round(time.monotonic() - started, 3)
        return scan

    def budget_reached(reason: str) -> Scan:
        scan.stop_reason = reason
        if reason == "page_budget":
            limit = f"Page limit reached ({page_budget} page{'s' if page_budget != 1 else ''})"
            continuation = "more pages remain"
        else:
            limit = f"Time limit reached ({runtime_budget} seconds)"
            continuation = "collection is incomplete"
        count = (
            len({item["asin"] for item in scan.products})
            if kind != "reviews"
            else len(scan.reviews)
        )
        return finish(
            "truncated",
            f"{limit}. Retained {count} item{'s' if count != 1 else ''} from "
            f"{scan.pages} completed page{'s' if scan.pages != 1 else ''}; "
            f"{continuation}.",
        )

    sections: list[tuple[str, str]]
    if kind == "reviews":
        try:
            html, url = await _load_before_deadline(page, f"{ORIGIN}/vine/vine-reviews", deadline)
        except RuntimeBudgetReachedError:
            return budget_reached("runtime_budget")
        except Exception as exc:
            return finish("failed", f"Review navigation failed ({type(exc).__name__}).")
        if not signed_in_vine(html, url):
            parsed = parse_reviews(html, url, "awaiting_review")
            return finish(
                "needs_login" if parsed.state in {"needs_login", "challenge"} else "failed",
                parsed.state,
            )
        observed = review_sections(html, url)
        if not {"awaiting_review", "reviewed"} <= observed.keys():
            return finish(
                "failed", "Could not identify both Awaiting Review and Reviewed navigation."
            )
        sections = [(section, observed[section]) for section in ("awaiting_review", "reviewed")]
    else:
        sections = [(kind, queue_url(kind, query))]
    scan.section_pages = dict.fromkeys((section for section, _ in sections), 0)
    visited: set[str] = set()
    pending = deque(sections)
    while pending:
        if not exhaustive and scan.pages >= page_budget:
            return budget_reached("page_budget")
        if deadline is not None and time.monotonic() >= deadline:
            return budget_reached("runtime_budget")
        section, current = pending.popleft()
        if current in visited:
            return finish("partial", "Pagination repeated a previously visited page.")
        visited.add(current)
        try:
            html, actual_url = await _load_before_deadline(page, current, deadline)
            parsed = (
                parse_reviews(html, actual_url, section)
                if kind == "reviews"
                else parse_catalog(html, actual_url)
            )
        except RuntimeBudgetReachedError:
            return budget_reached("runtime_budget")
        except Exception as exc:
            return finish(
                "partial" if scan.pages else "failed",
                f"Page load failed ({type(exc).__name__}); no absence inferred.",
            )
        if parsed.state not in {"ok", "empty"}:
            scan.products.extend(parsed.products)
            scan.reviews.extend(parsed.reviews)
            return finish(
                "needs_login"
                if parsed.state in {"needs_login", "challenge"}
                else ("partial" if scan.pages or scan.products or scan.reviews else "failed"),
                parsed.state + ": " + parsed.message,
            )
        scan.pages += 1
        scan.section_pages[section] += 1
        scan.products.extend(parsed.products)
        scan.reviews.extend(parsed.reviews)
        if parsed.advertised_count is not None:
            scan.advertised_count = parsed.advertised_count
        if progress:
            try:
                await progress(
                    {
                        "pages": scan.pages,
                        "observed": len(scan.products or scan.reviews),
                        "section": section,
                        "section_pages": dict(scan.section_pages),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "exhaustive": exhaustive,
                    }
                )
            except CollectionCancelledError:
                return finish("cancelled", "Cancelled by the operator; captured pages retained.")
        if parsed.next_url:
            pending.append((section, parsed.next_url))
    return finish("complete")
