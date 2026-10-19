"""AES-256 encrypted file backend for secret storage."""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets as _secrets_mod
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from konfig.secrets._filelock import DEFAULT_LOCK_TIMEOUT, FileLock
from konfig.secrets.backend import SecretBackend

logger = logging.getLogger(__name__)

_SALT_SIZE = 16
_KDF_ITERATIONS = 600_000
_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR  # 0o600
_BINARY = getattr(os, "O_BINARY", 0)

# (st_ino, st_size, st_mtime_ns) of the data file, or None when it is absent.
_Signature = Optional[tuple[int, int, int]]


class EncryptedFileError(RuntimeError):
    """Base class for encrypted file backend errors.

    Messages name the secrets file path but never key material or values.
    """


class MasterKeyMissingError(EncryptedFileError):
    """No master key is available for an existing, non-empty secrets file."""


def _derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a master key and salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode("utf-8")))


def _signature(st: os.stat_result) -> tuple[int, int, int]:
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _create_owner_only(path: Path, data: bytes) -> None:
    """Create ``path`` exclusively with mode 0600 and write ``data`` durably.

    The mode is applied at creation, so the file is never readable by others,
    even briefly. Raises ``FileExistsError`` if ``path`` already exists.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _BINARY, _OWNER_ONLY)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry change to disk where the platform supports it."""
    if sys.platform == "win32":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


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

    The file may be shared by many processes and containers. Every write is
    a read-modify-write transaction under an exclusive lock on the sidecar
    ``<file_path>.lock`` file, and is saved atomically (temporary file, then
    rename). Reads notice when another process has changed the file and
    reload it. On NFS-backed storage the client attribute cache can delay
    that notice; call ``refresh()`` when the very latest write from another
    host must be seen.

    Args:
        file_path: Path to the encrypted secrets file.
        master_key: Optional master key string.
        lock_timeout: Seconds to wait for the file lock before raising
            ``TimeoutError``.
    """

    def __init__(
        self,
        file_path: Path | str,
        master_key: Optional[str] = None,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        self._path = Path(file_path)
        self._lock = FileLock(
            self._path.with_name(self._path.name + ".lock"),
            timeout=lock_timeout,
            label=self._path,
        )
        self._master_key = master_key or self._resolve_master_key()
        self._data: dict[str, str] = {}
        self._salt: bytes = os.urandom(_SALT_SIZE)
        self._signature: _Signature = None
        # PBKDF2 is deliberately slow; derive once per file salt, not per I/O.
        self._derived_keys: dict[bytes, bytes] = {}
        _check_permissions(self._path)
        self.refresh()

    def _resolve_master_key(self) -> str:
        """Resolve master key from env var or auto-generate."""
        env_key = os.environ.get("KONFIG_MASTER_KEY")
        if env_key:
            return env_key

        key_file = self._path.with_suffix(".key")
        if key_file.exists():
            return self._read_key_file(key_file)

        # Decide and generate under the exclusive lock, so processes racing
        # on first boot settle on a single key file.
        with self._lock.exclusive():
            if key_file.exists():
                return self._read_key_file(key_file)
            if self._data_file_has_content():
                raise MasterKeyMissingError(
                    f"No master key is available for the existing secrets file "
                    f"{self._path}. Set KONFIG_MASTER_KEY (or pass master_key) to "
                    f"the key it was encrypted with; no key file was generated."
                )
            logger.warning(
                "No master key provided and KONFIG_MASTER_KEY is not set. "
                "Auto-generating a key file at %s. For production use, supply a "
                "master key via the KONFIG_MASTER_KEY environment variable instead.",
                key_file,
            )
            generated = Fernet.generate_key().decode("utf-8")
            key_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                _create_owner_only(key_file, generated.encode("utf-8"))
            except FileExistsError:
                # Created meanwhile by a process not using the lock.
                return self._read_key_file(key_file)
            return generated

    @staticmethod
    def _read_key_file(key_file: Path) -> str:
        _check_permissions(key_file)
        return key_file.read_text(encoding="utf-8").strip()

    def _data_file_has_content(self) -> bool:
        try:
            return self._path.stat().st_size > 0
        except FileNotFoundError:
            return False

    def _fernet(self, salt: bytes) -> Fernet:
        """Return a Fernet for ``salt``, deriving its key at most once."""
        key = self._derived_keys.get(salt)
        if key is None:
            key = _derive_key(self._master_key, salt)
            self._derived_keys[salt] = key
        return Fernet(key)

    # -- file I/O (callers hold the lock) ------------------------------------

    def _read_file(self) -> None:
        """Load and decrypt the file into the cache, recording its signature."""
        try:
            with open(self._path, "rb") as handle:
                signature: _Signature = _signature(os.fstat(handle.fileno()))
                raw = handle.read()
        except FileNotFoundError:
            self._data = {}
            self._signature = None
            return

        if len(raw) < _SALT_SIZE + 1:
            self._data = {}
            self._signature = signature
            return

        self._salt = raw[:_SALT_SIZE]
        encrypted = raw[_SALT_SIZE:]
        fernet = self._fernet(self._salt)
        decrypted = fernet.decrypt(encrypted)
        self._data = json.loads(decrypted.decode("utf-8"))
        self._signature = signature

    def _write_file(self) -> None:
        """Encrypt the cache and atomically replace the file with it."""
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fernet = self._fernet(self._salt)
        plaintext = json.dumps(self._data).encode("utf-8")
        payload = self._salt + fernet.encrypt(plaintext)

        tmp = directory / f".{self._path.name}.{_secrets_mod.token_hex(8)}.tmp"
        try:
            _create_owner_only(tmp, payload)
            os.replace(tmp, self._path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        _fsync_directory(directory)
        self._signature = _signature(os.stat(self._path))

    def _transact(self, mutate: Callable[[dict[str, str]], bool]) -> None:
        """Run a locked read-modify-write against the file on disk.

        ``mutate`` changes the freshly loaded data in place and returns
        whether anything changed; the file is rewritten only if it did.
        """
        with self._lock.exclusive():
            self._read_file()
            if mutate(self._data):
                self._write_file()

    def _ensure_fresh(self) -> None:
        """Reload if the file has changed since it was last read or written."""
        try:
            current: _Signature = _signature(os.stat(self._path))
        except FileNotFoundError:
            current = None
        if current != self._signature:
            self.refresh()

    # -- SecretBackend API ---------------------------------------------------

    def refresh(self) -> None:
        """Unconditionally reload the file from disk under a shared lock.

        Taking the lock also makes NFS clients (including Amazon EFS)
        revalidate their cached view of the file, so this sees the latest
        write from any host.
        """
        with self._lock.shared():
            self._read_file()

    def get(self, key: str) -> str | None:
        with self._lock.thread_guard():
            self._ensure_fresh()
            return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        def apply(data: dict[str, str]) -> bool:
            data[key] = value
            return True

        self._transact(apply)

    def delete(self, key: str) -> None:
        def apply(data: dict[str, str]) -> bool:
            return data.pop(key, None) is not None

        self._transact(apply)

    def has(self, key: str) -> bool:
        with self._lock.thread_guard():
            self._ensure_fresh()
            return key in self._data

    def list_keys(self) -> list[str]:
        with self._lock.thread_guard():
            self._ensure_fresh()
            return list(self._data.keys())
