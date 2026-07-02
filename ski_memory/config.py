"""Configuration and local data-directory resolution.

Everything SKI Memory writes lives in a single per-user folder the user owns.
No data ever leaves this machine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "ski_memory"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def resolve_home() -> Path:
    """Return the SKI Memory data directory, creating it if needed.

    Resolution order:
      1. ``SKI_MEMORY_HOME`` environment variable, if set.
      2. ``~/.ski_memory`` on every platform (simple and predictable).
    """
    override = os.environ.get("SKI_MEMORY_HOME")
    base = Path(override).expanduser() if override else Path.home() / ".ski_memory"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass(frozen=True)
class Config:
    home: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def db_path(self) -> Path:
        return self.home / "ski_memory.db"

    @property
    def identity_key_path(self) -> Path:
        return self.home / "identity.key"

    @property
    def identity_pub_path(self) -> Path:
        return self.home / "identity.pub"


def load_config(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Config:
    return Config(home=resolve_home(), host=host, port=port)
