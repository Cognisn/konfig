"""Tests for the Secrets frontend API."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from konfig.secrets.backend import SecretBackend
from konfig.secrets.encrypted_file import EncryptedFileBackend
from konfig.secrets.secrets import Secrets
from konfig.settings.settings import Settings


class InMemoryBackend(SecretBackend):
    """Simple in-memory backend for testing."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._data

    def list_keys(self) -> list[str]:
        return list(self._data.keys())


class TestSecretsAPI:
    def test_set_and_get(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        secrets.set("key", "value")
        assert secrets.get("key") == "value"

    def test_get_missing(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        assert secrets.get("missing") is None

    def test_has(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        assert secrets.has("key") is False
        secrets.set("key", "value")
        assert secrets.has("key") is True

    def test_delete(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        secrets.set("key", "value")
        secrets.delete("key")
        assert secrets.has("key") is False

    def test_list_keys(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        secrets.set("a", "1")
        secrets.set("b", "2")
        assert sorted(secrets.list_keys()) == ["a", "b"]


class TestSecretURIResolution:
    def test_resolve_secret_uri(self) -> None:
        backend = InMemoryBackend()
        backend.set("db_password", "s3cret")
        secrets = Secrets(backend=backend)
        assert secrets.resolve_uri("secret://db_password") == "s3cret"

    def test_resolve_non_uri(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        assert secrets.resolve_uri("plain_value") == "plain_value"

    def test_resolve_missing_secret(self) -> None:
        secrets = Secrets(backend=InMemoryBackend())
        assert secrets.resolve_uri("secret://missing") is None


class TestSecretsAutoDetection:
    def test_explicit_backend(self) -> None:
        backend = InMemoryBackend()
        secrets = Secrets(backend=backend)
        assert secrets._backend is backend

    def test_encrypted_file_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KONFIG_MASTER_KEY", raising=False)
        settings = Settings(defaults={
            "secrets": {
                "backend": "encrypted_file",
                "file_path": str(tmp_path / "secrets.enc"),
                "master_key": "test-master-key",
            }
        })
        secrets = Secrets(service_name="test", settings=settings)
        assert isinstance(secrets._backend, EncryptedFileBackend)
        secrets.set("key", "value")
        assert secrets.get("key") == "value"
