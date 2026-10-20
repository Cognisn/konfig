"""TLS listener that receives forwarded records and writes the central stream.

The listener runs an asyncio server on its own event loop in a daemon
thread, so it works the same under sync and async applications. Received
records, and the collector's own application records, are handed to a
single writer thread so lines in the central stream never interleave.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import socket
import ssl
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from konfig.logging.central.config import (
    DEFAULT_PORT,
    CentralLogConfig,
    parse_host_port,
)
from konfig.logging.central.discovery import is_shared_backend, publish_entry
from konfig.logging.central.protocol import (
    MAX_FRAME_BYTES,
    TYPE_DROPPED,
    TYPE_HELLO,
    TYPE_LOG,
    ProtocolError,
    check_protocol,
    decode_frame,
    encode_frame,
    record_to_wire,
    reject,
    welcome,
)
from konfig.logging.central.sender import DropOldestQueue
from konfig.logging.central.tlsutil import (
    CollectorCertificate,
    ensure_private_dir,
    load_or_create_certificate,
    load_or_create_token,
    server_context,
)
from konfig.logging.run_directory import cleanup_old_runs, create_run_directory

logger = logging.getLogger(__name__)

CENTRAL_DIR = "central"
STATE_DIR = "state"
STREAM_FILE = "central.log"
WRITER_QUEUE_SIZE = 100_000
START_TIMEOUT = 10.0
STOP_TIMEOUT = 5.0
_MAX_LABEL = 200
_MAX_INSTANCE_BYTES = 8 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_endpoint(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


class CentralWriter:
    """The single writer of the central stream, fed by a non-blocking queue."""

    def __init__(self, path: Path, max_bytes: int, backup_count: int) -> None:
        self._path = path
        self._queue = DropOldestQueue(WRITER_QUEUE_SIZE)
        self._handler = RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="konfig-log-collector-writer", daemon=True
        )

    @property
    def path(self) -> Path:
        return self._path

    def put(self, entry: dict[str, Any]) -> None:
        self._queue.put_nowait(entry)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = STOP_TIMEOUT) -> None:
        self._stopping.set()
        self._queue.wake()
        if self._thread.is_alive():
            self._thread.join(timeout)
        self._handler.close()

    def _write(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, ensure_ascii=False, default=str)
        self._handler.emit(logging.makeLogRecord({"msg": line}))

    def _run(self) -> None:
        while True:
            items = self._queue.take(500, 0.25)
            lost = self._queue.take_dropped()
            if lost:
                self._write(
                    {
                        "timestamp": _utc_now(),
                        "level": "WARNING",
                        "logger": "konfig.logging.central.collector",
                        "message": f"Central writer dropped {lost} record(s): "
                        f"its queue overflowed",
                        "dropped": lost,
                        "received_at": _utc_now(),
                    }
                )
            for entry in items:
                try:
                    self._write(entry)
                except Exception:
                    pass  # RotatingFileHandler reports its own errors to stderr
            if not items and self._stopping.is_set():
                return


class CaptureHandler(logging.Handler):
    """Writes the collector's own application records into the central stream."""

    def __init__(
        self, writer: CentralWriter, instance: dict[str, Any], level: int
    ) -> None:
        super().__init__(level)
        self._writer = writer
        self._instance = instance

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = record_to_wire(record)
            entry["instance"] = self._instance
            entry["received_at"] = _utc_now()
            self._writer.put(entry)
        except Exception:
            self.handleError(record)


def _clean_instance(raw: Any) -> dict[str, Any]:
    """Bound a sender-supplied identity block before it is copied onto records.

    The block is repeated on every record from the connection, so an
    oversized one is cut down to its label and hostname.
    """
    if not isinstance(raw, dict):
        return {}
    instance = {str(k): v for k, v in raw.items()}
    if len(json.dumps(instance, default=str)) <= _MAX_INSTANCE_BYTES:
        return instance
    trimmed: dict[str, Any] = {
        k: str(instance[k])[:_MAX_LABEL] for k in ("label", "hostname") if k in instance
    }
    trimmed["truncated"] = True
    return trimmed


