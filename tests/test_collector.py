from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from test_amazon import CATALOG, REVIEW_URL, REVIEWS, URL, FakePage, next_link
from test_login import FakeDesktop, FakeOwner
from vine_search.amazon import review_sections
from vine_search.collector import Collector, create_app
from vine_search.login import BrowserOwner, LoginController
from vine_search.store import Store

SECRET = "test-collector-secret-never-used-in-production"
HEADERS = {"X-Collector-Secret": SECRET}


def make_worker(tmp_path: Path, documents: dict[str, str | Exception]) -> Collector:
    store = Store(tmp_path / "database.sqlite3")
    owner = FakeOwner(tmp_path / "session")
    owner.pages = [FakePage(documents)]  # type: ignore[list-item]
    return Collector(store, owner)


async def test_collector_commits_pages_identity_and_repeated_sightings(tmp_path: Path) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    worker.store.set_connection("connected")
    job = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed and claimed["id"] == job["id"]
    result = await worker.execute(claimed)
    assert result.status == "complete"
    assert worker.store.get_job(job["id"])["status"] == "complete"
    assert worker.store.list_products()["total"] == 1
    second = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    await worker.execute(claimed)
    assert worker.store.get_job(second["id"])["status"] == "complete"
    assert worker.store.list_products()["total"] == 1
    assert len(worker.store.list_runs()) == 2


async def test_collector_honors_queued_snapshot_budget(tmp_path: Path) -> None:
    second = URL + "&page=2"
    worker = make_worker(tmp_path, {URL: CATALOG + next_link(second), second: CATALOG})
    worker.store.set_connection("connected")
    job = worker.store.enqueue_job("rfy", payload={"page_budget": 1})
    worker.store.update_settings({"page_budget": 10})
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    result = await worker.execute(claimed)
    assert result.status == "truncated" and result.pages == 1
    assert worker.store.get_job(job["id"])["status"] == "truncated"
    assert worker.store.list_runs()[0]["pages"] == 1


async def test_expired_login_pauses_jobs_without_erasing_history(tmp_path: Path) -> None:
    worker = make_worker(tmp_path, {URL: "<input id='captchacharacters'>"})
    worker.store.set_connection("connected")
    first = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    result = await worker.execute(claimed)
    assert result.status == "needs_login"
    assert worker.store.get_connection()["state"] == "challenge"
    assert worker.store.get_job(first["id"])["status"] == "needs_login"
    second = worker.store.enqueue_job("afa")
    assert worker.store.claim_job(worker.worker_id) is None
    assert worker.store.get_job(second["id"])["status"] == "queued"


async def test_browser_failure_is_sanitized_and_cancelled_job_never_opens_browser(
    tmp_path: Path,
) -> None:
    worker = make_worker(tmp_path, {})
    assert isinstance(worker.owner, FakeOwner)
    worker.owner.browser_error = RuntimeError("private_cookie=do-not-log")
    worker.store.set_connection("connected")
    job = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    result = await worker.execute(claimed)
    assert result.status == "failed"
    assert "do-not-log" not in str(worker.store.get_job(job["id"]))
    cancelled = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    worker.store.update_job(cancelled["id"], status="cancelled")
    assert (await worker.execute(claimed)).status == "cancelled"


async def test_reviews_record_both_sources_and_actual_status(tmp_path: Path) -> None:
    sections = review_sections(REVIEWS, REVIEW_URL)
    worker = make_worker(
        tmp_path, {REVIEW_URL: REVIEWS, **dict.fromkeys(sections.values(), REVIEWS)}
    )
    worker.store.set_connection("connected")
    worker.store.enqueue_job("reviews")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    result = await worker.execute(claimed)
    assert result.status == "complete" and result.pages == 2
    records = worker.store.list_reviews()["items"]
    assert records[0]["observed_status"] == "Pending approval"
    assert records[0]["local_progress"] == "not_started"


async def test_connection_check_proves_page_not_profile_existence(tmp_path: Path) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    assert await worker.check_connection()
    assert worker.store.get_connection()["state"] == "connected"
    worker.owner.pages[0].documents[URL] = "<input id='ap_email'>"  # type: ignore[attr-defined]
    assert not await worker.check_connection()
    assert worker.store.get_connection()["state"] == "needs_login"
    assert isinstance(worker.owner, FakeOwner)
    worker.owner.browser_error = RuntimeError("private state")
    assert not await worker.check_connection()
    assert worker.store.get_connection()["state"] == "failed"


