"""Tests for settings file parsers."""
from __future__ import annotations

from pathlib import Path

import pytest

from konfig.settings.parsers import parse_file, write_file


class TestParseYAML:
    def test_parse_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("database:\n  host: localhost\n  port: 5432\n")
        result = parse_file(f)
        assert result == {"database": {"host": "localhost", "port": 5432}}

    def test_parse_yml_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yml"
        f.write_text("key: value\n")
        result = parse_file(f)
        assert result == {"key": "value"}

    def test_parse_yaml_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("")
        result = parse_file(f)
        assert result == {}

    def test_parse_yaml_scalar_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("just a string\n")
        result = parse_file(f)
        assert result == {}


class TestParseTOML:
    def test_parse_toml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.toml"
        f.write_text('[database]\nhost = "localhost"\nport = 5432\n')
        result = parse_file(f)
        assert result == {"database": {"host": "localhost", "port": 5432}}

    def test_parse_toml_nested(self, tmp_path: Path) -> None:
        f = tmp_path / "config.toml"
        f.write_text('[server]\nhost = "0.0.0.0"\n\n[server.tls]\nenabled = true\n')
        result = parse_file(f)
        assert result == {"server": {"host": "0.0.0.0", "tls": {"enabled": True}}}


class TestParseJSON:
    def test_parse_json(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text('{"database": {"host": "localhost", "port": 5432}}')
        result = parse_file(f)
        assert result == {"database": {"host": "localhost", "port": 5432}}

    def test_parse_json_array_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text("[1, 2, 3]")
        with pytest.raises(ValueError, match="top-level object"):
            parse_file(f)


class TestParseFileErrors:
    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_file(tmp_path / "nonexistent.yaml")

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "config.xml"
        f.write_text("<root/>")
        with pytest.raises(ValueError, match="Unsupported"):
            parse_file(f)


class TestWriteFile:
    def test_write_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        data = {"database": {"host": "localhost", "port": 5432}}
        write_file(f, data)
        result = parse_file(f)
        assert result == data

    def test_write_json(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        data = {"key": "value", "nested": {"a": 1}}
        write_file(f, data)
        result = parse_file(f)
        assert result == data

    def test_write_toml_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "config.toml"
        with pytest.raises(ValueError, match="TOML"):
            write_file(f, {"key": "value"})

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "deep" / "nested" / "config.yaml"
        write_file(f, {"key": "value"})
        assert f.exists()
        assert parse_file(f) == {"key": "value"}

    def test_roundtrip_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        original = {"a": {"b": {"c": "deep"}}, "list": [1, 2, 3]}
        write_file(f, original)
        assert parse_file(f) == original

    def test_write_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "config.xml"
        with pytest.raises(ValueError, match="Unsupported"):
            write_file(f, {})
