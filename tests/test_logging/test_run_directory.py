"""Tests for run directory creation and retention."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from konfig.logging.run_directory import (
    cleanup_old_runs,
    create_run_directory,
    list_run_directories,
)


class TestCreateRunDirectory:
    def test_creates_directory(self, tmp_path: Path) -> None:
        run_dir = create_run_directory(tmp_path / "logs")
        assert run_dir.exists()
        assert run_dir.is_dir()

    def test_creates_base_dir(self, tmp_path: Path) -> None:
        base = tmp_path / "deep" / "nested" / "logs"
        run_dir = create_run_directory(base)
        assert base.exists()
        assert run_dir.exists()

    def test_timestamp_name(self, tmp_path: Path) -> None:
        run_dir = create_run_directory(tmp_path)
        # Name should be like 2026-03-28T14-30-00
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}", run_dir.name)

    def test_latest_symlink(self, tmp_path: Path) -> None:
        run_dir = create_run_directory(tmp_path)
        latest = tmp_path / "latest"
        assert latest.is_symlink()
        assert latest.resolve() == run_dir.resolve()

    def test_latest_symlink_updated(self, tmp_path: Path) -> None:
        create_run_directory(tmp_path)
        time.sleep(1.1)
        run2 = create_run_directory(tmp_path)
        latest = tmp_path / "latest"
        assert latest.resolve() == run2.resolve()


class TestCleanupOldRuns:
    def _make_run_dirs(self, base: Path, count: int) -> list[Path]:
        dirs = []
        for i in range(count):
            d = base / f"2026-03-{28 - count + i + 1:02d}T10-00-00"
            d.mkdir(parents=True)
            (d / "app.log").write_text("log content")
            dirs.append(d)
        return dirs

    def test_keeps_n_most_recent(self, tmp_path: Path) -> None:
        self._make_run_dirs(tmp_path, 5)
        removed = cleanup_old_runs(tmp_path, keep=3)
        assert len(removed) == 2
        remaining = list_run_directories(tmp_path)
        assert len(remaining) == 3

    def test_no_cleanup_when_under_limit(self, tmp_path: Path) -> None:
        self._make_run_dirs(tmp_path, 3)
        removed = cleanup_old_runs(tmp_path, keep=5)
        assert len(removed) == 0

    def test_ignores_non_timestamp_dirs(self, tmp_path: Path) -> None:
        self._make_run_dirs(tmp_path, 3)
        (tmp_path / "other_dir").mkdir()
        removed = cleanup_old_runs(tmp_path, keep=2)
        assert len(removed) == 1
        assert (tmp_path / "other_dir").exists()

    def test_nonexistent_base_dir(self, tmp_path: Path) -> None:
        removed = cleanup_old_runs(tmp_path / "nonexistent", keep=5)
        assert removed == []


class TestListRunDirectories:
    def test_list_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "2026-03-28T10-00-00").mkdir()
        (tmp_path / "2026-03-27T10-00-00").mkdir()
        (tmp_path / "2026-03-29T10-00-00").mkdir()
        dirs = list_run_directories(tmp_path)
        names = [d.name for d in dirs]
        assert names == ["2026-03-27T10-00-00", "2026-03-28T10-00-00", "2026-03-29T10-00-00"]

    def test_empty(self, tmp_path: Path) -> None:
        assert list_run_directories(tmp_path) == []
