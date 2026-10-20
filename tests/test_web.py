"""API contracts and hostile request boundaries against disposable SQLite state."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vine_search.config import Config
from vine_search.security import csrf_token, image_url_allowed, valid_csrf
from vine_search.web import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    cfg = Config(
        data_dir=tmp_path, collector_secret="test-internal-secret", allowed_hosts=("testserver",)
    )
    with TestClient(create_app(cfg)) as client:
        bootstrap = client.get("/api/bootstrap")
        client.headers["X-CSRF-Token"] = bootstrap.json()["csrf_token"]
        yield client


def product(client: TestClient, asin: str = "B0TEST0001") -> dict[str, Any]:
    store = client.app.state.store  # type: ignore[union-attr]
    job = store.enqueue_job("rfy")
    store.record_scan(
        job["id"],
        [
            {
                "asin": asin,
                "title": "<script>alert(1)</script> network switch",
                "image_url": "https://m.media-amazon.com/images/test.jpg",
            }
        ],
    )
    return store.list_products()["items"][0]  # type: ignore[no-any-return]


def test_csrf_origin_host_and_expiry(client: TestClient) -> None:
    assert client.post("/api/jobs", json={"kind": "rfy"}).status_code == 202
    for headers in [
        {"X-CSRF-Token": ""},
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-CSRF-Token": "forged"},
    ]:
        assert client.post("/api/jobs", json={"kind": "rfy"}, headers=headers).status_code == 403
    assert client.get("/health", headers={"host": "attacker.example"}).status_code == 400
    token = csrf_token("key")
    assert valid_csrf(token, "key")
    assert not valid_csrf(token, "wrong-key")
    assert not valid_csrf("broken", "key")
    assert not valid_csrf("1." + "a" * 48 + ".sig", "key")
    assert not valid_csrf("99999999999." + "a" * 48 + ".sig", "key")
    assert not valid_csrf("1.short.sig", "key")
    assert (
        client.post("/api/jobs", content="{}", headers={"content-length": "invalid"}).status_code
        == 400
    )
    assert client.post("/api/jobs", content="x" * 2_000_001).status_code == 413
    assert (
        client.post(
            "/api/jobs", content="x" * 2_000_001, headers={"content-length": "0"}
        ).status_code
        == 413
    )


def test_discovery_trackers_settings_and_jobs(client: TestClient) -> None:
    item = product(client)
    result = client.get("/api/products", params={"query": "switch", "sort": "recent"})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert client.get("/api/products?query=nonexistent").json()["total"] == 0
    assert client.get("/api/products?limit=1001").status_code == 422
    tracker = client.post(
        "/api/trackers",
        json={
            "name": "Test networking",
            "phrases": ["network"],
            "phrase_weight": 80,
        },
    ).json()
    assert client.get(f"/api/products?tracker_id={tracker['id']}").json()["items"][0]["score"] >= 80
    assert (
        client.patch(f"/api/trackers/{tracker['id']}", json={"exclusions": ["switch"]}).status_code
        == 200
    )
    assert client.get(f"/api/products?tracker_id={tracker['id']}").json()["total"] == 0
    assert client.delete(f"/api/trackers/{tracker['id']}").status_code == 200
    assert client.delete(f"/api/trackers/{tracker['id']}").status_code == 404
    assert client.get("/api/trackers").json()
    assert client.patch("/api/settings", json={"collection_interval_minutes": 0}).status_code == 422
    settings = client.patch(
        "/api/settings",
        json={
            "collection_enabled": False,
            "notification_secret": "private-token",
            "notification_url": "https://notify.example/private-webhook",
        },
    ).json()
    assert settings["notification_secret"] == "***"
    assert "private-token" not in client.get("/api/settings").text
    assert "private-webhook" not in client.get("/api/export").text
    assert client.get("/api/settings").json()["collection_enabled"] is False
    assert client.post("/api/settings/reset").json()["collection_enabled"] is True
    job = client.post("/api/jobs", json={"kind": "search", "query": "network"}).json()
    assert client.get(f"/api/jobs/{job['id']}").json()["query"] == "network"
    assert client.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 422
    assert client.post("/api/jobs", json={"kind": "arbitrary-url"}).status_code == 422
    assert client.get("/api/jobs").json()
    assert client.get("/api/runs").json()[0]["status"] == "complete"
    assert client.get("/api/export").json()
    assert item["asin"] == "B0TEST0001"
    assert client.get("/health").json()["status"] == "ok"


def test_reviews_import_preview_and_progress_remain_distinct(client: TestClient) -> None:
    records = [
        {
            "title": "Test review item",
            "asin": "B0TEST0001",
            "order_date": "2026-10-01",
            "observed_status": "Awaiting review",
            "body": "NEVER-IMPORT-PRIVATE-DRAFT",
            "cookie": "NEVER-IMPORT-COOKIE",
            "review_url": "https://www.amazon.com/review/create-review",
        }
    ]
    preview = client.post("/api/reviews/import/preview", json={"records": records}).json()
    assert "NEVER-IMPORT" not in str(preview)
    assert (
        client.post(
            "/api/reviews/import", json={"records": records, "preview_hash": "invalid"}
        ).status_code
        == 422
    )
    imported = client.post(
        "/api/reviews/import", json={"records": records, "preview_hash": preview["preview_hash"]}
    )
    assert imported.status_code == 200
    review = client.get("/api/reviews?query=item").json()["items"][0]
    updated = client.patch(
        f"/api/reviews/{review['id']}", json={"local_progress": "submitted"}
    ).json()
    assert updated["local_progress"] == "submitted"
    assert updated["observed_status"] == "Awaiting review"
    assert client.get("/api/reviews?local_progress=submitted").json()["total"] == 1
    export = client.get("/api/reviews/export")
    assert "attachment" in export.headers["content-disposition"]
    assert "NEVER-IMPORT" not in export.text
    assert client.post("/api/reviews/import/preview", json={"records": "wrong"}).status_code == 422
    assert client.post("/api/reviews/import", json={"records": "wrong"}).status_code == 422
    assert (
        client.patch(
            f"/api/reviews/{review['id']}", json={"local_progress": "approved"}
        ).status_code
        == 422
    )


def test_retention_requires_explicit_confirmation_and_stopped_work(client: TestClient) -> None:
    product(client)
    assert client.post("/api/retention/preview", json={}).status_code == 200
    assert client.post("/api/retention/apply", json={}).status_code == 422
    assert (
        client.post("/api/retention/apply", json={"confirm": "DELETE HISTORY"}).status_code == 200
    )
    assert client.post("/api/data/delete", json={}).status_code == 422
    store = client.app.state.store  # type: ignore[union-attr]
    store.enqueue_job("afa")
    store.set_connection("connected")
    store.claim_job("test")
    assert client.post("/api/data/delete", json={"confirm": "DELETE ALL DATA"}).status_code == 422
    for job in store.list_jobs():
        if job["status"] == "running":
            store.update_job(job["id"], status="cancelled")
    assert client.post("/api/data/delete", json={"confirm": "DELETE ALL DATA"}).status_code == 200
    assert client.get("/api/products").json()["total"] == 0


def test_notification_test_requires_configured_destination(client: TestClient) -> None:
    assert client.post("/api/notifications/test").status_code == 422
    client.patch(
        "/api/settings",
        json={
            "notification_url": "http://127.0.0.1:12345/topic",
            "notifications_enabled": True,
        },
    )
    result = client.post("/api/notifications/test")
    assert result.status_code == 202
    assert client.get("/api/notifications").json()


def mock_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    original = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return original(*args, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("vine_search.web.httpx.AsyncClient", factory)


def test_login_lifecycle_capabilities_not_returned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Collector-Secret"] == "test-internal-secret"
        if request.url.path == "/login/start":
            return httpx.Response(
                200,
                json={
                    "id": "session123",
                    "capability": "private-capability",
                    "state": "waiting",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        if request.url.path.startswith("/viewer/"):
            assert request.url.params["capability"] == "private-capability"
            return httpx.Response(200, text="served viewer", headers={"content-type": "text/html"})
        return httpx.Response(200, json={"state": "connected"})

    mock_transport(monkeypatch, handler)
    assert client.get("/api/connection").json()["state"] == "connected"
    assert client.get("/api/connection/login/session123").status_code == 403
    assert client.get("/login-viewer/session123/vnc.html").status_code == 403
    started = client.post("/api/connection/login")
    assert started.status_code == 202
    assert "private-capability" not in started.text
    assert "HttpOnly" in started.headers["set-cookie"]
    assert started.json()["viewer_path"].startswith("/login-viewer/")
    viewer_url = httpx.URL("http://testserver" + started.json()["viewer_path"])
    assert viewer_url.params["path"] == "/login-viewer/session123/websockify"
    assert client.get("/login-viewer/session123/vnc.html").text == "served viewer"
    assert client.get("/api/connection/login/session123").json()["state"] == "connected"
    assert client.post("/api/connection/login/session123/cancel").status_code == 200
    assert client.get("/login-viewer/session123/vnc.html").status_code == 403
    assert client.post("/api/connection/disconnect", json={"forget": True}).status_code == 200
    assert requests[-1].content == b'{"forget":true}'


def test_collector_unavailable_and_failure_are_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SECRET_INTERNAL_ADDRESS")

    mock_transport(monkeypatch, handler)
    assert client.get("/api/connection").json()["collector_available"] is False
    response = client.post("/api/connection/login")
    assert response.status_code == 503
    assert "SECRET_INTERNAL_ADDRESS" not in response.text


def test_collector_error_response_and_viewer_expiration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_transport(monkeypatch, lambda _: httpx.Response(410, text="secret"))
    assert client.post("/api/connection/login").status_code == 410
    client.cookies.set("vine_login_capability", "expired")
    assert client.get("/login-viewer/expired/vnc.html").status_code == 410
    with (
        pytest.raises(WebSocketDisconnect) as denied,
        client.websocket_connect(
            "/login-viewer/expired/websockify", headers={"origin": "https://evil.example"}
        ),
    ):
        pytest.fail("Cross-origin websocket must never open")
    assert denied.value.code == 1008


@pytest.mark.parametrize(
    "url",
    [
        "http://m.media-amazon.com/a",
        "https://evil.example/a",
        "https://m.media-amazon.com.evil.example/a",
        "https://u:p@m.media-amazon.com/a",
        "https://m.media-amazon.com:8080/a",
        "https://m.media-amazon.com:invalid/a",
    ],
)
def test_image_host_allowlist(url: str) -> None:
    assert not image_url_allowed(url)


def test_image_proxy_caches_and_rejects_markup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = product(client)
    counter = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal counter
        counter += 1
        return httpx.Response(200, content=b"JPEG", headers={"content-type": "image/jpeg"})

    mock_transport(monkeypatch, handler)
    path = f"/api/products/{item['id']}/image"
    assert client.get(path).content == b"JPEG"
    assert client.get(path).content == b"JPEG"
    assert counter == 1
    assert client.get("/api/products/999/image").status_code == 404
    client.patch("/api/settings", json={"image_mode": "hidden"})
    assert client.get(path).status_code == 404


def test_config_requires_explicit_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="setup"):
        Config(data_dir=tmp_path, collector_secret="").prepare()


@pytest.mark.parametrize("resource", ["products", "reviews"])
def test_visibility_api_is_protected_validated_and_atomic(
    client: TestClient, resource: str
) -> None:
    item = product(client)
    store = client.app.state.store  # type: ignore[union-attr]
    if resource == "reviews":
        job = store.enqueue_job("reviews")
        store.record_review_scan(
            job["id"],
            [{"title": "Synthetic obligation", "asin": item["asin"], "external_id": "order-1"}],
        )
        item = store.list_reviews()["items"][0]
    record_id = item["id"]
    single = f"/api/{resource}/{record_id}/visibility"
    bulk = f"/api/{resource}/visibility"
    for path, method, body in (
        (single, "PATCH", {"hidden": True}),
        (bulk, "POST", {"ids": [record_id], "hidden": True}),
    ):
        assert (
            client.request(method, path, json=body, headers={"X-CSRF-Token": ""}).status_code == 403
        )
        assert (
            client.request(
                method, path, json=body, headers={"Origin": "https://attacker.example"}
            ).status_code
            == 403
        )
    for body in (
        {"hidden": "true"},
        {"hidden": True, "unexpected": "ignored"},
        {},
    ):
        assert client.patch(single, json=body).status_code == 422
    for body in (
        {"ids": [], "hidden": True},
        {"ids": [record_id] * 201, "hidden": True},
        {"ids": [record_id, record_id], "hidden": True},
        {"ids": [True], "hidden": True},
        {"ids": [str(record_id)], "hidden": True},
        {"ids": [record_id]},
    ):
        assert client.post(bulk, json=body).status_code == 422
    assert client.post(bulk, json={"ids": [record_id, 99999], "hidden": True}).status_code == 404
    assert client.get(f"/api/{resource}").json()["total"] == 1
    changed = client.patch(single, json={"hidden": True})
    assert changed.status_code == 200
    assert changed.json() == {"ids": [record_id], "hidden": True, "updated": 1}
    assert client.get(f"/api/{resource}").json()["total"] == 0
    hidden = client.get(f"/api/{resource}?visibility=hidden").json()["items"][0]
    assert hidden["id"] == record_id and hidden["hidden"] is True and hidden["hidden_at"]
    assert client.get(f"/api/{resource}?visibility=all").json()["total"] == 1
    assert client.get(f"/api/{resource}?visibility=deleted").status_code == 422
    assert client.post(bulk, json={"ids": [record_id], "hidden": False}).status_code == 200
    restored = client.get(f"/api/{resource}").json()["items"][0]
    assert restored["hidden"] is False and restored["hidden_at"] is None


def test_review_image_proxy_uses_fallback_cache_and_image_privacy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = product(client)
    store = client.app.state.store  # type: ignore[union-attr]
    job = store.enqueue_job("reviews")
    store.record_review_scan(
        job["id"],
        [{"title": "Synthetic review image", "asin": item["asin"], "external_id": "order"}],
    )
    review = client.get("/api/reviews").json()["items"][0]
    assert review["image_url"] == item["image_url"]
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"})

    mock_transport(monkeypatch, handler)
    path = f"/api/reviews/{review['id']}/image"
    assert client.get(path).content == b"PNG"
    assert client.get(path).content == b"PNG"
    assert client.get(f"/api/products/{item['id']}/image").content == b"PNG"
    assert requests == [item["image_url"]]
    client.patch("/api/settings", json={"image_mode": "hidden"})
    assert client.get(path).status_code == 404
    assert len(requests) == 1
    client.patch("/api/settings", json={"image_mode": "proxy"})
    with store.connect(write=True) as connection:
        connection.execute(
            "UPDATE reviews SET image_url='http://127.0.0.1/private' WHERE id=?", (review["id"],)
        )
    assert client.get(path).status_code == 404
    assert client.get("/api/reviews/99999/image").status_code == 404
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("status", "mime", "content"),
    [
        (302, "image/png", b"redirect"),
        (200, "text/html", b"<script>unsafe</script>"),
        (200, "image/jpeg", b"x" * 5_000_001),
    ],
)
def test_review_image_proxy_rejects_redirect_markup_and_oversize(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    mime: str,
    content: bytes,
) -> None:
    store = client.app.state.store  # type: ignore[union-attr]
    job = store.enqueue_job("reviews")
    store.record_review_scan(
        job["id"],
        [
            {
                "title": "Synthetic thumbnail",
                "external_id": "order",
                "image_url": "https://m.media-amazon.com/thumbnail.jpg",
            }
        ],
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            content=content,
            headers={"content-type": mime, "location": "http://127.0.0.1/private"},
        )

    mock_transport(monkeypatch, handler)
    assert client.get("/api/reviews/1/image").status_code == 502


def test_review_pagination_is_applied_after_visibility_filter(client: TestClient) -> None:
    store = client.app.state.store  # type: ignore[union-attr]
    job = store.enqueue_job("reviews")
    store.record_review_scan(
        job["id"],
        [{"external_id": f"order-{number}", "title": f"Review {number}"} for number in range(4)],
    )
    store.set_visibility("reviews", [1], True)
    response = client.get("/api/reviews?limit=1&offset=1").json()
    assert response["total"] == 3 and response["items"][0]["id"] == 3
    assert response["limit"] == response["offset"] == 1
    assert client.get("/api/reviews?limit=1&page=2").json()["items"][0]["id"] == 3
    assert client.get("/api/reviews?visibility=all&limit=1&offset=1").json()["items"][0]["id"] == 2
    assert client.get("/api/reviews?limit=501").status_code == 422


def test_product_details_api_uses_only_observed_locator_and_existing_job_polling(
    client: TestClient,
) -> None:
    item = product(client)
    store = client.app.state.store  # type: ignore[union-attr]
    path = f"/api/products/{item['id']}/details"
    assert client.post(path).status_code == 422  # No observed Vine page in this fixture yet.
    with store.connect(write=True) as connection:
        connection.execute(
            "UPDATE products SET vine_url=? WHERE id=?",
            ("https://www.amazon.com/vine/vine-items?queue=potluck", item["id"]),
        )
    assert client.post(path, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.post(path, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post(path, json={"vine_url": "https://evil.example"}).status_code == 422
    assert client.post("/api/products/99999/details").status_code == 404
    response = client.post(path)
    assert response.status_code == 202
    job = response.json()
    assert job["kind"] == "details" and job["payload"]["product_id"] == item["id"]
    assert client.post(path, json={}).json()["id"] == job["id"]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "queued"
    assert client.post(f"/api/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert client.post("/api/jobs", json={"kind": "details", "url": "arbitrary"}).status_code == 422


def test_full_tracker_editor_payload_saves_updates_and_failed_saves_preserve_state(
    client: TestClient,
) -> None:
    """Exercise the browser editor's entire serialized shape, not a partial API example."""
    payload = {
        "name": "Synthetic network rack",
        "query": "network rack",
        "phrases": ["network rack", "server rack"],
        "phrase_mode": "any",
        "exclusions": ["wine rack", "shoe rack"],
        "categories": [],
        "enabled": True,
        "schedule_enabled": True,
        "notify": True,
        "phrase_weight": 30,
        "category_weight": 20,
        "freshness_weight": 10,
        "min_score": 1,
        "freshness_hours": 168,
        "interval_minutes": 15,
        "page_budget": 5,
    }
    # Saving tracker alert preferences is allowed before a destination is configured.
    assert client.get("/api/settings").json()["notifications_enabled"] is False
    response = client.post("/api/trackers", json=payload)
    assert response.status_code == 201
    saved = response.json()
    assert {key: saved[key] for key in payload} == payload
    route = f"/api/trackers/{saved['id']}"
    changed = {
        **payload,
        "name": "Updated synthetic rack",
        "phrase_weight": 40,
        "schedule_enabled": False,
        "page_budget": 100,
    }
    response = client.patch(route, json=changed)
    assert response.status_code == 200
    persisted = next(
        item for item in client.get("/api/trackers").json() if item["id"] == saved["id"]
    )
    assert {key: persisted[key] for key in changed} == changed
    cases = [
        ({"schedule_enabled": True, "query": ""}, "live query"),
        ({"page_budget": 101}, "page_budget"),
        ({"freshness_hours": 0}, "freshness_hours"),
    ]
    for patch, error in cases:
        rejected = client.patch(route, json=patch)
        assert rejected.status_code == 422
        assert error in rejected.json()["detail"]
    rejected = client.patch(route, json={"name": "Must not save"}, headers={"X-CSRF-Token": ""})
    assert rejected.status_code == 403
    assert "Reload the page" in rejected.json()["detail"]
    assert (
        next(item for item in client.get("/api/trackers").json() if item["id"] == saved["id"])
        == persisted
    )
