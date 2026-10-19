"""Shared-store behaviour of the encrypted file backend.

Covers many processes, threads and instances using one encrypted file:
lost updates, freshness, atomic writes, permissions and lock timeouts.
"""

from __future__ import annotations

import multiprocessing
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from konfig.secrets.encrypted_file import EncryptedFileBackend
from konfig.secrets.secrets import Secrets
from konfig.settings.settings import Settings
from tests.test_secrets._mp_workers import churn_keys, hold_exclusive_lock, write_keys

MASTER_KEY = "shared-test-master-key"


def _run_processes(targets: list[tuple[object, tuple[object, ...]]]) -> None:
    """Start processes together (spawn), release them at once, and join."""
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    procs = [
        ctx.Process(target=target, args=(*args, start))  # type: ignore[arg-type]
        for target, args in targets
    ]
    for proc in procs:
        proc.start()
    start.set()
    for proc in procs:
        proc.join(180)
    for proc in procs:
        if proc.is_alive():
            proc.terminate()
    assert [proc.exitcode for proc in procs] == [0] * len(procs)


@pytest.mark.slow
class TestMultiProcess:
    def test_no_lost_updates(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        workers, count = 6, 25
        _run_processes(
            [(write_keys, (str(path), MASTER_KEY, w, count)) for w in range(workers)]
        )
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert len(backend.list_keys()) == workers * count
        for w in range(workers):
            for i in range(count):
                assert backend.get(f"w{w}-k{i}") == f"value-{w}-{i}"

    def test_concurrent_delete_and_set_stay_consistent(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        EncryptedFileBackend(path, master_key=MASTER_KEY).set("stable", "keep")
        rounds = 10
        _run_processes(
            [
                (churn_keys, (str(path), MASTER_KEY, False, rounds)),
                (churn_keys, (str(path), MASTER_KEY, True, rounds)),
            ]
        )
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert backend.get("stable") == "keep"
        for round_no in range(rounds):
            assert backend.get(f"setter-{round_no}") == "done"
            assert backend.get(f"deleter-{round_no}") == "done"
        for i in range(5):
            assert backend.get(f"churn-{i}") in (None, f"churn-value-{i}")


class TestFreshness:
    def test_reads_see_other_instance_writes(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        writer = EncryptedFileBackend(path, master_key=MASTER_KEY)
        reader = EncryptedFileBackend(path, master_key=MASTER_KEY)

        writer.set("api_key", "first")
        assert reader.get("api_key") == "first"
        assert reader.has("api_key") is True
        assert reader.list_keys() == ["api_key"]

        writer.set("api_key", "second")
        assert reader.get("api_key") == "second"

        writer.delete("api_key")
        assert reader.get("api_key") is None
        assert reader.list_keys() == []

    def test_reads_notice_file_removal(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        backend.set("key", "value")
        path.unlink()
        assert backend.get("key") is None

    def test_refresh_forces_reload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "secrets.enc"
        writer = EncryptedFileBackend(path, master_key=MASTER_KEY)
        reader = EncryptedFileBackend(path, master_key=MASTER_KEY)
        # Simulate an NFS attribute cache hiding the change from stat().
        monkeypatch.setattr(reader, "_ensure_fresh", lambda: None)
        writer.set("key", "value")
        assert reader.get("key") is None
        reader.refresh()
        assert reader.get("key") == "value"

    def test_writes_merge_with_other_instance_changes(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        a = EncryptedFileBackend(path, master_key=MASTER_KEY)
        b = EncryptedFileBackend(path, master_key=MASTER_KEY)
        a.set("from_a", "1")
        b.set("from_b", "2")
        a.delete("missing")
        fresh = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert sorted(fresh.list_keys()) == ["from_a", "from_b"]

    def test_delete_of_absent_key_does_not_rewrite(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        backend.set("key", "value")
        before = path.stat()
        backend.delete("absent")
        after = path.stat()
        assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


class TestThreads:
    def test_threads_writing_distinct_keys_all_survive(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        shared = EncryptedFileBackend(path, master_key=MASTER_KEY)
        threads_n, count = 8, 15
        errors: list[BaseException] = []

        def work(n: int) -> None:
            # Half the threads share one instance, half have their own.
            backend = (
                shared if n % 2 else EncryptedFileBackend(path, master_key=MASTER_KEY)
            )
            try:
                for i in range(count):
                    backend.set(f"t{n}-k{i}", f"v{n}-{i}")
                    backend.get(f"t{n}-k{i}")
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(threads_n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        fresh = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert len(fresh.list_keys()) == threads_n * count
        for n in range(threads_n):
            for i in range(count):
                assert fresh.get(f"t{n}-k{i}") == f"v{n}-{i}"


class TestCrashSafety:
    def test_failed_replace_keeps_original_and_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        backend.set("key", "original")

        def failing_replace(src: object, dst: object) -> None:
            raise OSError("simulated crash before rename")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="simulated crash"):
            backend.set("key", "updated")
        monkeypatch.undo()

        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "secrets.enc",
            "secrets.enc.lock",
        ]
        reopened = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert reopened.get("key") == "original"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
class TestCreationPermissions:
    def test_files_are_owner_only_from_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With chmod disabled, 0600 can only come from the creation mode.
        monkeypatch.setattr(Path, "chmod", lambda *a, **k: None)
        monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
        monkeypatch.delenv("KONFIG_MASTER_KEY", raising=False)
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path)
        backend.set("key", "value")
        for created in (path, path.with_suffix(".key"), tmp_path / "secrets.enc.lock"):
            assert stat.S_IMODE(created.stat().st_mode) == 0o600, created

    def test_save_tightens_a_permissive_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        backend.set("key", "value")
        path.chmod(0o644)
        backend.set("key", "value2")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestLockTimeout:
    def test_write_times_out_while_another_process_holds_the_lock(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY, lock_timeout=0.3)
        ctx = multiprocessing.get_context("spawn")
        ready, release = ctx.Event(), ctx.Event()
        proc = ctx.Process(
            target=hold_exclusive_lock,
            args=(str(tmp_path / "secrets.enc.lock"), ready, release),
        )
        proc.start()
        try:
            assert ready.wait(60), "child process never acquired the lock"
            with pytest.raises(TimeoutError) as excinfo:
                backend.set("key", "top-secret-value")
            message = str(excinfo.value)
            assert str(path) in message
            assert "top-secret-value" not in message
            assert MASTER_KEY not in message
        finally:
            release.set()
            proc.join(60)
        assert proc.exitcode == 0
        backend.set("key", "value")
        assert backend.get("key") == "value"

    def test_timeout_setting_is_wired_through_secrets(self, tmp_path: Path) -> None:
        settings = Settings(
            defaults={
                "secrets": {
                    "backend": "encrypted_file",
                    "file_path": str(tmp_path / "secrets.enc"),
                    "master_key": MASTER_KEY,
                    "file_lock_timeout": "2.5",
                }
            }
        )
        secrets = Secrets(service_name="test", settings=settings)
        assert isinstance(secrets._backend, EncryptedFileBackend)
        assert secrets._backend._lock._timeout == 2.5
