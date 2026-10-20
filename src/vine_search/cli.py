"""Operator commands for installation, serving, and private data recovery."""

import os
import secrets
from pathlib import Path

import typer
import uvicorn

from vine_search.backup import create_backup, restore_backup
from vine_search.config import Config

app = typer.Typer(no_args_is_help=True)


@app.command()
def setup(directory: Path = Path(".")) -> None:
    """Create a private configuration without overwriting existing secrets."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".env"
    if path.exists():
        typer.echo("Configuration already exists; no changes made.")
        return
    data = directory / "data"
    for name in ("app", "session", "backups"):
        (data / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    contents = (
        "VINE_SEARCH_BIND=127.0.0.1\nVINE_SEARCH_PORT=8765\n"
        "VINE_SEARCH_DATA_DIR=./data/app\nVINE_SEARCH_SESSION_DIR=./data/session\n"
        f"VINE_SEARCH_COLLECTOR_SECRET={secrets.token_urlsafe(48)}\n"
        "VINE_SEARCH_ALLOWED_HOSTS=localhost,127.0.0.1,::1\n"
    )
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as target:
        target.write(contents)
    typer.echo("Created .env and private data directories. Start with docker compose up -d.")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", envvar="VINE_SEARCH_BIND"),
    port: int = typer.Option(8765, envvar="VINE_SEARCH_PORT"),
) -> None:
    """Serve the private dashboard."""
    from vine_search.web import create_app

    uvicorn.run(create_app(), host=host, port=port, access_log=False)


@app.command()
def collector() -> None:
    """Run the exclusive browser owner and background delivery worker."""
    from vine_search.collector import run

    run()


@app.command()
def demo(directory: Path = Path("data/demo")) -> None:
    """Create synthetic demonstration records in a separate, empty installation."""
    from vine_search.demo import seed_demo

    seed_demo(directory)
    typer.echo(f"Synthetic demo created in {directory}. It is not live inventory.")


@app.command()
def backup(destination: Path) -> None:
    """Back up database, settings and private browser state; stop collector first."""
    data_dir = Config().data_dir
    session_dir = Path(os.getenv("VINE_SEARCH_SESSION_DIR", "data/session"))
    try:
        result = create_backup(data_dir, session_dir, destination)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Private backup saved to {result}. Keep it protected; it contains session material."
    )


@app.command()
def restore(
    archive: Path,
    data_dir: Path = Path("data/restored-app"),
    session_dir: Path = Path("data/restored-session"),
) -> None:
    """Restore to fresh directories, preserving any existing installation."""
    try:
        restore_backup(archive, data_dir, session_dir)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Restored to {data_dir} and {session_dir}. Point a stopped installation there.")


def main() -> None:
    """Load only this installation's explicit environment file and invoke the CLI."""
    from dotenv import load_dotenv

    load_dotenv(Path(".env"), override=False)
    app()
