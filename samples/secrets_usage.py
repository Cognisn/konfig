"""Secrets usage — storing and retrieving secrets with the encrypted file backend."""

import tempfile
from pathlib import Path
from konfig import Secrets, Settings

# Use a secure temporary directory for the sample
_sample_dir = Path(tempfile.mkdtemp(prefix="konfig_sample_"))

# Configure to use the encrypted file backend with a known path
settings = Settings(defaults={
    "secrets": {
        "backend": "encrypted_file",
        "file_path": str(_sample_dir / "secrets.enc"),
        "master_key": "sample-master-key-do-not-use-in-production",
    }
})

secrets = Secrets(service_name="sample_app", settings=settings)

# Store secrets
secrets.set("api_key", "sk-abc123456789")
secrets.set("db_password", "super-secret-password")

# Retrieve secrets
print(f"API key: {secrets.get('api_key')}")
print(f"DB password: {secrets.get('db_password')}")

# Check existence
print(f"Has api_key: {secrets.has('api_key')}")
print(f"Has missing: {secrets.has('missing_key')}")

# List all keys
print(f"All keys: {secrets.list_keys()}")

# Resolve secret:// URIs (used for settings integration)
uri = "secret://api_key"
resolved = secrets.resolve_uri(uri)
print(f"Resolved '{uri}' -> {resolved}")

plain = "not-a-secret"
resolved = secrets.resolve_uri(plain)
print(f"Resolved '{plain}' -> {resolved}")

# Delete a secret
secrets.delete("db_password")
print(f"After delete, has db_password: {secrets.has('db_password')}")

# Clean up
import shutil
shutil.rmtree(_sample_dir, ignore_errors=True)

print("\nSecrets are encrypted at rest using AES-256.")
