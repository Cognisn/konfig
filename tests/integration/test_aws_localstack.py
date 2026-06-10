"""Opt-in LocalStack integration tests for the AWS Secrets Manager bundle backend.

Auto-skips unless boto3 is installed AND a LocalStack container is reachable on
localhost:4566. Run explicitly with: pytest -m localstack
Start LocalStack first with: docker compose up -d
"""

from __future__ import annotations

import json
import socket
import uuid
from collections.abc import Iterator

import pytest

# Skip gate 1: boto3 not installed (it is only in the `aws` extra, not `dev`).
boto3 = pytest.importorskip("boto3")

from konfig import Secrets

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


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point both the test's client and konfig's internal client at LocalStack.

    Setting AWS_ENDPOINT_URL (honoured by boto3 >= 1.34) makes the unmodified
    AWSSecretsBundleBackend._create_client reach LocalStack, so the real
    env-var-selected code path is exercised.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ENDPOINT_URL", ENDPOINT_URL)


def _client():
    """A direct boto3 Secrets Manager client pointing at LocalStack."""
    return boto3.client(
        "secretsmanager",
        region_name=REGION,
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture
def bundle_arn() -> Iterator[str]:
    """Create a uniquely-named JSON-bundle secret and yield its ARN; delete on teardown."""
    client = _client()
    name = f"konfig-itest/{uuid.uuid4().hex}"
    response = client.create_secret(
        Name=name, SecretString=json.dumps({"api_key": "sk-seeded"})
    )
    arn = response["ARN"]
    try:
        yield arn
    finally:
        try:
            client.delete_secret(SecretId=arn, ForceDeleteWithoutRecovery=True)
        except Exception:  # best-effort cleanup; never mask the test result
            pass


def test_bundle_backend_full_crud_round_trip(
    bundle_arn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The env var selects AWSSecretsBundleBackend; its real client hits LocalStack.
    monkeypatch.setenv("KONFIG_AWS_SECRETS_MANAGER", bundle_arn)

    secrets = Secrets()

    # Read the seeded value.
    assert secrets.get("api_key") == "sk-seeded"

    # Write a new key and read it back via the konfig API.
    secrets.set("db_password", "pw-123")
    assert secrets.has("db_password") is True
    assert "db_password" in secrets.list_keys()
    assert secrets.get("db_password") == "pw-123"

    # Persistence check: the write reached LocalStack, not just the in-process cache.
    stored = json.loads(_client().get_secret_value(SecretId=bundle_arn)["SecretString"])
    assert stored == {"api_key": "sk-seeded", "db_password": "pw-123"}

    # Delete a key and confirm it is gone both via the API and in the stored bundle.
    secrets.delete("api_key")
    assert secrets.has("api_key") is False
    stored_after = json.loads(
        _client().get_secret_value(SecretId=bundle_arn)["SecretString"]
    )
    assert "api_key" not in stored_after
    assert stored_after == {"db_password": "pw-123"}
