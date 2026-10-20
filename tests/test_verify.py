"""Verification reports must distinguish actual results from unavailable prerequisites."""

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from vine_search import verify
from vine_search.amazon import Scan


@pytest.mark.asyncio
async def test_live_missing_session_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINE_SEARCH_SESSION_DIR", str(tmp_path / "absent"))
    monkeypatch.delenv("VINE_SEARCH_AUTH_FILE", raising=False)
    result = await verify.verify_live()
    assert result["status"] == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expected",
    [
        ("complete", "passed"),
        ("truncated", "passed"),
        ("failed", "failed"),
        ("needs_login", "blocked"),
        ("exception", "blocked"),
    ],
)
async def test_live_report_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, expected: str
) -> None:
    """Controlled adapters test report logic only; they are never live evidence."""
    (tmp_path / "profile").mkdir()
    monkeypatch.setenv("VINE_SEARCH_SESSION_DIR", str(tmp_path))
    released: list[bool] = []

    class Page:
        url = "https://www.amazon.com/vine/vine-items"

        async def content(self) -> str:
            return "<div>Synthetic report-classification page</div>"

    class Owner:
        def __init__(self, _: Path) -> None:
            self.pages = [Page()]

        def acquire_process(self) -> None:
            if state == "exception":
                raise OSError("no browser")

        def release_process(self) -> None:
            released.append(True)

        @asynccontextmanager
        async def claim(self, _: str) -> Any:
            yield

        @asynccontextmanager
        async def browser(self) -> Any:
            yield self

    async def collect(*_: Any, **__: Any) -> Scan:
        return Scan(state, pages=1)

    monkeypatch.setattr("vine_search.login.BrowserOwner", Owner)
    monkeypatch.setattr("vine_search.amazon.collect", collect)
    monkeypatch.setattr("vine_search.amazon.signed_in_vine", lambda *_: True)
    result = await verify.verify_live()
    assert result["status"] == expected
    assert released == [True]
    if expected != "blocked":
        assert len(result["scans"]) == 4


@pytest.mark.parametrize("code,status", [(0, "passed"), (1, "failed")])
def test_fixture_report_carries_command_exit_and_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, status: str
) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["-m", "pytest"]
        kwargs["stdout"].write("Controlled subprocess report test\n")
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr("vine_search.verify.subprocess.run", run)
    result = verify.verify_fixture(tmp_path / "fixture.json")
    assert result["status"] == status
    assert result["exit_code"] == code
    assert (tmp_path / "fixture.log").is_file()


def test_verification_entrypoint_returns_nonzero_when_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["verify", "--mode", "fixture", "--report", str(target)])
    monkeypatch.setattr(verify, "verify_fixture", lambda _: {"status": "blocked"})
    with pytest.raises(SystemExit) as result:
        verify.main()
    assert result.value.code == 2
    assert json.loads(target.read_text())["status"] == "blocked"
    assert target.stat().st_mode & 0o777 == 0o600
