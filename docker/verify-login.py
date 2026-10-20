"""Exercise the actual served noVNC login with a clearly synthetic Amazon page.

Run inside the shipped Linux image. This uses disposable directories and routes
all observer requests locally; it never touches the installation's real session.
It is browser/transport evidence, not actual Amazon or physical-phone evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import uvicorn
from playwright.async_api import BrowserContext, Route, async_playwright

from vine_search.amazon import ORIGIN, load_page, signed_in_vine
from vine_search.collector import create_app as collector_app
from vine_search.config import Config
from vine_search.login import BrowserOwner
from vine_search.store import Store
from vine_search.web import create_app as web_app

LOGIN_HTML = """<!doctype html><html><body style="font:24px sans-serif;padding:80px">
<h1>Synthetic Amazon login fixture</h1><p>No account credentials are requested.</p>
<form action="/vine/vine-items" onsubmit="document.cookie='fixture_signed_in=yes; path=/'">
<label>Type fixture, then press Enter <input id="fixture-input" autofocus></label>
<button>Continue</button></form></body></html>"""
VINE_HTML = """<!doctype html><html><body><h1>Synthetic Vine fixture</h1>
<div id="vvp-items-grid">No items available</div></body></html>"""


class FixtureOwner(BrowserOwner):
    active_context: BrowserContext | None = None

    @asynccontextmanager
    async def browser(self, *, headed: bool = False) -> AsyncIterator[BrowserContext]:
        async with super().browser(headed=headed) as context:

            async def route(request: Route) -> None:
                if urlparse(request.request.url).hostname != "www.amazon.com":
                    await request.abort()
                    return
                cookies = await request.request.all_headers()
                html = (
                    VINE_HTML
                    if "fixture_signed_in=yes" in cookies.get("cookie", "")
                    else LOGIN_HTML
                )
                await request.fulfill(status=200, content_type="text/html", body=html)

            await context.route("**/*", route)
            self.active_context = context
            try:
                yield context
            finally:
                self.active_context = None


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def serve(app: Any, port: int) -> tuple[uvicorn.Server, asyncio.Task[None]]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    )
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            return server, task
        if task.done():
            await task
            raise RuntimeError("Fixture service failed to start")
        await asyncio.sleep(0.05)
    raise RuntimeError("Fixture service startup timed out")


async def main() -> None:
    os.environ["VINE_SEARCH_DISPLAY"] = ":199"
    os.environ["VINE_SEARCH_VIEWER_PORT"] = str(free_port())
    os.environ["VINE_SEARCH_VNC_PORT"] = str(free_port())
    os.environ.pop("VINE_SEARCH_AUTH_FILE", None)
    with tempfile.TemporaryDirectory(prefix="vine-browser-fixture-") as directory:
        root = Path(directory)
        store = Store(root / "app" / "vine-search.sqlite3")
        owner = FixtureOwner(root / "session")
        owner.acquire_process()
        secret = secrets.token_urlsafe(32)
        collector_port, web_port = free_port(), free_port()
        collector = collector_app(store=store, owner=owner, secret=secret, run_worker=False)
        login = collector.state.collector.login
        web = web_app(
            Config(
                data_dir=root / "app",
                collector_url=f"http://127.0.0.1:{collector_port}",
                collector_secret=secret,
            ),
            store=store,
        )
        collector_server, collector_task = await serve(collector, collector_port)
        web_server, web_task = await serve(web, web_port)
        url = f"http://127.0.0.1:{web_port}"
        results: dict[str, Any] = {"mode": "synthetic-linux-served-login", "checks": {}}
        checks = results["checks"]
        try:
            async with async_playwright() as engine:
                browser = await engine.chromium.launch(headless=True, chromium_sandbox=True)
                page = await browser.new_page(viewport={"width": 1300, "height": 1000})
                console_errors: list[str] = []
                failed_requests: list[str] = []
                page.on("pageerror", lambda error: console_errors.append(str(error)[:200]))
                page.on(
                    "console",
                    lambda message: (
                        console_errors.append(message.text[:500])
                        if message.type == "error"
                        else None
                    ),
                )
                page.on(
                    "response",
                    lambda response: (
                        failed_requests.append(f"{response.status}: {urlparse(response.url).path}")
                        if response.status >= 400
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        f"{urlparse(request.url).path}: {request.failure}"
                    ),
                )
                await page.goto(url)
                await page.locator('[data-action="connect"]').first.click()
                await page.locator('[data-action="start-login"]').click()
                frame = page.frame_locator("iframe.login-frame")
                canvas = frame.locator("canvas").first
                try:
                    await canvas.wait_for(state="visible", timeout=45000)
                    await frame.locator("html.noVNC_connected").wait_for(timeout=15000)
                except Exception:
                    await page.screenshot(path="/tmp/vine-fixture-failure.png", full_page=True)
                    print(
                        json.dumps(
                            {
                                "login_state": login.public().get("state"),
                                "login_message": login.public().get("message"),
                                "javascript_errors": console_errors,
                                "failed_requests": failed_requests,
                                "page_text": (await page.locator("body").inner_text())[-2000:],
                            }
                        ),
                        file=sys.stderr,
                    )
                    raise
                await page.screenshot(path="/tmp/vine-fixture-login.png", full_page=True)
                assert login.session
                active_id = login.session["id"]
                active_capability = login.session["capability"]
                checks["same_origin_viewer"] = await page.locator(
                    "iframe.login-frame"
                ).get_attribute("src")
                assert checks["same_origin_viewer"].startswith("/login-viewer/")
                assert owner.current == "login"
                waiter_entered = asyncio.Event()

                async def competing_job() -> None:
                    async with owner.claim("competing-collection"):
                        waiter_entered.set()

                waiter = asyncio.create_task(competing_job())
                await asyncio.sleep(0.1)
                assert not waiter_entered.is_set()
                checks["exclusive_browser_ownership"] = True
                # Measure the synthetic field, then use pointer/keyboard through noVNC.
                # Chromium's address bar can initially own focus without a window manager.
                assert owner.active_context
                observer_page = owner.active_context.pages[0]
                field = await observer_page.locator("#fixture-input").bounding_box()
                screen = await observer_page.evaluate(
                    """() => ({x:screenX, y:screenY, width:screen.width,
                    height:screen.height, border:(outerWidth-innerWidth)/2,
                    top:outerHeight-innerHeight})"""
                )
                canvas_box = await canvas.bounding_box()
                assert field and canvas_box
                await canvas.click(
                    position={
                        "x": (screen["x"] + screen["border"] + field["x"] + field["width"] / 2)
                        * canvas_box["width"]
                        / screen["width"],
                        "y": (
                            screen["y"]
                            + screen["top"]
                            - screen["border"]
                            + field["y"]
                            + field["height"] / 2
                        )
                        * canvas_box["height"]
                        / screen["height"],
                    }
                )
                await page.keyboard.type("fixture", delay=40)
                assert await observer_page.locator("#fixture-input").input_value() == "fixture"
                await page.keyboard.press("Enter")
                assert login.task
                await asyncio.wait_for(login.task, timeout=20)
                assert login.public()["state"] == "connected", login.public()
                await page.locator("iframe.login-frame").wait_for(state="detached", timeout=12000)
                await asyncio.wait_for(waiter, timeout=2)
                assert waiter_entered.is_set()
                checks["viewer_keyboard_completion_detection"] = True
                assert not login.valid(active_id, active_capability, viewer=True)
                assert login.desktop is None
                checks["viewer_shutdown_after_completion"] = True
                async with owner.claim("reuse"), owner.browser() as context:
                    observer = context.pages[0] if context.pages else await context.new_page()
                    html, location = await load_page(
                        observer, f"{ORIGIN}/vine/vine-items?queue=potluck"
                    )
                    assert signed_in_vine(html, location)
                checks["persistent_session_headless_reuse"] = True
                # Forget only the synthetic profile, then reconnect through served endpoints.
                await owner.forget()
                async with httpx.AsyncClient(base_url=url) as client:
                    bootstrap = (await client.get("/api/bootstrap")).json()
                    headers = {"X-CSRF-Token": bootstrap["csrf_token"], "Origin": url}
                    start = await client.post("/api/connection/login", headers=headers)
                    assert start.status_code == 202
                    started = start.json()
                    cancelled = await client.post(
                        f"/api/connection/login/{started['id']}/cancel", headers=headers
                    )
                    assert cancelled.json()["state"] == "cancelled"
                    checks["served_reconnect_cancel"] = True
                    login.timeout = 0.05
                    expired = (await client.post("/api/connection/login", headers=headers)).json()
                    assert login.task
                    await login.task
                    state = await client.get(f"/api/connection/login/{expired['id']}")
                    assert state.json()["state"] == "expired"
                    assert not login.valid(expired["id"], login.session["capability"], viewer=True)
                    checks["served_timeout_revokes_viewer"] = True
                async with httpx.AsyncClient(base_url=url) as stranger:
                    forbidden = await stranger.get(f"/login-viewer/{active_id}/vnc.html")
                    assert forbidden.status_code == 403
                checks["viewer_requires_capability"] = True
                checks["client_javascript_errors"] = console_errors
                assert not console_errors, console_errors
                await browser.close()
        finally:
            await login.cancel()
            web_server.should_exit = True
            collector_server.should_exit = True
            await asyncio.gather(web_task, collector_task)
            owner.release_process()
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
