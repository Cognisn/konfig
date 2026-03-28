"""Tests for settings layers."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from konfig.settings.layers import (
    DefaultsLayer,
    EnvLayer,
    FileLayer,
    RuntimeLayer,
    _MISSING,
)


class TestDefaultsLayer:
    def test_get_flat(self) -> None:
        layer = DefaultsLayer({"key": "value"})
        assert layer.get("key") == "value"

    def test_get_nested(self) -> None:
        layer = DefaultsLayer({"database": {"host": "localhost"}})
        assert layer.get("database.host") == "localhost"

    def test_get_missing(self) -> None:
        layer = DefaultsLayer({})
        assert layer.get("missing") is _MISSING

    def test_get_section(self) -> None:
        layer = DefaultsLayer({"db": {"host": "localhost", "port": 5432}})
        assert layer.get_section("db") == {"host": "localhost", "port": 5432}

    def test_get_section_missing(self) -> None:
        layer = DefaultsLayer({})
        assert layer.get_section("db") == {}


class TestFileLayer:
    def test_load_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("database:\n  host: filehost\n")
        layer = FileLayer(f)
        assert layer.get("database.host") == "filehost"

    def test_reload(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("key: original\n")
        layer = FileLayer(f)
        assert layer.get("key") == "original"
        f.write_text("key: updated\n")
        layer.reload()
        assert layer.get("key") == "updated"

    def test_no_file(self) -> None:
        layer = FileLayer(None)
        assert layer.get("anything") is _MISSING


class TestEnvLayer:
    def test_get_with_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYAPP__DATABASE__HOST", "envhost")
        layer = EnvLayer("MYAPP")
        assert layer.get("database.host") == "envhost"

    def test_get_without_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE__HOST", "envhost")
        layer = EnvLayer(None)
        assert layer.get("database.host") == "envhost"

    def test_get_missing(self) -> None:
        layer = EnvLayer("MYAPP")
        assert layer.get("nonexistent.key") is _MISSING

    def test_get_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYAPP__DB__HOST", "envhost")
        monkeypatch.setenv("MYAPP__DB__PORT", "3306")
        layer = EnvLayer("MYAPP")
        section = layer.get_section("db")
        assert section == {"host": "envhost", "port": "3306"}

    def test_case_insensitive_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYAPP__KEY", "val")
        layer = EnvLayer("myapp")
        assert layer.get("key") == "val"


class TestRuntimeLayer:
    def test_set_and_get(self) -> None:
        layer = RuntimeLayer()
        layer.set("database.host", "runtimehost")
        assert layer.get("database.host") == "runtimehost"

    def test_delete(self) -> None:
        layer = RuntimeLayer()
        layer.set("key", "value")
        assert layer.delete("key") is True
        assert layer.get("key") is _MISSING

    def test_delete_missing(self) -> None:
        layer = RuntimeLayer()
        assert layer.delete("missing") is False

    def test_get_section(self) -> None:
        layer = RuntimeLayer()
        layer.set("db.host", "runtimehost")
        layer.set("db.port", 5432)
        assert layer.get_section("db") == {"host": "runtimehost", "port": 5432}
