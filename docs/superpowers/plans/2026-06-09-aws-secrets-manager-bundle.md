# AWS Secrets Manager Bundle Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an env-var-driven AWS Secrets Manager backend where `KONFIG_AWS_SECRETS_MANAGER=<ARN>` makes konfig read and write secrets to a single designated AWS secret holding a JSON bundle.

**Architecture:** A new `AWSSecretsBundleBackend` implements the existing `SecretBackend` interface against one AWS secret whose `SecretString` is a JSON object (konfig keys are JSON keys). It uses a TTL read cache with write-through, and re-fetches the bundle before each write to narrow the lost-update window. `Secrets.__init__` checks the env var first and, when set, selects this backend as a hard override over an explicit `backend=` arg and over config. The existing per-key `AWSSecretsManagerBackend` is untouched.

**Tech Stack:** Python 3.12+, boto3 (optional `konfig[aws]` extra), pytest. Tests inject a fake boto3 client and a controllable clock — no real AWS calls.

---

## File Structure

- Create: `src/konfig/secrets/aws_bundle_backend.py` — the new bundle backend + ARN parsing helper.
- Modify: `src/konfig/secrets/secrets.py` — env-var selection and precedence; TTL resolution from settings.
- Create: `tests/test_secrets/test_aws_bundle_backend.py` — backend unit tests with fake client + clock.
- Modify: `tests/test_secrets/test_secrets.py` — env-var override precedence test.
- Modify: `src/konfig/_version.txt` — bump to `0.2.0`.
- Modify: `CHANGELOG.md` — 0.2.0 entry.
- Modify: `CLAUDE.md`, `README.md` — document the env-var bundle mode.

**Shared test helpers** (defined once at the top of `test_aws_bundle_backend.py`, used by many tests):

```python
"""Tests for the AWS Secrets Manager bundle backend."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend

ARN = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:myapp/secrets-AbCdEf"


class _ResourceNotFound(Exception):
    pass


class FakeSMClient:
    """Minimal stand-in for a boto3 secretsmanager client."""

    def __init__(self, secret_string: str | None = None, missing: bool = False) -> None:
        self._secret_string = secret_string
        self._missing = missing
        self.put_calls: list[str] = []
        self.get_calls = 0
        self.exceptions = SimpleNamespace(ResourceNotFoundException=_ResourceNotFound)

    def get_secret_value(self, SecretId: str) -> dict:
        self.get_calls += 1
        if self._missing:
            raise self.exceptions.ResourceNotFoundException()
        return {"SecretString": self._secret_string}

    def put_secret_value(self, SecretId: str, SecretString: str) -> None:
        self.put_calls.append(SecretString)
        self._secret_string = SecretString
        self._missing = False


class Clock:
    """Controllable monotonic clock for TTL tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt
```

---

## Task 1: ARN parsing & constructor

**Files:**
- Create: `src/konfig/secrets/aws_bundle_backend.py`
- Test: `tests/test_secrets/test_aws_bundle_backend.py`

- [ ] **Step 1: Write the failing tests**

Add the shared helpers block above to `tests/test_secrets/test_aws_bundle_backend.py`, then append:

```python
class TestArnParsing:
    def test_region_extracted_from_arn(self) -> None:
        backend = AWSSecretsBundleBackend(ARN, client=FakeSMClient("{}"))
        assert backend.region == "eu-west-1"

    def test_malformed_arn_raises(self) -> None:
        with pytest.raises(ValueError):
            AWSSecretsBundleBackend("not-an-arn", client=FakeSMClient("{}"))

    def test_arn_missing_region_raises(self) -> None:
        bad = "arn:aws:secretsmanager::123456789012:secret:x-AbCdEf"
        with pytest.raises(ValueError):
            AWSSecretsBundleBackend(bad, client=FakeSMClient("{}"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'konfig.secrets.aws_bundle_backend'`

- [ ] **Step 3: Write minimal implementation**

Create `src/konfig/secrets/aws_bundle_backend.py`:

