"""Application data directory and archival folder resolution.

Shared by the deleter CLI and the archive viewer so both sides agree on
where config.json and the default archival folder live."""


import json
import os
import sys
from pathlib import Path


def app_config_dir():
    """Per-OS application data directory (holds config.json and the default
    archival folder). Cross-platform safe: no hardcoded absolute paths."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "message-guillotine"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(base) / "message-guillotine"
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / "message-guillotine"


def resolve_archive_dir(explicit=None):
    """The archival folder that stores every archive run (one folder per chat).

    Priority: explicit argument, then the DM_ARCHIVE_DIR environment variable,
    then the archive_dir recorded in the app config file, then the per-OS default."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DM_ARCHIVE_DIR")
    if env:
        return Path(env).expanduser()
    try:
        config = json.loads((app_config_dir() / "config.json").read_text(encoding="utf-8"))
        return Path(config["archive_dir"]).expanduser()
    except (OSError, ValueError, TypeError, KeyError):
        return app_config_dir() / "archives"


def configure_archive_dir(current):
    """Prompt for a new archival folder and persist it to the app config."""
    print("\n" + "="*80)
    print("SET ARCHIVE FOLDER")
    print(f"Current: {current}")
    print("Every archive run is stored as its own folder inside this one.")
    raw = input("New archive folder (blank to keep current): ").strip()
    if not raw:
        print("Archive folder unchanged.")
        return current
    new_dir = Path(raw).expanduser()
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        config_dir = app_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"archive_dir": str(new_dir)}) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"Could not use that folder: {exc}")
        return current
    print(f"Archive folder set to: {new_dir}")
    print("(The DM_ARCHIVE_DIR environment variable still overrides this when set.)")
    return new_dir
