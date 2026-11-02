"""The stream readers in _helpers: strict after the collector stops, tolerant only
of a partly written last line while it is still writing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from konfig.logging.central.collector import CentralWriter
from tests.test_logging.test_central._helpers import poll_stream, read_stream


def entry(i: int, message: str = "") -> dict[str, Any]:
    return {
        "timestamp": "2026-11-02T22:31:17.891159+00:00",
        "logger": "e2e.worker-1",
        "message": message or f"message worker-1 {i}",
    }


def line(i: int, message: str = "") -> bytes:
    return (json.dumps(entry(i, message), ensure_ascii=False) + "\n").encode("utf-8")


def write_run(log_dir: Path, files: dict[str, bytes], run: str = "run-1") -> Path:
    run_dir = log_dir / "central" / run
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (run_dir / name).write_bytes(data)
    return run_dir


class TestPartialLastLine:
    def test_poll_ignores_a_partly_written_last_line(self, tmp_path: Path) -> None:
        # The exact text the polling read saw in the failed CI job.
        partial = b'{"timestamp": "2026-11-02T22:31:17.891159+'
        write_run(tmp_path, {"central.log": line(0) + line(1) + partial})
        assert poll_stream(tmp_path) == [entry(0), entry(1)]

    def test_strict_read_fails_on_the_same_file(self, tmp_path: Path) -> None:
        partial = b'{"timestamp": "2026-11-02T22:31:17.891159+'
        write_run(tmp_path, {"central.log": line(0) + partial})
        with pytest.raises(json.JSONDecodeError):
            read_stream(tmp_path)

    def test_poll_ignores_a_tail_cut_inside_a_multibyte_character(
        self, tmp_path: Path
    ) -> None:
        whole = line(1, "café ☕")
        cut = whole[: whole.index("☕".encode()) + 1]  # one byte of three
        write_run(tmp_path, {"central.log": line(0) + cut})
        assert poll_stream(tmp_path) == [entry(0)]

    def test_poll_sees_the_line_once_its_newline_is_written(
        self, tmp_path: Path
    ) -> None:
        whole = line(1)
        run_dir = write_run(tmp_path, {"central.log": line(0) + whole[:20]})
        assert poll_stream(tmp_path) == [entry(0)]
        with (run_dir / "central.log").open("ab") as stream:
            stream.write(whole[20:])
        assert poll_stream(tmp_path) == [entry(0), entry(1)]

    def test_poll_of_a_file_with_no_newline_yet_is_empty(self, tmp_path: Path) -> None:
        write_run(tmp_path, {"central.log": line(0)[:30]})
        assert poll_stream(tmp_path) == []


class TestMalformedCompleteLine:
    """A complete line that is not JSON is a product defect: both readers fail."""

    @pytest.mark.parametrize("reader", [poll_stream, read_stream])
    def test_malformed_line_in_the_middle(self, tmp_path: Path, reader: Any) -> None:
        write_run(
            tmp_path, {"central.log": line(0) + b'{"timestamp": "2026\n' + line(1)}
        )
        with pytest.raises(json.JSONDecodeError):
            reader(tmp_path)

    @pytest.mark.parametrize("reader", [poll_stream, read_stream])
    def test_malformed_last_line_with_its_newline(
        self, tmp_path: Path, reader: Any
    ) -> None:
        write_run(tmp_path, {"central.log": line(0) + b'{"timestamp": "2026\n'})
        with pytest.raises(json.JSONDecodeError):
            reader(tmp_path)

    def test_poll_fails_on_a_malformed_line_before_a_partial_tail(
        self, tmp_path: Path
    ) -> None:
        data = line(0) + b"not json\n" + line(1)[:25]
        write_run(tmp_path, {"central.log": data})
        with pytest.raises(json.JSONDecodeError):
            poll_stream(tmp_path)

    def test_poll_fails_on_two_lines_run_together(self, tmp_path: Path) -> None:
        # Interleaved writes would join records on one line.
        joined = line(0)[:-1] + line(1)
        write_run(tmp_path, {"central.log": joined})
        with pytest.raises(json.JSONDecodeError):
            poll_stream(tmp_path)


class TestRotatedFileSet:
    def test_poll_reads_every_file_of_a_rotated_set(self, tmp_path: Path) -> None:
        write_run(
            tmp_path,
            {
                "central.log.2": line(0) + line(1),
                "central.log.1": line(2) + line(3),
                "central.log": line(4) + line(5)[:10],
            },
        )
        got = poll_stream(tmp_path)
        assert sorted(e["message"] for e in got) == [
            f"message worker-1 {i}" for i in range(5)
        ]

    def test_poll_fails_on_an_unterminated_rotated_file(self, tmp_path: Path) -> None:
        # Rotated files are closed: only the live file can be mid-write.
        write_run(
            tmp_path,
            {"central.log.1": line(0) + line(1)[:10], "central.log": line(2)},
        )
        with pytest.raises(json.JSONDecodeError):
            poll_stream(tmp_path)

    def test_poll_fails_on_a_malformed_line_in_a_rotated_file(
        self, tmp_path: Path
    ) -> None:
        write_run(tmp_path, {"central.log.1": b"not json\n", "central.log": line(0)})
        with pytest.raises(json.JSONDecodeError):
            poll_stream(tmp_path)

    def test_every_run_directory_is_read_and_latest_skipped(
        self, tmp_path: Path
    ) -> None:
        write_run(tmp_path, {"central.log": line(0)}, run="run-1")
        write_run(tmp_path, {"central.log": line(1) + line(2)[:5]}, run="run-2")
        # A real directory standing in for the latest symlink must not be counted.
        write_run(tmp_path, {"central.log": line(9)}, run="latest")
        assert poll_stream(tmp_path) == [entry(0), entry(1)]
        assert len(read_stream(tmp_path / "missing")) == 0


class TestStrictRead:
    def test_strict_read_parses_an_unterminated_complete_last_line(
        self, tmp_path: Path
    ) -> None:
        write_run(tmp_path, {"central.log": line(0) + line(1)[:-1]})
        assert read_stream(tmp_path) == [entry(0), entry(1)]

    def test_both_readers_agree_on_a_stopped_writer(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "central" / "run-1"
        run_dir.mkdir(parents=True)
        writer = CentralWriter(run_dir / "central.log", max_bytes=2048, backup_count=20)
        writer.start()
        for i in range(50):
            writer.put(entry(i, f"message worker-1 {i} " + "é" * 40))
        writer.stop()
        assert len(list(run_dir.glob("central.log.*"))) > 1  # it did rotate
        strict = read_stream(tmp_path)
        assert len(strict) == 50
        assert sorted(poll_stream(tmp_path), key=str) == sorted(strict, key=str)
