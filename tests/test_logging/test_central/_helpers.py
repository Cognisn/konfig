"""Helpers shared by the centralised log forwarding tests."""

from __future__ import annotations

import json
import logging
import socket
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from konfig.logging.central.collector import STREAM_FILE
from konfig.logging.central.config import CentralLogConfig
from konfig.secrets import Secrets
from konfig.secrets.encrypted_file import EncryptedFileBackend

MASTER_KEY = "central-logging-test-master-key"


def wait_for(predicate: Callable[[], bool], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _stream_files(log_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted((log_dir / "central").glob("*/central.log*"))
        if path.parent.name != "latest"  # a symlink to one of the run directories
    ]


def _parse(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_stream(log_dir: Path) -> list[dict[str, Any]]:
    """Every entry in every central stream file under ``log_dir``.

    Strict: every line must be valid JSON, including a last line without its
    newline. Use it once the collector has stopped; while it may still be
    writing, poll with ``poll_stream``.
    """
    entries: list[dict[str, Any]] = []
    for path in _stream_files(log_dir):
        entries.extend(_parse(path.read_text(encoding="utf-8")))
    return entries


def poll_stream(log_dir: Path) -> list[dict[str, Any]]:
    """Every complete entry under ``log_dir``, for polling a running collector.

    The writer appends each line with its newline in one write, but a reader
    can see that write part way through (Linux does), so the bytes after the
    last newline of the live file are a line still being written and are left
    out. They are cut as bytes, since the cut can fall inside a character.
    Every complete line must still be valid JSON, and rotated files are closed,
    so they are read whole.
    """
    entries: list[dict[str, Any]] = []
    for path in _stream_files(log_dir):
        data = path.read_bytes()
        if path.name == STREAM_FILE:
            data = data[: data.rfind(b"\n") + 1]
        entries.extend(_parse(data.decode("utf-8")))
    return entries


def messages(entries: list[dict[str, Any]], logger_name: str) -> list[str]:
    return [e["message"] for e in entries if e.get("logger") == logger_name]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def shared_secrets(path: Path) -> Secrets:
    """A fresh view of a shared encrypted file store, as another container sees it."""
    return Secrets(backend=EncryptedFileBackend(path, master_key=MASTER_KEY))


def collector_config(**overrides: Any) -> CentralLogConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "collector": True,
        "listen": "127.0.0.1:0",
        "advertise": "127.0.0.1",
    }
    values.update(overrides)
    return CentralLogConfig(**values)


class FakeSMClient:
    """Minimal in-memory stand-in for a boto3 secretsmanager client."""

    def __init__(self, secret_string: str = "{}") -> None:
        self.secret_string = secret_string
        self.exceptions = SimpleNamespace(ResourceNotFoundException=KeyError)

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        return {"SecretString": self.secret_string}

    def put_secret_value(self, SecretId: str, SecretString: str) -> None:
        self.secret_string = SecretString


def isolated_logger(name: str, handler: logging.Handler) -> logging.Logger:
    """A logger that sends only to ``handler``, bypassing the root logger."""
    log = logging.getLogger(name)
    log.handlers = [handler]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    return log
