"""Credential-free descriptions of the active data backend (no connections)."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit


def data_backend_info(cfg, backend=None):
    backend = backend or cfg.data.backend or "sqlite"
    out = {"backend": backend, "location": "", "table": cfg.data.templates_table,
           "table_count_scope": "configured_application_table"}
    if backend in ("mysql", "postgres"):
        from golive.backends.factory import sql_dsn_env
        env = sql_dsn_env(cfg, backend)
        out["dsn_env"] = env
        out["location"] = f"{out['table']} (via ${env})"
        dsn = os.environ.get(env, "").strip()
        try:
            if backend == "mysql":
                from golive.backends._mysql import connection_options
                opts = connection_options(dsn)
                host, port, database = opts["host"], opts["port"], opts["database"]
            elif dsn.startswith(("postgres://", "postgresql://")):
                from urllib.parse import unquote
                url = urlsplit(dsn)
                host, port, database = url.hostname, url.port or 5432, unquote(url.path.lstrip("/"))
            else:
                from psycopg.conninfo import conninfo_to_dict
                opts = conninfo_to_dict(dsn)
                host, port, database = opts.get("host", "localhost"), opts.get("port", 5432), opts.get("dbname", "")
            out.update(host=host, port=port, database=database)
            out["location"] = f"{host}:{port}/{database} · {out['table']} (via ${env})"
        except (ValueError, TypeError, ImportError):
            pass  # Never echo a malformed DSN or driver parse exception.
    elif backend == "sqlite":
        from golive.core.paths import peek_home
        out["location"] = str(Path(cfg.data.sqlite_path).expanduser() if cfg.data.sqlite_path else peek_home() / "data.db")
    elif backend == "supabase":
        try:
            url = urlsplit(cfg.supabase.url)
            # Drop credentials, query and fragment even for invalid config.
            host = url.hostname or ""
            out["location"] = f"{url.scheme}://{host}" + (f":{url.port}" if url.port else "") + f" · {out['table']}"
        except ValueError:
            pass
    return out
