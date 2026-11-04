"""Centralised log forwarding — one collector and two senders on one machine.

Run it with no arguments:

    python samples/central_logging.py

The script plays the collector itself and starts two sender processes. All
three share an encrypted secrets file (standing in for a shared volume or
the AWS Secrets Manager bundle), which is how the senders discover the
collector. In a real deployment each role is a separate container with the
same image; only the environment differs:

    collector:  KONFIG_LOG_COLLECTOR=true  KONFIG_LOG_COLLECTOR_ADVERTISE=log-collector:9020
    senders:    KONFIG_LOG_CENTRAL=true    KONFIG_LOG_INSTANCE_LABEL=worker-1
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from konfig import AppContext


def app_context(role: str, base: Path, store: Path) -> AppContext:
    """The same application configuration for every role."""
    return AppContext(
        name=f"Central Demo ({role})",
        version="1.0.0",
        config_file=base / "config.yaml",  # absent: defaults and env only
        system_config_file=base / "system.yaml",
        defaults={
            "logging": {
                "log_dir": str(base / role / "logs"),
                "console_output": "none",
                "central": {
                    # Bind to loopback for the demo; containers use 0.0.0.0:9020.
                    "listen": "127.0.0.1:0",
                    "advertise": "127.0.0.1",
                },
            },
            "secrets": {"backend": "encrypted_file", "file_path": str(store)},
        },
    )


def run_sender(label: str, base: Path, store: Path) -> None:
    with app_context(label, base, store):
        log = logging.getLogger("demo.worker")
        for i in range(5):
            log.info("%s finished job %d", label, i)
        log.warning("%s is shutting down", label)
    # Leaving the context drains the forwarding queue before closing logs.


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="konfig-central-"))
    store = base / "shared" / "secrets.enc"
    # Every role must share the store's master key.
    env = dict(os.environ, KONFIG_MASTER_KEY="demo-only-master-key")
    os.environ["KONFIG_MASTER_KEY"] = env["KONFIG_MASTER_KEY"]
    os.environ["KONFIG_LOG_COLLECTOR"] = "true"
    with app_context("collector", base, store) as ctx:
        ctx.logger.info("Collector is up")

        senders = []
        for label in ("worker-1", "worker-2"):
            sender_env = dict(
                env, KONFIG_LOG_CENTRAL="true", KONFIG_LOG_INSTANCE_LABEL=label
            )
            senders.append(
                subprocess.Popen(
                    [sys.executable, __file__, "sender", label, str(base), str(store)],
                    env=sender_env,
                )
            )
        for proc in senders:
            proc.wait(60)
        time.sleep(0.5)  # let the collector's writer catch up

        central = ctx.log_manager.log_dir / "central" / "latest" / "central.log"
        print(f"Central stream: {central}\n")
        for line in central.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            who = entry["instance"].get("label") or entry["instance"]["app_name"]
            print(f"[{who:>18}] {entry['level']:<7} {entry['message']}")

    print(f"\nEach role's own local logs are still under {base}/<role>/logs")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "sender":
        run_sender(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        main()
