"""Tests for the AWS Secrets Manager bundle backend."""

from __future__ import annotations

import itertools
import json
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from konfig.secrets import aws_bundle_backend
from konfig.secrets.aws_bundle_backend import AWSSecretsBundleBackend, StaleBundleError

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

    def put_secret_value(
        self, SecretId: str, SecretString: str, ClientRequestToken: str | None = None
    ) -> None:
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
        assert backend.get("b") == "2"  # served from write-through cache
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


class TestBotoImport:
    def test_missing_boto3_raises_helpful_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("no boto3")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"pip install konfig\[aws\]"):
            AWSSecretsBundleBackend(ARN)  # no client injected -> tries boto3


class TestSeedIfEmpty:
    NAMES = ["api_key", "db_password"]

    @pytest.mark.parametrize("payload", ["", "  \n", "{}", " {} "])
    def test_empty_payload_seeds_placeholders(self, payload: str) -> None:
        client = FakeSMClient(payload)
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.seed_if_empty(self.NAMES, "CHANGEME") is True
        assert json.loads(client.put_calls[-1]) == {
            "api_key": "CHANGEME",
            "db_password": "CHANGEME",
        }

    def test_non_empty_payload_untouched(self) -> None:
        client = FakeSMClient(json.dumps({"existing": "value"}))
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.seed_if_empty(self.NAMES, "CHANGEME") is False
        assert client.put_calls == []

    def test_malformed_payload_untouched(self) -> None:
        client = FakeSMClient("not-json{")
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.seed_if_empty(self.NAMES, "CHANGEME") is False
        assert client.put_calls == []

    def test_binary_secret_untouched(self) -> None:
        client = FakeSMClient(secret_string=None)
        # FakeSMClient returns {"SecretString": None}; treat as binary/absent.
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.seed_if_empty(self.NAMES, "CHANGEME") is False
        assert client.put_calls == []

    def test_missing_secret_warns_and_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = FakeSMClient(missing=True)
        backend = AWSSecretsBundleBackend(ARN, client=client)
        with caplog.at_level("WARNING", logger="konfig.secrets.aws_bundle_backend"):
            assert backend.seed_if_empty(self.NAMES, "CHANGEME") is False
        assert client.put_calls == []
        assert any("Could not seed" in r.message for r in caplog.records)

    def test_no_names_is_noop_without_fetch(self) -> None:
        client = FakeSMClient("{}")
        backend = AWSSecretsBundleBackend(ARN, client=client)
        assert backend.seed_if_empty([], "CHANGEME") is False
        assert client.get_calls == 0
        assert client.put_calls == []

    def test_seed_write_failure_warns_and_continues(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = FakeSMClient("{}")
        backend = AWSSecretsBundleBackend(ARN, client=client)

        def failing_put(SecretId: str, SecretString: str, **kwargs: Any) -> None:
            raise RuntimeError("access denied")

        monkeypatch.setattr(client, "put_secret_value", failing_put)
        with caplog.at_level("WARNING", logger="konfig.secrets.aws_bundle_backend"):
            assert backend.seed_if_empty(self.NAMES, "CHANGEME") is False
        assert any("Could not seed" in r.message for r in caplog.records)


class VersionedFakeSMClient:
    """Stand-in for a boto3 secretsmanager client that keeps a version history.

    Every put creates a version whose VersionId is the request's
    ClientRequestToken (as Secrets Manager does) or a generated id. Reads
    return AWSCURRENT unless a stale read has been scripted with
    ``stale_reads``: each entry names the version the next read returns,
    which is how Secrets Manager's eventual consistency shows itself.
    """

    def __init__(self, bundle: dict[str, str], version_id: str = "A") -> None:
        self.versions: dict[str, str] = {version_id: json.dumps(bundle)}
        self.current = version_id
        self.stale_reads: list[str] = []
        self.always_stale: str | None = None
        self.get_calls = 0
        self.max_get_calls = 50  # fail fast rather than hang on an unbounded retry
        self.get_delay = 0.0  # widens the read-modify-write window for thread tests
        self.put_returns_version = True
        self.put_calls: list[dict[str, Any]] = []
        self.exceptions = SimpleNamespace(ResourceNotFoundException=_ResourceNotFound)
        self._ids = itertools.count(1)
        self._mutex = threading.Lock()

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        with self._mutex:
            self.get_calls += 1
            assert self.get_calls <= self.max_get_calls, "unbounded re-fetching"
            if self.stale_reads:
                version = self.stale_reads.pop(0)
            elif self.always_stale is not None:
                version = self.always_stale
            else:
                version = self.current
            response = {
                "SecretString": self.versions[version],
                "VersionId": version,
                "VersionStages": ["AWSCURRENT"],
            }
        if self.get_delay:
            time.sleep(self.get_delay)
        return response

    def put_secret_value(
        self, SecretId: str, SecretString: str, ClientRequestToken: str | None = None
    ) -> dict[str, Any]:
        with self._mutex:
            self.put_calls.append(
                {"SecretString": SecretString, "ClientRequestToken": ClientRequestToken}
            )
            version = ClientRequestToken or f"generated-{next(self._ids)}"
            if version in self.versions:
                # Secrets Manager ignores a repeated token with the same value.
                assert self.versions[version] == SecretString
                return {"VersionId": version, "VersionStages": ["AWSCURRENT"]}
            self.versions[version] = SecretString
            self.current = version
            if not self.put_returns_version:
                return {}
            return {"VersionId": version, "VersionStages": ["AWSCURRENT"]}

    def write_as_other_writer(self, bundle: dict[str, str], version_id: str) -> None:
        """Another process puts a version this backend has never seen."""
        self.versions[version_id] = json.dumps(bundle)
        self.current = version_id

    def bundle(self, version: str | None = None) -> dict[str, str]:
        return dict(json.loads(self.versions[version or self.current]))

    def last_put(self) -> dict[str, str]:
        return dict(json.loads(self.put_calls[-1]["SecretString"]))


VERSION_A = {"e1": "1", "e2": "2", "e3": "3", "e4": "4"}


def _no_sleep_backend(client: VersionedFakeSMClient, **kwargs: Any) -> Any:
    """A backend whose re-fetch backoff records its delays instead of sleeping."""
    backend = AWSSecretsBundleBackend(ARN, client=client, **kwargs)
    slept: list[float] = []
    backend._sleep = slept.append  # type: ignore[method-assign]
    return backend, slept


class TestSequentialWritesLostUpdate:
    """Sequential writes from one instance against an eventually consistent store."""

    def test_third_write_built_from_superseded_version_keeps_every_key(self) -> None:
        # Version A has four entries; key 1 makes B and key 2 makes C. The
        # third write's fetch returns A again, superseded twice over.
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client)
        backend.set("key1", "v1")
        backend.set("key2", "v2")
        client.stale_reads = ["A"]
        backend.set("key3", "v3")
        assert client.last_put() == {
            **VERSION_A,
            "key1": "v1",
            "key2": "v2",
            "key3": "v3",
        }
        assert client.bundle() == client.last_put()

    def test_write_after_stale_read_of_its_own_base_keeps_its_last_write(self) -> None:
        # The write's own version must count as newest, not only versions read.
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, slept = _no_sleep_backend(client)
        backend.set("key1", "v1")
        client.stale_reads = ["A"]
        backend.set("key2", "v2")
        assert client.last_put() == {**VERSION_A, "key1": "v1", "key2": "v2"}
        assert slept == [0.1]

    def test_written_version_known_without_version_id_in_response(self) -> None:
        # The ClientRequestToken is the new VersionId, so it is tracked even
        # when the put response carries no VersionId.
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        client.put_returns_version = False
        backend, _ = _no_sleep_backend(client)
        backend.set("key1", "v1")
        client.stale_reads = ["A"]
        backend.set("key2", "v2")
        assert client.last_put() == {**VERSION_A, "key1": "v1", "key2": "v2"}

    def test_delete_after_stale_read_keeps_earlier_write(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client)
        backend.set("key1", "v1")
        client.stale_reads = ["A", "A"]
        backend.delete("e1")
        expected = {**VERSION_A, "key1": "v1"}
        del expected["e1"]
        assert client.last_put() == expected

    def test_still_stale_after_bounded_backoff_raises_without_writing(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, slept = _no_sleep_backend(client)
        backend.set("key1", "v1")
        puts_before, gets_before = len(client.put_calls), client.get_calls
        client.always_stale = "A"
        with pytest.raises(StaleBundleError, match="superseded"):
            backend.set("key2", "v2")
        assert len(client.put_calls) == puts_before  # no put at all
        assert client.get_calls - gets_before == 6  # one read plus five re-reads
        assert slept == [0.1, 0.2, 0.4, 0.8, 1.6]  # 3.1 seconds in all
        assert isinstance(StaleBundleError("x"), RuntimeError)

    def test_default_backoff_bound(self) -> None:
        backend = AWSSecretsBundleBackend(ARN, client=VersionedFakeSMClient({}))
        assert backend._retry_delays == (0.1, 0.2, 0.4, 0.8, 1.6)
        assert sum(backend._retry_delays) == pytest.approx(3.1)

    def test_version_from_another_writer_is_accepted_as_current(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, slept = _no_sleep_backend(client)
        backend.set("key1", "v1")
        other = {**client.bundle(), "other": "o"}
        client.write_as_other_writer(other, version_id="X")
        backend.set("key2", "v2")
        assert slept == []  # an unseen version is never treated as stale
        assert client.last_put() == {**other, "key2": "v2"}

    def test_stale_read_recovers_to_another_writers_newer_version(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, slept = _no_sleep_backend(client)
        backend.set("key1", "v1")
        other = {**client.bundle(), "other": "o"}
        client.write_as_other_writer(other, version_id="X")
        client.stale_reads = ["A"]
        backend.set("key2", "v2")
        assert slept == [0.1]
        assert client.last_put() == {**other, "key2": "v2"}

    def test_only_recent_versions_are_remembered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(aws_bundle_backend, "_KNOWN_VERSIONS_LIMIT", 3)
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client)
        for i in range(5):
            backend.set(f"key{i}", "v")
        assert len(backend._versions) == 3
        previous = [v for v in client.versions if v != client.current][-1]
        client.stale_reads = [previous]
        backend.set("last", "v")  # a recent superseded version is still caught
        assert set(client.last_put()) >= {f"key{i}" for i in range(5)}


class TestReadsAfterRefresh:
    """A read after refresh() never goes back past what this instance has seen."""

    def test_get_after_refresh_never_reports_a_written_key_as_lost(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, slept = _no_sleep_backend(client)
        backend.set("key1", "v1")
        backend.set("key2", "v2")
        backend.refresh()
        client.stale_reads = ["A"]
        assert backend.get("key1") == "v1"
        assert backend.get("key2") == "v2"
        assert slept == [0.1]

    def test_get_after_refresh_never_reports_a_deleted_key_as_present(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client)
        backend.delete("e1")
        backend.refresh()
        client.stale_reads = ["A"]
        assert backend.has("e1") is False
        assert "e1" not in backend.list_keys()

    def test_read_after_ttl_expiry_never_goes_back(self) -> None:
        clock = Clock()
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client, ttl=300, time_func=clock)
        backend.set("key1", "v1")
        clock.advance(301)
        client.stale_reads = ["A"]
        assert backend.get("key1") == "v1"

    def test_read_still_stale_after_backoff_raises(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client)
        backend.set("key1", "v1")
        backend.refresh()
        client.always_stale = "A"
        with pytest.raises(StaleBundleError):
            backend.get("key1")

    def test_seed_after_stale_read_does_not_overwrite_written_keys(self) -> None:
        client = VersionedFakeSMClient({}, version_id="A")
        backend, _ = _no_sleep_backend(client)
        backend.set("key1", "v1")
        client.stale_reads = ["A"]  # the empty version, superseded by our write
        assert backend.seed_if_empty(["api_key"], "CHANGEME") is False
        assert client.bundle() == {"key1": "v1"}


class TestIdempotentPut:
    def test_each_put_carries_a_fresh_client_request_token(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        backend, _ = _no_sleep_backend(client)
        backend.set("key1", "v1")
        backend.set("key2", "v2")
        backend.delete("key1")
        tokens = [call["ClientRequestToken"] for call in client.put_calls]
        assert all(isinstance(t, str) and 32 <= len(t) <= 64 for t in tokens)
        assert len(set(tokens)) == len(tokens)
        assert client.current == tokens[-1]  # the token became the VersionId


class TestThreadedWriters:
    def test_concurrent_set_from_threads_loses_no_update(self) -> None:
        client = VersionedFakeSMClient(VERSION_A, version_id="A")
        client.get_delay = 0.002  # let threads interleave between read and write
        client.max_get_calls = 10_000
        backend, _ = _no_sleep_backend(client)
        errors: list[BaseException] = []

        def writer(n: int) -> None:
            try:
                for i in range(5):
                    backend.set(f"t{n}-{i}", str(i))
            except BaseException as exc:  # surfaced in the main thread below
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert errors == []
        expected = {f"t{n}-{i}" for n in range(8) for i in range(5)}
        assert expected <= set(client.bundle())
        assert len(client.put_calls) == 40
