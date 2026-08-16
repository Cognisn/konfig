"""Shared fixtures for settings tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_konfig_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure konfig env vars never leak into settings tests by default.

    Tests that exercise the env-var paths set them explicitly via monkeypatch.
    """
    monkeypatch.delenv("KONFIG_CONFIG_FORMAT", raising=False)
    monkeypatch.delenv("KONFIG_AWS_SETTINGS", raising=False)
    monkeypatch.delenv("KONFIG_AWS_SEED", raising=False)
