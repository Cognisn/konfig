"""Collector certificate management, fingerprints and TLS contexts.

The collector uses a self-signed certificate. Senders do not validate it
against any certificate authority; instead they pin its SHA-256 fingerprint,
which they learn from the shared secrets store or an environment override.
The private key never leaves the collector's state directory.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets as _secrets_mod
import ssl
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CERT_FILE = "collector-cert.pem"
KEY_FILE = "collector-key.pem"
TOKEN_FILE = "collector-token"

VALIDITY = timedelta(days=5 * 365)
RENEW_BEFORE = timedelta(days=30)

_OWNER_ONLY_FILE = stat.S_IRUSR | stat.S_IWUSR  # 0o600
_OWNER_ONLY_DIR = stat.S_IRWXU  # 0o700
_BINARY = getattr(os, "O_BINARY", 0)
_HEX_64 = re.compile(r"^[0-9A-F]{64}$")
_MAX_CN = 64


@dataclass(frozen=True)
class CollectorCertificate:
    """The collector's certificate and where its key lives."""

    cert_path: Path
    key_path: Path
    fingerprint: str
    not_after: datetime


# -- fingerprints -------------------------------------------------------------


def fingerprint_der(der: bytes) -> str:
    """SHA-256 of a DER certificate as uppercase colon-separated hex."""
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def normalise_fingerprint(text: str) -> str:
    """Accept colon-separated or plain hex and return the canonical form.

    Raises:
        ValueError: If the text is not a SHA-256 fingerprint.
    """
    compact = text.strip().replace(":", "").upper()
    if not _HEX_64.match(compact):
        raise ValueError("not a SHA-256 certificate fingerprint")
    return ":".join(compact[i : i + 2] for i in range(0, len(compact), 2))


def fingerprint_matches(der: Optional[bytes], expected: str) -> bool:
    """Constant-time comparison of a peer certificate against a pinned fingerprint."""
    if not der:
        return False
    actual = hashlib.sha256(der).digest()
    try:
        wanted = bytes.fromhex(normalise_fingerprint(expected).replace(":", ""))
    except ValueError:
        return False
    return hmac.compare_digest(actual, wanted)


# -- private files ------------------------------------------------------------


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` with mode 0700 (parents with the default mode)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=_OWNER_ONLY_DIR)
    except FileExistsError:
        if sys.platform != "win32":
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                logger.warning(
                    "Collector state directory %s has group/other permissions "
                    "(mode %o); run: chmod 700 %s",
                    path,
                    mode,
                    path,
                )
    return path


def write_private_file(path: Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path`` as an owner-only (0600) file.

    The temporary file is created with ``O_CREAT | O_EXCL`` and mode 0600,
    so the content is never readable by others, even briefly.
    """
    tmp = path.with_name(f".{path.name}.{_secrets_mod.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _BINARY, _OWNER_ONLY_FILE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def load_or_create_token(state_dir: Path) -> str:
    """Return the collector's access token, generating it on first start."""
    path = state_dir / TOKEN_FILE
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if token:
        return token
    token = _secrets_mod.token_urlsafe(32)
    write_private_file(path, token.encode("utf-8"))
    logger.info("Generated a new collector access token in %s", state_dir)
    return token


# -- certificates -------------------------------------------------------------


def _subject_alt_name(host: str) -> object:
    from cryptography import x509

    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def generate_certificate(
    common_name: str, now: Optional[datetime] = None
) -> tuple[bytes, bytes]:
    """Generate a self-signed EC P-256 certificate and key, both PEM-encoded."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = now or datetime.now(timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, common_name[:_MAX_CN] or "konfig")]
    )
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    try:
        san = _subject_alt_name(common_name)
        builder = builder.add_extension(
            x509.SubjectAlternativeName([san]),  # type: ignore[list-item]
            critical=False,
        )
    except ValueError:
        logger.debug("Advertise name %r is not usable as a SAN", common_name)
    cert = builder.sign(key, hashes.SHA256())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _load(cert_path: Path, key_path: Path) -> Optional[CollectorCertificate]:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except FileNotFoundError:
        return None
    except (ValueError, TypeError, OSError):
        logger.warning(
            "Collector certificate or key in %s is unreadable; regenerating",
            cert_path.parent,
        )
        return None
    return CollectorCertificate(
        cert_path=cert_path,
        key_path=key_path,
        fingerprint=fingerprint_der(cert.public_bytes(serialization.Encoding.DER)),
        not_after=cert.not_valid_after_utc,
    )


def load_or_create_certificate(
    state_dir: Path, common_name: str, now: Optional[datetime] = None
) -> CollectorCertificate:
    """Reuse the stored certificate, or generate one if missing or near expiry."""
    now = now or datetime.now(timezone.utc)
    cert_path = state_dir / CERT_FILE
    key_path = state_dir / KEY_FILE
    existing = _load(cert_path, key_path)
    if existing is not None:
        if existing.not_after - now > RENEW_BEFORE:
            return existing
        logger.info(
            "Collector certificate expires %s; generating a replacement",
            existing.not_after.isoformat(),
        )
    cert_pem, key_pem = generate_certificate(common_name, now)
    # Key first: a crash between the writes leaves a new key with an old
    # certificate, which fails to load and is regenerated next start.
    write_private_file(key_path, key_pem)
    write_private_file(cert_path, cert_pem)
    created = _load(cert_path, key_path)
    if created is None:
        raise RuntimeError(f"Could not load the generated certificate in {state_dir}")
    logger.info("Generated collector certificate (fingerprint %s)", created.fingerprint)
    return created


# -- SSL contexts -------------------------------------------------------------


def server_context(certificate: CollectorCertificate) -> ssl.SSLContext:
    """TLS server context for the collector (TLS 1.2 or later)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate.cert_path, certificate.key_path)
    return context


def client_context() -> ssl.SSLContext:
    """TLS client context for senders.

    SECURITY: certificate-authority validation and hostname checking are
    switched off because the collector's certificate is self-signed. This is
    safe ONLY because every connection made with this context is followed,
    straight after the handshake and before a single application byte is
    sent, by the mandatory pinned-fingerprint check in
    :func:`fingerprint_matches`. Never use this context without that check.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
