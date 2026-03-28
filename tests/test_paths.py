"""Tests for platform-aware default paths."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from konfig.paths import (
    app_id_from,
    config_dir,
    data_dir,
    default_config_file,
    default_secrets_file,
    default_system_config_file,
    log_dir,
    system_config_dir,
)


class TestAppIdFrom:
    def test_uses_env_prefix_lowered(self) -> None:
        assert app_id_from("My App", env_prefix="MYAPP") == "myapp"

    def test_uses_name_when_no_prefix(self) -> None:
        assert app_id_from("My Application") == "my_application"

    def test_sanitises_special_chars(self) -> None:
        assert app_id_from("My App! (v2.0)") == "my_app_v2_0"

    def test_strips_leading_trailing_underscores(self) -> None:
        assert app_id_from("  spaces  ") == "spaces"

    def test_empty_name_fallback(self) -> None:
        assert app_id_from("!!!") == "konfig"


class TestConfigDir:
    def test_returns_path(self) -> None:
        result = config_dir("myapp")
        assert isinstance(result, Path)
        assert "myapp" in str(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_macos_path(self) -> None:
        result = config_dir("myapp")
        assert "Library/Application Support/myapp" in str(result)

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
    def test_linux_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = config_dir("myapp")
            assert ".config/myapp" in str(result)

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
    def test_linux_xdg_override(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(tmp_path)}):
            result = config_dir("myapp")
            assert result == tmp_path / "myapp"


class TestDataDir:
    def test_returns_path(self) -> None:
        result = data_dir("myapp")
        assert isinstance(result, Path)
        assert "myapp" in str(result)


class TestLogDir:
    def test_returns_path(self) -> None:
        result = log_dir("myapp")
        assert isinstance(result, Path)
        assert "myapp" in str(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_macos_path(self) -> None:
        result = log_dir("myapp")
        assert "Library/Logs/myapp" in str(result)


class TestDefaultConfigFile:
    def test_finds_yaml(self, tmp_path: Path) -> None:
        with patch("konfig.paths.config_dir", return_value=tmp_path):
            (tmp_path / "config.yaml").write_text("key: value")
            result = default_config_file("myapp")
            assert result == tmp_path / "config.yaml"

    def test_finds_toml(self, tmp_path: Path) -> None:
        with patch("konfig.paths.config_dir", return_value=tmp_path):
            (tmp_path / "config.toml").write_text("[section]")
            result = default_config_file("myapp")
            assert result == tmp_path / "config.toml"

    def test_prefers_yaml_over_toml(self, tmp_path: Path) -> None:
        with patch("konfig.paths.config_dir", return_value=tmp_path):
            (tmp_path / "config.yaml").write_text("key: value")
            (tmp_path / "config.toml").write_text("[section]")
            result = default_config_file("myapp")
            assert result == tmp_path / "config.yaml"

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        with patch("konfig.paths.config_dir", return_value=tmp_path):
            result = default_config_file("myapp")
            assert result is None


class TestSystemConfigDir:
    def test_returns_path(self) -> None:
        result = system_config_dir("myapp")
        assert isinstance(result, Path)
        assert "myapp" in str(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_macos_path(self) -> None:
        result = system_config_dir("myapp")
        assert str(result) == "/Library/Application Support/myapp"

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
    def test_linux_path(self) -> None:
        result = system_config_dir("myapp")
        assert str(result) == "/etc/myapp"


class TestDefaultSystemConfigFile:
    def test_finds_yaml(self, tmp_path: Path) -> None:
        with patch("konfig.paths.system_config_dir", return_value=tmp_path):
            (tmp_path / "config.yaml").write_text("key: value")
            result = default_system_config_file("myapp")
            assert result == tmp_path / "config.yaml"

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        with patch("konfig.paths.system_config_dir", return_value=tmp_path):
            result = default_system_config_file("myapp")
            assert result is None


class TestDefaultSecretsFile:
    def test_returns_enc_path(self) -> None:
        result = default_secrets_file("myapp")
        assert result.name == "secrets.enc"
        assert "myapp" in str(result)
