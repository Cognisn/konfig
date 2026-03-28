"""Platform-aware default paths for config, secrets, and logs.

Provides OS-conventional base directories:

  macOS:
    config  → ~/Library/Application Support/<app_id>/
    data    → ~/Library/Application Support/<app_id>/
    logs    → ~/Library/Logs/<app_id>/

  Linux:
    config  → $XDG_CONFIG_HOME/<app_id>/  (default ~/.config/)
    data    → $XDG_DATA_HOME/<app_id>/    (default ~/.local/share/)
    logs    → $XDG_STATE_HOME/<app_id>/logs/  (default ~/.local/state/)

  Windows:
    config  → %APPDATA%/<app_id>/
    data    → %APPDATA%/<app_id>/
    logs    → %LOCALAPPDATA%/<app_id>/logs/
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional


def app_id_from(name: str, env_prefix: Optional[str] = None) -> str:
    """Derive a filesystem-safe app identifier.

    Uses ``env_prefix`` (lowercased) if provided, otherwise sanitises
    ``name`` to a lowercase, underscore-separated slug.

    Args:
        name: Application display name.
        env_prefix: Optional environment variable prefix.

    Returns:
        Filesystem-safe identifier string.
    """
    if env_prefix:
        return env_prefix.lower()
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "konfig"


def config_dir(app_id: str) -> Path:
    """Return the platform-conventional config directory for an app."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_id
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_id
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg) / app_id


def data_dir(app_id: str) -> Path:
    """Return the platform-conventional data directory for an app."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_id
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_id
    else:
        xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg) / app_id


def log_dir(app_id: str) -> Path:
    """Return the platform-conventional log directory for an app."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / app_id
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return Path(local) / app_id / "logs"
    else:
        xdg = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
        return Path(xdg) / app_id / "logs"


def system_config_dir(app_id: str) -> Path:
    """Return the platform-conventional system-wide config directory.

    These are typically only writable by administrators/root:

      macOS:   /Library/Application Support/<app_id>/
      Linux:   /etc/<app_id>/
      Windows: %PROGRAMDATA%/<app_id>/
    """
    if sys.platform == "darwin":
        return Path("/Library/Application Support") / app_id
    elif sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / app_id
    else:
        return Path("/etc") / app_id


def _find_config_file(base: Path) -> Optional[Path]:
    """Search a directory for a config file (yaml, yml, toml, json)."""
    for name in ("config.yaml", "config.yml", "config.toml", "config.json"):
        path = base / name
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None


def default_config_file(app_id: str) -> Optional[Path]:
    """Find an existing config file in the platform user config directory.

    Searches for config.yaml, config.yml, config.toml, config.json
    in order. Returns the first match, or None if none exist.

    Args:
        app_id: Application identifier.

    Returns:
        Path to the config file, or None.
    """
    return _find_config_file(config_dir(app_id))


def default_system_config_file(app_id: str) -> Optional[Path]:
    """Find an existing config file in the platform system config directory.

    Same search order as ``default_config_file`` but in the system-wide
    directory. Returns None gracefully if the directory is unreadable.

    Args:
        app_id: Application identifier.

    Returns:
        Path to the system config file, or None.
    """
    return _find_config_file(system_config_dir(app_id))


def default_secrets_file(app_id: str) -> Path:
    """Return the default path for the encrypted secrets file.

    Args:
        app_id: Application identifier.

    Returns:
        Path to the secrets file.
    """
    return data_dir(app_id) / "secrets.enc"
