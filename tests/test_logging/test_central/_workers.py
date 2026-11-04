"""Sender processes for the end-to-end tests.

Kept at module level in an importable module so the ``spawn`` start method
can locate them in child processes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


def run_sender(root: str, store: str, master_key: str, label: str, count: int) -> None:
    """Run an ``AppContext`` sender that logs ``count`` distinct messages."""
    for name in list(os.environ):
        if name.startswith("KONFIG_LOG_") or name in (
            "ECS_CONTAINER_METADATA_URI_V4",
            "KUBERNETES_SERVICE_HOST",
        ):
            del os.environ[name]
    os.environ["KONFIG_MASTER_KEY"] = master_key
    os.environ["KONFIG_LOG_CENTRAL"] = "true"
    os.environ["KONFIG_LOG_INSTANCE_LABEL"] = label

    from konfig import AppContext

    base = Path(root) / label
    defaults = {
        "logging": {"log_dir": str(base / "logs"), "console_output": "none"},
        "secrets": {"backend": "encrypted_file", "file_path": store},
    }
    with AppContext(
        name=f"Sender {label}",
        version="1.0.0",
        config_file=base / "missing.yaml",
        system_config_file=base / "missing-system.yaml",
        defaults=defaults,
    ):
        log = logging.getLogger(f"e2e.{label}")
        for i in range(count):
            log.info("message %s %d", label, i)
