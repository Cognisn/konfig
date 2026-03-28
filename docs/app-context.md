# AppContext

`AppContext` is an optional lightweight lifecycle context manager that wires together Settings, Secrets, and Logging. It handles setup, startup banner, and teardown.

**You don't have to use it.** Each subsystem (Settings, Secrets, LogManager) works independently. AppContext is a convenience for applications that want all three.

## Sync Usage

```python
from konfig import AppContext

with AppContext(
    name="My Application",
    version="1.0.0",
    config_file="config.yaml",
    env_prefix="MYAPP",
) as ctx:
    # All three subsystems are initialised
    host = ctx.settings.get("database.host")
    api_key = ctx.secrets.get("api_key")
    ctx.logger.info("Starting with host=%s", host)

    # Your application logic here
    run_server(host, api_key)

# On exit: log handlers flushed, handlers closed
```

## Async Usage

```python
import asyncio
from konfig import AppContext

async def main():
    async with AppContext(
        name="Async Server",
        version="2.0.0",
        env_prefix="MYSERVER",
    ) as ctx:
        host = ctx.settings.get("server.host", "0.0.0.0")
        port = ctx.settings.get("server.port", 8080, cast=int)
        ctx.logger.info("Starting on %s:%d", host, port)
        await serve(host, port)

asyncio.run(main())
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | "Application" | Application name (used in startup banner and as fallback app identifier) |
| `version` | str | "0.0.0" | Application version (shown in startup banner) |
| `config_file` | str/Path | Auto-discovered | Path to user-level config file. If not provided, Konfig searches the [platform config directory](platform-paths.md) |
| `system_config_file` | str/Path | Auto-discovered | Path to system-level config file. If not provided, Konfig searches the platform system config directory |
| `defaults` | dict | None | Default settings values |
| `env_prefix` | str | None | Prefix for environment variable mapping. Also used as the app identifier for default paths |
| `service_name` | str | Derived from name/prefix | Namespace for secrets storage |

## App Identifier

The app identifier determines directory names for config, data, and log paths. It is derived as follows:

- If `env_prefix` is set: lowercased prefix (e.g. `MYAPP` -> `myapp`)
- Otherwise: sanitised `name` (e.g. `"My Application"` -> `"my_application"`)

This means setting `env_prefix="MYAPP"` will look for configs in `myapp/` subdirectories, while omitting it with `name="My Application"` will use `my_application/`.

## What AppContext Does

On entry (`__enter__` / `__aenter__`):

1. **Settings** — loads defaults, system config, user config, env vars
2. **Secrets** — auto-detects backend (keyring -> encrypted file) based on settings
3. **LogManager** — creates run directory, configures handlers, logs startup banner

On exit (`__exit__` / `__aexit__`):

4. **LogManager** — flushes logs, closes file handlers

## Accessing Subsystems

```python
with AppContext(name="MyApp") as ctx:
    ctx.settings      # Settings instance
    ctx.secrets       # Secrets instance
    ctx.logger        # Root logging.Logger
    ctx.log_manager   # LogManager instance (for run_dir, etc.)
```

Accessing any property before entering the context raises `RuntimeError`:

```python
ctx = AppContext(name="MyApp")
ctx.settings  # RuntimeError: AppContext is not initialised
```

## Auto-Discovery

When `config_file` or `system_config_file` are not specified, AppContext searches platform-conventional directories for config files (in order: `config.yaml`, `config.yml`, `config.toml`, `config.json`). See [Platform Paths](platform-paths.md) for details.

If no config file is found, Settings initialises with only defaults and environment variables — this is perfectly valid.

## Composition, Not Inheritance

Unlike `dtPyAppFramework`'s `AbstractApp` pattern, Konfig uses composition:

```python
# OLD (dtPyAppFramework) - DON'T DO THIS
class MyApp(AbstractApp):
    def main(self, args):
        ...

# NEW (Konfig) - DO THIS
with AppContext(name="MyApp") as ctx:
    main(ctx)
```

There is no base class to inherit from. AppContext is a tool, not a framework.
