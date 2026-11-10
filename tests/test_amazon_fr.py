"""amazon.fr markup: French labels, epoch-ms order dates and review-type tabs."""

import pytest

from vine_search import amazon

FR = "https://www.amazon.fr"


@pytest.fixture(autouse=True)
def french_storefront(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(amazon, "AMAZON_HOSTS", frozenset({"amazon.fr", "www.amazon.fr"}))
    monkeypatch.setattr(amazon, "ORIGIN", FR)


def test_review_tabs_found_by_review_type() -> None:
    html = (
        '<a href="/vine/vine-reviews?review-type=pending_review">En attente</a>'
        '<a href="/vine/vine-reviews?review-type=completed">Avis envoyés</a>'
    )
    tabs = amazon.review_sections(html, f"{FR}/vine/vine-reviews")
    assert tabs == {
        "awaiting_review": f"{FR}/vine/vine-reviews?review-type=pending_review",
        "reviewed": f"{FR}/vine/vine-reviews?review-type=completed",
    }


def test_french_review_row() -> None:
    html = """<div id="vvp-items-grid-container"><p>Affichage de 1-1 sur 1 résultats</p>
    <table class="vvp-reviews-table"><tbody><tr class="vvp-reviews-table--row">
    <td class="vvp-reviews-table--text-col"><a href="/dp/B0ABCDEFGH">
      <span class="a-truncate-full">Lampe de bureau</span></a></td>
    <td class="vvp-reviews-table--text-col" data-order-timestamp="1762732800000">10/11/2025</td>
    <td class="vvp-reviews-table--text-col">Pas encore examiné</td>
    </tr></tbody></table></div>"""
    page = amazon.parse_reviews(html, f"{FR}/vine/vine-reviews?review-type=completed", "reviewed")
    assert page.state == "ok", page.message
    (row,) = page.reviews
    assert row["asin"] == "B0ABCDEFGH"
    assert row["order_date"] == "2025-11-10"
    assert row["observed_status"] == "Pas encore examiné"
    assert row["product_url"] == f"{FR}/dp/B0ABCDEFGH"
    assert page.advertised_count == 1


def test_french_etv_and_unavailable() -> None:
    product = {"asin": "B0ABCDEFGH", "title": "Lampe"}
    html = '<a href="/dp/B0ABCDEFGH">Lampe</a><p>Valeur fiscale estimée : 1&#8239;234,56 €</p>'
    details = amazon.parse_product_details(html, product, product_id=1)
    assert details["etv"] == "1 234,56 €"
    gone = amazon.parse_product_details("<p>Actuellement indisponible.</p>", product, product_id=1)
    assert gone["state"] == "unavailable"


def test_language_prefixed_pagination_and_item_count() -> None:
    """amazon.fr in English serves /-/en/ links and 'N item(s) matching' totals."""
    html = """<div id="vvp-items-grid-container"><p>113 article(s) correspondant à « lampe »</p>
    <div id="vvp-items-grid"><div class="vvp-item-tile" data-asin="B0DLWRSC4T">
      <div class="vvp-item-product-title-container"><a href="/dp/B0DLWRSC4T">
        <span class="a-truncate-full">Clips</span></a></div></div></div>
    <ul class="a-pagination"><li class="a-last">
      <a href="/-/en/vine/vine-items?queue=encore&pn=&cn=&page=2&search=lampe">Suivant</a>
    </li></ul></div>"""
    page = amazon.parse_catalog(html, f"{FR}/vine/vine-items?queue=encore&search=lampe")
    assert page.state == "ok", page.message
    assert page.next_url == f"{FR}/-/en/vine/vine-items?queue=encore&pn=&cn=&page=2&search=lampe"
    assert page.advertised_count == 113
    assert amazon.vine_path(page.next_url) == "/vine/vine-items"


def test_french_details_heading() -> None:
    assert amazon.DETAILS_HEADING.search("Détails de l'article")
    assert amazon.DETAILS_BUTTON.match("Voir les détails")
