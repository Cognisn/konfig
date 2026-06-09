"""Shared fixtures for secrets tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_konfig_aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the AWS bundle env var never leaks into secrets tests by default.

    Tests that exercise the env-var path set it explicitly via monkeypatch.
    """
    monkeypatch.delenv("KONFIG_AWS_SECRETS_MANAGER", raising=False)
