# Tests

Index of the tests in this folder. Keep it current as tests are added, changed, or removed.

| Test | Covers |
| --- | --- |
| `test_app.py` | `AppContext` lifecycle: sync and async context-manager usage, wiring of Settings/Secrets/LogManager, default path discovery, teardown; first-boot seeding of empty AWS stores via `secrets.seed_from(settings)`. |
| `test_paths.py` | Platform-conventional path helpers: default config, secrets, and log locations across macOS/Linux/Windows conventions; app id derivation. |
| `test_settings/test_parsers.py` | Config file parsing and writing for YAML, TOML, JSON; format detection and `resolve_format`. |
| `test_settings/test_layers.py` | Individual settings layers: defaults, file (graceful and strict), env-var mapping, runtime overrides; nested dot-notation helpers. |
| `test_settings/test_settings.py` | Layered `Settings` facade: precedence merge, CRUD with `persist` scopes, `get_section`, casting, reload, `to_dict()`; `Settings.to_dict()` in seeding. |
| `test_settings/test_sqlite_store.py` | SQLite settings store: `settings(key, value)` schema, JSON-encoded values, read/update/create parity with YAML/JSON. |
| `test_settings/test_aws_layer.py` | `AwsSettingsLayer` (stubbed client): inert-when-unconfigured, fetch/cache/reload, fail-fast error taxonomy, region selection, boto3 optionality; plus `Settings` wiring (`KONFIG_AWS_SETTINGS`, precedence, read-only, `secret://` composition); first-boot seeding of empty settings secrets with defaults. |
| `test_secrets/test_secrets.py` | `Secrets` frontend: backend auto-detection order, settings-driven selection, `secret://` URI resolution, placeholder warning on resolution; `seed_from(settings)`. |
| `test_secrets/test_keyring_backend.py` | OS keyring backend: availability probing and CRUD against the keyring API. |
| `test_secrets/test_encrypted_file.py` | AES-encrypted file backend: master-key handling, round-trip CRUD, file creation. |
| `test_secrets/test_aws_bundle_backend.py` | AWS designated-secret JSON bundle backend (stubbed client): ARN parsing, TTL read cache, write-through, re-fetch-before-write, boto3 import error; first-boot seeding of empty bundles with `CHANGEME` placeholders for every `secret://` reference. |
| `test_aws.py` | AWS seeding helpers: `seeding_enabled` detection from `KONFIG_AWS_SEED` environment variable. |
| `test_logging/test_formatters.py` | Text and JSON log formatters. |
| `test_logging/test_run_directory.py` | Run-scoped log directory creation, `latest` symlink, historical retention cleanup (including concurrent-removal tolerance). |
| `test_logging/test_manager.py` | `LogManager`: configuration from settings, startup banner, stdio-safe console routing, shutdown. |
| `integration/test_aws_localstack.py` | Opt-in LocalStack integration (`pytest -m localstack`): bundle backend CRUD round trip and `KONFIG_AWS_SETTINGS` settings layer (load, precedence, rotation via `reload()`, fail-fast missing secret); first-boot seeding of both empty stores with defaults and placeholders. |
