"""Central stream rotation while another handle holds central.log open.

Every record the writer is given is counted against every record in the stream
files. A plain reader (``open()``, as a tail or simple log shipper would use)
and a reader that opens with share-delete are compared with no reader at all.

Every case must keep every record on every platform. On POSIX a rename never
cares about other open handles. On Windows a handle opened without
``FILE_SHARE_DELETE`` makes the rename of central.log fail with WinError 32;
the standard RotatingFileHandler then lost every record written while the
reader was open and shifted earlier backups off the end. CentralWriter's
rollover copies central.log to ``.1`` and truncates it in place instead.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from konfig.logging.central.collector import STREAM_FILE, CentralWriter
from konfig.logging.central.config import CentralLogConfig
from tests.test_logging.test_central._helpers import read_stream

MAX_BYTES = 4096
BACKUP_COUNT = CentralLogConfig().max_files  # the shipped default
BEFORE = 60  # written and rotated before the reader opens
DURING = 60  # written while the reader holds central.log open
PADDING = "x" * 120  # about 200 bytes a line, so about 20 lines a file

WINDOWS = sys.platform == "win32"


def entry(i: int) -> dict[str, Any]:
    return {
        "timestamp": "2026-11-03T00:00:00+00:00",
        "level": "INFO",
        "logger": "rotation.test",
        "message": f"record {i:04d} {PADDING}",
    }


@contextmanager
def plain_reader(path: Path) -> Iterator[IO[bytes]]:
    with open(path, "rb") as handle:
        handle.read()
        yield handle


@contextmanager
def share_delete_reader(path: Path) -> Iterator[IO[bytes]]:
    """A reader that lets the file be renamed or deleted under it.

    POSIX handles always behave this way, so outside Windows this is a plain
    ``open()``. On Windows the handle is opened with ``FILE_SHARE_DELETE``.
    """
    if not WINDOWS:
        with plain_reader(path) as handle:
            yield handle
        return

    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    share_all = 0x1 | 0x2 | 0x4  # FILE_SHARE_READ | WRITE | DELETE
    open_existing = 3
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.restype = wintypes.HANDLE
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    raw = create_file(str(path), generic_read, share_all, None, open_existing, 0, None)
    if raw == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    fd = msvcrt.open_osfhandle(raw, os.O_RDONLY)
    with os.fdopen(fd, "rb") as handle:
        handle.read()
        yield handle


@contextmanager
def no_reader(path: Path) -> Iterator[None]:
    yield None


READERS = {
    "none": no_reader,
    "plain": plain_reader,
    "share_delete": share_delete_reader,
}


def rotate_with_reader(run_dir: Path, reader: str) -> tuple[list[str], list[str]]:
    """Write BEFORE records, then DURING records with ``reader`` holding central.log.

    Nothing reads the stream files while a writer runs: on Windows even a short
    read without share-delete can collide with a rename. So one writer writes
    the BEFORE records and stops, and a second writer appends the DURING
    records to the same file and is stopped (and so fully drained) while the
    reader is still open. Returns the messages given and the messages found.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / STREAM_FILE
    given = [entry(i)["message"] for i in range(BEFORE + DURING)]

    write(path, range(BEFORE))
    backups = sorted(run_dir.glob(f"{STREAM_FILE}.*"))
    assert len(backups) >= 2, "the BEFORE records should leave backups to lose"

    with READERS[reader](path):
        write(path, range(BEFORE, BEFORE + DURING))

    found = [e["message"] for e in read_stream(run_dir.parent.parent)]
    return given, found


def write(path: Path, indices: range) -> None:
    writer = CentralWriter(path, max_bytes=MAX_BYTES, backup_count=BACKUP_COUNT)
    writer.start()
    try:
        for i in indices:
            writer.put(entry(i))
    finally:
        writer.stop()


def assert_every_record_kept(given: list[str], found: list[str]) -> None:
    missing = sorted(set(given) - set(found))
    assert not missing and len(found) == len(given), (
        f"given {len(given)}, found {len(found)}, missing {len(missing)}: "
        f"{[m.split()[1] for m in missing]}"
    )


def test_capacity_holds_every_record() -> None:
    # The control is only meaningful if nothing falls off the end by design.
    line = len(json.dumps(entry(9999), ensure_ascii=False)) + 1
    per_file = MAX_BYTES // line
    assert per_file * (BACKUP_COUNT + 1) > BEFORE + DURING
    assert BEFORE // per_file >= 2  # at least two backups before the reader opens
    assert DURING > per_file  # the reader is held across at least one rotation


def test_rotation_with_no_reader_keeps_every_record(tmp_path: Path) -> None:
    given, found = rotate_with_reader(tmp_path / "central" / "run-1", "none")
    assert_every_record_kept(given, found)


def test_rotation_with_a_share_delete_reader_keeps_every_record(
    tmp_path: Path,
) -> None:
    given, found = rotate_with_reader(tmp_path / "central" / "run-1", "share_delete")
    assert_every_record_kept(given, found)


def test_rotation_with_a_plain_reader_keeps_every_record(tmp_path: Path) -> None:
    given, found = rotate_with_reader(tmp_path / "central" / "run-1", "plain")
    assert_every_record_kept(given, found)
