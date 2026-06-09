# Pluggable Config Format (YAML / JSON / SQLite) with Env Override

**Status:** Approved
**Date:** 2026-06-09
**Target version:** v0.2.0 (new backwards-compatible functionality)
**Branch:** `feat/config-format-sqlite` off `release/v0.2.0`
**Author:** Matthew Westwood-Hill

---

## 1. Summary

Allow konfig's config file to be stored as YAML, JSON, or **SQLite**, with the format
selectable by the `KONFIG_CONFIG_FORMAT` environment variable (default YAML). Reading,
updating, and creating settings work across all three formats.

YAML and JSON read/write already work today via `parsers.parse_file`/`write_file` and
`FileLayer`'s persistence (`Settings.set(..., persist="user")`). This feature adds
**SQLite as a third backing store** and an **env-var format override** layered on top of
the existing extension detection.

---

## 2. Motivation

Different deployments prefer different config substrates: human-edited YAML/JSON for most
apps, and a structured single-file database (SQLite) where atomic, queryable, lock-friendly
local storage is desirable. Letting an operator pick the format with one environment
variable — without changing code or file layout — fits konfig's "cross-deployment" goal,
mirroring the env-var-driven approach already used for the AWS secrets bundle.

---

## 3. Design decisions (confirmed)

| Decision | Choice |
|----------|--------|
| Format selection precedence | `KONFIG_CONFIG_FORMAT` env (yaml/json/sqlite) wins; else file-extension detection; else default YAML. Backwards-compatible. |
| SQLite schema | One table `settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)`; `key` is the dot-path, `value` is JSON-encoded. Round-trips to/from the nested dict the other layers use. |
| Treatment of SQLite | Another (de)serialisation format behind the existing `parse_file`/`write_file`; `FileLayer` is otherwise unchanged. |
| Env var name | `KONFIG_CONFIG_FORMAT` (case-insensitive; applies to both user and system config files). |
| TOML | Unchanged — read-only, reachable only via the `.toml` extension; not part of the env override set. |
| Dependency | `sqlite3` (stdlib) — no new dependency. |

---

## 4. Architecture

### 4.1 Format resolution

A new helper resolves the active format for a given config file:

```python
ALLOWED_OVERRIDES = ("yaml", "json", "sqlite")  # values valid for KONFIG_CONFIG_FORMAT

def resolve_format(path: Path | None, override: str | None) -> str:
    # 1. explicit override (from env), validated against ALLOWED_OVERRIDES
    # 2. extension detection: .yaml/.yml->yaml, .json->json, .toml->toml,
    #    .db/.sqlite/.sqlite3->sqlite
    # 3. default "yaml"
```

- `override` is the raw `KONFIG_CONFIG_FORMAT` value (case-insensitive); an unrecognised
  value raises `ValueError` naming the allowed values (`yaml`, `json`, `sqlite`).
- Returned format is one of `"yaml" | "json" | "toml" | "sqlite"`.
- `Settings.__init__` reads `os.environ.get("KONFIG_CONFIG_FORMAT")` once and calls
  `resolve_format` for each config file (user + system), passing the resolved format to
  the corresponding `FileLayer`. The env var, when set, therefore governs **both** files.

### 4.2 SQLite store — `src/konfig/settings/sqlite_store.py` (new)

Keeps SQLite logic isolated from the text-format `parsers.py`.

Schema (created on first write if absent):

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL          -- JSON-encoded leaf value
);
```

Functions:

```python
def read_sqlite(path: Path) -> dict[str, Any]:
    """Read all rows and unflatten dot-keys into a nested dict.
    Returns {} if the table/file does not exist yet."""

def write_sqlite(path: Path, data: dict[str, Any]) -> None:
    """Flatten the nested dict to (dotkey, json-value) leaf rows and replace
    the table contents in one transaction (CREATE IF NOT EXISTS; DELETE; INSERT)."""
