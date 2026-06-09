# LocalStack Integration Test for the AWS Bundle Backend

**Status:** Approved
**Date:** 2026-06-09
**Target version:** v0.2.0 (test/infrastructure only — no production change, no version bump on this branch)
**Author:** Matthew Westwood-Hill

---

## 1. Summary

Add an opt-in integration test that exercises the `KONFIG_AWS_SECRETS_MANAGER` env-var
bundle backend end-to-end against a real AWS Secrets Manager API, served locally by
[LocalStack](https://www.localstack.cloud/) in Docker. The unit tests deliberately mock
the boto3 client; this test exercises the genuine boto3 path that those mocks stand in
for.

The test is gated so it never affects the normal `pytest` run or the existing CI matrix:
it auto-skips when boto3 is not installed or LocalStack is not reachable.

---

## 2. Motivation

The `AWSSecretsBundleBackend` is fully unit-tested with an injected fake client, which
proves the logic (TTL cache, re-fetch-before-write, JSON-bundle CRUD) deterministically.
What the unit tests cannot prove is that the **real** boto3 wiring works: that
`_create_client` builds a client that reaches Secrets Manager, that the env-var selection
path constructs a working backend, and that `get_secret_value`/`put_secret_value` against
a real API behave as the code assumes. A LocalStack-backed round-trip closes that gap
cheaply and locally, with no AWS account or cost.

---

## 3. Design decisions (confirmed)

| Decision | Choice |
|----------|--------|
| Provisioning | Commit a `docker-compose.yml`; the test connects to `localhost:4566` and auto-skips if unreachable. |
| CI | Local-only for now. The existing CI matrix is untouched and never needs Docker. |
| Scope | Full CRUD round-trip through the real `Secrets` + env-var path, with persistence verified via a fresh direct client. Deterministic logic (TTL/refresh/re-fetch) is not re-tested here. |
| Branch | `feat/localstack-integration-tests` off `main`, merged into `release/v0.2.0` later. |

---

## 4. Architecture

### 4.1 Layout

```
docker-compose.yml                          # repo root — LocalStack service
tests/
└── integration/
    ├── __init__.py
    └── test_aws_localstack.py              # the integration test + fixtures
```

The test lives in `tests/integration/`, separate from `tests/test_secrets/`. This keeps
it clear of the autouse env-clearing fixture in `tests/test_secrets/conftest.py` (which
would otherwise need consideration) and signals intent. `testpaths = ["tests"]` still
collects it.

### 4.2 Marker registration

Register a `localstack` marker in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "localstack: integration tests requiring a running LocalStack container (auto-skipped if unavailable)",
]
```

This allows `pytest -m localstack` (run only integration tests) and
`pytest -m "not localstack"` (exclude them), with no unknown-marker warnings.

### 4.3 Gating — three independent skip gates

1. **boto3 absent:** `boto3 = pytest.importorskip("boto3")` at module top. Because boto3
   is only in the `aws` extra (not `dev`), the existing CI matrix — which installs
   `.[dev]` — skips this whole module at import.
2. **LocalStack unreachable:** a fast TCP connect to `127.0.0.1:4566` with a short
   timeout (≈0.5s). If it fails, the test skips with a clear reason. A socket check is
   used rather than a boto3 call to avoid boto3's multi-second retry/backoff on a closed
   endpoint.
3. **Marker:** every test in the module carries `@pytest.mark.localstack` (module-level
   `pytestmark`).

Net effect: plain `pytest` with no Docker and no boto3 → the module is skipped, never
failed.

### 4.4 Provisioning — `docker-compose.yml`

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

Developer workflow: `docker compose up -d` → `pip install -e ".[dev,aws]"` →
`pytest -m localstack`.

### 4.5 Fixtures and test flow

**Endpoint/credentials fixture** (function-scoped, autouse within the module): sets, via
`monkeypatch`, dummy credentials and the LocalStack endpoint so both the test's own boto3
client and konfig's internal `_create_client` reach LocalStack:

- `AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`
- `AWS_DEFAULT_REGION=us-east-1`
- `AWS_ENDPOINT_URL=http://localhost:4566`

Setting `AWS_ENDPOINT_URL` (honoured natively by boto3 ≥ 1.34) is what makes konfig's
unmodified `_create_client` talk to LocalStack — so the **real** env-var-selected path is
exercised, not a special test-only client.

**Bundle-secret fixture** (function-scoped): builds a direct boto3 `secretsmanager`
client, creates a uniquely-named secret (e.g. `konfig-itest/<uuid4-suffix>`) seeded
with `{"api_key": "sk-seeded"}` via `create_secret`, yields the returned ARN, and on
teardown calls `delete_secret(ForceDeleteWithoutRecovery=True)`. The `uuid4` suffix avoids
cross-run collisions.

**The test** (`test_bundle_backend_full_crud_round_trip`):
1. `monkeypatch.setenv("KONFIG_AWS_SECRETS_MANAGER", arn)`.
2. `secrets = Secrets()` — the env var selects `AWSSecretsBundleBackend`, whose real
   client points at LocalStack.
3. Assert `secrets.get("api_key") == "sk-seeded"`.
4. `secrets.set("db_password", "pw-123")`; assert `secrets.has("db_password")` and
   `"db_password" in secrets.list_keys()` and `secrets.get("db_password") == "pw-123"`.
5. **Persistence check:** using a *fresh* direct boto3 client, `get_secret_value` on the
   ARN, parse the JSON, and assert it contains both `api_key` and `db_password` — proving
   the write reached LocalStack rather than living only in the in-process cache.
6. `secrets.delete("api_key")`; assert `secrets.has("api_key") is False`; and via a fresh
   direct read, assert `api_key` is gone from the stored JSON.

### 4.6 Error handling / edge cases

- All AWS interaction is inside the skip-gated module, so failures only occur when a
  developer has explicitly brought up LocalStack.
- The bundle-secret fixture's teardown is best-effort: a `delete_secret` failure during
  teardown should not mask a test result (wrap teardown deletion so it does not raise).
- Region in LocalStack ARNs (`us-east-1`, account `000000000000`) parses correctly through
  the backend's existing `_parse_region`.

---

## 5. Documentation

Add a "Running the LocalStack integration test" subsection to `README.md`:

```bash
docker compose up -d                 # start LocalStack
pip install -e ".[dev,aws]"          # boto3 + dev tools
pytest -m localstack                 # run only the integration test
docker compose down                  # stop LocalStack
```

Note that the test auto-skips when LocalStack is not running.

Add a CHANGELOG line under the existing undated `## [0.2.0]` heading (no AI-authorship
references), e.g. under a `### Added` or new `### Tests` note:

- "Opt-in LocalStack integration test for the AWS Secrets Manager bundle backend
  (`pytest -m localstack`), with a `docker-compose.yml` for local provisioning."

---

## 6. Out of scope

- A dedicated CI job running LocalStack (deferred; may be added later).
- testcontainers-based auto-provisioning.
- Re-testing TTL expiry, `refresh()`, or re-fetch-before-write against LocalStack (already
  covered deterministically by unit tests).
- Any production code change or `_version.txt` bump on this branch.
- Testing the existing per-key `AWSSecretsManagerBackend` against LocalStack.
