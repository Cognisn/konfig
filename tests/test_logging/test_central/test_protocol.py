"""Tests for the forwarding wire protocol."""

from __future__ import annotations

import json
import logging
import sys

import pytest

from konfig.logging.central.protocol import (
    MAX_FRAME_BYTES,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    check_protocol,
    decode_frame,
    encode_frame,
    encode_log_batch,
    encode_record,
    hello,
    record_to_wire,
)


def _record(msg: str = "hello %s", args: tuple = ("world",), **extra: object):
    record = logging.LogRecord(
        "app.module", logging.WARNING, __file__, 1, msg, args, None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestFrames:
    def test_round_trip(self) -> None:
        message = hello("tok", {"label": "w1"})
        frame = encode_frame(message)
        assert frame.endswith(b"\n") and frame.count(b"\n") == 1
        assert decode_frame(frame) == message

    def test_newlines_in_values_stay_escaped(self) -> None:
        frame = encode_frame({"type": "log", "records": [{"message": "a\nb"}]})
        assert frame.count(b"\n") == 1
        assert decode_frame(frame)["records"][0]["message"] == "a\nb"

    def test_unicode(self) -> None:
        frame = encode_frame({"type": "log", "message": "g’day ☀"})
        assert decode_frame(frame)["message"] == "g’day ☀"

    def test_oversize_frame_rejected(self) -> None:
        with pytest.raises(ProtocolError):
            encode_frame({"type": "log", "pad": "x" * MAX_FRAME_BYTES})
        with pytest.raises(ProtocolError):
            decode_frame(b'{"type":"log","pad":"' + b"x" * MAX_FRAME_BYTES + b'"}\n')

    @pytest.mark.parametrize(
        "line",
        [
            b"not json\n",
            b'{"type": \n',
            b"[1, 2]\n",
            b'{"no_type": 1}\n',
            b"\xff\xfe\n",
        ],
    )
    def test_invalid_frames_rejected(self, line: bytes) -> None:
        with pytest.raises(ProtocolError):
            decode_frame(line)

    def test_error_messages_do_not_echo_content(self) -> None:
        with pytest.raises(ProtocolError) as info:
            decode_frame(b'{"token": "super-secret-token"\n')
        assert "super-secret-token" not in str(info.value)

    def test_log_batch(self) -> None:
        frame = encode_log_batch(
            [encode_record({"message": "a"}), encode_record({"m": 1})]
        )
        assert decode_frame(frame) == {
            "type": "log",
            "records": [{"message": "a"}, {"m": 1}],
        }


class TestVersioning:
    def test_current_version_accepted(self) -> None:
        check_protocol(hello("t", {}))

    @pytest.mark.parametrize("version", [0, 2, "1", None])
    def test_unknown_version_rejected(self, version: object) -> None:
        with pytest.raises(ProtocolError, match="unsupported protocol version"):
            check_protocol({"type": "hello", "protocol": version})

    def test_hello_carries_version(self) -> None:
        assert hello("t", {})["protocol"] == PROTOCOL_VERSION


class TestRecordToWire:
    def test_fields(self) -> None:
        wire = record_to_wire(_record())
        assert wire["message"] == "hello world"
        assert wire["level"] == "WARNING"
        assert wire["logger"] == "app.module"
        assert wire["timestamp"].endswith("+00:00")
        assert isinstance(wire["pid"], int)
        assert wire["thread"]
        assert "exception" not in wire
        json.dumps(wire)

    def test_message_captured_at_emit_time(self) -> None:
        data = ["before"]
        record = _record("value %s", (data,))
        wire = record_to_wire(record)
        data[0] = "after"
        assert wire["message"] == "value ['before']"

    def test_exception_text(self) -> None:
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            record = logging.LogRecord(
                "app", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
            )
        wire = record_to_wire(record)
        assert "RuntimeError: kaboom" in wire["exception"]

    def test_only_serialisable_extras(self) -> None:
        wire = record_to_wire(_record(request_id="r-1", count=3, obj=object()))
        assert wire["extra"] == {"request_id": "r-1", "count": 3}

    def test_long_message_truncated(self) -> None:
        wire = record_to_wire(_record("x" * (MAX_MESSAGE_BYTES * 2), ()))
        assert len(wire["message"].encode()) < MAX_MESSAGE_BYTES + 50
        assert wire["message"].endswith("[truncated]")

    def test_bad_format_args_do_not_raise(self) -> None:
        wire = record_to_wire(_record("%d items", ("not a number",)))
        assert wire["message"] == "%d items"
