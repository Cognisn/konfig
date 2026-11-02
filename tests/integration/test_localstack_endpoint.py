"""Resolution of the LocalStack endpoint used by the opt-in integration tests.

These run in the normal suite (no boto3 or LocalStack needed), so both the
default and the KONFIG_TEST_LOCALSTACK_URL override stay proven.
"""

from __future__ import annotations

import pytest

from tests.integration._localstack import (
    DEFAULT_ENDPOINT_URL,
    ENDPOINT_ENV_VAR,
    LocalStackEndpoint,
    resolve_endpoint,
)


def test_env_var_name() -> None:
    assert ENDPOINT_ENV_VAR == "KONFIG_TEST_LOCALSTACK_URL"


def test_default_is_the_plain_docker_compose_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENDPOINT_ENV_VAR, raising=False)
    assert DEFAULT_ENDPOINT_URL == "http://127.0.0.1:4566"
    assert resolve_endpoint() == LocalStackEndpoint(
        url="http://127.0.0.1:4566", host="127.0.0.1", port=4566
    )


def test_blank_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENDPOINT_ENV_VAR, "   ")
    assert resolve_endpoint().url == DEFAULT_ENDPOINT_URL


def test_override_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENDPOINT_ENV_VAR, "http://127.0.0.1:22466")
    assert resolve_endpoint() == LocalStackEndpoint(
        url="http://127.0.0.1:22466", host="127.0.0.1", port=22466
    )


def test_override_trailing_slash_and_whitespace_are_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENDPOINT_ENV_VAR, " http://localhost:4510/ ")
    assert resolve_endpoint() == LocalStackEndpoint(
        url="http://localhost:4510", host="localhost", port=4510
    )


def test_explicit_mapping_beats_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENDPOINT_ENV_VAR, "http://127.0.0.1:1")
    endpoint = resolve_endpoint({ENDPOINT_ENV_VAR: "http://127.0.0.1:2"})
    assert endpoint.port == 2


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1:4566",  # no scheme
        "ftp://127.0.0.1:4566",  # unsupported scheme
        "http://:4566",  # no host
        "http://127.0.0.1",  # no port
        "http://127.0.0.1:notaport",  # bad port
    ],
)
def test_invalid_values_are_refused(value: str) -> None:
    with pytest.raises(ValueError, match=ENDPOINT_ENV_VAR):
        resolve_endpoint({ENDPOINT_ENV_VAR: value})
