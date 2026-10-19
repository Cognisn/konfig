# Configuration Reference

This document lists all configuration keys that Konfig recognises in config files.

## Logging

```yaml
logging:
  level: INFO                    # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: text                   # text or json
  log_dir: logs                  # Base directory for run-scoped logs
  retention_runs: 10             # Keep N most recent run directories
  max_file_size_mb: 50           # Rotate log file at this size (MB)
  max_files_per_run: 3           # Keep N rotated files per run
  console_output: auto           # auto, stderr, or none
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `logging.level` | str | `INFO` | Minimum log level |
| `logging.format` | str | `text` | Output format: `text` (human-readable) or `json` (structured) |
| `logging.log_dir` | str | Platform default | Base directory for run-scoped log directories |
| `logging.retention_runs` | int | `10` | Number of historical run directories to keep |
| `logging.max_file_size_mb` | int | `50` | Maximum log file size before rotation |
| `logging.max_files_per_run` | int | `3` | Maximum number of rotated log files per run |
| `logging.console_output` | str | `auto` | Where console logs go: `auto` (stderr), `stderr`, or `none` |

## Centralised Log Forwarding

Optional and off by default. See [Centralised Log Forwarding](logging.md#centralised-log-forwarding)
for the roles, security model and deployment examples. Environment variables win over settings.

```yaml
logging:
  central:
    enabled: false               # sender role
    collector: false             # collector role (implies enabled)
    listen: 0.0.0.0:9020         # collector bind address
    advertise: log-collector:9020
    level: INFO                  # minimum level forwarded (independent of logging.level)
    queue_size: 10000
    store_key: konfig.log_collector
    flush_timeout: 5
```

| Key | Env var | Type | Default | Description |
|-----|---------|------|---------|-------------|
| `logging.central.enabled` | `KONFIG_LOG_CENTRAL` | bool | `false` | Forward this instance's records to the collector (sender role) |
| `logging.central.collector` | `KONFIG_LOG_COLLECTOR` | bool | `false` | Nominate this instance as the collector; implies `enabled` |
| `logging.central.listen` | `KONFIG_LOG_COLLECTOR_LISTEN` | str | `0.0.0.0:9020` | Collector bind address (`host:port`, `[ipv6]:port`) |
| `logging.central.advertise` | `KONFIG_LOG_COLLECTOR_ADVERTISE` | str | none | Stable name senders connect to, for example `log-collector:9020`; the port defaults to the bound port. Without it, `hostname:port` is advertised with a warning |
| `logging.central.endpoint` | `KONFIG_LOG_ENDPOINT` | str | none | Sender override of the discovered endpoint |
| `logging.central.cert_sha256` | `KONFIG_LOG_CERT_SHA256` | str | none | Sender override of the discovered certificate fingerprint (colon-separated or plain hex) |
| `logging.central.token` | `KONFIG_LOG_TOKEN` | str | none | Sender override of the discovered token; may be a `secret://` reference |
| `logging.central.instance_label` | `KONFIG_LOG_INSTANCE_LABEL` | str | none | Human label for this instance, for example `worker-3` |
| `logging.central.level` | | str | `INFO` | Minimum level forwarded, independent of `logging.level` |
| `logging.central.queue_size` | | int | `10000` | Bounded sender queue; the oldest record is dropped when full |
| `logging.central.store_key` | | str | `konfig.log_collector` | Secrets store key holding the published collector entry |
| `logging.central.flush_timeout` | | float | `5` | Seconds a sender drains its queue on shutdown |
| `logging.central.include_instance_locally` | | bool | `false` | Also add the `instance` block to local JSON logs |
| `logging.central.max_connections` | | int | `1000` | Collector cap on concurrent sender connections |
| `logging.central.retention_runs` | | int | `10` | Central run directories the collector keeps |
| `logging.central.max_file_size_mb` | | int | `100` | Central stream size before rotation |
| `logging.central.max_files` | | int | `10` | Rotated central stream files kept per run |
| `logging.central.handshake_timeout` | | float | `10` | Seconds the collector waits for TLS and the hello |
| `logging.central.idle_timeout` | | float | `300` | Seconds the collector keeps a silent connection open |

The endpoint, fingerprint and token override is all-or-nothing: if any of the three environment
variables is set, all three must be, otherwise forwarding stays off with a configuration error. The
settings keys are used only when none of the environment variables is set, under the same rule.
Boolean environment values accept `1/true/yes/on` and `0/false/no/off` (case-insensitive); any
other value logs a warning and counts as false.

## Secrets

```yaml
secrets:
  backend: auto                  # auto, keyring, encrypted_file, aws_secrets_manager
  file_path: ~/.konfig/myapp/secrets.enc  # Path for encrypted file backend
  master_key: null               # Master key (prefer KONFIG_MASTER_KEY env var)
  file_lock_timeout: 30          # Seconds to wait for the encrypted file lock
  aws:
    region: us-east-1            # AWS region for Secrets Manager
    prefix: myapp                # Prefix for AWS secret names
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `secrets.backend` | str | Auto-detected | Backend type. If not set, Konfig tries keyring, then encrypted file |
| `secrets.file_path` | str | Platform default | Path to the encrypted secrets file |
| `secrets.master_key` | str | From env/auto | Master key for the encrypted file backend |
| `secrets.file_lock_timeout` | float | `30` | Seconds the encrypted file backend waits for its file lock before raising `TimeoutError` |
| `secrets.aws.region` | str | `us-east-1` | AWS region for Secrets Manager backend |
| `secrets.aws.prefix` | str | `""` | Prefix prepended to all secret names in AWS |

## Environment Variables

These environment variables are recognised by Konfig:

| Variable | Description |
|----------|-------------|
| `KONFIG_MASTER_KEY` | Master key for the encrypted file secrets backend |
| `<PREFIX>__<KEY>` | Settings override (e.g. `MYAPP__DATABASE__HOST`) |
| `KONFIG_LOG_CENTRAL` | Enable centralised log forwarding (sender role) |
| `KONFIG_LOG_COLLECTOR` | Nominate this instance as the log collector |
| `KONFIG_LOG_COLLECTOR_LISTEN` | Collector bind address |
| `KONFIG_LOG_COLLECTOR_ADVERTISE` | Stable collector name published to senders |
| `KONFIG_LOG_ENDPOINT`, `KONFIG_LOG_CERT_SHA256`, `KONFIG_LOG_TOKEN` | Sender override of the discovered collector details (all three or none) |
| `KONFIG_LOG_INSTANCE_LABEL` | Human label attached to this instance's forwarded records |

## Example Complete Config

```yaml
# config.yaml
database:
  host: localhost
  port: 5432
  name: myapp_db
  password: secret://db_password    # Resolved from secrets

server:
  host: 0.0.0.0
  port: 8080
  workers: 4
  debug: false

secrets:
  backend: encrypted_file
  file_path: /etc/myapp/secrets.enc

logging:
  level: INFO
  format: text
  log_dir: /var/log/myapp
  retention_runs: 30
  max_file_size_mb: 100
  max_files_per_run: 5
  console_output: stderr
```
