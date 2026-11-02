"""Tests for collector certificates, fingerprints and pinning."""

from __future__ import annotations

import logging
import socket
import ssl
import stat
import sys
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from konfig.logging.central.config import CentralLogConfig
from konfig.logging.central.discovery import CollectorEntry
from konfig.logging.central.sender import LogSender
from konfig.logging.central.tlsutil import (
    CERT_FILE,
    KEY_FILE,
    TOKEN_FILE,
    ensure_private_dir,
    fingerprint_der,
    fingerprint_matches,
    load_or_create_certificate,
    load_or_create_token,
    normalise_fingerprint,
    server_context,
)
from tests.test_logging.test_central._helpers import isolated_logger, wait_for

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestFingerprints:
    def test_format(self) -> None:
        fp = fingerprint_der(b"certificate bytes")
        parts = fp.split(":")
        assert len(parts) == 32
        assert all(len(p) == 2 and p == p.upper() for p in parts)

    def test_normalise_accepts_plain_and_lower_hex(self) -> None:
        fp = fingerprint_der(b"x")
        assert normalise_fingerprint(fp.replace(":", "").lower()) == fp
        assert normalise_fingerprint(f"  {fp.lower()}  ") == fp

    @pytest.mark.parametrize("text", ["", "AB:CD", "Z" * 64, "AB" * 33])
    def test_normalise_rejects_garbage(self, text: str) -> None:
        with pytest.raises(ValueError):
            normalise_fingerprint(text)

    def test_matches(self) -> None:
        der = b"some der"
        assert fingerprint_matches(der, fingerprint_der(der))
        assert fingerprint_matches(der, fingerprint_der(der).replace(":", ""))
        assert not fingerprint_matches(der, fingerprint_der(b"other"))
        assert not fingerprint_matches(None, fingerprint_der(der))
        assert not fingerprint_matches(der, "not a fingerprint")


