"""AES-256 encrypted file backend for secret storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets_mod
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from konfig.secrets._filelock import DEFAULT_LOCK_TIMEOUT, FileLock
from konfig.secrets.backend import SecretBackend

logger = logging.getLogger(__name__)

_SALT_SIZE = 16
_KDF_ITERATIONS = 600_000

# File format v2: magic + version + key identifier + salt + Fernet token.
# Legacy (0.4.0 and earlier) files are salt + Fernet token, with no header.
_MAGIC = b"KNFG"
_VERSION_V2 = 0x02
_KEY_ID_SIZE = 8
_KEY_ID_CONTEXT = b"konfig-key-id-v1"
_V2_HEADER_SIZE = len(_MAGIC) + 1 + _KEY_ID_SIZE + _SALT_SIZE
_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR  # 0o600
_BINARY = getattr(os, "O_BINARY", 0)

# (st_ino, st_size, st_mtime_ns, st_ctime_ns) of the data file, or None when
# it is absent. ctime catches same-size rewrites that keep or restore mtime.
_Signature = Optional[tuple[int, int, int, int]]


class EncryptedFileError(RuntimeError):
    """Base class for encrypted file backend errors.

    Messages name the secrets file path but never key material or values.
    """


class MasterKeyMissingError(EncryptedFileError):
    """No master key is available for an existing, non-empty secrets file."""


class MasterKeyMismatchError(EncryptedFileError, InvalidToken):
    """The master key does not match the one the secrets file was written with.

    Also an ``InvalidToken``, so code that caught the bare ``cryptography``
    error raised by earlier versions keeps working.
    """


class SecretsFileCorruptError(EncryptedFileError, InvalidToken):
    """The secrets file is truncated, damaged or in an unknown format."""


def _derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from a master key and salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode("utf-8")))


def _key_id(fernet_key: bytes) -> bytes:
    """Identify a derived key without revealing it (truncated HMAC-SHA256)."""
    raw = base64.urlsafe_b64decode(fernet_key)
    return hmac.new(raw, _KEY_ID_CONTEXT, hashlib.sha256).digest()[:_KEY_ID_SIZE]


def _signature(st: os.stat_result) -> tuple[int, int, int, int]:
    return (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


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
        # Maps salt -> (Fernet key, key identifier).
        self._derived_keys: dict[bytes, tuple[bytes, bytes]] = {}
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

    def _keys_for(self, salt: bytes) -> tuple[bytes, bytes]:
        """Return (Fernet key, key identifier) for ``salt``, deriving at most once."""
        cached = self._derived_keys.get(salt)
        if cached is None:
            fernet_key = _derive_key(self._master_key, salt)
            cached = (fernet_key, _key_id(fernet_key))
            self._derived_keys[salt] = cached
        return cached

    def _mismatch_error(self) -> MasterKeyMismatchError:
        return MasterKeyMismatchError(
            f"The master key does not match the secrets file {self._path}. Every "
            f"process sharing this file must use the same KONFIG_MASTER_KEY."
        )

    def _decode(self, raw: bytes) -> dict[str, str]:
        """Decrypt v2 or legacy file contents, recording the file's salt."""
        if raw.startswith(_MAGIC):
            try:
                salt, plaintext = self._decrypt_v2(raw)
            except EncryptedFileError:
                # A legacy file's random salt can begin with the magic bytes
                # (about 1 in 2**32). Accept it if it decrypts as legacy;
                # otherwise report the v2 problem.
                try:
                    salt, plaintext = self._decrypt_legacy(raw)
                except EncryptedFileError:
                    pass
                else:
                    self._salt = salt
                    return self._parse(plaintext)
                raise
        else:
            salt, plaintext = self._decrypt_legacy(raw)
        self._salt = salt
        return self._parse(plaintext)

    def _decrypt_v2(self, raw: bytes) -> tuple[bytes, bytes]:
        if len(raw) <= _V2_HEADER_SIZE:
            raise SecretsFileCorruptError(
                f"The secrets file {self._path} is truncated or damaged."
            )
        version = raw[len(_MAGIC)]
        if version != _VERSION_V2:
            raise SecretsFileCorruptError(
                f"The secrets file {self._path} uses unsupported format "
                f"version {version}; it may have been written by a newer konfig."
            )
        offset = len(_MAGIC) + 1
        stored_id = raw[offset : offset + _KEY_ID_SIZE]
        salt = raw[offset + _KEY_ID_SIZE : _V2_HEADER_SIZE]
        fernet_key, key_id = self._keys_for(salt)
        if not hmac.compare_digest(stored_id, key_id):
            raise self._mismatch_error()
        try:
            return salt, Fernet(fernet_key).decrypt(raw[_V2_HEADER_SIZE:])
        except InvalidToken:
            raise SecretsFileCorruptError(
                f"The secrets file {self._path} could not be decrypted; it is "
                f"damaged or has been tampered with."
            ) from None

    def _decrypt_legacy(self, raw: bytes) -> tuple[bytes, bytes]:
        salt = raw[:_SALT_SIZE]
        fernet_key, _ = self._keys_for(salt)
        try:
            return salt, Fernet(fernet_key).decrypt(raw[_SALT_SIZE:])
        except InvalidToken:
            # Legacy files carry no key identifier, so a wrong key and damage
            # look the same; the wrong key is far more likely.
            raise self._mismatch_error() from None

    @staticmethod
    def _parse(plaintext: bytes) -> dict[str, str]:
        data: dict[str, str] = json.loads(plaintext.decode("utf-8"))
        return data

    def _encode(self, data: dict[str, str]) -> bytes:
        """Encrypt ``data`` in format v2, keeping the file's salt."""
        fernet_key, key_id = self._keys_for(self._salt)
        token = Fernet(fernet_key).encrypt(json.dumps(data).encode("utf-8"))
        return _MAGIC + bytes([_VERSION_V2]) + key_id + self._salt + token

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

        if not raw.startswith(_MAGIC) and len(raw) < _SALT_SIZE + 1:
            # Empty (or too short to hold a legacy payload): no secrets yet.
            self._data = {}
            self._signature = signature
            return

        self._data = self._decode(raw)
        self._signature = signature

    def _write_file(self, data: dict[str, str]) -> None:
        """Atomically replace the file with ``data``, then adopt it as the cache."""
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        payload = self._encode(data)

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
        self._data = data
        self._signature = _signature(os.stat(self._path))

    def _transact(self, mutate: Callable[[dict[str, str]], bool]) -> None:
        """Run a locked read-modify-write against the file on disk.

        ``mutate`` changes a copy of the freshly loaded data in place and
        returns whether anything changed; the file is rewritten only if it
        did. The cache is updated only once the write has succeeded.
        """
        with self._lock.exclusive():
            self._read_file()
            data = dict(self._data)
            if mutate(data):
                self._write_file(data)

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
