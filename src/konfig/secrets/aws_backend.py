"""AWS Secrets Manager backend for secret storage (optional)."""
from __future__ import annotations

import json
from typing import Any, Optional

from konfig.secrets.backend import SecretBackend


class AWSSecretsManagerBackend(SecretBackend):
    """Stores secrets in AWS Secrets Manager.

    Requires ``boto3`` to be installed (``pip install konfig[aws]``).

    Args:
        region: AWS region name.
        prefix: Optional prefix for secret names in AWS.
    """

    def __init__(self, region: str, prefix: str = "") -> None:
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager backend. "
                "Install it with: pip install konfig[aws]"
            )
        self._client = boto3.client("secretsmanager", region_name=region)
        self._prefix = prefix

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def get(self, key: str) -> str | None:
        try:
            response = self._client.get_secret_value(SecretId=self._full_key(key))
            return response["SecretString"]
        except self._client.exceptions.ResourceNotFoundException:
            return None

    def set(self, key: str, value: str) -> None:
        full_key = self._full_key(key)
        try:
            self._client.put_secret_value(SecretId=full_key, SecretString=value)
        except self._client.exceptions.ResourceNotFoundException:
            self._client.create_secret(Name=full_key, SecretString=value)

    def delete(self, key: str) -> None:
        try:
            self._client.delete_secret(
                SecretId=self._full_key(key), ForceDeleteWithoutRecovery=True
            )
        except self._client.exceptions.ResourceNotFoundException:
            pass

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def list_keys(self) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_secrets")
        for page in paginator.paginate():
            for secret in page.get("SecretList", []):
                name = secret["Name"]
                if self._prefix:
                    if name.startswith(f"{self._prefix}/"):
                        keys.append(name[len(self._prefix) + 1 :])
                else:
                    keys.append(name)
        return keys
