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
