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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

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


class CollectionCancelledError(Exception):
    """The operator cancelled a durable collection job."""


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
    for link in node.select("a[href]"):
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", str(link.get("href")))
        if match:
            return match.group(1)
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
        title = clean(title_node.get_text(" ", strip=True) if title_node else "")
        if not asin or not title:
            return ParsedPage(
                "layout_changed",
                products=products,
                message="A Vine tile lacked a readable identity or title.",
            )
        img = card.select_one("img")
        category = card.get("data-category")
        products.append(
            {
                "asin": asin,
                "marketplace": "amazon.com",
                "title": title,
                "image_url": image_url(str(img.get("src", ""))) if img else None,
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
        title_node = row.select_one(
            ".vvp-reviews-table--text-col a, a[href*='/dp/'], a[href*='/gp/product/']"
        )
        if title_node is None:
            continue
        title = clean(title_node.get_text(" ", strip=True))
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


async def collect(
    page: Any,
    kind: str,
    query: str = "",
    *,
    page_budget: int = 5,
    runtime_budget: int = 120,
    progress: Any = None,
) -> Scan:
    if not 1 <= page_budget <= 100 or not 10 <= runtime_budget <= 1800:
        raise ValueError("Collection budget outside supported bounds")
    scan = Scan("failed")
    started = time.monotonic()
    sections: list[tuple[str, str]]
    if kind == "reviews":
        try:
            html, url = await asyncio.wait_for(
                load_page(page, f"{ORIGIN}/vine/vine-reviews"), timeout=runtime_budget
            )
        except Exception as exc:
            scan.error = f"Review navigation failed ({type(exc).__name__})."
            return scan
        if not signed_in_vine(html, url):
            parsed = parse_reviews(html, url, "awaiting_review")
            scan.status = (
                "needs_login" if parsed.state in {"needs_login", "challenge"} else "failed"
            )
            scan.error = parsed.state
            return scan
        observed = review_sections(html, url)
        if not {"awaiting_review", "reviewed"} <= observed.keys():
            scan.error = "Could not identify both Awaiting Review and Reviewed navigation."
            return scan
        sections = list(observed.items())
    else:
        sections = [(kind, queue_url(kind, query))]
    visited: set[str] = set()
    for section, initial in sections:
        current: str | None = initial
        while current:
            if scan.pages >= page_budget or time.monotonic() - started >= runtime_budget:
                scan.status, scan.error = "truncated", "Configured page or runtime budget reached."
                return scan
            if current in visited:
                scan.status, scan.error = (
                    "partial",
                    "Pagination repeated a previously visited page.",
                )
                return scan
            visited.add(current)
            try:
                remaining = max(1.0, runtime_budget - (time.monotonic() - started))
                html, actual_url = await asyncio.wait_for(
                    load_page(page, current), timeout=remaining
                )
                parsed = (
                    parse_reviews(html, actual_url, section)
                    if kind == "reviews"
                    else parse_catalog(html, actual_url)
                )
            except Exception as exc:
                scan.status = "partial" if scan.pages else "failed"
                scan.error = f"Page load failed ({type(exc).__name__}); no absence inferred."
                return scan
            if parsed.state not in {"ok", "empty"}:
                scan.products.extend(parsed.products)
                scan.reviews.extend(parsed.reviews)
                scan.status = (
                    "needs_login"
                    if parsed.state in {"needs_login", "challenge"}
                    else ("partial" if scan.pages or scan.products or scan.reviews else "failed")
                )
                scan.error = parsed.state + ": " + parsed.message
                return scan
            scan.pages += 1
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
                        }
                    )
                except CollectionCancelledError:
                    scan.status, scan.error = (
                        "cancelled",
                        "Cancelled by the operator; captured pages retained.",
                    )
                    return scan
            current = parsed.next_url
    scan.status = "complete"
    return scan
