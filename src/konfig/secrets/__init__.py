"""Secrets subsystem — pluggable secret storage backends."""
from konfig.secrets.backend import SecretBackend
from konfig.secrets.secrets import Secrets

__all__ = ["SecretBackend", "Secrets"]
