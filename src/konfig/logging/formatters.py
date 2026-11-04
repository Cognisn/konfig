"""Text and JSON log formatters."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class TextFormatter(logging.Formatter):
    """Human-readable text log formatter.

    Format: ``LEVEL  [logger] message``
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )


class JSONFormatter(logging.Formatter):
    """Structured JSON-lines log formatter for container/cloud environments.

    Each log record is emitted as a single JSON line with fields:
    timestamp, level, logger, message, pid.
    """

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self.build_entry(record), default=str)

    def build_entry(self, record: logging.LogRecord) -> dict[str, Any]:
        """Build the dict serialised for ``record``."""
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "pid": record.process,
        }
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return entry


class InstanceJSONFormatter(JSONFormatter):
    """JSON formatter that adds the centralised logging ``instance`` block.

    Used for local logs only when ``logging.central.include_instance_locally``
    is enabled.
    """

    def __init__(self, instance: dict[str, Any]) -> None:
        super().__init__()
        self._instance = instance

    def build_entry(self, record: logging.LogRecord) -> dict[str, Any]:
        entry = super().build_entry(record)
        entry["instance"] = self._instance
        return entry
