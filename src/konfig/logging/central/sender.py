"""Queue-based forwarding handler and the background shipping thread.

The application thread only ever converts a record to a dict and appends it
to a bounded in-memory queue; when the queue is full the oldest record is
dropped and counted. Everything that can be slow or fail (discovery, DNS,
TCP, TLS, authentication, sending) happens on one daemon thread.
"""

from __future__ import annotations

import logging
import random
import select
import socket
import ssl
import threading
import time
from collections import deque
from collections.abc import Callable
from logging.handlers import QueueHandler
from typing import Any, Optional

from konfig.logging.central.config import CentralLogConfig, parse_host_port
from konfig.logging.central.discovery import CollectorEntry, EntryReader
from konfig.logging.central.protocol import (
    MAX_BATCH_BYTES,
    MAX_BATCH_RECORDS,
    MAX_FRAME_BYTES,
    TYPE_REJECT,
    TYPE_WELCOME,
    ProtocolError,
    check_protocol,
    decode_frame,
    dropped,
    encode_frame,
    encode_log_batch,
    encode_record,
    hello,
    record_to_wire,
)
from konfig.logging.central.tlsutil import client_context, fingerprint_matches

logger = logging.getLogger(__name__)

CENTRAL_LOGGER_PREFIX = "konfig.logging.central"

CONNECT_TIMEOUT = 5.0
HANDSHAKE_TIMEOUT = 10.0
SEND_TIMEOUT = 10.0
CONNECT_BACKOFF = (1.0, 60.0)
DISCOVERY_BACKOFF = (15.0, 300.0)
POLL_INTERVAL = 0.25


def is_central_record(record: logging.LogRecord) -> bool:
    """True for records from konfig's own central logging modules."""
    name = record.name
    return name == CENTRAL_LOGGER_PREFIX or name.startswith(CENTRAL_LOGGER_PREFIX + ".")


def _not_central(record: logging.LogRecord) -> bool:
    return not is_central_record(record)


