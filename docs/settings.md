# Settings

Konfig's `Settings` class provides layered configuration with a CRUD API, dot-notation keys, and persistent writes to config files.

## Layered Precedence

Settings are resolved from five layers, highest precedence first:

| Priority | Layer | Source | Writable |
|----------|-------|--------|----------|
| 5 (highest) | Runtime | `settings.set()` | In-memory only |
| 4 | Environment | `MYAPP__DATABASE__HOST` | No |
| 3 | User config file | `~/.config/myapp/config.yaml` | Yes (`persist="user"`) |
| 2 | System config file | `/etc/myapp/config.yaml` | Yes (`persist="system"`) |
| 1 (lowest) | Defaults | Hardcoded dict | No |

When you call `settings.get("database.host")`, Konfig checks each layer from highest to lowest and returns the first match.

## Basic Usage

```python
from konfig import Settings

settings = Settings(
    config_file="config.yaml",
    defaults={"database": {"host": "localhost", "port": 5432}},
    env_prefix="MYAPP",
)

# Read with dot notation
host = settings.get("database.host")
port = settings.get("database.port", cast=int)

# Default value when missing
timeout = settings.get("database.timeout", 30)

# Check existence
if settings.has("database.host"):
    ...

# Get all keys under a prefix
db_config = settings.get_section("database")
# Returns: {"host": "localhost", "port": 5432}
```

## System and User Config Files

Settings supports two config file layers for shared (system-wide) and personal (user-level) configuration:

```python
settings = Settings(
    system_config_file="/etc/myapp/config.yaml",
    config_file="~/.config/myapp/config.yaml",
    defaults={"server": {"workers": 4}},
)
```

If you don't specify paths, Konfig auto-discovers config files from [platform-conventional directories](platform-paths.md).

The system config is read **gracefully** - if the file doesn't exist or the user lacks read permission, it is silently skipped. The application never crashes due to an unreadable system config.

## Writing Settings

By default, `set()` creates a runtime override (in-memory, highest precedence):

```python
settings.set("database.host", "override-host")
```

To persist a setting to a config file, use the `persist` parameter:

```python
# Write to user config file
settings.set("database.host", "my-host", persist="user")

# Write to system config file (requires write permission)
settings.set("database.host", "shared-host", persist="system")

# Delete from a config file
settings.delete("database.host", persist="user")
```

If the process doesn't have permission to write to the system config, a `PermissionError` is raised. Your application should catch this and handle it appropriately:

```python
try:
    settings.set("key", "value", persist="system")
except PermissionError:
    print("Cannot write system config. Try with elevated privileges.")
    settings.set("key", "value", persist="user")  # Fall back to user config
```

If no config file path is configured for the requested scope, a `RuntimeError` is raised.

Persistent writes support YAML (`.yaml`, `.yml`) and JSON (`.json`) formats. TOML is read-only due to the lack of a stdlib writer in Python < 3.11.

## Config File Formats

All three formats are supported for reading. The format is auto-detected from the file extension.

**YAML** (`config.yaml` or `config.yml`):
```yaml
database:
  host: localhost
  port: 5432
logging:
  level: INFO
  retention_runs: 5
```

**TOML** (`config.toml`):
```toml
[database]
host = "localhost"
port = 5432

[logging]
level = "INFO"
retention_runs = 5
```

**JSON** (`config.json`):
```json
{
  "database": {"host": "localhost", "port": 5432},
  "logging": {"level": "INFO", "retention_runs": 5}
}
```

## Environment Variable Mapping

Nested keys are mapped to environment variables using `__` (double underscore) as the separator. An optional prefix scopes which variables are considered.

```python
settings = Settings(env_prefix="MYAPP")
```

| Setting Key | Env Var (prefix=MYAPP) | Env Var (no prefix) |
|-------------|----------------------|---------------------|
| `database.host` | `MYAPP__DATABASE__HOST` | `DATABASE__HOST` |
| `logging.level` | `MYAPP__LOGGING__LEVEL` | `LOGGING__LEVEL` |
| `server.read_only` | `MYAPP__SERVER__READ_ONLY` | `SERVER__READ_ONLY` |

Environment variable values are always strings. Use `cast=` to convert:

```python
port = settings.get("database.port", cast=int)
debug = settings.get("server.debug", cast=lambda v: v.lower() in ("true", "1", "yes"))
```

## Reloading

To pick up changes made to config files on disk:

```python
settings.reload()  # Reloads both system and user config files
```

## Type Casting

The `cast` parameter accepts any callable:

```python
settings.get("port", cast=int)
settings.get("ratio", cast=float)
settings.get("debug", cast=bool)
settings.get("tags", cast=lambda v: v.split(","))
```
