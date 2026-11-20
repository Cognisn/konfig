"""AWS Secrets Manager single-secret JSON bundle backend (optional)."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Callable

from konfig._aws import parse_region
from konfig.secrets.backend import SecretBackend

logger = logging.getLogger(__name__)

_NOT_JSON_OBJECT = "Designated AWS secret is not a JSON object."
_NO_SECRET_STRING = (
    "Designated AWS secret has no SecretString (binary secrets are not supported)."
)

# Delays between re-fetches when Secrets Manager returns a version this backend
# already knows has been superseded: six reads in all, 3.1 seconds of waiting.
_STALE_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.2, 0.4, 0.8, 1.6)

# How many version ids one backend remembers. The oldest are forgotten first, so
# only a read lagging by more than this many versions could go undetected.
_KNOWN_VERSIONS_LIMIT = 1024


class StaleBundleError(RuntimeError):
    """Secrets Manager kept returning a bundle version known to be superseded.

    Raised by a read or write once the bounded re-fetch gives up; no write is
    made. It is a ``RuntimeError``, so callers need not import it to catch it.
    """


class AWSSecretsBundleBackend(SecretBackend):
    """Reads and writes secrets to a single AWS secret holding a JSON bundle.

    The secret named by ``arn`` stores a JSON object; each konfig key is a key
    within that object. Requires ``boto3`` (``pip install konfig[aws]``).

    Secrets Manager is eventually consistent, so a read can return an older
    version than one already written. The backend remembers every version id
    it has read or written; a read returning one of those that has since been
    superseded is retried with a short, bounded backoff and never used as the
    base of a write or served from ``get()``. A version it has never seen
    (another writer's) is taken as current. ``set()`` and ``delete()`` are
    serialised by a lock within one instance; writers in other processes are
    not coordinated.

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
        self._region = parse_region(arn)
        self._ttl = ttl
        self._time = time_func
        self._client: Any = client if client is not None else self._create_client()
        self._cache: dict[str, str] | None = None
        self._cache_at: float = 0.0
        # Serialises read-modify-write and guards the state below across threads.
        self._lock = threading.RLock()
        # Version ids this instance has read or written, oldest first; the last
        # is the newest. Any other id in it is known to have been superseded.
        self._versions: dict[str, None] = {}
        self._retry_delays: tuple[float, ...] = _STALE_RETRY_DELAYS
        self._sleep: Callable[[float], None] = time.sleep

    @property
    def region(self) -> str:
        return self._region

    def _create_client(self) -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for the AWS Secrets Manager backend. "
                "Install it with: pip install konfig[aws]"
            ) from exc
        return boto3.client("secretsmanager", region_name=self._region)

    def _note_version(self, version_id: str | None) -> None:
        """Record ``version_id`` as the newest version this instance knows."""
        if version_id is None:
            return
        self._versions.pop(version_id, None)
        self._versions[version_id] = None
        while len(self._versions) > _KNOWN_VERSIONS_LIMIT:
            del self._versions[next(iter(self._versions))]

    def _is_superseded(self, version_id: str | None) -> bool:
        """True for a version this instance has seen replaced by a newer one.

        A version it has never seen (another writer's) is taken as current.
        """
        if version_id is None or version_id not in self._versions:
            return False
        return version_id != next(reversed(self._versions))

    def _get_current(self) -> dict[str, Any]:
        """Call get_secret_value, re-fetching while it returns a superseded version.

        Raises:
            StaleBundleError: still superseded after the bounded backoff.
        """
        delays = iter(self._retry_delays)
        while True:
            response: dict[str, Any] = self._client.get_secret_value(SecretId=self._arn)
            version_id = response.get("VersionId")
            if not self._is_superseded(version_id):
                self._note_version(version_id)
                return response
            delay = next(delays, None)
            if delay is None:
                raise StaleBundleError(
                    f"AWS secret {self._arn} still returns version {version_id}, "
                    "which this process has already seen superseded, after "
                    f"{len(self._retry_delays) + 1} reads over "
                    f"{sum(self._retry_delays):g}s; nothing was written. Secrets "
                    "Manager is eventually consistent: retry shortly."
                )
            logger.debug(
                "AWS bundle secret %s returned superseded version %s; "
                "re-fetching in %gs",
                self._arn,
                version_id,
                delay,
            )
            self._sleep(delay)

    def _fetch(self) -> dict[str, str]:
        """Fetch and parse the bundle directly from AWS (no cache).

        Never returns a version this instance knows has been superseded.
        """
        logger.debug("Fetching AWS bundle secret %s", self._arn)
        try:
            response = self._get_current()
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
        with self._lock:
            now = self._time()
            if self._cache is None or (now - self._cache_at) >= self._ttl:
                self._cache = self._fetch()
                self._cache_at = now
            return self._cache

    def refresh(self) -> None:
        """Force the next read to re-fetch the bundle from AWS.

        The versions this instance has seen are kept, so the next read never
        goes back to a bundle older than the newest of them.
        """
        with self._lock:
            self._cache = None

    def get(self, key: str) -> str | None:
        return self._bundle().get(key)

    def _write(self, bundle: dict[str, str]) -> None:
        """Persist the whole bundle to AWS and update the write-through cache.

        The ClientRequestToken becomes the new version's VersionId, so the
        version is known even without it in the response, and a resent request
        cannot create a second version.
        """
        token = str(uuid.uuid4())
        with self._lock:
            response = self._client.put_secret_value(
                SecretId=self._arn,
                SecretString=json.dumps(bundle),
                ClientRequestToken=token,
            )
            version_id = (
                response.get("VersionId") if isinstance(response, dict) else None
            )
            self._note_version(version_id or token)
            self._cache = bundle
            self._cache_at = self._time()

    def set(self, key: str, value: str) -> None:
        with self._lock:
            bundle = self._fetch()  # re-fetch before write to narrow the race window
            bundle[key] = value
            self._write(bundle)

    def delete(self, key: str) -> None:
        with self._lock:
            bundle = self._fetch()  # re-fetch before write to narrow the race window
            bundle.pop(key, None)
            self._write(bundle)

    def has(self, key: str) -> bool:
        return key in self._bundle()

    def list_keys(self) -> list[str]:
        return list(self._bundle().keys())

    def seed_if_empty(self, names: list[str], placeholder: str) -> bool:
        """Seed the bundle with placeholder entries when the store is empty.

        Empty means an empty or whitespace-only ``SecretString`` or a bare
        ``{}``. A missing secret, an unreadable secret, a binary-only secret,
        or any malformed payload is left untouched — malformed payloads keep
        failing fast on the read path. Concurrent replicas racing this write
        are benign: every writer writes the same placeholder map.

        Returns:
            True when a seed write happened.
        """
        if not names:
            return False
        with self._lock:
            return self._seed_if_empty(names, placeholder)

    def _seed_if_empty(self, names: list[str], placeholder: str) -> bool:
        try:
            response = self._get_current()
        except Exception as exc:
            logger.warning(
                "Could not seed AWS secrets bundle %s (unreadable or missing, "
                "continuing): %s",
                self._arn,
                exc,
            )
            return False
        raw = response.get("SecretString")
        if raw is None:
            return False  # binary-only secret: not ours to touch
        if raw.strip():
            try:
                if json.loads(raw) != {}:
                    return False
            except ValueError:
                return False  # malformed: the read path fails fast on it
        try:
            self._write({name: placeholder for name in names})
        except Exception as exc:
            logger.warning(
                "Could not seed AWS secrets bundle %s with placeholders "
                "(continuing): %s",
                self._arn,
                exc,
            )
            return False
        logger.warning(
            "Seeded empty AWS secrets bundle %s with %d placeholder entries; "
            "populate them, then restart",
            self._arn,
            len(names),
        )
        return True
