"""Private backup round trips and protection against unsafe restores."""

import fcntl
import io
import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vine_search.backup import create_backup, restore_backup
from vine_search.cli import app
from vine_search.demo import seed_demo
from vine_search.store import Store


def test_backup_restore_preserves_settings_reviews_and_session(tmp_path: Path) -> None:
    data = tmp_path / "app"
    session = tmp_path / "session"
    session.mkdir()
    (session / "state.json").write_text('{"cookies":["private"]}')
    seed_demo(data)
    store = Store(data / "vine-search.sqlite3")
    store.update_settings({"notification_secret": "private-secret"})
    archive = create_backup(data, session, tmp_path / "backup.tgz")
    assert archive.stat().st_mode & 0o777 == 0o600
    restore_backup(archive, tmp_path / "restored", tmp_path / "restored-session")
    restored = Store(tmp_path / "restored/vine-search.sqlite3")
    assert restored.list_products()["total"] == 15
    assert restored.list_reviews()["total"] == 4
    assert restored.get_settings(include_secrets=True)["notification_secret"] == "private-secret"
    assert (tmp_path / "restored-session/state.json").read_text() == '{"cookies":["private"]}'
    with pytest.raises(ValueError, match="empty"):
        restore_backup(archive, data, tmp_path / "another-session")
    with pytest.raises(ValueError, match="already exists"):
        create_backup(data, session, archive)
    with pytest.raises(ValueError, match="empty database"):
        seed_demo(data)


def test_backup_refuses_active_collector_and_missing_db(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No application database"):
        create_backup(tmp_path / "missing", tmp_path / "session", tmp_path / "no.tgz")
    data, session = tmp_path / "app", tmp_path / "session"
    seed_demo(data)
    session.mkdir()
    with (session / "collector.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="Stop the collector"):
            create_backup(data, session, tmp_path / "no.tgz")
        fcntl.flock(lock, fcntl.LOCK_UN)


@pytest.mark.parametrize("entry", ["../escape", "/tmp/escape", "unknown", "session/../../escape"])
def test_restore_rejects_traversal_before_any_write(tmp_path: Path, entry: str) -> None:
    archive = tmp_path / "malicious.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo(entry)
        member.size = 4
        tar.addfile(member, io.BytesIO(b"evil"))
    with pytest.raises(ValueError, match="unsafe"):
        restore_backup(archive, tmp_path / "data", tmp_path / "session")
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "escape").exists()


def test_restore_rejects_unknown_manifest_and_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "future.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        body = json.dumps({"format": 999}).encode()
        member = tarfile.TarInfo("manifest.json")
        member.size = len(body)
        tar.addfile(member, io.BytesIO(body))
    with pytest.raises(ValueError, match="Unsupported backup"):
        restore_backup(archive, tmp_path / "data", tmp_path / "session")
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("session/escape")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc"
        tar.addfile(member)
    with pytest.raises(ValueError, match="unsafe"):
        restore_backup(archive, tmp_path / "data", tmp_path / "session")


def test_cli_setup_is_private_and_never_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--directory", str(tmp_path)])
    assert result.exit_code == 0, result.output
    config = tmp_path / ".env"
    original = config.read_text()
    assert config.stat().st_mode & 0o777 == 0o600
    assert runner.invoke(app, ["setup", "--directory", str(tmp_path)]).exit_code == 0
    assert config.read_text() == original
    assert runner.invoke(app, ["demo", "--directory", str(tmp_path / "demo")]).exit_code == 0
    assert (tmp_path / "demo/DEMO").is_file()


def test_cli_backup_restore_failures_are_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINE_SEARCH_DATA_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("VINE_SEARCH_SESSION_DIR", str(tmp_path / "session"))
    runner = CliRunner()
    assert runner.invoke(app, ["backup", str(tmp_path / "out.tgz")]).exit_code == 1
    assert runner.invoke(app, ["restore", str(tmp_path / "missing.tgz")]).exit_code == 1
