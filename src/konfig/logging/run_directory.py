"""Run-scoped log directory creation and historical retention."""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$")


def create_run_directory(base_dir: Path | str) -> Path:
    """Create a new run-scoped log directory.

    Creates a directory named with the current timestamp (e.g.
    ``2026-03-28T14-30-00``) under ``base_dir``, and updates
    a ``latest`` symlink.

    Args:
        base_dir: Base directory for all run logs.

    Returns:
        Path to the newly created run directory.
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    run_dir = base / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    _update_latest_symlink(base, run_dir)

    return run_dir


def _update_latest_symlink(base_dir: Path, target: Path) -> None:
    """Update the ``latest`` symlink to point to the given target."""
    link = base_dir / "latest"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target.name)
    except OSError:
        pass


def cleanup_old_runs(base_dir: Path | str, keep: int) -> list[Path]:
    """Remove old run directories, keeping the N most recent.

    Only directories matching the timestamp pattern are considered.

    Args:
        base_dir: Base directory containing run directories.
        keep: Number of most recent run directories to keep.

    Returns:
        List of paths that were removed.
    """
    base = Path(base_dir)
    if not base.exists():
        return []

    run_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and _TIMESTAMP_PATTERN.match(d.name)],
        key=lambda d: d.name,
    )

    if len(run_dirs) <= keep:
        return []

    to_remove = run_dirs[: len(run_dirs) - keep]
    removed: list[Path] = []
    for d in to_remove:
        shutil.rmtree(d)
        removed.append(d)

    return removed


def list_run_directories(base_dir: Path | str) -> list[Path]:
    """List all run directories sorted oldest to newest.

    Args:
        base_dir: Base directory containing run directories.

    Returns:
        Sorted list of run directory paths.
    """
    base = Path(base_dir)
    if not base.exists():
        return []

    return sorted(
        [d for d in base.iterdir() if d.is_dir() and _TIMESTAMP_PATTERN.match(d.name)],
        key=lambda d: d.name,
    )
