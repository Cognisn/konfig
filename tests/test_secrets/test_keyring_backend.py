"""Tests for the keyring backend (mocked)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from konfig.secrets.keyring_backend import KeyringBackend, _KEYS_ENTRY


class MockKeyring:
    """In-memory mock of the keyring module."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self.errors = MagicMock()
        self.errors.PasswordDeleteError = KeyError

    def get_password(self, service: str, key: str) -> str | None:
        return self._store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self._store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        if (service, key) not in self._store:
            raise KeyError(key)
        del self._store[(service, key)]


@pytest.fixture
def keyring_backend() -> KeyringBackend:
    mock = MockKeyring()
    backend = KeyringBackend.__new__(KeyringBackend)
    backend._keyring = mock  # type: ignore[attr-defined]
    backend._service = "test_service"
    return backend


class TestKeyringBackend:
    def test_set_and_get(self, keyring_backend: KeyringBackend) -> None:
        keyring_backend.set("api_key", "sk-123")
        assert keyring_backend.get("api_key") == "sk-123"

    def test_get_missing(self, keyring_backend: KeyringBackend) -> None:
        assert keyring_backend.get("missing") is None

    def test_has(self, keyring_backend: KeyringBackend) -> None:
        assert keyring_backend.has("key") is False
        keyring_backend.set("key", "value")
        assert keyring_backend.has("key") is True

    def test_delete(self, keyring_backend: KeyringBackend) -> None:
        keyring_backend.set("key", "value")
        keyring_backend.delete("key")
        assert keyring_backend.has("key") is False

    def test_delete_nonexistent(self, keyring_backend: KeyringBackend) -> None:
        keyring_backend.delete("missing")  # Should not raise

    def test_list_keys(self, keyring_backend: KeyringBackend) -> None:
        keyring_backend.set("a", "1")
        keyring_backend.set("b", "2")
        assert sorted(keyring_backend.list_keys()) == ["a", "b"]

    def test_list_keys_empty(self, keyring_backend: KeyringBackend) -> None:
        assert keyring_backend.list_keys() == []

    def test_delete_untracks_key(self, keyring_backend: KeyringBackend) -> None:
        keyring_backend.set("key", "value")
        keyring_backend.delete("key")
        assert "key" not in keyring_backend.list_keys()
