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
