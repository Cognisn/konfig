"""Tests for the SQLite config store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from konfig.settings.sqlite_store import _flatten, _unflatten, read_sqlite, write_sqlite


class TestFlatten:
    def test_flatten_nested(self) -> None:
        data = {"database": {"host": "localhost", "port": 5432}, "debug": True}
        assert sorted(_flatten(data)) == [
            ("database.host", "localhost"),
            ("database.port", 5432),
            ("debug", True),
        ]

    def test_flatten_list_is_a_leaf(self) -> None:
        assert _flatten({"a": [1, 2, 3]}) == [("a", [1, 2, 3])]

    def test_flatten_empty_dict_yields_no_rows(self) -> None:
        assert _flatten({"a": {}}) == []


class TestUnflatten:
    def test_unflatten_roundtrip(self) -> None:
        rows = [("database.host", "localhost"), ("database.port", 5432)]
        assert _unflatten(rows) == {"database": {"host": "localhost", "port": 5432}}


class TestReadWrite:
    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        data = {
            "database": {"host": "localhost", "port": 5432},
            "debug": True,
            "tags": ["a", "b"],
            "ratio": 1.5,
            "nothing": None,
        }
        db = tmp_path / "config.sqlite"
        write_sqlite(db, data)
        assert read_sqlite(db) == data

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert read_sqlite(tmp_path / "absent.sqlite") == {}

    def test_read_file_without_table_returns_empty(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        sqlite3.connect(str(db)).close()  # creates the file, no settings table
        assert read_sqlite(db) == {}

    def test_write_replaces_previous_contents(self, tmp_path: Path) -> None:
        db = tmp_path / "config.sqlite"
        write_sqlite(db, {"a": 1, "b": 2})
        write_sqlite(db, {"a": 3})
        assert read_sqlite(db) == {"a": 3}

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        db = tmp_path / "nested" / "dir" / "config.sqlite"
        write_sqlite(db, {"a": 1})
        assert read_sqlite(db) == {"a": 1}
