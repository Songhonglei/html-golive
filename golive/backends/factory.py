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
    raise ValueError(f"unknown registry backend: {backend!r} "
                     "(expected sqlite | supabase)")


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
    """TemplateStore when data.backend == supabase, else None."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    if cfg.data.backend == "supabase":
        from golive.backends.data.supabase import TemplateStore
        return TemplateStore()
    return None
