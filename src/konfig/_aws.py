"""Shared AWS helpers used by both the secrets backends and the settings layer."""

from __future__ import annotations


def parse_region(arn: str) -> str:
    """Extract the region from a Secrets Manager ARN.

    ARN shape: ``arn:aws:secretsmanager:<region>:<account>:secret:<name>``.

    Raises:
        ValueError: If the string is not a valid Secrets Manager ARN.
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
