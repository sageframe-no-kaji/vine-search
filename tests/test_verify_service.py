"""Running-service verification must use protected jobs and truthful observation evidence."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from vine_search import verify


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,expected",
    [
        ("complete", "passed"),
        ("truncated", "passed"),
        ("exhaustive_truncated", "failed"),
        ("demo", "blocked"),
        ("disconnected", "blocked"),
        ("expired", "blocked"),
        ("lost_connection", "blocked"),
        ("failed", "failed"),
        ("missing_run", "failed"),
        ("wrong_kind", "failed"),
        ("wrong_query", "failed"),
        ("wrong_run_id", "failed"),
        ("zero_pages", "failed"),
        ("http_error", "blocked"),
        ("malformed", "blocked"),
    ],
)
async def test_service_verification_uses_jobs_and_rejects_false_evidence(
    monkeypatch: pytest.MonkeyPatch, case: str, expected: str
) -> None:
    posted: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(verify.asyncio, "sleep", sleep)

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/bootstrap":
            if case == "http_error":
                return httpx.Response(403)
            if case == "malformed":
                return httpx.Response(200, text="Not a JSON application")
            return httpx.Response(
                200,
                headers={"set-cookie": "vine_csrf=synthetic-token; Path=/; HttpOnly"},
                json={
                    "version": "test-service",
                    "demo": case == "demo",
                    "connection": {
                        "state": "disconnected" if case == "disconnected" else "connected"
                    },
                    "csrf_token": "synthetic-token",
                },
            )
        if path == "/api/jobs":
            assert request.method == "POST"
            assert request.headers["X-CSRF-Token"] == "synthetic-token"
            assert request.headers["Origin"] == "http://operator.test"
            assert request.headers["Cookie"] == "vine_csrf=synthetic-token"
            payload = json.loads(request.content)
            posted.append(payload)
            return httpx.Response(202, json={"id": len(posted), "status": "queued"})
        if path.startswith("/api/jobs/"):
            job_id = int(path.rsplit("/", 1)[-1])
            payload = posted[job_id - 1]
            status = {
                "expired": "needs_login",
                "failed": "partial",
                "truncated": "truncated",
            }.get(case, "complete")
            if case == "exhaustive_truncated" and payload["kind"] == "search":
                status = "truncated"
            run = {
                "id": job_id if case != "wrong_run_id" else job_id + 100,
                "job_id": job_id,
                "kind": payload["kind"] if case != "wrong_kind" else "other",
                "query": payload["query"] if case != "wrong_query" else "unrelated",
                "status": status,
                "pages": 0 if case == "zero_pages" else 2,
                "observed_count": 17,
                "started_at": "2026-10-20T00:00:00+00:00",
                "finished_at": "2026-10-20T00:00:02+00:00",
            }
            if case != "missing_run":
                runs.append(run)
            return httpx.Response(
                200,
                json={
                    "id": job_id,
                    "status": status,
                    "result": {"run_id": job_id},
                    "payload": {"exhaustive": case == "exhaustive_truncated"},
                },
            )
        if path == "/api/runs":
            return httpx.Response(200, json=runs)
        assert path == "/api/connection"
        return httpx.Response(
            200, json={"state": "needs_login" if case == "lost_connection" else "connected"}
        )

    result = await verify.verify_live_service(
        "http://operator.test", transport=httpx.MockTransport(handle)
    )
    assert result["status"] == expected
    assert "synthetic-token" not in json.dumps(result)
    assert "operator.test" not in json.dumps(result)
    if case in {"demo", "disconnected", "http_error", "malformed"}:
        assert posted == []
    elif expected == "passed":
        assert [item["kind"] for item in posted] == ["rfy", "afa", "search", "reviews"]
        assert result["service_version"] == "test-service"
        assert len(result["scans"]) == len(waits) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/app",
        "http://user:secret@host",
        "http://host/?token=x",
        "http://",
        "http://[invalid",
        "http://localhost:bad",
        "http://localhost:999999",
    ],
)
async def test_service_rejects_urls_with_credentials_or_non_application_schemes(url: str) -> None:
    result = await verify.verify_live_service(url)
    assert result["status"] == "blocked"
    assert "secret" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("expire_after_enqueue", [False, True])
async def test_service_wait_expiry_leaves_collection_untouched(
    monkeypatch: pytest.MonkeyPatch, expire_after_enqueue: bool
) -> None:
    posted: list[str] = []
    checks = 0

    def monotonic() -> float:
        nonlocal checks
        checks += 1
        return 0 if checks < (3 if expire_after_enqueue else 2) else 3

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/bootstrap":
            return httpx.Response(
                200,
                json={
                    "version": "test",
                    "csrf_token": "fake",
                    "connection": {"state": "connected"},
                },
            )
        assert request.url.path == "/api/jobs"
        posted.append(request.url.path)
        return httpx.Response(202, json={"id": 71, "status": "queued"})

    monkeypatch.setattr(verify, "time", SimpleNamespace(monotonic=monotonic))
    result = await verify.verify_live_service(
        "http://operator.test", wait_seconds=1, transport=httpx.MockTransport(handle)
    )
    assert result["status"] == "blocked"
    assert posted == (["/api/jobs"] if expire_after_enqueue else [])
    if expire_after_enqueue:
        assert result["pending_job_id"] == 71


def test_live_url_entrypoint_records_service_version_and_private_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "live.json"

    async def service(url: str, *, wait_seconds: int) -> dict[str, Any]:
        assert url == "http://operator.test"
        assert wait_seconds == 60
        return {"status": "passed", "service_version": "test-service"}

    monkeypatch.setattr(verify, "verify_live_service", service)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify",
            "--mode",
            "live",
            "--url",
            "http://operator.test",
            "--wait-seconds",
            "60",
            "--report",
            str(report),
        ],
    )
    with pytest.raises(SystemExit) as result:
        verify.main()
    assert result.value.code == 0
    assert json.loads(report.read_text())["service_version"] == "test-service"
    assert report.stat().st_mode & 0o777 == 0o600


def test_fixture_url_is_rejected_before_network_or_fixture_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "fixture.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify", "--mode", "fixture", "--url", "http://operator.test", "--report", str(report)],
    )
    with pytest.raises(SystemExit) as result:
        verify.main()
    assert result.value.code == 2
    assert not report.exists()
