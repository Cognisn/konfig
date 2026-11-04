"""Optional centralised log forwarding.

One nominated instance, the collector, receives log records forwarded over
pinned TLS by every other instance (the senders) and writes them, tagged with
each sender's identity, to a central stream on its own log volume. Every
instance keeps logging locally exactly as before.

Most applications enable it through ``AppContext`` with the
``KONFIG_LOG_CENTRAL`` / ``KONFIG_LOG_COLLECTOR`` environment variables or
``logging.central.*`` settings. Applications that compose ``Settings``,
``Secrets`` and ``LogManager`` themselves call
``log_manager.start_central_logging(settings, secrets)`` after
``log_manager.setup()``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from konfig.logging.central.config import CentralLogConfig, resolve_config

if TYPE_CHECKING:
    from konfig.logging.central.collector import CentralCollector
    from konfig.logging.central.sender import LogSender
    from konfig.logging.manager import LogManager

__all__ = [
    "CentralLogConfig",
    "CentralLogging",
    "resolve_config",
    "start_central_logging",
    "stop_central_logging",
]

logger = logging.getLogger(__name__)


class CentralLogging:
    """A running centralised logging role, returned by :func:`start_central_logging`."""

    def __init__(
        self,
        config: CentralLogConfig,
        *,
        sender: Optional[LogSender] = None,
        collector: Optional[CentralCollector] = None,
    ) -> None:
        self.config = config
        self.sender = sender
        self.collector = collector
        self._restore: list[Callable[[], None]] = []
        self._stopped = False

    @property
    def role(self) -> str:
        """``"collector"`` or ``"sender"``."""
        return "collector" if self.collector is not None else "sender"

    def _on_stop(self, action: Callable[[], None]) -> None:
        self._restore.append(action)

    def stop(self) -> None:
        """Stop forwarding or collecting. Safe to call more than once."""
        if self._stopped:
            return
        self._stopped = True
        root = logging.getLogger()
        if self.sender is not None:
            root.removeHandler(self.sender.handler)
            unsent = self.sender.stop()
            if unsent:
                logger.warning(
                    "Central log forwarding stopped with %d record(s) unsent", unsent
                )
            else:
                logger.info(
                    "Central log forwarding stopped; %d record(s) forwarded",
                    self.sender.sent,
                )
        if self.collector is not None:
            if self.collector.capture_handler is not None:
                root.removeHandler(self.collector.capture_handler)
            self.collector.stop()
            logger.info("Log collector stopped")
        for action in reversed(self._restore):
            try:
                action()
            except Exception:
                logger.debug("Could not restore logging state", exc_info=True)
        self._restore.clear()


def start_central_logging(
    log_manager: LogManager,
    settings: Any,
    secrets: Any = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[CentralLogging]:
    """Start centralised log forwarding when it is enabled.

    Call after ``log_manager.setup()``. Returns None when the feature is not
    enabled, is misconfigured, or fails to start; failures are logged locally
    and never raised, so the application always carries on.

    Args:
        log_manager: The application's set-up ``LogManager``.
        settings: The application's ``Settings``.
        secrets: The application's ``Secrets`` (needed for discovery and
            ``secret://`` token references).
        environ: Environment mapping; defaults to ``os.environ``.
    """
    config = resolve_config(settings, environ)
    if not config.active:
        return None
    try:
        return _start(config, log_manager, secrets, environ)
    except Exception as exc:
        logger.warning(
            "Centralised log forwarding could not start (%s: %s); continuing "
            "without it",
            type(exc).__name__,
            exc,
        )
        return None


def stop_central_logging(handle: Optional[CentralLogging]) -> None:
    """Stop a handle returned by :func:`start_central_logging` (None is ignored)."""
    if handle is not None:
        handle.stop()


def _start(
    config: CentralLogConfig,
    log_manager: LogManager,
    secrets: Any,
    environ: Optional[Mapping[str, str]],
) -> Optional[CentralLogging]:
    from konfig.logging.central.identity import detect_instance

    run_dir = log_manager.run_dir
    identify: Callable[[], dict[str, Any]] = partial(
        detect_instance,
        app_id=log_manager.app_id,
        app_name=log_manager.app_name,
        version=log_manager.version,
        run_dir=run_dir.name if run_dir is not None else None,
        label=config.instance_label,
        environ=environ,
    )

    handle: Optional[CentralLogging]
    if config.collector:
        handle = _start_collector(config, log_manager, secrets, identify())
    else:
        handle = _start_sender(config, log_manager, secrets, identify)
    if handle is None:
        return None
    _lower_root_level(handle, config, log_manager)
    return handle


def _start_collector(
    config: CentralLogConfig,
    log_manager: LogManager,
    secrets: Any,
    instance: dict[str, Any],
) -> CentralLogging:
    from konfig.logging.central.collector import CentralCollector

    collector = CentralCollector(
        config, log_dir=Path(log_manager.log_dir), instance=instance, secrets=secrets
    )
    collector.start()
    handle = CentralLogging(config, collector=collector)
    if config.include_instance_locally:
        _include_instance_locally(handle, log_manager, instance)
    assert collector.capture_handler is not None
    logging.getLogger().addHandler(collector.capture_handler)
    return handle


def _start_sender(
    config: CentralLogConfig,
    log_manager: LogManager,
    secrets: Any,
    identify: Callable[[], dict[str, Any]],
) -> Optional[CentralLogging]:
    from konfig.logging.central.discovery import (
        CollectorEntry,
        is_shared_backend,
        validate_details,
    )
    from konfig.logging.central.sender import LogSender

    override: Optional[CollectorEntry] = None
    if config.override_error:
        logger.error(
            "Centralised log forwarding disabled: %s (from %s)",
            config.override_error,
            config.override_source,
        )
        return None
    if config.has_override:
        assert config.endpoint and config.cert_sha256 and config.token
        token: Optional[str] = config.token
        if token and token.startswith("secret://"):
            if secrets is None:
                logger.error(
                    "Centralised log forwarding disabled: the token is a secret:// "
                    "reference but no secrets store is available"
                )
                return None
            token = secrets.resolve_uri(token)
        if not token:
            logger.error(
                "Centralised log forwarding disabled: the token reference did not "
                "resolve to a value"
            )
            return None
        try:
            override = validate_details(config.endpoint, config.cert_sha256, token)
        except ValueError as exc:
            logger.error(
                "Centralised log forwarding disabled: %s (from %s)",
                exc,
                config.override_source,
            )
            return None
    elif secrets is None:
        logger.error(
            "Centralised log forwarding disabled: no secrets store to discover the "
            "collector from, and no KONFIG_LOG_ENDPOINT / KONFIG_LOG_CERT_SHA256 / "
            "KONFIG_LOG_TOKEN override"
        )
        return None
    elif not is_shared_backend(secrets):
        logger.warning(
            "The active secrets backend is the OS keyring, which is local to this "
            "machine; the collector can only be discovered if it runs here. Use a "
            "shared store or the KONFIG_LOG_* overrides"
        )

    handle_instance: Optional[dict[str, Any]] = None
    if config.include_instance_locally:
        handle_instance = identify()
        fixed = handle_instance

        def identify() -> dict[str, Any]:
            return fixed

    sender = LogSender(
        config, secrets=secrets, instance_factory=identify, override=override
    )
    handle = CentralLogging(config, sender=sender)
    if handle_instance is not None:
        _include_instance_locally(handle, log_manager, handle_instance)
    logging.getLogger().addHandler(sender.handler)
    sender.start()
    return handle


def _include_instance_locally(
    handle: CentralLogging, log_manager: LogManager, instance: dict[str, Any]
) -> None:
    """Swap the manager's JSON formatters for ones that add the instance block."""
    from konfig.logging.formatters import InstanceJSONFormatter, JSONFormatter

    for handler in log_manager.handlers:
        original = handler.formatter
        if isinstance(original, JSONFormatter):
            handler.setFormatter(InstanceJSONFormatter(instance))
            handle._on_stop(partial(handler.setFormatter, original))


def _lower_root_level(
    handle: CentralLogging, config: CentralLogConfig, log_manager: LogManager
) -> None:
    """Let records below the local level reach the forwarding handler.

    The forwarded level is independent of the local one. When it is lower,
    the root logger is lowered to it and the manager's own handlers are
    pinned at the local level, so local output is unchanged.
    """
    root = logging.getLogger()
    local_level = root.level
    if config.level >= root.getEffectiveLevel():
        return
    for handler in log_manager.handlers:
        if handler.level == logging.NOTSET:
            handler.setLevel(local_level)
            handle._on_stop(partial(handler.setLevel, logging.NOTSET))
    root.setLevel(config.level)
    handle._on_stop(partial(root.setLevel, local_level))
