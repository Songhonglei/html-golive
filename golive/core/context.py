"""golive.core.context — "which configuration am I actually using?".

The nastiest golive failure has no error message: the CLI and the server
resolve different ``GOLIVE_HOME`` values (one shell exported it, another
didn't), so ``golive publish`` writes to one registry and ``golive list``
reads another. Everything looks fine; the site is just gone.

``golive context`` answers that in one screen, and — the important part —
annotates *where each value came from*, because the provenance is the
thing people cannot see.

Everything here is strictly read-only: no directory is created, no
database is initialised. That matters because the whole point is to
observe the current state, not to change it (and because running
``context`` from the wrong shell must not silently mkdir a second home).

Public API:
  collect()   -> dict with one entry per row, each carrying a `source`
  render(...) -> the aligned text block printed by the CLI
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from golive.core import paths


def _fmt(path, exists_hint: str = "") -> str:
    return f"{path}{(' ' + exists_hint) if exists_hint else ''}"


def _count_sites(db: Path):
    """Number of rows in the registry, or None when unreadable/absent."""
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            return conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def _data_stats(db: Path):
    """(table_count, row_count) for the data db, or (None, None)."""
    if not db.is_file():
        return None, None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")]
            rows = 0
            for t in tables:
                if not t.replace("_", "").isalnum():
                    continue        # never interpolate anything odd into SQL
                rows += conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            return len(tables), rows
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None, None


def _config_source(cfg_path: Path) -> str:
    """Explain which lookup rule produced the config path we found."""
    if os.environ.get("GOLIVE_CONFIG", "").strip():
        return "from $GOLIVE_CONFIG"
    try:
        if cfg_path.parent.resolve() == Path.cwd().resolve():
            return "from ./golive.yaml"
    except OSError:  # pragma: no cover — unreadable cwd
        pass
    return "from $GOLIVE_HOME/golive.yaml"


def collect(cfg=None, port: int = 8787) -> dict:
    """Gather everything ``golive context`` reports. Creates nothing."""
    from golive import __version__

    if cfg is None:
        from golive.config import get_config
        cfg = get_config()

    home = paths.peek_home()
    home_src = paths.home_source()
    out = {
        "golive_version": __version__,
        "python": ".".join(str(x) for x in __import__("sys").version_info[:3]),
        "home": {
            "path": str(home),
            "exists": home.is_dir(),
            "source": home_src,
            "source_label": paths.home_source_label(),
        },
        "home_pointer": {
            "path": str(paths.home_pointer_file()),
            "exists": paths.home_pointer_file().is_file(),
        },
    }

    # config file
    cfg_path = Path(cfg.source_path) if cfg.source_path else None
    out["config"] = {
        "path": str(cfg_path) if cfg_path else "",
        "exists": bool(cfg_path and cfg_path.is_file()),
        "source": _config_source(cfg_path) if cfg_path else "built-in defaults",
    }

    # registry
    reg_backend = cfg.registry.backend or "sqlite"
    reg_db = home / "registry.db"
    out["registry"] = {
        "backend": reg_backend,
        "path": str(reg_db) if reg_backend in ("", "sqlite") else "",
        "exists": reg_db.is_file() if reg_backend in ("", "sqlite") else None,
        "sites": _count_sites(reg_db) if reg_backend in ("", "sqlite") else None,
        "source": "from golive.yaml" if cfg.source_path else "default",
    }

    # data layer
    data_backend = cfg.data.backend or "sqlite"
    if data_backend == "sqlite":
        data_db = Path(cfg.data.sqlite_path).expanduser() \
            if cfg.data.sqlite_path else home / "data.db"
        tables, rows = _data_stats(data_db)
        out["data"] = {"backend": "sqlite", "path": str(data_db),
                       "exists": data_db.is_file(),
                       "tables": tables, "rows": rows,
                       "source": "from golive.yaml" if cfg.source_path
                                 else "default"}
    elif data_backend == "postgres":
        # Never echo the DSN itself — it carries a password. Report the env
        # var name and whether it is set, which is what an operator needs.
        dsn_env = cfg.registry.postgres_dsn_env or "GOLIVE_PG_DSN"
        out["data"] = {"backend": "postgres",
                       "path": f"${dsn_env}",
                       "exists": bool(os.environ.get(dsn_env, "").strip()),
                       "tables": None, "rows": None,
                       "source": "from golive.yaml" if cfg.source_path
                                 else "default"}
    elif data_backend == "supabase":
        out["data"] = {"backend": "supabase", "path": cfg.supabase.url,
                       "exists": bool(cfg.supabase.configured),
                       "tables": None, "rows": None,
                       "source": "from golive.yaml"}
    else:
        out["data"] = {"backend": data_backend or "none", "path": "",
                       "exists": None, "tables": None, "rows": None,
                       "source": "from golive.yaml" if cfg.source_path
                                 else "default"}

    # storage
    sites_dir = home / "sites"
    published = 0
    if sites_dir.is_dir():
        published = sum(1 for p in sites_dir.iterdir() if p.is_dir())
    out["storage"] = {
        "backend": cfg.storage.backend or "local",
        "path": str(sites_dir) if cfg.storage.backend in ("", "local") else "",
        "exists": sites_dir.is_dir(),
        "dirs": published,
        "source": "from golive.yaml" if cfg.source_path else "default",
    }

    # skill installs
    out["skill"] = _skill_info()

    # server
    out["server"] = _server_info(port)
    return out


def _skill_info() -> dict:
    try:
        from golive.core import skill_installer as si
        installs = si.find_installed()
        packaged = ""
        try:
            packaged = si.read_skill_meta(si.packaged_skill_dir()).get(
                "version", "")
        except si.SkillInstallError:
            pass
        return {"installs": installs, "count": len(installs),
                "packaged_version": packaged,
                "in_sync": bool(installs) and all(
                    i["version"] == packaged for i in installs)}
    except Exception as e:  # noqa: BLE001 — never let context blow up
        return {"installs": [], "count": 0, "packaged_version": "",
                "in_sync": False, "error": str(e)}


def _server_info(port: int) -> dict:
    """Ask a running server who it is (version drift is a real user report)."""
    import json
    import urllib.error
    import urllib.request

    info = {"port": port, "running": False, "version": "", "home": "",
            "pid": None, "matches_cli": None}
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return info

    from golive import __version__
    info.update(running=True,
                version=str(payload.get("version", "")),
                home=str(payload.get("home", "")),
                pid=payload.get("pid"),
                data_backend=str(payload.get("data_backend", "")))
    info["matches_cli"] = (info["version"] == __version__)
    try:
        info["same_home"] = (Path(info["home"]).resolve()
                             == paths.peek_home().resolve()) \
            if info["home"] else None
    except OSError:  # pragma: no cover
        info["same_home"] = None
    return info


# ── rendering ────────────────────────────────────────────────────────────────

_W = 15   # label column width


def _line(label: str, value: str, source: str = "") -> str:
    tail = f"  ({source})" if source else ""
    return f"{label:<{_W}}{value}{tail}"


def render(info: dict) -> str:
    """The aligned human-readable block. Missing things say so explicitly."""
    L = []
    home = info["home"]
    L.append(_line("GOLIVE_HOME", _fmt(home["path"],
                                       "" if home["exists"] else "(missing)"),
                   home["source_label"]))

    cfg = info["config"]
    if cfg["path"]:
        L.append(_line("config file", _fmt(cfg["path"],
                                           "(exists)" if cfg["exists"]
                                           else "(missing)"), cfg["source"]))
    else:
        L.append(_line("config file", "(none — using built-in defaults)",
                       "default"))

    reg = info["registry"]
    if reg["backend"] in ("", "sqlite"):
        if reg["exists"]:
            n = reg["sites"]
            detail = f"({n} sites)" if n is not None else "(unreadable)"
        else:
            detail = "(missing — created on first publish)"
        L.append(_line("registry", _fmt(reg["path"], detail), reg["source"]))
    else:
        L.append(_line("registry", reg["backend"], reg["source"]))

    d = info["data"]
    if d["backend"] == "sqlite":
        if d["exists"]:
            detail = (f"({d['tables']} tables, {d['rows']} rows)"
                      if d["tables"] is not None else "(unreadable)")
        else:
            detail = "(missing — created on first write)"
        L.append(_line("data backend", f"sqlite → {_fmt(d['path'], detail)}",
                       d["source"]))
    elif d["backend"] == "postgres":
        L.append(_line("data backend",
                       f"postgres → {d['path']}"
                       f" {'(DSN set)' if d['exists'] else '(DSN NOT set)'}",
                       d["source"]))
    elif d["backend"] == "supabase":
        L.append(_line("data backend",
                       f"supabase → {d['path'] or '(url not set)'}"
                       f" {'(configured)' if d['exists'] else '(NOT configured)'}",
                       d["source"]))
    else:
        L.append(_line("data backend", f"{d['backend']} (data layer disabled)",
                       d["source"]))

    st = info["storage"]
    if st["backend"] in ("", "local"):
        detail = f"({st['dirs']} site dirs)" if st["exists"] else "(missing)"
        L.append(_line("storage", _fmt(st["path"] + "/", detail), st["source"]))
    else:
        L.append(_line("storage", st["backend"], st["source"]))

    sk = info["skill"]
    if not sk["count"]:
        L.append(_line("skill", "not installed  "
                                "(golive skill install)", ""))
    else:
        first = sk["installs"][0]
        ver = first["version"] or "(no version)"
        match = "matches CLI" if first["version"] == sk["packaged_version"] \
            else f"packaged is {sk['packaged_version'] or '?'} — run "\
                 "golive skill install --force"
        extra = f", +{sk['count'] - 1} more" if sk["count"] > 1 else ""
        L.append(_line("skill", f"{first['path']} ({ver}, {match}{extra})",
                       first.get("agent", "")))
        for item in sk["installs"][1:]:
            L.append(_line("", f"{item['path']} "
                               f"({item['version'] or 'no version'})"))

    srv = info["server"]
    if not srv["running"]:
        L.append(_line("server", f"not running on port {srv['port']}  "
                                 f"(golive serve --port {srv['port']})"))
    else:
        bits = [f"port {srv['port']}", f"v{srv['version'] or '?'}"]
        if srv.get("pid"):
            bits.append(f"pid {srv['pid']}")
        warn = ""
        if srv["matches_cli"] is False:
            warn = f"  ⚠️  CLI is v{info['golive_version']} — restart the server"
        elif srv.get("same_home") is False:
            warn = (f"  ⚠️  server home is {srv['home']} — "
                    "different from this CLI!")
        L.append(_line("server", "running (" + ", ".join(bits) + ")" + warn))

    return "\n".join(L)
