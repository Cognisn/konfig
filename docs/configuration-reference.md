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

## Secrets

```yaml
secrets:
  backend: auto                  # auto, keyring, encrypted_file, aws_secrets_manager
  file_path: ~/.konfig/myapp/secrets.enc  # Path for encrypted file backend
  master_key: null               # Master key (prefer KONFIG_MASTER_KEY env var)
  aws:
    region: us-east-1            # AWS region for Secrets Manager
    prefix: myapp                # Prefix for AWS secret names
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `secrets.backend` | str | Auto-detected | Backend type. If not set, Konfig tries keyring, then encrypted file |
| `secrets.file_path` | str | Platform default | Path to the encrypted secrets file |
| `secrets.master_key` | str | From env/auto | Master key for the encrypted file backend |
| `secrets.aws.region` | str | `us-east-1` | AWS region for Secrets Manager backend |
| `secrets.aws.prefix` | str | `""` | Prefix prepended to all secret names in AWS |

## Environment Variables

These environment variables are recognised by Konfig:

| Variable | Description |
|----------|-------------|
| `KONFIG_MASTER_KEY` | Master key for the encrypted file secrets backend |
| `<PREFIX>__<KEY>` | Settings override (e.g. `MYAPP__DATABASE__HOST`) |

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
