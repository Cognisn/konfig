"""Async AppContext usage — for async applications and servers."""

import asyncio
import tempfile
from pathlib import Path
from konfig import AppContext


async def main() -> None:
    config_dir = Path(tempfile.mkdtemp())

    async with AppContext(
        name="Async Server",
        version="2.0.0",
        defaults={
            "server": {"host": "0.0.0.0", "port": 8080},
            "secrets": {
                "backend": "encrypted_file",
                "file_path": str(config_dir / "secrets.enc"),
                "master_key": "async-sample-key",
            },
            "logging": {
                "level": "DEBUG",
                "format": "text",
                "log_dir": str(config_dir / "logs"),
                "console_output": "stderr",
            },
        },
    ) as ctx:
        host = ctx.settings.get("server.host")
        port = ctx.settings.get("server.port", cast=int)
        ctx.logger.info("Server configured at %s:%d", host, port)

        # Simulate async work
        ctx.logger.info("Starting async operations...")
        await asyncio.sleep(0.1)
        ctx.logger.info("Async operations complete")

        print(f"Async server configured at {host}:{port}")

    print("Async AppContext exited cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
