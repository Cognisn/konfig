"""AWS Secrets Manager single-secret JSON bundle backend (optional)."""
from __future__ import annotations

import json
import time
from typing import Callable

from konfig.secrets.backend import SecretBackend

_NOT_JSON_OBJECT = "Designated AWS secret is not a JSON object."
_NO_SECRET_STRING = (
    "Designated AWS secret has no SecretString (binary secrets are not supported)."
)


def _parse_region(arn: str) -> str:
    """Extract the region from a Secrets Manager ARN.

    ARN shape: ``arn:aws:secretsmanager:<region>:<account>:secret:<name>``.
    """
    parts = arn.split(":")
    if (
        len(parts) < 6
        or parts[0] != "arn"
        or parts[2] != "secretsmanager"
        or not parts[3]
    ):
        raise ValueError(f"Invalid AWS Secrets Manager ARN: {arn!r}")
    return parts[3]


class AWSSecretsBundleBackend(SecretBackend):
    """Reads and writes secrets to a single AWS secret holding a JSON bundle.

    The secret named by ``arn`` stores a JSON object; each konfig key is a key
    within that object. Requires ``boto3`` (``pip install konfig[aws]``).

    Args:
        arn: Full ARN of the designated AWS secret.
        ttl: Read-cache time-to-live in seconds.
        client: Optional pre-built boto3 client (for testing/injection).
        time_func: Monotonic time source (for testing).
    """

    def __init__(
        self,
        arn: str,
        ttl: int = 300,
        client: object | None = None,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._arn = arn
        self._region = _parse_region(arn)
        self._ttl = ttl
        self._time = time_func
        self._client = client if client is not None else self._create_client()
        self._cache: dict[str, str] | None = None
        self._cache_at: float = 0.0

    @property
    def region(self) -> str:
        return self._region

    def _create_client(self):
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager backend. "
                "Install it with: pip install konfig[aws]"
            ) from exc
        return boto3.client("secretsmanager", region_name=self._region)

    def _fetch(self) -> dict[str, str]:
        """Fetch and parse the bundle directly from AWS (no cache)."""
        try:
            response = self._client.get_secret_value(SecretId=self._arn)
        except self._client.exceptions.ResourceNotFoundException:
            return {}
        raw = response.get("SecretString")
        if raw is None:
            raise ValueError(_NO_SECRET_STRING)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(_NOT_JSON_OBJECT) from exc
        if not isinstance(data, dict):
            raise ValueError(_NOT_JSON_OBJECT)
        return data

    def _bundle(self) -> dict[str, str]:
        """Return the cached bundle, refreshing if the TTL has expired."""
        now = self._time()
        if self._cache is None or (now - self._cache_at) >= self._ttl:
            self._cache = self._fetch()
            self._cache_at = now
        return self._cache

    def refresh(self) -> None:
        """Force the next read to re-fetch the bundle from AWS."""
        self._cache = None

    def get(self, key: str) -> str | None:
        return self._bundle().get(key)

    def _write(self, bundle: dict[str, str]) -> None:
        """Persist the whole bundle to AWS and update the write-through cache."""
        self._client.put_secret_value(
            SecretId=self._arn, SecretString=json.dumps(bundle)
        )
        self._cache = bundle
        self._cache_at = self._time()

    def set(self, key: str, value: str) -> None:
        bundle = self._fetch()  # re-fetch before write to narrow the race window
        bundle[key] = value
        self._write(bundle)

    def delete(self, key: str) -> None:
        bundle = self._fetch()  # re-fetch before write to narrow the race window
        bundle.pop(key, None)
        self._write(bundle)

    def has(self, key: str) -> bool:
        return key in self._bundle()

    def list_keys(self) -> list[str]:
        return list(self._bundle().keys())
