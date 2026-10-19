"""AppContext and LogManager integration, safety rules and regression checks."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

import pytest

import konfig.logging.central as central_pkg
from konfig import AppContext
from tests.test_logging.test_central._helpers import (
    MASTER_KEY,
    free_port,
    messages,
    read_stream,
    wait_for,
)
from tests.test_logging.test_central._regression import FIXTURES, capture_app_log

_FORBIDDEN_MODULES = {"pickle", "cPickle", "_pickle", "marshal", "shelve", "dill"}
_FORBIDDEN_NAMES = {"SocketHandler", "DatagramHandler", "listen"}


def _app(tmp_path: Path, central: dict, log_format: str = "text") -> AppContext:
    return AppContext(
        name="Central App",
        version="2.0.0",
        config_file=tmp_path / "missing.yaml",
        system_config_file=tmp_path / "missing-system.yaml",
        defaults={
            "logging": {
                "log_dir": str(tmp_path / "logs"),
                "console_output": "none",
                "format": log_format,
                "central": central,
            },
            "secrets": {
                "backend": "encrypted_file",
                "file_path": str(tmp_path / "secrets.enc"),
                "master_key": MASTER_KEY,
            },
        },
    )


def _collector_settings(**extra: object) -> dict:
    values: dict[str, object] = {
        "collector": True,
        "listen": "127.0.0.1:0",
        "advertise": "127.0.0.1",
    }
    values.update(extra)
    return values


class TestNoPickle:
    def test_package_never_imports_pickle(self) -> None:
        package_dir = Path(central_pkg.__file__).parent
        sources = sorted(package_dir.glob("*.py"))
        assert len(sources) >= 8
        for source in sources:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {(node.module or "").split(".")[0]}
                    names |= {alias.name for alias in node.names} & _FORBIDDEN_NAMES
                else:
                    continue
                bad = names & (_FORBIDDEN_MODULES | _FORBIDDEN_NAMES)
                assert not bad, f"{source.name} imports {bad}"

    def test_no_unsafe_logging_handlers_referenced(self) -> None:
        package_dir = Path(central_pkg.__file__).parent
        for source in package_dir.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            attributes = {
                n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
            }
            assert not attributes & {"SocketHandler", "DatagramHandler"}, source.name
            assert "logging.config" not in source.read_text(encoding="utf-8")


class TestRegression:
    @pytest.mark.parametrize("log_format", ["text", "json"])
    def test_disabled_output_matches_041_fixture(
        self, tmp_path: Path, log_format: str
    ) -> None:
        expected = (FIXTURES / f"app_log_{log_format}.txt").read_text(encoding="utf-8")
        assert capture_app_log(tmp_path, log_format) == expected

    def test_disabled_adds_no_handlers_or_files(self, tmp_path: Path) -> None:
        with _app(tmp_path, {}) as ctx:
            assert ctx.log_manager.central is None
            root_handlers = set(logging.getLogger().handlers)
            assert set(ctx.log_manager.handlers) <= root_handlers
            assert not (tmp_path / "logs" / "central").exists()


class TestAppContext:
    def test_collector_role(self, tmp_path: Path) -> None:
        with _app(tmp_path, _collector_settings()) as ctx:
            central = ctx.log_manager.central
            assert central is not None and central.role == "collector"
            logging.getLogger("ctx.app").info("collector app record")
            assert wait_for(lambda: messages(read_stream(tmp_path / "logs"), "ctx.app"))
            assert ctx.secrets.has("konfig.log_collector")
        entry = [e for e in read_stream(tmp_path / "logs") if e["logger"] == "ctx.app"]
        assert entry[0]["instance"]["app_name"] == "Central App"
        assert entry[0]["instance"]["version"] == "2.0.0"
        # Local logging is unchanged and the shutdown message reached it.
        local = next((tmp_path / "logs").glob("2*/app.log")).read_text()
        assert "collector app record" in local
        assert "Log collector stopped" in local

    def test_startup_failure_never_stops_the_app(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with _app(tmp_path, _collector_settings(listen="not-an-address")) as ctx:
            assert ctx.log_manager.central is None
            ctx.logger.info("still running")
        assert "could not start" in caplog.text

    def test_port_in_use_never_stops_the_app(self, tmp_path: Path) -> None:
        with _app(tmp_path / "a", _collector_settings()) as first:
            first_central = first.log_manager.central
            assert first_central is not None and first_central.collector is not None
            port = first_central.collector.port
            with _app(
                tmp_path / "b", _collector_settings(listen=f"127.0.0.1:{port}")
            ) as second:
                assert second.log_manager.central is None

    def test_sender_without_collector_starts_and_stops_quickly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time

        monkeypatch.setenv("KONFIG_LOG_CENTRAL", "1")
        monkeypatch.setenv("KONFIG_LOG_ENDPOINT", f"127.0.0.1:{free_port()}")
        monkeypatch.setenv("KONFIG_LOG_CERT_SHA256", "AB" * 32)
        monkeypatch.setenv("KONFIG_LOG_TOKEN", "unused-token")
        started = time.monotonic()
        with _app(tmp_path, {"flush_timeout": 0.5}) as ctx:
            assert ctx.log_manager.central is not None
            for i in range(1000):
                ctx.logger.info("record %d", i)
        assert time.monotonic() - started < 5
        local = next((tmp_path / "logs").glob("2*/app.log")).read_text()
        assert "record 999" in local
        assert "record(s) unsent" in local
        assert "unused-token" not in local

    def test_include_instance_locally(self, tmp_path: Path) -> None:
        settings = _collector_settings(
            include_instance_locally=True, instance_label="c1"
        )
        with _app(tmp_path, settings, log_format="json") as ctx:
            ctx.logger.info("tagged locally")
            run_dir = ctx.log_manager.run_dir
        assert run_dir is not None
        lines = [
            json.loads(line) for line in (run_dir / "app.log").read_text().splitlines()
        ]
        tagged = [line for line in lines if line["message"] == "tagged locally"]
        assert tagged[0]["instance"]["label"] == "c1"
        banner = [line for line in lines if line["message"].startswith("App:")]
        assert "instance" not in banner[0]  # logged before forwarding started

    def test_composed_start_call(self, tmp_path: Path) -> None:
        from konfig import LogManager, Secrets, Settings
        from konfig.secrets.encrypted_file import EncryptedFileBackend

        settings = Settings(defaults={"logging": {"central": _collector_settings()}})
        secrets = Secrets(
            backend=EncryptedFileBackend(tmp_path / "s.enc", master_key=MASTER_KEY)
        )
        manager = LogManager(log_dir=tmp_path / "logs", console_output="none")
        manager.setup()
        try:
            assert manager.start_central_logging(settings, secrets) is True
            assert (
                manager.start_central_logging(settings, secrets) is True
            )  # idempotent
        finally:
            manager.stop_central_logging()
            manager.stop_central_logging()
            manager.shutdown()
        assert manager.central is None
