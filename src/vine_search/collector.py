"""Serial durable collection worker and authenticated, internal login service."""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from websockets.asyncio.client import connect
from websockets.typing import Subprotocol

from vine_search.amazon import (
    ORIGIN,
    CollectionCancelledError,
    Scan,
    collect,
    load_page,
    lookup_details,
    signed_in_vine,
)
from vine_search.login import BrowserOwner, LoginController, utc_now
from vine_search.store import Store


class Collector:
    def __init__(self, store: Store, owner: BrowserOwner) -> None:
        self.store, self.owner = store, owner
        self.worker_id = str(uuid.uuid4())
        self.login = LoginController(owner, store.set_connection)
        self.stopping = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.delivery_task: asyncio.Task[None] | None = None
        self.disconnection_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.owner.acquire_process()
        self.store.recover_jobs()
        # A surviving profile is merely a reason to check, never proof of login.
        has_session = (self.owner.session_dir / "profile").exists() or os.environ.get(
            "VINE_SEARCH_AUTH_FILE"
        )
        deliberately_disconnected = (self.owner.session_dir / "disconnected").exists()
        if has_session and not deliberately_disconnected:
            await self.check_connection()
        elif self.store.get_connection().get("state") in {"connecting", "connected"}:
            self.store.set_connection(
                "needs_login", message="Open the login browser to connect Amazon."
            )
        self.task = asyncio.create_task(self.loop())
        self.delivery_task = asyncio.create_task(self.delivery_loop())

    async def stop(self) -> None:
        self.stopping.set()
        await self.login.cancel()
        for task in (self.task, self.delivery_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self.disconnection_task:
            await self.disconnection_task
        self.owner.release_process()

    async def check_connection(self) -> bool:
        try:
            async with self.owner.claim("check_connection"), self.owner.browser() as browser:
                page = browser.pages[0] if browser.pages else await browser.new_page()
                html, url = await load_page(page, f"{ORIGIN}/vine/vine-items?queue=potluck")
                if signed_in_vine(html, url):
                    self.store.set_connection(
                        "connected",
                        message="Amazon Vine access verified.",
                        last_success=utc_now(),
                    )
                    return True
                self.store.set_connection(
                    "needs_login", message="Amazon needs you to sign in again."
                )
        except Exception as exc:
            self.store.set_connection(
                "failed", message=f"Connection check failed ({type(exc).__name__})."
            )
        return False

    async def loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self.store.recover_jobs()
                self.store.schedule_due()
                if (
                    not self.login.active
                    and self.store.get_connection().get("state") == "connected"
                ):
                    job = self.store.claim_job(self.worker_id)
                    if job:
                        await self.execute(job)
                        continue
            except Exception:
                # Preserve durable queued work. Avoid writing raw page/URL/credential errors.
                self.store.set_connection(
                    "failed", message="The collection worker encountered an error."
                )
            await asyncio.sleep(1)

    async def delivery_loop(self) -> None:
        from vine_search.notifications import NotificationWorker

        worker = NotificationWorker(self.store)
        while not self.stopping.is_set():
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.store.queue_review_reminders)
                await asyncio.to_thread(worker.run_once)
            await asyncio.sleep(2)

    async def execute(self, job: dict[str, Any]) -> Scan:
        settings = self.store.get_settings()
        payload = job.get("payload") or {}
        # Job snapshots take precedence; settings changes apply to newly queued work.
        configuration = {**settings, **payload.get("settings", {}), **payload}
        page_budget = int(
            configuration.get(
                "review_page_budget" if job["kind"] == "reviews" else "page_budget", 5
            )
        )
        runtime = int(configuration.get("runtime_budget_seconds", 120))
        scan = Scan("failed", error="Browser operation did not finish.")

        async def progress(details: dict[str, Any]) -> None:
            current = self.store.get_job(job["id"])
            if current["status"] == "cancelled":
                raise CollectionCancelledError()
            self.store.heartbeat_job(job["id"], self.worker_id, progress=details)

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(15)
                if self.store.get_job(job["id"])["status"] == "running":
                    self.store.heartbeat_job(job["id"], self.worker_id)

        heart = asyncio.create_task(heartbeat())
        try:
            async with self.owner.claim(f"job:{job['id']}"):
                if self.store.get_job(job["id"])["status"] == "cancelled":
                    return Scan("cancelled")
                async with self.owner.browser() as browser:
                    page = browser.pages[0] if browser.pages else await browser.new_page()
                    if job["kind"] == "details":
                        scan = await lookup_details(page, payload, progress=progress)
                    else:
                        scan = await collect(
                            page,
                            job["kind"],
                            job.get("query", ""),
                            page_budget=page_budget,
                            runtime_budget=runtime,
                            exhaustive=job["kind"] == "search",
                            progress=progress,
                        )
        except asyncio.CancelledError:
            # No false completion: the lease survives and restart recovery retries it.
            raise
        except Exception as exc:
            scan = Scan("failed", error=f"Browser collection failed ({type(exc).__name__}).")
        finally:
            heart.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heart

        def mark_cancelled() -> None:
            scan.status = "cancelled"
            scan.error = "Cancelled by the operator; captured pages retained."
            scan.stop_reason = None

        def save_capture() -> None:
            if job["kind"] == "details":
                self.store.update_job(
                    job["id"],
                    status=scan.status,
                    result=scan.details,
                    error=scan.error,
                )
            elif job["kind"] == "reviews":
                self.store.record_review_scan(
                    job["id"],
                    scan.reviews,
                    status=scan.status,
                    pages=scan.pages,
                    source="amazon",
                    error=scan.error,
                )
            else:
                self.store.record_scan(
                    job["id"],
                    scan.products,
                    status=scan.status,
                    pages=scan.pages,
                    advertised_count=scan.advertised_count,
                    error=scan.error,
                )

        if self.store.get_job(job["id"])["status"] == "cancelled":
            mark_cancelled()
        try:
            save_capture()
        except ValueError:
            # The web process can cancel after our status check but before the
            # transaction commits. Retain the captured result without reviving it.
            if scan.status == "cancelled" or self.store.get_job(job["id"])["status"] != "cancelled":
                raise
            mark_cancelled()
            save_capture()
        saved_progress = self.store.get_job(job["id"])["progress"]
        self.store.update_job(
            job["id"],
            progress={
                **saved_progress,
                "stop_reason": scan.stop_reason,
                "section_pages": scan.section_pages,
                "elapsed_seconds": scan.elapsed_seconds,
                "exhaustive": scan.exhaustive,
            },
        )
        deliberately_disconnected = (self.owner.session_dir / "disconnected").exists()
        if scan.status == "needs_login" and not deliberately_disconnected:
            self.store.set_connection(
                "challenge" if scan.error and scan.error.startswith("challenge") else "needs_login",
                message="Amazon needs your attention. Open the login browser to continue.",
            )
        elif (
            scan.status in {"complete", "truncated"}
            and scan.pages
            and not deliberately_disconnected
        ):
            self.store.set_connection(
                "connected", message="Amazon Vine access verified.", last_success=utc_now()
            )
        return scan


