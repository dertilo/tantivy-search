import os
import shutil
from pathlib import Path

SCHEMA_VERSION = 5

CACHE_DIR = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tantivy-search"
)
INDEX_DIR = CACHE_DIR / "index"
SCHEMA_VERSION_FILE = INDEX_DIR / ".schema_version"


def check_schema_version() -> bool:
    """Return True if schema version matches, False if mismatch or missing."""
    if not SCHEMA_VERSION_FILE.exists():
        return False
    try:
        return int(SCHEMA_VERSION_FILE.read_text().strip()) == SCHEMA_VERSION
    except (ValueError, OSError):
        return False


def write_schema_version() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMA_VERSION_FILE.write_text(str(SCHEMA_VERSION))


def nuke_index() -> None:
    if INDEX_DIR.exists():
        shutil.rmtree(INDEX_DIR)
