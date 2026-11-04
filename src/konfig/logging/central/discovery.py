"""Publish (collector) and read (sender) the collector's store entry.

The entry is one JSON string value under a single secrets key, so a reader
never sees it half-written. It carries the access token, so neither the raw
value nor anything parsed from it other than the endpoint and fingerprint
is ever logged or put into an exception.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from konfig.logging.central.config import parse_host_port
from konfig.logging.central.protocol import PROTOCOL_VERSION
from konfig.logging.central.tlsutil import normalise_fingerprint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectorEntry:
    """Connection details a sender needs to reach the collector."""

    endpoint: str
    cert_sha256: str
    token: str = field(repr=False)
    epoch: int = 0
    collector_host: str = ""
    published_at: str = ""
    protocol: int = PROTOCOL_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {
                "endpoint": self.endpoint,
                "cert_sha256": self.cert_sha256,
                "token": self.token,
                "epoch": self.epoch,
                "collector_host": self.collector_host,
                "published_at": self.published_at,
                "protocol": self.protocol,
            },
            separators=(",", ":"),
        )


def validate_details(endpoint: str, cert_sha256: str, token: str) -> CollectorEntry:
    """Validate connection details from any source.

    Raises:
        ValueError: With a message that names the bad field but never its
            value (the token in particular).
    """
    try:
        parse_host_port(endpoint)
    except ValueError as exc:
        raise ValueError(f"endpoint is invalid ({exc})") from None
    try:
        fingerprint = normalise_fingerprint(cert_sha256)
    except ValueError:
        raise ValueError("cert_sha256 is not a SHA-256 fingerprint") from None
    if not token:
        raise ValueError("token is empty")
    return CollectorEntry(endpoint=endpoint, cert_sha256=fingerprint, token=token)


def parse_entry(raw: str) -> CollectorEntry:
    """Parse a stored entry.

    Raises:
        ValueError: If the entry is malformed. The message never includes
            the raw value.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("entry is not valid JSON") from None
    if not isinstance(data, dict):
        raise ValueError("entry is not a JSON object")
    fields: dict[str, Any] = {}
    for name in ("endpoint", "cert_sha256", "token"):
        value = data.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"entry has no valid {name}")
        fields[name] = value
    entry = validate_details(fields["endpoint"], fields["cert_sha256"], fields["token"])
    epoch = data.get("epoch", 0)
    protocol = data.get("protocol", PROTOCOL_VERSION)
    return CollectorEntry(
        endpoint=entry.endpoint,
        cert_sha256=entry.cert_sha256,
        token=entry.token,
        epoch=epoch if isinstance(epoch, int) else 0,
        collector_host=str(data.get("collector_host") or ""),
        published_at=str(data.get("published_at") or ""),
        protocol=protocol if isinstance(protocol, int) else PROTOCOL_VERSION,
    )


def is_shared_backend(secrets: Any) -> bool:
    """False when the active secrets backend is local to this machine (OS keyring)."""
    from konfig.secrets.keyring_backend import KeyringBackend

    backend = getattr(secrets, "backend", None)
    return not isinstance(backend, KeyringBackend)


class EntryReader:
    """Reads the collector entry, logging a malformed entry only once."""

    def __init__(self, secrets: Any, store_key: str) -> None:
        self._secrets = secrets
        self._key = store_key
        self._reported_malformed = False
        self._reported_error = False

    def read(self) -> Optional[CollectorEntry]:
        """Return the current entry, or None if absent, unreadable or malformed."""
        try:
            self._secrets.refresh()
            raw = self._secrets.get(self._key)
        except Exception as exc:
            if not self._reported_error:
                logger.warning(
                    "Could not read the log collector entry %r from the secrets "
                    "store: %s",
                    self._key,
                    type(exc).__name__,
                )
                self._reported_error = True
            return None
        self._reported_error = False
        if raw is None:
            return None
        try:
            entry = parse_entry(raw)
        except ValueError as exc:
            if not self._reported_malformed:
                logger.warning(
                    "Ignoring malformed log collector entry %r: %s", self._key, exc
                )
                self._reported_malformed = True
            return None
        self._reported_malformed = False
        return entry


def publish_entry(
    secrets: Any,
    store_key: str,
    *,
    endpoint: str,
    cert_sha256: str,
    token: str,
    collector_host: str,
) -> CollectorEntry:
    """Write this collector's entry, replacing any earlier one.

    Warns when the entry being replaced came from a different collector
    host, which usually means two instances were nominated as collector.
    """
    existing = EntryReader(secrets, store_key).read()
    if existing is not None and existing.collector_host != collector_host:
        logger.warning(
            "Replacing the log collector entry %r published by another collector "
            "(%s, endpoint %s); check that only one instance is nominated as "
            "the collector",
            store_key,
            existing.collector_host or "unknown host",
            existing.endpoint,
        )
    entry = CollectorEntry(
        endpoint=endpoint,
        cert_sha256=cert_sha256,
        token=token,
        epoch=(existing.epoch + 1) if existing is not None else 1,
        collector_host=collector_host,
        published_at=datetime.now(timezone.utc).isoformat(),
    )
    secrets.set(store_key, entry.to_json())
    return entry
