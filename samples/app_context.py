"""AppContext usage — the recommended way to use Konfig in an application."""

import tempfile
from pathlib import Path
from konfig import AppContext

# Create a sample config file
config_dir = Path(tempfile.mkdtemp())
config_file = config_dir / "config.yaml"
config_file.write_text(
    "database:\n"
    "  host: localhost\n"
    "  port: 5432\n"
    "  name: myapp_db\n"
    "secrets:\n"
    "  backend: encrypted_file\n"
    "  file_path: {secrets_path}\n"
    "  master_key: sample-key\n"
    "logging:\n"
    "  level: INFO\n"
    "  format: text\n"
    "  log_dir: {log_dir}\n"
    "  retention_runs: 5\n"
    "  console_output: stderr\n".format(
        secrets_path=config_dir / "secrets.enc",
        log_dir=config_dir / "logs",
    )
)

# AppContext wires everything together
with AppContext(
    name="Sample Application",
    version="1.0.0",
    config_file=config_file,
    defaults={"server": {"workers": 4}},
    env_prefix="MYAPP",
) as ctx:
    # Access settings
    db_host = ctx.settings.get("database.host")
    workers = ctx.settings.get("server.workers", cast=int)
    ctx.logger.info("Database: %s, Workers: %d", db_host, workers)

    # Store and retrieve a secret
    ctx.secrets.set("api_key", "sk-demo-key")
    ctx.logger.info("Stored API key, has=%s", ctx.secrets.has("api_key"))

    # Log directory info
    ctx.logger.info("Logs are in: %s", ctx.log_manager.run_dir)

    print(f"App running with DB={db_host}, workers={workers}")
    print(f"Log directory: {ctx.log_manager.run_dir}")

# After exiting the context manager, logging handlers are cleaned up
print("AppContext exited cleanly.")
