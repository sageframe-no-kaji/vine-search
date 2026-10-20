"""Responsive web application and protected application-origin login proxy."""

import asyncio
import contextlib
import hashlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from vine_search import __version__
from vine_search.config import Config
from vine_search.security import (
    CSRF_COOKIE,
    LOGIN_COOKIE,
    check_write,
    client_allowed,
    client_networks,
    csrf_token,
    image_url_allowed,
    valid_csrf,
)
from vine_search.store import Store

PACKAGE_DIR = Path(__file__).parent
Json = dict[str, Any]


def create_app(config: Config | None = None, store: Store | None = None) -> FastAPI:
    """Build an application with explicit, testable storage and service boundaries."""
    cfg = config or Config()
    allowed_clients = client_networks(cfg.allowed_clients)
    cfg.prepare()
    db = store or Store(cfg.database)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(title="VineSearch", version=__version__, lifespan=lifespan)
    app.state.store = db
    app.state.config = cfg
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(cfg.allowed_hosts))
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    (PACKAGE_DIR / "static").mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def boundaries(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not client_allowed(request.client.host if request.client else None, allowed_clients):
            return JSONResponse({"detail": "Client address is not allowed."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                check_write(request, cfg.collector_secret)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Invalid content length"}, status_code=400)
            if size > 2_000_000:
                return JSONResponse({"detail": "Request exceeds 2 MB"}, status_code=413)
            body = await request.body()
            if len(body) > 2_000_000:
                return JSONResponse({"detail": "Request exceeds 2 MB"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = (
            "private, max-age=86400" if request.url.path.startswith("/static/") else "no-store"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; img-src 'self' data: https://m.media-amazon.com "
            "https://images-na.ssl-images-amazon.com https://images-eu.ssl-images-amazon.com "
            "https://images.amazon.com; "
            "connect-src 'self' ws: wss:; frame-src 'self'; frame-ancestors 'self'; "
            "base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid_input(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_record(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": "Record not found."}, status_code=404)

    async def control(method: str, path: str, data: Json | None = None) -> Json:
        try:
            async with httpx.AsyncClient(
                base_url=cfg.collector_url,
                timeout=2 if method == "GET" else 15,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                result = await client.request(
                    method, path, json=data, headers={"X-Collector-Secret": cfg.collector_secret}
                )
            if result.status_code >= 400:
                # Never propagate internal URLs, capabilities, or stack traces.
                raise HTTPException(result.status_code, "Collector request could not be completed.")
            value: Json = result.json()
            return value
        except httpx.HTTPError as exc:
            raise HTTPException(
                503, "Collector unavailable. Saved results remain available."
            ) from exc

    def public_login(value: Json) -> Json:
        """Normalize every lifecycle state's viewer URL to the protected app origin."""
        value = dict(value)
        value.pop("capability", None)
        if value.get("id"):
            login_id = str(value["id"])
            value["viewer_path"] = f"/login-viewer/{login_id}/vnc.html?" + urlencode(
                {
                    "autoconnect": 1,
                    "resize": "scale",
                    "path": f"/login-viewer/{login_id}/websockify",
                }
            )
        return value

    @app.get("/health")
    def health() -> Json:
        return {"status": "ok", "version": __version__, "database": db.dashboard()["products"]}

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request, response: Response) -> Json:
        token = request.cookies.get(CSRF_COOKIE, "")
        if not valid_csrf(token, cfg.collector_secret):
            token = csrf_token(cfg.collector_secret)
        response.set_cookie(
            CSRF_COOKIE,
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=86400,
        )
        current_connection = db.get_connection()
        try:
            current_connection = await control("GET", "/connection")
            if isinstance(current_connection.get("login"), dict):
                current_connection["login"] = public_login(current_connection["login"])
        except HTTPException:
            current_connection["collector_available"] = False
        return {
            "csrf_token": token,
            "version": __version__,
            "settings": db.get_settings(),
            "connection": current_connection,
            "dashboard": db.dashboard(),
            "health": db.dashboard(),
            "demo": (cfg.data_dir / "DEMO").exists(),
        }

    @app.get("/api/products")
    def products(
        q: str = "",
        query: str = "",
        source: str = "",
        tracker_id: int | None = None,
        job_id: int | None = None,
        category: str = "",
        sort: str = "rank",
        min_score: float | None = None,
        freshness_hours: int | None = None,
        page: Annotated[int, Query(ge=1, le=10000)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 60,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
        visibility: str = "visible",
    ) -> Json:
        return db.list_products(
            query=query or q,
            source=source,
            tracker_id=tracker_id,
            job_id=job_id,
            category=category,
            sort=sort,
            min_score=min_score,
            freshness_hours=freshness_hours,
            limit=limit,
            offset=offset or (page - 1) * limit,
            visibility=visibility,
        )

    def change_visibility(resource: str, data: Json, record_id: int | None = None) -> Json:
        allowed = {"hidden", "ids"} if record_id is None else {"hidden"}
        if set(data) != allowed:
            raise ValueError("Provide only hidden and, for a selection, ids")
        return db.set_visibility(
            resource, data["ids"] if record_id is None else [record_id], data["hidden"]
        )

    @app.patch("/api/products/{product_id}/visibility")
    def product_visibility(product_id: int, data: Json) -> Json:
        return change_visibility("products", data, product_id)

    @app.post("/api/products/visibility")
    def products_visibility(data: Json) -> Json:
        return change_visibility("products", data)

    @app.post("/api/products/{product_id}/details", status_code=202)
    def product_details(product_id: int, data: Json | None = None) -> Json:
        if data:
            raise ValueError("Product details use the saved item; do not provide a URL or locator")
        return db.enqueue_product_details(product_id)

    @app.get("/api/trackers")
    def trackers() -> list[Json]:
        return db.list_trackers()

    @app.post("/api/trackers", status_code=201)
    def new_tracker(data: Json) -> Json:
        return db.save_tracker(data)

    @app.patch("/api/trackers/{tracker_id}")
    def edit_tracker(tracker_id: int, data: Json) -> Json:
        return db.save_tracker(data, tracker_id=tracker_id)

    @app.delete("/api/trackers/{tracker_id}")
    def remove_tracker(tracker_id: int) -> Json:
        db.delete_tracker(tracker_id)
        return {"deleted": tracker_id}

    @app.get("/api/settings")
    def settings() -> Json:
        return db.get_settings()

    @app.patch("/api/settings")
    def update_settings(data: Json) -> Json:
        return db.update_settings(data)

    @app.post("/api/settings/reset")
    def reset_settings() -> Json:
        return db.reset_settings()

    @app.get("/api/jobs")
    def jobs() -> list[Json]:
        return db.list_jobs()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int) -> Json:
        return db.get_job(job_id)

    @app.post("/api/jobs", status_code=202)
    def enqueue(data: Json) -> Json:
        kind = str(data.get("kind", "search"))
        if kind not in {"rfy", "afa", "search", "reviews"}:
            raise ValueError("Choose RFY, AFA, search or review sync.")
        return db.enqueue_job(
            kind, query=str(data.get("query", "")), tracker_id=data.get("tracker_id")
        )

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> Json:
        existing = db.get_job(job_id)
        if existing["status"] not in {"queued", "running"}:
            raise ValueError("Only queued or running work can be cancelled.")
        return db.update_job(job_id, status="cancelled")

    @app.get("/api/runs")
    def runs() -> list[Json]:
        return db.list_runs()

    @app.get("/api/reviews")
    def reviews(
        q: str = "",
        query: str = "",
        status: str = "",
        local_progress: str = "",
        source: str = "",
        sort: str = "oldest",
        page: Annotated[int, Query(ge=1, le=10000)] = 1,
        visibility: str = "visible",
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    ) -> Json:
        return db.list_reviews(
            query=query or q,
            status=status,
            local_progress=local_progress,
            source=source,
            sort=sort,
            offset=offset or (page - 1) * limit,
            limit=limit,
            visibility=visibility,
        )

    @app.patch("/api/reviews/{review_id}/visibility")
    def review_visibility(review_id: int, data: Json) -> Json:
        return change_visibility("reviews", data, review_id)

    @app.post("/api/reviews/visibility")
    def reviews_visibility(data: Json) -> Json:
        return change_visibility("reviews", data)

    @app.patch("/api/reviews/{review_id}")
    def review_progress(review_id: int, data: Json) -> Json:
        return db.set_review_progress(review_id, str(data.get("local_progress", "")))

    @app.post("/api/reviews/import/preview")
    def preview_reviews(data: Json) -> Json:
        records = data.get("records")
        if not isinstance(records, list) or len(records) > 5000:
            raise ValueError("Provide a records array with at most 5,000 rows.")
        return db.preview_review_import(records)

    @app.post("/api/reviews/import")
    def import_reviews(data: Json) -> Json:
        records = data.get("records")
        if not isinstance(records, list) or len(records) > 5000:
            raise ValueError("Provide a records array with at most 5,000 rows.")
        return db.import_reviews(records, preview_hash=str(data.get("preview_hash", "")))

    @app.get("/api/reviews/export")
    def export_reviews() -> Response:
        return JSONResponse(
            db.export_reviews(),
            headers={"Content-Disposition": 'attachment; filename="vine-search-reviews.json"'},
        )

    @app.get("/api/export")
    def export_data() -> Response:
        return JSONResponse(
            db.export_data(),
            headers={"Content-Disposition": 'attachment; filename="vine-search-export.json"'},
        )

    @app.post("/api/retention/preview")
    def retention_preview(data: Json) -> Json:
        return db.retention_preview(days=data.get("days"))

    @app.post("/api/retention/apply")
    def retention_apply(data: Json) -> Json:
        return db.apply_retention(confirm=str(data.get("confirm", "")), days=data.get("days"))

    @app.post("/api/data/delete")
    def delete_data(data: Json) -> Json:
        if any(j["status"] == "running" for j in db.list_jobs()):
            raise ValueError("Pause collection and wait for active work before deleting data.")
        db.delete_data(confirm=str(data.get("confirm", "")))
        return {"deleted": True}

    @app.get("/api/notifications")
    def notifications() -> list[Json]:
        return db.list_notifications()

    @app.post("/api/notifications/test", status_code=202)
    def test_notification() -> Json:
        return db.queue_notification_test()

    @app.get("/api/connection")
    async def connection() -> Json:
        try:
            value = await control("GET", "/connection")
            if isinstance(value.get("login"), dict):
                value["login"] = public_login(value["login"])
            return value
        except HTTPException:
            return {**db.get_connection(), "collector_available": False}

    @app.post("/api/connection/login", status_code=202)
    async def login(request: Request, response: Response) -> Json:
        result = await control("POST", "/login/start")
        login_id = str(result["id"])
        capability = str(result.pop("capability"))
        response.set_cookie(
            LOGIN_COOKIE,
            capability,
            path=f"/login-viewer/{login_id}/",
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=900,
        )
        # A separate cookie authorizes lifecycle requests; inaccessible to JavaScript.
        response.set_cookie(
            f"vine_login_{login_id}",
            capability,
            path=f"/api/connection/login/{login_id}",
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=900,
        )
        return public_login(result)

    def login_capability(request: Request, login_id: str) -> str:
        capability = request.cookies.get(f"vine_login_{login_id}", "")
        if not capability:
            raise HTTPException(403, "Login access expired. Open a new login browser.")
        return capability

    @app.get("/api/connection/login/{login_id}")
    async def login_state(login_id: str, request: Request) -> Json:
        capability = login_capability(request, login_id)
        value = await control("GET", f"/login/{login_id}?" + urlencode({"capability": capability}))
        return public_login(value)

    @app.post("/api/connection/login/{login_id}/cancel")
    async def login_cancel(login_id: str, request: Request, response: Response) -> Json:
        capability = login_capability(request, login_id)
        result = await control(
            "POST", f"/login/{login_id}/cancel?" + urlencode({"capability": capability})
        )
        response.delete_cookie(LOGIN_COOKIE, path=f"/login-viewer/{login_id}/")
        response.delete_cookie(f"vine_login_{login_id}", path=f"/api/connection/login/{login_id}")
        return result

    @app.post("/api/connection/disconnect")
    async def disconnect(data: Json) -> Json:
        return await control("POST", "/disconnect", {"forget": data.get("forget") is True})

    @app.get("/login-viewer/{login_id}/{asset:path}")
    async def viewer_asset(login_id: str, asset: str, request: Request) -> Response:
        capability = request.cookies.get(LOGIN_COOKIE, "")
        if not capability:
            raise HTTPException(403, "Login browser access expired.")
        if ".." in asset.split("/") or asset.startswith("/"):
            raise HTTPException(400, "Invalid viewer path.")
        params = {"capability": capability}
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            try:
                result = await client.get(
                    f"{cfg.collector_url}/viewer/{login_id}/{asset}",
                    params=params,
                    headers={"X-Collector-Secret": cfg.collector_secret},
                )
            except httpx.HTTPError as exc:
                raise HTTPException(503, "Login browser unavailable.") from exc
        if result.status_code != 200:
            raise HTTPException(result.status_code, "Login browser closed or expired.")
        return Response(result.content, media_type=result.headers.get("content-type"))

    @app.websocket("/login-viewer/{login_id}/websockify")
    async def viewer_socket(socket: WebSocket, login_id: str) -> None:
        if not client_allowed(socket.client.host if socket.client else None, allowed_clients):
            await socket.close(code=1008)
            return
        capability = socket.cookies.get(LOGIN_COOKIE, "")
        origin = socket.headers.get("origin")
        scheme = "https" if socket.url.scheme == "wss" else "http"
        if not capability or origin != f"{scheme}://{socket.url.netloc}":
            await socket.close(code=1008)
            return
        base = cfg.collector_url.replace("http://", "ws://").replace("https://", "wss://")
        remote_url = f"{base}/viewer/{login_id}/websockify?" + urlencode({"capability": capability})
        try:
            async with connect(
                remote_url,
                additional_headers={"X-Collector-Secret": cfg.collector_secret},
                max_size=8_000_000,
                open_timeout=10,
            ) as remote:
                await socket.accept()

                async def upstream() -> None:
                    while True:
                        message = await socket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await remote.send(message.get("bytes") or message.get("text", ""))

                async def downstream() -> None:
                    async for data in remote:
                        if isinstance(data, bytes):
                            await socket.send_bytes(data)
                        else:
                            await socket.send_text(data)

                tasks = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (ConnectionClosed, WebSocketDisconnect, OSError, TimeoutError):
            pass
        finally:
            with contextlib.suppress(RuntimeError):
                await socket.close()

    @app.get("/api/products/{product_id}/image")
    async def product_image(product_id: int) -> Response:
        return await listing_image(db.get_product(product_id))

    @app.get("/api/reviews/{review_id}/image")
    async def review_image(review_id: int) -> Response:
        return await listing_image(db.get_review(review_id))

    async def listing_image(record: Json) -> Response:
        settings = db.get_settings()
        if settings.get("image_mode") == "hidden":
            raise HTTPException(404, "Images are disabled.")
        url = str(record.get("image_url") or "")
        if not image_url_allowed(url):
            raise HTTPException(404, "No supported product image.")
        directory = cfg.data_dir / "image-cache"
        directory.mkdir(exist_ok=True)
        path = directory / hashlib.sha256(url.encode()).hexdigest()
        mime_path = path.with_suffix(".mime")
        if path.is_file() and mime_path.is_file() and time.time() - path.stat().st_mtime < 86400:
            return FileResponse(path, media_type=mime_path.read_text())
        try:
            async with (
                httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client,
                client.stream("GET", url) as result,
            ):
                mime = result.headers.get("content-type", "").split(";")[0]
                if result.status_code != 200 or mime not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                    "image/gif",
                }:
                    raise HTTPException(502, "Product image unavailable.")
                content = bytearray()
                async for chunk in result.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 5_000_000:
                        raise HTTPException(502, "Product image exceeds size limit.")
            path.write_bytes(content)
            mime_path.write_text(mime)
            # Bounded cache, oldest entries first; this never removes inventory records.
            entries = sorted(directory.iterdir(), key=lambda item: item.stat().st_mtime)
            total = sum(item.stat().st_size for item in entries)
            for index, entry in enumerate(entries):
                if total <= 200_000_000 and len(entries) - index <= 2000:
                    break
                total -= entry.stat().st_size
                entry.unlink(missing_ok=True)
            return Response(bytes(content), media_type=mime)
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Product image unavailable.") from exc

    @app.get("/", response_class=HTMLResponse)
    @app.get("/discover", response_class=HTMLResponse)
    @app.get("/trackers", response_class=HTMLResponse)
    @app.get("/reviews", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    @app.get("/help", response_class=HTMLResponse)
    @app.get("/activity", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return templates.TemplateResponse(
            request=request, name="index.html", context={"version": __version__}
        )

    return app
