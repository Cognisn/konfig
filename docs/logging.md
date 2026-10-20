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

## Centralised Log Forwarding

Optional, and off by default. When many containers (ECS or Fargate tasks, Kubernetes pods, Docker
Compose services) run the same konfig application, each one logs only to its own run directory.
Centralised log forwarding gives you a single place to pull logs from:

- Every instance keeps logging locally **exactly as before**.
- One nominated instance, the **collector**, also receives records forwarded by all the other
  instances (the **senders**) and writes them, tagged with each sender's identity, to one central
  stream on its persistent volume.
- The collector provisions itself. It generates a TLS certificate and an access token and publishes
  the connection details into the **shared konfig secrets store** (the AWS Secrets Manager bundle
  or a shared encrypted file). Senders discover them from the store and start forwarding on their
  own.

Forwarding never slows down, blocks or crashes the application. A missing, slow or dead
collector, a full queue, a TLS failure or a store read error only degrades forwarding, and is
reported in the local log.

### Turning it on

Set one environment variable per container (or the matching `logging.central.*` setting):

| Role | Environment | Setting |
|------|-------------|---------|
| Sender | `KONFIG_LOG_CENTRAL=true` | `logging.central.enabled: true` |
| Collector | `KONFIG_LOG_COLLECTOR=true` | `logging.central.collector: true` |

Nominating the collector implies `enabled`. Nominate **exactly one** instance. If a collector
replaces an entry published by a different host, it logs a warning, because that usually means two
instances were nominated. Boolean values accept `1/true/yes/on` and `0/false/no/off`; any other
value logs a warning and counts as false.

Give the collector a stable name that senders can resolve, because container addresses change on
restart:

```bash
KONFIG_LOG_COLLECTOR=true
KONFIG_LOG_COLLECTOR_ADVERTISE=log-collector:9020   # a service name, not a container IP
KONFIG_LOG_COLLECTOR_LISTEN=0.0.0.0:9020            # the default
```

Without an advertise name, the collector advertises `hostname:port` and logs a warning.

`AppContext` starts and stops forwarding automatically. If you compose the pieces yourself, make
one call after `setup()`:

```python
manager = LogManager.from_settings(settings, app_name="Worker", version="1.0.0")
manager.setup()
manager.start_central_logging(settings, secrets)   # no-op unless enabled; never raises
...
manager.shutdown()   # drains and stops forwarding first, then closes local handlers
```

