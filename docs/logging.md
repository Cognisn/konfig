# Logging

Konfig's `LogManager` provides run-scoped logging with configurable retention, structured JSON output, and stdio-safe operation.

**Critical design constraint:** Konfig never writes to stdout. All console output goes to stderr. This is non-negotiable for compatibility with MCP servers that use stdout for the JSON-RPC protocol.

## Basic Usage

```python
from konfig import LogManager

manager = LogManager(
    app_name="My App",
    version="1.0.0",
    log_dir="logs",
    level="INFO",
)
logger = manager.setup()

logger.info("Application started")
logger.warning("Something happened")

# On shutdown
manager.shutdown()
```

## Run-Scoped Directory Structure

Each application run gets its own timestamped log directory:

```
logs/
├── 2026-03-28T14-30-00/
│   ├── app.log
│   └── app.log.1           # Rotated (if max size exceeded)
├── 2026-03-28T15-45-12/
│   └── app.log
├── 2026-03-29T09-00-00/
│   └── app.log
└── latest -> 2026-03-29T09-00-00/   # Symlink to most recent
```

When no `log_dir` is specified, Konfig uses the [platform-conventional log directory](platform-paths.md) (e.g. `~/Library/Logs/<app_id>/` on macOS).

## Configuration

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `app_name` | str | "Application" | Name shown in the startup banner |
| `version` | str | "0.0.0" | Version shown in the startup banner |
| `log_dir` | Path/str | Platform default | Base directory for run-scoped logs |
| `level` | str | "INFO" | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |
| `log_format` | str | "text" | Output format: "text" or "json" |
| `retention_runs` | int | 10 | Number of historical run directories to keep |
| `max_file_size_mb` | int | 50 | Max log file size before rotation (MB) |
| `max_files_per_run` | int | 3 | Max rotated log files per run |
| `console_output` | str | "auto" | Console output target (see below) |

### Console Output Modes

| Value | Behaviour | Use Case |
|-------|-----------|----------|
| `auto` | Log to stderr (never stdout) | Safe default for all environments |
| `stderr` | Always log to stderr | Containers, MCP stdio servers |
| `none` | File output only, no console | Background services, daemons |

There is intentionally no `stdout` option.

### From Settings

```python
from konfig import Settings, LogManager

settings = Settings(config_file="config.yaml")
manager = LogManager.from_settings(settings, app_name="My App", version="1.0.0")
logger = manager.setup()
```

With a config file:

```yaml
logging:
  level: INFO
  format: text
  log_dir: /var/log/myapp
  retention_runs: 10
  max_file_size_mb: 50
  max_files_per_run: 3
  console_output: auto
```

## Retention

Two dimensions of retention are managed:

### Historical Retention

How many past run directories to keep. On startup, `LogManager` deletes the oldest runs beyond this count. Cleanup runs **only on startup** — logs are never deleted while the app is running.

```python
manager = LogManager(retention_runs=5)  # Keep 5 most recent runs
```

### Session Retention

Log rotation within a single run. When `app.log` exceeds `max_file_size_mb`, it is rotated to `app.log.1`, `app.log.2`, etc., up to `max_files_per_run`.

```python
manager = LogManager(
    max_file_size_mb=50,     # Rotate at 50 MB
    max_files_per_run=3,     # Keep 3 rotated files
)
```

## Log Formats

### Text (default)

Human-readable format:

```
2026-03-28T14:30:00 INFO  [my_app.server] Server started on port 8080
2026-03-28T14:30:01 DEBUG [my_app.db] Connected to database
```

### JSON (structured)

JSON-lines format for CloudWatch, ECS, Datadog, and other log aggregators:

```json
{"timestamp": "2026-03-28T14:30:00.123456+00:00", "level": "INFO", "logger": "my_app.server", "message": "Server started on port 8080", "pid": 12345}
```

Exceptions include an `exception` field with the formatted traceback.

## Startup Banner

On setup, LogManager logs a startup banner to both the log file and stderr:

```
INFO  [konfig] ──────────────────────────────────
INFO  [konfig] App:       My Application
INFO  [konfig] Version:   1.2.3
INFO  [konfig] PID:       12345
INFO  [konfig] Platform:  Darwin-25.2.0-arm64 (macOS 26.2)
INFO  [konfig] Python:    3.10.20
INFO  [konfig] Log Dir:   /Users/me/Library/Logs/myapp/2026-03-28T14-30-00
INFO  [konfig] Log Level: INFO
INFO  [konfig] ──────────────────────────────────
```

## Shutdown

Always call `shutdown()` when done to close file handlers and flush buffers:

```python
manager.shutdown()
```

If using `AppContext`, shutdown is handled automatically on context exit.

## MCP / stdio Safety

When running an MCP server on stdio, stdout is reserved for the JSON-RPC protocol. Konfig's logging guarantees:

1. Console output always goes to **stderr**, never stdout
2. The `auto` mode enforces this regardless of environment
3. There is no `stdout` option — this is by design
4. The `none` mode disables console output entirely for maximum safety
