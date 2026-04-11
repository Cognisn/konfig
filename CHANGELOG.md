# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
