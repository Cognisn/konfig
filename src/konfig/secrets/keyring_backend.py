"""OS keyring backend for secret storage."""
from __future__ import annotations

import logging
from typing import Optional

from konfig.secrets.backend import SecretBackend

logger = logging.getLogger(__name__)

_KEYS_ENTRY = "__konfig_keys__"
_KEYS_SEPARATOR = "\n"


class KeyringBackend(SecretBackend):
    """Stores secrets in the OS keyring (macOS Keychain, Windows Credential Locker, etc.).

    Uses the ``keyring`` library for cross-platform support. Tracks known keys
    in a special keyring entry so that ``list_keys()`` works.

    Args:
        service_name: The service/namespace for keyring entries.
    """

    def __init__(self, service_name: str) -> None:
        import keyring as _keyring

        self._keyring = _keyring
        self._service = service_name

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(self._service, key)

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(self._service, key, value)
        self._track_key(key)

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(self._service, key)
        except self._keyring.errors.PasswordDeleteError:
            pass
        self._untrack_key(key)

    def has(self, key: str) -> bool:
        return self._keyring.get_password(self._service, key) is not None

    def list_keys(self) -> list[str]:
        raw = self._keyring.get_password(self._service, _KEYS_ENTRY)
        if not raw:
            return []
        return [k for k in raw.split(_KEYS_SEPARATOR) if k]

    def _track_key(self, key: str) -> None:
        keys = set(self.list_keys())
        keys.add(key)
        self._keyring.set_password(
            self._service, _KEYS_ENTRY, _KEYS_SEPARATOR.join(sorted(keys))
        )

    def _untrack_key(self, key: str) -> None:
        keys = set(self.list_keys())
        keys.discard(key)
        if keys:
            self._keyring.set_password(
                self._service, _KEYS_ENTRY, _KEYS_SEPARATOR.join(sorted(keys))
            )
        else:
            try:
                self._keyring.delete_password(self._service, _KEYS_ENTRY)
            except self._keyring.errors.PasswordDeleteError:
                pass

    @staticmethod
    def is_available() -> bool:
        """Check if a functional keyring backend is available."""
        try:
            import keyring as _keyring
            from keyring.backends.fail import Keyring as FailKeyring

            backend = _keyring.get_keyring()
            return not isinstance(backend, FailKeyring)
        except Exception:
            return False
