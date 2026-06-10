"""Config file parsers for YAML, TOML, and JSON formats."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


# TOML is intentionally NOT overridable via KONFIG_CONFIG_FORMAT: it is read-only,
# so it is reachable only by file extension, never forced as a writable format.
ALLOWED_FORMAT_OVERRIDES = ("yaml", "json", "sqlite")

_EXTENSION_FORMATS = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
}


def _format_from_extension(path: Path) -> Optional[str]:
    """Map a file extension to a format, or None if unrecognised."""
    return _EXTENSION_FORMATS.get(Path(path).suffix.lower())


def resolve_format(path: Optional[Path], override: Optional[str]) -> str:
    """Resolve the active config format.

    Precedence: explicit ``override`` (from ``KONFIG_CONFIG_FORMAT``) ->
    file extension -> ``"yaml"``.

    Raises:
        ValueError: If ``override`` is set but not one of yaml/json/sqlite.
    """
    if override:
        normalised = override.strip().lower()
        if normalised not in ALLOWED_FORMAT_OVERRIDES:
            raise ValueError(
                f"Invalid KONFIG_CONFIG_FORMAT {override!r}; "
                f"allowed values: {', '.join(ALLOWED_FORMAT_OVERRIDES)}"
            )
        return normalised
    if path is not None:
        detected = _format_from_extension(path)
        if detected is not None:
            return detected
    return "yaml"


def parse_file(path: Path, fmt: Optional[str] = None) -> dict[str, Any]:
    """Parse a config file. If ``fmt`` is given it is used; otherwise the
    format is detected from the file extension.

    Supported formats: yaml, toml, json, sqlite.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the format cannot be determined or is unsupported.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    if fmt is None:
        fmt = _format_from_extension(path)
        if fmt is None:
            raise ValueError(f"Unsupported config file format: {path.suffix}")

    if fmt == "yaml":
        return _parse_yaml(path)
    elif fmt == "toml":
        return _parse_toml(path)
    elif fmt == "json":
        return _parse_json(path)
    elif fmt == "sqlite":
        from konfig.settings.sqlite_store import read_sqlite

        return read_sqlite(path)
    else:
        raise ValueError(f"Unsupported config file format: {fmt}")


def _parse_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _parse_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _parse_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("JSON config file must contain a top-level object")
    return data


def write_file(path: Path, data: dict[str, Any], fmt: Optional[str] = None) -> None:
    """Write a config dict to file. If ``fmt`` is given it is used; otherwise
    the format is detected from the file extension.

    Writable formats: yaml, json, sqlite. TOML writing is not supported.

    Raises:
        ValueError: If the format cannot be determined or is unsupported for writing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt is None:
        fmt = _format_from_extension(path)
        if fmt is None:
            raise ValueError(
                f"Unsupported config file format for writing: {path.suffix}"
            )

    if fmt == "yaml":
        _write_yaml(path, data)
    elif fmt == "json":
        _write_json(path, data)
    elif fmt == "sqlite":
        from konfig.settings.sqlite_store import write_sqlite

        write_sqlite(path, data)
    elif fmt == "toml":
        raise ValueError(
            "Writing TOML config files is not supported. "
            "Use YAML, JSON, or SQLite for writable config files."
        )
    else:
        raise ValueError(f"Unsupported config file format for writing: {fmt}")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
