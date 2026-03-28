"""Tests for the Settings class."""
from __future__ import annotations

from pathlib import Path

import pytest

from konfig.settings.settings import Settings


class TestSettingsGet:
    def test_get_from_defaults(self) -> None:
        s = Settings(defaults={"database": {"host": "localhost"}})
        assert s.get("database.host") == "localhost"

    def test_get_default_value(self) -> None:
        s = Settings()
        assert s.get("missing", "fallback") == "fallback"

    def test_get_none_when_missing(self) -> None:
        s = Settings()
        assert s.get("missing") is None

    def test_get_with_cast(self) -> None:
        s = Settings(defaults={"port": "8080"})
        assert s.get("port", cast=int) == 8080

    def test_file_overrides_defaults(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("database:\n  host: filehost\n")
        s = Settings(config_file=f, defaults={"database": {"host": "localhost"}})
        assert s.get("database.host") == "filehost"

    def test_env_overrides_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("database:\n  host: filehost\n")
        monkeypatch.setenv("MYAPP__DATABASE__HOST", "envhost")
        s = Settings(config_file=f, env_prefix="MYAPP")
        assert s.get("database.host") == "envhost"

    def test_runtime_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYAPP__KEY", "envval")
        s = Settings(env_prefix="MYAPP")
        s.set("key", "runtimeval")
        assert s.get("key") == "runtimeval"


class TestSettingsHas:
    def test_has_existing(self) -> None:
        s = Settings(defaults={"key": "value"})
        assert s.has("key") is True

    def test_has_missing(self) -> None:
        s = Settings()
        assert s.has("missing") is False


class TestSettingsSetDelete:
    def test_set_and_get(self) -> None:
        s = Settings()
        s.set("new.key", "value")
        assert s.get("new.key") == "value"

    def test_delete(self) -> None:
        s = Settings()
        s.set("key", "value")
        assert s.delete("key") is True
        assert s.get("key") is None

    def test_delete_missing(self) -> None:
        s = Settings()
        assert s.delete("missing") is False


class TestSettingsGetSection:
    def test_section_merges_layers(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("database:\n  port: 3306\n")
        s = Settings(
            config_file=f,
            defaults={"database": {"host": "localhost", "port": 5432}},
        )
        section = s.get_section("database")
        assert section["host"] == "localhost"
        assert section["port"] == 3306  # file overrides default

    def test_section_empty(self) -> None:
        s = Settings()
        assert s.get_section("nonexistent") == {}


class TestSettingsReload:
    def test_reload_picks_up_changes(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("key: original\n")
        s = Settings(config_file=f)
        assert s.get("key") == "original"
        f.write_text("key: updated\n")
        s.reload()
        assert s.get("key") == "updated"


class TestSystemUserLayers:
    def test_user_overrides_system(self, tmp_path: Path) -> None:
        sys_f = tmp_path / "system" / "config.yaml"
        sys_f.parent.mkdir()
        sys_f.write_text("database:\n  host: sys-host\n  port: 5432\n")

        user_f = tmp_path / "user" / "config.yaml"
        user_f.parent.mkdir()
        user_f.write_text("database:\n  host: user-host\n")

        s = Settings(config_file=user_f, system_config_file=sys_f)
        assert s.get("database.host") == "user-host"
        assert s.get("database.port") == 5432  # falls through to system

    def test_system_overrides_defaults(self, tmp_path: Path) -> None:
        sys_f = tmp_path / "config.yaml"
        sys_f.write_text("db:\n  host: sys-host\n")
        s = Settings(
            system_config_file=sys_f,
            defaults={"db": {"host": "default-host", "port": 5432}},
        )
        assert s.get("db.host") == "sys-host"
        assert s.get("db.port") == 5432

    def test_system_config_graceful_on_missing(self) -> None:
        s = Settings(system_config_file="/nonexistent/path/config.yaml")
        assert s.get("anything") is None  # no crash

    def test_section_merges_all_layers(self, tmp_path: Path) -> None:
        sys_f = tmp_path / "system.yaml"
        sys_f.write_text("db:\n  host: sys\n  port: 5432\n")
        user_f = tmp_path / "user.yaml"
        user_f.write_text("db:\n  host: user\n  name: mydb\n")
        s = Settings(
            config_file=user_f,
            system_config_file=sys_f,
            defaults={"db": {"timeout": 30}},
        )
        section = s.get_section("db")
        assert section["host"] == "user"       # user wins
        assert section["port"] == 5432         # system
        assert section["name"] == "mydb"       # user only
        assert section["timeout"] == 30        # defaults


class TestPersistSettings:
    def test_persist_user(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("key: original\n")
        s = Settings(config_file=f)
        s.set("key", "updated", persist="user")

        # Verify it was written to disk
        s2 = Settings(config_file=f)
        assert s2.get("key") == "updated"

    def test_persist_user_nested(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("database:\n  host: localhost\n")
        s = Settings(config_file=f)
        s.set("database.port", 3306, persist="user")

        s2 = Settings(config_file=f)
        assert s2.get("database.host") == "localhost"
        assert s2.get("database.port") == 3306

    def test_persist_system_writable(self, tmp_path: Path) -> None:
        sys_f = tmp_path / "system.yaml"
        sys_f.write_text("key: sys_val\n")
        s = Settings(system_config_file=sys_f)
        s.set("key", "new_sys_val", persist="system")

        s2 = Settings(system_config_file=sys_f)
        assert s2.get("key") == "new_sys_val"

    def test_persist_system_unwritable(self, tmp_path: Path) -> None:
        import sys as _sys

        if _sys.platform == "win32":
            pytest.skip("POSIX permissions test")

        sys_f = tmp_path / "system.yaml"
        sys_f.write_text("key: val\n")
        sys_f.chmod(0o444)
        tmp_path.chmod(0o555)

        s = Settings(system_config_file=sys_f)
        with pytest.raises(PermissionError):
            s.set("key", "new_val", persist="system")

        # Clean up permissions so tmp_path can be removed
        tmp_path.chmod(0o755)
        sys_f.chmod(0o644)

    def test_delete_persisted_user(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("a: 1\nb: 2\n")
        s = Settings(config_file=f)
        assert s.delete("a", persist="user") is True

        s2 = Settings(config_file=f)
        assert s2.get("a") is None
        assert s2.get("b") == 2

    def test_persist_json(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text('{"key": "original"}')
        s = Settings(config_file=f)
        s.set("key", "updated", persist="user")

        s2 = Settings(config_file=f)
        assert s2.get("key") == "updated"

    def test_persist_no_file_raises(self) -> None:
        s = Settings()
        with pytest.raises(RuntimeError, match="no config file"):
            s.set("key", "value", persist="user")
