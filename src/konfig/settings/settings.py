"""Settings class — unified layered access to configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal, Optional, TypeVar

from konfig.settings.layers import (
    DefaultsLayer,
    EnvLayer,
    FileLayer,
    RuntimeLayer,
    _MISSING,
)

T = TypeVar("T")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """Unified settings with layered precedence.

    Layers (lowest to highest):
      1. defaults — hardcoded in the application
      2. system config file — system-wide, shared across all users
      3. user config file — per-user config
      4. environment variables — mapped from nested keys
      5. runtime overrides — set programmatically

    Args:
        config_file: Path to the user-level config file (YAML, TOML, or JSON).
        system_config_file: Path to the system-level config file. Read
            gracefully — if unreadable due to permissions, it is silently skipped.
        defaults: Dict of default values.
        env_prefix: Prefix for environment variable mapping.
    """

    def __init__(
        self,
        config_file: Optional[str | Path] = None,
        system_config_file: Optional[str | Path] = None,
        defaults: Optional[dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
    ) -> None:
        self._defaults_layer = DefaultsLayer(defaults)
        self._system_file_layer = FileLayer(
            Path(system_config_file) if system_config_file else None,
            graceful=True,
        )
        self._user_file_layer = FileLayer(
            Path(config_file) if config_file else None,
        )
        self._env_layer = EnvLayer(env_prefix)
        self._runtime_layer = RuntimeLayer()

    def get(
        self,
        key: str,
        default: Any = None,
        *,
        cast: Optional[Callable[..., Any]] = None,
    ) -> Any:
        """Get a setting value by dot-notation key.

        Layers are checked in reverse precedence order (highest first):
        runtime -> env -> user file -> system file -> defaults.

        Args:
            key: Dot-notation key (e.g. "database.host").
            default: Value to return if key is not found in any layer.
            cast: Optional callable to cast the value (e.g. int, float, bool).

        Returns:
            The resolved value, or default if not found.
        """
        for layer in self._read_order:
            value = layer.get(key)
            if value is not _MISSING:
                if cast is not None:
                    return cast(value)
                return value
        return default

    def has(self, key: str) -> bool:
        """Check if a key exists in any layer."""
        for layer in self._read_order:
            if layer.get(key) is not _MISSING:
                return True
        return False

    def set(
        self,
        key: str,
        value: Any,
        *,
        persist: Optional[Literal["user", "system"]] = None,
    ) -> None:
        """Set a setting value.

        By default, sets a runtime override (in-memory only, highest
        precedence). Use ``persist`` to write the value to a config file.

        Args:
            key: Dot-notation key.
            value: Value to set.
            persist: If ``"user"``, write to the user config file.
                If ``"system"``, write to the system config file.
                If ``None`` (default), set as a runtime override only.

        Raises:
            PermissionError: If ``persist="system"`` and the system config
                file is not writable.
            RuntimeError: If ``persist`` is set but no config file path is
                configured for that scope.
        """
        if persist is None:
            self._runtime_layer.set(key, value)
        elif persist == "user":
            self._user_file_layer.set(key, value)
        elif persist == "system":
            self._system_file_layer.set(key, value)
        else:
            raise ValueError(f"Invalid persist scope: {persist!r}")

    def delete(
        self,
        key: str,
        *,
        persist: Optional[Literal["user", "system"]] = None,
    ) -> bool:
        """Delete a setting value.

        By default, deletes from the runtime override layer. Use
        ``persist`` to delete from a config file.

        Args:
            key: Dot-notation key.
            persist: Scope to delete from. Same as ``set()``.

        Returns:
            True if the key was found and deleted, False otherwise.

        Raises:
            PermissionError: If ``persist="system"`` and the system config
                file is not writable.
        """
        if persist is None:
            return self._runtime_layer.delete(key)
        elif persist == "user":
            return self._user_file_layer.delete(key)
        elif persist == "system":
            return self._system_file_layer.delete(key)
        else:
            raise ValueError(f"Invalid persist scope: {persist!r}")

    def get_section(self, prefix: str) -> dict[str, Any]:
        """Get all keys under a prefix, merged across all layers.

        Args:
            prefix: Dot-notation prefix (e.g. "database").

        Returns:
            Merged dict of all matching keys.
        """
        result: dict[str, Any] = {}
        result = _deep_merge(result, self._defaults_layer.get_section(prefix))
        result = _deep_merge(result, self._system_file_layer.get_section(prefix))
        result = _deep_merge(result, self._user_file_layer.get_section(prefix))
        result = _deep_merge(result, self._env_layer.get_section(prefix))
        result = _deep_merge(result, self._runtime_layer.get_section(prefix))
        return result

    def reload(self) -> None:
        """Reload both config files from disk."""
        self._system_file_layer.reload()
        self._user_file_layer.reload()

    @property
    def _read_order(self) -> tuple:
        """Layers in highest-to-lowest precedence for reads."""
        return (
            self._runtime_layer,
            self._env_layer,
            self._user_file_layer,
            self._system_file_layer,
            self._defaults_layer,
        )