```python
"""AWS Secrets Manager single-secret JSON bundle backend (optional)."""
from __future__ import annotations

import json
import time
from typing import Callable

from konfig.secrets.backend import SecretBackend

_NOT_JSON_OBJECT = "Designated AWS secret is not a JSON object."
_NO_SECRET_STRING = (
    "Designated AWS secret has no SecretString (binary secrets are not supported)."
)


def _parse_region(arn: str) -> str:
    """Extract the region from a Secrets Manager ARN.

    ARN shape: ``arn:aws:secretsmanager:<region>:<account>:secret:<name>``.
    """
    parts = arn.split(":")
    if (
        len(parts) < 6
        or parts[0] != "arn"
        or parts[2] != "secretsmanager"
        or not parts[3]
    ):
        raise ValueError(f"Invalid AWS Secrets Manager ARN: {arn!r}")
    return parts[3]


class AWSSecretsBundleBackend(SecretBackend):
    """Reads and writes secrets to a single AWS secret holding a JSON bundle.

    The secret named by ``arn`` stores a JSON object; each konfig key is a key
    within that object. Requires ``boto3`` (``pip install konfig[aws]``).

    Args:
        arn: Full ARN of the designated AWS secret.
        ttl: Read-cache time-to-live in seconds.
        client: Optional pre-built boto3 client (for testing/injection).
        time_func: Monotonic time source (for testing).
    """

    def __init__(
        self,
        arn: str,
        ttl: int = 300,
        client: object | None = None,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._arn = arn
        self._region = _parse_region(arn)
        self._ttl = ttl
        self._time = time_func
        self._client = client if client is not None else self._create_client()
        self._cache: dict[str, str] | None = None
        self._cache_at: float = 0.0

    @property
    def region(self) -> str:
        return self._region

    def _create_client(self):  # pragma: no cover - exercised in Task 6
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager backend. "
                "Install it with: pip install konfig[aws]"
            ) from exc
        return boto3.client("secretsmanager", region_name=self._region)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/secrets/aws_bundle_backend.py tests/test_secrets/test_aws_bundle_backend.py
git commit -m "Add AWS bundle backend ARN parsing and constructor"
```

---

## Task 2: Read path — get / has / list_keys

