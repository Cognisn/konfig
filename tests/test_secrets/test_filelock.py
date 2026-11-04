"""Tests for the cross-process advisory file lock."""

from __future__ import annotations

import multiprocessing
import stat
import sys
import threading
from pathlib import Path

import pytest

from konfig.secrets._filelock import FileLock
from tests.test_secrets._mp_workers import hold_exclusive_lock


def test_creates_lock_file_and_never_deletes_it(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "secrets.enc.lock"
    with FileLock(lock_path).exclusive():
        assert lock_path.exists()
    assert lock_path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_lock_file_is_owner_only_on_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prove the mode comes from creation, not from a later chmod.
    monkeypatch.setattr(Path, "chmod", lambda *a, **k: None)
    monkeypatch.setattr("os.chmod", lambda *a, **k: None)
    lock_path = tmp_path / "secrets.enc.lock"
    with FileLock(lock_path).shared():
        pass
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_reentrant_within_a_thread(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "x.lock")
    with lock.exclusive():
        with lock.shared():
            with lock.exclusive():
                pass


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows locks are always exclusive"
)
def test_upgrade_from_shared_is_refused(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "x.lock")
    with lock.shared():
        with pytest.raises(RuntimeError, match="upgrade"):
            with lock.exclusive():
                pass


def test_excludes_other_threads_in_the_same_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "x.lock"
    label = tmp_path / "secrets.enc"
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with FileLock(lock_path).exclusive():
            held.set()
            release.wait(10)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(10)
        with pytest.raises(TimeoutError, match="secrets.enc"):
            with FileLock(lock_path, timeout=0.2, label=label).shared():
                pass
    finally:
        release.set()
        thread.join()
    # Once released, the lock is available again.
    with FileLock(lock_path, timeout=1).exclusive():
        pass


def test_times_out_when_another_process_holds_the_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "secrets.enc.lock"
    label = tmp_path / "secrets.enc"
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    proc = ctx.Process(
        target=hold_exclusive_lock, args=(str(lock_path), ready, release)
    )
    proc.start()
    try:
        assert ready.wait(60), "child process never acquired the lock"
        with pytest.raises(TimeoutError) as excinfo:
            with FileLock(lock_path, timeout=0.3, label=label).exclusive():
                pass
        assert str(label) in str(excinfo.value)
    finally:
        release.set()
        proc.join(60)
    assert proc.exitcode == 0
    with FileLock(lock_path, timeout=5).exclusive():
        pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_shared_lock_in_read_only_directory_without_lock_file(tmp_path: Path) -> None:
    import os

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    ro_dir.chmod(0o500)
    try:
        with FileLock(ro_dir / "secrets.enc.lock").shared():
            pass
        with pytest.raises(PermissionError):
            with FileLock(ro_dir / "secrets.enc.lock").exclusive():
                pass
    finally:
        ro_dir.chmod(0o700)