async def test_worker_start_stop_and_queued_restart_recovery(tmp_path: Path) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    worker.store.set_connection("connected")
    await worker.start()
    assert worker.store.get_connection()["state"] == "needs_login"
    await worker.stop()
    assert not worker.owner.lock.locked()
    replacement = BrowserOwner(worker.owner.session_dir)
    replacement.acquire_process()
    replacement.release_process()


async def test_internal_api_requires_secret_and_caps_are_never_returned_by_read(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "database.sqlite3")
    owner = FakeOwner(tmp_path / "session")
    app = create_app(store=store, owner=owner, secret=SECRET, run_worker=False)
    desktop = FakeDesktop()
    app.state.collector.login = LoginController(
        owner,
        store.set_connection,
        desktop_factory=lambda: desktop,  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://collector") as client:
        assert (await client.get("/health")).status_code == 403
        assert (await client.get("/health", headers=HEADERS)).json()["status"] == "ok"
        first = (await client.post("/login/start", headers=HEADERS)).json()
        await owner.entered.wait()
        read = (await client.get("/connection", headers=HEADERS)).json()
        assert "capability" not in read["login"]
        assert read["state"] == "connecting"
        path = f"/login/{first['id']}"
        assert (await client.get(path, headers=HEADERS)).status_code == 410
        assert (
            await client.get(path, params={"capability": first["capability"]}, headers=HEADERS)
        ).json()["state"] == "ready"
        cancelled = await client.post(
            path + "/cancel", params={"capability": first["capability"]}, headers=HEADERS
        )
        assert cancelled.json()["state"] == "cancelled"
        viewer = await client.get(
            f"/viewer/{first['id']}/vnc.html",
            params={"capability": first["capability"]},
            headers=HEADERS,
        )
        assert viewer.status_code == 410
        response = await client.post("/disconnect", json={"forget": True}, headers=HEADERS)
        assert response.json()["state"] == "disconnected"


def test_secret_required_and_websocket_access_denied(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="24 characters"):
        create_app(secret="short")
    app = create_app(store=Store(tmp_path / "db.sqlite3"), secret=SECRET, run_worker=False)
    from starlette.websockets import WebSocketDisconnect

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/viewer/none/websockify"),
    ):
        pass


async def test_login_viewer_assets_proxy_only_when_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "database.sqlite3")
    app = create_app(store=store, secret=SECRET, run_worker=False)
    login = app.state.collector.login
    login.session = {
        "id": "test-session",
        "capability": "test-capability",
        "state": "ready",
        "deadline": time.monotonic() + 60,
    }
    response = httpx.Response(
        200, content=b"<html>real asset</html>", headers={"content-type": "text/html"}
    )
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = response
    real_client = httpx.AsyncClient
    monkeypatch.setattr("vine_search.collector.httpx.AsyncClient", lambda **kwargs: mock_client)
    async with real_client(
        transport=httpx.ASGITransport(app=app), base_url="http://collector"
    ) as client:
        asset = await client.get(
            "/viewer/test-session/vnc.html?capability=test-capability", headers=HEADERS
        )
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "no-store"
        assert mock_client.get.call_args.args[0] == "http://127.0.0.1:6080/vnc.html"
        denied = await client.get("/viewer/test-session/vnc.html?capability=bad", headers=HEADERS)
        assert denied.status_code == 410


async def test_loop_does_not_claim_during_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker(tmp_path, {})
    worker.store.set_connection("connected")
    worker.login.session = {"state": "ready"}
    original = worker.store.claim_job
    calls: list[str] = []

    def claim(identifier: str, **kwargs: Any) -> Any:
        calls.append(identifier)
        return original(identifier, **kwargs)

    monkeypatch.setattr(worker.store, "claim_job", claim)
    task = asyncio.create_task(worker.loop())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == []
    assert worker.store.list_jobs()