class TestStateFiles:
    @posix_only
    def test_permissions_at_creation(self, tmp_path: Path) -> None:
        state = ensure_private_dir(tmp_path / "central" / "state")
        assert _mode(state) == 0o700
        load_or_create_token(state)
        load_or_create_certificate(state, "log-collector")
        for name in (CERT_FILE, KEY_FILE, TOKEN_FILE):
            assert _mode(state / name) == 0o600, name

    @posix_only
    def test_files_created_owner_only_not_chmodded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        calls: list[object] = []
        monkeypatch.setattr(os, "chmod", lambda *a, **k: calls.append(a))
        state = ensure_private_dir(tmp_path / "state")
        load_or_create_token(state)
        load_or_create_certificate(state, "log-collector")
        assert calls == []

    @posix_only
    def test_loose_existing_directory_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        state = tmp_path / "state"
        state.mkdir(mode=0o755)
        state.chmod(0o755)
        with caplog.at_level(logging.WARNING):
            ensure_private_dir(state)
        assert "chmod 700" in caplog.text

    def test_token_reused_across_restarts(self, tmp_path: Path) -> None:
        state = ensure_private_dir(tmp_path / "state")
        first = load_or_create_token(state)
        assert len(first) >= 40
        assert load_or_create_token(state) == first

    def test_certificate_reused_across_restarts(self, tmp_path: Path) -> None:
        state = ensure_private_dir(tmp_path / "state")
        first = load_or_create_certificate(state, "log-collector")
        second = load_or_create_certificate(state, "log-collector")
        assert first.fingerprint == second.fingerprint

    def test_certificate_properties(self, tmp_path: Path) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec

        state = ensure_private_dir(tmp_path / "state")
        created = load_or_create_certificate(state, "log-collector")
        cert = x509.load_pem_x509_certificate((state / CERT_FILE).read_bytes())
        public_key = cert.public_key()
        assert isinstance(public_key, ec.EllipticCurvePublicKey)
        assert public_key.curve.name == "secp256r1"
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert cn[0].value == "log-collector"
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        assert san.value.get_values_for_type(x509.DNSName) == ["log-collector"]
        lifetime = created.not_after - datetime.now(timezone.utc)
        assert timedelta(days=5 * 365 - 2) < lifetime <= timedelta(days=5 * 365)

    def test_ip_advertise_gets_ip_san(self, tmp_path: Path) -> None:
        import ipaddress

        from cryptography import x509

        state = ensure_private_dir(tmp_path / "state")
        load_or_create_certificate(state, "10.1.2.3")
        cert = x509.load_pem_x509_certificate((state / CERT_FILE).read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        assert san.value.get_values_for_type(x509.IPAddress) == [
            ipaddress.ip_address("10.1.2.3")
        ]

    def test_regenerated_near_expiry(self, tmp_path: Path) -> None:
        state = ensure_private_dir(tmp_path / "state")
        now = datetime.now(timezone.utc)
        # Issued so that it expires in 10 days: inside the 30-day renewal window.
        old = load_or_create_certificate(
            state, "log-collector", now=now - timedelta(days=5 * 365 - 10)
        )
        renewed = load_or_create_certificate(state, "log-collector", now=now)
        assert renewed.fingerprint != old.fingerprint
        assert renewed.not_after > now + timedelta(days=365)

    def test_not_regenerated_outside_window(self, tmp_path: Path) -> None:
        state = ensure_private_dir(tmp_path / "state")
        now = datetime.now(timezone.utc)
        old = load_or_create_certificate(
            state, "log-collector", now=now - timedelta(days=5 * 365 - 60)
        )
        assert load_or_create_certificate(state, "log-collector").fingerprint == (
            old.fingerprint
        )

    def test_corrupt_files_regenerated(self, tmp_path: Path) -> None:
        state = ensure_private_dir(tmp_path / "state")
        first = load_or_create_certificate(state, "log-collector")
        (state / CERT_FILE).write_text("garbage")
        assert load_or_create_certificate(state, "log-collector").fingerprint != (
            first.fingerprint
        )


class RecordingTLSServer:
    """A TLS server that records what one client connection did.

    It counts the TCP accept and the server-side handshake outcome, notes the
    negotiated TLS version and how the connection ended, and keeps every
    application byte the client sends.
    """

    def __init__(self, state_dir: Path) -> None:
        self.certificate = load_or_create_certificate(
            ensure_private_dir(state_dir), "127.0.0.1"
        )
        self._context = server_context(self.certificate)
        # A TLS 1.3 server writes its session tickets after the client's side
        # of the handshake has already finished. A client that hangs up at once,
        # as the sender must on a pin mismatch, leaves them unread; Windows then
        # aborts the connection and the server's handshake fails while writing
        # them. Without tickets the server's handshake ends when it reads the
        # client's Finished, so its outcome no longer races the client's close.
        self._context.num_tickets = 0
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self.port = self._listener.getsockname()[1]
        self.received = b""
        self.accepted = 0
        self.handshakes = 0
        self.handshake_errors: list[str] = []
        self.tls_version: str | None = None
        self.ended: str | None = None  # "eof", or the exception that ended it
        self.closed = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            self.closed.set()
            return
        self.accepted += 1
        conn.settimeout(10)
        try:
            try:
                tls = self._context.wrap_socket(conn, server_side=True)
            except (OSError, ssl.SSLError) as exc:
                self.handshake_errors.append(type(exc).__name__)
                return
            with tls:
                self.handshakes += 1
                self.tls_version = tls.version()
                while True:
                    try:
                        chunk = tls.recv(65536)
                    except (OSError, ssl.SSLError) as exc:
                        self.ended = type(exc).__name__
                        break
                    if not chunk:
                        self.ended = "eof"
                        break
                    self.received += chunk
        finally:
            conn.close()
            self.closed.set()

    def close(self) -> None:
        self._listener.close()


@pytest.fixture
def recording_server(tmp_path: Path) -> Iterator[RecordingTLSServer]:
    server = RecordingTLSServer(tmp_path / "server-state")
    yield server
    server.close()


def _sender_for(server: RecordingTLSServer, fingerprint: str) -> LogSender:
    entry = CollectorEntry(
        endpoint=f"127.0.0.1:{server.port}",
        cert_sha256=fingerprint,
        token="pin-test-token",
    )
    return LogSender(
        CentralLogConfig(enabled=True, flush_timeout=0.5),
        override=entry,
        connect_backoff=(30.0, 60.0),
    )


def test_pin_mismatch_closes_before_any_byte(
    recording_server: RecordingTLSServer, caplog: pytest.LogCaptureFixture
) -> None:
    wrong = fingerprint_der(b"some other certificate")
    sender = _sender_for(recording_server, wrong)
    log = isolated_logger("pin.mismatch", sender.handler)
    with caplog.at_level(logging.WARNING, logger="konfig.logging.central"):
        sender.start()
        log.info("must never be sent")
        assert recording_server.closed.wait(10)
        sender.stop()
    # One TCP connection, one completed TLS handshake, then the sender hung up
    # without sending a single application byte.
    assert recording_server.accepted == 1
    assert recording_server.handshake_errors == []
    assert recording_server.handshakes == 1
    assert recording_server.tls_version in ("TLSv1.2", "TLSv1.3")
    assert recording_server.ended in ("eof", "ConnectionResetError")
    assert recording_server.received == b""
    assert not sender.connected
    assert "does not match the pinned fingerprint" in caplog.text
    assert "pin-test-token" not in caplog.text


def test_pin_match_sends_hello(recording_server: RecordingTLSServer) -> None:
    # Positive control for the test above: with the right pin, bytes do flow.
    sender = _sender_for(recording_server, recording_server.certificate.fingerprint)
    sender.start()
    try:
        assert wait_for(lambda: b"\n" in recording_server.received, 10)
        assert recording_server.received.startswith(b'{"type":"hello"')
    finally:
        sender.stop()
