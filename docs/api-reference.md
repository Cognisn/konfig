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

#### `refresh() -> None`

Make the next read see the active backend's current data by delegating to the backend's
`refresh()`. For the encrypted file backend this reloads the file under a shared lock, which
also forces NFS clients (including Amazon EFS) to revalidate; for the AWS bundle backend it
drops the TTL cache. A no-op for backends that do not cache.

#### `resolve_uri(value) -> str | None`

Resolve a `secret://` URI to its actual value. Non-secret strings pass through unchanged.

```python
secrets.resolve_uri("secret://api_key")  # Returns the secret value
secrets.resolve_uri("plain_value")       # Returns "plain_value"
```

### Properties

#### `backend -> SecretBackend`

The active backend instance.

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

#### `start_central_logging(settings, secrets=None, *, environ=None) -> bool`

Start [centralised log forwarding](logging.md#centralised-log-forwarding) in the role selected by
`logging.central.*` or the `KONFIG_LOG_*` environment variables. Call after `setup()`; `AppContext`
does this automatically. Returns `True` when this instance is now forwarding or collecting, and
`False` when the feature is off, misconfigured or failed to start. Never raises: failures are
logged locally and the application carries on. Calling it again while running is a no-op.

- **settings** (`Settings`): the application's settings.
- **secrets** (`Secrets`, optional): used to publish (collector) or discover (sender) the collector
  entry, and to resolve a `secret://` token.
- **environ** (mapping, optional): environment to read instead of `os.environ`.

#### `stop_central_logging() -> None`

Stop forwarding or collecting. A sender drains its queue for up to `logging.central.flush_timeout`
seconds and logs how many records were left unsent. A no-op when not running.

#### `shutdown() -> None`

Stop centralised log forwarding if it is running, then close and remove all handlers added by this
manager.

### Properties

#### `run_dir -> Path | None`

Path to the current run's log directory. `None` before `setup()` is called.

#### `log_dir -> Path`

Base directory holding the run-scoped log directories.

#### `app_id -> str`, `app_name -> str`, `version -> str`

Application details used for default paths and the startup banner.

#### `handlers -> tuple[logging.Handler, ...]`

The handlers this manager attached to the root logger.

#### `central -> CentralLogging | None`

The running centralised logging role, if any.

---

## konfig.logging.central

```python
from konfig.logging.central import (
    CentralLogConfig, CentralLogging, resolve_config,
    start_central_logging, stop_central_logging,
)
```

#### `resolve_config(settings=None, environ=None) -> CentralLogConfig`

Resolve `logging.central.*` settings and `KONFIG_LOG_*` environment variables into a frozen
`CentralLogConfig`. Environment variables win. A partial endpoint/fingerprint/token override is
reported in `override_error` rather than mixed with other sources.

#### `start_central_logging(log_manager, settings, secrets=None, *, environ=None) -> CentralLogging | None`

The function behind `LogManager.start_central_logging`. Returns a handle, or `None` when the feature
is off or could not start. Never raises.

#### `stop_central_logging(handle) -> None`

Stop a handle (`None` is ignored).

#### `CentralLogging`

- `role -> str`: `"collector"` or `"sender"`.
- `config -> CentralLogConfig`
- `stop() -> None`: stop the role, restoring any logging levels and formatters it changed. Safe
  to call more than once.

#### `CentralLogConfig`

A frozen dataclass with one field per `logging.central.*` setting (see the
[Configuration Reference](configuration-reference.md#centralised-log-forwarding)), plus
`override_source`, `override_error` and the properties `active` and `has_override`. `token` is
left out of its `repr`.

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

### Methods

#### `refresh() -> None`

Discard any cached state so the next read sees the store's current data. Concrete and a
no-op by default, so existing backends need no change; override it in backends that cache.

---

## konfig.secrets.EncryptedFileBackend

```python
class EncryptedFileBackend(
    file_path: Path | str,
    master_key: str | None = None,
    lock_timeout: float = 30.0,
)
```

AES-256 encrypted JSON file backend. Implements `SecretBackend`. Safe to share between
processes and containers; see [Sharing an encrypted file](secrets.md#sharing-an-encrypted-file-between-processes-and-containers).

Master key resolution: explicit parameter -> `KONFIG_MASTER_KEY` env var -> existing `.key`
file -> auto-generated `.key` file (only when the secrets file does not exist yet; otherwise
`MasterKeyMissingError`).

- `lock_timeout`: seconds to wait for the `<file_path>.lock` lock before raising `TimeoutError`.
  Set from `secrets.file_lock_timeout` when created by `Secrets`.
- `refresh()`: unconditionally reload the file under a shared lock.

Errors (from `konfig.secrets`, all subclasses of `EncryptedFileError`):

| Error | Raised when |
|-------|-------------|
| `MasterKeyMissingError` | No master key is available for an existing, non-empty secrets file |
| `MasterKeyMismatchError` | The master key does not match the file (also an `InvalidToken`) |
| `SecretsFileCorruptError` | The file is damaged, truncated or an unknown format version (also an `InvalidToken`) |

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
