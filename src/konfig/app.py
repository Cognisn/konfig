"""AppContext — optional lightweight app lifecycle context manager."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from konfig.logging.manager import LogManager
from konfig.paths import app_id_from, default_config_file, default_system_config_file
from konfig.secrets.secrets import Secrets
from konfig.settings.settings import Settings


class AppContext:
    """Lifecycle context manager that wires together Settings, Secrets, and Logging.

    Supports both sync and async usage:

        with AppContext(name="MyApp") as ctx:
            ctx.settings.get("key")

        async with AppContext(name="MyApp") as ctx:
            await do_work(ctx.settings)

    When no ``config_file`` is specified, AppContext searches the
    platform-conventional config directory for a config file
    (config.yaml, config.yml, config.toml, config.json).

    The app identifier used for default paths is derived from
    ``env_prefix`` (lowercased) if provided, otherwise from ``name``.

    Args:
        name: Application name.
        version: Application version.
        config_file: Path to the user-level config file (YAML, TOML, or JSON).
            If not provided, auto-discovered from the platform user config dir.
        system_config_file: Path to the system-level config file.
            If not provided, auto-discovered from the platform system config dir.
            Read gracefully — unreadable files are silently skipped.
        defaults: Default settings dict.
        env_prefix: Prefix for environment variable mapping. Also used
            as the app identifier for default file paths.
        service_name: Namespace for secrets storage.
    """

    def __init__(
        self,
        name: str = "Application",
        version: str = "0.0.0",
        config_file: Optional[str | Path] = None,
        system_config_file: Optional[str | Path] = None,
        defaults: Optional[dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> None:
        self._name = name
        self._version = version
        self._env_prefix = env_prefix
        self._app_id = app_id_from(name, env_prefix)
        self._config_file = config_file or default_config_file(self._app_id)
        self._system_config_file = system_config_file or default_system_config_file(self._app_id)
        self._defaults = defaults
        self._service_name = service_name or self._app_id

        self._settings: Optional[Settings] = None
        self._secrets: Optional[Secrets] = None
        self._log_manager: Optional[LogManager] = None
        self._logger: Optional[logging.Logger] = None

    def _setup(self) -> None:
        """Initialise all subsystems."""
        self._settings = Settings(
            config_file=self._config_file,
            system_config_file=self._system_config_file,
            defaults=self._defaults,
            env_prefix=self._env_prefix,
        )

        self._secrets = Secrets(
            service_name=self._service_name,
            settings=self._settings,
        )

        self._log_manager = LogManager.from_settings(
            self._settings,
            app_name=self._name,
            version=self._version,
            app_id=self._app_id,
        )
        self._logger = self._log_manager.setup()

    def _teardown(self) -> None:
        """Clean up all subsystems."""
        if self._log_manager:
            self._log_manager.shutdown()

    def __enter__(self) -> AppContext:
        self._setup()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._teardown()

    async def __aenter__(self) -> AppContext:
        self._setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._teardown()

    @property
    def settings(self) -> Settings:
        """The Settings instance."""
        if self._settings is None:
            raise RuntimeError("AppContext is not initialised. Use it as a context manager.")
        return self._settings

    @property
    def secrets(self) -> Secrets:
        """The Secrets instance."""
        if self._secrets is None:
            raise RuntimeError("AppContext is not initialised. Use it as a context manager.")
        return self._secrets

    @property
    def logger(self) -> logging.Logger:
        """The root logger."""
        if self._logger is None:
            raise RuntimeError("AppContext is not initialised. Use it as a context manager.")
        return self._logger

    @property
    def log_manager(self) -> LogManager:
        """The LogManager instance."""
        if self._log_manager is None:
            raise RuntimeError("AppContext is not initialised. Use it as a context manager.")
        return self._log_manager
