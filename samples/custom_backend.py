"""Custom secret backend — implementing a simple in-memory backend."""

from konfig import Secrets
from konfig.secrets.backend import SecretBackend


class InMemoryBackend(SecretBackend):
    """A simple in-memory secret backend for demonstration.

    Secrets are lost when the process exits. Useful for testing or
    environments where persistence is handled elsewhere.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def has(self, key: str) -> bool:
        return key in self._store

    def list_keys(self) -> list[str]:
        return list(self._store.keys())


# Use the custom backend with the Secrets API
backend = InMemoryBackend()
secrets = Secrets(backend=backend)

secrets.set("token", "my-secret-token")
print(f"Token: {secrets.get('token')}")
print(f"Keys: {secrets.list_keys()}")

secrets.delete("token")
print(f"After delete: {secrets.get('token')}")
print(f"Keys: {secrets.list_keys()}")
