# Graph Report - konfig  (2026-11-20)

## Corpus Check
- 114 files · ~58,511 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1762 nodes · 3950 edges · 100 communities (83 shown, 10 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 290 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- tests test_paths TestAppIdFrom
- collector QueueHandler
- tests test_config TestDefaults
- filelock AbstractContextManager
- tests test_parsers TestParseFileErrors
- encrypted_file InvalidToken
- tests test_encrypted_file_shared Event
- tests test_settings Settings
- tests helpers FakeSMClient
- backend ABC
- tests test_encrypted_file EncryptedFileBackend
- discovery CollectorEntry
- tests test_collector CaptureFixture
- tests test_run_directory TestCleanupOldRuns
- tests test_keyring_backend KeyringBackend
- tests test_aws_bundle_backend TestReadsAfterRefresh
- layers RuntimeLayer
- tests test_helpers TestMalformedCompleteLine
- tests test_writer_rollover CaptureFixture
- tests test_collector_errors BaseException
- layers PermissionError
- tests test_protocol TestRecordToWire
- tests test_encrypted_file_format TestCorruption
- tests test_identity
- tests test_aws_bundle_backend AWSSecretsBundleBackend
- tests test_sqlite_store TestFlatten
- tests test_aws_localstack
- aws_layer AwsSettingsLayer
- init__ CentralLogging
- sender LogSender
- secrets Secrets
- protocol ProtocolError
- tests test_aws_bundle_backend FakeSMClient
- collector CentralCollector
- tlsutil CollectorCertificate
- tests test_tls TestStateFiles
- tests test_tls RecordingTLSServer
- tests test_bump_version CompletedProcess
- tests test_rotation IO
- tests test_aws TestSeedingEnabled
- tests test_integration TestAppContext
- tests test_aws_layer TestSettingsWiring
- tests test_manager LogManager
- layers EnvLayer
- tests helpers
- app AppContext
- tests test_settings TestConfigFormatSelection
- aws_bundle_backend
- tests test_localstack_endpoint LocalStackEndpoint
- tests test_secrets TestSeedFrom
- tests test_secrets InMemoryBackend
- tests test_sender CentralLogConfig
- tests test_layers DefaultsLayer
- settings
- tests test_aws_layer FakeSMClient
- formatters InstanceJSONFormatter
- tests test_manager TestLogManagerFromSettings
- tests conftest
- tests test_aws_layer TestSettingsDocumentSeeding
- init__
- manager Logger
- encrypted_file
- tests test_aws_bundle_backend TestBotoImport
- tests test_secrets TestPlaceholderWarning
- samples custom_backend InMemoryBackend
- tests test_parsers TestResolveFormat
- tests test_aws_bundle_backend Clock
- tests test_secrets TestEnvVarBundleSelection
- collector CaptureHandler
- tests test_aws_layer TestBotoImport
- tlsutil
- tests test_app
- tests test_aws_layer TestSecretUriComposition
- samples async_app TestAppContextAsync
- samples central_logging
- formatters TextFormatter
- tests test_app TestAppContextSync
- aws
- formatters
- manager
- tests conftest 2
- tests conftest 3
- aws_bundle_backend StaleBundleError
- secrets
- layers
- tests conftest 4
- tests test_aws_layer TestRegionSelection
- manager 2
- tests workers
- manager 3
- bump-version
- settings 2
- pyproject

## God Nodes (most connected - your core abstractions)
1. `Settings` - 108 edges
2. `EncryptedFileBackend` - 98 edges
3. `Secrets` - 76 edges
4. `AWSSecretsBundleBackend` - 64 edges
5. `AwsSettingsLayer` - 50 edges
6. `LogManager` - 49 edges
7. `FakeSMClient` - 43 edges
8. `CentralCollector` - 37 edges
9. `LogSender` - 37 edges
10. `CentralLogConfig` - 36 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `AppContext`  [INFERRED]
  samples/async_app.py → src/konfig/app.py
- `test_app_context_calls_seed_from()` --uses--> `AppContext`  [INFERRED]
  tests/test_app.py → src/konfig/app.py
- `TestAppContextAsync` --uses--> `AppContext`  [INFERRED]
  tests/test_app.py → src/konfig/app.py
- `TestAppContextSync` --uses--> `AppContext`  [INFERRED]
  tests/test_app.py → src/konfig/app.py
- `capture_app_log()` --calls--> `AppContext`  [INFERRED]
  tests/test_logging/test_central/_regression.py → src/konfig/app.py

## Import Cycles
- None detected.

## Communities (100 total, 10 thin omitted)

### Community 0 - "tests test_paths TestAppIdFrom"
Cohesion: 0.06
Nodes (33): Path, AppContext — optional lightweight app lifecycle context manager., app_id_from(), config_dir(), data_dir(), default_config_file(), default_secrets_file(), default_system_config_file() (+25 more)

### Community 1 - "collector QueueHandler"
Cohesion: 0.05
Nodes (25): QueueHandler, CentralRotatingFileHandler, CentralWriter, _clean_instance(), Any, OSError, Path, RotatingFileHandler (+17 more)

### Community 2 - "tests test_config TestDefaults"
Cohesion: 0.07
Nodes (27): The Settings instance., _level(), _number(), parse_bool(), parse_host_port(), Any, Resolve settings and environment variables into a central logging config. This…, Return (values, source, error) for the endpoint/fingerprint/token trio. (+19 more)

### Community 3 - "filelock AbstractContextManager"
Cohesion: 0.09
Nodes (29): AbstractContextManager, FileLock, _PathState, Path, Cross-process advisory file locking for the encrypted file backend. A sidecar…, Hold a shared (read) lock; exclusive on Windows., Hold an exclusive (write) lock., Exclude other threads in this process without taking the OS lock. Locks taken… (+21 more)

### Community 4 - "tests test_parsers TestParseFileErrors"
Cohesion: 0.12
Nodes (23): _format_from_extension(), parse_file(), _parse_json(), _parse_toml(), _parse_yaml(), Any, Path, Config file parsers for YAML, TOML, and JSON formats. (+15 more)

### Community 5 - "encrypted_file InvalidToken"
Cohesion: 0.08
Nodes (29): InvalidToken, _check_permissions(), _create_owner_only(), _derive_key(), EncryptedFileError, _fsync_directory(), _key_id(), MasterKeyMismatchError (+21 more)

### Community 6 - "tests test_encrypted_file_shared Event"
Cohesion: 0.09
Nodes (20): Event, churn_keys(), first_boot_write(), Write ``count`` distinct keys owned by ``worker``., Repeatedly set (or delete) the shared ``churn-*`` keys., Open a store with no master key configured and write one key., write_keys(), MonkeyPatch (+12 more)

### Community 7 - "tests test_settings Settings"
Cohesion: 0.10
Nodes (12): Check if a key exists in any layer., Reload both config files from disk and re-fetch the AWS settings document (when…, Unified settings with layered precedence. Layers (lowest to highest): 1.…, Settings, Tests for the Settings class., TestSettingsGet, TestSettingsGetSection, TestSettingsHas (+4 more)

### Community 8 - "tests helpers FakeSMClient"
Cohesion: 0.12
Nodes (26): FakeSMClient, isolated_logger(), messages(), Handler, Logger, Minimal in-memory stand-in for a boto3 secretsmanager client., A logger that sends only to ``handler``, bypassing the root logger., A fresh view of a shared encrypted file store, as another container sees it. (+18 more)

### Community 9 - "backend ABC"
Cohesion: 0.08
Nodes (15): ABC, AWSSecretsManagerBackend, AWS Secrets Manager backend for secret storage (optional)., Stores secrets in AWS Secrets Manager. Requires ``boto3`` to be installed…, Abstract interface for secret storage backends., Retrieve a secret by key. Returns None if not found., Delete a secret by key., Check if a secret exists. (+7 more)

### Community 10 - "tests test_encrypted_file EncryptedFileBackend"
Cohesion: 0.13
Nodes (13): EncryptedFileBackend, Stores secrets in an AES-encrypted JSON file. The master key is sourced from:…, Reload if the file has changed since it was last read or written., Unconditionally reload the file from disk under a shared lock. Taking the lock…, LogCaptureFixture, MonkeyPatch, Path, skipif (+5 more)

### Community 11 - "discovery CollectorEntry"
Cohesion: 0.11
Nodes (18): CollectorEntry, EntryReader, is_shared_backend(), parse_entry(), publish_entry(), Any, Publish (collector) and read (sender) the collector's store entry. The entry is…, False when the active secrets backend is local to this machine (OS keyring). (+10 more)

### Community 12 - "tests test_collector CaptureFixture"
Cohesion: 0.15
Nodes (12): _entry(), CaptureFixture, LogCaptureFixture, Path, StartCollector, Tests for the collector: authentication, protocol enforcement, central stream., A hand-driven pinned TLS client for protocol-level tests., RawClient (+4 more)

### Community 13 - "tests test_run_directory TestCleanupOldRuns"
Cohesion: 0.14
Nodes (16): cleanup_old_runs(), create_run_directory(), list_run_directories(), Path, Run-scoped log directory creation and historical retention., Create a new run-scoped log directory. Creates a directory named with the…, Update the ``latest`` symlink to point to the given target., Remove old run directories, keeping the N most recent. Only directories… (+8 more)

### Community 14 - "tests test_keyring_backend KeyringBackend"
Cohesion: 0.09
Nodes (9): KeyringBackend, Stores secrets in the OS keyring (macOS Keychain, Windows Credential Locker,…, Check if a functional keyring backend is available., keyring_backend(), MockKeyring, fixture, Tests for the keyring backend (mocked)., In-memory mock of the keyring module. (+1 more)

### Community 15 - "tests test_aws_bundle_backend TestReadsAfterRefresh"
Cohesion: 0.12
Nodes (10): _no_sleep_backend(), Any, Stand-in for a boto3 secretsmanager client that keeps a version history. Every…, Another process puts a version this backend has never seen., A backend whose re-fetch backoff records its delays instead of sleeping., Sequential writes from one instance against an eventually consistent store., A read after refresh() never goes back past what this instance has seen., TestReadsAfterRefresh (+2 more)

### Community 16 - "layers RuntimeLayer"
Cohesion: 0.11
Nodes (14): _delete_nested(), _get_nested(), _get_section(), Any, Layer implementations for the Settings system. Layers (lowest to highest…, All settings visible through this layer, as a nested dict. Only meaningful when…, Retrieve a value from a nested dict using dot-notation key., Layer 4: Values set programmatically at runtime. (+6 more)

### Community 17 - "tests test_helpers TestMalformedCompleteLine"
Cohesion: 0.21
Nodes (14): poll_stream(), Every complete entry under ``log_dir``, for polling a running collector. The…, entry(), line(), Any, parametrize, Path, The stream readers in _helpers: strict after the collector stops, tolerant only… (+6 more)

### Community 18 - "tests test_writer_rollover CaptureFixture"
Cohesion: 0.17
Nodes (28): backups(), count_copies(), emit_all(), line(), make_handler(), ordered_lines(), CaptureFixture, LogCaptureFixture (+20 more)

### Community 19 - "tests test_collector_errors BaseException"
Cohesion: 0.11
Nodes (16): BaseException, _collector(), _Interrupt, Any, LogCaptureFixture, MonkeyPatch, Path, Collector error handling: what the listener thread and handlers let through. (+8 more)

### Community 20 - "layers PermissionError"
Cohesion: 0.11
Nodes (14): PermissionError, FileLayer, Path, Values loaded from a config file (YAML, TOML, or JSON). Supports optional…, Reload the config file from disk., Set a value and persist to the config file. Raises: PermissionError: If the…, Delete a value and persist to the config file. Returns: True if the key was…, Write current data back to the config file. (+6 more)

### Community 21 - "tests test_protocol TestRecordToWire"
Cohesion: 0.13
Nodes (18): check_protocol(), dropped(), _extras(), hello(), Any, LogRecord, Wire format for centralised log forwarding. Frames are newline-delimited UTF-8…, Raise ``ProtocolError`` unless the message speaks our protocol version. (+10 more)

### Community 22 - "tests test_encrypted_file_format TestCorruption"
Cohesion: 0.13
Nodes (13): _assert_no_key_material(), _legacy_fernet_key(), MonkeyPatch, Path, File format, legacy compatibility and key handling for the encrypted file…, The 0.4.0 key derivation, reimplemented independently of the backend., Write a file in the exact 0.4.0 format: 16-byte salt + Fernet token., TestCorruption (+5 more)

### Community 23 - "tests test_identity"
Cohesion: 0.14
Nodes (23): detect_instance(), _ecs_metadata(), _fetch_json(), Any, Path, Detect the identity block that tags every forwarded log record., Read task and container details from the ECS task metadata endpoint v4.…, Build the identity block for this instance. Always includes the hostname, PID,… (+15 more)

### Community 24 - "tests test_aws_bundle_backend AWSSecretsBundleBackend"
Cohesion: 0.12
Nodes (8): AWSSecretsBundleBackend, Return the cached bundle, refreshing if the TTL has expired., Force the next read to re-fetch the bundle from AWS. The versions this instance…, Reads and writes secrets to a single AWS secret holding a JSON bundle. The…, bundle_secrets(), TestArnParsing, TestErrorHandling, TestReadPath

### Community 25 - "tests test_sqlite_store TestFlatten"
Cohesion: 0.14
Nodes (16): _flatten(), Any, Path, SQLite backing store for config settings. Stores a nested config dict as a flat…, Flatten a nested dict into (dot-key, leaf-value) pairs. A leaf is any non-dict…, Rebuild a nested dict from (dot-key, leaf-value) pairs., Read all settings into a nested dict. Returns ``{}`` if the file or the…, Replace the ``settings`` table contents with the flattened nested dict. (+8 more)

### Community 26 - "tests test_aws_localstack"
Cohesion: 0.14
Nodes (25): _aws_env(), bundle_arn(), _client(), empty_secret(), _localstack_reachable(), fixture, MonkeyPatch, Opt-in LocalStack integration tests for the AWS Secrets Manager bundle backend.… (+17 more)

### Community 27 - "aws_layer AwsSettingsLayer"
Cohesion: 0.13
Nodes (8): AwsSettingsLayer, Any, First-boot path: the store exists but its payload is empty. Writes the…, The secret ARN or name, or None when the layer is inert., Read-only settings layer backed by one AWS Secrets Manager secret. Args:…, Re-fetch the settings document from AWS. Raises: RuntimeError: If the secret is…, TestFailFast, TestInertWhenUnconfigured

### Community 28 - "init__ CentralLogging"
Cohesion: 0.15
Nodes (20): Validate connection details from any source. Raises: ValueError: With a message…, validate_details(), CentralLogging, _include_instance_locally(), _lower_root_level(), Any, Optional centralised log forwarding. One nominated instance, the collector,…, Start centralised log forwarding when it is enabled. Call after… (+12 more)

### Community 29 - "sender LogSender"
Cohesion: 0.12
Nodes (9): _ConnectFailure, LogSender, Exception, A connection attempt failed; the message is safe to log., Ships queued records to the collector from a daemon thread. Args: config:…, Number of records successfully handed to the collector connection., Drain for up to ``flush_timeout`` seconds, then stop. The handler should…, Detect a collector that has closed the connection since the last send. (+1 more)

### Community 30 - "secrets Secrets"
Cohesion: 0.11
Nodes (9): Delete a secret by key., Check if a secret exists., List all stored secret keys., Make the next read see the active backend's current data. Delegates to the…, Unified secrets API with pluggable backends. Backend selection order (highest…, The active backend instance., Select the best available backend., Secrets (+1 more)

### Community 31 - "protocol ProtocolError"
Cohesion: 0.17
Nodes (12): decode_frame(), encode_frame(), encode_log_batch(), encode_record(), ProtocolError, Build a ``log`` frame from records already serialised to JSON text., Serialise one wire record to compact JSON text., A frame was malformed, oversized, or violated the protocol. Messages never… (+4 more)

### Community 32 - "tests test_aws_bundle_backend FakeSMClient"
Cohesion: 0.13
Nodes (7): FakeSMClient, LogCaptureFixture, MonkeyPatch, parametrize, Minimal stand-in for a boto3 secretsmanager client., TestSeedIfEmpty, TestWritePath

### Community 33 - "collector CentralCollector"
Cohesion: 0.16
Nodes (10): CentralCollector, _peer(), SSLContext, The collector role: certificate, token, listener, writer and publication. Args:…, The advertised ``host:port`` senders connect to., The port actually bound (useful when listening on port 0)., Close the listener and every connection, then drain the writer., Authenticate the sender; return its identity block, or None if rejected. (+2 more)

### Community 34 - "tlsutil CollectorCertificate"
Cohesion: 0.16
Nodes (18): datetime, _printable(), TLS listener that receives forwarded records and writes the central stream. The…, Neutralise control characters (newlines included) for local log lines., CollectorCertificate, generate_certificate(), _load(), load_or_create_token() (+10 more)

### Community 35 - "tests test_tls TestStateFiles"
Cohesion: 0.26
Nodes (9): posix_only, ensure_private_dir(), load_or_create_certificate(), Reuse the stored certificate, or generate one if missing or near expiry., Create ``path`` with mode 0700 (parents with the default mode)., _mode(), MonkeyPatch, Path (+1 more)

### Community 36 - "tests test_tls RecordingTLSServer"
Cohesion: 0.15
Nodes (13): fingerprint_der(), SHA-256 of a DER certificate as uppercase colon-separated hex., fixture, LogCaptureFixture, parametrize, Tests for collector certificates, fingerprints and pinning., A TLS server that records what one client connection did. It counts the TCP…, recording_server() (+5 more)

### Community 37 - "tests test_bump_version CompletedProcess"
Cohesion: 0.16
Nodes (14): CompletedProcess, _find_bash(), Project, fixture, parametrize, Path, Tests for scripts/bump-version.sh, run with bash against a temporary copy., Return a bash that can run the script, or ``None``. On Windows the ``bash`` on… (+6 more)

### Community 38 - "tests test_rotation IO"
Cohesion: 0.22
Nodes (18): IO, assert_every_record_kept(), entry(), no_reader(), plain_reader(), Any, Path, range (+10 more)

### Community 39 - "tests test_aws TestSeedingEnabled"
Cohesion: 0.15
Nodes (12): Whether first-boot seeding of empty AWS stores is enabled. Controlled by the…, seeding_enabled(), find_secret_refs(), _walk(), Any, Seed an empty AWS bundle store from the effective settings. First-boot…, Collect secret names referenced as ``secret://<name>`` values. Recursively…, MonkeyPatch (+4 more)

### Community 40 - "tests test_integration TestAppContext"
Cohesion: 0.20
Nodes (9): _app(), _collector_settings(), LogCaptureFixture, MonkeyPatch, parametrize, Path, TestAppContext, TestNoPickle (+1 more)

### Community 41 - "tests test_aws_layer TestSettingsWiring"
Cohesion: 0.14
Nodes (6): Any, fixture, MonkeyPatch, The layer wired into Settings via env var / constructor parameter., Install a stub client so Settings can build the layer without boto3., TestSettingsWiring

### Community 42 - "tests test_manager LogManager"
Cohesion: 0.21
Nodes (6): LogManager, Application identifier used for default paths., The running centralised logging role, if any., Configures Python logging from settings with run-scoped directories. CRITICAL:…, Path, TestLogManager

### Community 43 - "layers EnvLayer"
Cohesion: 0.19
Nodes (6): EnvLayer, Layer 3: Values from environment variables. Nested keys are mapped using ``__``…, Scan environment for all keys under a prefix., MonkeyPatch, TestEnvLayer, TestEnvLayerEnumerate

### Community 44 - "tests helpers"
Cohesion: 0.17
Nodes (14): free_port(), _parse(), Any, Path, Helpers shared by the centralised log forwarding tests., Every entry in every central stream file under ``log_dir``. Strict: every line…, read_stream(), _stream_files() (+6 more)

### Community 45 - "app AppContext"
Cohesion: 0.15
Nodes (8): AppContext, Any, Logger, Clean up all subsystems., The Secrets instance., The LogManager instance., Lifecycle context manager that wires together Settings, Secrets, and Logging.…, Initialise all subsystems.

### Community 46 - "tests test_settings TestConfigFormatSelection"
Cohesion: 0.21
Nodes (4): MonkeyPatch, Path, TestConfigFormatSelection, TestPersistSettings

### Community 47 - "aws_bundle_backend"
Cohesion: 0.15
Nodes (7): Any, True for a version this instance has seen replaced by a newer one. A version it…, Call get_secret_value, re-fetching while it returns a superseded version.…, Fetch and parse the bundle directly from AWS (no cache). Never returns a…, Persist the whole bundle to AWS and update the write-through cache. The…, Seed the bundle with placeholder entries when the store is empty. Empty means…, Record ``version_id`` as the newest version this instance knows.

### Community 48 - "tests test_localstack_endpoint LocalStackEndpoint"
Cohesion: 0.26
Nodes (13): LocalStackEndpoint, Where the opt-in LocalStack integration tests find LocalStack. The endpoint URL…, Return the LocalStack endpoint from the environment (or the default). Raises…, resolve_endpoint(), MonkeyPatch, parametrize, Resolution of the LocalStack endpoint used by the opt-in integration tests.…, test_blank_value_falls_back_to_default() (+5 more)

### Community 49 - "tests test_secrets TestSeedFrom"
Cohesion: 0.18
Nodes (4): MonkeyPatch, Stands in for AWSSecretsBundleBackend in seed_from routing tests., _RecordingBundleBackend, TestSeedFrom

### Community 50 - "tests test_secrets InMemoryBackend"
Cohesion: 0.15
Nodes (4): InMemoryBackend, Simple in-memory backend for testing., TestRefresh, TestSecretURIResolution

### Community 51 - "tests test_sender CentralLogConfig"
Cohesion: 0.19
Nodes (7): CentralLogConfig, Typed, immutable centralised log forwarding configuration. Build one with…, True when this instance takes part in forwarding in either role., True when a complete endpoint, fingerprint and token were supplied., _dead_sender(), MonkeyPatch, TestNeverBlocks

### Community 52 - "tests test_layers DefaultsLayer"
Cohesion: 0.20
Nodes (5): Settings subsystem — layered configuration with CRUD API., DefaultsLayer, Layer 1: Hardcoded application defaults., Settings class — unified layered access to configuration., TestDefaultsLayer

### Community 53 - "settings"
Cohesion: 0.19
Nodes (8): _deep_merge(), Any, Set a setting value. By default, sets a runtime override (in-memory only,…, Get all keys under a prefix, merged across all layers. Args: prefix: Dot-…, Return the merged effective settings as one nested dict. Deep-merges every…, Recursively merge override into base, returning a new dict., Layers in highest-to-lowest precedence for reads., Get a setting value by dot-notation key. Layers are checked in reverse…

### Community 54 - "tests test_aws_layer FakeSMClient"
Cohesion: 0.24
Nodes (3): FakeSMClient, Minimal stand-in for a boto3 secretsmanager client (read-only)., TestFetchAndRead

### Community 55 - "formatters InstanceJSONFormatter"
Cohesion: 0.24
Nodes (7): InstanceJSONFormatter, JSONFormatter, Text and JSON log formatters., Structured JSON-lines log formatter for container/cloud environments. Each log…, JSON formatter that adds the centralised logging ``instance`` block. Used for…, Tests for log formatters., TestJSONFormatter

### Community 56 - "tests test_manager TestLogManagerFromSettings"
Cohesion: 0.18
Nodes (8): Any, Start centralised log forwarding if ``logging.central`` enables it. Call after…, Create a LogManager configured from a Settings instance. Args: settings: A…, _clean_root_logger(), fixture, Tests for the LogManager., Remove all handlers from root logger before and after each test., TestLogManagerFromSettings

### Community 57 - "tests conftest"
Cohesion: 0.26
Nodes (11): clean_env(), fixture, MonkeyPatch, Path, Shared fixtures for the centralised log forwarding tests., Keep the host environment from switching the feature on or off., restore_root_logger(), start_collector() (+3 more)

### Community 58 - "tests test_aws_layer TestSettingsDocumentSeeding"
Cohesion: 0.18
Nodes (4): LogCaptureFixture, parametrize, First-boot seeding of an empty KONFIG_AWS_SETTINGS store (issue #7)., TestSettingsDocumentSeeding

### Community 59 - "init__"
Cohesion: 0.18
Nodes (5): AppContext usage — the recommended way to use Konfig in an application., Basic settings usage — loading from a YAML config file with defaults and env…, Logging demo — run-scoped logging with retention and formatters., Secrets usage — storing and retrieving secrets with the encrypted file backend., Konfig — Settings, Secrets, and Logging for Python applications.

### Community 60 - "manager Logger"
Cohesion: 0.20
Nodes (6): Logging subsystem — run-scoped logging with retention., _get_pid(), _get_platform(), Logger, LogManager — configure Python logging from settings., Set up logging: create run dir, configure handlers, log startup banner.…

### Community 61 - "encrypted_file"
Cohesion: 0.20
Nodes (4): apply(), Decrypt v2 or legacy file contents, recording the file's salt., Load and decrypt the file into the cache, recording its signature., Run a locked read-modify-write against the file on disk. ``mutate`` changes a…

### Community 62 - "tests test_aws_bundle_backend TestBotoImport"
Cohesion: 0.18
Nodes (6): Exception, Tests for the AWS Secrets Manager bundle backend., _ResourceNotFound, TestBotoImport, TestIdempotentPut, TestThreadedWriters

### Community 64 - "samples custom_backend InMemoryBackend"
Cohesion: 0.20
Nodes (3): InMemoryBackend, Custom secret backend — implementing a simple in-memory backend., A simple in-memory secret backend for demonstration. Secrets are lost when the…

### Community 65 - "tests test_parsers TestResolveFormat"
Cohesion: 0.29
Nodes (4): Resolve the active config format. Precedence: explicit ``override`` (from…, resolve_format(), Path, TestResolveFormat

### Community 66 - "tests test_aws_bundle_backend Clock"
Cohesion: 0.24
Nodes (3): Clock, Controllable monotonic clock for TTL tests., TestTtlCache

### Community 67 - "tests test_secrets TestEnvVarBundleSelection"
Cohesion: 0.22
Nodes (4): Path, TestEnvVarBundleSelection, fake_init(), TestSecretsAutoDetection

### Community 68 - "collector CaptureHandler"
Cohesion: 0.22
Nodes (6): CaptureHandler, format_endpoint(), LogRecord, Writes the collector's own application records into the central stream., Provision credentials, start the writer and listener, then publish., _utc_now()

### Community 69 - "tests test_aws_layer TestBotoImport"
Cohesion: 0.25
Nodes (6): _ClientError, Exception, Tests for the AWS Secrets Manager settings layer., _ResourceNotFound, TestBotoImport, raise_generic()

### Community 70 - "tlsutil"
Cohesion: 0.25
Nodes (7): client_context(), fingerprint_matches(), normalise_fingerprint(), SSLContext, TLS client context for senders. SECURITY: certificate-authority validation and…, Accept colon-separated or plain hex and return the canonical form. Raises:…, Constant-time comparison of a peer certificate against a pinned fingerprint.

### Community 71 - "tests test_app"
Cohesion: 0.25
Nodes (6): _clean_root_logger(), fixture, Tests for the AppContext lifecycle., AppContext wires bundle seeding at startup, after logging is up., Remove all handlers from root logger before and after each test., test_app_context_calls_seed_from()

### Community 73 - "samples async_app TestAppContextAsync"
Cohesion: 0.33
Nodes (4): asyncio, main(), Async AppContext usage — for async applications and servers., TestAppContextAsync

### Community 74 - "samples central_logging"
Cohesion: 0.48
Nodes (6): app_context(), main(), Path, Centralised log forwarding — one collector and two senders on one machine. Run…, The same application configuration for every role., run_sender()

### Community 75 - "formatters TextFormatter"
Cohesion: 0.43
Nodes (3): Human-readable text log formatter. Format: ``LEVEL [logger] message``, TextFormatter, TestTextFormatter

### Community 77 - "aws"
Cohesion: 0.40
Nodes (4): parse_region(), Shared AWS helpers used by both the secrets backends and the settings layer., Extract the region from a Secrets Manager ARN. ARN shape:…, AWS Secrets Manager settings layer (optional, requires konfig[aws]). Loads an…

### Community 78 - "formatters"
Cohesion: 0.53
Nodes (3): Any, LogRecord, Build the dict serialised for ``record``.

### Community 79 - "manager"
Cohesion: 0.33
Nodes (3): Path, Path to the current run's log directory., Base directory holding the run-scoped log directories.

### Community 80 - "tests conftest 2"
Cohesion: 0.33
Nodes (5): _clear_konfig_aws_env(), fixture, MonkeyPatch, Shared fixtures for secrets tests., Ensure the AWS bundle env var never leaks into secrets tests by default. Tests…

### Community 81 - "tests conftest 3"
Cohesion: 0.33
Nodes (5): _clear_konfig_env(), fixture, MonkeyPatch, Shared fixtures for settings tests., Ensure konfig env vars never leak into settings tests by default. Tests that…

### Community 82 - "aws_bundle_backend StaleBundleError"
Cohesion: 0.40
Nodes (4): RuntimeError, AWS Secrets Manager single-secret JSON bundle backend (optional)., Secrets Manager kept returning a bundle version known to be superseded. Raised…, StaleBundleError

### Community 85 - "tests conftest 4"
Cohesion: 0.40
Nodes (4): fixture, Path, Provide a temporary directory for test files., tmp_dir()

### Community 86 - "tests test_aws_layer TestRegionSelection"
Cohesion: 0.50
Nodes (3): TestRegionSelection, recording_client_func(), recording_client_func()

### Community 88 - "tests workers"
Cohesion: 0.50
Nodes (3): Sender processes for the end-to-end tests. Kept at module level in an…, Run an ``AppContext`` sender that logs ``count`` distinct messages., run_sender()

## Knowledge Gaps
- **2 isolated node(s):** `cognisn-konfig`, `bump-version.sh script`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 501 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `tests test_settings Settings` to `tests test_paths TestAppIdFrom`, `tests test_config TestDefaults`, `tests test_encrypted_file_shared Event`, `tests helpers FakeSMClient`, `backend ABC`, `layers RuntimeLayer`, `layers PermissionError`, `tests test_aws_localstack`, `aws_layer AwsSettingsLayer`, `secrets Secrets`, `tests test_aws TestSeedingEnabled`, `tests test_integration TestAppContext`, `tests test_aws_layer TestSettingsWiring`, `layers EnvLayer`, `app AppContext`, `tests test_settings TestConfigFormatSelection`, `tests test_secrets TestSeedFrom`, `tests test_layers DefaultsLayer`, `settings`, `tests test_manager TestLogManagerFromSettings`, `tests test_aws_layer TestSettingsDocumentSeeding`, `init__`, `tests test_parsers TestResolveFormat`, `tests test_secrets TestEnvVarBundleSelection`, `tests test_aws_layer TestSecretUriComposition`, `settings 2`?**
  _High betweenness centrality (0.188) - this node is a cross-community bridge._
- **Why does `Secrets` connect `secrets Secrets` to `tests test_paths TestAppIdFrom`, `tests test_config TestDefaults`, `encrypted_file InvalidToken`, `tests test_encrypted_file_shared Event`, `tests test_settings Settings`, `tests helpers FakeSMClient`, `backend ABC`, `tests test_encrypted_file EncryptedFileBackend`, `discovery CollectorEntry`, `tests test_keyring_backend KeyringBackend`, `tests test_aws_bundle_backend AWSSecretsBundleBackend`, `tests test_aws_localstack`, `tests test_aws TestSeedingEnabled`, `tests test_integration TestAppContext`, `app AppContext`, `tests test_secrets TestSeedFrom`, `tests test_secrets InMemoryBackend`, `init__`, `tests test_secrets TestPlaceholderWarning`, `tests test_secrets TestEnvVarBundleSelection`, `tests test_app`, `tests test_aws_layer TestSecretUriComposition`, `secrets`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Why does `EncryptedFileBackend` connect `tests test_encrypted_file EncryptedFileBackend` to `tests test_config TestDefaults`, `filelock AbstractContextManager`, `tests test_secrets TestEnvVarBundleSelection`, `encrypted_file InvalidToken`, `tests test_encrypted_file_shared Event`, `tests helpers FakeSMClient`, `backend ABC`, `tests test_integration TestAppContext`, `tests test_encrypted_file_format TestCorruption`, `encrypted_file`, `secrets Secrets`?**
  _High betweenness centrality (0.152) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `Settings` (e.g. with `AppContext` and `Secrets`) actually correct?**
  _`Settings` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `EncryptedFileBackend` (e.g. with `FileLock` and `Secrets`) actually correct?**
  _`EncryptedFileBackend` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `Secrets` (e.g. with `AppContext` and `AWSSecretsManagerBackend`) actually correct?**
  _`Secrets` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `AWSSecretsBundleBackend` (e.g. with `Secrets` and `TestDiscovery`) actually correct?**
  _`AWSSecretsBundleBackend` has 12 INFERRED edges - model-reasoned connections that need verification._