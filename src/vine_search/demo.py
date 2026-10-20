"""Explicitly synthetic, isolated demonstration data for documentation and tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from vine_search.store import Store

CATALOG = [
    ("Five-port 2.5 GbE desktop network switch", "Networking", "rfy"),
    ("USB-C soldering iron with adjustable temperature", "Tools", "afa"),
    ("Compact five-port Ethernet switch", "Networking", "search"),
    ("Cordless drill with adjustable clutch", "Tools", "rfy"),
    ("USB-C hub with Ethernet and HDMI", "Electronics", "afa"),
    ("Magnetic building tiles, 48-piece family set", "Family", "rfy"),
    ("Compact cordless drill and driver", "Tools", "afa"),
    ("Adjustable LED desk lamp with swing arm", "Home improvement", "rfy"),
    ("Temperature-controlled soldering iron", "Electronics", "search"),
    ("Dimmable desk lamp for a workbench", "Home improvement", "afa"),
    ("Magnetic building tiles, geometric starter set", "Family", "rfy"),
    ("Lightweight cordless drill kit", "Tools", "afa"),
    ("Aluminum USB-C hub with four ports", "Electronics", "rfy"),
    ("Task desk lamp with adjustable arm", "Home improvement", "search"),
    ("Unmanaged five-port network switch", "Networking", "afa"),
]


def seed_demo(data_dir: Path) -> dict[str, Any]:
    """Populate an empty database, visibly marked demo, with collection disabled."""
    store = Store(data_dir / "vine-search.sqlite3")
    if store.list_products()["total"] or store.list_reviews()["total"]:
        raise ValueError("Demo seeding requires an empty database; existing data is preserved.")
    store.update_settings({"collection_enabled": False, "review_sync_enabled": False})
    now = datetime.now(UTC)
    for kind in ("rfy", "afa", "search"):
        products = [
            {
                "asin": f"B0TEST{i:04d}",
                "title": title,
                "category": category,
                "product_url": f"https://www.amazon.com/dp/B0TEST{i:04d}",
                "vine_url": f"https://www.amazon.com/vine/vine-items?search={title.split()[0]}",
                "variant": "Synthetic demonstration",
            }
            for i, (title, category, source) in enumerate(CATALOG, 1)
            if source == kind
        ]
        job = store.enqueue_job(kind, query="electronics" if kind == "search" else "")
        store.record_scan(
            job["id"],
            products,
            now=now - timedelta(minutes=12),
            pages=1,
            advertised_count=len(products),
        )
    reviews = [
        {
            "external_id": f"DEMO-ORDER-{i}",
            "asin": f"B0TEST{i:04d}",
            "title": CATALOG[i - 1][0],
            "variant": "Synthetic demonstration",
            "order_date": (now - timedelta(days=i * 6)).date().isoformat(),
            "observed_status": "Awaiting review" if i < 4 else "Reviewed",
            "product_url": f"https://www.amazon.com/dp/B0TEST{i:04d}",
            "review_url": f"https://www.amazon.com/review/create-review?asin=B0TEST{i:04d}",
            "source": "synthetic",
        }
        for i in range(1, 5)
    ]
    job = store.enqueue_job("reviews")
    store.record_review_scan(job["id"], reviews, source="synthetic")
    first = store.list_reviews()["items"][0]
    store.set_review_progress(first["id"], "in_progress")
    (data_dir / "DEMO").write_text("Synthetic demonstration data. No Amazon account connected.\n")
    return store.dashboard()