class DropOldestQueue:
    """Bounded, thread-safe queue that drops its oldest item when full.

    ``put_nowait`` never blocks, so a logging call can never be held up by a
    slow or absent consumer.
    """

    def __init__(self, maxsize: int) -> None:
        self._maxsize = max(1, maxsize)
        self._items: deque[Any] = deque()
        self._cond = threading.Condition(threading.Lock())
        self._dropped = 0

    def put_nowait(self, item: Any) -> None:
        with self._cond:
            if len(self._items) >= self._maxsize:
                self._items.popleft()
                self._dropped += 1
            self._items.append(item)
            self._cond.notify()

    def put(
        self, item: Any, block: bool = True, timeout: Optional[float] = None
    ) -> None:
        self.put_nowait(item)

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        items = self.take(1, timeout if block else 0)
        if not items:
            raise IndexError("queue is empty")
        return items[0]

    def take(self, limit: int, timeout: Optional[float]) -> list[Any]:
        """Remove up to ``limit`` items, waiting up to ``timeout`` for the first."""
        with self._cond:
            if not self._items and timeout:
                self._cond.wait(timeout)
            count = min(limit, len(self._items))
            return [self._items.popleft() for _ in range(count)]

    def take_dropped(self) -> int:
        """Return and reset the number of items dropped since the last call."""
        with self._cond:
            count, self._dropped = self._dropped, 0
            return count

    @property
    def dropped(self) -> int:
        with self._cond:
            return self._dropped

    def wake(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def __len__(self) -> int:
        with self._cond:
            return len(self._items)


class ForwardingHandler(QueueHandler):
    """Root-logger handler that queues records for forwarding.

    Records from konfig's own central logging modules are filtered out, so
    forwarding problems cannot feed back into the forwarding queue.
    """

    queue: DropOldestQueue

    def __init__(self, queue: DropOldestQueue, level: int = logging.INFO) -> None:
        super().__init__(queue)
        self.setLevel(level)
        self.addFilter(_not_central)

    def prepare(self, record: logging.LogRecord) -> Any:
        # Capture the formatted message and exception text now, at emit time.
        return record_to_wire(record)


class _ConnectFailure(Exception):
    """A connection attempt failed; the message is safe to log."""


class LogSender:
    """Ships queued records to the collector from a daemon thread.

    Args:
        config: Resolved central logging config.
        secrets: A ``Secrets`` instance for discovery, or None when only an
            override is used.
        instance_factory: Called once on the background thread to build the
            identity block sent in the hello.
        override: Connection details that replace discovery entirely.
    """

    def __init__(
        self,
        config: CentralLogConfig,
        *,
        secrets: Any = None,
        instance_factory: Callable[[], dict[str, Any]] = dict,
        override: Optional[CollectorEntry] = None,
        connect_backoff: tuple[float, float] = CONNECT_BACKOFF,
        discovery_backoff: tuple[float, float] = DISCOVERY_BACKOFF,
    ) -> None:
        self._config = config
        self._queue = DropOldestQueue(config.queue_size)
        self.handler = ForwardingHandler(self._queue, config.level)
        self._reader = (
            EntryReader(secrets, config.store_key) if secrets is not None else None
        )
        self._override = override
        self._instance_factory = instance_factory
        self._instance: dict[str, Any] = {}
        self._context: Optional[ssl.SSLContext] = None
        self._connect_backoff = connect_backoff
        self._discovery_backoff = discovery_backoff

        self._entry: Optional[CollectorEntry] = None
        self._sock: Optional[ssl.SSLSocket] = None
        self._backlog: deque[tuple[str, int]] = deque()
        self._pending: Optional[tuple[bytes, int, int]] = None
        self._failures = 0
        self._discovery_delay = discovery_backoff[0]
        self._delay = 0.0
        self._warned_failure = False
        self._warned_waiting = False
        self._sent = 0

        self._stopping = threading.Event()
        self._deadline = 0.0
        self._thread = threading.Thread(
            target=self._run, name="konfig-log-sender", daemon=True
        )

    # -- public API -----------------------------------------------------------

    @property
    def sent(self) -> int:
        """Number of records successfully handed to the collector connection."""
        return self._sent

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def start(self) -> None:
        self._thread.start()

    def unsent(self) -> int:
        pending = self._pending[1] if self._pending is not None else 0
        return len(self._queue) + len(self._backlog) + pending

    def stop(self) -> int:
        """Drain for up to ``flush_timeout`` seconds, then stop.

        The handler should already be detached so no new records arrive.

        Returns:
            The number of records left unsent.
        """
        self._deadline = time.monotonic() + self._config.flush_timeout
        self._stopping.set()
        self._queue.wake()
        if self._thread.is_alive():
            self._thread.join(self._config.flush_timeout + 1.0)
        return self.unsent()

    # -- background thread ----------------------------------------------------

    def _run(self) -> None:
        try:
            self._instance = self._instance_factory()
        except Exception:
            logger.debug("Could not detect the instance identity", exc_info=True)
            self._instance = {}
        try:
            self._context = client_context()
            while True:
                if self._stopping.is_set() and (
                    self._idle() or time.monotonic() >= self._deadline
                ):
                    break
                if self._sock is None:
                    if self._connect():
                        continue
                    if self._stopping.is_set():
                        break  # collector unreachable: give up the drain
                    self._stopping.wait(self._delay)
                    continue
                self._ship()
        except Exception:
            # Never let the shipping thread die silently; the application
            # carries on, only forwarding stops.
            logger.exception("Central log forwarding thread failed")
        finally:
            self._disconnect()

    def _idle(self) -> bool:
        return (
            self._pending is None
            and not self._backlog
            and len(self._queue) == 0
            and self._queue.dropped == 0
        )

    # -- connection -------------------------------------------------------------

    def _current_entry(self) -> Optional[CollectorEntry]:
        if self._override is not None:
            return self._override
        if self._entry is None and self._reader is not None:
            self._entry = self._reader.read()
        return self._entry

    def _connect(self) -> bool:
        entry = self._current_entry()
        if entry is None:
            if not self._warned_waiting:
                logger.info(
                    "Waiting for the log collector to publish its connection "
                    "details (secrets key %r)",
                    self._config.store_key,
                )
                self._warned_waiting = True
            self._delay = self._discovery_delay
            self._discovery_delay = min(
                self._discovery_delay * 2, self._discovery_backoff[1]
            )
            return False
        self._discovery_delay = self._discovery_backoff[0]
        try:
            self._sock = self._open(entry)
        except _ConnectFailure as exc:
            self._connection_failed(entry.endpoint, str(exc))
            return False
        except (OSError, ProtocolError, ValueError) as exc:
            self._connection_failed(entry.endpoint, type(exc).__name__)
            return False
        self._failures = 0
        self._warned_failure = False
        self._warned_waiting = False
        logger.info(
            "Forwarding logs to collector %s (certificate %s)",
            entry.endpoint,
            entry.cert_sha256,
        )
        return True

    def _open(self, entry: CollectorEntry) -> ssl.SSLSocket:
        assert self._context is not None
        # DNS is resolved on every attempt, so a collector that moves behind
        # a stable service name is found again.
        host, port = parse_host_port(entry.endpoint)
        raw = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        try:
            tls = self._context.wrap_socket(raw)
        except BaseException:
            raw.close()
            raise
        try:
            # MANDATORY PIN CHECK. The client context performs no certificate
            # validation, so this comparison is the only thing that proves we
            # are talking to the real collector. It must happen before any
            # application byte (the hello, which carries the token) is sent.
            if not fingerprint_matches(
                tls.getpeercert(binary_form=True), entry.cert_sha256
            ):
                raise _ConnectFailure(
                    "collector certificate does not match the pinned fingerprint"
                )
            tls.settimeout(HANDSHAKE_TIMEOUT)
            tls.sendall(encode_frame(hello(entry.token, self._instance)))
            reply = decode_frame(self._read_line(tls))
            if reply["type"] == TYPE_REJECT:
                reason = str(reply.get("reason", ""))[:200]
                raise _ConnectFailure(f"collector rejected the connection: {reason}")
            if reply["type"] != TYPE_WELCOME:
                raise _ConnectFailure("collector sent an unexpected reply")
            check_protocol(reply)
            tls.settimeout(SEND_TIMEOUT)
            return tls
        except BaseException:
            tls.close()
            raise

    @staticmethod
    def _read_line(sock: ssl.SSLSocket) -> bytes:
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        data = b""
        while not data.endswith(b"\n"):
            if len(data) > MAX_FRAME_BYTES or time.monotonic() > deadline:
                raise _ConnectFailure("collector reply was too long or too slow")
            chunk = sock.recv(4096)
            if not chunk:
                raise _ConnectFailure(
                    "collector closed the connection during the hello"
                )
            data += chunk
        return data

    def _connection_failed(self, endpoint: str, reason: str) -> None:
        self._disconnect()
        self._failures += 1
        if self._override is None:
            self._entry = None  # re-read the store before the next attempt
        base, cap = self._connect_backoff
        delay = min(cap, base * (2 ** min(self._failures - 1, 16)))
        self._delay = min(cap, delay * random.uniform(0.8, 1.2))
        if not self._warned_failure:
            logger.warning(
                "Cannot forward logs to collector %s: %s; retrying in the background",
                endpoint,
                reason,
            )
            self._warned_failure = True
        else:
            logger.debug("Collector %s still unavailable: %s", endpoint, reason)

    def _disconnect(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _peer_closed(self) -> bool:
        """Detect a collector that has closed the connection since the last send."""
        sock = self._sock
        if sock is None:
            return True
        try:
            readable, _, _ = select.select([sock], [], [], 0)
        except (OSError, ValueError):
            return True
        if not readable:
            return False
        sock.setblocking(False)
        try:
            data = sock.recv(1)
        except (ssl.SSLWantReadError, BlockingIOError):
            return False  # only TLS housekeeping was waiting
        except OSError:
            return True
        finally:
            try:
                sock.settimeout(SEND_TIMEOUT)
            except OSError:
                pass
        # EOF, or unexpected data from a collector that never sends after
        # its welcome: either way, start a fresh connection.
        del data
        return True

    # -- shipping ---------------------------------------------------------------

    def _next_batch(self) -> list[str]:
        parts: list[str] = []
        size = 0
        while len(parts) < MAX_BATCH_RECORDS:
            if not self._backlog:
                wait = 0.0 if parts or self._stopping.is_set() else POLL_INTERVAL
                items = self._queue.take(MAX_BATCH_RECORDS - len(parts), wait)
                if not items:
                    break
                for item in items:
                    try:
                        text = encode_record(item)
                    except (TypeError, ValueError):
                        continue
                    self._backlog.append((text, len(text.encode("utf-8")) + 1))
                continue
            text, nbytes = self._backlog[0]
            if parts and size + nbytes > MAX_BATCH_BYTES:
                break
            self._backlog.popleft()
            parts.append(text)
            size += nbytes
        return parts

    def _ship(self) -> None:
        if self._pending is None:
            lost = self._queue.take_dropped()
            parts = self._next_batch()
            if not parts and not lost:
                return
            frame = b""
            if lost:
                frame += encode_frame(dropped(lost))
            if parts:
                frame += encode_log_batch(parts)
            self._pending = (frame, len(parts), lost)

        endpoint = self._entry.endpoint if self._entry else "collector"
        if self._override is not None:
            endpoint = self._override.endpoint
        if self._peer_closed():
            self._connection_failed(endpoint, "collector closed the connection")
            return
        assert self._sock is not None
        try:
            self._sock.sendall(self._pending[0])
        except OSError as exc:
            self._connection_failed(endpoint, type(exc).__name__)
            return
        self._sent += self._pending[1]
        self._pending = None
