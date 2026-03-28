"""Tests for log formatters."""
from __future__ import annotations

import json
import logging

from konfig.logging.formatters import JSONFormatter, TextFormatter


class TestTextFormatter:
    def test_format_contains_level_and_message(self) -> None:
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "INFO" in output
        assert "Hello world" in output
        assert "[test.logger]" in output

    def test_format_contains_timestamp(self) -> None:
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="app", level=logging.WARNING, pathname="", lineno=0,
            msg="warn", args=(), exc_info=None,
        )
        output = formatter.format(record)
        # Should contain ISO-ish timestamp
        assert "T" in output or "-" in output


class TestJSONFormatter:
    def test_format_is_valid_json(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="app.server", level=logging.INFO, pathname="", lineno=0,
            msg="Server started", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "app.server"
        assert data["message"] == "Server started"
        assert "timestamp" in data
        assert "pid" in data

    def test_format_with_args(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="app", level=logging.DEBUG, pathname="", lineno=0,
            msg="Count: %d", args=(42,), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "Count: 42"

    def test_format_with_exception(self) -> None:
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="app", level=logging.ERROR, pathname="", lineno=0,
            msg="Failed", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]
