"""Tests for the LogManager."""
from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

import pytest

from konfig.logging.manager import LogManager
from konfig.settings.settings import Settings


@pytest.fixture(autouse=True)
def _clean_root_logger() -> Generator[None, None, None]:
    """Remove all handlers from root logger before and after each test."""
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    yield
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)


class TestLogManager:
    def test_setup_creates_run_dir(self, tmp_path: Path) -> None:
        manager = LogManager(log_dir=tmp_path / "logs")
        manager.setup()
        assert manager.run_dir is not None
        assert manager.run_dir.exists()
        assert (manager.run_dir / "app.log").exists()
        manager.shutdown()

    def test_setup_writes_banner(self, tmp_path: Path) -> None:
        manager = LogManager(
            app_name="TestApp",
            version="1.0.0",
            log_dir=tmp_path / "logs",
        )
        manager.setup()
        log_content = (manager.run_dir / "app.log").read_text()  # type: ignore[union-attr]
        assert "TestApp" in log_content
        assert "1.0.0" in log_content
        manager.shutdown()

    def test_never_writes_stdout(self, tmp_path: Path) -> None:
        import sys
        import io

        capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = capture
        try:
            manager = LogManager(log_dir=tmp_path / "logs")
            logger = manager.setup()
            logger.info("Test message")
            manager.shutdown()
        finally:
            sys.stdout = old_stdout

        assert capture.getvalue() == ""

    def test_console_output_none(self, tmp_path: Path) -> None:
        manager = LogManager(log_dir=tmp_path / "logs", console_output="none")
        manager.setup()
        # Manager should only have a file handler, no console
        our_handlers = manager._handlers
        stream_handlers = [
            h for h in our_handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ]
        assert len(stream_handlers) == 0
        manager.shutdown()

    def test_console_output_stderr(self, tmp_path: Path) -> None:
        import sys

        manager = LogManager(log_dir=tmp_path / "logs", console_output="stderr")
        manager.setup()
        our_handlers = manager._handlers
        stream_handlers = [
            h for h in our_handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].stream is sys.stderr
        manager.shutdown()

    def test_json_format(self, tmp_path: Path) -> None:
        import json

        manager = LogManager(
            log_dir=tmp_path / "logs",
            log_format="json",
            console_output="none",
        )
        logger = manager.setup()
        logger.info("test json")
        manager.shutdown()
        log_content = (manager.run_dir / "app.log").read_text()  # type: ignore[union-attr]
        # Each line should be valid JSON (banner lines + our message)
        for line in log_content.strip().splitlines():
            data = json.loads(line)
            assert "level" in data

    def test_retention_on_setup(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        for i in range(5):
            (log_dir / f"2026-03-{20 + i:02d}T10-00-00").mkdir(parents=True)
        manager = LogManager(log_dir=log_dir, retention_runs=3)
        manager.setup()
        # 5 old + 1 new = 6 total, keep 3 → should have 3 old + 1 new = but cleanup runs before creation
        # cleanup removes 2 oldest, leaving 3. Then new one is created = 4 total.
        from konfig.logging.run_directory import list_run_directories
        dirs = list_run_directories(log_dir)
        assert len(dirs) == 4  # 3 kept + 1 new
        manager.shutdown()

    def test_shutdown_removes_handlers(self, tmp_path: Path) -> None:
        manager = LogManager(log_dir=tmp_path / "logs")
        manager.setup()
        assert len(manager._handlers) > 0
        manager.shutdown()
        assert len(manager._handlers) == 0


class TestLogManagerFromSettings:
    def test_from_settings(self, tmp_path: Path) -> None:
        settings = Settings(defaults={
            "logging": {
                "log_dir": str(tmp_path / "logs"),
                "level": "DEBUG",
                "format": "text",
                "retention_runs": 5,
                "max_file_size_mb": 10,
                "max_files_per_run": 2,
                "console_output": "none",
            }
        })
        manager = LogManager.from_settings(settings, app_name="Test", version="0.1")
        manager.setup()
        assert manager.run_dir is not None
        manager.shutdown()
