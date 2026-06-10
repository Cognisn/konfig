"""SQLite backing store for config settings.

Stores a nested config dict as a flat key-value table: each leaf value is one
row keyed by its dot-notation path, with the value JSON-encoded.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS settings (" "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten a nested dict into (dot-key, leaf-value) pairs.

    A leaf is any non-dict value (scalars and lists). Empty dicts yield no rows.
    """
    rows: list[tuple[str, Any]] = []
    for key, value in data.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.extend(_flatten(value, full))
        else:
            rows.append((full, value))
    return rows


def _unflatten(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    """Rebuild a nested dict from (dot-key, leaf-value) pairs."""
    result: dict[str, Any] = {}
    for key, value in rows:
        parts = key.split(".")
        current = result
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    return result


def read_sqlite(path: Path) -> dict[str, Any]:
    """Read all settings into a nested dict.

    Returns ``{}`` if the file or the ``settings`` table does not exist yet.
    """
    path = Path(path)
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    try:
        present = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
        if present is None:
            return {}
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    finally:
        conn.close()
    return _unflatten([(key, json.loads(value)) for key, value in rows])


def write_sqlite(path: Path, data: dict[str, Any]) -> None:
    """Replace the ``settings`` table contents with the flattened nested dict."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        with conn:  # transaction: commit on success, rollback on error
            conn.execute(_CREATE_TABLE)
            conn.execute("DELETE FROM settings")
            conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in _flatten(data)],
            )
    finally:
        conn.close()
