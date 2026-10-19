"""Tests for instance identity detection."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from konfig.logging.central.identity import detect_instance

TASK = {
    "Cluster": "arn:aws:ecs:eu-west-1:123456789012:cluster/prod",
    "TaskARN": "arn:aws:ecs:eu-west-1:123456789012:task/prod/abc123",
    "LaunchType": "FARGATE",
    "AvailabilityZone": "eu-west-1a",
}
CONTAINER = {"Name": "worker", "DockerId": "deadbeef"}


def _identity(tmp_path: Path, env: dict[str, str], **kwargs: object) -> dict:
    return detect_instance(
        app_id="myapp",
        app_name="My App",
        version="1.2.3",
        run_dir="2026-10-20T10-00-00",
        environ=env,
        dockerenv=tmp_path / "no-dockerenv",
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def metadata_server() -> Iterator[tuple[str, dict[str, float]]]:
    delay = {"seconds": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            time.sleep(delay["seconds"])
            body = TASK if self.path.endswith("/task") else CONTAINER
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v4/abc", delay
    server.shutdown()
    server.server_close()


def test_always_present_fields(tmp_path: Path) -> None:
    instance = _identity(tmp_path, {})
    assert instance["hostname"] == socket.gethostname()
    assert instance["pid"] == os.getpid()
    assert instance["app_id"] == "myapp"
    assert instance["app_name"] == "My App"
    assert instance["version"] == "1.2.3"
    assert instance["run_dir"] == "2026-10-20T10-00-00"
    assert instance["platform"] == "host"
    assert "label" not in instance


def test_label(tmp_path: Path) -> None:
    assert _identity(tmp_path, {}, label="worker-3")["label"] == "worker-3"


def test_container_detected_by_dockerenv(tmp_path: Path) -> None:
    marker = tmp_path / ".dockerenv"
    marker.touch()
    instance = detect_instance(
        app_id="a", app_name="A", version="1", environ={}, dockerenv=marker
    )
    assert instance["platform"] == "container"


def test_kubernetes(tmp_path: Path) -> None:
    env = {
        "KUBERNETES_SERVICE_HOST": "10.0.0.1",
        "POD_NAMESPACE": "logging",
        "NODE_NAME": "node-7",
        "POD_NAME": "worker-abc",
    }
    instance = _identity(tmp_path, env)
    assert instance["platform"] == "kubernetes"
    assert instance["kubernetes"] == {
        "pod_name": "worker-abc",
        "namespace": "logging",
        "node_name": "node-7",
    }


def test_kubernetes_pod_name_defaults_to_hostname(tmp_path: Path) -> None:
    instance = _identity(tmp_path, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"})
    assert instance["kubernetes"] == {"pod_name": socket.gethostname()}


def test_ecs_metadata(
    tmp_path: Path, metadata_server: tuple[str, dict[str, float]]
) -> None:
    uri, _ = metadata_server
    instance = _identity(tmp_path, {"ECS_CONTAINER_METADATA_URI_V4": uri})
    assert instance["platform"] == "ecs"
    assert instance["ecs"] == {
        "task_arn": TASK["TaskARN"],
        "cluster": TASK["Cluster"],
        "launch_type": "FARGATE",
        "availability_zone": "eu-west-1a",
        "container_name": "worker",
    }


def test_ecs_timeout_is_silent(
    tmp_path: Path,
    metadata_server: tuple[str, dict[str, float]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    uri, delay = metadata_server
    delay["seconds"] = 2.0
    started = time.monotonic()
    with caplog.at_level("WARNING"):
        instance = _identity(
            tmp_path, {"ECS_CONTAINER_METADATA_URI_V4": uri}, ecs_timeout=0.2
        )
    assert time.monotonic() - started < 1.5
    assert instance["platform"] == "ecs"
    assert "ecs" not in instance
    assert caplog.records == []


def test_ecs_unreachable_is_silent(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {"ECS_CONTAINER_METADATA_URI_V4": f"http://127.0.0.1:{port}/v4"}
    instance = _identity(tmp_path, env)
    assert instance["platform"] == "ecs"
    assert "ecs" not in instance


def test_ecs_non_http_scheme_refused(tmp_path: Path) -> None:
    secret = tmp_path / "task"
    secret.write_text(json.dumps(TASK))
    env = {"ECS_CONTAINER_METADATA_URI_V4": tmp_path.as_uri()}
    instance = _identity(tmp_path, env)
    assert "ecs" not in instance
