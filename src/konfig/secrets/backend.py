"""Abstract interface for secret storage backends."""
from __future__ import annotations

from abc import ABC, abstractmethod


class SecretBackend(ABC):
    """Abstract interface for secret storage backends."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns None if not found."""
        ...

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """Store a secret."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a secret by key."""
        ...

    @abstractmethod
    def has(self, key: str) -> bool:
        """Check if a secret exists."""
        ...

    @abstractmethod
    def list_keys(self) -> list[str]:
        """List all stored secret keys."""
        ...
