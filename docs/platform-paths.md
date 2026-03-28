# Platform Paths

When no explicit paths are provided, Konfig uses platform-conventional directories for config files, secrets, and logs. These follow OS conventions that users and administrators expect.

## Directory Locations

### macOS

| Purpose | Path |
|---------|------|
| User config | `~/Library/Application Support/<app_id>/` |
| System config | `/Library/Application Support/<app_id>/` |
| User data (secrets) | `~/Library/Application Support/<app_id>/` |
| Logs | `~/Library/Logs/<app_id>/` |

### Linux

| Purpose | Path | Env Override |
|---------|------|-------------|
| User config | `~/.config/<app_id>/` | `$XDG_CONFIG_HOME` |
| System config | `/etc/<app_id>/` | — |
| User data (secrets) | `~/.local/share/<app_id>/` | `$XDG_DATA_HOME` |
| Logs | `~/.local/state/<app_id>/logs/` | `$XDG_STATE_HOME` |

Linux paths follow the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/). If the XDG environment variables are set, they are respected.

### Windows

| Purpose | Path |
|---------|------|
| User config | `%APPDATA%\<app_id>\` |
| System config | `%PROGRAMDATA%\<app_id>\` |
| User data (secrets) | `%APPDATA%\<app_id>\` |
| Logs | `%LOCALAPPDATA%\<app_id>\logs\` |

## App Identifier

The `<app_id>` in the paths above is derived from your application's identity:

```python
from konfig.paths import app_id_from

# If env_prefix is set, it's lowercased
app_id_from("My App", env_prefix="MYAPP")  # "myapp"

# Otherwise, name is sanitised to a filesystem-safe slug
app_id_from("My Application")       # "my_application"
app_id_from("My App! (v2.0)")       # "my_app_v2_0"
```

This means:
- `AppContext(name="My App", env_prefix="MYAPP")` uses `myapp/` directories
- `AppContext(name="My Application")` uses `my_application/` directories

## Config File Discovery

When no `config_file` is specified, Konfig searches the config directory for files in this order:

1. `config.yaml`
2. `config.yml`
3. `config.toml`
4. `config.json`

The first match is used. If none exist, Settings initialises without a file layer.

The same search is performed for system config files in the system config directory.

## Graceful Handling

- **Missing directories**: If the config directory doesn't exist, no error — Settings works without file config.
- **Unreadable system config**: If the system config exists but the user lacks read permission, it is silently skipped with a debug log message.
- **Unwritable system config**: Writing to system config (`persist="system"`) when lacking permissions raises `PermissionError` for the application to handle.

## Using the Paths API Directly

The `konfig.paths` module exposes all path functions for direct use:

```python
from konfig.paths import (
    app_id_from,
    config_dir,
    system_config_dir,
    data_dir,
    log_dir,
    default_config_file,
    default_system_config_file,
    default_secrets_file,
)

app_id = app_id_from("My App", env_prefix="MYAPP")

print(config_dir(app_id))          # User config directory
print(system_config_dir(app_id))   # System config directory
print(data_dir(app_id))            # Data directory (secrets)
print(log_dir(app_id))             # Log directory
print(default_secrets_file(app_id)) # Default secrets file path
```

## Overriding Defaults

All default paths can be overridden via settings or constructor parameters:

```yaml
# In config.yaml
secrets:
  file_path: /custom/path/secrets.enc
logging:
  log_dir: /var/log/myapp
```

```python
# Or via constructor parameters
Settings(config_file="/custom/config.yaml")
LogManager(log_dir="/var/log/myapp")
Secrets(service_name="myapp")  # Uses default_secrets_file("myapp")
```

Explicit paths always take precedence over platform defaults.
