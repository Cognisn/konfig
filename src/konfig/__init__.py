"""Konfig — Settings, Secrets, and Logging for Python applications."""
from __future__ import annotations

from pathlib import Path

from konfig.app import AppContext
from konfig.logging.manager import LogManager
from konfig.secrets.secrets import Secrets
from konfig.settings.settings import Settings

__all__ = [
    "AppContext",
    "LogManager",
    "Secrets",
    "Settings",
    "__version__",
]


def _read_version() -> str:
    version_file = Path(__file__).parent / "_version.txt"
    return version_file.read_text(encoding="utf-8").strip()


__version__ = _read_version()