def test_websocket_bridges_binary_and_text_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(store=Store(tmp_path / "db.sqlite3"), secret=SECRET, run_worker=False)
    app.state.collector.login.session = {
        "id": "socket-session",
        "capability": "socket-capability",
        "state": "ready",
        "deadline": time.monotonic() + 60,
    }
    received: list[Any] = []

    class Upstream:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *_: Any) -> None:
            pass

        async def send(self, value: Any) -> None:
            received.append(value)

        async def __aiter__(self) -> Any:
            yield b"binary-screen-data"
            yield "text-control-data"
            await asyncio.Event().wait()

    monkeypatch.setattr("vine_search.collector.connect", lambda *args, **kwargs: Upstream())
    with (
        TestClient(app) as client,
        client.websocket_connect(
            "/viewer/socket-session/websockify?capability=socket-capability",
            headers=HEADERS,
            subprotocols=["binary"],
        ) as socket,
    ):
        assert socket.accepted_subprotocol == "binary"
        socket.send_bytes(b"pointer-event")
        assert socket.receive_bytes() == b"binary-screen-data"
        assert socket.receive_text() == "text-control-data"
        socket.send_text("keyboard-event")
    assert b"pointer-event" in received


async def test_loop_executes_job_and_scheduler_failure_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    worker.store.set_connection("connected")
    first = worker.store.enqueue_job("rfy")
    original = worker.execute

    async def execute(job: dict[str, Any]) -> Any:
        result = await original(job)
        worker.stopping.set()
        return result

    monkeypatch.setattr(worker, "execute", execute)
    await worker.loop()
    assert worker.store.get_job(first["id"])["status"] == "complete"
    worker.stopping.clear()

    def failed_schedule() -> None:
        raise ValueError("controlled")

    monkeypatch.setattr(worker.store, "schedule_due", failed_schedule)
    task = asyncio.create_task(worker.loop())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.store.get_connection()["state"] == "failed"


def test_app_lifespan_acquires_and_releases_process_lock(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite3")
    owner = BrowserOwner(tmp_path / "session")
    app = create_app(store=store, owner=owner, secret=SECRET, run_worker=True)
    with TestClient(app) as client:
        assert client.get("/connection", headers=HEADERS).status_code == 200
        assert owner._lock_file is not None
    assert owner._lock_file is None


async def test_heartbeat_extends_running_job_and_cancellation_retains_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    worker.store.set_connection("connected")
    job = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    original_sleep = asyncio.sleep
    original_heartbeat = worker.store.heartbeat_job
    beats: list[int] = []

    async def short_sleep(seconds: float) -> None:
        await original_sleep(0.001 if seconds == 15 else seconds)

    def heartbeat(job_id: int, worker_id: str, progress: Any = None) -> None:
        beats.append(job_id)
        original_heartbeat(job_id, worker_id, progress)

    page = worker.owner.pages[0]  # type: ignore[attr-defined]
    original_goto = page.goto

    async def delayed_goto(url: str, **kwargs: Any) -> None:
        await original_sleep(0.02)
        worker.store.update_job(job["id"], status="cancelled")
        await original_goto(url, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", short_sleep)
    monkeypatch.setattr(worker.store, "heartbeat_job", heartbeat)
    monkeypatch.setattr(page, "goto", delayed_goto)
    result = await worker.execute(claimed)
    assert beats
    assert result.status == "cancelled"
    assert worker.store.list_products()["total"] == 1
    assert worker.store.get_job(job["id"])["status"] == "cancelled"
    with pytest.raises(ValueError, match="Job already completed"):
        worker.store.record_scan(job["id"], result.products, status="cancelled")
    assert len(worker.store.list_runs()) == 1


async def test_interrupted_browser_retains_durable_claim_for_recovery(tmp_path: Path) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    worker.store.set_connection("connected")
    job = worker.store.enqueue_job("rfy")
    claimed = worker.store.claim_job(worker.worker_id)
    assert claimed
    await worker.owner.lock.acquire()
    task = asyncio.create_task(worker.execute(claimed))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    worker.owner.lock.release()
    assert worker.store.get_job(job["id"])["status"] == "running"
    assert worker.store.list_runs() == []


async def test_explicit_disconnect_survives_restart_with_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_worker(tmp_path, {URL: CATALOG})
    (worker.owner.session_dir / "profile").mkdir(parents=True)
    (worker.owner.session_dir / "disconnected").write_text("operator choice")
    check = AsyncMock()
    monkeypatch.setattr(worker, "check_connection", check)
    await worker.start()
    check.assert_not_awaited()
    assert worker.store.get_connection()["state"] == "disconnected"
    await worker.stop()


async def test_reconnect_clears_deliberate_disconnect_marker(tmp_path: Path) -> None:
    owner = FakeOwner(tmp_path)
    (tmp_path / "disconnected").write_text("operator choice")
    login = LoginController(owner, lambda *args, **kwargs: None)
    await login.start()
    assert not (tmp_path / "disconnected").exists()
    await login.cancel()
