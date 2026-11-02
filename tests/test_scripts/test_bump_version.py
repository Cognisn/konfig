"""Tests for scripts/bump-version.sh, run with bash against a temporary copy."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bump-version.sh"

CHANGELOG = (
    b"# Changelog\n"
    b"\n"
    b"All notable changes to this project will be documented in this file.\n"
    b"\n"
    b"## [Unreleased]\n"
    b"\n"
    b"### Added\n"
    b"\n"
    b"- A new feature.\n"
    b"\n"
    b"### Fixed\n"
    b"\n"
    b"- A bug fix.\n"
    b"\n"
    b"## [0.4.9] - 2026-01-01\n"
    b"\n"
    b"### Added\n"
    b"\n"
    b"- An earlier feature.\n"
)


def _find_bash() -> str | None:
    """Return a bash that can run the script, or ``None``.

    On Windows the ``bash`` on PATH is often the WSL launcher (System32 or
    WindowsApps), which runs a Linux distribution rather than this checkout,
    so Git for Windows' bash, found beside ``git``, is preferred.
    """
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        for root in Path(git).resolve().parents:
            candidate = root / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    bash = shutil.which("bash")
    if bash and not any(part in bash.lower() for part in ("system32", "windowsapps")):
        return bash
    return None


BASH = _find_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")


class Project:
    """A temporary project holding a copy of the script, a version file and a changelog."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, root / "scripts" / "bump-version.sh")
        self.version_file = root / "src" / "examplepkg" / "_version.txt"
        self.version_file.parent.mkdir(parents=True)
        self.version_file.write_bytes(b"0.5.0a1\n")
        self.changelog = root / "CHANGELOG.md"
        self.changelog.write_bytes(CHANGELOG)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        assert BASH is not None
        return subprocess.run(
            [BASH, "scripts/bump-version.sh", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def snapshot(self) -> tuple[bytes, bytes]:
        return self.version_file.read_bytes(), self.changelog.read_bytes()


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return Project(tmp_path)


def test_no_argument_prints_current_version_and_changes_nothing(
    project: Project,
) -> None:
    before = project.snapshot()
    result = project.run()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0.5.0a1"
    assert project.snapshot() == before


def test_final_version_writes_version_and_rolls_changelog(project: Project) -> None:
    day_before = datetime.date.today().isoformat()
    result = project.run("0.5.0")
    day_after = datetime.date.today().isoformat()
    assert result.returncode == 0, result.stderr
    assert project.version_file.read_bytes() == b"0.5.0\n"

    def rolled(day: str) -> bytes:
        return CHANGELOG.replace(
            b"## [Unreleased]\n",
            b"## [Unreleased]\n\n## [0.5.0] - " + day.encode() + b"\n",
            1,
        )

    assert project.changelog.read_bytes() in {rolled(day_before), rolled(day_after)}


@pytest.mark.parametrize("version", ["0.5.0a2", "0.5.0b1", "0.5.0rc1"])
def test_pre_release_writes_version_and_leaves_changelog_alone(
    project: Project, version: str
) -> None:
    result = project.run(version)
    assert result.returncode == 0, result.stderr
    assert project.version_file.read_bytes() == f"{version}\n".encode()
    assert project.changelog.read_bytes() == CHANGELOG
    assert "skipped" in result.stdout.lower()


@pytest.mark.parametrize(
    "version",
    ["v0.5.0", "0.5", "0.5.0-alpha", "", "0.5.0a", "0.5.0.1", "0.5.0 "],
)
def test_malformed_version_is_refused_and_changes_nothing(
    project: Project, version: str
) -> None:
    before = project.snapshot()
    result = project.run(version)
    assert result.returncode != 0
    assert result.stderr.strip()
    assert project.snapshot() == before


@pytest.mark.parametrize("version", ["0.5.0", "0.5.0rc1"])
def test_version_file_is_written_with_lf_only(project: Project, version: str) -> None:
    result = project.run(version)
    assert result.returncode == 0, result.stderr
    data = project.version_file.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")
