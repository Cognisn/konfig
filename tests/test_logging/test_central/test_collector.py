"""Tests for the collector: authentication, protocol enforcement, central stream."""

from __future__ import annotations

import json
import logging
import socket
import ssl
from collections.abc import Callable
from pathlib import Path

import pytest

from konfig.logging.central.collector import CentralCollector
from konfig.logging.central.config import CentralLogConfig
from konfig.logging.central.discovery import CollectorEntry, parse_entry
from konfig.logging.central.protocol import MAX_FRAME_BYTES, encode_frame, hello
from konfig.logging.central.sender import LogSender
from konfig.logging.central.tlsutil import client_context, fingerprint_matches
from tests.test_logging.test_central._helpers import (
    isolated_logger,
    messages,
    read_stream,
    shared_secrets,
    wait_for,
)

StartCollector = Callable[..., CentralCollector]


def _entry(collector: CentralCollector, store_path: Path) -> CollectorEntry:
    raw = shared_secrets(store_path).get("konfig.log_collector")
    assert raw is not None
    return parse_entry(raw)


class RawClient:
    """A hand-driven pinned TLS client for protocol-level tests."""

    def __init__(self, collector: CentralCollector) -> None:
        raw = socket.create_connection(("127.0.0.1", collector.port), timeout=10)
        self.sock = client_context().wrap_socket(raw)
        assert fingerprint_matches(
            self.sock.getpeercert(binary_form=True), collector.fingerprint
        )
        self._buffer = b""

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def read_line(self) -> bytes:
        while b"\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                return b""
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line

    def closed_by_peer(self) -> bool:
        try:
            return self.sock.recv(4096) == b""
        except (ConnectionError, ssl.SSLError, OSError):
            return True

    def close(self) -> None:
        self.sock.close()


def _welcomed(collector: CentralCollector, token: str) -> RawClient:
    client = RawClient(collector)
    client.send(encode_frame(hello(token, {"label": "raw"})))
    assert json.loads(client.read_line())["type"] == "welcome"
    return client


