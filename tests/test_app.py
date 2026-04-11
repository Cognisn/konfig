"""Tests for the AppContext lifecycle."""
from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

import pytest

from konfig.app import AppContext


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


class TestAppContextSync:
    def test_context_manager(self, tmp_path: Path) -> None:
        config = tmp_path / "config.yaml"
        config.write_text("logging:\n  log_dir: {}\n  console_output: none\n".format(
            tmp_path / "logs"
        ))
        with AppContext(
            name="TestApp",
            version="1.0.0",
            config_file=config,
            defaults={"app": {"mode": "test"}},
        ) as ctx:
            assert ctx.settings.get("app.mode") == "test"
            assert ctx.secrets is not None
            assert ctx.logger is not None
            assert ctx.log_manager.run_dir is not None

    def test_settings_accessible(self, tmp_path: Path) -> None:
        with AppContext(
            name="Test",
            defaults={
                "key": "value",
                "logging": {"log_dir": str(tmp_path / "logs"), "console_output": "none"},
            },
        ) as ctx:
            assert ctx.settings.get("key") == "value"

    def test_secrets_accessible(self, tmp_path: Path) -> None:
        with AppContext(
            name="Test",
            defaults={
                "secrets": {
                    "backend": "encrypted_file",
                    "file_path": str(tmp_path / "secrets.enc"),
                    "master_key": "test-key",
                },
                "logging": {"log_dir": str(tmp_path / "logs"), "console_output": "none"},
            },
        ) as ctx:
            ctx.secrets.set("api_key", "sk-test")
            assert ctx.secrets.get("api_key") == "sk-test"

    def test_properties_raise_before_init(self) -> None:
        ctx = AppContext(name="Test")
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = ctx.settings
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = ctx.secrets
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = ctx.logger
        with pytest.raises(RuntimeError, match="not initialised"):
            _ = ctx.log_manager

    def test_cleanup_on_exit(self, tmp_path: Path) -> None:
        with AppContext(
            name="Test",
            defaults={"logging": {"log_dir": str(tmp_path / "logs"), "console_output": "none"}},
        ) as ctx:
            manager = ctx.log_manager
        # After exit, handlers should be cleaned up
        assert len(manager._handlers) == 0


class TestAppContextAsync:
    @pytest.mark.asyncio
    async def test_async_context_manager(self, tmp_path: Path) -> None:
        async with AppContext(
            name="AsyncApp",
            version="2.0.0",
            defaults={
                "app": {"async": True},
                "logging": {"log_dir": str(tmp_path / "logs"), "console_output": "none"},
            },
        ) as ctx:
            assert ctx.settings.get("app.async") is True
            assert ctx.logger is not None

    @pytest.mark.asyncio
    async def test_async_cleanup(self, tmp_path: Path) -> None:
        async with AppContext(
            name="Test",
            defaults={"logging": {"log_dir": str(tmp_path / "logs"), "console_output": "none"}},
        ) as ctx:
            manager = ctx.log_manager
        assert len(manager._handlers) == 0
