
from __future__ import annotations
# golive — data directory layout
#
# GOLIVE_HOME (default: ~/.golive/)
# ├── sites/<site_id>/index.html     published sites
# ├── backups/<site_id>/             rollback snapshots (max 10 per site)
# ├── registry.db                    SQLite registry
# ├── data.db                        SQLite data layer (TemplateAPI rows)
# ├── logs/                          audit + error logs
# └── cache/                         misc caches (css backups, tailwind, ...)
"""golive.core.paths — unified data-directory resolution.

Resolution order:
  1. env GOLIVE_HOME              (explicit override, highest priority)
  2. the *home pointer* file      (written by ``golive init --home <DIR>``)
  3. ~/.golive/                   (default)

The pointer file exists because the single most confusing failure mode is
a CLI and a server that silently disagree about where the data lives:
``golive publish`` writes to one registry, ``golive list`` reads another,
and everything "looks fine". Persisting the choice in one well-known
location — and echoing it back through ``golive context`` — makes that
disagreement impossible to miss.

Pointer location: ``$XDG_CONFIG_HOME/golive/home`` (``~/.config/golive/home``
when XDG_CONFIG_HOME is unset). A single line holding an absolute path.

Public API:
  get_home()        -> Path   GOLIVE_HOME root (created)
  peek_home()       -> Path   same path, never created (read-only probes)
  home_source()     -> str    'env' | 'pointer' | 'default'
  home_source_label() -> str  human-readable provenance for `golive context`
  resolve_home()    -> (Path, source)  pure resolution, no side effects
  home_pointer_file() -> Path pointer file location (may not exist)
  read_home_pointer() -> Optional[Path]
  write_home_pointer(p) -> Path
  bootstrap_home_env() -> str  export pointer into $GOLIVE_HOME (CLI entry)
  get_sites_dir()   -> Path   sites/
  get_backups_dir() -> Path   backups/
  get_registry_db() -> Path   registry.db (path only; not created)
  get_data_db()     -> Path   data.db (path only; not created)
  get_log_dir()     -> Path   logs/
  get_data_dir()    -> Path   cache/
"""

import os
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_HOME_NAME = ".golive"

_resolved_home = None
#: True once bootstrap_home_env() copied the pointer into $GOLIVE_HOME —
#: without it the env var would masquerade as an explicit user override.
_pointer_bootstrapped = False


# ── home pointer (persisted `golive init --home`) ────────────────────────────

def home_pointer_file() -> Path:
    """Location of the pointer file (the file itself may not exist)."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "golive" / "home"


def read_home_pointer() -> Optional[Path]:
    """Path recorded by ``golive init --home``, or None when unset/unusable."""
    f = home_pointer_file()
    try:
        raw = f.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not raw:
        return None
    return Path(raw).expanduser()


def write_home_pointer(path) -> Path:
    """Persist GOLIVE_HOME so later CLI runs and servers agree. Returns file."""
    f = home_pointer_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(Path(path).expanduser()) + "\n", encoding="utf-8")
    return f


def clear_home_pointer() -> bool:
    """Remove the pointer file. True when a file was actually removed."""
    f = home_pointer_file()
    if f.is_file():
        f.unlink()
        return True
    return False


# ── resolution ───────────────────────────────────────────────────────────────

def resolve_home() -> Tuple[Path, str]:
    """(path, source) without touching the filesystem. source ∈ env/pointer/default."""
    env_val = os.environ.get("GOLIVE_HOME", "").strip()
    if env_val:
        # NB: resolve() so macOS /tmp -> /private/tmp symlinks compare equal.
        return (Path(env_val).expanduser().resolve(),
                "pointer" if _pointer_bootstrapped else "env")
    pointed = read_home_pointer()
    if pointed:
        return pointed.resolve(), "pointer"
    return (Path.home() / DEFAULT_HOME_NAME).resolve(), "default"


def bootstrap_home_env() -> str:
    """Export the pointer-recorded home into ``$GOLIVE_HOME`` for this process.

    Called once from the CLI entry point. Config loading, the server and
    any subprocess all read ``$GOLIVE_HOME`` directly; exporting it here is
    what makes ``golive init --home <DIR>`` stick for everything downstream
    instead of only for this module.

    Returns the effective source ('env' when the caller already set it).
    """
    global _pointer_bootstrapped
    if os.environ.get("GOLIVE_HOME", "").strip():
        return "env"
    pointed = read_home_pointer()
    if pointed:
        os.environ["GOLIVE_HOME"] = str(pointed)
        _pointer_bootstrapped = True
        return "pointer"
    return "default"


def peek_home() -> Path:
    """The GOLIVE_HOME path *without* creating it (read-only inspection)."""
    return resolve_home()[0]


def home_source() -> str:
    """'env' | 'pointer' | 'default' for the currently effective home."""
    return resolve_home()[1]


def home_source_label() -> str:
    """Human-readable provenance, e.g. ``from $GOLIVE_HOME``."""
    src = home_source()
    if src == "env":
        return "from $GOLIVE_HOME"
    if src == "pointer":
        return f"from {home_pointer_file()}"
    return "default (~/%s)" % DEFAULT_HOME_NAME


def get_home() -> Path:
    """Return GOLIVE_HOME root directory (created, cached per process)."""
    global _resolved_home
    if _resolved_home is None:
        _resolved_home = resolve_home()[0]
    _resolved_home.mkdir(parents=True, exist_ok=True)
    return _resolved_home


def reset_cache() -> None:
    """Testing helper: forget the cached home + pointer bootstrap state."""
    global _resolved_home, _pointer_bootstrapped
    _resolved_home = None
    _pointer_bootstrapped = False


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


def get_data_db() -> Path:
    """Path of the SQLite data-layer database (file may not exist yet)."""
    return get_home() / "data.db"


def get_log_dir() -> Path:
    """logs/ — audit log + error log."""
    return _sub("logs")


def get_data_dir() -> Path:
    """cache/ — css style backups and other caches."""
    return _sub("cache")
