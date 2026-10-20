from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from vine_search.amazon import ORIGIN
from vine_search.login import BrowserOwner, LoginController, OwnershipError, VirtualDesktop


class FakeDesktop:
    http_port = 6080

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class LoginPage:
    def __init__(self) -> None:
        self.url = f"{ORIGIN}/ap/signin?return_to=/vine/vine-items"
        self.html = "<input id='ap_password'>"
        self.gotos: list[str] = []

    async def goto(self, url: str, **_: Any) -> None:
        self.gotos.append(url)

    async def content(self) -> str:
        return self.html


class FakeOwner(BrowserOwner):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.page = LoginPage()
        self.closed = False
        self.entered = asyncio.Event()
        self.browser_error: Exception | None = None
        self.pages = [self.page]

    async def new_page(self) -> LoginPage:
        return self.page

    @asynccontextmanager
    async def browser(self, *, headed: bool = False) -> AsyncIterator[Any]:
        if self.browser_error:
            raise self.browser_error
        self.entered.set()
        try:
            yield self
        finally:
            self.closed = True


def controller(
    tmp_path: Path, *, timeout: float = 5
) -> tuple[LoginController, FakeOwner, list[Any], FakeDesktop]:
    owner = FakeOwner(tmp_path)
    states: list[Any] = []
    desktop = FakeDesktop()
    login = LoginController(
        owner,
        lambda state, **kwargs: states.append((state, kwargs)),
        timeout=timeout,
        desktop_factory=lambda: desktop,  # type: ignore[arg-type]
    )
    return login, owner, states, desktop


def test_process_lock_prevents_second_collector_and_releases(tmp_path: Path) -> None:
    first, second = BrowserOwner(tmp_path), BrowserOwner(tmp_path)
    first.acquire_process()
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    with pytest.raises(OwnershipError):
        second.acquire_process()
    first.release_process()
    second.acquire_process()
    second.release_process()
    second.release_process()


async def test_login_waits_for_browser_ownership_then_cancels_cleanly(tmp_path: Path) -> None:
    login, owner, states, desktop = controller(tmp_path)
    async with owner.claim("existing-job"):
        first = await login.start()
        again = await login.start()
        assert first["id"] == again["id"]
        await asyncio.sleep(0)
        assert login.public()["state"] == "waiting"
        assert not desktop.started
        assert owner.current == "existing-job"
    await owner.entered.wait()
    assert desktop.started
    assert owner.current == "login"
    assert login.valid(first["id"], first["capability"], viewer=True)
    await login.cancel()
    assert owner.current is None and owner.closed and desktop.stopped
    assert login.public()["state"] == "cancelled"
    assert states[-1][0] == "needs_login"
    assert not login.valid(first["id"], first["capability"], viewer=True)


async def test_completion_requires_actual_host_and_vine_ui_and_closes_viewer(
    tmp_path: Path,
) -> None:
    login, owner, states, desktop = controller(tmp_path)
    owner.page.html = "<div id='vvp-items-grid'>No items available</div>"
    owner.page.url = "https://phishing.example/vine/vine-items"
    await login.start()
    await owner.entered.wait()
    await asyncio.sleep(0)
    assert login.public()["state"] == "ready"
    assert all(state[0] != "connected" for state in states)
    owner.page.url = f"{ORIGIN}/vine/vine-items"
    assert login.task
    await asyncio.wait_for(login.task, timeout=2)
    assert login.public()["state"] == "connected"
    assert states[-1][0] == "connected" and states[-1][1]["last_success"]
    assert owner.closed and desktop.stopped
    assert "capability" not in login.public()


async def test_timeout_expires_capability_and_reconnect_gets_new_capability(tmp_path: Path) -> None:
    login, owner, states, desktop = controller(tmp_path, timeout=0.02)
    first = await login.start()
    assert login.task
    await login.task
    assert login.public()["state"] == "expired"
    assert owner.closed and desktop.stopped
    assert not login.valid(first["id"], first["capability"])
    assert states[-1][0] == "needs_login"
    second = await login.start()
    assert second["capability"] != first["capability"]
    await login.cancel()


async def test_login_failure_is_sanitized_and_releases_lock(tmp_path: Path) -> None:
    login, owner, states, desktop = controller(tmp_path)
    owner.browser_error = RuntimeError("password=secret must not appear")
    await login.start()
    assert login.task
    await login.task
    assert login.public()["state"] == "failed"
    assert "secret" not in login.public()["message"]
    assert states[-1][0] == "failed"
    assert owner.current is None and desktop.stopped


async def test_capability_checks_and_forget_preserve_other_files(tmp_path: Path) -> None:
    login, owner, _, _ = controller(tmp_path)
    assert login.public() == {"state": "idle"}
    assert not login.valid("bad", "bad")
    first = await login.start()
    assert not login.valid("bad", first["capability"])
    assert not login.valid(first["id"], "bad")
    assert not login.valid(first["id"], first["capability"], viewer=True)
    await login.cancel()
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "Cookies").write_text("synthetic")
    (tmp_path / "imported-state.sha256").write_text("synthetic")
    (tmp_path / "other").write_text("preserve")
    await owner.forget()
    assert not (tmp_path / "profile").exists()
    assert not (tmp_path / "imported-state.sha256").exists()
    assert (tmp_path / "other").read_text() == "preserve"
    await owner.forget()


