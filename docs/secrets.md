# Secrets

Konfig's `Secrets` class provides a unified API for storing and retrieving secrets with pluggable backends.

## Basic Usage

```python
from konfig import Secrets

secrets = Secrets(service_name="my_app")

# Store
secrets.set("api_key", "sk-abc123")

# Retrieve
value = secrets.get("api_key")  # Returns str or None

# Check existence
if secrets.has("api_key"):
    ...

# List all keys
keys = secrets.list_keys()

# Delete
secrets.delete("api_key")
```

## Backend Selection

Konfig automatically selects the best available backend:

```
Is OS keyring available and functional?
  YES -> KeyringBackend
  NO  -> Is a master key configured?
          YES -> EncryptedFileBackend
          NO  -> Auto-generate master key -> EncryptedFileBackend
```

You can override this via settings:

```yaml
secrets:
  backend: encrypted_file   # or: keyring, aws_secrets_manager
```

Or by passing an explicit backend:

```python
from konfig.secrets.encrypted_file import EncryptedFileBackend

backend = EncryptedFileBackend("/path/to/secrets.enc", master_key="my-key")
secrets = Secrets(backend=backend)
```

## Backends

### OS Keyring (default)

Uses the `keyring` library for cross-platform OS keyring integration:

- **macOS**: Keychain
- **Windows**: Credential Locker
- **Linux**: Secret Service (GNOME Keyring, KDE Wallet)

```python
secrets = Secrets(service_name="my_app")
# Automatically uses keyring if available
```

### Encrypted File (fallback)

AES-256 encrypted JSON file for environments where the OS keyring is unavailable (e.g. containers, headless servers).

**Encryption details:**
- PBKDF2-HMAC-SHA256 key derivation with 600,000 iterations
- Fernet (AES-128-CBC + HMAC-SHA256) authenticated encryption
- Random 16-byte salt per file
- Files created with `0600` permissions (owner-only) from the moment they exist
- Atomic saves (temporary file, `fsync`, rename), so a crash mid-save never truncates the file
- File format v2 carries a short key identifier, so a wrong master key is reported clearly
  instead of as a bare decryption failure. Files written by konfig 0.4.0 and earlier load
  unchanged and are upgraded to v2 on their next write.

**Master key resolution (in priority order):**

1. Explicit `master_key` parameter
2. `KONFIG_MASTER_KEY` environment variable
3. An existing `<file>.key` key file
4. Auto-generated key written to `<file>.key` (a warning is logged), but only when the
   secrets file does not exist yet. If the secrets file already has content and no key is
   available, `MasterKeyMissingError` is raised and no key file is written.

Opening a file with the wrong master key raises `MasterKeyMismatchError`; a damaged or
truncated file raises `SecretsFileCorruptError`. Both name the file path but never key
material, and both are subclasses of `EncryptedFileError` (importable from `konfig.secrets`)
and of `cryptography.fernet.InvalidToken`, so handlers written for earlier versions still work.

```python
from konfig.secrets.encrypted_file import EncryptedFileBackend

# With explicit master key
backend = EncryptedFileBackend("/path/to/secrets.enc", master_key="my-key")

# From environment variable
# export KONFIG_MASTER_KEY="my-key"
backend = EncryptedFileBackend("/path/to/secrets.enc")
```

For production, always supply the master key via the `KONFIG_MASTER_KEY` environment variable rather than relying on auto-generation. The auto-generated key file sits next to the encrypted data, which provides no security against filesystem-level access.

#### Sharing an encrypted file between processes and containers

Many processes and containers can read and write the same encrypted file on a shared mount
(for example a Docker named volume, Amazon EFS or a Kubernetes persistent volume claim).

- **Use the same master key everywhere.** Every process must use the same `KONFIG_MASTER_KEY`.
  Do not rely on an auto-generated key file for a shared store. A process with a different key
  gets `MasterKeyMismatchError` and never overwrites the file.
- **Run as the same user.** Files are created owner-only (`0600`), so every process must run as
  the user (UID) that owns them, or be able to read and write files owned by it.
- **Writes are locked read-modify-write transactions.** `set()` and `delete()` take an exclusive
  lock, re-read the file from disk, apply only their own change and save atomically. Processes
  writing different keys never lose each other's changes; for the same key the last writer wins.
