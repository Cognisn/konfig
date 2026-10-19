"""File format, legacy compatibility and key handling for the encrypted file backend."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import konfig.secrets.encrypted_file as encrypted_file
from konfig.secrets import (
    EncryptedFileError,
    MasterKeyMismatchError,
    SecretsFileCorruptError,
)
from konfig.secrets.encrypted_file import EncryptedFileBackend

MASTER_KEY = "format-test-master-key"
WRONG_KEY = "some-other-master-key"


def _legacy_fernet_key(master_key: str, salt: bytes) -> bytes:
    """The 0.4.0 key derivation, reimplemented independently of the backend."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode("utf-8")))


def _write_legacy_file(
    path: Path, data: dict[str, str], master_key: str, salt: bytes | None = None
) -> bytes:
    """Write a file in the exact 0.4.0 format: 16-byte salt + Fernet token."""
    salt = salt if salt is not None else os.urandom(16)
    token = Fernet(_legacy_fernet_key(master_key, salt)).encrypt(
        json.dumps(data).encode("utf-8")
    )
    path.write_bytes(salt + token)
    return salt


def _assert_no_key_material(message: str) -> None:
    assert MASTER_KEY not in message
    assert WRONG_KEY not in message


class TestFormatV2:
    def test_new_files_use_v2_header_with_key_identifier(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        EncryptedFileBackend(path, master_key=MASTER_KEY).set("key", "value")
        raw = path.read_bytes()

        assert raw[:4] == b"KNFG"
        assert raw[4] == 0x02
        key_id, salt, token = raw[5:13], raw[13:29], raw[29:]
        fernet_key = _legacy_fernet_key(MASTER_KEY, salt)
        expected_id = hmac.new(
            base64.urlsafe_b64decode(fernet_key), b"konfig-key-id-v1", hashlib.sha256
        ).digest()[:8]
        assert key_id == expected_id
        assert json.loads(Fernet(fernet_key).decrypt(token)) == {"key": "value"}

    def test_salt_is_preserved_across_saves(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        backend.set("a", "1")
        salt = path.read_bytes()[13:29]
        backend.set("b", "2")
        assert path.read_bytes()[13:29] == salt


class TestLegacyCompatibility:
    def test_legacy_file_loads_unchanged_and_upgrades_on_write(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "secrets.enc"
        salt = _write_legacy_file(path, {"api_key": "sk-legacy"}, MASTER_KEY)
        original = path.read_bytes()

        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert backend.get("api_key") == "sk-legacy"
        assert backend.list_keys() == ["api_key"]
        backend.refresh()
        assert path.read_bytes() == original  # reads never rewrite

        backend.set("new_key", "new")
        raw = path.read_bytes()
        assert raw[:5] == b"KNFG\x02"
        assert raw[13:29] == salt  # legacy salt carried into v2

        reopened = EncryptedFileBackend(path, master_key=MASTER_KEY)
        assert reopened.get("api_key") == "sk-legacy"
        assert reopened.get("new_key") == "new"

    def test_legacy_file_whose_salt_starts_with_magic(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        _write_legacy_file(
            path, {"key": "value"}, MASTER_KEY, salt=b"KNFG" + os.urandom(12)
        )
        assert EncryptedFileBackend(path, master_key=MASTER_KEY).get("key") == "value"


class TestWrongKey:
    def test_v2_file_with_wrong_key(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        EncryptedFileBackend(path, master_key=MASTER_KEY).set("key", "secret-value")

        with pytest.raises(MasterKeyMismatchError) as excinfo:
            EncryptedFileBackend(path, master_key=WRONG_KEY)
        message = str(excinfo.value)
        assert str(path) in message
        assert "does not match" in message
        _assert_no_key_material(message)
        assert "secret-value" not in message

    def test_legacy_file_with_wrong_key(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        _write_legacy_file(path, {"key": "secret-value"}, MASTER_KEY)

        with pytest.raises(MasterKeyMismatchError) as excinfo:
            EncryptedFileBackend(path, master_key=WRONG_KEY)
        message = str(excinfo.value)
        assert str(path) in message
        _assert_no_key_material(message)

    def test_mismatch_is_still_an_invalid_token(self, tmp_path: Path) -> None:
        # Callers that caught cryptography's InvalidToken in 0.4.0 keep working.
        path = tmp_path / "secrets.enc"
        EncryptedFileBackend(path, master_key=MASTER_KEY).set("key", "value")
        with pytest.raises(InvalidToken):
            EncryptedFileBackend(path, master_key=WRONG_KEY)

    def test_wrong_key_writer_does_not_clobber_file(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        # Opened before the file exists, so construction cannot detect the
        # mismatch; its first write must fail rather than overwrite.
        late = EncryptedFileBackend(path, master_key=WRONG_KEY)
        EncryptedFileBackend(path, master_key=MASTER_KEY).set("key", "value")
        before = path.read_bytes()
        with pytest.raises(MasterKeyMismatchError):
            late.set("key", "clobbered")
        assert path.read_bytes() == before


class TestCorruption:
    def _v2_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "secrets.enc"
        EncryptedFileBackend(path, master_key=MASTER_KEY).set("key", "value")
        return path

    def test_damaged_token(self, tmp_path: Path) -> None:
        path = self._v2_file(tmp_path)
        raw = bytearray(path.read_bytes())
        raw[-5] ^= 0xFF
        path.write_bytes(bytes(raw))
        with pytest.raises(SecretsFileCorruptError, match="damaged"):
            EncryptedFileBackend(path, master_key=MASTER_KEY)

    def test_truncated_header(self, tmp_path: Path) -> None:
        path = self._v2_file(tmp_path)
        path.write_bytes(path.read_bytes()[:20])
        with pytest.raises(EncryptedFileError, match="truncated"):
            EncryptedFileBackend(path, master_key=MASTER_KEY)

    def test_unsupported_version(self, tmp_path: Path) -> None:
        path = self._v2_file(tmp_path)
        raw = bytearray(path.read_bytes())
        raw[4] = 0x09
        path.write_bytes(bytes(raw))
        with pytest.raises(SecretsFileCorruptError, match="version 9"):
            EncryptedFileBackend(path, master_key=MASTER_KEY)


class TestDerivedKeyCaching:
    def test_derivation_runs_once_per_file_salt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bytes] = []
        real = encrypted_file._derive_key

        def spy(master_key: str, salt: bytes) -> bytes:
            calls.append(salt)
            return real(master_key, salt)

        monkeypatch.setattr(encrypted_file, "_derive_key", spy)
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key=MASTER_KEY)
        backend.set("a", "1")
        backend.set("b", "2")
        backend.delete("a")
        for _ in range(3):
            backend.refresh()
            backend.get("b")
            backend.list_keys()
        assert len(calls) == 1

    def test_reload_after_other_writer_reuses_cached_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "secrets.enc"
        writer = EncryptedFileBackend(path, master_key=MASTER_KEY)
        writer.set("a", "1")
        reader = EncryptedFileBackend(path, master_key=MASTER_KEY)

        calls: list[bytes] = []
        real = encrypted_file._derive_key
        monkeypatch.setattr(
            encrypted_file,
            "_derive_key",
            lambda key, salt: calls.append(salt) or real(key, salt),
        )
        for i in range(3):
            writer.set("a", str(i))
            assert reader.get("a") == str(i)
        assert calls == []