def create_app(
    *,
    store: Store | None = None,
    owner: BrowserOwner | None = None,
    secret: str | None = None,
    run_worker: bool = True,
) -> FastAPI:
    service_secret = secret or os.environ.get("VINE_SEARCH_COLLECTOR_SECRET", "")
    if len(service_secret) < 24:
        raise RuntimeError("VINE_SEARCH_COLLECTOR_SECRET must contain at least 24 characters")
    data = Path(os.environ.get("VINE_SEARCH_DATA_DIR", "data"))
    runtime_store = store or Store(data / "vine-search.sqlite3")
    runtime_owner = owner or BrowserOwner(
        Path(os.environ.get("VINE_SEARCH_SESSION_DIR", str(data / "private-session")))
    )
    worker = Collector(runtime_store, runtime_owner)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if run_worker:
            await worker.start()
        try:
            yield
        finally:
            if run_worker:
                await worker.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.collector = worker

    async def authorized(request: Request) -> None:
        if not secrets.compare_digest(
            request.headers.get("x-collector-secret", ""), service_secret
        ):
            raise HTTPException(403, "Private collector service")

    auth = [Depends(authorized)]

    def session_valid(session_id: str, capability: str, *, viewer: bool = False) -> None:
        if not worker.login.valid(session_id, capability, viewer=viewer):
            raise HTTPException(410, "Login capability is invalid, expired, or no longer active")

    @app.get("/health", dependencies=auth)
    async def health() -> dict[str, Any]:
        return {"status": "ok", "browser_owner": runtime_owner.current}

    @app.get("/connection", dependencies=auth)
    async def connection() -> dict[str, Any]:
        return {**runtime_store.get_connection(), "login": worker.login.public()}

    @app.post("/login/start", dependencies=auth)
    async def start_login() -> dict[str, Any]:
        return await worker.login.start()

    @app.get("/login/{session_id}", dependencies=auth)
    async def get_login(session_id: str, capability: str = "") -> dict[str, Any]:
        session = worker.login.session
        terminal = session and session["state"] in {"connected", "cancelled", "expired", "failed"}
        if not (
            terminal
            and session
            and session["id"] == session_id
            and secrets.compare_digest(session["capability"], capability)
        ):
            session_valid(session_id, capability)
        return worker.login.public()

    @app.post("/login/{session_id}/cancel", dependencies=auth)
    async def cancel_login(session_id: str, capability: str = "") -> dict[str, Any]:
        session_valid(session_id, capability)
        return await worker.login.cancel()

    @app.post("/disconnect", dependencies=auth)
    async def disconnect(request: Request) -> dict[str, Any]:
        body = await request.json()
        await worker.login.cancel()
        runtime_owner.session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        (runtime_owner.session_dir / "disconnected").write_text("Disconnected by the operator\n")
        runtime_store.set_connection(
            "disconnected", message="Amazon disconnected. History remains available."
        )
        # Signal cancellation immediately; browser close/removal can await exclusive
        # ownership without blocking the webpage request.
        current = runtime_owner.current or ""
        if current.startswith("job:"):
            runtime_store.update_job(int(current.split(":")[1]), status="cancelled")
        if body.get("forget", False):
            worker.disconnection_task = asyncio.create_task(runtime_owner.forget())
        return runtime_store.get_connection()

    @app.get("/viewer/{session_id}/{path:path}", dependencies=auth)
    async def viewer(session_id: str, path: str, capability: str = "") -> Response:
        session_valid(session_id, capability, viewer=True)
        if ".." in path.split("/") or path.startswith("/") or not path:
            raise HTTPException(400, "Invalid viewer asset")
        port = worker.login.desktop.http_port if worker.login.desktop else 6080
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            upstream = await client.get(f"http://127.0.0.1:{port}/{quote(path, safe='/')}")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/octet-stream"),
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @app.websocket("/viewer/{session_id}/websockify")
    async def viewer_socket(websocket: WebSocket, session_id: str, capability: str = "") -> None:
        if not secrets.compare_digest(
            websocket.headers.get("x-collector-secret", ""), service_secret
        ) or not worker.login.valid(session_id, capability, viewer=True):
            await websocket.close(code=1008)
            return
        await websocket.accept(
            subprotocol="binary"
            if "binary" in websocket.headers.get("sec-websocket-protocol", "")
            else None
        )
        port = worker.login.desktop.http_port if worker.login.desktop else 6080
        try:
            async with connect(
                f"ws://127.0.0.1:{port}/websockify",
                subprotocols=[Subprotocol("binary")],
                max_size=4 * 1024 * 1024,
                proxy=None,
            ) as upstream:

                async def to_upstream() -> None:
                    while worker.login.valid(session_id, capability, viewer=True):
                        try:
                            message = await asyncio.wait_for(websocket.receive(), timeout=5)
                        except TimeoutError:
                            continue
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(message.get("bytes") or message.get("text") or b"")

                async def to_browser() -> None:
                    async for message in upstream:
                        if not worker.login.valid(session_id, capability, viewer=True):
                            return
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                outgoing = asyncio.create_task(to_upstream())
                incoming = asyncio.create_task(to_browser())
                done, pending = await asyncio.wait(
                    {outgoing, incoming}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*done, *pending, return_exceptions=True)
        except (OSError, WebSocketDisconnect, TimeoutError):
            pass
        finally:
            with contextlib.suppress(RuntimeError):
                await websocket.close()

    return app


def run() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("VINE_SEARCH_COLLECTOR_HOST", "0.0.0.0"),
        port=int(os.environ.get("VINE_SEARCH_COLLECTOR_PORT", "8766")),
        access_log=False,
    )


if __name__ == "__main__":
    run()