class TestAuthentication:
    def test_wrong_token_rejected_and_never_logged(
        self,
        start_collector: StartCollector,
        store_path: Path,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        caplog.set_level(logging.DEBUG)
        collector = start_collector()
        real = _entry(collector, store_path)
        wrong_token = "definitely-the-wrong-token-1234567890"
        sender = LogSender(
            CentralLogConfig(enabled=True, flush_timeout=0.5),
            override=CollectorEntry(real.endpoint, real.cert_sha256, wrong_token),
            connect_backoff=(30.0, 60.0),
        )
        log = isolated_logger("auth.wrong", sender.handler)
        sender.start()
        log.info("should not arrive")
        assert wait_for(lambda: "authentication failed" in caplog.text, 10)
        sender.stop()
        collector.stop()

        assert "rejected the connection: authentication failed" in caplog.text
        assert (
            messages(
                read_stream(store_path.parent.parent / "collector-logs"), "auth.wrong"
            )
            == []
        )
        captured = capsys.readouterr()
        stream = "".join(
            p.read_text()
            for p in (store_path.parent.parent / "collector-logs").rglob("*.log")
        )
        for token in (real.token, wrong_token):
            assert token not in caplog.text
            assert token not in captured.out + captured.err
            assert token not in stream

    def test_missing_token_rejected(self, start_collector: StartCollector) -> None:
        collector = start_collector()
        client = RawClient(collector)
        client.send(encode_frame({"type": "hello", "protocol": 1, "instance": {}}))
        reply = json.loads(client.read_line())
        assert reply == {"type": "reject", "reason": "authentication failed"}
        assert client.closed_by_peer()
        client.close()

    def test_unknown_protocol_rejected_with_reason(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector()
        token = _entry(collector, store_path).token
        client = RawClient(collector)
        client.send(encode_frame({"type": "hello", "protocol": 2, "token": token}))
        reply = json.loads(client.read_line())
        assert reply["type"] == "reject"
        assert "unsupported protocol version 2" in reply["reason"]
        assert token not in reply["reason"]
        client.close()

    def test_first_frame_must_be_hello(self, start_collector: StartCollector) -> None:
        client = RawClient(start_collector())
        client.send(encode_frame({"type": "log", "records": []}))
        assert json.loads(client.read_line())["type"] == "reject"
        client.close()


class TestFrameLimits:
    def test_oversize_frame_drops_connection(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector()
        client = _welcomed(collector, _entry(collector, store_path).token)
        client.send(b'{"type":"log","records":["' + b"x" * (MAX_FRAME_BYTES + 10))
        assert client.closed_by_peer()
        client.close()

    def test_invalid_json_drops_connection(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector()
        client = _welcomed(collector, _entry(collector, store_path).token)
        client.send(b"this is not json\n")
        assert client.closed_by_peer()
        client.close()

    def test_invalid_utf8_drops_connection(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector()
        client = _welcomed(collector, _entry(collector, store_path).token)
        client.send(b'{"type":"log","records":["\xff\xfe"]}\n')
        assert client.closed_by_peer()
        client.close()

    def test_handshake_timeout(self, start_collector: StartCollector) -> None:
        collector = start_collector(handshake_timeout=0.3)
        client = RawClient(collector)
        assert client.closed_by_peer()  # never sent a hello
        client.close()

    def test_idle_timeout(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector(idle_timeout=0.3)
        client = _welcomed(collector, _entry(collector, store_path).token)
        assert client.closed_by_peer()
        client.close()

    def test_connection_cap(
        self, start_collector: StartCollector, store_path: Path
    ) -> None:
        collector = start_collector(max_connections=1)
        token = _entry(collector, store_path).token
        first = _welcomed(collector, token)
        second = RawClient(collector)
        reply = json.loads(second.read_line())
        assert reply["type"] == "reject"
        assert "connection limit" in reply["reason"]
        first.close()
        second.close()


class TestCentralStream:
    def test_records_tagged_with_instance(
        self, start_collector: StartCollector, store_path: Path, tmp_path: Path
    ) -> None:
        collector = start_collector()
        client = _welcomed(collector, _entry(collector, store_path).token)
        record = {"timestamp": "t", "level": "INFO", "logger": "x", "message": "m"}
        client.send(encode_frame({"type": "log", "records": [record, "not a dict"]}))
        client.send(encode_frame({"type": "dropped", "count": 7}))
        log_dir = tmp_path / "collector-logs"
        assert wait_for(lambda: len(read_stream(log_dir)) >= 2, 10)
        client.close()
        entries = read_stream(log_dir)
        received = [e for e in entries if e.get("logger") == "x"][0]
        assert received["message"] == "m"
        assert received["instance"]["label"] == "raw"
        assert "received_at" in received
        gap = [e for e in entries if e.get("dropped") == 7][0]
        assert gap["level"] == "WARNING"
        assert gap["instance"]["label"] == "raw"

    def test_collector_own_records_in_stream(
        self, start_collector: StartCollector, tmp_path: Path
    ) -> None:
        collector = start_collector()
        assert collector.capture_handler is not None
        log = isolated_logger("collector.app", collector.capture_handler)
        log.info("from the collector itself")
        log.debug("below the forwarded level")
        log_dir = tmp_path / "collector-logs"
        assert wait_for(lambda: messages(read_stream(log_dir), "collector.app"), 10)
        entries = [e for e in read_stream(log_dir) if e["logger"] == "collector.app"]
        assert [e["message"] for e in entries] == ["from the collector itself"]
        assert entries[0]["instance"]["label"] == "collector"

    def test_stream_in_central_run_directory(
        self, start_collector: StartCollector, tmp_path: Path
    ) -> None:
        collector = start_collector()
        assert collector.stream_path is not None
        assert collector.stream_path.name == "central.log"
        assert (
            collector.stream_path.parent.parent
            == tmp_path / "collector-logs" / "central"
        )
        assert (tmp_path / "collector-logs" / "central" / "latest").exists()

    def test_retention_of_central_runs(self, tmp_path: Path, store_path: Path) -> None:
        central = tmp_path / "collector-logs" / "central"
        for name in (
            "2020-01-01T00-00-00",
            "2020-01-02T00-00-00",
            "2020-01-03T00-00-00",
        ):
            (central / name).mkdir(parents=True)
        config = CentralLogConfig(
            enabled=True,
            collector=True,
            listen="127.0.0.1:0",
            advertise="127.0.0.1",
            retention_runs=1,
        )
        collector = CentralCollector(
            config,
            log_dir=tmp_path / "collector-logs",
            instance={},
            secrets=shared_secrets(store_path),
        )
        collector.start()
        collector.stop()
        remaining = sorted(p.name for p in central.iterdir() if p.name[:2] == "20")
        assert "2020-01-01T00-00-00" not in remaining
        assert "2020-01-02T00-00-00" not in remaining
        assert (central / "state").is_dir()

    def test_listen_failure_raises(self, start_collector: StartCollector) -> None:
        first = start_collector()
        with pytest.raises(OSError):
            start_collector(listen=f"127.0.0.1:{first.port}")

    def test_oversized_instance_is_trimmed(
        self, start_collector: StartCollector, store_path: Path, tmp_path: Path
    ) -> None:
        collector = start_collector()
        client = RawClient(collector)
        token = _entry(collector, store_path).token
        instance = {"label": "big\nlabel", "hostname": "h", "pad": "x" * 20_000}
        client.send(encode_frame(hello(token, instance)))
        assert json.loads(client.read_line())["type"] == "welcome"
        client.send(encode_frame({"type": "log", "records": [{"logger": "big"}]}))
        log_dir = tmp_path / "collector-logs"
        assert wait_for(
            lambda: any(e.get("logger") == "big" for e in read_stream(log_dir))
        )
        client.close()
        entry = [e for e in read_stream(log_dir) if e.get("logger") == "big"][0]
        assert entry["instance"]["label"] == "big\nlabel"
        assert entry["instance"]["truncated"] is True
        assert "pad" not in entry["instance"]
