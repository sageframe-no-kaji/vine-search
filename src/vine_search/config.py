"""Deployment configuration, separate from editable product behavior."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Process-local paths and the internal collector connection."""

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("VINE_SEARCH_DATA_DIR", "data")))
    collector_url: str = field(
        default_factory=lambda: os.getenv("VINE_SEARCH_COLLECTOR_URL", "http://127.0.0.1:8766")
    )
    collector_secret: str = field(
        default_factory=lambda: os.getenv("VINE_SEARCH_COLLECTOR_SECRET", "")
    )
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.getenv("VINE_SEARCH_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",")
        )
    )

    @property
    def database(self) -> Path:
        return self.data_dir / "vine-search.sqlite3"

    def prepare(self) -> None:
        """Create application storage without inspecting browser storage."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.collector_secret:
            raise ValueError("Run vine-search setup and load .env before starting the application.")