async def test_explicit_auth_import_filters_domains_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = BrowserOwner(tmp_path / "private")
    owner.acquire_process()
    source = tmp_path / "authorized.json"
    source.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "session-id", "domain": ".amazon.com", "value": "synthetic"},
                    {"name": "unrelated", "domain": ".unrelated.example", "value": "excluded"},
                ]
            }
        )
    )
    monkeypatch.setenv("VINE_SEARCH_AUTH_FILE", str(source))
    browser = AsyncMock()
    await owner._import_authorized_state(browser)
    assert browser.add_cookies.call_args.args[0] == [
        {"name": "session-id", "domain": ".amazon.com", "value": "synthetic"}
    ]
    await owner._import_authorized_state(browser)
    assert browser.add_cookies.await_count == 1
    source.write_text('{"cookies":[]}')
    with pytest.raises(ValueError, match="no browser cookies"):
        await owner._import_authorized_state(browser)
    source.write_text('{"cookies":[{"domain":"evil.example"}]}')
    with pytest.raises(ValueError, match=r"no Amazon\.com cookies"):
        await owner._import_authorized_state(browser)
    monkeypatch.delenv("VINE_SEARCH_AUTH_FILE")
    await owner._import_authorized_state(browser)
    owner.release_process()


async def test_virtual_desktop_stops_children_on_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = AsyncMock()
    process.returncode = 1
    process.pid = 999999
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    desktop = VirtualDesktop()
    with pytest.raises(RuntimeError, match="could not start"):
        await desktop.start()
    assert desktop.processes == []
    assert spawn.call_args.args[0] == "Xvfb"


async def test_claim_cleanup_on_exception(tmp_path: Path) -> None:
    owner = BrowserOwner(tmp_path)
    with pytest.raises(ValueError):
        async with owner.claim("job"):
            assert owner.current == "job"
            raise ValueError("test")
    assert owner.current is None and not owner.lock.locked()


async def test_expiry_disallows_viewer_even_before_timeout_task_runs(tmp_path: Path) -> None:
    login, _, _, _ = controller(tmp_path)
    value = await login.start()
    assert login.session
    login.session["deadline"] = time.monotonic() - 1
    assert not login.valid(value["id"], value["capability"])
    await login.cancel()


async def test_immediate_cancel_cannot_leave_connecting_state(tmp_path: Path) -> None:
    login, _, states, _ = controller(tmp_path)
    await login.start()
    await login.cancel()
    assert login.public()["state"] == "cancelled"
    assert not login.active
    assert states[-1][0] == "needs_login"


async def test_forget_prevents_automatic_reimport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = BrowserOwner(tmp_path)
    monkeypatch.setenv("VINE_SEARCH_AUTH_FILE", str(tmp_path / "external-not-readable"))
    await owner.forget()
    browser = AsyncMock()
    await owner._import_authorized_state(browser)
    browser.add_cookies.assert_not_called()
    assert (tmp_path / "import-disabled").exists()


async def test_persistent_browser_is_sandboxed_and_closes_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vine_search.login as module

    context = AsyncMock()
    context.storage_state.return_value = {
        "cookies": [
            {"domain": ".amazon.com", "name": "session", "value": "synthetic"},
            {"domain": "unrelated.example", "name": "irrelevant", "value": "excluded"},
        ],
        "origins": [{"origin": "https://unrelated.example", "localStorage": []}],
    }
    engine = AsyncMock()
    engine.chromium.launch_persistent_context.return_value = context
    manager = AsyncMock()
    manager.__aenter__.return_value = engine
    monkeypatch.setattr(module, "async_playwright", lambda: manager)
    monkeypatch.delenv("VINE_SEARCH_AUTH_FILE", raising=False)
    owner = BrowserOwner(tmp_path)
    with pytest.raises(RuntimeError):
        async with owner.browser(headed=True):
            raise RuntimeError("controlled caller failure")
    arguments = engine.chromium.launch_persistent_context.call_args
    assert arguments.args[0] == str(tmp_path / "profile")
    assert arguments.kwargs["chromium_sandbox"] is True
    assert arguments.kwargs["headless"] is False
    assert arguments.kwargs["accept_downloads"] is False
    context.close.assert_awaited_once()
    saved = tmp_path / "session-state.json"
    snapshot = json.loads(saved.read_text())
    assert snapshot["origins"] == []
    assert snapshot["cookies"] == [
        {"domain": ".amazon.com", "name": "session", "value": "synthetic"}
    ]
    assert saved.stat().st_mode & 0o777 == 0o600
    async with owner.browser():
        pass
    context.add_cookies.assert_awaited_once_with(snapshot["cookies"])
    await owner.forget()
    assert not saved.exists()


async def test_virtual_desktop_success_and_shutdown_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vine_search.login as module

    processes = [AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()]
    for index, process in enumerate(processes):
        process.returncode = None
        process.pid = 900001 + index
    processes[0].wait.side_effect = [TimeoutError(), 0]
    spawn = AsyncMock(side_effect=processes)
    writer = AsyncMock()
    writer.close = lambda: None
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(asyncio, "open_connection", AsyncMock(return_value=(None, writer)))
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    kills: list[tuple[int, Any]] = []
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: kills.append((pid, sig)))
    desktop = VirtualDesktop()
    await desktop.start()
    assert len(desktop.processes) == 4
    assert "127.0.0.1:6080" in spawn.call_args.args
    await desktop.stop()
    assert desktop.processes == []
    assert len(kills) == 5
