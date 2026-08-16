"""AWS Secrets Manager settings layer (optional, requires konfig[aws]).

Loads an application's settings tree from a single Secrets Manager secret
whose ``SecretString`` is a JSON object. Selected via the
``KONFIG_AWS_SETTINGS`` environment variable or ``Settings(aws_settings=...)``.

Unlike the graceful system config file, this layer is an explicit opt-in
carrying load-bearing configuration, so every failure mode (missing secret,
unreadable secret, non-JSON payload, non-object top level) raises immediately
at construction rather than silently degrading to defaults. Error messages
name the secret but never echo its payload.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from konfig._aws import parse_region
from konfig.settings.layers import _get_nested, _get_section

logger = logging.getLogger(__name__)


class AwsSettingsLayer:
    """Read-only settings layer backed by one AWS Secrets Manager secret.

    Args:
        source: Secret ARN or name. If None, the layer is inert and empty
            (mirrors ``FileLayer`` with no path) and boto3 is never imported.
        client: Optional pre-built boto3 client (for testing/injection).
    """

    def __init__(
        self,
        source: Optional[str] = None,
        client: object | None = None,
    ) -> None:
        self._source = source
        self._data: dict[str, Any] = {}
        self._client: Any = None
        if self._source:
            self._client = client if client is not None else self._create_client()
            self.reload()

    def _create_client(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager settings layer "
                "(KONFIG_AWS_SETTINGS). Install it with: pip install konfig[aws]"
            ) from exc
        assert self._source is not None
        # Region from the ARN when one is given; otherwise the default
        # provider chain decides (matches the secrets bundle behaviour).
        region = parse_region(self._source) if self._source.startswith("arn:") else None
        return boto3.client("secretsmanager", region_name=region)

    def reload(self) -> None:
        """Re-fetch the settings document from AWS.

        Raises:
            RuntimeError: If the secret is missing, unreadable, or any other
                exception occurs during fetch (botocore errors, credential issues, etc).
            ValueError: If the payload is binary-only, not valid JSON, or
                not a JSON object at the top level.
        """
        if not self._source:
            return
        logger.debug("Fetching AWS settings secret %s", self._source)
        try:
            response = self._client.get_secret_value(SecretId=self._source)
        except Exception as exc:
            # Covers ClientError subclasses (ResourceNotFoundException, AccessDenied),
            # as well as botocore failures (NoCredentialsError, EndpointConnectionError).
            # The message names the secret; there is no payload to leak here.
            raise RuntimeError(
                f"Cannot read AWS settings secret {self._source!r}: {exc}"
            ) from exc
        raw = response.get("SecretString")
        if raw is None:
            raise ValueError(
                f"AWS settings secret {self._source!r} has no SecretString "
                "(binary secrets are not supported)"
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Deliberately excludes the payload from the message.
            raise ValueError(
                f"AWS settings secret {self._source!r} is not valid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"AWS settings secret {self._source!r} must be a JSON object "
                "at the top level"
            )
        self._data = data

    def get(self, key: str) -> Any:
        return _get_nested(self._data, key)

    def get_section(self, prefix: str) -> dict[str, Any]:
        return _get_section(self._data, prefix)

    @property
    def source(self) -> Optional[str]:
        """The secret ARN or name, or None when the layer is inert."""
        return self._source

    @property
    def data(self) -> dict[str, Any]:
        return self._data
