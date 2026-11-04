"""Capture normalised local log output from ``AppContext`` for regression checks.

The fixtures beside this module were produced with konfig 0.4.1, before
centralised log forwarding existed. Volatile values (timestamps, the PID,
platform details and temporary paths) are replaced with placeholders so the
remaining bytes can be compared exactly.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

_SUBSTITUTIONS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00)?"), "<TS>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}"), "<RUN>"),
    (re.compile(r'"pid": \d+'), '"pid": <PID>'),
    (re.compile(r"PID:       \d+"), "PID:       <PID>"),
    (re.compile(r"Platform:  [^\"\n]*"), "Platform:  <PLATFORM>"),
    (re.compile(r"Python:    [^\"\n]*"), "Python:    <PYTHON>"),
    (re.compile(r'File \\?"(.*?)\\?", line \d+'), "File <FILE>, line <N>"),
]


def capture_app_log(tmp_path: Path, log_format: str) -> str:
    """Run a short ``AppContext`` session and return its normalised app.log."""
    from konfig import AppContext

    log_dir = tmp_path / "logs"
    defaults = {
        "logging": {
            "log_dir": str(log_dir),
            "format": log_format,
            "console_output": "none",
        },
        "secrets": {
            "backend": "encrypted_file",
            "file_path": str(tmp_path / "secrets.enc"),
            "master_key": "regression-master-key",
        },
    }
    with AppContext(
        name="Regression App",
        version="9.9.9",
        config_file=tmp_path / "missing.yaml",
        system_config_file=tmp_path / "missing-system.yaml",
        defaults=defaults,
    ) as ctx:
        app_logger = logging.getLogger("regression.app")
        app_logger.info("Plain message %s", 42)
        app_logger.warning("A warning")
        try:
            raise ValueError("boom")
        except ValueError:
            app_logger.exception("Something failed")
        run_dir = ctx.log_manager.run_dir
    assert run_dir is not None
    text = (run_dir / "app.log").read_text(encoding="utf-8")
    text = text.replace(str(tmp_path).replace("\\", "\\\\"), "<TMP>")
    text = text.replace(str(tmp_path), "<TMP>")
    text = re.sub(r"<TMP>[\\/]+logs[\\/]+", "<TMP>/logs/", text)
    for pattern, replacement in _SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text