- **Reads see other processes' writes.** `get()`, `has()` and `list_keys()` check the file's
  inode, size and modification time and reload when it has changed. On NFS-backed storage
  (including Amazon EFS) the client attribute cache can delay that check from noticing another
  host's write for a few seconds. Taking the lock forces revalidation, so call `refresh()` (or
  `Secrets.refresh()`) when you must see another host's very latest write, for example for
  service discovery. Every write already does this.
- **The lock file.** Locking uses a sidecar `<file>.lock` (for example `secrets.enc.lock`) in the
  same directory. It is created on first use and is never deleted; do not delete it while the
  store is in use. Lock waits are bounded by `secrets.file_lock_timeout` (default 30 seconds),
  after which a `TimeoutError` naming the file is raised.
- **Locks are advisory.** They coordinate konfig processes only. Anything else that edits the
  file directly is not excluded.

Supported storage:

- Local filesystems on Linux, macOS and Windows
- Docker named volumes on a Linux host
- Amazon EFS and other NFSv4 storage (POSIX record locks via `fcntl.lockf`, which NFS honours)
- Kubernetes persistent volume claims backed by NFS or EFS

Unsupported or not guaranteed:

- Docker Desktop bind mounts on macOS or Windows (the file-sharing layer does not reliably
  propagate locks between the host and containers)
- SMB/CIFS shares
- Mixing processes on different operating systems against one file (Windows and POSIX locks
  do not interoperate)

On Windows, `msvcrt` has no shared lock mode, so reads and writes both take an exclusive lock.
A reader whose directory is read-only and has no lock file reads without a lock.

### AWS Secrets Manager (optional)

Requires the `aws` extra: `pip install konfig[aws]`

```yaml
secrets:
  backend: aws_secrets_manager
  aws:
    region: eu-west-1
    prefix: myapp          # Optional: prefixes all secret names
```

```python
from konfig.secrets.aws_backend import AWSSecretsManagerBackend

backend = AWSSecretsManagerBackend(region="eu-west-1", prefix="myapp")
secrets = Secrets(backend=backend)
```

## Secret References in Settings

Use `secret://` URIs in config files to reference secrets:

```yaml
database:
  host: localhost
  password: secret://db_password
```

Resolve them using `Secrets.resolve_uri()`:

```python
raw_value = settings.get("database.password")
# raw_value == "secret://db_password"

password = secrets.resolve_uri(raw_value)
# password == the actual secret value, or None if not found
```

Non-secret values pass through unchanged:

```python
secrets.resolve_uri("plain_value")  # Returns "plain_value"
```

## Custom Backends

Implement the `SecretBackend` abstract interface:

```python
from konfig.secrets.backend import SecretBackend

class VaultBackend(SecretBackend):
    def __init__(self, vault_url: str, token: str) -> None:
        self._client = VaultClient(vault_url, token)

    def get(self, key: str) -> str | None:
        return self._client.read(key)

    def set(self, key: str, value: str) -> None:
        self._client.write(key, value)

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def has(self, key: str) -> bool:
        return self._client.read(key) is not None

    def list_keys(self) -> list[str]:
        return self._client.list()

# Use it
secrets = Secrets(backend=VaultBackend("https://vault.example.com", "hvs.xxx"))
```

`SecretBackend` also provides a non-abstract `refresh()` that does nothing by default.
Override it if your backend caches reads, so `Secrets.refresh()` can discard the cache.

## Security Considerations

- **File permissions**: The encrypted file, key file and lock file are created with `0600` (owner read/write only) on POSIX systems, with no window in which they are more permissive. If existing files have overly permissive permissions, a warning is logged, and the secrets file is tightened to `0600` on its next write.
- **Master key storage**: For production, use the `KONFIG_MASTER_KEY` environment variable. Auto-generated key files next to the data provide convenience, not security.
- **In-memory exposure**: Decrypted secrets are held in memory as plain strings for the lifetime of the backend instance.
- **TOML configs**: Secret URIs in TOML files work for reading. However, if you need to persist secrets configuration, use YAML or JSON (TOML writing is not supported).
