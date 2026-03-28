# API Reference

Complete reference for all public classes and functions in Konfig.

## konfig

Top-level package exports.

```python
from konfig import Settings, Secrets, LogManager, AppContext, __version__
```

---

## konfig.Settings

```python
class Settings(
    config_file: str | Path | None = None,
    system_config_file: str | Path | None = None,
    defaults: dict[str, Any] | None = None,
    env_prefix: str | None = None,
)
```

Unified settings with layered precedence: defaults < system config < user config < env vars < runtime overrides.

### Methods

#### `get(key, default=None, *, cast=None) -> Any`

Get a setting value by dot-notation key. Returns `default` if not found in any layer.

- **key** (str): Dot-notation key, e.g. `"database.host"`
- **default** (Any): Value to return if missing. Default: `None`
- **cast** (callable, optional): Type conversion function, e.g. `int`, `float`

#### `has(key) -> bool`

Check if a key exists in any layer.

#### `set(key, value, *, persist=None) -> None`

Set a value. By default, creates an in-memory runtime override.

- **persist** (`"user"` | `"system"` | `None`): If set, writes to the corresponding config file.
- Raises `PermissionError` if writing to a non-writable file.
- Raises `RuntimeError` if no config file path is configured for the scope.

#### `delete(key, *, persist=None) -> bool`

Delete a value. Returns `True` if found and deleted.

- **persist**: Same as `set()`.

#### `get_section(prefix) -> dict[str, Any]`

Get all keys under a dot-notation prefix, merged across all layers.

```python
settings.get_section("database")
# {"host": "localhost", "port": 5432, "name": "mydb"}
```

#### `reload() -> None`

Reload both system and user config files from disk.

---

## konfig.Secrets

```python
class Secrets(
    service_name: str = "konfig",
    settings: Settings | None = None,
    backend: SecretBackend | None = None,
)
```

Unified secrets API with pluggable backends and automatic backend detection.

### Methods

#### `get(key) -> str | None`

Retrieve a secret by key. Returns `None` if not found.

#### `set(key, value) -> None`

Store a secret.

#### `delete(key) -> None`

Delete a secret by key.

#### `has(key) -> bool`

Check if a secret exists.

#### `list_keys() -> list[str]`

List all stored secret keys.

#### `resolve_uri(value) -> str | None`

Resolve a `secret://` URI to its actual value. Non-secret strings pass through unchanged.

```python
secrets.resolve_uri("secret://api_key")  # Returns the secret value
secrets.resolve_uri("plain_value")       # Returns "plain_value"
```

---

## konfig.LogManager

```python
class LogManager(
    app_name: str = "Application",
    version: str = "0.0.0",
    log_dir: str | Path | None = None,
    level: str = "INFO",
    log_format: str = "text",
    retention_runs: int = 10,
    max_file_size_mb: int = 50,
    max_files_per_run: int = 3,
    console_output: str = "auto",
    app_id: str | None = None,
)
```

Configures Python logging from settings with run-scoped directories. Never writes to stdout.

### Class Methods

#### `LogManager.from_settings(settings, app_name, version, app_id=None) -> LogManager`

Create a LogManager configured from a Settings instance.

### Methods

#### `setup() -> logging.Logger`

Set up logging: create run directory, configure handlers, log startup banner. Returns the root logger.

#### `shutdown() -> None`

Close and remove all handlers added by this manager.

### Properties

#### `run_dir -> Path | None`

Path to the current run's log directory. `None` before `setup()` is called.

---

## konfig.AppContext

```python
class AppContext(
    name: str = "Application",
    version: str = "0.0.0",
    config_file: str | Path | None = None,
    system_config_file: str | Path | None = None,
    defaults: dict[str, Any] | None = None,
    env_prefix: str | None = None,
    service_name: str | None = None,
)
```

Lifecycle context manager. Supports both sync (`with`) and async (`async with`).

### Properties

All raise `RuntimeError` if accessed before entering the context.

#### `settings -> Settings`
#### `secrets -> Secrets`
#### `logger -> logging.Logger`
#### `log_manager -> LogManager`

---

## konfig.secrets.SecretBackend

```python
class SecretBackend(ABC)
```

Abstract interface for secret storage backends.

### Abstract Methods

#### `get(key) -> str | None`
#### `set(key, value) -> None`
#### `delete(key) -> None`
#### `has(key) -> bool`
#### `list_keys() -> list[str]`

---

## konfig.secrets.EncryptedFileBackend

```python
class EncryptedFileBackend(
    file_path: Path | str,
    master_key: str | None = None,
)
```

AES-256 encrypted JSON file backend. Implements `SecretBackend`.

Master key resolution: explicit parameter -> `KONFIG_MASTER_KEY` env var -> auto-generated `.key` file.

---

## konfig.secrets.KeyringBackend

```python
class KeyringBackend(service_name: str)
```

OS keyring backend (macOS Keychain, Windows Credential Locker, Linux Secret Service). Implements `SecretBackend`.

### Static Methods

#### `is_available() -> bool`

Check if a functional keyring backend is available.

---

## konfig.secrets.AWSSecretsManagerBackend

```python
class AWSSecretsManagerBackend(
    region: str,
    prefix: str = "",
)
```

AWS Secrets Manager backend. Requires `boto3` (`pip install konfig[aws]`). Implements `SecretBackend`.

---

## konfig.paths

Platform-aware path utilities.

### Functions

#### `app_id_from(name, env_prefix=None) -> str`

Derive a filesystem-safe app identifier from name or env_prefix.

#### `config_dir(app_id) -> Path`

Platform-conventional user config directory.

#### `system_config_dir(app_id) -> Path`

Platform-conventional system-wide config directory.

#### `data_dir(app_id) -> Path`

Platform-conventional user data directory.

#### `log_dir(app_id) -> Path`

Platform-conventional log directory.

#### `default_config_file(app_id) -> Path | None`

Find an existing config file in the user config directory.

#### `default_system_config_file(app_id) -> Path | None`

Find an existing config file in the system config directory.

#### `default_secrets_file(app_id) -> Path`

Default path for the encrypted secrets file.

---

## konfig.settings.parsers

Config file parsing and writing.

### Functions

#### `parse_file(path) -> dict[str, Any]`

Parse a config file (YAML, TOML, or JSON), auto-detected by extension.

#### `write_file(path, data) -> None`

Write a config dict to file (YAML or JSON). TOML writing is not supported.
