# Pluggable Config Format (YAML / JSON / SQLite) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the config file be stored as YAML, JSON, or SQLite, selectable via `KONFIG_CONFIG_FORMAT` (default YAML), with read/update/create working across all formats.

**Architecture:** SQLite becomes a third (de)serialisation format behind the existing `parse_file`/`write_file`, backed by a new `sqlite_store.py` that maps a nested config dict to a flat `settings(key, value)` table. A `resolve_format` helper picks the format (env override → extension → YAML). `FileLayer` gains an explicit `fmt`, and `Settings` resolves it once per config file. Persistence (`set(..., persist=...)`) already flows through `FileLayer`, so it works for SQLite unchanged.

**Tech Stack:** Python 3.12+, stdlib `sqlite3` (no new dependency), pytest.

---

## File Structure

- Create: `src/konfig/settings/sqlite_store.py` — SQLite read/write + flatten/unflatten.
- Modify: `src/konfig/settings/parsers.py` — `resolve_format`, extension map, `fmt` param on `parse_file`/`write_file`, SQLite dispatch.
- Modify: `src/konfig/settings/layers.py` — `FileLayer` gains `fmt`.
- Modify: `src/konfig/settings/settings.py` — read env var, resolve per-file format, pass `fmt` to `FileLayer`s.
- Create: `tests/test_settings/test_sqlite_store.py`.
- Modify: `tests/test_settings/test_parsers.py`, `tests/test_settings/test_layers.py`, `tests/test_settings/test_settings.py`.
- Modify: `README.md`, `CLAUDE.md`, `CHANGELOG.md`.

---

## Task 1: SQLite store module

**Files:**
- Create: `src/konfig/settings/sqlite_store.py`
- Test: `tests/test_settings/test_sqlite_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings/test_sqlite_store.py`:

```python
"""Tests for the SQLite config store."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from konfig.settings.sqlite_store import (
    _flatten,
    _unflatten,
    read_sqlite,
    write_sqlite,
)


class TestFlatten:
    def test_flatten_nested(self) -> None:
        data = {"database": {"host": "localhost", "port": 5432}, "debug": True}
        assert sorted(_flatten(data)) == [
            ("database.host", "localhost"),
            ("database.port", 5432),
            ("debug", True),
        ]

    def test_flatten_list_is_a_leaf(self) -> None:
        assert _flatten({"a": [1, 2, 3]}) == [("a", [1, 2, 3])]

    def test_flatten_empty_dict_yields_no_rows(self) -> None:
        assert _flatten({"a": {}}) == []


class TestUnflatten:
    def test_unflatten_roundtrip(self) -> None:
        rows = [("database.host", "localhost"), ("database.port", 5432)]
        assert _unflatten(rows) == {"database": {"host": "localhost", "port": 5432}}


class TestReadWrite:
    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        data = {
            "database": {"host": "localhost", "port": 5432},
            "debug": True,
            "tags": ["a", "b"],
            "ratio": 1.5,
            "nothing": None,
        }
        db = tmp_path / "config.sqlite"
        write_sqlite(db, data)
        assert read_sqlite(db) == data

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_sqlite(tmp_path / "absent.sqlite") == {}

    def test_read_file_without_table_returns_empty(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        sqlite3.connect(str(db)).close()  # creates the file, no settings table
        assert read_sqlite(db) == {}

    def test_write_replaces_previous_contents(self, tmp_path: Path) -> None:
        db = tmp_path / "config.sqlite"
        write_sqlite(db, {"a": 1, "b": 2})
        write_sqlite(db, {"a": 3})
        assert read_sqlite(db) == {"a": 3}

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        db = tmp_path / "nested" / "dir" / "config.sqlite"
        write_sqlite(db, {"a": 1})
        assert read_sqlite(db) == {"a": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings/test_sqlite_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'konfig.settings.sqlite_store'`

- [ ] **Step 3: Write the implementation**

Create `src/konfig/settings/sqlite_store.py`:

```python
"""SQLite backing store for config settings.

Stores a nested config dict as a flat key-value table: each leaf value is one
row keyed by its dot-notation path, with the value JSON-encoded.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS settings ("
    "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten a nested dict into (dot-key, leaf-value) pairs.

    A leaf is any non-dict value (scalars and lists). Empty dicts yield no rows.
    """
    rows: list[tuple[str, Any]] = []
    for key, value in data.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.extend(_flatten(value, full))
        else:
            rows.append((full, value))
    return rows


def _unflatten(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    """Rebuild a nested dict from (dot-key, leaf-value) pairs."""
    result: dict[str, Any] = {}
    for key, value in rows:
        parts = key.split(".")
        current = result
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    return result


def read_sqlite(path: Path) -> dict[str, Any]:
    """Read all settings into a nested dict.

    Returns ``{}`` if the file or the ``settings`` table does not exist yet.
    """
    path = Path(path)
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    try:
        present = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
        if present is None:
            return {}
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    finally:
        conn.close()
    return _unflatten([(key, json.loads(value)) for key, value in rows])


def write_sqlite(path: Path, data: dict[str, Any]) -> None:
    """Replace the ``settings`` table contents with the flattened nested dict."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        with conn:  # transaction: commit on success, rollback on error
            conn.execute(_CREATE_TABLE)
            conn.execute("DELETE FROM settings")
            conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in _flatten(data)],
            )
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings/test_sqlite_store.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/settings/sqlite_store.py tests/test_settings/test_sqlite_store.py
git commit -m "Add SQLite config store with flatten/unflatten round-trip"
```

---

## Task 2: Format resolution + SQLite dispatch in parsers

**Files:**
- Modify: `src/konfig/settings/parsers.py`
- Test: `tests/test_settings/test_parsers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings/test_parsers.py`:

```python
from konfig.settings.parsers import resolve_format


class TestResolveFormat:
    def test_override_wins(self, tmp_path: Path) -> None:
        assert resolve_format(tmp_path / "config.yaml", "sqlite") == "sqlite"

    def test_override_case_insensitive(self) -> None:
        assert resolve_format(None, "SQLite") == "sqlite"

    def test_override_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="KONFIG_CONFIG_FORMAT"):
            resolve_format(None, "xml")

    def test_extension_detection(self, tmp_path: Path) -> None:
        assert resolve_format(tmp_path / "c.yaml", None) == "yaml"
        assert resolve_format(tmp_path / "c.yml", None) == "yaml"
        assert resolve_format(tmp_path / "c.json", None) == "json"
        assert resolve_format(tmp_path / "c.toml", None) == "toml"
        assert resolve_format(tmp_path / "c.sqlite", None) == "sqlite"
        assert resolve_format(tmp_path / "c.db", None) == "sqlite"
        assert resolve_format(tmp_path / "c.sqlite3", None) == "sqlite"

    def test_default_yaml_when_unknown(self, tmp_path: Path) -> None:
        assert resolve_format(tmp_path / "c.conf", None) == "yaml"
        assert resolve_format(None, None) == "yaml"


class TestSqliteViaParseFile:
    def test_write_and_parse_sqlite_with_fmt(self, tmp_path: Path) -> None:
        f = tmp_path / "store.bin"  # extension intentionally not sqlite-ish
        write_file(f, {"database": {"host": "localhost"}}, fmt="sqlite")
        assert parse_file(f, fmt="sqlite") == {"database": {"host": "localhost"}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings/test_parsers.py::TestResolveFormat -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_format'`

- [ ] **Step 3: Write the implementation**

In `src/konfig/settings/parsers.py`, first change the existing import line `from typing import Any` to:

```python
from typing import Any, Optional
```

Then add near the top (after the imports, before `parse_file`):

```python
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
        fmt = override.strip().lower()
        if fmt not in ALLOWED_FORMAT_OVERRIDES:
            raise ValueError(
                f"Invalid KONFIG_CONFIG_FORMAT {override!r}; "
                f"allowed values: {', '.join(ALLOWED_FORMAT_OVERRIDES)}"
            )
        return fmt
    if path is not None:
        fmt = _format_from_extension(path)
        if fmt is not None:
            return fmt
    return "yaml"
```

Note: `from pathlib import Path` already exists at the top of the file; the `Optional` import is covered by the edit to the existing `from typing import Any` line above.

Now replace the body of `parse_file` so it accepts an explicit `fmt`:

```python
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
```

And replace the body of `write_file`:

```python
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
            raise ValueError(f"Unsupported config file format for writing: {path.suffix}")

    if fmt in ("yaml", "yml"):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings/test_parsers.py -v`
Expected: PASS (all existing parser tests plus the new `TestResolveFormat` and `TestSqliteViaParseFile`).

- [ ] **Step 5: Commit**

```bash
git add src/konfig/settings/parsers.py tests/test_settings/test_parsers.py
git commit -m "Add resolve_format and SQLite dispatch to parsers"
```

---

## Task 3: FileLayer gains an explicit format

**Files:**
- Modify: `src/konfig/settings/layers.py`
- Test: `tests/test_settings/test_layers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings/test_layers.py`:

