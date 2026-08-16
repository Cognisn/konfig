# AWS Settings Layer (`KONFIG_AWS_SETTINGS`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only AWS Secrets Manager settings layer so an application's entire configuration can be delivered as one JSON document, selected via `KONFIG_AWS_SETTINGS` or `Settings(aws_settings=...)`.

**Architecture:** A new `AwsSettingsLayer` class (in its own module, mirroring how `aws_bundle_backend.py` isolates the boto3-optional surface) slots into `Settings._read_order` between the env layer and the user file layer. It fetches the secret's `SecretString` once at construction, fails fast on any error, and re-fetches only on `Settings.reload()`. The ARN region parser moves to a small shared module so both the secrets bundle backend and the settings layer use it.

**Tech Stack:** Python >= 3.10, boto3 via the existing `konfig[aws]` extra, pytest with stubbed clients, opt-in LocalStack integration tests (`pytest -m localstack`).

**Spec:** GitHub issue Cognisn/konfig#3 (view with `gh issue view 3 --repo Cognisn/konfig`). Key spec points restated inline in each task.

## Global Constraints

- Work on branch `feat/aws-settings-layer`, created from `main`. Do not commit to `main`.
- Python floor is 3.10 (`requires-python = ">=3.10"`); no 3.11+-only syntax.
- `mypy --strict` must stay clean on `src/` (run: `python -m mypy src`).
- Format with `black` and `isort` (profile=black) before each commit (run: `python -m black src tests && python -m isort src tests`).
- Australian English in all comments, docstrings, and docs (behaviour, initialise, etc.).
- Commit messages must NOT contain any Co-Authored-By / AI attribution lines.
- boto3 must remain optional: importing `konfig` (and constructing `Settings` without the AWS feature) must work with boto3 absent.
- Nothing may ever write to stdout.
- Run the full suite with `python -m pytest` (LocalStack tests auto-skip when the container is down).

## Precedence After This Change

Highest to lowest: `runtime -> env -> AWS settings -> user file -> system file -> defaults`.

## File Structure

- Create: `src/konfig/_aws.py` — shared `parse_region(arn)` helper (moved from `aws_bundle_backend.py`).
- Create: `src/konfig/settings/aws_layer.py` — `AwsSettingsLayer` (read-only layer, boto3-optional).
- Modify: `src/konfig/secrets/aws_bundle_backend.py` — import `parse_region` from `konfig._aws`.
- Modify: `src/konfig/settings/settings.py` — `aws_settings` parameter, env var resolution, read order, `get_section` merge, `reload()`.
- Modify: `src/konfig/settings/layers.py` — module docstring layer listing only.
- Modify: `tests/test_settings/conftest.py` — isolate `KONFIG_AWS_SETTINGS` from the environment.
- Create: `tests/test_settings/test_aws_layer.py` — layer unit tests + Settings wiring tests (stubbed client).
- Modify: `tests/integration/test_aws_localstack.py` — settings-layer LocalStack tests.
- Modify: `README.md`, `CLAUDE.md` — documentation.

---

### Task 1: Shared ARN region parser (`konfig/_aws.py`)

The settings layer needs the same ARN-region parsing the bundle backend has. Move it to a shared module rather than importing a private helper across packages.

**Files:**
- Create: `src/konfig/_aws.py`
- Modify: `src/konfig/secrets/aws_bundle_backend.py:20-33` (delete `_parse_region`, import instead)
- Test: existing `tests/test_secrets/test_aws_bundle_backend.py` (behaviour unchanged; no new tests)

**Interfaces:**
- Produces: `konfig._aws.parse_region(arn: str) -> str` — raises `ValueError` on a malformed ARN. Task 2 imports this.

- [ ] **Step 1: Create the shared module**

Create `src/konfig/_aws.py`:

```python
"""Shared AWS helpers used by both the secrets backends and the settings layer."""

from __future__ import annotations


def parse_region(arn: str) -> str:
    """Extract the region from a Secrets Manager ARN.

    ARN shape: ``arn:aws:secretsmanager:<region>:<account>:secret:<name>``.

    Raises:
        ValueError: If the string is not a valid Secrets Manager ARN.
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
```

- [ ] **Step 2: Use it from the bundle backend**

