"""golive.backends.factory — pick storage/registry backends from config.

CLI and server code call these instead of hard-coding LocalStorage /
SqliteRegistry, so ``golive.yaml`` backend switches take effect everywhere.
"""

from __future__ import annotations


def get_registry(cfg=None):
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    backend = cfg.registry.backend
    if backend in ("", "sqlite"):
        from golive.backends.registry.sqlite_store import SqliteRegistry
        return SqliteRegistry()
    if backend == "supabase":
        from golive.backends.registry.supabase_store import SupabaseRegistry
        return SupabaseRegistry()
    if backend == "postgres":
        from golive.backends.registry.postgres_store import PostgresRegistry
        return PostgresRegistry()
    raise ValueError(f"unknown registry backend: {backend!r} "
                     "(expected sqlite | postgres | supabase)")


def get_storage(cfg=None):
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    backend = cfg.storage.backend
    if backend in ("", "local"):
        from golive.backends.storage.local import LocalStorage
        return LocalStorage()
    if backend == "supabase":
        from golive.backends.storage.supabase_store import SupabaseStorage
        return SupabaseStorage()
    if backend == "s3":
        from golive.backends.storage.s3 import S3Storage
        return S3Storage()
    raise ValueError(f"unknown storage backend: {backend!r} "
                     "(expected local | s3 | supabase)")


def get_template_store(cfg=None):
    """TemplateStore for the configured data backend (None when disabled).

    sqlite (default) -> local $GOLIVE_HOME/data.db, zero configuration
    supabase         -> PostgREST against your Supabase project
    none             -> data layer disabled; callers inject a stub
    """
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    backend = cfg.data.backend
    if backend in ("", "sqlite"):
        from golive.backends.data.sqlite_store import TemplateStore
        return TemplateStore()
    if backend == "supabase":
        from golive.backends.data.supabase import TemplateStore
        return TemplateStore()
    if backend == "postgres":
        from golive.backends.data.postgres_store import TemplateStore
        return TemplateStore()
    if backend == "none":
        return None
    raise ValueError(f"unknown data backend: {backend!r} "
                     "(expected sqlite | supabase | postgres | none)")


# ── data backend capabilities ───────────────────────────────────────────────
#
# Two shapes of data backend exist, and almost every caller cares about the
# shape rather than the specific name:
#
#   server-proxied  (sqlite, postgres) — the server owns the connection and
#       published pages talk to it over the local ``/api/data`` endpoint. No
#       credentials ever reach the browser.
#   page-direct     (supabase) — the page talks to a remote PostgREST service
#       directly, using a URL + anon key embedded in the HTML.
#
# Keep these predicates as the single source of truth; adding a backend then
# means touching this file instead of hunting down every ``== "sqlite"``.

#: Backends the server proxies through ``/api/data``.
SERVER_PROXIED_DATA_BACKENDS = ("", "sqlite", "postgres")


def is_server_proxied_data(cfg=None) -> bool:
    """True when published pages should call the local ``/api/data``."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    return cfg.data.backend in SERVER_PROXIED_DATA_BACKENDS


def data_backend_ready(cfg=None) -> tuple:
    """Can the data layer actually serve pages? -> ``(ready, label)``.

    ``label`` is the backend name for user-facing messages. A server-proxied
    backend is ready as soon as it is selected (SQLite needs no config;
    Postgres surfaces a DSN/driver error on first use, with an actionable
    message). Supabase additionally needs a URL and key in config.
    """
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    backend = cfg.data.backend
    if backend in SERVER_PROXIED_DATA_BACKENDS:
        return True, backend or "sqlite"
    if backend == "supabase":
        return bool(cfg.supabase.configured), "supabase"
    return False, backend or "none"
