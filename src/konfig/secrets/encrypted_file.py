"""AES-256 encrypted file backend for secret storage."""
from __future__ import annotations

import base64
import json
import logging
import os
import stat
import sys
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from konfig.secrets.backend import SecretBackend

logger = logging.getLogger(__name__)

_SALT_SIZE = 16
_KDF_ITERATIONS = 600_000
_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR  # 0o600


def _derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a master key and salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode("utf-8")))


def _restrict_permissions(path: Path) -> None:
    """Set file permissions to owner-only (0600) on POSIX systems."""
    if sys.platform == "win32":
        return
    try:
        path.chmod(_OWNER_ONLY)
    except OSError:
        logger.warning("Could not set restrictive permissions on %s", path)


def _check_permissions(path: Path) -> None:
    """Warn if a sensitive file has overly permissive permissions."""
    if sys.platform == "win32" or not path.exists():
        return
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
            logger.warning(
                "Sensitive file %s has group/other permissions (mode %o). "
                "Run: chmod 600 %s",
                path,
                stat.S_IMODE(mode),
                path,
            )
    except OSError:
        pass


class EncryptedFileBackend(SecretBackend):
    """Stores secrets in an AES-encrypted JSON file.

    The master key is sourced from:
      1. The ``master_key`` parameter
      2. The ``KONFIG_MASTER_KEY`` environment variable
      3. Auto-generated and written to ``<file_path>.key`` (a warning is
         logged because the key file sits next to the data file)

    Args:
        file_path: Path to the encrypted secrets file.
        master_key: Optional master key string.
    """

    def __init__(
        self,
        file_path: Path | str,
        master_key: Optional[str] = None,
    ) -> None:
        self._path = Path(file_path)
        self._master_key = master_key or self._resolve_master_key()
        self._data: dict[str, str] = {}
        self._salt: bytes = os.urandom(_SALT_SIZE)
        _check_permissions(self._path)
        self._load()

    def _resolve_master_key(self) -> str:
        """Resolve master key from env var or auto-generate."""
        env_key = os.environ.get("KONFIG_MASTER_KEY")
        if env_key:
            return env_key

        key_file = self._path.with_suffix(".key")
        if key_file.exists():
            _check_permissions(key_file)
            return key_file.read_text(encoding="utf-8").strip()

        logger.warning(
            "No master key provided and KONFIG_MASTER_KEY is not set. "
            "Auto-generating a key file at %s. For production use, supply a "
            "master key via the KONFIG_MASTER_KEY environment variable instead.",
            key_file,
        )
        generated = Fernet.generate_key().decode("utf-8")
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(generated, encoding="utf-8")
        _restrict_permissions(key_file)
        return generated

    def _load(self) -> None:
        """Load and decrypt secrets from file."""
        if not self._path.exists():
            return

        raw = self._path.read_bytes()
        if len(raw) < _SALT_SIZE + 1:
            return

        self._salt = raw[:_SALT_SIZE]
        encrypted = raw[_SALT_SIZE:]
        key = _derive_key(self._master_key, self._salt)
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted)
        self._data = json.loads(decrypted.decode("utf-8"))

    def _save(self) -> None:
        """Encrypt and write secrets to file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = _derive_key(self._master_key, self._salt)
        fernet = Fernet(key)
        plaintext = json.dumps(self._data).encode("utf-8")
        encrypted = fernet.encrypt(plaintext)
        self._path.write_bytes(self._salt + encrypted)
        _restrict_permissions(self._path)

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._save()

    def has(self, key: str) -> bool:
        return key in self._data

    def list_keys(self) -> list[str]:
        return list(self._data.keys())
