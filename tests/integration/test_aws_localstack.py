"""Opt-in LocalStack integration tests for the AWS Secrets Manager bundle backend.

Auto-skips unless boto3 is installed AND a LocalStack container is reachable on
localhost:4566. Run explicitly with: pytest -m localstack
Start LocalStack first with: docker compose up -d
"""
from __future__ import annotations

import socket

import pytest

# Skip gate 1: boto3 not installed (it is only in the `aws` extra, not `dev`).
boto3 = pytest.importorskip("boto3")

LOCALSTACK_HOST = "127.0.0.1"
LOCALSTACK_PORT = 4566
ENDPOINT_URL = f"http://{LOCALSTACK_HOST}:{LOCALSTACK_PORT}"
REGION = "us-east-1"


def _localstack_reachable() -> bool:
    """Fast TCP check so we skip (not hang) when LocalStack is down."""
    try:
        with socket.create_connection((LOCALSTACK_HOST, LOCALSTACK_PORT), timeout=0.5):
            return True
    except OSError:
        return False


# The `localstack` marker (opt-in selector) plus skip gate 2: endpoint unreachable.
pytestmark = [
    pytest.mark.localstack,
    pytest.mark.skipif(
        not _localstack_reachable(),
        reason=f"LocalStack not reachable at {ENDPOINT_URL} (start it with `docker compose up -d`)",
    ),
]


def test_localstack_is_reachable() -> None:
    """Sanity check: when this module runs at all, LocalStack is up."""
    assert _localstack_reachable()
