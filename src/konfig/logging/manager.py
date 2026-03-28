"""LogManager — configure Python logging from settings."""
from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from konfig.logging.formatters import JSONFormatter, TextFormatter
from konfig.logging.run_directory import cleanup_old_runs, create_run_directory


class LogManager:
    """Configures Python logging from settings with run-scoped directories.

    CRITICAL: Never writes to stdout. Console output goes to stderr only.

    Args:
        app_name: Application name for the startup banner.
        version: Application version for the startup banner.
        log_dir: Base directory for run-scoped logs. If not provided,
            uses the platform-conventional log directory for ``app_id``.
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: "text" or "json".
        retention_runs: Number of historical run directories to keep.
        max_file_size_mb: Max log file size in MB before rotation.
        max_files_per_run: Max rotated log files per run.
        console_output: "auto", "stderr", or "none".
        app_id: Application identifier for default path resolution.
            If not provided, derived from ``app_name``.
    """

    def __init__(
        self,
        app_name: str = "Application",
        version: str = "0.0.0",
        log_dir: Optional[str | Path] = None,
        level: str = "INFO",
        log_format: str = "text",
        retention_runs: int = 10,
        max_file_size_mb: int = 50,
        max_files_per_run: int = 3,
        console_output: str = "auto",
        app_id: Optional[str] = None,
    ) -> None:
        from konfig.paths import app_id_from
        from konfig.paths import log_dir as platform_log_dir

        self._app_name = app_name
        self._version = version
        resolved_app_id = app_id or app_id_from(app_name)
        self._log_dir = Path(log_dir) if log_dir is not None else platform_log_dir(resolved_app_id)
        self._level = getattr(logging, level.upper(), logging.INFO)
        self._format = log_format
        self._retention_runs = retention_runs
        self._max_file_size = max_file_size_mb * 1024 * 1024
        self._max_files = max_files_per_run
        self._console_output = console_output
        self._run_dir: Optional[Path] = None
        self._handlers: list[logging.Handler] = []

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        app_name: str = "Application",
        version: str = "0.0.0",
        app_id: Optional[str] = None,
    ) -> LogManager:
        """Create a LogManager configured from a Settings instance.

        Args:
            settings: A Settings instance.
            app_name: Application name.
            version: Application version.
            app_id: Application identifier for default path resolution.

        Returns:
            Configured LogManager instance.
        """
        return cls(
            app_name=app_name,
            version=version,
            log_dir=settings.get("logging.log_dir"),
            level=settings.get("logging.level", "INFO"),
            log_format=settings.get("logging.format", "text"),
            retention_runs=settings.get("logging.retention_runs", 10, cast=int),
            max_file_size_mb=settings.get("logging.max_file_size_mb", 50, cast=int),
            max_files_per_run=settings.get("logging.max_files_per_run", 3, cast=int),
            console_output=settings.get("logging.console_output", "auto"),
            app_id=app_id,
        )

    def setup(self) -> logging.Logger:
        """Set up logging: create run dir, configure handlers, log startup banner.

        Returns:
            The root logger.
        """
        cleanup_old_runs(self._log_dir, self._retention_runs)

        self._run_dir = create_run_directory(self._log_dir)

        root = logging.getLogger()
        root.setLevel(self._level)

        formatter = JSONFormatter() if self._format == "json" else TextFormatter()

        file_handler = RotatingFileHandler(
            self._run_dir / "app.log",
            maxBytes=self._max_file_size,
            backupCount=self._max_files,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        self._handlers.append(file_handler)

        if self._should_add_console():
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)
            self._handlers.append(console_handler)

        self._log_startup_banner()

        return root

    def _should_add_console(self) -> bool:
        if self._console_output == "none":
            return False
        # "auto" and "stderr" both go to stderr. Never stdout.
        return True

    def _log_startup_banner(self) -> None:
        logger = logging.getLogger("konfig")
        separator = "\u2500" * 34
        logger.info(separator)
        logger.info("App:       %s", self._app_name)
        logger.info("Version:   %s", self._version)
        logger.info("PID:       %s", _get_pid())
        logger.info("Platform:  %s", _get_platform())
        logger.info("Python:    %s", platform.python_version())
        logger.info("Log Dir:   %s", self._run_dir)
        logger.info("Log Level: %s", logging.getLevelName(self._level))
        logger.info(separator)

    @property
    def run_dir(self) -> Optional[Path]:
        """Path to the current run's log directory."""
        return self._run_dir

    def shutdown(self) -> None:
        """Close and remove all handlers added by this manager."""
        root = logging.getLogger()
        for handler in self._handlers:
            handler.close()
            root.removeHandler(handler)
        self._handlers.clear()


def _get_pid() -> int:
    import os
    return os.getpid()


def _get_platform() -> str:
    system = platform.system()
    release = platform.release()
    machine = platform.machine()
    if system == "Darwin":
        mac_ver = platform.mac_ver()[0]
        if mac_ver:
            return f"{system}-{release}-{machine} (macOS {mac_ver})"
        return f"{system}-{release}-{machine} (macOS)"
    return f"{system}-{release}-{machine}"
