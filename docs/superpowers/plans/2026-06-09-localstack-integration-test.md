# LocalStack Integration Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, auto-skipping LocalStack integration test that exercises the `KONFIG_AWS_SECRETS_MANAGER` bundle backend end-to-end against a real Secrets Manager API.

**Architecture:** A new `tests/integration/` module connects to LocalStack at `localhost:4566`, seeds a JSON-bundle secret via a direct boto3 client, then drives the real `Secrets` env-var path (whose `_create_client` reaches LocalStack via `AWS_ENDPOINT_URL`) through a full CRUD round-trip, verifying persistence with a fresh direct read. Three skip gates (no boto3 / endpoint unreachable / marker) keep the existing CI matrix untouched.

**Tech Stack:** Python 3.12+, pytest, boto3 (`konfig[aws]`), Docker + LocalStack (`docker-compose.yml`).

---

## File Structure

- Create: `docker-compose.yml` (repo root) — LocalStack service for local provisioning.
- Create: `tests/integration/__init__.py` — package marker.
- Create: `tests/integration/test_aws_localstack.py` — the integration test, fixtures, and skip gates.
- Modify: `pyproject.toml` — register the `localstack` pytest marker.
- Modify: `README.md` — "Running the LocalStack integration test" section.
- Modify: `CHANGELOG.md` — line under the existing undated `## [0.2.0]` heading.

No production code changes. No `_version.txt` change on this branch.

---

## Task 1: Register the `localstack` marker

**Files:**
- Modify: `pyproject.toml` (the `[tool.pytest.ini_options]` table)

- [ ] **Step 1: Read the current pytest config**

Run: `grep -n -A3 "tool.pytest.ini_options" pyproject.toml`
Expected: shows
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Add the marker registration**

Edit `pyproject.toml` so the `[tool.pytest.ini_options]` table becomes exactly:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "localstack: integration tests requiring a running LocalStack container (auto-skipped if unavailable)",
]
```

- [ ] **Step 3: Verify the marker is registered and no tests break**

Run: `pytest --markers | grep localstack`
Expected: prints the line `@pytest.mark.localstack: integration tests requiring a running LocalStack container (auto-skipped if unavailable)`

Run: `pytest -q`
Expected: the existing suite still passes (e.g. `166 passed, 3 skipped`).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Register localstack pytest marker"
```

---

## Task 2: Add the LocalStack docker-compose file

**Files:**
- Create: `docker-compose.yml` (repo root)

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
services:
  localstack:
    image: localstack/localstack:latest
    ports:
      - "4566:4566"
    environment:
      - SERVICES=secretsmanager
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4566/_localstack/health"]
      interval: 5s
      timeout: 5s
      retries: 10
```

- [ ] **Step 2: Validate the compose file syntax**

Run: `docker compose config -q`
Expected: no output and exit code 0 (the file is valid). If Docker is not installed in this environment, run `python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` instead and expect no error. Report which check you used.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "Add docker-compose for LocalStack integration testing"
```

---

## Task 3: Create the integration test package and skip gates

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_aws_localstack.py`

This task creates the module with its three skip gates and a trivial gate-proving test, but NOT yet the full CRUD test (Task 4). This isolates the gating logic so we can confirm it skips cleanly.

- [ ] **Step 1: Create the package marker**

Create `tests/integration/__init__.py` as an empty file (zero bytes).

- [ ] **Step 2: Create the test module with skip gates and a connectivity test**

Create `tests/integration/test_aws_localstack.py`:

```python
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


# Skip gate 3 (marker) + skip gate 2 (endpoint unreachable), combined.
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
```

The module has exactly one `pytestmark` — the list combining the `localstack` marker and the reachability `skipif`.

- [ ] **Step 3: Verify it skips cleanly when LocalStack is down**

Run (with LocalStack NOT running): `pytest tests/integration/ -v`
Expected: `test_localstack_is_reachable` is SKIPPED with the reachability reason (or, if boto3 is not installed, the whole module is skipped at import via `importorskip`). Either way: no failures.

Run: `pytest -q`
Expected: full suite still green; the integration test shows as skipped, not failed.

- [ ] **Step 4: (If Docker available) verify it runs when LocalStack is up**

Run: `docker compose up -d` then `pytest -m localstack -v`
Expected: `test_localstack_is_reachable` PASSES. Then `docker compose down`.
If Docker is unavailable in this environment, note that this step could not be executed and rely on Step 3's skip behaviour.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_aws_localstack.py
git commit -m "Add LocalStack integration test package with skip gates"
```

