"""Consistent private backups with a strict, non-overwriting restore boundary."""

import fcntl
import json
import os
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from vine_search import __version__
from vine_search.store import Store


@contextmanager
def session_lock(session_dir: Path) -> Iterator[None]:
    """Refuse to read a profile while the collector owns its browser."""
    session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (session_dir / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "Stop the collector before backing up or restoring its session."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def create_backup(data_dir: Path, session_dir: Path, destination: Path) -> Path:
    """Archive a SQLite snapshot and private session; no active browser files."""
    if destination.exists():
        raise ValueError("Backup destination already exists.")
    database = data_dir / "vine-search.sqlite3"
    if not database.is_file():
        raise ValueError("No application database exists at that location.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with session_lock(session_dir), tempfile.TemporaryDirectory() as temp:
        staging = Path(temp)
        Store(database).backup(staging / "vine-search.sqlite3")
        (staging / "manifest.json").write_text(
            json.dumps({"format": 1, "application_version": __version__})
        )
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with (
                os.fdopen(fd, "wb") as output,
                tarfile.open(fileobj=output, mode="w:gz") as archive,
            ):
                archive.add(staging / "manifest.json", arcname="manifest.json")
                archive.add(staging / "vine-search.sqlite3", arcname="app/vine-search.sqlite3")
                for item in sorted(session_dir.rglob("*")):
                    if item.is_symlink() or not item.is_file() or item.name == "collector.lock":
                        continue
                    archive.add(item, arcname=str(Path("session") / item.relative_to(session_dir)))
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return destination


def restore_backup(archive_path: Path, data_dir: Path, session_dir: Path) -> None:
    """Validate fully before restoring into fresh destinations; never overwrite history."""
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError("Restore requires an empty application directory.")
    if session_dir.exists() and any(session_dir.iterdir()):
        raise ValueError("Restore requires an empty session directory.")
    with tempfile.TemporaryDirectory() as temp:
        staging = Path(temp)
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if sum(member.size for member in members) > 4_000_000_000:
                raise ValueError("Backup exceeds the 4 GB restore limit.")
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or member.issym()
                    or member.islnk()
                    or not member.isfile()
                    or not (
                        member.name in {"manifest.json", "app/vine-search.sqlite3"}
                        or member.name.startswith("session/")
                    )
                ):
                    raise ValueError("Backup contains an unsupported or unsafe entry.")
                target = staging / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Backup entry cannot be read.")
                with source, target.open("xb") as output:
                    while block := source.read(1024 * 1024):
                        output.write(block)
        try:
            manifest = json.loads((staging / "manifest.json").read_text())
        except (OSError, ValueError) as exc:
            raise ValueError("Backup manifest is missing or invalid.") from exc
        if manifest.get("format") != 1:
            raise ValueError("Unsupported backup format; original data has not been changed.")
        # Store validates SQLite integrity and refuses newer schema versions.
        validated = staging / "validated.sqlite3"
        Store.restore(staging / "app/vine-search.sqlite3", validated)
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(validated, data_dir / "vine-search.sqlite3")
        restored_session = staging / "session"
        if restored_session.exists():
            import shutil

            shutil.copytree(restored_session, session_dir, dirs_exist_ok=True)
        for item in session_dir.rglob("*"):
            item.chmod(0o700 if item.is_dir() else 0o600)
