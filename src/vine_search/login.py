"""Temporary remote Amazon login, owned exclusively by the collector process."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import signal
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, async_playwright

from vine_search.amazon import ORIGIN, signed_in_vine


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class OwnershipError(RuntimeError):
    """Another collector owns this installation's dedicated browser."""


class BrowserOwner:
    """Cross-process file lock plus a per-process job/login mutex.

    Never point ``session_dir`` at an everyday browser profile.
    """

    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.lock = asyncio.Lock()
        self._lock_file: Any = None
        self.current: str | None = None

    def acquire_process(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.session_dir, 0o700)
        self._lock_file = (self.session_dir / "collector.lock").open("a")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lock_file.close()
            self._lock_file = None
            raise OwnershipError("Another collector owns this browser session") from exc

    def release_process(self) -> None:
        if self._lock_file is not None:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None

    @asynccontextmanager
    async def claim(self, name: str) -> AsyncIterator[None]:
        async with self.lock:
            self.current = name
            try:
                yield
            finally:
                self.current = None

    @asynccontextmanager
    async def browser(self, *, headed: bool = False) -> AsyncIterator[BrowserContext]:
        profile = self.session_dir / "profile"
        async with async_playwright() as engine:
            browser = await engine.chromium.launch_persistent_context(
                str(profile),
                headless=not headed,
                chromium_sandbox=True,
                viewport=None if headed else {"width": 1280, "height": 900},
                no_viewport=headed,
                accept_downloads=False,
                args=["--disable-dev-shm-usage", *(["--start-maximized"] if headed else [])],
            )
            try:
                saved = self.session_dir / "session-state.json"
                if saved.exists():
                    await browser.add_cookies(json.loads(saved.read_text()).get("cookies", []))
                await self._import_authorized_state(browser)
                yield browser
            finally:
                # Chromium drops session cookies on a normal profile close. Keep
                # a private Playwright snapshot so dedicated login survives that close.
                with contextlib.suppress(Exception):
                    state = await browser.storage_state()
                    state["cookies"] = [
                        cookie
                        for cookie in state.get("cookies", [])
                        if str(cookie.get("domain", "")).lstrip(".")
                        in {"amazon.com", "www.amazon.com"}
                    ]
                    state["origins"] = []
                    staged = self.session_dir / "session-state.tmp"
                    staged.write_text(json.dumps(state))
                    os.chmod(staged, 0o600)
                    staged.replace(self.session_dir / "session-state.json")
                await browser.close()

    async def _import_authorized_state(self, browser: BrowserContext) -> None:
        auth_path = os.environ.get("VINE_SEARCH_AUTH_FILE")
        if not auth_path or (self.session_dir / "import-disabled").exists():
            return
        source = Path(auth_path)
        # Explicitly supplied advanced handoff only; never discover browser profiles.
        raw = source.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest()
        marker = self.session_dir / "imported-state.sha256"
        if marker.exists() and marker.read_text().strip() == fingerprint:
            return
        state = json.loads(raw)
        cookies = state.get("cookies", [])
        if not isinstance(cookies, list) or not cookies:
            raise ValueError("Authorized state file has no browser cookies")
        amazon_cookies = [
            cookie
            for cookie in cookies
            if str(cookie.get("domain", "")).lstrip(".") in {"amazon.com", "www.amazon.com"}
        ]
        if not amazon_cookies:
            raise ValueError("Authorized state file has no Amazon.com cookies")
        await browser.add_cookies(amazon_cookies)
        marker.write_text(fingerprint)
        os.chmod(marker, 0o600)

    async def forget(self) -> None:
        async with self.claim("disconnect"):
            for name in (
                "profile",
                "session-state.json",
                "session-state.tmp",
                "imported-state.sha256",
            ):
                path = self.session_dir / name
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            if os.environ.get("VINE_SEARCH_AUTH_FILE"):
                # A forget request must not silently restore the same external handoff.
                (self.session_dir / "import-disabled").write_text("Forgotten by the operator\n")