---

## Task 4: Full CRUD round-trip test

**Files:**
- Modify: `tests/integration/test_aws_localstack.py`

Add the fixtures and the end-to-end test. The seeded value travels: direct boto3 `create_secret` → konfig `Secrets` (real boto3 client via `AWS_ENDPOINT_URL`) → assertions → fresh direct `get_secret_value` for the persistence check.

- [ ] **Step 1: Add imports at the top of `tests/integration/test_aws_localstack.py`**

Add these to the existing imports (keep `from __future__ import annotations` first):

```python
import json
import uuid
from collections.abc import Iterator

from konfig import Secrets
```

- [ ] **Step 2: Add the credentials/endpoint fixture and the bundle-secret fixture**

Append to `tests/integration/test_aws_localstack.py`:

```python
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
```

- [ ] **Step 3: Add the full CRUD round-trip test**

Append to `tests/integration/test_aws_localstack.py`:

```python
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
```

- [ ] **Step 4: Verify skip behaviour is unchanged when LocalStack is down**

Run (LocalStack NOT running): `pytest tests/integration/ -v`
Expected: both tests SKIPPED (reachability reason), no failures.

Run: `pytest -q`
Expected: full suite green; integration tests skipped.

- [ ] **Step 5: (If Docker available) run the real round-trip**

Run: `docker compose up -d`, wait for health (`docker compose ps` shows healthy), then `pytest -m localstack -v`.
Expected: `test_localstack_is_reachable` and `test_bundle_backend_full_crud_round_trip` both PASS. Then `docker compose down`.
If Docker is unavailable here, note it and rely on the skip verification in Step 4. Do NOT weaken the test to make it pass without LocalStack.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_aws_localstack.py
git commit -m "Add full CRUD round-trip integration test against LocalStack"
```

---

## Task 5: Documentation — README and CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the README section**

In `README.md`, find the AWS Secrets Manager / Secrets section added for the bundle backend. Immediately after it, add:

````markdown
### Running the LocalStack integration test

The AWS bundle backend has an opt-in integration test that runs against a local
[LocalStack](https://www.localstack.cloud/) container (no AWS account needed). It
auto-skips when LocalStack is not running, so it never affects the normal test run.

```bash
docker compose up -d         # start LocalStack
pip install -e ".[dev,aws]"  # boto3 + dev tools
pytest -m localstack         # run only the integration test
docker compose down          # stop LocalStack
```
````

If the README has no AWS/Secrets section yet (it may differ), place this near the other testing/usage content and report where you put it.

- [ ] **Step 2: Add the CHANGELOG line**

In `CHANGELOG.md`, under the existing undated `## [0.2.0]` heading, add (create a `### Tests` subsection if none fits, placing it after `### Added`):

```markdown
### Tests

- Opt-in LocalStack integration test for the AWS Secrets Manager bundle backend
  (`pytest -m localstack`), with a `docker-compose.yml` for local provisioning.
```

Use Australian English. No AI/Claude/Anthropic references.

- [ ] **Step 3: Verify the suite still passes**

Run: `pytest -q`
Expected: full suite green (integration tests skipped without LocalStack).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document LocalStack integration test"
```

---

## Self-Review Notes

- **Spec coverage:** §4.1 layout → Tasks 3,4; §4.2 marker → Task 1; §4.3 three skip gates → Task 3 (importorskip, socket skipif, marker); §4.4 compose → Task 2; §4.5 fixtures + flow → Task 4; §4.6 best-effort teardown + region parsing → Task 4 (teardown try/except; LocalStack `us-east-1` ARN parses via existing `_parse_region`); §5 docs → Task 5.
- **Placeholder scan:** none — every code step has complete content.
- **Consistency:** `ENDPOINT_URL`, `REGION`, `_client()`, `bundle_arn`, `_localstack_reachable`, and the single list-form `pytestmark` are defined in Task 3 and reused unchanged in Task 4. The `boto3 = pytest.importorskip("boto3")` binding from Task 3 is what Task 4's `_client()` uses.
- **No production change / no version bump** on this branch, per spec §6.
