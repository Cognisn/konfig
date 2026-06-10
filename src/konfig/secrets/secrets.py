"""Secrets class — frontend API with auto-detection and secret:// URI resolution."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from konfig.secrets.backend import SecretBackend
from konfig.secrets.encrypted_file import EncryptedFileBackend
from konfig.secrets.keyring_backend import KeyringBackend

if TYPE_CHECKING:
    from konfig.settings.settings import Settings

logger = logging.getLogger(__name__)


class Secrets:
    """Unified secrets API with pluggable backends.

    Backend selection order (highest priority first):
      1. ``KONFIG_AWS_SECRETS_MANAGER`` env var (hard override) — uses the
         designated AWS Secrets Manager secret as a JSON bundle. Wins over an
         explicit ``backend=`` argument and over config.
      2. Explicit backend instance passed as ``backend=``.
      3. Explicit backend from settings (``secrets.backend``).
      4. OS keyring if available.
      5. Encrypted file fallback.

    Args:
        service_name: Namespace for keyring/file storage.
        settings: Optional Settings instance to read backend config from.
        backend: Optional explicit backend instance (overrides auto-detection).
    """

    def __init__(
        self,
        service_name: str = "konfig",
        settings: Optional[Settings] = None,
        backend: Optional[SecretBackend] = None,
    ) -> None:
        self._service_name = service_name
        self._settings = settings

        env_arn = os.environ.get("KONFIG_AWS_SECRETS_MANAGER")
        if env_arn:
            # Hard override: the env var wins over an explicit backend and config.
            self._backend = self._create_bundle_backend(env_arn)
        elif backend is not None:
            self._backend = backend
        else:
            self._backend = self._auto_detect_backend()

    def _auto_detect_backend(self) -> SecretBackend:
        """Select the best available backend."""
        if self._settings:
            configured = self._settings.get("secrets.backend")
            if configured == "aws_secrets_manager":
                return self._create_aws_backend()
            elif configured == "encrypted_file":
                return self._create_encrypted_file_backend()
            elif configured == "keyring":
                return self._create_keyring_backend()

        if KeyringBackend.is_available():
            logger.debug("Using OS keyring backend")
            return KeyringBackend(self._service_name)

        logger.debug("Keyring not available, falling back to encrypted file backend")
        return self._create_encrypted_file_backend()

    def _create_keyring_backend(self) -> KeyringBackend:
        return KeyringBackend(self._service_name)

    def _create_encrypted_file_backend(self) -> EncryptedFileBackend:
        from pathlib import Path

        from konfig.paths import default_secrets_file

        file_path = default_secrets_file(self._service_name)
        if self._settings:
            custom_path = self._settings.get("secrets.file_path")
            if custom_path:
                file_path = Path(custom_path)
        master_key = None
        if self._settings:
            master_key = self._settings.get("secrets.master_key")
        return EncryptedFileBackend(file_path, master_key=master_key)

    def _create_bundle_backend(self, arn: str) -> SecretBackend:
        from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend

        ttl = 300
        if self._settings:
            ttl = self._settings.get("secrets.aws.cache_ttl", 300, cast=int)
        return AWSSecretsBundleBackend(arn=arn, ttl=ttl)

    def _create_aws_backend(self) -> SecretBackend:
        from konfig.secrets.aws_backend import AWSSecretsManagerBackend

        region = "us-east-1"
        prefix = ""
        if self._settings:
            region = self._settings.get("secrets.aws.region", "us-east-1")
            prefix = self._settings.get("secrets.aws.prefix", "")
        return AWSSecretsManagerBackend(region=region, prefix=prefix)

    def get(self, key: str) -> str | None:
        """Retrieve a secret by key."""
        return self._backend.get(key)

    def set(self, key: str, value: str) -> None:
        """Store a secret."""
        self._backend.set(key, value)

    def delete(self, key: str) -> None:
        """Delete a secret by key."""
        self._backend.delete(key)

    def has(self, key: str) -> bool:
        """Check if a secret exists."""
        return self._backend.has(key)

    def list_keys(self) -> list[str]:
        """List all stored secret keys."""
        return self._backend.list_keys()

    def resolve_uri(self, value: str) -> str | None:
        """Resolve a ``secret://`` URI to the actual secret value.

        Args:
            value: A string that may be a ``secret://key`` URI.

        Returns:
            The secret value if the URI is valid, or the original value if not a secret URI.
        """
        if isinstance(value, str) and value.startswith("secret://"):
            secret_key = value[len("secret://") :]
            return self._backend.get(secret_key)
        return value
