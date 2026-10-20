"""Tests for sender resilience: never block, never crash, drop oldest."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from konfig.logging.central.collector import CentralCollector
from konfig.logging.central.config import CentralLogConfig
from konfig.logging.central.discovery import CollectorEntry
from konfig.logging.central.sender import DropOldestQueue, ForwardingHandler, LogSender
from tests.test_logging.test_central._helpers import (
    free_port,
    isolated_logger,
    messages,
    read_stream,
    shared_secrets,
    wait_for,
)

FINGERPRINT = ":".join(["AB"] * 32)
StartCollector = Callable[..., CentralCollector]


def _dead_sender(**config: object) -> LogSender:
    values: dict[str, object] = {"enabled": True, "flush_timeout": 0.5}
    values.update(config)
    return LogSender(
        CentralLogConfig(**values),  # type: ignore[arg-type]
        override=CollectorEntry(f"127.0.0.1:{free_port()}", FINGERPRINT, "token"),
    )


class TestDropOldestQueue:
    def test_drops_oldest_and_counts(self) -> None:
        queue = DropOldestQueue(3)
        for i in range(5):
            queue.put_nowait(i)
        assert len(queue) == 3
        assert queue.take(10, 0) == [2, 3, 4]
        assert queue.take_dropped() == 2
        assert queue.take_dropped() == 0

    def test_take_waits_for_first_item_only_up_to_timeout(self) -> None:
        queue = DropOldestQueue(3)
        started = time.monotonic()
        assert queue.take(10, 0.1) == []
        assert time.monotonic() - started < 1.0


class TestNeverBlocks:
    def test_ten_thousand_calls_without_a_collector(self) -> None:
        sender = _dead_sender()
        log = isolated_logger("resilience.fast", sender.handler)
        sender.start()
        try:
            started = time.perf_counter()
            for i in range(10_000):
                log.info("message %d", i)
            elapsed = time.perf_counter() - started
        finally:
            sender.stop()
        assert elapsed < 1.0, f"10,000 log calls took {elapsed:.2f}s"

    def test_stop_is_bounded_with_dead_collector(self) -> None:
        sender = _dead_sender(flush_timeout=0.5)
        log = isolated_logger("resilience.stop", sender.handler)
        sender.start()
        for i in range(100):
            log.info("message %d", i)
        started = time.monotonic()
        unsent = sender.stop()
        assert time.monotonic() - started < 3.0
        assert unsent == 100

    def test_unresolvable_host_does_not_raise(self) -> None:
        sender = LogSender(
            CentralLogConfig(enabled=True, flush_timeout=0.2),
            override=CollectorEntry("no-such-host.invalid:9020", FINGERPRINT, "t"),
        )
        log = isolated_logger("resilience.dns", sender.handler)
        sender.start()
        log.error("still fine")
        sender.stop()

    def test_handler_errors_do_not_reach_caller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sender = _dead_sender()
        monkeypatch.setattr(logging, "raiseExceptions", False)

        def explode(item: object) -> None:
            raise RuntimeError("queue failure")

        monkeypatch.setattr(sender.handler.queue, "put_nowait", explode)
        log = isolated_logger("resilience.errors", sender.handler)
        log.info("does not raise")


class TestFiltering:
    def test_central_loggers_not_forwarded(self) -> None:
        queue = DropOldestQueue(10)
        handler = ForwardingHandler(queue, logging.DEBUG)
        for name in (
            "konfig.logging.central",
            "konfig.logging.central.sender",
            "konfig.logging.central.collector",
        ):
            handler.handle(logging.LogRecord(name, logging.ERROR, "", 0, "x", (), None))
        assert len(queue) == 0
        for name in ("konfig", "konfig.logging", "konfig.logging.centralised", "app"):
            handler.handle(logging.LogRecord(name, logging.ERROR, "", 0, "x", (), None))
        assert len(queue) == 4

    def test_level_filter(self) -> None:
        queue = DropOldestQueue(10)
        handler = ForwardingHandler(queue, logging.WARNING)
        log = isolated_logger("filter.level", handler)
        log.info("too low")
        log.warning("forwarded")
        assert [r["message"] for r in queue.take(10, 0)] == ["forwarded"]


class TestOverflow:
    def test_overflow_drops_oldest_and_reports_dropped(
        self, start_collector: StartCollector, store_path: Path, tmp_path: Path
    ) -> None:
        # The store is empty, so the sender waits for discovery while its
        # small queue overflows.
        sender = LogSender(
            CentralLogConfig(enabled=True, queue_size=100, flush_timeout=5),
            secrets=shared_secrets(store_path),
            instance_factory=lambda: {"label": "overflow"},
            discovery_backoff=(0.1, 0.2),
            connect_backoff=(0.1, 0.2),
        )
        log = isolated_logger("overflow.app", sender.handler)
        sender.start()
        for i in range(250):
            log.info("record %d", i)
        assert sender.unsent() == 100

        start_collector()
        log_dir = tmp_path / "collector-logs"
        assert wait_for(
            lambda: len(messages(read_stream(log_dir), "overflow.app")) == 100
        )
        sender.stop()
        entries = read_stream(log_dir)
        assert messages(entries, "overflow.app") == [
            f"record {i}" for i in range(150, 250)
        ]
        gaps = [e for e in entries if "dropped" in e]
        assert [g["dropped"] for g in gaps] == [150]
        assert gaps[0]["instance"]["label"] == "overflow"
