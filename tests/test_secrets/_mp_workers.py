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


def write_keys(
    path: str, master_key: str, worker: int, count: int, start: Event
) -> None:
    """Write ``count`` distinct keys owned by ``worker``."""
    from konfig.secrets.encrypted_file import EncryptedFileBackend

    backend = EncryptedFileBackend(Path(path), master_key=master_key)
    start.wait(60)
    for i in range(count):
        backend.set(f"w{worker}-k{i}", f"value-{worker}-{i}")


def churn_keys(
    path: str, master_key: str, deleting: bool, rounds: int, start: Event
) -> None:
    """Repeatedly set (or delete) the shared ``churn-*`` keys."""
    from konfig.secrets.encrypted_file import EncryptedFileBackend

    backend = EncryptedFileBackend(Path(path), master_key=master_key)
    start.wait(60)
    for round_no in range(rounds):
        for i in range(5):
            if deleting:
                backend.delete(f"churn-{i}")
            else:
                backend.set(f"churn-{i}", f"churn-value-{i}")
        backend.set(f"{'deleter' if deleting else 'setter'}-{round_no}", "done")