```python
class TestFileLayerSqlite:
    def test_sqlite_set_get_roundtrip(self, tmp_path: Path) -> None:
        db = tmp_path / "config.sqlite"
        layer = FileLayer(db, fmt="sqlite")
        layer.set("database.host", "localhost")
        assert layer.get("database.host") == "localhost"
        # A fresh layer reads the persisted value back from the DB.
        reloaded = FileLayer(db, fmt="sqlite")
        assert reloaded.get("database.host") == "localhost"

    def test_sqlite_delete_persists(self, tmp_path: Path) -> None:
        db = tmp_path / "config.sqlite"
        layer = FileLayer(db, fmt="sqlite")
        layer.set("a", "1")
        assert layer.delete("a") is True
        reloaded = FileLayer(db, fmt="sqlite")
        assert reloaded.get("a") is _MISSING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings/test_layers.py::TestFileLayerSqlite -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'fmt'`

- [ ] **Step 3: Write the implementation**

In `src/konfig/settings/layers.py`, modify `FileLayer.__init__` to accept and store `fmt`:

```python
    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        graceful: bool = False,
        fmt: Optional[str] = None,
    ) -> None:
        self._path = Path(path) if path else None
        self._data: dict[str, Any] = {}
        self._graceful = graceful
        self._fmt = fmt
        if self._path:
            self.reload()
```

In `FileLayer.reload`, pass the format to `parse_file`:

```python
            if self._path.exists():
                self._data = parse_file(self._path, fmt=self._fmt)
```

In `FileLayer._write`, pass the format to `write_file`:

```python
        try:
            write_file(self._path, self._data, fmt=self._fmt)
        except OSError as exc:
            raise PermissionError(
                f"Cannot write to config file {self._path}: {exc}"
            ) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings/test_layers.py -v`
Expected: PASS (existing layer tests plus `TestFileLayerSqlite`).

- [ ] **Step 5: Commit**

```bash
git add src/konfig/settings/layers.py tests/test_settings/test_layers.py
git commit -m "Add fmt parameter to FileLayer"
```

---

## Task 4: Settings resolves format from env + extension

**Files:**
- Modify: `src/konfig/settings/settings.py`
- Test: `tests/test_settings/test_settings.py`

- [ ] **Step 1: Write the failing tests**

First check the top of `tests/test_settings/test_settings.py` for existing imports. Then append:

```python
class TestConfigFormatSelection:
    def test_sqlite_via_env_var_full_crud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KONFIG_CONFIG_FORMAT", "sqlite")
        db = tmp_path / "config.sqlite"

        settings = Settings(config_file=str(db))
        settings.set("database.host", "localhost", persist="user")
        assert settings.get("database.host") == "localhost"

        # A fresh Settings re-reads the persisted value from the SQLite file.
        reopened = Settings(config_file=str(db))
        assert reopened.get("database.host") == "localhost"

        reopened.delete("database.host", persist="user")
        assert Settings(config_file=str(db)).get("database.host") is None

    def test_env_override_beats_extension(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Path says .yaml, but the env var forces SQLite.
        monkeypatch.setenv("KONFIG_CONFIG_FORMAT", "sqlite")
        path = tmp_path / "config.yaml"
        settings = Settings(config_file=str(path))
        settings.set("key", "value", persist="user")
        # Stored as SQLite: a fresh SQLite read finds it.
        from konfig.settings.sqlite_store import read_sqlite

        assert read_sqlite(path) == {"key": "value"}

    def test_no_env_uses_extension(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KONFIG_CONFIG_FORMAT", raising=False)
        path = tmp_path / "config.json"
        settings = Settings(config_file=str(path))
        settings.set("key", "value", persist="user")
        # Stored as JSON because of the extension.
        import json

        assert json.loads(path.read_text()) == {"key": "value"}

    def test_invalid_format_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KONFIG_CONFIG_FORMAT", "xml")
        with pytest.raises(ValueError, match="KONFIG_CONFIG_FORMAT"):
            Settings(config_file=str(tmp_path / "config.yaml"))
```

