"""Resolve settings and environment variables into a central logging config.

This module is imported on every ``AppContext`` start-up to decide whether
centralised log forwarding is enabled, so it deliberately imports nothing
beyond the standard library's lightweight modules.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

ENV_ENABLED = "KONFIG_LOG_CENTRAL"
ENV_COLLECTOR = "KONFIG_LOG_COLLECTOR"
ENV_LISTEN = "KONFIG_LOG_COLLECTOR_LISTEN"
ENV_ADVERTISE = "KONFIG_LOG_COLLECTOR_ADVERTISE"
ENV_ENDPOINT = "KONFIG_LOG_ENDPOINT"
ENV_CERT_SHA256 = "KONFIG_LOG_CERT_SHA256"
ENV_TOKEN = "KONFIG_LOG_TOKEN"
ENV_INSTANCE_LABEL = "KONFIG_LOG_INSTANCE_LABEL"

DEFAULT_LISTEN = "0.0.0.0:9020"
DEFAULT_PORT = 9020
DEFAULT_STORE_KEY = "konfig.log_collector"

_PREFIX = "logging.central."
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})

# The three connection details that can override discovery. They are taken
# all from one source or not at all, never mixed.
_OVERRIDE_ENV = (ENV_ENDPOINT, ENV_CERT_SHA256, ENV_TOKEN)
_OVERRIDE_KEYS = ("endpoint", "cert_sha256", "token")


def parse_bool(value: Any, name: str) -> bool:
    """Parse a boolean setting or environment value.

    Accepts real booleans and the strings ``1/true/yes/on`` and
    ``0/false/no/off`` (case-insensitive). Anything else logs a warning and
    is treated as false.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    logger.warning(
        "Unrecognised boolean value %r for %s; treating it as false", value, name
    )
    return False


def parse_host_port(text: str, default_port: Optional[int] = None) -> tuple[str, int]:
    """Split ``host:port`` (or ``[ipv6]:port``) into its parts.

    Raises:
        ValueError: If the text is empty, the port is missing with no
            default, or the port is not a valid TCP port number.
    """
    text = text.strip()
    if not text:
        raise ValueError("address is empty")
    host: str
    port_text: Optional[str]
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            raise ValueError("unterminated IPv6 address")
        host = text[1:end]
        rest = text[end + 1 :]
        if rest and not rest.startswith(":"):
            raise ValueError("unexpected text after IPv6 address")
        port_text = rest[1:] if rest else None
    elif text.count(":") == 1:
        host, port_text = text.split(":")
    else:
        host, port_text = text, None
    if not host:
        raise ValueError("host is empty")
    if not port_text:
        if default_port is None:
            raise ValueError("port is missing")
        return host, default_port
    try:
        port = int(port_text)
    except ValueError:
        raise ValueError("port is not a number") from None
    if not 0 <= port <= 65535:
        raise ValueError("port is out of range")
    return host, port


@dataclass(frozen=True)
class CentralLogConfig:
    """Typed, immutable centralised log forwarding configuration.

    Build one with :func:`resolve_config`. The defaults leave the feature
    disabled.
    """

    enabled: bool = False
    collector: bool = False
    listen: str = DEFAULT_LISTEN
    advertise: Optional[str] = None
    endpoint: Optional[str] = None
    cert_sha256: Optional[str] = None
    token: Optional[str] = field(default=None, repr=False)
    override_source: Optional[str] = None
    override_error: Optional[str] = None
    instance_label: Optional[str] = None
    level: int = logging.INFO
    queue_size: int = 10000
    store_key: str = DEFAULT_STORE_KEY
    flush_timeout: float = 5.0
    include_instance_locally: bool = False
    max_connections: int = 1000
    retention_runs: int = 10
    max_file_size_mb: int = 100
    max_files: int = 10
    handshake_timeout: float = 10.0
    idle_timeout: float = 300.0

    @property
    def active(self) -> bool:
        """True when this instance takes part in forwarding in either role."""
        return self.enabled or self.collector

    @property
    def has_override(self) -> bool:
        """True when a complete endpoint, fingerprint and token were supplied."""
        return self.override_source is not None and self.override_error is None


def _setting(settings: Any, key: str) -> Any:
    if settings is None:
        return None
    try:
        return settings.get(_PREFIX + key)
    except Exception:  # a broken settings layer must not break start-up
        logger.debug("Could not read setting %s%s", _PREFIX, key, exc_info=True)
        return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(settings: Any, key: str, default: float, cast: type) -> Any:
    value = _setting(settings, key)
    if value is None:
        return default
    try:
        result = cast(value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid value %r for %s%s; using %s", value, _PREFIX, key, default
        )
        return default
    if result <= 0:
        logger.warning(
            "Value for %s%s must be positive; using %s", _PREFIX, key, default
        )
        return default
    return result


