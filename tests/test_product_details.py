"""Details snapshots use observed locators and never become catalog observations."""

from pathlib import Path
from typing import Any

import pytest

from vine_search.models import clean_product_details
from vine_search.store import Store

LISTING = "https://www.amazon.com/vine/vine-items?queue=encore&search=synthetic&page=2"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    result = Store(tmp_path / "details.sqlite", seed=False)
    job = result.enqueue_job("search", query="synthetic")
    result.record_scan(
        job["id"],
        [
            {"asin": f"B00000000{number}", "title": f"Product {number}", "vine_url": LISTING}
            for number in (1, 2)
        ],
    )
    return result


def details(**extra: Any) -> dict[str, Any]:
    return {
        "product_id": 1,
        "asin": "B000000001",
        "state": "observed",
        "title": "Synthetic details",
        "image_url": "https://m.media-amazon.com/synthetic.jpg",
        "description": "A product description.\nA second feature.",
        "etv": "$9.89",
        "etv_label": "Estimated Taxable Value",
        "variants": [{"name": "Color", "selected": "Blue", "options": ["Blue", "Red"]}],
        "availability": None,
        "observed_at": "2026-10-20T20:00:00Z",
        "message": None,
        **extra,
    }


def test_details_use_saved_locator_per_product_dedup_and_serial_claim(store: Store) -> None:
    first = store.enqueue_job(
        "details",
        payload={"product_id": 1, "asin": "B999999999", "vine_url": "https://evil.example"},
    )
    assert first["kind"] == "details"
    assert first["payload"]["asin"] == "B000000001"
    assert first["payload"]["vine_url"] == LISTING
    assert first["payload"]["exhaustive"] is False
    assert store.enqueue_product_details(1)["id"] == first["id"]
    second = store.enqueue_product_details(2)
    assert second["id"] != first["id"]
    store.set_connection("connected")
    assert store.claim_job("owner")["id"] == first["id"]  # type: ignore[index]
    assert store.claim_job("other") is None
    before = store.get_product(1)
    completed = store.update_job(first["id"], status="complete", result=details())
    assert completed["result"]["etv"] == "$9.89"
    assert Store(store.path).get_job(first["id"])["result"] == completed["result"]
    assert store.get_product(1) == before
    assert store.claim_job("owner")["id"] == second["id"]  # type: ignore[index]
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM sightings").fetchone()[0] == 2
    assert store.enqueue_product_details(1)["id"] != first["id"]


def test_details_require_a_saved_vine_listing_and_keep_original_snapshot(store: Store) -> None:
    with pytest.raises(KeyError):
        store.enqueue_product_details(999)
    for value in (True, 0, -1):
        with pytest.raises(ValueError):
            store.enqueue_product_details(value)
    with pytest.raises(ValueError):
        store.enqueue_job("details")
    with pytest.raises(ValueError):
        store.enqueue_job("details", source="schedule", payload={"product_id": 1})
    first = store.enqueue_product_details(1)
    with store.connect(write=True) as connection:
        connection.execute(
            "UPDATE products SET vine_url='https://www.amazon.com/dp/B000000002' WHERE id=2"
        )
        connection.execute(
            "UPDATE products SET vine_url=? WHERE id=1", (LISTING.replace("page=2", "page=3"),)
        )
    with pytest.raises(ValueError, match="Refresh"):
        store.enqueue_product_details(2)
    assert store.get_job(first["id"])["payload"]["vine_url"] == LISTING
    with pytest.raises(ValueError):
        store.record_scan(first["id"], [])


def test_details_unavailable_and_cancellation_do_not_infer_zero_or_complete(store: Store) -> None:
    job = store.enqueue_product_details(1)
    unavailable = details(
        state="unavailable", title="", image_url=None, etv=None, variants=[], message="Refresh item"
    )
    result = store.update_job(job["id"], status="complete", result=unavailable)
    assert result["result"]["state"] == "unavailable"
    assert result["result"]["etv"] is None
    assert result["result"]["image_url"] == ""
    cancelled = store.enqueue_product_details(1)
    store.update_job(cancelled["id"], status="cancelled")
    with pytest.raises(ValueError, match="completed job"):
        store.update_job(cancelled["id"], status="complete", result=details())
    assert store.get_job(cancelled["id"])["result"] == {}
    failed = store.enqueue_product_details(2)
    with pytest.raises(ValueError, match="require"):
        store.update_job(failed["id"], status="complete")
    assert store.update_job(failed["id"], status="needs_login")["status"] == "needs_login"


def test_details_result_whitelist_excludes_raw_html_credentials_and_order_controls() -> None:
    cleaned = clean_product_details(
        details(
            raw_html="<input name=token value=PRIVATE>",
            cookie="PRIVATE",
            order_url="https://www.amazon.com/order",
        ),
        product_id=1,
        asin="B000000001",
    )
    assert "PRIVATE" not in str(cleaned)
    assert "raw_html" not in cleaned and "order_url" not in cleaned
    assert cleaned["observed_at"] == "2026-10-20T20:00:00+00:00"
    assert cleaned["variants"][0]["options"] == ["Blue", "Red"]


@pytest.mark.parametrize(
    "extra",
    [
        {"product_id": 2},
        {"product_id": True},
        {"asin": "B000000002"},
        {"state": "purchased"},
        {"state": {}},
        {"variants": {}},
        {"variants": [{}] * 21},
        {"variants": ["bad"]},
        {"variants": [{"options": ["choice"] * 101}]},
        {"image_url": "http://127.0.0.1/private"},
        {"etv": 0},
        {"description": "x" * 20001},
        {"observed_at": "yesterday"},
    ],
)
def test_invalid_details_cannot_overwrite_durable_job(store: Store, extra: dict[str, Any]) -> None:
    job = store.enqueue_product_details(1)
    with pytest.raises(ValueError):
        store.update_job(job["id"], status="complete", result=details(**extra))
    saved = store.get_job(job["id"])
    assert saved["status"] == "queued" and saved["result"] == {}
