"""End-to-end tests: a collector and real sender processes sharing a store."""

from __future__ import annotations

import logging
import multiprocessing
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from konfig.logging.central.collector import CentralCollector
from konfig.logging.central.config import CentralLogConfig
from konfig.logging.central.sender import LogSender
from tests.test_logging.test_central import _workers
from tests.test_logging.test_central._helpers import (
    MASTER_KEY,
    isolated_logger,
    messages,
    read_stream,
    shared_secrets,
    wait_for,
)

StartCollector = Callable[..., CentralCollector]
LABELS = ("worker-1", "worker-2", "worker-3")
COUNT = 200


@pytest.mark.slow
def test_three_sender_processes(
    start_collector: StartCollector, store_path: Path, tmp_path: Path
) -> None:
    start_collector()
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(
            target=_workers.run_sender,
            args=(str(tmp_path / "senders"), str(store_path), MASTER_KEY, label, COUNT),
        )
        for label in LABELS
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(60)
        assert proc.exitcode == 0

    log_dir = tmp_path / "collector-logs"
    expected = COUNT * len(LABELS)

    def arrived() -> int:
        return sum(
            1
            for e in read_stream(log_dir)
            if str(e.get("logger", "")).startswith("e2e.")
        )

    assert wait_for(lambda: arrived() >= expected, 20)
    entries = [e for e in read_stream(log_dir) if e["logger"].startswith("e2e.")]
    seen = Counter((e["instance"]["label"], e["message"]) for e in entries)
    for label in LABELS:
        for i in range(COUNT):
            key = (label, f"message {label} {i}")
            assert seen[key] == 1, key
        # The message's logger agrees with the instance that sent it.
        assert all(
            e["instance"]["label"] == e["logger"][len("e2e.") :] for e in entries
        )
    assert len(entries) == expected

    for label in LABELS:
        logs = list((tmp_path / "senders" / label / "logs").glob("2*/app.log"))
        assert len(logs) == 1
        local = logs[0].read_text(encoding="utf-8")
        for i in range(COUNT):
            assert f"message {label} {i}" in local
        # The drain finished before the local handlers closed.
        assert "Central log forwarding stopped" in local


@pytest.mark.slow
def test_collector_restart_mid_stream(
    start_collector: StartCollector, store_path: Path, tmp_path: Path
) -> None:
    first = start_collector()
    sender = LogSender(
        CentralLogConfig(enabled=True, flush_timeout=5),
        secrets=shared_secrets(store_path),
        instance_factory=lambda: {"label": "restart"},
        connect_backoff=(0.1, 0.5),
        discovery_backoff=(0.1, 0.5),
    )
    log = isolated_logger("restart.app", sender.handler)
    log_dir = tmp_path / "collector-logs"
    sender.start()
    try:
        for i in range(20):
            log.info("before %d", i)
        assert wait_for(
            lambda: len(messages(read_stream(log_dir), "restart.app")) == 20
        )
        first.stop()
        for i in range(20):
            log.info("during %d", i)
        second = start_collector()  # new port, re-published under a new epoch
        assert second.port != 0
        for i in range(20):
            log.info("after %d", i)
        assert wait_for(
            lambda: all(
                f"after {i}" in messages(read_stream(log_dir), "restart.app")
                for i in range(20)
            ),
            30,
        )
    finally:
        sender.stop()
    received = messages(read_stream(log_dir), "restart.app")
    assert len(received) == len(set(received)), "no record arrives twice"


def test_collector_level_independent_of_local_level(
    tmp_path: Path, store_path: Path
) -> None:
    """A lower forwarded level reaches the central stream, not the local log."""
    from konfig import Settings
    from konfig.logging.manager import LogManager

    settings = Settings(
        defaults={
            "logging": {
                "level": "INFO",
                "log_dir": str(tmp_path / "logs"),
                "console_output": "none",
                "central": {
                    "collector": True,
                    "listen": "127.0.0.1:0",
                    "advertise": "127.0.0.1",
                    "level": "DEBUG",
                },
            }
        }
    )
    manager = LogManager.from_settings(settings, app_name="Levels")
    manager.setup()
    try:
        assert manager.start_central_logging(settings, shared_secrets(store_path))
        logging.getLogger("levels.app").debug("debug only centrally")
        logging.getLogger("levels.app").info("info everywhere")
        assert wait_for(
            lambda: len(messages(read_stream(tmp_path / "logs"), "levels.app")) == 2
        )
    finally:
        manager.shutdown()
    assert logging.getLogger().level == logging.INFO
    assert manager.run_dir is not None
    local = (manager.run_dir / "app.log").read_text(encoding="utf-8")
    assert "info everywhere" in local
    assert "debug only centrally" not in local
