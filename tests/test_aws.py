"""Tests for shared AWS helpers in konfig._aws."""

from __future__ import annotations

import pytest

from konfig._aws import seeding_enabled


class TestSeedingEnabled:
    def test_enabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KONFIG_AWS_SEED", raising=False)
        assert seeding_enabled() is True

    @pytest.mark.parametrize(
        "value", ["0", "false", "False", "FALSE", "no", "off", " off "]
    )
    def test_disabled_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("KONFIG_AWS_SEED", value)
        assert seeding_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "", "anything"])
    def test_enabled_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("KONFIG_AWS_SEED", value)
        assert seeding_enabled() is True