class VirtualDesktop:
    """Start only for a login; all viewer sockets bind container loopback."""

    def __init__(self) -> None:
        self.processes: list[asyncio.subprocess.Process] = []
        self.display = os.environ.get("VINE_SEARCH_DISPLAY", ":99")
        self.http_port = int(os.environ.get("VINE_SEARCH_VIEWER_PORT", "6080"))
        self.vnc_port = int(os.environ.get("VINE_SEARCH_VNC_PORT", "5900"))

    async def start(self) -> None:
        commands = [
            ["Xvfb", self.display, "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
            ["openbox", "--sm-disable"],
            [
                "x11vnc",
                "-display",
                self.display,
                "-localhost",
                "-rfbport",
                str(self.vnc_port),
                "-nopw",
                "-shared",
                "-forever",
                "-quiet",
            ],
            [
                "websockify",
                "--web=/usr/share/novnc",
                f"127.0.0.1:{self.http_port}",
                f"127.0.0.1:{self.vnc_port}",
            ],
        ]
        os.environ["DISPLAY"] = self.display
        try:
            for command in commands:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
                self.processes.append(process)
                await asyncio.sleep(0.25)
                if process.returncode is not None:
                    raise RuntimeError("The temporary browser viewer could not start")
            for _ in range(40):
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", self.http_port)
                    del reader
                    writer.close()
                    await writer.wait_closed()
                    return
                except OSError:
                    await asyncio.sleep(0.1)
            raise RuntimeError("The temporary browser viewer did not become available")
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        for process in reversed(self.processes):
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
        self.processes.clear()


class LoginController:
    def __init__(
        self,
        owner: BrowserOwner,
        connection_update: Callable[..., Any],
        *,
        timeout: float = 600,
        desktop_factory: Callable[[], VirtualDesktop] = VirtualDesktop,
    ) -> None:
        self.owner = owner
        self.connection_update = connection_update
        self.timeout = timeout
        self.desktop_factory = desktop_factory
        self.session: dict[str, Any] | None = None
        self.task: asyncio.Task[None] | None = None
        self.desktop: VirtualDesktop | None = None

    @property
    def active(self) -> bool:
        return self.session is not None and self.session["state"] in {
            "waiting",
            "starting",
            "ready",
            "challenge",
        }

    async def start(self) -> dict[str, Any]:
        if self.active:
            return self.public(include_capability=True)
        (self.owner.session_dir / "disconnected").unlink(missing_ok=True)
        self.session = {
            "id": secrets.token_urlsafe(18),
            "capability": secrets.token_urlsafe(32),
            "expires_at": datetime.fromtimestamp(time.time() + self.timeout, UTC).isoformat(),
            "deadline": time.monotonic() + self.timeout,
            "state": "waiting",
            "message": "Waiting for the current browser operation to finish.",
        }
        self.connection_update("connecting", message="Opening the dedicated Amazon login browser.")
        self.task = asyncio.create_task(self._run())
        return self.public(include_capability=True)

    def public(self, *, include_capability: bool = False) -> dict[str, Any]:
        if self.session is None:
            return {"state": "idle"}
        result = {
            key: value
            for key, value in self.session.items()
            if key not in {"deadline", "capability"}
        }
        result["viewer_path"] = f"/viewer/{self.session['id']}/vnc.html"
        if include_capability:
            result["capability"] = self.session["capability"]
        return result

    def valid(self, session_id: str, capability: str, *, viewer: bool = False) -> bool:
        if not self.session or session_id != self.session["id"]:
            return False
        if not secrets.compare_digest(capability, self.session["capability"]):
            return False
        if time.monotonic() >= self.session["deadline"]:
            return False
        return not (viewer and self.session["state"] not in {"ready", "challenge"})

    async def cancel(self) -> dict[str, Any]:
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.active:
            # Cancellation can arrive before the task has entered its try/finally.
            assert self.session is not None
            self.session.update(state="cancelled", message="Login cancelled.")
            self.connection_update(
                "needs_login", message="Login cancelled; existing history is preserved."
            )
        return self.public()

    async def _run(self) -> None:
        assert self.session is not None
        try:
            async with asyncio.timeout(self.timeout):
                async with self.owner.claim("login"):
                    self.session.update(state="starting", message="Starting the temporary browser.")
                    self.desktop = self.desktop_factory()
                    await self.desktop.start()
                    async with self.owner.browser(headed=True) as browser:
                        page = browser.pages[0] if browser.pages else await browser.new_page()
                        await page.goto(
                            f"{ORIGIN}/vine/vine-items?queue=potluck",
                            wait_until="domcontentloaded",
                            timeout=45_000,
                        )
                        self.session.update(
                            state="ready", message="Sign into Amazon in the secure browser below."
                        )
                        while True:
                            for candidate in list(browser.pages):
                                if signed_in_vine(await candidate.content(), str(candidate.url)):
                                    self.session.update(
                                        state="connected",
                                        message="Signed-in Amazon Vine access verified.",
                                    )
                                    self.connection_update(
                                        "connected",
                                        message="Signed-in Amazon Vine access verified.",
                                        last_success=utc_now(),
                                    )
                                    return
                            await asyncio.sleep(1)
        except TimeoutError:
            self.session.update(
                state="expired",
                message="The login window expired. Open a new login browser to retry.",
            )
            self.connection_update("needs_login", message=self.session["message"])
        except asyncio.CancelledError:
            self.session.update(state="cancelled", message="Login cancelled.")
            self.connection_update(
                "needs_login", message="Login cancelled; existing history is preserved."
            )
        except Exception as exc:
            self.session.update(
                state="failed",
                message=f"Login browser failed ({type(exc).__name__}). Try connecting again.",
            )
            self.connection_update("failed", message=self.session["message"])
        finally:
            if self.desktop:
                await self.desktop.stop()
                self.desktop = None
