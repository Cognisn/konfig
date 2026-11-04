"""CentralWriter's rollover: move first, shift only after, copy and truncate if refused.

The refused move is simulated on every platform by making ``os.rename`` and
``os.replace`` raise WinError 32 for central.log, as Windows does while another
program holds it open without share-delete. ``test_rotation.py`` covers the
real held reader on Windows.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pytest

from konfig.logging.central.collector import (
    STREAM_FILE,
    CentralRotatingFileHandler,
    CentralWriter,
)

MAX_BYTES = 1024
BACKUPS = 3
LOGGER = "konfig.logging.central.collector"


def line(i: int) -> str:
    return f"record {i:04d} " + "x" * 80  # about ten lines a file


def make_handler(path: Path, cls: type[RotatingFileHandler]) -> RotatingFileHandler:
    handler = cls(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def emit_all(
    directory: Path,
    indices: range,
    cls: type[RotatingFileHandler] = CentralRotatingFileHandler,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    handler = make_handler(directory / STREAM_FILE, cls)
    try:
        for i in indices:
            handler.emit(logging.makeLogRecord({"msg": line(i)}))
    finally:
        handler.close()


def snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def backups(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.glob(f"{STREAM_FILE}.*"))


def ordered_lines(directory: Path) -> list[str]:
    """Every line in the stream files, oldest backup first and central.log last."""
    names = [f"{STREAM_FILE}.{n}" for n in range(BACKUPS, 0, -1)] + [STREAM_FILE]
    lines: list[str] = []
    for name in names:
        path = directory / name
        if path.exists():
            lines.extend(path.read_text(encoding="utf-8").splitlines())
    return lines


def refuse_moves(monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    """Make every move of central.log fail with ``error``; other moves still work."""

    def guard(real: Callable[..., Any]) -> Callable[..., Any]:
        def move(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
            if Path(os.fspath(src)).name == STREAM_FILE:
                raise error
            return real(src, dst, *args, **kwargs)

        return move

    monkeypatch.setattr(os, "rename", guard(os.rename))
    monkeypatch.setattr(os, "replace", guard(os.replace))


def sharing_violation(path: str = STREAM_FILE) -> PermissionError:
    return PermissionError(
        13,
        "The process cannot access the file because it is being used by another "
        "process",
        path,
    )


def count_copies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    copies: list[str] = []
    real = shutil.copyfile

    def copyfile(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        copies.append(os.fspath(src))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copyfile", copyfile)
    return copies


@pytest.mark.parametrize(
    "move_error, copy_fails",
    [
        (sharing_violation(), True),  # refused, and the fallback copy fails too
        (OSError(5, "Input/output error", STREAM_FILE), False),  # not a refusal
    ],
    ids=["refused-and-copy-fails", "other-move-error"],
)
def test_a_failed_move_never_deletes_or_shifts_a_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    move_error: OSError,
    copy_fails: bool,
) -> None:
    emit_all(tmp_path, range(45))  # rotates normally until every backup is full
    assert backups(tmp_path) == [f"{STREAM_FILE}.{n}" for n in (1, 2, 3)]
    before = snapshot(tmp_path)

    refuse_moves(monkeypatch, move_error)
    if copy_fails:

        def broken_copy(*args: Any, **kwargs: Any) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(shutil, "copyfile", broken_copy)
    monkeypatch.setattr(logging, "raiseExceptions", False)  # handleError stays quiet
    emit_all(tmp_path, range(45, 75))  # central.log fills, so each rollover fails

    after = snapshot(tmp_path)
    for name in backups(tmp_path):
        assert after[name] == before[name], f"{name} was changed by a failed move"
    assert sorted(after) == sorted(before), "a failed move added or removed a file"
    assert after[STREAM_FILE].startswith(before[STREAM_FILE]), "central.log lost lines"


def test_copy_and_truncate_keeps_every_record_and_the_backup_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse_moves(monkeypatch, sharing_violation())
    copies = count_copies(monkeypatch)

    emit_all(tmp_path / "within", range(30))  # fewer rollovers than backups
    assert ordered_lines(tmp_path / "within") == [line(i) for i in range(30)]
    assert len(copies) >= 2
    assert len(backups(tmp_path / "within")) == len(copies)

    emit_all(tmp_path / "beyond", range(120))  # more rollovers than backups
    assert len(backups(tmp_path / "beyond")) == BACKUPS
    monkeypatch.undo()
    emit_all(tmp_path / "renamed", range(120))
    # The fallback leaves exactly the files a working rename would have left.
    assert snapshot(tmp_path / "beyond") == snapshot(tmp_path / "renamed")
    kept = ordered_lines(tmp_path / "beyond")
    assert kept == [line(i) for i in range(120 - len(kept), 120)]


def test_each_fallback_reports_one_warning_and_no_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    refuse_moves(monkeypatch, sharing_violation())
    copies = count_copies(monkeypatch)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    emit_all(tmp_path, range(60))

    warnings = [r for r in caplog.records if r.name == LOGGER]
    assert len(copies) >= 3
    assert len(warnings) == len(copies), "one warning per fallback, not per record"
    for record in warnings:
        assert record.levelno == logging.WARNING
        assert record.exc_info is None
        assert STREAM_FILE in record.getMessage()
    stderr = capsys.readouterr().err
    assert "Traceback" not in stderr and "Logging error" not in stderr


def test_the_rename_path_is_unchanged_where_the_move_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    copies = count_copies(monkeypatch)
    caplog.set_level(logging.WARNING, logger=LOGGER)

    emit_all(tmp_path / "central", range(120))
    emit_all(tmp_path / "stdlib", range(120), cls=RotatingFileHandler)

    assert snapshot(tmp_path / "central") == snapshot(tmp_path / "stdlib")
    assert copies == []
    assert [r for r in caplog.records if r.name == LOGGER] == []


def test_the_writer_keeps_every_record_when_moves_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse_moves(monkeypatch, sharing_violation())
    writer = CentralWriter(
        tmp_path / STREAM_FILE, max_bytes=MAX_BYTES, backup_count=BACKUPS
    )
    writer.start()
    try:
        for i in range(30):
            writer.put({"message": line(i)})
    finally:
        writer.stop()

    found = [text for text in ordered_lines(tmp_path) if text]
    assert [f'{{"message": "{line(i)}"}}' for i in range(30)] == found
