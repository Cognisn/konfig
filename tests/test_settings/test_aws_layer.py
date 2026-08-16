"""Tests for the AWS Secrets Manager settings layer."""

from __future__ import annotations

import json
import sys
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
        layer = AwsSettingsLayer(
            "myapp/settings", client=FakeSMClient(json.dumps(TREE))
        )
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

    def test_generic_exception_wrapped_in_runtime_error(self) -> None:
        # Plain Exception (not ClientError) from the client is wrapped in RuntimeError
        client = FakeSMClient(json.dumps(TREE))

        def raise_generic(*args: Any, **kwargs: Any) -> Any:
            raise Exception("generic botocore error")

        client.get_secret_value = raise_generic
        with pytest.raises(RuntimeError, match="myapp/settings-AbCdEf"):
            AwsSettingsLayer(ARN, client=client)


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


class TestRegionSelection:
    def test_region_extracted_from_arn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ARN source -> region extracted and passed to boto3.client()
        call_args: dict[str, Any] = {}

        def recording_client_func(service: str, region_name: str | None = None) -> Any:
            call_args["service"] = service
            call_args["region_name"] = region_name
            return FakeSMClient(json.dumps(TREE))

        fake_boto3 = SimpleNamespace(client=recording_client_func)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        AwsSettingsLayer(ARN)
        assert call_args["service"] == "secretsmanager"
        assert call_args["region_name"] == "eu-west-1"

    def test_region_none_for_plain_secret_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Plain secret name (not ARN) -> region_name=None (uses default provider chain)
        call_args: dict[str, Any] = {}

        def recording_client_func(service: str, region_name: str | None = None) -> Any:
            call_args["service"] = service
            call_args["region_name"] = region_name
            return FakeSMClient(json.dumps(TREE))

        fake_boto3 = SimpleNamespace(client=recording_client_func)
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        AwsSettingsLayer("myapp/settings")
        assert call_args["service"] == "secretsmanager"
        assert call_args["region_name"] is None


class TestSettingsWiring:
    """The layer wired into Settings via env var / constructor parameter."""

    @pytest.fixture
    def fake_client(self, monkeypatch: pytest.MonkeyPatch) -> FakeSMClient:
        """Install a stub client so Settings can build the layer without boto3."""
        client = FakeSMClient(json.dumps(TREE))
        monkeypatch.setattr(AwsSettingsLayer, "_create_client", lambda self: client)
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

    def test_env_var_wins_over_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from konfig.settings.settings import Settings

        env_client = FakeSMClient(json.dumps({"origin": "env"}))
        monkeypatch.setattr(AwsSettingsLayer, "_create_client", lambda self: env_client)
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
