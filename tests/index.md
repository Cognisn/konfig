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
| `test_secrets/test_secrets.py` | `Secrets` frontend: backend auto-detection order, settings-driven selection, `secret://` URI resolution, placeholder warning on resolution; `seed_from(settings)`.; `refresh()` delegation and the no-op `SecretBackend.refresh()` default. |
| `test_secrets/test_keyring_backend.py` | OS keyring backend: availability probing and CRUD against the keyring API. |
| `test_secrets/test_encrypted_file.py` | AES-encrypted file backend: master-key handling, round-trip CRUD, file creation. |
| `test_secrets/test_encrypted_file_shared.py` | Encrypted file as a shared store: multi-process lost updates and concurrent delete/set (spawn, marked `slow`), cross-instance freshness and `refresh()`, thread safety, crash safety on a failed rename, creation-time `0600` permissions, lock timeouts and `secrets.file_lock_timeout` wiring, missing-key refusal, racing first-boot key generation. |
| `test_secrets/test_encrypted_file_format.py` | Encrypted file format v2 (key identifier header), legacy 0.4.0 compatibility and upgrade on write, wrong-key and corruption errors, PBKDF2 derivation cached per file salt. |
| `test_secrets/test_filelock.py` | Sidecar advisory file lock: creation mode, re-entrancy, thread and cross-process exclusion, `TimeoutError`, read-only directory fallback. |
| `test_secrets/test_aws_bundle_backend.py` | AWS designated-secret JSON bundle backend (stubbed client): ARN parsing, TTL read cache, write-through, re-fetch-before-write, boto3 import error; first-boot seeding of empty bundles with `CHANGEME` placeholders for every `secret://` reference. |
| `test_aws.py` | AWS seeding helpers: `seeding_enabled` detection from `KONFIG_AWS_SEED` environment variable. |
| `test_logging/test_formatters.py` | Text and JSON log formatters. |
| `test_logging/test_run_directory.py` | Run-scoped log directory creation, `latest` symlink, historical retention cleanup (including concurrent-removal tolerance). |
| `test_logging/test_manager.py` | `LogManager`: configuration from settings, startup banner, stdio-safe console routing, shutdown. |
| `test_logging/test_central/test_config.py` | Centralised logging config: boolean parsing, `host:port` parsing, defaults (disabled leaves 0.4.1 behaviour), env-over-settings precedence, all-or-nothing endpoint/fingerprint/token override, `secret://` token resolution. |
| `test_logging/test_central/test_identity.py` | Instance identity: always-present fields, label, Docker, Kubernetes downward API values, ECS task metadata against a stub HTTP server, silent ECS timeout and unreachable endpoint, non-HTTP scheme refused. |
| `test_logging/test_central/test_protocol.py` | Wire protocol: frame round trip, escaping, size limits, invalid UTF-8/JSON, protocol versioning, record conversion (emit-time capture, exceptions, serialisable extras, truncation). |
| `test_logging/test_central/test_tls.py` | Collector TLS: fingerprint formatting and matching, `0700`/`0600` state at creation without chmod, token and certificate reuse, regeneration near expiry or on corruption, certificate properties, pin mismatch closes before any byte is sent. |
| `test_logging/test_central/test_collector.py` | Collector: token rejection (token never in logs, stderr or the stream), missing token, unknown protocol, hello-first rule, oversize/invalid frames, handshake and idle timeouts, connection cap, instance tagging and `dropped` notices, own records in the stream, central retention, bind failure, oversized identity blocks. |
| `test_logging/test_central/test_sender.py` | Sender resilience: drop-oldest queue, 10,000 calls with no collector in under a second, bounded stop, DNS failure, handler errors contained, konfig central loggers not forwarded, level filter, overflow reported as a `dropped` count. |
| `test_logging/test_central/test_discovery.py` | Store entry: single JSON value, restart keeps token and certificate and bumps the epoch, replacement warning for another collector host, keyring and missing-advertise warnings, malformed entries absent and logged once, discovery through a shared encrypted file and a stubbed AWS bundle, late collector, re-read after a stale entry. |
| `test_logging/test_central/test_end_to_end.py` | Three sender processes (spawn, marked `slow`) sharing an encrypted file store: every message arrives exactly once with the right label and stays in local logs; collector restart mid-stream (marked `slow`); forwarded level independent of the local level. |
| `test_logging/test_central/test_integration.py` | No pickle or unsafe logging handlers in the package; local log output byte-identical to 0.4.1 fixtures when disabled; `AppContext` collector role, startup failures that never stop the app, sender with no collector, `include_instance_locally`, and the composed `LogManager.start_central_logging()` call. |
| `integration/test_aws_localstack.py` | Opt-in LocalStack integration (`pytest -m localstack`): bundle backend CRUD round trip and `KONFIG_AWS_SETTINGS` settings layer (load, precedence, rotation via `reload()`, fail-fast missing secret); first-boot seeding of both empty stores with defaults and placeholders. |
