"""Tests for publishing and discovering the collector entry."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from konfig.logging.central.collector import CentralCollector
from konfig.logging.central.config import CentralLogConfig
from konfig.logging.central.discovery import (
    CollectorEntry,
    EntryReader,
    parse_entry,
    publish_entry,
)
from konfig.logging.central.sender import LogSender
from konfig.secrets import Secrets
from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend
from konfig.secrets.keyring_backend import KeyringBackend
from tests.test_logging.test_central._helpers import (
    FakeSMClient,
    isolated_logger,
    messages,
    read_stream,
    shared_secrets,
    wait_for,
)

ARN = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:logs-AbCdEf"
FINGERPRINT = ":".join(["AB"] * 32)
StartCollector = Callable[..., CentralCollector]


def _discovering_sender(secrets: Secrets, label: str) -> LogSender:
    return LogSender(
        CentralLogConfig(enabled=True, flush_timeout=5),
        secrets=secrets,
        instance_factory=lambda: {"label": label},
        discovery_backoff=(0.1, 0.2),
        connect_backoff=(0.1, 0.2),
    )


class TestPublication:
    def test_collector_publishes_single_json_entry(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector()
        raw = shared_secrets(store_path).get("konfig.log_collector")
        assert raw is not None
        data = json.loads(raw)
        assert set(data) == {
            "endpoint",
            "cert_sha256",
            "token",
            "epoch",
            "collector_host",
            "published_at",
            "protocol",
        }
        assert data["endpoint"] == f"127.0.0.1:{collector.port}"
        assert data["cert_sha256"] == collector.fingerprint
        assert data["epoch"] == 1
        assert data["protocol"] == 1
        assert data["published_at"].endswith("+00:00")

    def test_restart_keeps_token_and_certificate_and_bumps_epoch(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        first = start_collector()
        before = parse_entry(
            shared_secrets(store_path).get("konfig.log_collector") or ""
        )
        first.stop()
        start_collector()
        after = parse_entry(
            shared_secrets(store_path).get("konfig.log_collector") or ""
        )
        assert after.epoch == before.epoch + 1
        assert after.token == before.token
        assert after.cert_sha256 == before.cert_sha256

    def test_replacing_another_collectors_entry_warns(
        self, store_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secrets = shared_secrets(store_path)
        other = CollectorEntry(
            "other:9020",
            FINGERPRINT,
            "other-token",
            epoch=4,
            collector_host="other-host",
        )
        secrets.set("konfig.log_collector", other.to_json())
        with caplog.at_level(logging.WARNING):
            entry = publish_entry(
                secrets,
                "konfig.log_collector",
                endpoint="me:9020",
                cert_sha256=FINGERPRINT,
                token="my-token",
                collector_host="my-host",
            )
        assert entry.epoch == 5
        assert "published by another collector (other-host" in caplog.text
        assert "other-token" not in caplog.text and "my-token" not in caplog.text

    def test_same_host_republish_does_not_warn(
        self, store_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secrets = shared_secrets(store_path)
        for _ in range(2):
            with caplog.at_level(logging.WARNING):
                publish_entry(
                    secrets,
                    "konfig.log_collector",
                    endpoint="me:9020",
                    cert_sha256=FINGERPRINT,
                    token="t",
                    collector_host="my-host",
                )
        assert "another collector" not in caplog.text

    def test_keyring_backend_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store: dict[str, str] = {}
        backend = MagicMock(spec=KeyringBackend)
        backend.get.side_effect = store.get
        backend.set.side_effect = store.__setitem__
        collector = CentralCollector(
            CentralLogConfig(
                enabled=True,
                collector=True,
                listen="127.0.0.1:0",
                advertise="127.0.0.1",
            ),
            log_dir=tmp_path / "logs",
            instance={},
            secrets=Secrets(backend=backend),
        )
        with caplog.at_level(logging.WARNING):
            collector.start()
        collector.stop()
        assert "OS keyring" in caplog.text

    def test_missing_advertise_warns(
        self, start_collector: StartCollector, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            start_collector(advertise=None)
        assert "stable service name" in caplog.text


class TestReading:
    @pytest.mark.parametrize(
        "raw",
        [
            "not json at all secret-in-garbage",
            "[]",
            json.dumps({"endpoint": "x:1", "cert_sha256": FINGERPRINT}),
            json.dumps(
                {"endpoint": "x:1", "cert_sha256": "nope", "token": "secret-in-garbage"}
            ),
            json.dumps(
                {
                    "endpoint": "no-port",
                    "cert_sha256": FINGERPRINT,
                    "token": "secret-in-garbage",
                }
            ),
        ],
    )
    def test_malformed_entry_is_absent_and_logged_once(
        self, store_path: Path, raw: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        secrets = shared_secrets(store_path)
        secrets.set("konfig.log_collector", raw)
        reader = EntryReader(secrets, "konfig.log_collector")
        with caplog.at_level(logging.WARNING):
            assert reader.read() is None
            assert reader.read() is None
        warnings = [r for r in caplog.records if "malformed" in r.getMessage()]
        assert len(warnings) == 1
        assert "secret-in-garbage" not in caplog.text

    def test_absent_entry(self, store_path: Path) -> None:
        assert (
            EntryReader(shared_secrets(store_path), "konfig.log_collector").read()
            is None
        )

    def test_store_errors_are_absent(self, caplog: pytest.LogCaptureFixture) -> None:
        secrets = MagicMock()
        secrets.get.side_effect = TimeoutError("lock timeout")
        with caplog.at_level(logging.WARNING):
            assert EntryReader(secrets, "k").read() is None
        assert "TimeoutError" in caplog.text

    def test_entry_repr_hides_token(self) -> None:
        assert "hidden-token" not in repr(
            CollectorEntry("x:1", FINGERPRINT, "hidden-token")
        )


class TestDiscovery:
    def test_sender_discovers_via_shared_encrypted_file(
        self, start_collector: StartCollector, store_path: Path, tmp_path: Path
    ) -> None:
        start_collector()
        sender = _discovering_sender(shared_secrets(store_path), "file-sender")
        log = isolated_logger("discovery.file", sender.handler)
        sender.start()
        log.info("via the shared file")
        log_dir = tmp_path / "collector-logs"
        assert wait_for(lambda: messages(read_stream(log_dir), "discovery.file"))
        sender.stop()
        entry = [e for e in read_stream(log_dir) if e["logger"] == "discovery.file"][0]
        assert entry["instance"]["label"] == "file-sender"

    def test_sender_waits_for_late_collector(
        self, start_collector: StartCollector, store_path: Path, tmp_path: Path
    ) -> None:
        sender = _discovering_sender(shared_secrets(store_path), "early")
        log = isolated_logger("discovery.late", sender.handler)
        sender.start()
        log.info("logged before the collector existed")
        assert wait_for(lambda: not sender.connected, 1)
        start_collector()
        log_dir = tmp_path / "collector-logs"
        assert wait_for(lambda: messages(read_stream(log_dir), "discovery.late"))
        sender.stop()

    def test_sender_discovers_via_aws_bundle(
        self, start_collector: StartCollector, tmp_path: Path
    ) -> None:
        client = FakeSMClient("{}")

        def bundle_secrets() -> Secrets:
            return Secrets(backend=AWSSecretsBundleBackend(ARN, ttl=300, client=client))

        start_collector(secrets=bundle_secrets())
        assert "konfig.log_collector" in json.loads(client.secret_string)
        sender = _discovering_sender(bundle_secrets(), "aws-sender")
        log = isolated_logger("discovery.aws", sender.handler)
        sender.start()
        log.info("via the AWS bundle")
        log_dir = tmp_path / "collector-logs"
        assert wait_for(lambda: messages(read_stream(log_dir), "discovery.aws"))
        sender.stop()

    def test_sender_rereads_bundle_cache_after_failure(
        self, start_collector: StartCollector, tmp_path: Path
    ) -> None:
        # The sender's bundle cache holds a stale entry pointing nowhere; the
        # connection failure must trigger refresh() and a fresh read.
        client = FakeSMClient(
            json.dumps(
                {
                    "konfig.log_collector": CollectorEntry(
                        "127.0.0.1:1", FINGERPRINT, "stale", collector_host="old"
                    ).to_json()
                }
            )
        )
        sender_secrets = Secrets(
            backend=AWSSecretsBundleBackend(ARN, ttl=3600, client=client)
        )
        sender = _discovering_sender(sender_secrets, "stale")
        log = isolated_logger("discovery.stale", sender.handler)
        sender.start()
        log.info("after a stale read")
        time.sleep(0.3)  # let it read the stale entry and fail at least once
        assert not sender.connected
        start_collector(
            secrets=Secrets(backend=AWSSecretsBundleBackend(ARN, client=client))
        )
        log_dir = tmp_path / "collector-logs"
        assert wait_for(lambda: messages(read_stream(log_dir), "discovery.stale"))
        sender.stop()
