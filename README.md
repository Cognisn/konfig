# Konfig

Settings management, pluggable secrets, and run-scoped logging for Python applications.

Konfig provides three foundational capabilities every Python application needs, with an optional lightweight app lifecycle context manager that ties them together. It is a clean-sheet replacement for `dtPyAppFramework`.

## Features

- **Layered settings** with system/user/env/runtime precedence and persistent writes
- **Pluggable secrets** with OS keyring, AES-encrypted file, and AWS Secrets Manager backends
- **Run-scoped logging** with historical retention, structured JSON mode, and stdio-safe output
- **Platform-aware defaults** for config, data, and log directories (macOS, Linux, Windows)
- **Optional app lifecycle** via a sync/async context manager — no inheritance required
- Python 3.10+

## Installation

```bash
pip install konfig
```

For AWS Secrets Manager support:

```bash
pip install konfig[aws]
```

## Quick Start

```python
from konfig import AppContext

with AppContext(
    name="My Application",
    version="1.0.0",
    config_file="config.yaml",
    env_prefix="MYAPP",
) as ctx:
    host = ctx.settings.get("database.host", "localhost")
    api_key = ctx.secrets.get("api_key")
    ctx.logger.info("Starting with host=%s", host)
```

For async applications:

```python
async with AppContext(name="My Server", version="2.0.0") as ctx:
    await run_server(ctx.settings)
```

Each subsystem (Settings, Secrets, LogManager) can also be used independently. See the full documentation in the [`docs/`](docs/) directory:

- [Settings Guide](docs/settings.md)
- [Secrets Guide](docs/secrets.md)
- [Logging Guide](docs/logging.md)
- [AppContext Guide](docs/app-context.md)
- [Platform Paths](docs/platform-paths.md)
- [Configuration Reference](docs/configuration-reference.md)
- [API Reference](docs/api-reference.md)

## Samples

Working examples are provided in the [`samples/`](samples/) directory:

| File | Description |
|------|-------------|
| [`basic_settings.py`](samples/basic_settings.py) | Config files, defaults, env vars, overrides |
| [`secrets_usage.py`](samples/secrets_usage.py) | Store, retrieve, and delete secrets |
| [`logging_demo.py`](samples/logging_demo.py) | Run-scoped logging with retention |
| [`app_context.py`](samples/app_context.py) | Full lifecycle with all subsystems |
| [`async_app.py`](samples/async_app.py) | Async context manager usage |
| [`custom_backend.py`](samples/custom_backend.py) | Implementing a custom SecretBackend |

## Development

```bash
pip install -e ".[dev]"
pytest
pytest --cov=konfig
mypy src/konfig
black src/ tests/
isort src/ tests/
```

## License

MIT License. See [LICENSE](LICENSE) for details.
