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
        return json.dumps(entry, default=str)
