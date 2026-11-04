"""Shared fixtures for the centralised log forwarding tests."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from konfig.logging.central.collector import CentralCollector
from tests.test_logging.test_central._helpers import collector_config, shared_secrets

_ENV_VARS = (
    "KONFIG_LOG_CENTRAL",
    "KONFIG_LOG_COLLECTOR",
    "KONFIG_LOG_COLLECTOR_LISTEN",
    "KONFIG_LOG_COLLECTOR_ADVERTISE",
    "KONFIG_LOG_ENDPOINT",
    "KONFIG_LOG_CERT_SHA256",
    "KONFIG_LOG_TOKEN",
    "KONFIG_LOG_INSTANCE_LABEL",
    "KONFIG_AWS_SECRETS_MANAGER",
    "KONFIG_AWS_SETTINGS",
    "ECS_CONTAINER_METADATA_URI_V4",
    "KUBERNETES_SERVICE_HOST",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the host environment from switching the feature on or off."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
    root.setLevel(level)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "shared" / "secrets.enc"


@pytest.fixture
def start_collector(
    tmp_path: Path, store_path: Path
) -> Iterator[Callable[..., CentralCollector]]:
    started: list[CentralCollector] = []

    def _start(secrets: Any = "shared", **overrides: Any) -> CentralCollector:
        if secrets == "shared":
            secrets = shared_secrets(store_path)
        collector = CentralCollector(
            collector_config(**overrides),
            log_dir=tmp_path / "collector-logs",
            instance={"label": "collector", "hostname": "collector-host"},
            secrets=secrets,
        )
        collector.start()
        started.append(collector)
        return collector

    yield _start
    for collector in started:
        collector.stop()
