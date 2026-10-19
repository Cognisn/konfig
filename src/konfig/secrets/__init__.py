"""Secrets subsystem — pluggable secret storage backends."""

from konfig.secrets.backend import SecretBackend
from konfig.secrets.encrypted_file import (
    EncryptedFileError,
    MasterKeyMismatchError,
    MasterKeyMissingError,
    SecretsFileCorruptError,
)
from konfig.secrets.secrets import Secrets

__all__ = [
    "EncryptedFileError",
    "MasterKeyMismatchError",
    "MasterKeyMissingError",
    "SecretBackend",
    "Secrets",
    "SecretsFileCorruptError",
]
