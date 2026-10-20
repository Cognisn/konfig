"""Wire format for centralised log forwarding.

Frames are newline-delimited UTF-8 JSON objects sent over TLS. The sender
opens with a ``hello`` (protocol version, token and identity), the collector
answers ``welcome`` or ``reject``, and the sender then streams ``log``
batches and occasional ``dropped`` notices. Nothing on this path is ever
unpickled or evaluated: frames are parsed as JSON and validated.
"""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

PROTOCOL_VERSION = 1

MAX_FRAME_BYTES = 256 * 1024
MAX_BATCH_RECORDS = 500
MAX_BATCH_BYTES = 64 * 1024

# Per-record field caps keep any single record well inside one frame.
MAX_MESSAGE_BYTES = 16 * 1024
MAX_EXCEPTION_BYTES = 16 * 1024
MAX_EXTRA_BYTES = 8 * 1024

_TRUNCATED = "...[truncated]"

TYPE_HELLO = "hello"
TYPE_WELCOME = "welcome"
TYPE_REJECT = "reject"
TYPE_LOG = "log"
TYPE_DROPPED = "dropped"

# Attributes every LogRecord has; anything else on a record came from
# ``extra=`` and is a candidate for the ``extra`` field.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
    | {"message", "asctime", "taskName"}
)


class ProtocolError(ValueError):
    """A frame was malformed, oversized, or violated the protocol.

    Messages never include frame contents, so they cannot leak a token.
    """


def encode_frame(message: Mapping[str, Any]) -> bytes:
    """Serialise one message as a newline-terminated JSON frame."""
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    frame = data.encode("utf-8") + b"\n"
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame of {len(frame)} bytes exceeds the limit")
    return frame


def decode_frame(line: bytes) -> dict[str, Any]:
    """Parse one frame (with or without its trailing newline).

    Raises:
        ProtocolError: On an oversized frame, invalid UTF-8 or JSON, or a
            value that is not an object with a string ``type``.
    """
    if len(line) > MAX_FRAME_BYTES:
        raise ProtocolError("frame exceeds the size limit")
    if line.endswith(b"\n"):
        line = line[:-1]
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("frame is not valid UTF-8") from None
    try:
        message = json.loads(text)
    except ValueError:
        raise ProtocolError("frame is not valid JSON") from None
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("frame is not a typed JSON object")
    return message


def hello(token: str, instance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": TYPE_HELLO,
        "protocol": PROTOCOL_VERSION,
        "token": token,
        "instance": dict(instance),
    }


def welcome() -> dict[str, Any]:
    return {"type": TYPE_WELCOME, "protocol": PROTOCOL_VERSION}


def reject(reason: str) -> dict[str, Any]:
    return {"type": TYPE_REJECT, "reason": reason}


def dropped(count: int) -> dict[str, Any]:
    return {"type": TYPE_DROPPED, "count": count}


def encode_log_batch(encoded_records: list[str]) -> bytes:
    """Build a ``log`` frame from records already serialised to JSON text."""
    body = '{"type":"log","records":[' + ",".join(encoded_records) + "]}\n"
    frame = body.encode("utf-8")
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame of {len(frame)} bytes exceeds the limit")
    return frame


def encode_record(record: Mapping[str, Any]) -> str:
    """Serialise one wire record to compact JSON text."""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def check_protocol(message: Mapping[str, Any]) -> None:
    """Raise ``ProtocolError`` unless the message speaks our protocol version."""
    version = message.get("protocol")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            f"unsupported protocol version {version!r}; this collector speaks "
            f"version {PROTOCOL_VERSION}"
        )


def _truncate(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore") + _TRUNCATED


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    budget = MAX_EXTRA_BYTES
    for key, value in vars(record).items():
        if key in _STANDARD_ATTRS or key.startswith("_"):
            continue
        try:
            size = len(json.dumps(value, ensure_ascii=False))
        except (TypeError, ValueError):
            continue  # not JSON-serialisable: leave it out
        if size > budget:
            continue
        budget -= size
        extra[key] = value
    return extra


def record_to_wire(record: logging.LogRecord) -> dict[str, Any]:
    """Convert a LogRecord into a protocol record dict.

    Called at emit time, so the message and exception text are captured
    before anything can mutate the record or its arguments.
    """
    try:
        message = record.getMessage()
    except Exception:
        message = str(record.msg)
    wire: dict[str, Any] = {
        "timestamp": datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": _truncate(message, MAX_MESSAGE_BYTES),
        "pid": record.process,
        "thread": record.threadName,
    }
    exc_text = record.exc_text
    if not exc_text and record.exc_info and record.exc_info[1] is not None:
        exc_text = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
    if exc_text:
        wire["exception"] = _truncate(exc_text, MAX_EXCEPTION_BYTES)
    if record.stack_info:
        wire["stack"] = _truncate(record.stack_info, MAX_EXCEPTION_BYTES)
    extra = _extras(record)
    if extra:
        wire["extra"] = extra
    return wire
