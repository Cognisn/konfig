"""Worker functions for multi-process secrets tests.

Kept at module level in an importable module so the ``spawn`` start method
(the default on Windows and macOS) can locate them in child processes.
"""

from __future__ import annotations

from multiprocessing.synchronize import Event
from pathlib import Path

from konfig.secrets._filelock import FileLock


def hold_exclusive_lock(lock_path: str, ready: Event, release: Event) -> None:
    """Hold an exclusive lock until told to release it."""
    with FileLock(Path(lock_path)).exclusive():
        ready.set()
        release.wait(60)
