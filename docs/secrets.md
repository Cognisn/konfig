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
- Files written with `0600` permissions (owner-only)

**Master key resolution (in priority order):**

1. Explicit `master_key` parameter
2. `KONFIG_MASTER_KEY` environment variable
3. Auto-generated key written to `<file>.key` (a warning is logged)

```python
from konfig.secrets.encrypted_file import EncryptedFileBackend

# With explicit master key
backend = EncryptedFileBackend("/path/to/secrets.enc", master_key="my-key")

# From environment variable
# export KONFIG_MASTER_KEY="my-key"
backend = EncryptedFileBackend("/path/to/secrets.enc")
```

For production, always supply the master key via the `KONFIG_MASTER_KEY` environment variable rather than relying on auto-generation. The auto-generated key file sits next to the encrypted data, which provides no security against filesystem-level access.

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

## Security Considerations

- **File permissions**: The encrypted file and key file are created with `0600` (owner read/write only) on POSIX systems. If existing files have overly permissive permissions, a warning is logged.
- **Master key storage**: For production, use the `KONFIG_MASTER_KEY` environment variable. Auto-generated key files next to the data provide convenience, not security.
- **In-memory exposure**: Decrypted secrets are held in memory as plain strings for the lifetime of the backend instance.
- **TOML configs**: Secret URIs in TOML files work for reading. However, if you need to persist secrets configuration, use YAML or JSON (TOML writing is not supported).
