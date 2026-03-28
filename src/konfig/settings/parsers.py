"""Config file parsers for YAML, TOML, and JSON formats."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def parse_file(path: Path) -> dict[str, Any]:
    """Parse a config file, auto-detecting format from file extension.

    Supported extensions: .yaml, .yml, .toml, .json

    Args:
        path: Path to the config file.

    Returns:
        Parsed configuration as a nested dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not supported.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _parse_yaml(path)
    elif suffix == ".toml":
        return _parse_toml(path)
    elif suffix == ".json":
        return _parse_json(path)
    else:
        raise ValueError(f"Unsupported config file format: {suffix}")


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


def write_file(path: Path, data: dict[str, Any]) -> None:
    """Write a config dict to file, auto-detecting format from extension.

    Supported extensions: .yaml, .yml, .json

    TOML writing is not supported (no stdlib writer in Python <3.11 and
    ``tomli`` is read-only). Use YAML or JSON for writable config files.

    Args:
        path: Path to the config file.
        data: Configuration dict to write.

    Raises:
        ValueError: If the file extension is not supported for writing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        _write_yaml(path, data)
    elif suffix == ".json":
        _write_json(path, data)
    elif suffix == ".toml":
        raise ValueError(
            "Writing TOML config files is not supported. "
            "Use YAML or JSON for writable config files."
        )
    else:
        raise ValueError(f"Unsupported config file format for writing: {suffix}")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