In `src/konfig/secrets/aws_bundle_backend.py`:
- Delete the whole `_parse_region` function (lines 20–33).
- Add `from konfig._aws import parse_region` to the imports.
- In `AWSSecretsBundleBackend.__init__`, change `self._region = _parse_region(arn)` to `self._region = parse_region(arn)`.

- [ ] **Step 3: Run the existing backend tests**

Run: `python -m pytest tests/test_secrets/test_aws_bundle_backend.py -v`
Expected: all PASS (this is a pure refactor).

- [ ] **Step 4: Lint gate**

Run: `python -m black src tests && python -m isort src tests && python -m mypy src`
Expected: no changes needed beyond formatting, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/konfig/_aws.py src/konfig/secrets/aws_bundle_backend.py
git commit -m "refactor: move Secrets Manager ARN region parsing to shared konfig._aws"
```

---

### Task 2: `AwsSettingsLayer` class

Read-only layer fetching a JSON settings tree from one Secrets Manager secret. Fail fast at construction: unreadable/missing secret, binary-only secret, non-JSON payload, or non-object top level all raise immediately (the spec calls this out explicitly — this layer is an explicit opt-in carrying load-bearing configuration, unlike the graceful system file layer). Error messages name the secret source but never echo the payload.

**Files:**
- Create: `src/konfig/settings/aws_layer.py`
- Test: `tests/test_settings/test_aws_layer.py` (new file; Settings wiring tests are added to this same file in Task 3)

**Interfaces:**
- Consumes: `konfig._aws.parse_region` (Task 1); `_get_nested`, `_get_section`, `_MISSING` from `konfig.settings.layers`.
- Produces: `AwsSettingsLayer(source: str | None = None, client: object | None = None)` with `get(key: str) -> Any`, `get_section(prefix: str) -> dict[str, Any]`, `reload() -> None`, `data: dict[str, Any]` property, `source: str | None` property. `source=None` gives an inert empty layer (mirrors `FileLayer(path=None)`) that never touches boto3. Task 3 constructs it and calls `reload()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings/test_aws_layer.py`:

```python
"""Tests for the AWS Secrets Manager settings layer."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from konfig.settings.aws_layer import AwsSettingsLayer
from konfig.settings.layers import _MISSING

ARN = "arn:aws:secretsmanager:eu-west-1:123456789012:secret:myapp/settings-AbCdEf"

TREE = {"database": {"host": "aws-db", "port": 5432}, "feature_flags": ["a", "b"]}


class _ClientError(Exception):
    pass


class _ResourceNotFound(_ClientError):
    pass


class FakeSMClient:
    """Minimal stand-in for a boto3 secretsmanager client (read-only)."""

    def __init__(
        self,
        secret_string: str | None = None,
        missing: bool = False,
        error: bool = False,
    ) -> None:
        self._secret_string = secret_string
        self._missing = missing
        self._error = error
        self.get_calls = 0
        self.exceptions = SimpleNamespace(
            ClientError=_ClientError, ResourceNotFoundException=_ResourceNotFound
        )

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        self.get_calls += 1
        if self._missing:
            raise self.exceptions.ResourceNotFoundException("secret not found")
        if self._error:
            raise self.exceptions.ClientError("access denied")
        if self._secret_string is None:
            return {}  # binary-only secret: no SecretString key
        return {"SecretString": self._secret_string}


class TestInertWhenUnconfigured:
    def test_no_source_is_empty(self) -> None:
        layer = AwsSettingsLayer()
        assert layer.get("anything") is _MISSING
        assert layer.get_section("anything") == {}
        assert layer.data == {}

    def test_no_source_never_creates_a_client(self) -> None:
        # Would raise ImportError/ClientError if it tried; plain construction must not.
        layer = AwsSettingsLayer(source=None)
        assert layer.source is None
        layer.reload()  # no-op, no client involved


class TestFetchAndRead:
    def test_fetches_at_construction(self) -> None:
        client = FakeSMClient(json.dumps(TREE))
        AwsSettingsLayer(ARN, client=client)
        assert client.get_calls == 1

    def test_get_nested_key(self) -> None:
        layer = AwsSettingsLayer(ARN, client=FakeSMClient(json.dumps(TREE)))
        assert layer.get("database.host") == "aws-db"
        assert layer.get("database.port") == 5432

    def test_list_values_survive(self) -> None:
        layer = AwsSettingsLayer(ARN, client=FakeSMClient(json.dumps(TREE)))
        assert layer.get("feature_flags") == ["a", "b"]

    def test_missing_key_is_missing(self) -> None:
        layer = AwsSettingsLayer(ARN, client=FakeSMClient(json.dumps(TREE)))
        assert layer.get("nope.nothing") is _MISSING

    def test_get_section(self) -> None:
        layer = AwsSettingsLayer(ARN, client=FakeSMClient(json.dumps(TREE)))
        assert layer.get_section("database") == {"host": "aws-db", "port": 5432}

    def test_secret_name_accepted_as_source(self) -> None:
        # A plain name (not an ARN) is a valid source; region comes from the
        # default provider chain in that case.
        layer = AwsSettingsLayer("myapp/settings", client=FakeSMClient(json.dumps(TREE)))
        assert layer.get("database.host") == "aws-db"

    def test_reads_are_cached_not_refetched(self) -> None:
        client = FakeSMClient(json.dumps(TREE))
        layer = AwsSettingsLayer(ARN, client=client)
        layer.get("database.host")
        layer.get("database.port")
        assert client.get_calls == 1

    def test_reload_refetches(self) -> None:
        client = FakeSMClient(json.dumps(TREE))
        layer = AwsSettingsLayer(ARN, client=client)
        client._secret_string = json.dumps({"database": {"host": "rotated"}})
        layer.reload()
        assert layer.get("database.host") == "rotated"
        assert client.get_calls == 2


class TestFailFast:
    def test_missing_secret_raises(self) -> None:
        with pytest.raises(RuntimeError, match="myapp/settings-AbCdEf"):
            AwsSettingsLayer(ARN, client=FakeSMClient(missing=True))

    def test_unreadable_secret_raises(self) -> None:
        with pytest.raises(RuntimeError, match="myapp/settings-AbCdEf"):
            AwsSettingsLayer(ARN, client=FakeSMClient(error=True))

    def test_non_json_payload_raises(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            AwsSettingsLayer(ARN, client=FakeSMClient("not-json{"))

    def test_error_never_echoes_payload(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            AwsSettingsLayer(ARN, client=FakeSMClient("sup3r-s3cret-payload{"))
        assert "sup3r-s3cret-payload" not in str(excinfo.value)

    def test_json_array_top_level_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            AwsSettingsLayer(ARN, client=FakeSMClient(json.dumps([1, 2])))

    def test_binary_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="SecretString"):
            AwsSettingsLayer(ARN, client=FakeSMClient(secret_string=None))


class TestBotoImport:
    def test_missing_boto3_raises_helpful_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "boto3":
                raise ImportError("no boto3")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"pip install konfig\[aws\]"):
            AwsSettingsLayer(ARN)  # no client injected -> tries boto3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings/test_aws_layer.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'konfig.settings.aws_layer'`.

- [ ] **Step 3: Implement the layer**

Create `src/konfig/settings/aws_layer.py`:

```python
"""AWS Secrets Manager settings layer (optional, requires konfig[aws]).

