"""Tests for resolving centralised logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from konfig import Settings
from konfig.logging.central import start_central_logging
from konfig.logging.central.config import (
    CentralLogConfig,
    parse_bool,
    parse_host_port,
    resolve_config,
)
from konfig.logging.manager import LogManager
from konfig.secrets import Secrets
from konfig.secrets.encrypted_file import EncryptedFileBackend

FINGERPRINT = ":".join(["AB"] * 32)


def _settings(central: dict[str, Any]) -> Settings:
    return Settings(defaults={"logging": {"central": central}})


class TestParseBool:
    @pytest.mark.parametrize("text", ["1", "true", "TRUE", "Yes", "on", " On "])
    def test_true_values(self, text: str) -> None:
        assert parse_bool(text, "X") is True

    @pytest.mark.parametrize("text", ["0", "false", "False", "no", "OFF", ""])
    def test_false_values(self, text: str) -> None:
        assert parse_bool(text, "X") is False

    def test_real_booleans_and_none(self) -> None:
        assert parse_bool(True, "X") is True
        assert parse_bool(False, "X") is False
        assert parse_bool(None, "X") is False

    def test_unrecognised_warns_and_is_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_bool("maybe", "KONFIG_LOG_CENTRAL") is False
        assert "KONFIG_LOG_CENTRAL" in caplog.text

    def test_env_garbage_does_not_enable(self) -> None:
        # bool("no") would be True; the parser must not do that.
        assert not resolve_config(None, {"KONFIG_LOG_CENTRAL": "no"}).enabled
        assert not resolve_config(None, {"KONFIG_LOG_CENTRAL": "banana"}).enabled


class TestParseHostPort:
    def test_host_and_port(self) -> None:
        assert parse_host_port("log-collector:9020") == ("log-collector", 9020)

    def test_ipv6(self) -> None:
        assert parse_host_port("[::1]:9020") == ("::1", 9020)

    def test_default_port(self) -> None:
        assert parse_host_port("log-collector", 9020) == ("log-collector", 9020)

    @pytest.mark.parametrize("text", ["", "host", "host:abc", "host:70000", ":9020"])
    def test_invalid(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_host_port(text)


class TestDefaults:
    def test_disabled_by_default(self) -> None:
        config = resolve_config(Settings(), {})
        assert config == CentralLogConfig()
        assert not config.active

    def test_defaults_when_enabled(self) -> None:
        config = resolve_config(None, {"KONFIG_LOG_CENTRAL": "1"})
        assert config.enabled and not config.collector
        assert config.listen == "0.0.0.0:9020"
        assert config.level == logging.INFO
        assert config.queue_size == 10000
        assert config.store_key == "konfig.log_collector"
        assert config.flush_timeout == 5.0
        assert config.max_connections == 1000
        assert config.retention_runs == 10
        assert not config.include_instance_locally
        assert not config.has_override

    def test_disabled_does_not_start(self, tmp_path: Path) -> None:
        manager = LogManager(log_dir=tmp_path, console_output="none")
        manager.setup()
        try:
            root_handlers = list(logging.getLogger().handlers)
            assert start_central_logging(manager, Settings(), None, environ={}) is None
            assert logging.getLogger().handlers == root_handlers
            assert not (tmp_path / "central").exists()
        finally:
            manager.shutdown()


class TestPrecedence:
    def test_settings_enable(self) -> None:
        config = resolve_config(_settings({"enabled": True}), {})
        assert config.enabled

    def test_collector_implies_enabled(self) -> None:
        config = resolve_config(None, {"KONFIG_LOG_COLLECTOR": "true"})
        assert config.enabled and config.collector and config.active

    def test_env_wins_over_settings(self) -> None:
        settings = _settings(
            {
                "enabled": True,
                "listen": "127.0.0.1:1111",
                "advertise": "from-settings:1",
                "instance_label": "settings-label",
            }
        )
        env = {
            "KONFIG_LOG_COLLECTOR_LISTEN": "0.0.0.0:2222",
            "KONFIG_LOG_COLLECTOR_ADVERTISE": "from-env:2",
            "KONFIG_LOG_INSTANCE_LABEL": "env-label",
        }
        config = resolve_config(settings, env)
        assert config.listen == "0.0.0.0:2222"
        assert config.advertise == "from-env:2"
        assert config.instance_label == "env-label"

    def test_env_can_disable(self) -> None:
        config = resolve_config(
            _settings({"enabled": True}), {"KONFIG_LOG_CENTRAL": "0"}
        )
        assert not config.active

    def test_settings_only_values(self) -> None:
        settings = _settings(
            {
                "enabled": "yes",
                "level": "debug",
                "queue_size": "50",
                "store_key": "custom.key",
                "flush_timeout": 2,
                "include_instance_locally": "on",
                "max_connections": 7,
            }
        )
        config = resolve_config(settings, {})
        assert config.level == logging.DEBUG
        assert config.queue_size == 50
        assert config.store_key == "custom.key"
        assert config.flush_timeout == 2.0
        assert config.include_instance_locally
        assert config.max_connections == 7

    def test_invalid_numbers_fall_back(self, caplog: pytest.LogCaptureFixture) -> None:
        settings = _settings({"enabled": True, "queue_size": "lots", "level": "LOUD"})
        with caplog.at_level(logging.WARNING):
            config = resolve_config(settings, {})
        assert config.queue_size == 10000
        assert config.level == logging.INFO


class TestOverride:
    def test_full_env_override(self) -> None:
        env = {
            "KONFIG_LOG_CENTRAL": "1",
            "KONFIG_LOG_ENDPOINT": "log-collector:9020",
            "KONFIG_LOG_CERT_SHA256": FINGERPRINT,
            "KONFIG_LOG_TOKEN": "tok",
        }
        config = resolve_config(None, env)
        assert config.has_override
        assert config.override_source == "environment"
        assert config.endpoint == "log-collector:9020"
        assert "tok" not in repr(config)

    def test_partial_env_override_is_an_error(self) -> None:
        env = {"KONFIG_LOG_CENTRAL": "1", "KONFIG_LOG_ENDPOINT": "log-collector:9020"}
        config = resolve_config(None, env)
        assert not config.has_override
        assert config.override_error is not None
        assert "KONFIG_LOG_CERT_SHA256" in config.override_error
        assert "KONFIG_LOG_TOKEN" in config.override_error

    def test_env_never_mixed_with_settings(self) -> None:
        settings = _settings(
            {
                "enabled": True,
                "endpoint": "settings:9020",
                "cert_sha256": FINGERPRINT,
                "token": "settings-token",
            }
        )
        config = resolve_config(settings, {"KONFIG_LOG_TOKEN": "env-token"})
        assert config.override_source == "environment"
        assert config.override_error is not None
        assert config.endpoint is None

    def test_full_settings_override(self) -> None:
        settings = _settings(
            {
                "enabled": True,
                "endpoint": "settings:9020",
                "cert_sha256": FINGERPRINT,
                "token": "secret://log_token",
            }
        )
        config = resolve_config(settings, {})
        assert config.has_override
        assert config.override_source == "settings"

    def test_partial_override_disables_forwarding(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = LogManager(log_dir=tmp_path, console_output="none")
        manager.setup()
        try:
            env = {"KONFIG_LOG_CENTRAL": "1", "KONFIG_LOG_ENDPOINT": "x:1"}
            with caplog.at_level(logging.ERROR):
                handle = start_central_logging(manager, Settings(), None, environ=env)
            assert handle is None
            assert "must be set together" in caplog.text
        finally:
            manager.shutdown()

    def test_secret_uri_token_is_resolved(self, tmp_path: Path) -> None:
        secrets = Secrets(
            backend=EncryptedFileBackend(tmp_path / "s.enc", master_key="k")
        )
        secrets.set("log_token", "resolved-token-value")
        manager = LogManager(log_dir=tmp_path / "logs", console_output="none")
        manager.setup()
        env = {
            "KONFIG_LOG_CENTRAL": "1",
            "KONFIG_LOG_ENDPOINT": "127.0.0.1:9",
            "KONFIG_LOG_CERT_SHA256": FINGERPRINT,
            "KONFIG_LOG_TOKEN": "secret://log_token",
        }
        try:
            handle = start_central_logging(manager, Settings(), secrets, environ=env)
            assert handle is not None and handle.sender is not None
            override = handle.sender._override
            assert override is not None
            assert override.token == "resolved-token-value"
        finally:
            manager.shutdown()

    def test_unresolvable_secret_uri_disables(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secrets = Secrets(
            backend=EncryptedFileBackend(tmp_path / "s.enc", master_key="k")
        )
        manager = LogManager(log_dir=tmp_path / "logs", console_output="none")
        manager.setup()
        env = {
            "KONFIG_LOG_CENTRAL": "1",
            "KONFIG_LOG_ENDPOINT": "127.0.0.1:9",
            "KONFIG_LOG_CERT_SHA256": FINGERPRINT,
            "KONFIG_LOG_TOKEN": "secret://missing",
        }
        try:
            with caplog.at_level(logging.ERROR):
                assert (
                    start_central_logging(manager, Settings(), secrets, environ=env)
                    is None
                )
            assert "did not resolve" in caplog.text
        finally:
            manager.shutdown()