def _level(value: Any) -> int:
    if value is None:
        return logging.INFO
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    resolved = logging.getLevelName(str(value).strip().upper())
    if isinstance(resolved, int):
        return resolved
    logger.warning("Unknown level %r for %slevel; using INFO", value, _PREFIX)
    return logging.INFO


def _resolve_override(
    settings: Any, env: Mapping[str, str]
) -> tuple[dict[str, Optional[str]], Optional[str], Optional[str]]:
    """Return (values, source, error) for the endpoint/fingerprint/token trio."""
    from_env = {
        k: _text(env.get(name)) for k, name in zip(_OVERRIDE_KEYS, _OVERRIDE_ENV)
    }
    if any(from_env.values()):
        missing = [
            name for k, name in zip(_OVERRIDE_KEYS, _OVERRIDE_ENV) if not from_env[k]
        ]
        if missing:
            return (
                from_env,
                "environment",
                f"{', '.join(_OVERRIDE_ENV)} must be set together; missing: "
                f"{', '.join(missing)}",
            )
        return from_env, "environment", None

    from_settings = {k: _text(_setting(settings, k)) for k in _OVERRIDE_KEYS}
    if any(from_settings.values()):
        missing = [_PREFIX + k for k in _OVERRIDE_KEYS if not from_settings[k]]
        if missing:
            return (
                from_settings,
                "settings",
                f"{', '.join(_PREFIX + k for k in _OVERRIDE_KEYS)} must be set "
                f"together; missing: {', '.join(missing)}",
            )
        return from_settings, "settings", None

    return {k: None for k in _OVERRIDE_KEYS}, None, None


def resolve_config(
    settings: Any = None, environ: Optional[Mapping[str, str]] = None
) -> CentralLogConfig:
    """Resolve ``logging.central.*`` settings and environment variables.

    Environment variables win over settings. The endpoint, fingerprint and
    token override is all-or-nothing per source: a partial set from the
    environment is a configuration error (reported in ``override_error``),
    never topped up from settings or discovery.

    Args:
        settings: A ``Settings`` instance (or anything with a compatible
            ``get``), or None.
        environ: Environment mapping; defaults to ``os.environ``.
    """
    env = os.environ if environ is None else environ

    def pick(env_name: str, key: str) -> Any:
        if env_name in env:
            return env[env_name]
        return _setting(settings, key)

    collector_name = ENV_COLLECTOR if ENV_COLLECTOR in env else _PREFIX + "collector"
    enabled_name = ENV_ENABLED if ENV_ENABLED in env else _PREFIX + "enabled"
    collector = parse_bool(pick(ENV_COLLECTOR, "collector"), collector_name)
    enabled = collector or parse_bool(pick(ENV_ENABLED, "enabled"), enabled_name)

    if not enabled:
        # Disabled: skip the rest so start-up does no further work.
        return CentralLogConfig()

    values, source, error = _resolve_override(settings, env)
    defaults = CentralLogConfig()
    return CentralLogConfig(
        enabled=enabled,
        collector=collector,
        listen=_text(pick(ENV_LISTEN, "listen")) or DEFAULT_LISTEN,
        advertise=_text(pick(ENV_ADVERTISE, "advertise")),
        endpoint=values["endpoint"],
        cert_sha256=values["cert_sha256"],
        token=values["token"],
        override_source=source,
        override_error=error,
        instance_label=_text(pick(ENV_INSTANCE_LABEL, "instance_label")),
        level=_level(_setting(settings, "level")),
        queue_size=_number(settings, "queue_size", defaults.queue_size, int),
        store_key=_text(_setting(settings, "store_key")) or DEFAULT_STORE_KEY,
        flush_timeout=_number(settings, "flush_timeout", defaults.flush_timeout, float),
        include_instance_locally=parse_bool(
            _setting(settings, "include_instance_locally"),
            _PREFIX + "include_instance_locally",
        ),
        max_connections=_number(
            settings, "max_connections", defaults.max_connections, int
        ),
        retention_runs=_number(
            settings, "retention_runs", defaults.retention_runs, int
        ),
        max_file_size_mb=_number(
            settings, "max_file_size_mb", defaults.max_file_size_mb, int
        ),
        max_files=_number(settings, "max_files", defaults.max_files, int),
        handshake_timeout=_number(
            settings, "handshake_timeout", defaults.handshake_timeout, float
        ),
        idle_timeout=_number(settings, "idle_timeout", defaults.idle_timeout, float),
    )
