"""Shared AWS helpers used by both the secrets backends and the settings layer."""

from __future__ import annotations

import os

_SEED_DISABLED_VALUES = {"0", "false", "no", "off"}


def seeding_enabled() -> bool:
    """Whether first-boot seeding of empty AWS stores is enabled.

    Controlled by the ``KONFIG_AWS_SEED`` environment variable: seeding is on
    by default and disabled when the value is one of ``0``, ``false``, ``no``,
    or ``off`` (case-insensitive). The hard opt-out exists for operators
    running strictly read-only IAM roles who want no write attempt at all.
    """
    return (
        os.environ.get("KONFIG_AWS_SEED", "").strip().lower()
        not in _SEED_DISABLED_VALUES
    )


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
