"""Where the opt-in LocalStack integration tests find LocalStack.

The endpoint URL comes from KONFIG_TEST_LOCALSTACK_URL, defaulting to the port
the repository's docker-compose.yml publishes, so a plain `docker compose up -d`
needs no configuration. Set it when LocalStack is published elsewhere, for
example in a per-worktree sandbox: KONFIG_TEST_LOCALSTACK_URL=http://127.0.0.1:22466
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

ENDPOINT_ENV_VAR = "KONFIG_TEST_LOCALSTACK_URL"
DEFAULT_ENDPOINT_URL = "http://127.0.0.1:4566"


@dataclass(frozen=True)
class LocalStackEndpoint:
    url: str
    host: str
    port: int


def resolve_endpoint(environ: Mapping[str, str] | None = None) -> LocalStackEndpoint:
    """Return the LocalStack endpoint from the environment (or the default).

    Raises ValueError, naming the variable, for a value that is not an
    http(s) URL with a host and an explicit port.
    """
    env = os.environ if environ is None else environ
    url = env.get(ENDPOINT_ENV_VAR, "").strip().rstrip("/") or DEFAULT_ENDPOINT_URL

    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = None
    if parts.scheme not in ("http", "https") or not parts.hostname or port is None:
        raise ValueError(
            f"{ENDPOINT_ENV_VAR}={url!r} must be an http(s) URL with a host and "
            f"a port, for example {DEFAULT_ENDPOINT_URL}"
        )
    return LocalStackEndpoint(url=url, host=parts.hostname, port=port)