def _printable(text: str) -> str:
    """Neutralise control characters (newlines included) for local log lines."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _peer(writer: asyncio.StreamWriter) -> str:
    peer = writer.get_extra_info("peername")
    if isinstance(peer, tuple) and len(peer) >= 2:
        return format_endpoint(str(peer[0]), int(peer[1]))
    return str(peer)


class CentralCollector:
    """The collector role: certificate, token, listener, writer and publication.

    Args:
        config: Resolved central logging config (``collector`` is true).
        log_dir: The application's base log directory; the central stream
            and the collector state live under ``<log_dir>/central``.
        instance: The collector's own identity block.
        secrets: A ``Secrets`` instance to publish the entry into, or None.
    """

    def __init__(
        self,
        config: CentralLogConfig,
        *,
        log_dir: Path,
        instance: dict[str, Any],
        secrets: Any = None,
    ) -> None:
        self._config = config
        self._base = Path(log_dir) / CENTRAL_DIR
        self._state_dir = self._base / STATE_DIR
        self._instance = instance
        self._secrets = secrets
        self._token = ""
        self._certificate: Optional[CollectorCertificate] = None
        self._writer: Optional[CentralWriter] = None
        self.capture_handler: Optional[CaptureHandler] = None
        self._endpoint = ""
        self._port = 0

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._ready = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._thread: Optional[threading.Thread] = None

    # -- public API -----------------------------------------------------------

    @property
    def endpoint(self) -> str:
        """The advertised ``host:port`` senders connect to."""
        return self._endpoint

    @property
    def port(self) -> int:
        """The port actually bound (useful when listening on port 0)."""
        return self._port

    @property
    def fingerprint(self) -> str:
        return self._certificate.fingerprint if self._certificate else ""

    @property
    def stream_path(self) -> Optional[Path]:
        """The central stream file for this run."""
        return self._writer.path if self._writer else None

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    def start(self) -> None:
        """Provision credentials, start the writer and listener, then publish."""
        listen_host, listen_port = parse_host_port(self._config.listen, DEFAULT_PORT)
        advertise_host: Optional[str] = None
        advertise_port: Optional[int] = None
        if self._config.advertise:
            advertise_host, port = parse_host_port(self._config.advertise, 0)
            advertise_port = port or None

        ensure_private_dir(self._state_dir)
        self._token = load_or_create_token(self._state_dir)
        self._certificate = load_or_create_certificate(
            self._state_dir, advertise_host or socket.gethostname()
        )

        cleanup_old_runs(self._base, self._config.retention_runs)
        run_dir = create_run_directory(self._base)
        self._writer = CentralWriter(
            run_dir / STREAM_FILE,
            max_bytes=self._config.max_file_size_mb * 1024 * 1024,
            backup_count=self._config.max_files,
        )
        self._writer.start()
        try:
            self._start_listener(listen_host, listen_port)
        except BaseException:
            self._writer.stop()
            raise

        if advertise_host is None:
            advertise_host = socket.gethostname()
            logger.warning(
                "No advertise address configured for the log collector; senders "
                "will use %s, which may change when the container restarts. Set "
                "KONFIG_LOG_COLLECTOR_ADVERTISE (or logging.central.advertise) to "
                "a stable service name",
                format_endpoint(advertise_host, self._port),
            )
        self._endpoint = format_endpoint(advertise_host, advertise_port or self._port)
        self.capture_handler = CaptureHandler(
            self._writer, self._instance, self._config.level
        )
        logger.info(
            "Log collector listening on %s, advertising %s (certificate %s); "
            "central stream %s",
            format_endpoint(listen_host, self._port),
            self._endpoint,
            self.fingerprint,
            self._writer.path,
        )
        self._publish()

    def stop(self) -> None:
        """Close the listener and every connection, then drain the writer."""
        loop, event = self._loop, self._stop_event
        if loop is not None and event is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass  # the loop has already stopped
        if self._thread is not None:
            self._thread.join(STOP_TIMEOUT)
        if self._writer is not None:
            self._writer.stop()

    # -- publication ------------------------------------------------------------

    def _publish(self) -> None:
        if self._secrets is None:
            logger.warning(
                "The log collector has no secrets store to publish into; senders "
                "need KONFIG_LOG_ENDPOINT, KONFIG_LOG_CERT_SHA256 and "
                "KONFIG_LOG_TOKEN"
            )
            return
        if not is_shared_backend(self._secrets):
            logger.warning(
                "The active secrets backend is the OS keyring, which is local to "
                "this machine; senders in other containers cannot discover the "
                "collector. Use a shared store (AWS Secrets Manager bundle or a "
                "shared encrypted file) or the KONFIG_LOG_* overrides"
            )
        try:
            entry = publish_entry(
                self._secrets,
                self._config.store_key,
                endpoint=self._endpoint,
                cert_sha256=self.fingerprint,
                token=self._token,
                collector_host=socket.gethostname(),
            )
        except Exception as exc:
            logger.warning(
                "Could not publish the log collector entry %r (%s); senders need "
                "the KONFIG_LOG_* overrides until it is published",
                self._config.store_key,
                type(exc).__name__,
            )
            return
        logger.info(
            "Published log collector entry %r (epoch %d)",
            self._config.store_key,
            entry.epoch,
        )

    # -- listener ---------------------------------------------------------------

    def _start_listener(self, host: str, port: int) -> None:
        assert self._certificate is not None
        context = server_context(self._certificate)
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(host, port, context),
            name="konfig-log-collector",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT):
            raise TimeoutError("log collector listener did not start in time")
        if self._start_error is not None:
            raise self._start_error

    def _thread_main(self, host: str, port: int, context: ssl.SSLContext) -> None:
        try:
            asyncio.run(self._serve(host, port, context))
        except BaseException as exc:  # pragma: no cover - defensive
            if not self._ready.is_set():
                self._start_error = exc
                self._ready.set()
            else:
                logger.exception("Log collector listener failed")

    async def _serve(self, host: str, port: int, context: ssl.SSLContext) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        try:
            server = await asyncio.start_server(
                self._handle,
                host,
                port,
                ssl=context,
                ssl_handshake_timeout=self._config.handshake_timeout,
                limit=MAX_FRAME_BYTES,
            )
        except BaseException as exc:
            self._start_error = exc
            self._ready.set()
            return
        self._port = int(server.sockets[0].getsockname()[1])
        self._ready.set()
        try:
            await self._stop_event.wait()
        finally:
            server.close()
            tasks = list(self._tasks)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await asyncio.wait_for(server.wait_closed(), STOP_TIMEOUT)
            except (asyncio.TimeoutError, OSError):
                pass

    async def _send(
        self, writer: asyncio.StreamWriter, message: dict[str, Any]
    ) -> None:
        try:
            writer.write(encode_frame(message))
            await asyncio.wait_for(writer.drain(), self._config.handshake_timeout)
        except (OSError, asyncio.TimeoutError, ssl.SSLError):
            pass

    async def _read(self, reader: asyncio.StreamReader, timeout: float) -> bytes:
        return await asyncio.wait_for(reader.readuntil(b"\n"), timeout)

    async def _handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, peer: str
    ) -> Optional[dict[str, Any]]:
        """Authenticate the sender; return its identity block, or None if rejected."""
        try:
            message = decode_frame(
                await self._read(reader, self._config.handshake_timeout)
            )
            if message["type"] != TYPE_HELLO:
                raise ProtocolError("expected a hello frame")
            check_protocol(message)
        except ProtocolError as exc:
            await self._send(writer, reject(str(exc)))
            logger.warning("Rejected sender %s: %s", peer, exc)
            return None
        token = message.get("token")
        # Never log or echo the token, valid or not.
        if not isinstance(token, str) or not hmac.compare_digest(
            token.encode("utf-8"), self._token.encode("utf-8")
        ):
            await self._send(writer, reject("authentication failed"))
            logger.warning("Rejected sender %s: authentication failed", peer)
            return None
        instance = _clean_instance(message.get("instance"))
        instance["peer"] = peer
        await self._send(writer, welcome())
        return instance

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        peer = _peer(writer)
        label: Optional[str] = None
        try:
            if len(self._tasks) > self._config.max_connections:
                await self._send(writer, reject("collector is at its connection limit"))
                logger.warning(
                    "Rejected sender %s: connection limit (%d) reached",
                    peer,
                    self._config.max_connections,
                )
                return
            instance = await self._handshake(reader, writer, peer)
            if instance is None:
                return
            label = _printable(
                str(instance.get("label") or instance.get("hostname") or "")[
                    :_MAX_LABEL
                ]
            )
            logger.info("Sender %s (%s) connected", peer, label or "unlabelled")
            while True:
                line = await self._read(reader, self._config.idle_timeout)
                self._dispatch(decode_frame(line), instance)
        except asyncio.IncompleteReadError:
            pass  # the sender closed the connection
        except asyncio.LimitOverrunError:
            logger.warning("Dropped sender %s: frame exceeds the size limit", peer)
        except asyncio.TimeoutError:
            logger.info(
                "Dropped sender %s: %s timed out",
                peer,
                "idle connection" if label is not None else "handshake",
            )
        except ProtocolError as exc:
            logger.warning("Dropped sender %s: %s", peer, exc)
        except asyncio.CancelledError:
            pass  # the collector is stopping
        except (ConnectionError, ssl.SSLError, OSError) as exc:
            logger.debug("Connection from %s failed: %s", peer, type(exc).__name__)
        finally:
            if task is not None:
                self._tasks.discard(task)
            writer.close()
            if label is not None:
                logger.info("Sender %s (%s) disconnected", peer, label or "unlabelled")

    def _dispatch(self, message: dict[str, Any], instance: dict[str, Any]) -> None:
        assert self._writer is not None
        kind = message["type"]
        received_at = _utc_now()
        if kind == TYPE_LOG:
            records = message.get("records")
            if not isinstance(records, list):
                raise ProtocolError("log frame has no record list")
            for record in records:
                if isinstance(record, dict):
                    entry = dict(record)
                    entry["instance"] = instance
                    entry["received_at"] = received_at
                    self._writer.put(entry)
        elif kind == TYPE_DROPPED:
            count = message.get("count")
            if not isinstance(count, int) or count < 0:
                raise ProtocolError("dropped frame has no valid count")
            self._writer.put(
                {
                    "timestamp": received_at,
                    "level": "WARNING",
                    "logger": "konfig.logging.central.collector",
                    "message": f"Sender dropped {count} record(s) after its queue "
                    f"overflowed",
                    "dropped": count,
                    "instance": instance,
                    "received_at": received_at,
                }
            )
        else:
            raise ProtocolError("unexpected frame type")
