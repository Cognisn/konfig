"""Basic settings usage — loading from a YAML config file with defaults and env vars."""

from pathlib import Path
from konfig import Settings

# Create a sample config file
config_path = Path("sample_config.yaml")
config_path.write_text(
    "database:\n"
    "  host: config-host.example.com\n"
    "  port: 3306\n"
    "server:\n"
    "  debug: false\n"
)

# Initialise settings with defaults, config file, and env prefix
settings = Settings(
    config_file=config_path,
    defaults={
        "database": {"host": "localhost", "port": 5432, "name": "mydb"},
        "server": {"debug": True, "workers": 4},
    },
    env_prefix="MYAPP",
)

# Read values — config file overrides defaults
print(f"DB host: {settings.get('database.host')}")        # config-host.example.com (from file)
print(f"DB port: {settings.get('database.port')}")        # 3306 (from file)
print(f"DB name: {settings.get('database.name')}")        # mydb (from defaults)
print(f"Workers: {settings.get('server.workers')}")       # 4 (from defaults)

# Type casting
port = settings.get("database.port", cast=int)
print(f"Port as int: {port} (type: {type(port).__name__})")

# Runtime overrides (highest precedence)
settings.set("database.host", "runtime-host.example.com")
print(f"DB host after override: {settings.get('database.host')}")  # runtime-host.example.com

# Section access
db_config = settings.get_section("database")
print(f"Full DB config: {db_config}")

# Check existence
print(f"Has database.host: {settings.has('database.host')}")
print(f"Has missing.key: {settings.has('missing.key')}")

# Delete runtime override
settings.delete("database.host")
print(f"DB host after delete: {settings.get('database.host')}")  # back to config-host.example.com

# Clean up
config_path.unlink()

print("\nTo override via environment, set: MYAPP__DATABASE__HOST=env-host")