Ensure `import pytest` and `from pathlib import Path` and `from konfig.settings.settings import Settings` are present at the top (they are — confirm).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings/test_settings.py::TestConfigFormatSelection -v`
Expected: FAIL — `set(persist="user")` writes YAML (the `.yaml` path) / SQLite not selected, so `test_sqlite_via_env_var_full_crud` and `test_env_override_beats_extension` fail; `test_invalid_format_raises` fails because no validation happens yet.

- [ ] **Step 3: Write the implementation**

In `src/konfig/settings/settings.py`, add `import os` near the top imports, and import `resolve_format`:

```python
import os
```

and extend the existing layers import:

```python
from konfig.settings.parsers import resolve_format
```

(Add this as a new import line below the existing `from konfig.settings.layers import (...)` block.)

Then change `Settings.__init__` so it resolves the format per file and passes it to each `FileLayer`:

```python
    def __init__(
        self,
        config_file: Optional[str | Path] = None,
        system_config_file: Optional[str | Path] = None,
        defaults: Optional[dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
    ) -> None:
        fmt_override = os.environ.get("KONFIG_CONFIG_FORMAT")
        system_path = Path(system_config_file) if system_config_file else None
        user_path = Path(config_file) if config_file else None

        self._defaults_layer = DefaultsLayer(defaults)
        self._system_file_layer = FileLayer(
            system_path,
            graceful=True,
            fmt=resolve_format(system_path, fmt_override),
        )
        self._user_file_layer = FileLayer(
            user_path,
            fmt=resolve_format(user_path, fmt_override),
        )
        self._env_layer = EnvLayer(env_prefix)
        self._runtime_layer = RuntimeLayer()
```

Note: `resolve_format` validates the override, so an invalid `KONFIG_CONFIG_FORMAT` raises `ValueError` here at construction (it is called even when the path is None).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings/test_settings.py -v`
Expected: PASS (existing tests plus `TestConfigFormatSelection`).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: full suite green (no regressions in settings, secrets, logging, or app tests).

- [ ] **Step 6: Commit**

```bash
git add src/konfig/settings/settings.py tests/test_settings/test_settings.py
git commit -m "Resolve config format from KONFIG_CONFIG_FORMAT env and extension"
```

---

## Task 5: Documentation

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: README**

In `README.md`, find the Settings usage area. Add a short subsection (match the file's existing heading depth):

````markdown
### Config file format

The config file format is chosen by the `KONFIG_CONFIG_FORMAT` environment variable
(`yaml`, `json`, or `sqlite`). When unset, the format is detected from the file extension,
defaulting to YAML. Reading, updating, and creating settings work in every format.

```bash
export KONFIG_CONFIG_FORMAT=sqlite   # store settings in a SQLite database file
```

```python
from konfig import Settings

settings = Settings(config_file="config.db")
settings.set("database.host", "localhost", persist="user")  # written to SQLite
host = settings.get("database.host")
```
````

If the README has no Settings section, place this near the other usage content and report where.

- [ ] **Step 2: CLAUDE.md**

In `CLAUDE.md` section `## 1. Settings`, after the "### Config File Formats" subsection, add:

```markdown
### Selecting the Format

The active config format is resolved as: `KONFIG_CONFIG_FORMAT` env var
(`yaml` / `json` / `sqlite`) if set → file extension (`.yaml/.yml`, `.json`, `.toml`,
`.db/.sqlite/.sqlite3`) → default `yaml`. The env var, when set, applies to both the user
and system config files and overrides the extension. SQLite stores settings in a
`settings(key, value)` table keyed by dot-path with JSON-encoded values; reading, updating,
and creating settings work across YAML, JSON, and SQLite. TOML remains read-only.
```

- [ ] **Step 3: CHANGELOG**

In `CHANGELOG.md`, under the existing `## [0.2.0]` `### Added` section, add:

```markdown
- Pluggable config file format: store settings as YAML, JSON, or SQLite, selectable via the
  `KONFIG_CONFIG_FORMAT` environment variable (default YAML, otherwise detected from the file
  extension). Reading, updating, and creating settings work across all three formats.
```

Use Australian English. No AI/Claude/Anthropic references.

- [ ] **Step 4: Verify the suite still passes**

Run: `pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md CHANGELOG.md
git commit -m "Document pluggable config format and KONFIG_CONFIG_FORMAT"
```

Note: `CLAUDE.md` is gitignored in this repo; if `git add` does not stage it, that is expected — commit the README and CHANGELOG, and leave the on-disk CLAUDE.md updated.

---

## Self-Review Notes

- **Spec coverage:** §4.1 resolve_format → Task 2; §4.2 sqlite_store → Task 1; §4.3 wiring (parsers `fmt` → Task 2, FileLayer `fmt` → Task 3, Settings → Task 4); §4.4 behavioural notes → covered by Task 4 tests (env-beats-extension, missing-file-empty via Task 1); §4.5 error handling (invalid override → Task 2/Task 4; TOML write → Task 2; empty-dict non-round-trip → Task 1 `test_flatten_empty_dict_yields_no_rows`); §5 testing → Tasks 1–4; §6 docs → Task 5.
- **Placeholder scan:** none — every code step is complete.
- **Consistency:** `resolve_format(path, override)`, `_format_from_extension`, `read_sqlite`/`write_sqlite`, `_flatten`/`_unflatten`, and the `fmt=` keyword are defined in Tasks 1–2 and reused unchanged in Tasks 3–4. `FileLayer(path, *, graceful=False, fmt=None)` signature matches its use in Settings.
- **No new dependency:** `sqlite3` is stdlib. `_MISSING` is already exported from `layers.py` for the Task 3 test.
