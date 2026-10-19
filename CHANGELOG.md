# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Encrypted file backend is now safe to share between processes and containers on a shared
  mount (Docker named volumes, Amazon EFS, NFS-backed Kubernetes PVCs) using one
  `KONFIG_MASTER_KEY`:
  - Stale reads: `get()`, `has()` and `list_keys()` reload the file when another process has
    changed it, instead of serving the copy loaded at start-up.
  - Lost updates: `set()` and `delete()` are locked read-modify-write transactions on a sidecar
    `<file>.lock` (`fcntl.lockf` on POSIX, `msvcrt.locking` on Windows), so processes writing
    different keys no longer erase each other's changes.
  - Non-atomic writes: saves go to a temporary file that is `fsync`-ed and renamed into place, so
    a crash mid-save can no longer truncate the file.
  - Permission window: the secrets, key and lock files are created with `0600` rather than
    `chmod`-ed afterwards.
- A missing master key for an existing secrets file now raises `MasterKeyMissingError` instead of
  writing a stray key file and failing with a bare `InvalidToken`. Concurrent first-boot
  processes settle on a single auto-generated key.
- The PBKDF2 key derivation runs once per file salt rather than on every load and save.

### Added

- `refresh()` on `Secrets` and `SecretBackend` (a no-op by default, so existing custom backends
  are unaffected) to force the next read to see the store's current data.
- Encrypted file format v2 with a key identifier, giving a clear `MasterKeyMismatchError` for a
  wrong master key and `SecretsFileCorruptError` for a damaged file (both also `InvalidToken`).
  Files written by 0.4.0 and earlier load unchanged and are upgraded to v2 on their next write.
- `lock_timeout` argument on `EncryptedFileBackend` and the `secrets.file_lock_timeout` setting
  (default 30 seconds).

## [0.4.0] - 2026-08-16

### Added

- First-boot seeding of empty AWS Secrets Manager stores: an empty `KONFIG_AWS_SETTINGS`
  secret is seeded with the application's defaults tree as pretty-printed JSON, and an empty
  `KONFIG_AWS_SECRETS_MANAGER` bundle is seeded with `CHANGEME` placeholders for every
  `secret://` reference in the effective settings (via `Secrets.seed_from`, wired into
  `AppContext`). Resolving an unpopulated placeholder logs a warning naming the key.
  Non-empty stores are never written to; disable with `KONFIG_AWS_SEED=false`.
- `Settings.to_dict()` returning the merged effective settings as one nested dict.

## [0.3.0] - 2026-08-16

### Added

- AWS Secrets Manager settings layer: set `KONFIG_AWS_SETTINGS=<secret ARN or name>` (or pass
  `Settings(aws_settings=...)`, with the environment variable winning) to load an application's
  entire settings tree from a single Secrets Manager secret holding a JSON object. The layer sits
  between environment variables and the user config file in precedence, is read-only, fails fast
  at startup on a missing/unreadable secret or malformed payload, and is re-fetched only on
  `reload()`. Requires `konfig[aws]`; `secret://` values inside the document resolve through the
  active secrets backend as usual.

### Fixed

- PyPI publish workflow: updated the pinned `pypa/gh-action-pypi-publish` to v1.14.2 so wheels
  carrying Metadata-Version 2.5 are accepted, and added a `workflow_dispatch` trigger so a failed
  publish can be re-run from `main`.

## [0.2.1] - 2026-07-13

### Fixed

- Run-log retention no longer crashes when multiple processes share a log directory.
  `cleanup_old_runs` now tolerates a run directory being removed concurrently by another
  process (e.g. sibling worker replicas racing the same cleanup), skipping the
  `FileNotFoundError` instead of aborting.

## [0.2.0] - 2026-06-10

### Added

- Pluggable config file format: store settings as YAML, JSON, or SQLite, selectable via the
  `KONFIG_CONFIG_FORMAT` environment variable (default YAML, otherwise detected from the file
  extension). Reading, updating, and creating settings work across all three formats.
- AWS Secrets Manager bundle backend: set `KONFIG_AWS_SECRETS_MANAGER=<secret-ARN>` to make
  konfig read and write all secrets to a single designated AWS Secrets Manager secret holding
  a JSON bundle (each konfig key is a key within the JSON). The env var is a hard override over
  an explicit backend and over config. Region is derived from the ARN. The designated secret
  must already exist. Requires `pip install konfig[aws]`.
- TTL read cache for the bundle backend (default 300s, configurable via `secrets.aws.cache_ttl`)
  with write-through and re-fetch-before-write to narrow the lost-update window.

### Tests

- Opt-in LocalStack integration test for the AWS Secrets Manager bundle backend
  (`pytest -m localstack`), with a `docker-compose.yml` for local provisioning.

## [0.1.1] - 2026-04-11

### Fixed

- Duplicated string literal in `AppContext` extracted into a module-level constant.
- `__aenter__`/`__aexit__` now delegate to their sync counterparts instead of duplicating implementation.
- Redundant `PermissionError` removed from except clause in `FileLayer` (already a subclass of `OSError`).
- Empty f-string replaced with plain string in logging sample.
- Generator return type annotations added to yield-based test fixtures.
- Unused local variable removed in run directory tests.

### Security

- GitHub Actions `id-token: write` permission moved from workflow level to job level.
- `pypa/gh-action-pypi-publish` pinned to full commit SHA to prevent supply chain attacks.
- Sample secrets script now uses `tempfile.mkdtemp()` instead of hardcoded `/tmp/` paths.

### Added

- SonarCloud quality badges in README.

## [0.1.0] - 2026-03-28

### Added

- Layered settings system with CRUD API, dot-notation keys, and YAML/TOML/JSON support.
- System-level and user-level config file layers with persistent writes.
- Environment variable mapping with configurable prefix and `__` separator.
- Pluggable secrets management with OS keyring, AES-encrypted file, and AWS Secrets Manager backends.
- `secret://` URI scheme for transparent secret resolution from settings.
- Run-scoped logging with configurable historical and session retention.
- Text and structured JSON log formatters.
- stdio-safe logging (never writes to stdout) for MCP server compatibility.
- Startup banner with app name, version, PID, platform, and log directory.
- Platform-aware default paths for config, data, and log directories (macOS, Linux, Windows).
- `AppContext` sync/async context manager for optional app lifecycle.
- GitHub Actions workflows for CI and PyPI publishing.
