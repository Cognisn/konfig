"""Collector error handling: what the listener thread and handlers let through."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from konfig.logging.central import collector as collector_module
from konfig.logging.central.collector import CentralCollector
from konfig.logging.central.config import CentralLogConfig


def _collector(tmp_path: Path) -> CentralCollector:
    return CentralCollector(CentralLogConfig(), log_dir=tmp_path, instance={})


class _Interrupt(BaseException):
    """Stands in for KeyboardInterrupt or SystemExit without touching either."""


class _StalledReader:
    """A reader that never delivers a line, so the handler waits until cancelled."""

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        await asyncio.Event().wait()
        return b""  # pragma: no cover - never reached


class _RecordingWriter:
    def __init__(self) -> None:
        self.closed = False

    def get_extra_info(self, name: str) -> Any:
        return ("192.0.2.10", 50000) if name == "peername" else None

    def close(self) -> None:
        self.closed = True


class TestListenerThread:
    def test_base_exception_before_start_is_recorded_and_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        collector = _collector(tmp_path)

        async def interrupted(*args: Any) -> None:
            raise _Interrupt

        monkeypatch.setattr(collector, "_serve", interrupted)
        with pytest.raises(_Interrupt):
            collector._thread_main("127.0.0.1", 0, None)  # type: ignore[arg-type]
        assert collector._ready.is_set()
        assert isinstance(collector._start_error, _Interrupt)

    def test_failure_after_start_is_logged_not_raised(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        collector = _collector(tmp_path)
        collector._ready.set()

        async def failing(*args: Any) -> None:
            raise RuntimeError("listener broke")

        monkeypatch.setattr(collector, "_serve", failing)
        with caplog.at_level(logging.ERROR, logger=collector_module.__name__):
            collector._thread_main("127.0.0.1", 0, None)  # type: ignore[arg-type]
        assert collector._start_error is None
        assert "Log collector listener failed" in caplog.text


class TestBind:
    def test_bind_error_is_recorded_for_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        collector = _collector(tmp_path)

        async def refused(*args: Any, **kwargs: Any) -> None:
            raise OSError("address in use")

        monkeypatch.setattr(collector_module.asyncio, "start_server", refused)
        asyncio.run(collector._serve("127.0.0.1", 0, None))  # type: ignore[arg-type]
        assert collector._ready.is_set()
        assert isinstance(collector._start_error, OSError)

    def test_base_exception_while_binding_is_recorded_and_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        collector = _collector(tmp_path)

        async def interrupted(*args: Any, **kwargs: Any) -> None:
            raise _Interrupt

        monkeypatch.setattr(collector_module.asyncio, "start_server", interrupted)
        with pytest.raises(_Interrupt):
            asyncio.run(
                collector._serve("127.0.0.1", 0, None)  # type: ignore[arg-type]
            )
        assert collector._ready.is_set()
        assert isinstance(collector._start_error, _Interrupt)


class TestHandlerCancellation:
    async def test_cancelled_handler_cleans_up_and_stays_cancelled(
        self, tmp_path: Path
    ) -> None:
        collector = _collector(tmp_path)
        writer = _RecordingWriter()
        task = asyncio.create_task(
            collector._handle(_StalledReader(), writer)  # type: ignore[arg-type]
        )
        for _ in range(5):
            await asyncio.sleep(0)
        assert task in collector._tasks
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert writer.closed
        assert task not in collector._tasks