All the settings are listed in the [Configuration Reference](configuration-reference.md#centralised-log-forwarding).

### What the collector writes

```
<log_dir>/central/
├── state/                      # 0700: collector certificate, private key, token (0600 each)
├── 2026-10-20T09-00-00/
│   ├── central.log             # JSON lines from every instance, including the collector
│   └── central.log.1           # Rotated at logging.central.max_file_size_mb (default 100 MB)
└── latest -> 2026-10-20T09-00-00/
```

Each line is one record plus the sender's `instance` block and a `received_at` timestamp:

```json
{"timestamp": "2026-10-20T09:00:01.120000+00:00", "level": "INFO", "logger": "worker.jobs", "message": "Job 42 done", "pid": 17, "thread": "MainThread", "instance": {"hostname": "a1b2c3", "pid": 17, "app_id": "worker", "app_name": "Worker", "version": "1.0.0", "run_dir": "2026-10-20T08-59-58", "label": "worker-3", "platform": "kubernetes", "kubernetes": {"pod_name": "worker-7d9f", "namespace": "jobs", "node_name": "node-2"}, "peer": "10.0.3.17:51544"}, "received_at": "2026-10-20T09:00:01.123456+00:00"}
```

The collector's own application records go into the same stream, tagged with its own identity, so
the central location holds everything. When a sender's queue overflowed, the stream gets a
`WARNING` line with a `dropped` count, so the gap is visible. Central run directories follow the
same retention as local ones (`logging.central.retention_runs`, default 10).

Records carry `timestamp`, `level`, `logger`, `message`, `pid`, `thread`, and, when present,
`exception` (formatted traceback), `stack` and `extra`. `extra` holds any JSON-serialisable
attributes passed through `extra=`. Very long messages and tracebacks are truncated at 16 KiB.

### Instance identity

Every sender identifies itself once per connection with its hostname, PID, app id, name and
version, run directory name and optional label (`KONFIG_LOG_INSTANCE_LABEL`, for example
`worker-3`), plus platform details:

- **ECS / Fargate**: when `ECS_CONTAINER_METADATA_URI_V4` is set, the task ARN, cluster, container
  name, launch type and availability zone are read from the task metadata endpoint (1-second
  timeout; failures are silent).
- **Kubernetes**: when `KUBERNETES_SERVICE_HOST` is set, the pod name (defaults to the hostname),
  namespace and node name. Expose these with the downward API:

  ```yaml
  env:
    - name: POD_NAME
      valueFrom: {fieldRef: {fieldPath: metadata.name}}
    - name: POD_NAMESPACE
      valueFrom: {fieldRef: {fieldPath: metadata.namespace}}
    - name: NODE_NAME
      valueFrom: {fieldRef: {fieldPath: spec.nodeName}}
  ```

- Otherwise `platform` is `container` (when `/.dockerenv` exists) or `host`.

Set `logging.central.include_instance_locally: true` to add the same `instance` block to local
JSON logs as well. It applies once forwarding has started, so the startup banner is not tagged.

### Discovery and the store entry

The collector publishes one secrets entry, under `logging.central.store_key` (default
`konfig.log_collector`). It is a single JSON string, so it is never read half-written:

```json
{"endpoint": "log-collector:9020", "cert_sha256": "3F:A1:...:9C", "token": "...", "epoch": 7, "collector_host": "a1b2c3", "published_at": "2026-10-20T09:00:00+00:00", "protocol": 1}
```

`epoch` goes up each time the collector starts. The token and certificate are kept in the
collector's state directory and reused across restarts, so senders reconnect without new
credentials. The certificate is regenerated only if it is missing, unreadable, or within 30 days of
expiry.

Senders read the entry on a background thread, never on the application's thread. While it is
absent they poll, backing off from 15 seconds to 5 minutes. Once connected, they re-read it only
after a connection, TLS, pinning or authentication failure, which is how they follow a collector
that has restarted on a new address. A malformed entry is logged once (without its contents) and
treated as absent.

The store must be **shared** between containers: the AWS Secrets Manager bundle
(`KONFIG_AWS_SECRETS_MANAGER`) or an encrypted file on a shared volume with the same
`KONFIG_MASTER_KEY` everywhere (see [Sharing an encrypted file between processes and containers](secrets.md#sharing-an-encrypted-file-between-processes-and-containers)). With the OS
keyring backend, discovery cannot work across containers, and konfig warns.

#### Environment overrides

A sender can skip discovery by being given the details directly. This is useful as a backup, or
when senders cannot read the store:

```bash
KONFIG_LOG_ENDPOINT=log-collector:9020
KONFIG_LOG_CERT_SHA256=3F:A1:...:9C        # colon-separated or plain hex
KONFIG_LOG_TOKEN=secret://log_token        # a literal, or a secret:// reference
```

The three values are **all-or-nothing**. If any one of them is set in the environment, all three
must be. Otherwise konfig logs a configuration error and leaves forwarding off rather than mixing
sources. The same rule applies to the `logging.central.endpoint`, `cert_sha256` and `token`
settings, which are used only when none of the environment variables is set. The collector logs
its endpoint and fingerprint at startup; take the token from its state directory
(`<log_dir>/central/state/collector-token`) or from the store.

### Security model

- **TLS is mandatory**, TLS 1.2 or later. There is no plaintext mode.
- **Pinned self-signed certificate.** The collector generates an EC P-256 certificate (5-year
  validity). Senders do no certificate-authority validation; instead, straight after the TLS
  handshake, they compare the SHA-256 fingerprint of the certificate presented with the pinned
  fingerprint. On a mismatch they close the connection before sending a single byte, so the token
  never reaches an impostor.
- **The private key never leaves the collector.** It lives only in the collector's state directory
  (directory `0700`, files created `0600`).
- **Token authentication.** A sender's first message carries the token. The collector compares it
  in constant time and rejects mismatches. Tokens, private keys and secret values are never logged
  or put in exceptions; the endpoint and fingerprint may be.
- **Whoever can write the store entry controls where logs go.** Anyone who can replace the entry
  can point senders at their own endpoint and certificate. Restrict **write** access to the entry to
  the collector. With AWS Secrets Manager, grant `secretsmanager:PutSecretValue` on the bundle only
  to the collector's task role and, unless senders write application secrets of their own, give
  them `GetSecretValue` only. With a shared encrypted
  file, every holder of the master key can write, so mount the volume read-only into senders where
  your platform allows it.
- **No pickle.** The wire format is newline-delimited UTF-8 JSON with a 256 KiB frame limit. konfig
  never uses `SocketHandler`, `DatagramHandler` or `logging.config.listen`, which unpickle network
  data. Oversized frames, invalid UTF-8 or JSON, an unknown protocol version, a silent handshake
  (10 seconds) or an idle connection (5 minutes) end the connection. Concurrent connections are
  capped (`logging.central.max_connections`, default 1,000).

### Delivery behaviour

Forwarding is best effort: records are delivered at most once, and none is ever duplicated.

- Records wait in a bounded in-memory queue (`logging.central.queue_size`, default 10,000). When it
  is full, the **oldest** record is dropped and counted, and the count is reported centrally once
  the sender reconnects.
- The forwarded level (`logging.central.level`, default `INFO`) is independent of the local level.
  If it is lower, konfig lowers the root logger to it and pins its own local handlers at the local
  level, so local output does not change. Handlers that your application adds to the root logger
  itself will then see the extra records too.
- Records produced by konfig's own forwarding code (`konfig.logging.central.*`) are never forwarded,
  so problems cannot feed back into the queue. They still appear in the local log.
- On shutdown, the sender drains its queue for up to `logging.central.flush_timeout` seconds
  (default 5). If records are left unsent, it logs how many to the local log. If the collector is
  unreachable at shutdown, the drain is skipped.
- Records that are in flight when a collector crashes can be lost. The local logs remain the
  complete record for each instance.

### Persistent storage for the collector

The collector needs a persistent volume at its `logging.log_dir` for two reasons:

- the central stream must survive restarts;
- the `central/state` directory keeps the certificate and token stable, so senders do not have to
  rediscover after every restart.

If you lose the state directory, the collector generates new credentials and republishes, and
senders pick them up after their next connection failure.

### Platform examples

#### Docker Compose

The `MYAPP__...` variables assume `AppContext(env_prefix="MYAPP")`.

```yaml
services:
  log-collector:
    image: my-app:latest
    environment:
      KONFIG_LOG_COLLECTOR: "true"
      KONFIG_LOG_COLLECTOR_ADVERTISE: log-collector:9020
      KONFIG_MASTER_KEY: ${KONFIG_MASTER_KEY}
      MYAPP__LOGGING__LOG_DIR: /var/log/my-app
      MYAPP__SECRETS__BACKEND: encrypted_file
      MYAPP__SECRETS__FILE_PATH: /shared/secrets.enc
    volumes:
      - collector-logs:/var/log/my-app
      - shared-store:/shared

  worker:
    image: my-app:latest
    deploy: {replicas: 3}
    environment:
      KONFIG_LOG_CENTRAL: "true"
      KONFIG_MASTER_KEY: ${KONFIG_MASTER_KEY}
      MYAPP__SECRETS__BACKEND: encrypted_file
      MYAPP__SECRETS__FILE_PATH: /shared/secrets.enc
    volumes:
      - shared-store:/shared

volumes:
  collector-logs:
  shared-store:
```

The central stream is then in the `collector-logs` volume under `central/latest/central.log`.

#### Kubernetes

Run the collector as a single replica with a PersistentVolumeClaim and give it a ClusterIP Service
for its stable name:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata: {name: log-collector}
spec:
  replicas: 1
  serviceName: log-collector
  selector: {matchLabels: {app: log-collector}}
  template:
    metadata: {labels: {app: log-collector}}
    spec:
      containers:
        - name: app
          image: my-app:latest
          ports: [{containerPort: 9020, name: logs}]
          env:
            - {name: KONFIG_LOG_COLLECTOR, value: "true"}
            - {name: KONFIG_LOG_COLLECTOR_ADVERTISE, value: "log-collector.my-namespace.svc:9020"}
            - {name: MYAPP__LOGGING__LOG_DIR, value: /var/log/my-app}
          volumeMounts: [{name: logs, mountPath: /var/log/my-app}]
  volumeClaimTemplates:
    - metadata: {name: logs}
      spec:
        accessModes: [ReadWriteOnce]
        resources: {requests: {storage: 20Gi}}
---
apiVersion: v1
kind: Service
metadata: {name: log-collector}
spec:
  type: ClusterIP
  selector: {app: log-collector}
  ports: [{name: logs, port: 9020, targetPort: logs}]
```

Senders set `KONFIG_LOG_CENTRAL=true` and the downward API variables shown under
[Instance identity](#instance-identity). The shared store is typically the AWS bundle (via IRSA or
Pod Identity) or an encrypted file on a `ReadWriteMany` volume.

#### ECS / Fargate

- Run the collector as its own service with a desired count of **1**.
- Mount an **EFS** access point at its `logging.log_dir` so the central stream and state survive
  task replacement.
- Give it a stable name with **Service Connect** or **Cloud Map** (for example
  `log-collector.internal:9020`) and set `KONFIG_LOG_COLLECTOR_ADVERTISE` to that name.
- Use the AWS Secrets Manager bundle as the shared store (`KONFIG_AWS_SECRETS_MANAGER=<arn>`), and
  restrict `PutSecretValue` on it to the collector's task role where you can (see the
  [security model](#security-model)).
- Senders set `KONFIG_LOG_CENTRAL=true`. Allow TCP 9020 from the senders' security group to the
  collector's.