```

Flatten/unflatten helpers:

- `_flatten(data)` → list of `(dotkey, value)` for every leaf, where a **leaf** is any
  non-dict value (scalars and lists). Lists are stored whole as JSON.
- `_unflatten(rows)` → nested dict, splitting each `dotkey` on `.` and `json.loads`-ing the
  value.

Round-trip contract: `read_sqlite(write_sqlite(d)) == d` for any nested dict whose only
non-leaf nodes are non-empty dicts and whose keys contain no `.` (the same dot-notation
assumption the rest of the settings system already relies on).

### 4.3 Wiring into existing code

**`src/konfig/settings/parsers.py`:**
- `parse_file(path, fmt: str | None = None)` — when `fmt` is given, dispatch on it; else
  existing extension dispatch. Add a `sqlite` branch delegating to
  `sqlite_store.read_sqlite`.
- `write_file(path, data, fmt: str | None = None)` — same; `sqlite` branch delegates to
  `sqlite_store.write_sqlite`. (TOML write remains unsupported with its current error.)
- Add the `resolve_format` helper here (it is format/parsing concern).

**`src/konfig/settings/layers.py` (`FileLayer`):**
- Add a `fmt: str | None = None` constructor parameter stored on the instance.
- `reload()` calls `parse_file(self._path, fmt=self._fmt)`.
- `_write()` calls `write_file(self._path, self._data, fmt=self._fmt)`.
- No other behaviour changes; `set`/`delete`/`get`/`get_section` untouched.

**`src/konfig/settings/settings.py` (`Settings.__init__`):**
- Read `override = os.environ.get("KONFIG_CONFIG_FORMAT")`.
- `system_fmt = resolve_format(system_path, override)`; `user_fmt = resolve_format(user_path, override)`.
- Pass `fmt=` to each `FileLayer`. All other methods unchanged — `set(..., persist=...)`,
  `delete(..., persist=...)`, `get`, `reload`, etc. work across formats automatically.

### 4.4 Behavioural notes

- With `KONFIG_CONFIG_FORMAT=sqlite`, a `config_file` path is treated as a SQLite database
  regardless of its extension (env override wins). Operators are responsible for supplying a
  sensible path; this is documented.
- A freshly-referenced SQLite file that does not yet exist reads as an empty config (`{}`),
  matching how a missing YAML/JSON file behaves today. The file/table is created on the
  first persisted `set`.
- The env var governs both user and system config layers identically.

### 4.5 Error handling

| Condition | Behaviour |
|-----------|-----------|
| Invalid `KONFIG_CONFIG_FORMAT` value | `ValueError` at `Settings` construction, naming allowed values (`yaml`, `json`, `sqlite`). |
| Corrupt / non-database SQLite file (user layer) | `sqlite3.DatabaseError` propagates (consistent with a malformed YAML/JSON raising on the non-graceful user layer). |
| Same, system layer | Swallowed by the existing `graceful=True` read path (treated as empty), as today. |
| TOML + write | Unchanged: still raises the existing "writing TOML not supported" error. The env override cannot select TOML. |
| Value that is an empty dict | Produces no SQLite leaf row, so it does not round-trip. Documented limitation; acceptable for config. |

---

## 5. Testing

New `tests/test_settings/test_sqlite_store.py`:
- `_flatten`/`_unflatten` correctness, including nested dicts, lists, ints, bools, strings, None.
- `write_sqlite` then `read_sqlite` round-trip equality.
- `read_sqlite` on a non-existent file/table returns `{}`.
- `write_sqlite` replaces (does not append to) prior contents.
- Table is created when absent.

New tests in `tests/test_settings/test_parsers.py`:
- `resolve_format`: env override wins; extension detection for each extension; default YAML
  when neither resolves; invalid override raises `ValueError`; case-insensitivity.
- `parse_file`/`write_file` with `fmt="sqlite"`.

New tests in `tests/test_settings/test_layers.py`:
- `FileLayer(path, fmt="sqlite")` read/set/delete persistence round-trip.

New tests in `tests/test_settings/test_settings.py`:
- `KONFIG_CONFIG_FORMAT=sqlite` selects SQLite: `set(..., persist="user")` then `get` then
  `delete` persists to the DB; a fresh `Settings` re-reads the persisted value.
- Env override beats a conflicting extension (e.g. a `.yaml` path read/written as SQLite).
- Unset env var falls back to extension detection (existing behaviour preserved).
- Invalid `KONFIG_CONFIG_FORMAT` raises `ValueError`.
- Tests that set the env var clear it via `monkeypatch` so they never leak.

All existing settings tests must remain green.

---

## 6. Documentation

- `README.md`: a short note under the Settings section that the config format can be set
  with `KONFIG_CONFIG_FORMAT=yaml|json|sqlite` (default YAML), with a one-line SQLite example.
- `CLAUDE.md` §1 (Settings): document the env override and SQLite format alongside the
  existing format table.
- `CHANGELOG.md`: an entry under the existing undated `## [0.2.0]` `### Added` section
  (no AI-authorship references).

---

## 7. Out of scope

- Per-key live SQL access / concurrent multi-writer SQLite semantics (whole-file
  replace-on-write is sufficient for config).
- Making TOML writable, or adding TOML to the env override set.
- Encrypting the SQLite config file (secrets remain the `Secrets` subsystem's job).
- Migrating data between formats automatically.
- Any change to the secrets, logging, or app-lifecycle subsystems.
