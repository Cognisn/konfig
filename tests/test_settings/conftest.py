"""Shared fixtures for settings tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_konfig_config_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure KONFIG_CONFIG_FORMAT never leaks into settings tests by default.

    Tests that exercise the env-var path set it explicitly via monkeypatch.
    """
    monkeypatch.delenv("KONFIG_CONFIG_FORMAT", raising=False)