Loads an application's settings tree from a single Secrets Manager secret
whose ``SecretString`` is a JSON object. Selected via the
``KONFIG_AWS_SETTINGS`` environment variable or ``Settings(aws_settings=...)``.

Unlike the graceful system config file, this layer is an explicit opt-in
carrying load-bearing configuration, so every failure mode (missing secret,
unreadable secret, non-JSON payload, non-object top level) raises immediately
at construction rather than silently degrading to defaults. Error messages
name the secret but never echo its payload.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from konfig._aws import parse_region
from konfig.settings.layers import _get_nested, _get_section

logger = logging.getLogger(__name__)


class AwsSettingsLayer:
    """Read-only settings layer backed by one AWS Secrets Manager secret.

    Args:
        source: Secret ARN or name. If None, the layer is inert and empty
            (mirrors ``FileLayer`` with no path) and boto3 is never imported.
        client: Optional pre-built boto3 client (for testing/injection).
    """

    def __init__(
        self,
        source: Optional[str] = None,
        client: object | None = None,
    ) -> None:
        self._source = source
        self._data: dict[str, Any] = {}
        self._client: Any = None
        if self._source:
            self._client = client if client is not None else self._create_client()
            self.reload()

    def _create_client(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager settings layer "
                "(KONFIG_AWS_SETTINGS). Install it with: pip install konfig[aws]"
            ) from exc
        assert self._source is not None
        # Region from the ARN when one is given; otherwise the default
        # provider chain decides (matches the secrets bundle behaviour).
        region = parse_region(self._source) if self._source.startswith("arn:") else None
        return boto3.client("secretsmanager", region_name=region)

    def reload(self) -> None:
        """Re-fetch the settings document from AWS.

        Raises:
            RuntimeError: If the secret is missing or unreadable.
            ValueError: If the payload is binary-only, not valid JSON, or
                not a JSON object at the top level.
        """
        if not self._source:
            return
        logger.debug("Fetching AWS settings secret %s", self._source)
        try:
            response = self._client.get_secret_value(SecretId=self._source)
        except self._client.exceptions.ClientError as exc:
            # Covers ResourceNotFoundException, AccessDenied, etc. The
            # message names the secret; there is no payload to leak here.
            raise RuntimeError(
                f"Cannot read AWS settings secret {self._source!r}: {exc}"
            ) from exc
        raw = response.get("SecretString")
        if raw is None:
            raise ValueError(
                f"AWS settings secret {self._source!r} has no SecretString "
                "(binary secrets are not supported)"
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Deliberately excludes the payload from the message.
            raise ValueError(
                f"AWS settings secret {self._source!r} is not valid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"AWS settings secret {self._source!r} must be a JSON object "
                "at the top level"
            )
        self._data = data

    def get(self, key: str) -> Any:
        return _get_nested(self._data, key)

    def get_section(self, prefix: str) -> dict[str, Any]:
        return _get_section(self._data, prefix)

    @property
    def source(self) -> Optional[str]:
        """The secret ARN or name, or None when the layer is inert."""
        return self._source

    @property
    def data(self) -> dict[str, Any]:
        return self._data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings/test_aws_layer.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint gate**

Run: `python -m black src tests && python -m isort src tests && python -m mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/konfig/settings/aws_layer.py tests/test_settings/test_aws_layer.py
git commit -m "feat: add read-only AWS Secrets Manager settings layer"
```

---

### Task 3: Wire the layer into `Settings`

New `aws_settings` constructor parameter; `KONFIG_AWS_SETTINGS` env var wins over it (consistent with how `KONFIG_AWS_SECRETS_MANAGER` is a hard override on the secrets side). Layer sits between env and user file. Writes never touch it. `reload()` re-fetches it. Also prove `secret://` values inside the document pass through to `Secrets.resolve_uri` unchanged — that is the existing resolution mechanism, so composition needs a test, not new code.

**Files:**
- Modify: `src/konfig/settings/settings.py`
- Modify: `src/konfig/settings/layers.py:1-9` (module docstring listing only)
- Modify: `tests/test_settings/conftest.py`
- Test: `tests/test_settings/test_aws_layer.py` (append)

**Interfaces:**
- Consumes: `AwsSettingsLayer(source, client=None)` / `.reload()` / `.get()` / `.get_section()` from Task 2.
- Produces: `Settings(config_file=None, system_config_file=None, defaults=None, env_prefix=None, aws_settings: Optional[str] = None)`. Read precedence `runtime -> env -> aws -> user file -> system file -> defaults`. Tasks 4–5 rely on exactly this constructor signature and env var name `KONFIG_AWS_SETTINGS`.

- [ ] **Step 1: Isolate the env var in the settings test suite**

In `tests/test_settings/conftest.py`, extend the existing autouse fixture so a real `KONFIG_AWS_SETTINGS` in the developer's shell can never leak into (and break) every settings test:

```python
@pytest.fixture(autouse=True)
def _clear_konfig_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure konfig env vars never leak into settings tests by default.

    Tests that exercise the env-var paths set them explicitly via monkeypatch.
    """
    monkeypatch.delenv("KONFIG_CONFIG_FORMAT", raising=False)
    monkeypatch.delenv("KONFIG_AWS_SETTINGS", raising=False)
```

(Replace the existing `_clear_konfig_config_format` fixture with this renamed one.)

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_settings/test_aws_layer.py`:

```python
class TestSettingsWiring:
    """The layer wired into Settings via env var / constructor parameter."""

    @pytest.fixture
    def fake_client(self, monkeypatch: pytest.MonkeyPatch) -> FakeSMClient:
        """Install a stub client so Settings can build the layer without boto3."""
        client = FakeSMClient(json.dumps(TREE))
        monkeypatch.setattr(
            AwsSettingsLayer, "_create_client", lambda self: client
        )
        return client

    def test_env_var_loads_document(
        self, fake_client: FakeSMClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from konfig.settings.settings import Settings

        monkeypatch.setenv("KONFIG_AWS_SETTINGS", ARN)
        settings = Settings()
        assert settings.get("database.host") == "aws-db"
        assert settings.has("database.port") is True
        assert settings.get_section("database") == {"host": "aws-db", "port": 5432}

    def test_constructor_parameter_loads_document(
        self, fake_client: FakeSMClient
    ) -> None:
        from konfig.settings.settings import Settings

        settings = Settings(aws_settings=ARN)
        assert settings.get("database.host") == "aws-db"

    def test_env_var_wins_over_parameter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from konfig.settings.settings import Settings

        env_client = FakeSMClient(json.dumps({"origin": "env"}))
        monkeypatch.setattr(
            AwsSettingsLayer, "_create_client", lambda self: env_client
        )
        monkeypatch.setenv("KONFIG_AWS_SETTINGS", ARN)
        settings = Settings(aws_settings="some-other-secret")
        assert settings._aws_layer.source == ARN
        assert settings.get("origin") == "env"

    def test_unused_feature_needs_no_boto3(self) -> None:
        # No env var, no parameter: constructing Settings must not touch boto3.
        from konfig.settings.settings import Settings

        settings = Settings(defaults={"a": 1})
        assert settings.get("a") == 1

    def test_aws_overrides_user_file(
        self, fake_client: FakeSMClient, tmp_path: Any
    ) -> None:
        from konfig.settings.settings import Settings

        config = tmp_path / "config.yaml"
        config.write_text(
            "database:\n  host: file-db\n  name: from-file\n", encoding="utf-8"
        )
        settings = Settings(config_file=config, aws_settings=ARN)
        assert settings.get("database.host") == "aws-db"  # aws beats user file
        assert settings.get("database.name") == "from-file"  # file still visible

    def test_env_var_layer_overrides_aws(
        self, fake_client: FakeSMClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from konfig.settings.settings import Settings

        monkeypatch.setenv("DATABASE__HOST", "env-db")
        settings = Settings(aws_settings=ARN)
        assert settings.get("database.host") == "env-db"

    def test_runtime_set_does_not_touch_aws_layer(
        self, fake_client: FakeSMClient
    ) -> None:
        from konfig.settings.settings import Settings

        settings = Settings(aws_settings=ARN)
        settings.set("database.host", "runtime-db")
        assert settings.get("database.host") == "runtime-db"
        assert settings._aws_layer.get("database.host") == "aws-db"  # unchanged

    def test_persist_user_still_writes_user_file(
        self, fake_client: FakeSMClient, tmp_path: Any
    ) -> None:
        from konfig.settings.settings import Settings

        config = tmp_path / "config.yaml"
        config.write_text("database:\n  host: file-db\n", encoding="utf-8")
        settings = Settings(config_file=config, aws_settings=ARN)
        settings.set("database.name", "written", persist="user")
        assert "written" in config.read_text(encoding="utf-8")
        assert settings._aws_layer.data == TREE  # aws layer untouched

    def test_reload_refetches_document(self, fake_client: FakeSMClient) -> None:
        from konfig.settings.settings import Settings

        settings = Settings(aws_settings=ARN)
        fake_client._secret_string = json.dumps({"database": {"host": "rotated"}})
        settings.reload()
        assert settings.get("database.host") == "rotated"

    def test_get_section_merges_aws_between_file_and_env(
        self,
        fake_client: FakeSMClient,
        tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from konfig.settings.settings import Settings

        config = tmp_path / "config.yaml"
        config.write_text(
            "database:\n  host: file-db\n  name: from-file\n", encoding="utf-8"
        )
        monkeypatch.setenv("DATABASE__PORT", "9999")
        settings = Settings(config_file=config, aws_settings=ARN)
        assert settings.get_section("database") == {
            "host": "aws-db",  # aws beats file
            "name": "from-file",  # only in file
            "port": "9999",  # env beats aws
        }


class TestSecretUriComposition:
    def test_secret_uri_in_document_resolves_via_secrets_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """secret:// values inside the AWS settings document resolve through
        the active secrets backend, exactly like values from any other layer."""
        from konfig.secrets.backend import SecretBackend
        from konfig.secrets.secrets import Secrets
        from konfig.settings.settings import Settings

        doc = {"database": {"password": "secret://db_password"}}
        client = FakeSMClient(json.dumps(doc))
        monkeypatch.setattr(AwsSettingsLayer, "_create_client", lambda self: client)

        class FakeBackend(SecretBackend):
            def get(self, key: str) -> str | None:
                return "pw-123" if key == "db_password" else None

            def set(self, key: str, value: str) -> None:  # pragma: no cover
                raise NotImplementedError

            def delete(self, key: str) -> None:  # pragma: no cover
                raise NotImplementedError

            def has(self, key: str) -> bool:
                return key == "db_password"

            def list_keys(self) -> list[str]:
                return ["db_password"]

        settings = Settings(aws_settings=ARN)
        secrets = Secrets(backend=FakeBackend())
        raw = settings.get("database.password")
        assert raw == "secret://db_password"
        assert secrets.resolve_uri(raw) == "pw-123"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings/test_aws_layer.py -v`
Expected: `TestSettingsWiring` and `TestSecretUriComposition` FAIL (`Settings.__init__() got an unexpected keyword argument 'aws_settings'`); earlier classes still PASS.

- [ ] **Step 4: Implement the wiring**

In `src/konfig/settings/settings.py`:

1. Add the import:

```python
from konfig.settings.aws_layer import AwsSettingsLayer
```

2. Extend the constructor signature and docstring:

```python
    def __init__(
        self,
        config_file: Optional[str | Path] = None,
        system_config_file: Optional[str | Path] = None,
        defaults: Optional[dict[str, Any]] = None,
        env_prefix: Optional[str] = None,
        aws_settings: Optional[str] = None,
    ) -> None:
```

Docstring additions — the class-level layer list becomes (lowest to highest):

```
      1. defaults — hardcoded in the application
      2. system config file — system-wide, shared across all users
      3. user config file — per-user config
      4. AWS settings document — one Secrets Manager secret holding the
         whole settings tree as JSON (KONFIG_AWS_SETTINGS)
      5. environment variables — mapped from nested keys
      6. runtime overrides — set programmatically
```

and the args section gains:

```
        aws_settings: ARN or name of an AWS Secrets Manager secret whose
            SecretString is a JSON object holding the settings tree. The
            KONFIG_AWS_SETTINGS environment variable overrides this
            argument. Read-only; requires konfig[aws]. Errors reading or
            parsing the secret raise immediately at construction.
```

3. At the end of `__init__`, after `self._runtime_layer = RuntimeLayer()`:

```python
        # The env var is a hard override, mirroring KONFIG_AWS_SECRETS_MANAGER
        # on the secrets side.
        aws_source = os.environ.get("KONFIG_AWS_SETTINGS") or aws_settings
        self._aws_layer = AwsSettingsLayer(aws_source)
```

4. Update `_read_order` (and its docstring mention in `get()` to `runtime -> env -> AWS settings -> user file -> system file -> defaults`):

```python
    @property
    def _read_order(self) -> tuple[Any, ...]:
        """Layers in highest-to-lowest precedence for reads."""
        return (
            self._runtime_layer,
            self._env_layer,
            self._aws_layer,
            self._user_file_layer,
            self._system_file_layer,
            self._defaults_layer,
        )
```

5. In `get_section()`, insert between the user-file and env merges:

```python
        result = _deep_merge(result, self._user_file_layer.get_section(prefix))
        result = _deep_merge(result, self._aws_layer.get_section(prefix))
        result = _deep_merge(result, self._env_layer.get_section(prefix))
```

6. Extend `reload()`:

```python
    def reload(self) -> None:
        """Reload both config files from disk and re-fetch the AWS settings
        document (when configured)."""
        self._system_file_layer.reload()
        self._user_file_layer.reload()
        self._aws_layer.reload()
```

7. `set()`/`delete()` need no change — there is deliberately no persist scope for the AWS layer.

8. In `src/konfig/settings/layers.py`, update the module docstring list to:

```python
"""Layer implementations for the Settings system.

Layers (lowest to highest precedence):
  1. DefaultsLayer — hardcoded application defaults
  2. FileLayer (system) — system-wide config file
  3. FileLayer (user) — per-user config file
  4. AwsSettingsLayer — AWS Secrets Manager settings document (see aws_layer.py)
  5. EnvLayer — values from environment variables
  6. RuntimeLayer — values set programmatically at runtime
"""
```

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest`
Expected: all PASS (LocalStack tests skip), including all pre-existing settings tests — this proves the feature is inert when unconfigured.

- [ ] **Step 6: Lint gate**

Run: `python -m black src tests && python -m isort src tests && python -m mypy src`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/konfig/settings/settings.py src/konfig/settings/layers.py tests/test_settings/test_aws_layer.py tests/test_settings/conftest.py
git commit -m "feat: wire KONFIG_AWS_SETTINGS / Settings(aws_settings=...) into layered precedence"
```

---

### Task 4: LocalStack integration test

Exercise the real boto3 code path against LocalStack, following the existing opt-in pattern in `tests/integration/test_aws_localstack.py` (marker `localstack`, TCP reachability skip gate, `AWS_ENDPOINT_URL` pointing konfig's own client at LocalStack).

**Files:**
- Modify: `tests/integration/test_aws_localstack.py` (append)

**Interfaces:**
- Consumes: `Settings(aws_settings=...)` and `KONFIG_AWS_SETTINGS` from Task 3; existing module fixtures `_aws_env`, `_client()`.

- [ ] **Step 1: Write the integration tests**

Append to `tests/integration/test_aws_localstack.py`:

```python
@pytest.fixture
def settings_arn() -> Iterator[str]:
    """Create a settings-document secret and yield its ARN; delete on teardown."""
    client = _client()
    name = f"konfig-itest-settings/{uuid.uuid4().hex}"
    document = {"database": {"host": "aws-db", "port": 5432}, "flags": ["x", "y"]}
    response = client.create_secret(Name=name, SecretString=json.dumps(document))
    arn = response["ARN"]
    try:
        yield arn
    finally:
        try:
            client.delete_secret(SecretId=arn, ForceDeleteWithoutRecovery=True)
        except Exception:  # best-effort cleanup; never mask the test result
            pass


def test_settings_layer_via_env_var(
    settings_arn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from konfig import Settings

    monkeypatch.setenv("KONFIG_AWS_SETTINGS", settings_arn)
    settings = Settings(defaults={"database": {"host": "default-db"}})

    # The AWS document overrides defaults; list values arrive intact.
    assert settings.get("database.host") == "aws-db"
    assert settings.get("database.port") == 5432
    assert settings.get("flags") == ["x", "y"]
    assert settings.get_section("database") == {"host": "aws-db", "port": 5432}

    # reload() picks up a rotated document without a restart.
    _client().put_secret_value(
        SecretId=settings_arn,
        SecretString=json.dumps({"database": {"host": "rotated-db"}}),
    )
    settings.reload()
    assert settings.get("database.host") == "rotated-db"


def test_settings_layer_missing_secret_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from konfig import Settings

    monkeypatch.setenv(
        "KONFIG_AWS_SETTINGS", f"konfig-itest-missing/{uuid.uuid4().hex}"
    )
    with pytest.raises(RuntimeError, match="konfig-itest-missing"):
        Settings()
```

Note: `from konfig import Settings` requires `Settings` to already be exported from `konfig/__init__.py` — it is (the existing quick-start docs use it). If the import fails, use `from konfig.settings.settings import Settings` instead and flag it in the task report.

- [ ] **Step 2: Run the integration tests (if LocalStack is available)**

Run: `docker compose up -d && python -m pytest -m localstack -v`
Expected: all PASS, including the two new tests. If Docker/LocalStack is unavailable in the execution environment, run `python -m pytest tests/integration/ -v` and confirm the tests SKIP cleanly with the LocalStack-unreachable reason — then note in the task report that the live run is outstanding.

- [ ] **Step 3: Lint gate**

Run: `python -m black tests && python -m isort tests && python -m mypy src`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_aws_localstack.py
git commit -m "test: LocalStack coverage for the AWS settings layer"
```

---

### Task 5: Documentation (README + CLAUDE.md)

**Files:**
- Modify: `README.md` — new subsection after the existing "### AWS Secrets Manager (designated secret)" section
- Modify: `CLAUDE.md` — layered precedence list and a short feature note

**Interfaces:**
- Consumes: behaviour and names finalised in Tasks 2–3 (`KONFIG_AWS_SETTINGS`, `Settings(aws_settings=...)`, precedence order).

- [ ] **Step 1: Add the README section**

Read the existing "### AWS Secrets Manager (designated secret)" section first and match its tone and formatting. Insert after it:

```markdown
### AWS Secrets Manager settings document (`KONFIG_AWS_SETTINGS`)

Deliver an application's entire configuration as one JSON document held in a
single Secrets Manager secret — no config file or per-setting environment
variables needed in the task definition:

```bash
export KONFIG_AWS_SETTINGS=arn:aws:secretsmanager:eu-west-1:123456789012:secret:myapp/settings-AbCdEf
```

The secret's `SecretString` must be a JSON object holding the same nested
settings tree a config file would. A plain secret name is also accepted; the
region then comes from the default AWS provider chain (with an ARN it is
taken from the ARN). An equivalent constructor argument exists for
programmatic use — `Settings(aws_settings=...)` — with the environment
variable winning when both are set. Requires `pip install konfig[aws]`.

Precedence (highest to lowest):
`runtime -> env vars -> AWS settings -> user file -> system file -> defaults`
— environment variables remain the operator's immediate per-container
override, while the AWS document overrides anything baked into the image.

Behaviour:

- **Read-only.** `settings.set(...)` keeps writing to the runtime layer or
  config files exactly as before.
- **Fail fast.** A missing/unreadable secret, non-JSON payload, or
  non-object top level raises at startup rather than silently degrading to
  defaults. Error messages name the secret, never its payload.
- **Fetched once.** The document is read at construction and only re-fetched
  by `settings.reload()`; there is no background polling.
- **Composes with secrets.** Values in the document may be `secret://` URIs,
  resolved as usual by the active secrets backend.

This is independent of `KONFIG_AWS_SECRETS_MANAGER`. Pointing both at the
same secret works, but keeping configuration and secret material in separate
Secrets Manager entries is recommended so IAM can distinguish "may read
config" from "may read credentials".
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`:

1. In the "## 1. Settings" → "### Layered Precedence" list, insert a new entry between the config file and environment variables entries:

```markdown
3. **AWS settings document** — optional: one Secrets Manager secret holding the whole settings tree as JSON, selected via `KONFIG_AWS_SETTINGS` or `Settings(aws_settings=...)` (env var wins). Read-only, fail-fast, re-fetched only on `reload()`. Requires `konfig[aws]`.
```

and renumber the following entries (env vars become 4, runtime overrides become 5).

2. In the "## 2. Secrets" section, after the "Designated Secret via Environment Variable" subsection, add one clarifying line:

```markdown
`KONFIG_AWS_SETTINGS` (settings document, read-only, part of the Settings layer stack) is independent of `KONFIG_AWS_SECRETS_MANAGER` (secrets bundle, read-write). They may point at the same secret, but separate entries are recommended so IAM can distinguish config-read from credential-read.
```

- [ ] **Step 3: Verify docs render and nothing is stale**

Run: `grep -n "KONFIG_AWS_SETTINGS" README.md CLAUDE.md`
Expected: hits in both files. Also re-read both edited sections in full to check the surrounding numbering and formatting still make sense.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document the KONFIG_AWS_SETTINGS settings layer"
```

---

## Acceptance Criteria Traceability (from issue #3)

| Criterion | Task |
|---|---|
| `KONFIG_AWS_SETTINGS=<arn>` loads a JSON tree via `get`/`has`/`get_section` with the stated precedence | 3 |
| `Settings(aws_settings=...)` parameter, env var overriding it | 3 |
| Layer is read-only; `set`/`delete` unchanged for other layers | 3 |
| `reload()` re-fetches the document | 2, 3 |
| Fail-fast for missing secret, non-JSON payload, non-object top level | 2 |
| Works without boto3 when unused; clear `konfig[aws]` error when selected without it | 2, 3 |
| `secret://` values inside the document resolve through the active secrets backend | 3 |
| Stubbed-client unit tests + opt-in LocalStack integration test | 2–4 |
| README section (env var, precedence, IAM note, separate-entries recommendation) | 5 |

## Out of Scope (per the issue)

- No polling/auto-refresh of the secret (explicit `reload()` only).
- No SSM Parameter Store or other remote stores.
- No YAML/TOML payloads — JSON only; `KONFIG_CONFIG_FORMAT` does not apply.
- No version bump on this branch — versioning happens on the release branch per the project workflow (this lands as a MINOR feature, next release 0.3.0).
