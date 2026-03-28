"""Logging demo — run-scoped logging with retention and formatters."""

import logging
import tempfile
from pathlib import Path
from konfig import LogManager

# Use a temp directory so we don't pollute the working directory
log_base = Path(tempfile.mkdtemp()) / "logs"

manager = LogManager(
    app_name="Logging Demo",
    version="1.0.0",
    log_dir=log_base,
    level="DEBUG",
    log_format="text",         # Try "json" for structured output
    retention_runs=5,
    max_file_size_mb=10,
    max_files_per_run=3,
    console_output="stderr",   # "auto", "stderr", or "none"
)

# Setup creates the run directory, configures handlers, and logs the startup banner
root_logger = manager.setup()

# Use standard Python logging
logger = logging.getLogger("sample.app")
logger.debug("Debug message — visible because level is DEBUG")
logger.info("Application initialised successfully")
logger.warning("This is a warning")

try:
    result = 1 / 0
except ZeroDivisionError:
    logger.error("Caught an error", exc_info=True)

# Check where logs went
print(f"\nLogs written to: {manager.run_dir}")
print(f"Log file contents:")
log_file = manager.run_dir / "app.log"
print(log_file.read_text())

# Shutdown cleanly
manager.shutdown()

# Show the directory structure
print(f"\nRun directories in {log_base}:")
for item in sorted(log_base.iterdir()):
    suffix = " (symlink)" if item.is_symlink() else ""
    print(f"  {item.name}{suffix}")
