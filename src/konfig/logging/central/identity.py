"""Detect the identity block that tags every forwarded log record."""

from __future__ import annotations

import json
import logging
import os
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

logger = logging.getLogger(__name__)

ECS_METADATA_ENV = "ECS_CONTAINER_METADATA_URI_V4"
ECS_TIMEOUT = 1.0
DOCKERENV = Path("/.dockerenv")

# Kubernetes downward API variables included in the identity when present.
_KUBERNETES_ENV = {
    "pod_name": "POD_NAME",
    "namespace": "POD_NAMESPACE",
    "node_name": "NODE_NAME",
}


def _fetch_json(url: str, timeout: float) -> Any:
    # Only plain HTTP(S) is fetched: the metadata endpoint is link-local HTTP,
    # and refusing other schemes keeps urllib away from file:// and friends.
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("unsupported metadata URL scheme")
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 (scheme checked)
        return json.loads(response.read().decode("utf-8"))


def _ecs_metadata(uri: str, timeout: float) -> dict[str, Any]:
    """Read task and container details from the ECS task metadata endpoint v4.

    Failures are silent apart from a debug log; whatever was read is kept.
    """
    details: dict[str, Any] = {}
    base = uri.rstrip("/")
    try:
        task = _fetch_json(f"{base}/task", timeout)
        if isinstance(task, dict):
            for key, name in (
                ("task_arn", "TaskARN"),
                ("cluster", "Cluster"),
                ("launch_type", "LaunchType"),
                ("availability_zone", "AvailabilityZone"),
            ):
                if task.get(name):
                    details[key] = task[name]
    except Exception:
        logger.debug("Could not read ECS task metadata", exc_info=True)
    try:
        container = _fetch_json(base, timeout)
        if isinstance(container, dict) and container.get("Name"):
            details["container_name"] = container["Name"]
    except Exception:
        logger.debug("Could not read ECS container metadata", exc_info=True)
    return details


def detect_instance(
    *,
    app_id: str,
    app_name: str,
    version: str,
    run_dir: Optional[str] = None,
    label: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
    ecs_timeout: float = ECS_TIMEOUT,
    dockerenv: Path = DOCKERENV,
) -> dict[str, Any]:
    """Build the identity block for this instance.

    Always includes the hostname, PID, application details, run directory
    name and label (when set), plus a ``platform`` of ``ecs``,
    ``kubernetes``, ``container`` or ``host`` with platform-specific detail.
    """
    env = os.environ if environ is None else environ
    hostname = socket.gethostname()
    instance: dict[str, Any] = {
        "hostname": hostname,
        "pid": os.getpid(),
        "app_id": app_id,
        "app_name": app_name,
        "version": version,
        "run_dir": run_dir,
    }
    if label:
        instance["label"] = label

    ecs_uri = env.get(ECS_METADATA_ENV)
    if ecs_uri:
        instance["platform"] = "ecs"
        ecs = _ecs_metadata(ecs_uri, ecs_timeout)
        if ecs:
            instance["ecs"] = ecs
    elif env.get("KUBERNETES_SERVICE_HOST"):
        instance["platform"] = "kubernetes"
        kubernetes: dict[str, Any] = {"pod_name": hostname}
        for key, name in _KUBERNETES_ENV.items():
            if env.get(name):
                kubernetes[key] = env[name]
        instance["kubernetes"] = kubernetes
    elif dockerenv.exists():
        instance["platform"] = "container"
    else:
        instance["platform"] = "host"
    return instance
