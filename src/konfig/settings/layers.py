"""Layer implementations for the Settings system.

Layers (lowest to highest precedence):
  1. DefaultsLayer — hardcoded application defaults
  2. FileLayer (system) — system-wide config file
  3. FileLayer (user) — per-user config file
  4. EnvLayer — values from environment variables
  5. RuntimeLayer — values set programmatically at runtime
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from konfig.settings.parsers import parse_file, write_file

logger = logging.getLogger(__name__)


def _get_nested(data: dict[str, Any], key: str) -> Any:
    """Retrieve a value from a nested dict using dot-notation key."""
    parts = key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_nested(data: dict[str, Any], key: str, value: Any) -> None:
    """Set a value in a nested dict using dot-notation key."""
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _delete_nested(data: dict[str, Any], key: str) -> bool:
    """Delete a value from a nested dict using dot-notation key. Returns True if deleted."""
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]
        return True
    return False


def _get_section(data: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Get all keys under a prefix as a dict."""
    result = _get_nested(data, prefix)
    if isinstance(result, dict):
        return dict(result)
    return {}


class _Missing:
    """Sentinel for missing values."""
    _instance: Optional[_Missing] = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


class DefaultsLayer:
    """Layer 1: Hardcoded application defaults."""

    def __init__(self, defaults: Optional[dict[str, Any]] = None) -> None:
        self._data: dict[str, Any] = defaults or {}

    def get(self, key: str) -> Any:
        return _get_nested(self._data, key)

    def get_section(self, prefix: str) -> dict[str, Any]:
        return _get_section(self._data, prefix)

    @property
    def data(self) -> dict[str, Any]:
        return self._data


class FileLayer:
    """Values loaded from a config file (YAML, TOML, or JSON).

    Supports optional persistence: ``set()`` and ``delete()`` modify the
    in-memory data and write it back to the file. If the file or its
    directory is not writable, a ``PermissionError`` is raised.

    Args:
        path: Path to the config file. If None, the layer is empty.
        graceful: If True, silently ignore read errors (e.g. permission
            denied). Useful for system-wide config that may be unreadable.
    """

    def __init__(self, path: Optional[Path] = None, *, graceful: bool = False) -> None:
        self._path = Path(path) if path else None
        self._data: dict[str, Any] = {}
        self._graceful = graceful
        if self._path:
            self.reload()

    def reload(self) -> None:
        """Reload the config file from disk."""
        if not self._path:
            return
        try:
            if self._path.exists():
                self._data = parse_file(self._path)
        except (OSError, PermissionError) as exc:
            if self._graceful:
                logger.debug("Could not read config file %s: %s", self._path, exc)
                self._data = {}
            else:
                raise

    def set(self, key: str, value: Any) -> None:
        """Set a value and persist to the config file.

        Raises:
            PermissionError: If the file or directory is not writable.
            RuntimeError: If no file path is configured.
        """
        if not self._path:
            raise RuntimeError("Cannot persist setting: no config file path configured")
        _set_nested(self._data, key, value)
        self._write()

    def delete(self, key: str) -> bool:
        """Delete a value and persist to the config file.

        Returns:
            True if the key was found and deleted.

        Raises:
            PermissionError: If the file or directory is not writable.
            RuntimeError: If no file path is configured.
        """
        if not self._path:
            raise RuntimeError("Cannot persist setting: no config file path configured")
        deleted = _delete_nested(self._data, key)
        if deleted:
            self._write()
        return deleted

    def _write(self) -> None:
        """Write current data back to the config file."""
        assert self._path is not None
        try:
            write_file(self._path, self._data)
        except OSError as exc:
            raise PermissionError(
                f"Cannot write to config file {self._path}: {exc}"
            ) from exc

    def get(self, key: str) -> Any:
        return _get_nested(self._data, key)

    def get_section(self, prefix: str) -> dict[str, Any]:
        return _get_section(self._data, prefix)

    @property
    def path(self) -> Optional[Path]:
        """The config file path, or None."""
        return self._path

    @property
    def data(self) -> dict[str, Any]:
        return self._data


class EnvLayer:
    """Layer 3: Values from environment variables.

    Nested keys are mapped using ``__`` as separator.
    An optional prefix scopes which env vars are considered.

    Example: with prefix ``MYAPP``, the env var ``MYAPP__DATABASE__HOST``
    maps to the key ``database.host``.
    """

    def __init__(self, prefix: Optional[str] = None) -> None:
        self._prefix = prefix.upper() if prefix else None

    def get(self, key: str) -> Any:
        env_key = self._key_to_env(key)
        value = os.environ.get(env_key)
        if value is not None:
            return value
        return _MISSING

    def _key_to_env(self, key: str) -> str:
        env_key = key.upper().replace(".", "__")
        if self._prefix:
            return f"{self._prefix}__{env_key}"
        return env_key

    def get_section(self, prefix: str) -> dict[str, Any]:
        """Scan environment for all keys under a prefix."""
        env_prefix = self._key_to_env(prefix) + "__"
        result: dict[str, Any] = {}
        for env_key, value in os.environ.items():
            if env_key.startswith(env_prefix):
                remainder = env_key[len(env_prefix):].lower().replace("__", ".")
                _set_nested(result, remainder, value)
        return result

    @property
    def data(self) -> dict[str, Any]:
        return {}


class RuntimeLayer:
    """Layer 4: Values set programmatically at runtime."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return _get_nested(self._data, key)

    def set(self, key: str, value: Any) -> None:
        _set_nested(self._data, key, value)

    def delete(self, key: str) -> bool:
        return _delete_nested(self._data, key)

    def get_section(self, prefix: str) -> dict[str, Any]:
        return _get_section(self._data, prefix)

    @property
    def data(self) -> dict[str, Any]:
        return self._data
