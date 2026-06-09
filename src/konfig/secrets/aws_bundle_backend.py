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

    def _create_client(self):  # pragma: no cover - exercised in Task 6
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager backend. "
                "Install it with: pip install konfig[aws]"
            ) from exc
        return boto3.client("secretsmanager", region_name=self._region)

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def has(self, key: str) -> bool:
        raise NotImplementedError

    def list_keys(self) -> list[str]:
        raise NotImplementedError
