"""Tests for the encrypted file backend."""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from konfig.secrets.encrypted_file import EncryptedFileBackend


class TestEncryptedFileBackend:
    def test_set_and_get(self, tmp_path: Path) -> None:
        backend = EncryptedFileBackend(tmp_path / "secrets.enc", master_key="testkey")
        backend.set("api_key", "sk-abc123")
        assert backend.get("api_key") == "sk-abc123"

    def test_get_missing(self, tmp_path: Path) -> None:
        backend = EncryptedFileBackend(tmp_path / "secrets.enc", master_key="testkey")
        assert backend.get("missing") is None

    def test_has(self, tmp_path: Path) -> None:
        backend = EncryptedFileBackend(tmp_path / "secrets.enc", master_key="testkey")
        assert backend.has("key") is False
        backend.set("key", "value")
        assert backend.has("key") is True

    def test_delete(self, tmp_path: Path) -> None:
        backend = EncryptedFileBackend(tmp_path / "secrets.enc", master_key="testkey")
        backend.set("key", "value")
        backend.delete("key")
        assert backend.has("key") is False

    def test_list_keys(self, tmp_path: Path) -> None:
        backend = EncryptedFileBackend(tmp_path / "secrets.enc", master_key="testkey")
        backend.set("a", "1")
        backend.set("b", "2")
        assert sorted(backend.list_keys()) == ["a", "b"]

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        backend1 = EncryptedFileBackend(path, master_key="testkey")
        backend1.set("key", "persistent_value")

        backend2 = EncryptedFileBackend(path, master_key="testkey")
        assert backend2.get("key") == "persistent_value"

    def test_auto_generate_master_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KONFIG_MASTER_KEY", raising=False)
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path)
        backend.set("key", "value")

        key_file = path.with_suffix(".key")
        assert key_file.exists()

        backend2 = EncryptedFileBackend(path)
        assert backend2.get("key") == "value"

    def test_master_key_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KONFIG_MASTER_KEY", "env-master-key")
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path)
        backend.set("key", "value")

        backend2 = EncryptedFileBackend(path)
        assert backend2.get("key") == "value"

    def test_empty_file_loads_ok(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        path.write_bytes(b"")
        backend = EncryptedFileBackend(path, master_key="testkey")
        assert backend.list_keys() == []

    def test_delete_nonexistent_key(self, tmp_path: Path) -> None:
        backend = EncryptedFileBackend(tmp_path / "secrets.enc", master_key="testkey")
        backend.delete("nonexistent")  # Should not raise


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
class TestFilePermissions:
    def test_encrypted_file_is_owner_only(self, tmp_path: Path) -> None:
        path = tmp_path / "secrets.enc"
        backend = EncryptedFileBackend(path, master_key="testkey")
        backend.set("key", "value")
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_auto_generated_key_file_is_owner_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KONFIG_MASTER_KEY", raising=False)
        path = tmp_path / "secrets.enc"
        EncryptedFileBackend(path)
        key_file = path.with_suffix(".key")
        mode = stat.S_IMODE(key_file.stat().st_mode)
        assert mode == 0o600

    def test_warns_on_permissive_key_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("KONFIG_MASTER_KEY", raising=False)
        path = tmp_path / "secrets.enc"
        key_file = path.with_suffix(".key")
        # Create a key file with overly permissive permissions
        key_file.write_text("dGVzdGtleQ==")
        key_file.chmod(0o644)
        with caplog.at_level("WARNING"):
            EncryptedFileBackend(path)
        assert any("group/other permissions" in msg for msg in caplog.messages)

    def test_warns_on_permissive_secrets_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "secrets.enc"
        # Create a secrets file with overly permissive permissions
        path.write_bytes(b"")
        path.chmod(0o644)
        with caplog.at_level("WARNING"):
            EncryptedFileBackend(path, master_key="testkey")
        assert any("group/other permissions" in msg for msg in caplog.messages)

    def test_warns_on_auto_generated_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("KONFIG_MASTER_KEY", raising=False)
        path = tmp_path / "secrets.enc"
        with caplog.at_level("WARNING"):
            EncryptedFileBackend(path)
        assert any("Auto-generating" in msg for msg in caplog.messages)
