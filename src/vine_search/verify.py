"""Repeatable fixture and authorized-live verification, with non-passing blocked states."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from vine_search import __version__


async def verify_live_service(
    url: str,
    *,
    wait_seconds: int = 1800,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Use the running collector's durable jobs without opening its private profile."""
    try:
        parsed = urlsplit(url)
        # urllib validates the port only when accessed; httpx also rejects
        # malformed host/port combinations before any network request.
        _ = parsed.port
        httpx.URL(url)
    except (ValueError, httpx.InvalidURL):
        return {"status": "blocked", "reason": "Supply a valid application URL and wait limit."}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not 1 <= wait_seconds <= 7200
    ):
        return {"status": "blocked", "reason": "Supply a valid application URL and wait limit."}
    scans: list[dict[str, Any]] = []
    started = time.monotonic()
    terminal = {"complete", "truncated", "partial", "failed", "needs_login", "cancelled"}
    try:
        async with httpx.AsyncClient(
            base_url=url.rstrip("/") + "/",
            timeout=15,
            transport=transport,
            follow_redirects=False,
        ) as client:

            async def request(method: str, path: str, **kwargs: Any) -> Any:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            bootstrap = await request("GET", "api/bootstrap")
            if bootstrap.get("demo"):
                return {
                    "status": "blocked",
                    "reason": "A demonstration installation cannot provide live Amazon evidence.",
                }
            if bootstrap.get("connection", {}).get("state") != "connected":
                return {
                    "status": "blocked",
                    "reason": "Connect Amazon through the application's login browser first.",
                }
            version = str(bootstrap["version"])
            token = bootstrap["csrf_token"]
            headers = {
                "X-CSRF-Token": token,
                "Origin": f"{parsed.scheme}://{parsed.netloc}",
            }
            for kind, query in [("rfy", ""), ("afa", ""), ("search", "usb"), ("reviews", "")]:
                if time.monotonic() - started >= wait_seconds:
                    return {
                        "status": "blocked",
                        "reason": "Verification wait limit reached; queued work was not cancelled.",
                        "scans": scans,
                    }
                job = await request(
                    "POST", "api/jobs", headers=headers, json={"kind": kind, "query": query}
                )
                job_id = int(job["id"])
                while job.get("status") not in terminal:
                    if time.monotonic() - started >= wait_seconds:
                        return {
                            "status": "blocked",
                            "reason": (
                                "Verification wait limit reached; the collection job remains "
                                "available in Activity."
                            ),
                            "pending_job_id": job_id,
                            "scans": scans,
                        }
                    await asyncio.sleep(1)
                    job = await request("GET", f"api/jobs/{job_id}")
                if job["status"] == "needs_login":
                    return {
                        "status": "blocked",
                        "reason": "Amazon requires interactive login.",
                        "scans": scans,
                    }
                runs = await request("GET", "api/runs")
                run = next(
                    (
                        item
                        for item in runs
                        if item.get("job_id") == job_id
                        and item.get("id") == job.get("result", {}).get("run_id")
                    ),
                    None,
                )
                if (
                    run is None
                    or run.get("kind") != kind
                    or run.get("query", "") != query
                    or run.get("status") != job["status"]
                    or int(run.get("pages", 0)) < 1
                ):
                    return {
                        "status": "failed",
                        "reason": "The collection job has no matching observed-page run.",
                        "scans": scans,
                    }
                scans.append(
                    {
                        "job_id": job_id,
                        "run_id": run["id"],
                        "kind": kind,
                        "query": query,
                        "status": run["status"],
                        "pages": run["pages"],
                        "observed_count": run["observed_count"],
                        "advertised_count": run.get("advertised_count"),
                        "started_at": run["started_at"],
                        "finished_at": run["finished_at"],
                    }
                )
                if job["status"] not in {"complete", "truncated"}:
                    return {
                        "status": "failed",
                        "reason": "A live collection did not finish its configured scope.",
                        "scans": scans,
                    }
                if (
                    kind == "search"
                    and job.get("payload", {}).get("exhaustive")
                    and job["status"] != "complete"
                ):
                    return {
                        "status": "failed",
                        "reason": "The search did not reach the final Amazon result page.",
                        "scans": scans,
                    }
            connection = await request("GET", "api/connection")
            if connection.get("state") != "connected":
                return {
                    "status": "blocked",
                    "reason": "Amazon connection was lost during verification.",
                    "scans": scans,
                }
            return {
                "status": "passed",
                "service_version": version,
                "scans": scans,
                "scope": (
                    "Actual Amazon collection through the running service's serial jobs. "
                    "Each run uses the installation's collection policy; truncated runs "
                    "establish observed-page compatibility, not complete account coverage."
                ),
            }
    except (
        httpx.HTTPError,
        httpx.InvalidURL,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        return {
            "status": "blocked",
            "reason": f"Running-service verification unavailable ({type(exc).__name__}).",
            "scans": scans,
        }


async def verify_live() -> dict[str, Any]:
    """Read actual Amazon pages with the installation's dedicated session."""
    from vine_search.amazon import collect, signed_in_vine
    from vine_search.login import BrowserOwner

    session_dir = Path(os.getenv("VINE_SEARCH_SESSION_DIR", "data/session"))
    auth_path = os.getenv("VINE_SEARCH_AUTH_FILE")
    if not (session_dir / "profile").is_dir() and not (auth_path and Path(auth_path).is_file()):
        return {
            "status": "blocked",
            "reason": "No authorized dedicated Amazon session is available.",
        }
    owner = BrowserOwner(session_dir)
    scans: list[dict[str, Any]] = []
    try:
        owner.acquire_process()
        async with owner.claim("live-verification"), owner.browser() as context:
            page = context.pages[0] if context.pages else await context.new_page()
            for kind, query in [("rfy", ""), ("afa", ""), ("search", "usb"), ("reviews", "")]:
                scan = await collect(page, kind, query, page_budget=2, runtime_budget=120)
                scans.append(
                    {
                        "kind": kind,
                        "query": query,
                        "status": scan.status,
                        "pages": scan.pages,
                        "product_count": len(scan.products),
                        "review_count": len(scan.reviews),
                        "advertised_count": scan.advertised_count,
                        "actual_vine_ui": signed_in_vine(await page.content(), page.url),
                        "error": scan.error,
                    }
                )
                if scan.status == "needs_login":
                    return {
                        "status": "blocked",
                        "reason": "Amazon requires interactive login.",
                        "scans": scans,
                    }
        good = all(s["status"] in {"complete", "truncated"} and s["actual_vine_ui"] for s in scans)
        return {
            "status": "passed" if good else "failed",
            "scans": scans,
            "scope": "Actual Amazon pages; two-page budget per source, no inventory published.",
        }
    except Exception as exc:
        return {"status": "blocked", "reason": f"Live browser unavailable ({type(exc).__name__})."}
    finally:
        owner.release_process()


def verify_fixture(report_path: Path) -> dict[str, Any]:
    """Run actual persistence, failure, boundary, and served Chromium interaction tests."""
    project = Path(__file__).resolve().parents[2]
    tests = project / "tests"
    if not tests.is_dir():
        return {
            "status": "blocked",
            "reason": "Fixture verification needs the source checkout and uv sync --dev.",
        }
    log = report_path.with_suffix(".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", str(tests), "--no-cov", "-q"]
    with log.open("w") as output:
        result = subprocess.run(
            command, cwd=project, stdout=output, stderr=subprocess.STDOUT, check=False
        )
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "command": "python -m pytest tests --no-cov -q",
        "exit_code": result.returncode,
        "log": str(log),
        "scope": [
            "Synthetic observations and real SQLite persistence",
            "Tracker ranking, review import/progress, settings, local notification receiver",
            "Login lifecycle and exclusive ownership with controlled browser adapters",
            "Real Chromium against served UI at 360, 390, 768 and 1440px",
            "Failure, restart, security and backup/restore assertions",
        ],
        "separate_evidence_required": [
            "Real Amazon/MFA access",
            "Docker served noVNC login",
            "Physical phone",
            "Public image installation",
            "Optional authorized external notification delivery",
        ],
    }


def main() -> None:
    """Write a private JSON report and return failure when checks cannot pass."""
    from dotenv import load_dotenv

    load_dotenv(Path(".env"), override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixture", "live"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--url", help="Running application URL; uses its collector without downtime."
    )
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.url and args.mode != "live":
        parser.error("--url is supported only with --mode live")
    started = time.monotonic()
    if args.mode == "fixture":
        result = verify_fixture(args.report)
    elif args.url:
        result = asyncio.run(verify_live_service(args.url, wait_seconds=args.wait_seconds))
    else:
        result = asyncio.run(verify_live())
    result.update(
        {
            "version": __version__,
            "mode": args.mode,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    args.report.chmod(0o600)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
