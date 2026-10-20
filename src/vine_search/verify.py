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

from vine_search import __version__


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
    args = parser.parse_args()
    started = time.monotonic()
    result = verify_fixture(args.report) if args.mode == "fixture" else asyncio.run(verify_live())
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
