"""AWS Secrets Manager settings layer (optional, requires konfig[aws]).

Loads an application's settings tree from a single Secrets Manager secret
whose ``SecretString`` is a JSON object. Selected via the
``KONFIG_AWS_SETTINGS`` environment variable or ``Settings(aws_settings=...)``.

Unlike the graceful system config file, this layer is an explicit opt-in
carrying load-bearing configuration. Missing secrets, unreadable secrets,
non-JSON payloads, and non-object top level all raise immediately at
construction. Empty payloads (empty/whitespace SecretString or bare ``{}``)
trigger first-boot seeding of the defaults tree (gated by ``KONFIG_AWS_SEED``),
then continue with an empty layer so reads fall through to defaults.
Error messages name the secret but never echo its payload.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from konfig._aws import parse_region, seeding_enabled
from konfig.settings.layers import _get_nested, _get_section

logger = logging.getLogger(__name__)


class AwsSettingsLayer:
    """Read-only settings layer backed by one AWS Secrets Manager secret.

    Args:
        source: Secret ARN or name. If None, the layer is inert and empty
            (mirrors ``FileLayer`` with no path) and boto3 is never imported.
        client: Optional pre-built boto3 client (for testing/injection).
        defaults: Optional dict of default settings. On first boot (empty store),
            this tree is seeded as a template to the secret when
            KONFIG_AWS_SEED is enabled.
    """

    def __init__(
        self,
        source: Optional[str] = None,
        client: object | None = None,
        defaults: Optional[dict[str, Any]] = None,
    ) -> None:
        self._source = source
        self._defaults: dict[str, Any] = defaults or {}
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

        On first boot (empty payload), the layer seeds the store with the
        defaults tree when KONFIG_AWS_SEED is enabled, then continues with
        an empty layer so reads fall through to the defaults layer.
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
        if not raw.strip():
            self._seed_empty_store()
            return
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
        if not data:
            self._seed_empty_store()
            return
        self._data = data

    def _seed_empty_store(self) -> None:
        """First-boot path: the store exists but its payload is empty.

        Writes the application's defaults tree as pretty-printed JSON, giving
        the operator a template to edit, then continues with an empty layer —
        reads fall through to the defaults layer, so behaviour is identical
        to the layer being absent. Concurrent replicas racing this write are
        benign: every writer writes the identical defaults tree. Never runs
        for a non-empty payload, and a failed write only warns.
        """
        self._data = {}
        if not seeding_enabled():
            logger.info(
                "AWS settings secret %s is empty; seeding disabled by KONFIG_AWS_SEED",
                self._source,
            )
            return
        if not self._defaults:
            logger.info(
                "AWS settings secret %s is empty and no defaults are configured; "
                "nothing to seed",
                self._source,
            )
            return
        try:
            document = json.dumps(self._defaults, indent=2, sort_keys=True)
            self._client.put_secret_value(SecretId=self._source, SecretString=document)
        except Exception as exc:
            logger.warning(
                "Could not seed AWS settings secret %s with default settings "
                "(continuing with defaults): %s",
                self._source,
                exc,
            )
            return
        logger.warning(
            "Seeded empty AWS settings secret %s with the application's default "
            "settings; review and edit the document, then restart",
            self._source,
        )

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
