"""Tests for settings file parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from konfig.settings.parsers import parse_file, resolve_format, write_file


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


class TestResolveFormat:
    def test_override_wins(self, tmp_path: Path) -> None:
        assert resolve_format(tmp_path / "config.yaml", "sqlite") == "sqlite"

    def test_override_case_insensitive(self) -> None:
        assert resolve_format(None, "SQLite") == "sqlite"

    def test_override_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="KONFIG_CONFIG_FORMAT"):
            resolve_format(None, "xml")

    def test_extension_detection(self, tmp_path: Path) -> None:
        assert resolve_format(tmp_path / "c.yaml", None) == "yaml"
        assert resolve_format(tmp_path / "c.yml", None) == "yaml"
        assert resolve_format(tmp_path / "c.json", None) == "json"
        assert resolve_format(tmp_path / "c.toml", None) == "toml"
        assert resolve_format(tmp_path / "c.sqlite", None) == "sqlite"
        assert resolve_format(tmp_path / "c.db", None) == "sqlite"
        assert resolve_format(tmp_path / "c.sqlite3", None) == "sqlite"

    def test_default_yaml_when_unknown(self, tmp_path: Path) -> None:
        assert resolve_format(tmp_path / "c.conf", None) == "yaml"
        assert resolve_format(None, None) == "yaml"


class TestSqliteViaParseFile:
    def test_write_and_parse_sqlite_with_fmt(self, tmp_path: Path) -> None:
        f = tmp_path / "store.bin"  # extension intentionally not sqlite-ish
        write_file(f, {"database": {"host": "localhost"}}, fmt="sqlite")
        assert parse_file(f, fmt="sqlite") == {"database": {"host": "localhost"}}