**Files:**
- Modify: `src/konfig/secrets/aws_bundle_backend.py`
- Test: `tests/test_secrets/test_aws_bundle_backend.py`

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class TestReadPath:
    def test_get_returns_value(self) -> None:
        client = FakeSMClient(json.dumps({"api_key": "sk-123"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.get("api_key") == "sk-123"

    def test_get_missing_key_returns_none(self) -> None:
        client = FakeSMClient(json.dumps({"api_key": "sk-123"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.get("nope") is None

    def test_has(self) -> None:
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.has("a") is True
        assert backend.has("b") is False

    def test_list_keys(self) -> None:
        client = FakeSMClient(json.dumps({"a": "1", "b": "2"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert sorted(backend.list_keys()) == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestReadPath -v`
Expected: FAIL — `AttributeError: 'AWSSecretsBundleBackend' object has no attribute 'get'`

- [ ] **Step 3: Write minimal implementation**

Append these methods to `AWSSecretsBundleBackend` in `src/konfig/secrets/aws_bundle_backend.py`:

```python
    def _fetch(self) -> dict[str, str]:
        """Fetch and parse the bundle directly from AWS (no cache)."""
        try:
            response = self._client.get_secret_value(SecretId=self._arn)
        except self._client.exceptions.ResourceNotFoundException:
            return {}
        raw = response.get("SecretString")
        if raw is None:
            raise ValueError(_NO_SECRET_STRING)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(_NOT_JSON_OBJECT) from exc
        if not isinstance(data, dict):
            raise ValueError(_NOT_JSON_OBJECT)
        return data

    def _bundle(self) -> dict[str, str]:
        """Return the cached bundle, refreshing if the TTL has expired."""
        now = self._time()
        if self._cache is None or (now - self._cache_at) >= self._ttl:
            self._cache = self._fetch()
            self._cache_at = now
        return self._cache

    def get(self, key: str) -> str | None:
        return self._bundle().get(key)

    def has(self, key: str) -> bool:
        return key in self._bundle()

    def list_keys(self) -> list[str]:
        return list(self._bundle().keys())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestReadPath -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/secrets/aws_bundle_backend.py tests/test_secrets/test_aws_bundle_backend.py
git commit -m "Add AWS bundle backend read path (get/has/list_keys)"
```

---

## Task 3: TTL cache & refresh

**Files:**
- Modify: `src/konfig/secrets/aws_bundle_backend.py`
- Test: `tests/test_secrets/test_aws_bundle_backend.py`

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class TestTtlCache:
    def test_reads_within_ttl_hit_cache(self) -> None:
        clock = Clock()
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, ttl=300, client=client, time_func=clock)
        backend.get("a")
        backend.get("a")
        assert client.get_calls == 1  # second read served from cache

    def test_read_after_ttl_refetches(self) -> None:
        clock = Clock()
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, ttl=300, client=client, time_func=clock)
        backend.get("a")
        clock.advance(301)
        backend.get("a")
        assert client.get_calls == 2

    def test_refresh_forces_refetch(self) -> None:
        clock = Clock()
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, ttl=300, client=client, time_func=clock)
        backend.get("a")
        backend.refresh()
        backend.get("a")
        assert client.get_calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestTtlCache -v`
Expected: FAIL — `test_refresh_forces_refetch` fails with `AttributeError: ... has no attribute 'refresh'` (the cache tests may already pass from Task 2's `_bundle`).

- [ ] **Step 3: Write minimal implementation**

Append the `refresh` method to `AWSSecretsBundleBackend`:

```python
    def refresh(self) -> None:
        """Force the next read to re-fetch the bundle from AWS."""
        self._cache = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestTtlCache -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/secrets/aws_bundle_backend.py tests/test_secrets/test_aws_bundle_backend.py
git commit -m "Add AWS bundle backend TTL cache and refresh"
```

---

## Task 4: Error handling & empty-bundle behaviour

**Files:**
- Test: `tests/test_secrets/test_aws_bundle_backend.py`

(The behaviour is already implemented in `_fetch` from Task 2; these tests lock it in.)

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class TestErrorHandling:
    def test_missing_secret_reads_as_empty(self) -> None:
        client = FakeSMClient(missing=True)
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.get("a") is None
        assert backend.list_keys() == []
        assert backend.has("a") is False

    def test_non_json_secret_raises(self) -> None:
        client = FakeSMClient("this-is-not-json")
        backend = AWSSecretsBundleBackend(ARN, client=client)
        with pytest.raises(ValueError, match="not a JSON object"):
            backend.get("a")

    def test_json_array_not_object_raises(self) -> None:
        client = FakeSMClient(json.dumps(["a", "b"]))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        with pytest.raises(ValueError, match="not a JSON object"):
            backend.get("a")

    def test_binary_secret_raises(self) -> None:
        client = FakeSMClient(secret_string=None)  # SecretString is None
        backend = AWSSecretsBundleBackend(ARN, client=client)
        with pytest.raises(ValueError, match="no SecretString"):
            backend.get("a")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestErrorHandling -v`
Expected: PASS (4 passed) — behaviour already implemented in Task 2.

If any fail, fix `_fetch` in `aws_bundle_backend.py` to match the messages in the constants `_NOT_JSON_OBJECT` / `_NO_SECRET_STRING`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_secrets/test_aws_bundle_backend.py
git commit -m "Cover AWS bundle backend error and empty-bundle handling"
```

---

## Task 5: Write path — set / delete with re-fetch and write-through

**Files:**
- Modify: `src/konfig/secrets/aws_bundle_backend.py`
- Test: `tests/test_secrets/test_aws_bundle_backend.py`

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
class TestWritePath:
    def test_set_writes_whole_bundle(self) -> None:
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        backend.set("b", "2")
        assert json.loads(client.put_calls[-1]) == {"a": "1", "b": "2"}

    def test_set_is_readable_via_write_through(self) -> None:
        clock = Clock()
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, ttl=300, client=client, time_func=clock)
        backend.set("b", "2")
        gets_before = client.get_calls
        assert backend.get("b") == "2"          # served from write-through cache
        assert client.get_calls == gets_before  # no extra fetch

    def test_delete_removes_key(self) -> None:
        client = FakeSMClient(json.dumps({"a": "1", "b": "2"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        backend.delete("a")
        assert json.loads(client.put_calls[-1]) == {"b": "2"}

    def test_delete_missing_key_is_noop(self) -> None:
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        backend.delete("nope")
        assert json.loads(client.put_calls[-1]) == {"a": "1"}

    def test_set_refetches_before_write(self) -> None:
        # Cache is warmed, then the secret changes underneath; set must not
        # clobber the externally-added key.
        clock = Clock()
        client = FakeSMClient(json.dumps({"a": "1"}))
        backend = AWSSecretsBundleBackend(ARN, ttl=300, client=client, time_func=clock)
        backend.get("a")  # warms cache with {"a": "1"}
        client._secret_string = json.dumps({"a": "1", "external": "x"})
        backend.set("b", "2")
        assert json.loads(client.put_calls[-1]) == {"a": "1", "external": "x", "b": "2"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestWritePath -v`
Expected: FAIL — `AttributeError: ... has no attribute 'set'`

- [ ] **Step 3: Write minimal implementation**

Append these methods to `AWSSecretsBundleBackend`:

```python
    def _write(self, bundle: dict[str, str]) -> None:
        """Persist the whole bundle to AWS and update the write-through cache."""
        self._client.put_secret_value(
            SecretId=self._arn, SecretString=json.dumps(bundle)
        )
        self._cache = bundle
        self._cache_at = self._time()

    def set(self, key: str, value: str) -> None:
        bundle = self._fetch()  # re-fetch before write to narrow the race window
        bundle[key] = value
        self._write(bundle)

    def delete(self, key: str) -> None:
        bundle = self._fetch()  # re-fetch before write to narrow the race window
        bundle.pop(key, None)
        self._write(bundle)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestWritePath -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/secrets/aws_bundle_backend.py tests/test_secrets/test_aws_bundle_backend.py
git commit -m "Add AWS bundle backend write path (set/delete) with re-fetch and write-through"
```

---

## Task 6: boto3 lazy import / ImportError path

**Files:**
- Test: `tests/test_secrets/test_aws_bundle_backend.py`

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
class TestBotoImport:
    def test_missing_boto3_raises_helpful_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("no boto3")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"pip install konfig\[aws\]"):
            AWSSecretsBundleBackend(ARN)  # no client injected -> tries boto3
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py::TestBotoImport -v`
Expected: PASS — `_create_client` already raises the helpful `ImportError`. (The `# pragma: no cover` on `_create_client` can be removed now that it is exercised.)

- [ ] **Step 3: Remove the coverage pragma**

In `src/konfig/secrets/aws_bundle_backend.py`, change:

```python
    def _create_client(self):  # pragma: no cover - exercised in Task 6
```

to:

```python
    def _create_client(self):
```

- [ ] **Step 4: Run the full backend test file**

Run: `pytest tests/test_secrets/test_aws_bundle_backend.py -v`
Expected: PASS (all tasks 1–6 green)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/secrets/aws_bundle_backend.py tests/test_secrets/test_aws_bundle_backend.py
git commit -m "Cover AWS bundle backend missing-boto3 path"
```

---

## Task 7: Wire env-var selection into Secrets with precedence

**Files:**
- Modify: `src/konfig/secrets/secrets.py:41-43` (the `__init__` backend-selection block)
- Test: `tests/test_secrets/test_secrets.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_secrets/test_secrets.py`:

```python
class TestEnvVarBundleSelection:
    def test_env_var_overrides_explicit_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "KONFIG_AWS_SECRETS_MANAGER",
            "arn:aws:secretsmanager:eu-west-1:123456789012:secret:app/s-AbCdEf",
        )
        from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend

        captured: dict[str, object] = {}

        def fake_init(self, arn, ttl=300, client=None, time_func=None):
            captured["arn"] = arn
            captured["ttl"] = ttl
            self._cache = {}
            self._cache_at = 0.0

        # Avoid constructing a real boto3 client.
        monkeypatch.setattr(AWSSecretsBundleBackend, "__init__", fake_init)

        secrets = Secrets(backend=InMemoryBackend())
        assert isinstance(secrets._backend, AWSSecretsBundleBackend)
        assert captured["arn"].endswith("s-AbCdEf")

    def test_no_env_var_uses_explicit_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KONFIG_AWS_SECRETS_MANAGER", raising=False)
        backend = InMemoryBackend()
        secrets = Secrets(backend=backend)
        assert secrets._backend is backend
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_secrets/test_secrets.py::TestEnvVarBundleSelection -v`
Expected: FAIL — `test_env_var_overrides_explicit_backend` fails because the explicit backend is used instead of the bundle backend.

- [ ] **Step 3: Write the implementation**

In `src/konfig/secrets/secrets.py`, add `import os` near the top (after `import logging`). Then replace the constructor's backend-selection block:

```python
        if backend is not None:
            self._backend = backend
        else:
            self._backend = self._auto_detect_backend()
```

with:

```python
        env_arn = os.environ.get("KONFIG_AWS_SECRETS_MANAGER")
        if env_arn:
            # Hard override: the env var wins over an explicit backend and config.
            self._backend = self._create_bundle_backend(env_arn)
        elif backend is not None:
            self._backend = backend
        else:
            self._backend = self._auto_detect_backend()
```

Then add this helper method to the `Secrets` class (next to `_create_aws_backend`):

```python
    def _create_bundle_backend(self, arn: str) -> SecretBackend:
        from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend

        ttl = 300
        if self._settings:
            ttl = int(self._settings.get("secrets.aws.cache_ttl", 300))
        return AWSSecretsBundleBackend(arn=arn, ttl=ttl)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_secrets/test_secrets.py::TestEnvVarBundleSelection -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/konfig/secrets/secrets.py tests/test_secrets/test_secrets.py
git commit -m "Select AWS bundle backend from KONFIG_AWS_SECRETS_MANAGER env var"
```

---

## Task 8: TTL resolution from settings

**Files:**
- Test: `tests/test_secrets/test_secrets.py`

(Implemented in Task 7's `_create_bundle_backend`; this test locks in the settings knob.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_secrets/test_secrets.py`:

```python
    def test_cache_ttl_read_from_settings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(
            "KONFIG_AWS_SECRETS_MANAGER",
            "arn:aws:secretsmanager:eu-west-1:123456789012:secret:app/s-AbCdEf",
        )
        from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend

        captured: dict[str, object] = {}

        def fake_init(self, arn, ttl=300, client=None, time_func=None):
            captured["ttl"] = ttl
            self._cache = {}
            self._cache_at = 0.0

        monkeypatch.setattr(AWSSecretsBundleBackend, "__init__", fake_init)

        config = tmp_path / "config.yaml"
        config.write_text("secrets:\n  aws:\n    cache_ttl: 60\n", encoding="utf-8")
        settings = Settings(config_file=str(config))

        Secrets(settings=settings)
        assert captured["ttl"] == 60
```

Note: this test lives inside `class TestEnvVarBundleSelection` (it uses the same monkeypatch pattern). Ensure `from pathlib import Path` is imported at the top of the test file (it already is).

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_secrets/test_secrets.py::TestEnvVarBundleSelection::test_cache_ttl_read_from_settings -v`
Expected: PASS — `_create_bundle_backend` already reads `secrets.aws.cache_ttl`.

If it fails because `Settings.get` does not accept a positional default, adjust the call in `_create_bundle_backend` to match the real `Settings.get` signature (verify with `grep -n "def get" src/konfig/settings/settings.py`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_secrets/test_secrets.py
git commit -m "Resolve AWS bundle cache TTL from settings"
```

---

## Task 9: Version bump, changelog, and docs

**Files:**
- Modify: `src/konfig/_version.txt`
- Modify: `CHANGELOG.md`
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Bump the version**

Set the entire contents of `src/konfig/_version.txt` to:

```
0.2.0
```

- [ ] **Step 2: Add the changelog entry**

Insert this block in `CHANGELOG.md` immediately above the `## [0.1.1] - 2026-04-11` heading (no AI-co-authorship references):

```markdown
## [0.2.0] - 2026-06-09

### Added

- AWS Secrets Manager bundle backend: set `KONFIG_AWS_SECRETS_MANAGER=<secret-ARN>` to
  make konfig read and write secrets to a single designated AWS secret holding a JSON
  bundle. The env var is a hard override over an explicit backend and over config.
- TTL read cache (default 300s, configurable via `secrets.aws.cache_ttl`) with
  write-through and re-fetch-before-write to narrow the lost-update window.

```

- [ ] **Step 3: Document in CLAUDE.md**

In `CLAUDE.md` section `## 2. Secrets`, add a subsection after "Backend Selection Logic" describing the env-var bundle mode:

```markdown
### Designated Secret via Environment Variable

Setting `KONFIG_AWS_SECRETS_MANAGER=<secret-ARN>` makes konfig store and retrieve all
secrets in a single designated AWS Secrets Manager secret. The secret's `SecretString`
is a JSON object; each konfig key is a key within it. Read-write, with a TTL read cache
(default 300s, `secrets.aws.cache_ttl`) and re-fetch-before-write. This env var is a
hard override: it wins over an explicit `backend=` argument and over `secrets.backend`
config. Region is derived from the ARN. Requires `pip install konfig[aws]`.

This is distinct from the per-key `AWSSecretsManagerBackend` (selected via
`secrets.backend: aws_secrets_manager`), which stores one AWS secret per konfig key.
```

- [ ] **Step 4: Document in README.md**

Add a short usage note to `README.md` under the secrets section (match the file's existing heading style):

```markdown
### AWS Secrets Manager (designated secret)

Point konfig at a single AWS secret that holds a JSON bundle of your secrets:

```bash
export KONFIG_AWS_SECRETS_MANAGER=arn:aws:secretsmanager:eu-west-1:123456789012:secret:myapp/secrets-AbCdEf
```

```python
from konfig import Secrets

secrets = Secrets()           # env var selects the AWS bundle backend
api_key = secrets.get("api_key")
secrets.set("api_key", "sk-new")  # read-modify-write back to the bundle
```

Requires `pip install konfig[aws]`.
```

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS (all tests, including the new backend and env-var tests).

- [ ] **Step 6: Commit**

```bash
git add src/konfig/_version.txt CHANGELOG.md CLAUDE.md README.md
git commit -m "Bump to 0.2.0; document AWS Secrets Manager bundle backend"
```

---

## Self-Review Notes

- **Spec coverage:** §4.1 selection/precedence → Task 7; §4.2 backend + methods → Tasks 1,2,5; §4.3 ARN/region → Task 1; §4.4 caching/writes → Tasks 3,5; §4.5 error handling → Tasks 4,6; §4.6 config knob → Task 8; §5 packaging/version → Task 9; §6 testing → Tasks 1–8; §7 docs → Task 9.
- **Type consistency:** `AWSSecretsBundleBackend(arn, ttl, client, time_func)` signature is used identically in tests and the `fake_init` monkeypatches; `region` property, `refresh()`, `_fetch`, `_bundle`, `_write` names are consistent across tasks.
- **Verify before relying:** Task 8 notes the `Settings.get` default-argument assumption and how to confirm it.
