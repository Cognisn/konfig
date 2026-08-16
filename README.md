# Konfig

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=bugs)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=ncloc)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=Cognisn_konfig&metric=duplicated_lines_density)](https://sonarcloud.io/summary/new_code?id=Cognisn_konfig)

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

## Secrets

### AWS Secrets Manager (designated secret)

Point konfig at a single AWS secret that holds a JSON bundle of your secrets (the secret must
already exist):

```bash
export KONFIG_AWS_SECRETS_MANAGER=arn:aws:secretsmanager:eu-west-1:123456789012:secret:myapp/secrets-AbCdEf
```

```python
from konfig import Secrets

secrets = Secrets()               # env var selects the AWS bundle backend
api_key = secrets.get("api_key")
secrets.set("api_key", "sk-new")  # read-modify-write back to the bundle
```

Requires `pip install konfig[aws]`.

### AWS Secrets Manager settings document (`KONFIG_AWS_SETTINGS`)

Deliver an application's entire configuration as one JSON document held in a
single Secrets Manager secret — no config file or per-setting environment
variables needed in the task definition:

```bash
export KONFIG_AWS_SETTINGS=arn:aws:secretsmanager:eu-west-1:123456789012:secret:myapp/settings-AbCdEf
```

The secret's `SecretString` must be a JSON object holding the same nested
settings tree a config file would. A plain secret name is also accepted; the
region then comes from the default AWS provider chain (with an ARN it is
taken from the ARN). An equivalent constructor argument exists for
programmatic use — `Settings(aws_settings=...)` — with the environment
variable winning when both are set. Requires `pip install konfig[aws]`.

Precedence (highest to lowest):
`runtime -> env vars -> AWS settings -> user file -> system file -> defaults`
— environment variables remain the operator's immediate per-container
override, while the AWS document overrides anything baked into the image.

Behaviour:

- **Read-only.** `settings.set(...)` keeps writing to the runtime layer or
  config files exactly as before.
- **Fail fast.** A missing/unreadable secret, non-JSON payload, or
  non-object top level raises at startup rather than silently degrading to
  defaults. Error messages name the secret, never its payload.
- **Fetched once.** The document is read at construction and only re-fetched
  by `settings.reload()`; there is no background polling.
- **Composes with secrets.** Values in the document may be `secret://` URIs,
  resolved as usual by the active secrets backend.

This is independent of `KONFIG_AWS_SECRETS_MANAGER`. Pointing both at the
same secret works, but keeping configuration and secret material in separate
Secrets Manager entries is recommended so IAM can distinguish "may read
config" from "may read credentials".

### First boot on AWS: seeded stores

When konfig starts against **empty** stores (an empty or whitespace-only
`SecretString`, or a bare `{}`), it writes a template for the operator instead
of leaving them to transcribe documentation:

- The `KONFIG_AWS_SETTINGS` settings secret is seeded with the application's
  defaults tree as pretty-printed JSON. Startup continues with reads resolving
  exactly as if the layer were absent.
- The `KONFIG_AWS_SECRETS_MANAGER` bundle secret is seeded with a `"CHANGEME"`
  placeholder for every `secret://<name>` reference in the effective settings.
  Resolving an unpopulated placeholder logs a warning naming the key.
  `AppContext` runs this automatically at startup; when composing `Settings`
  and `Secrets` yourself, call `secrets.seed_from(settings)`.

The intended first-boot flow: create the two (empty) secrets, grant
`secretsmanager:PutSecretValue` on them for first boot, start once, edit the
seeded documents, restart — and optionally drop the write grant again.

Seeding never touches a non-empty store (malformed payloads keep failing
fast, and partial documents are never merged into), never creates secrets,
and a failed seed write (for example `AccessDenied` under a read-only role)
only logs a warning. Concurrent replicas racing the first boot are benign:
every writer writes identical content. Operators who want no write attempt at
all can disable seeding outright with `KONFIG_AWS_SEED=false`.

### Running the LocalStack integration tests

The AWS integrations have opt-in integration tests that run against a local
[LocalStack](https://www.localstack.cloud/) container (no AWS account needed). They
auto-skip when LocalStack is not running, so they never affect the normal test run.

```bash
docker compose up -d         # start LocalStack
pip install -e ".[dev,aws]"  # boto3 + dev tools
pytest -m localstack         # run only the integration test
docker compose down          # stop LocalStack
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

### Config file format

The config file format is chosen by the `KONFIG_CONFIG_FORMAT` environment variable
(`yaml`, `json`, or `sqlite`). When unset, the format is detected from the file extension,
defaulting to YAML. Reading, updating, and creating settings work in every format.
(TOML config files are still supported by extension detection, but are read-only and
cannot be selected via `KONFIG_CONFIG_FORMAT`.)

```bash
export KONFIG_CONFIG_FORMAT=sqlite   # store settings in a SQLite database file
```

```python
from konfig import Settings

settings = Settings(config_file="config.db")
settings.set("database.host", "localhost", persist="user")  # written to SQLite
settings.set("debug", True)                                  # omit persist: in-memory only
host = settings.get("database.host")
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
