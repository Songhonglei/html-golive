
from __future__ import annotations
# golive — data directory layout
#
# GOLIVE_HOME (default: ~/.golive/)
# ├── sites/<site_id>/index.html     published sites
# ├── backups/<site_id>/             rollback snapshots (max 10 per site)
# ├── registry.db                    SQLite registry
# ├── logs/                          audit + error logs
# └── cache/                         misc caches (css backups, tailwind, ...)
"""golive.core.paths — unified data-directory resolution.

Resolution order:
  1. env GOLIVE_HOME (explicit override, highest priority)
  2. ~/.golive/ (default)

Public API:
  get_home()        -> Path   GOLIVE_HOME root (created)
  get_sites_dir()   -> Path   sites/
  get_backups_dir() -> Path   backups/
  get_registry_db() -> Path   registry.db (path only; not created)
  get_log_dir()     -> Path   logs/
  get_data_dir()    -> Path   cache/
"""

import os
from pathlib import Path

_resolved_home = None


def get_home() -> Path:
    """Return GOLIVE_HOME root directory (created, cached per process)."""
    global _resolved_home
    if _resolved_home is None:
        env_val = os.environ.get("GOLIVE_HOME", "").strip()
        if env_val:
            _resolved_home = Path(env_val).expanduser().resolve()
        else:
            _resolved_home = Path.home() / ".golive"
    _resolved_home.mkdir(parents=True, exist_ok=True)
    return _resolved_home


def _sub(name: str) -> Path:
    d = get_home() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_sites_dir() -> Path:
    """sites/ — one directory per published site."""
    return _sub("sites")


def get_backups_dir() -> Path:
    """backups/ — rollback snapshots, max 10 per site."""
    return _sub("backups")


def get_registry_db() -> Path:
    """Path of the SQLite registry database (file may not exist yet)."""
    return get_home() / "registry.db"


def get_log_dir() -> Path:
    """logs/ — audit log + error log."""
    return _sub("logs")


def get_data_dir() -> Path:
    """cache/ — css style backups and other caches."""
    return _sub("cache")
