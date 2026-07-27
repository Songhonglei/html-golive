#!/usr/bin/env python3
"""golive.core.slug_checker — short-slug three-layer validation.

Layers:
  1. Format check   (length, allowed chars)
  2. Reserved list  (built-in system slugs + optional yaml extension)
  3. Occupation     (registry lookup — slug already taken by another site)

All checks are case-insensitive.

Extend the reserved list via golive.yaml::

  slug:
    reserved:
      - internal
      - beta
"""


from __future__ import annotations
import re
from typing import Optional

# ── format rules ─────────────────────────────────────────────────────────────
_MIN_LEN = 2
_MAX_LEN = 32
_VALID_CHAR_RE = re.compile(r'^[a-zA-Z0-9_-]+$')

# ── built-in reserved slugs (system routes & common infra paths) ─────────────
RESERVED_SLUGS = {
    # golive server routes
    "api", "s", "health", "static", "assets", "favicon.ico",
    # common infra / admin paths
    "admin", "login", "logout", "oauth", "sso", "auth",
    "www", "root", "system", "internal", "metrics", "status",
    "robots.txt", "sitemap.xml", ".well-known",
}

_extra_reserved: set = set()


def configure_reserved(slugs) -> None:
    """Extend the reserved list (from golive.yaml)."""
    for s in slugs or []:
        _extra_reserved.add(str(s).strip().lower())


def _all_reserved() -> set:
    return RESERVED_SLUGS | _extra_reserved


# ── layer 1: format ──────────────────────────────────────────────────────────

def check_format(slug: str) -> tuple[bool, str]:
    """Validate slug format. Returns (ok, error_message)."""
    if len(slug) < _MIN_LEN:
        return False, f"短域名长度不能少于 {_MIN_LEN} 个字符（当前：{len(slug)}）"
    if len(slug) > _MAX_LEN:
        return False, f"短域名长度不能超过 {_MAX_LEN} 个字符（当前：{len(slug)}）"
    if not _VALID_CHAR_RE.match(slug):
        invalid_chars = set(c for c in slug if not re.match(r'[a-zA-Z0-9_-]', c))
        return False, (
            f"短域名只能包含字母、数字、下划线（_）和中划线（-），"
            f"不允许使用：{'、'.join(repr(c) for c in sorted(invalid_chars))}"
        )
    return True, ""


# ── layer 2: reserved list ───────────────────────────────────────────────────

def _strip_for_match(slug: str) -> str:
    """Normalize before matching: drop -, _ and digits, keep lowercase letters.

    Prevents bypass via variants like h-e-l-l / h3ll / hell_o.
    """
    return re.sub(r'[^a-z]', '', slug.lower())


def check_reserved(slug: str) -> tuple[bool, str]:
    """Check against reserved slugs. Returns (hit, error_message)."""
    slug_lower = slug.lower()
    if slug_lower in _all_reserved():
        return True, f"短域名 `{slug}` 是系统保留字，请更换"
    # normalized variant match（防连字符/数字变体绕过）
    stripped = _strip_for_match(slug)
    for r in _all_reserved():
        if _strip_for_match(r) and stripped == _strip_for_match(r):
            return True, f"短域名 `{slug}` 与系统保留字 `{r}` 等价，请更换"
    return False, ""


# ── layer 3: occupation (registry) ───────────────────────────────────────────

def check_occupation(slug: str, current_site_id: str,
                     registry=None) -> tuple[bool, str]:
    """Check whether slug is taken by another site.

    registry: a RegistryBackend instance (defaults to the SQLite store).
    Returns (occupied, error_message).
    """
    if registry is None:
        from golive.backends.registry.sqlite_store import SqliteRegistry
        registry = SqliteRegistry()
    site = registry.get_by_slug(slug.lower())
    if site is None:
        return False, ""
    if site["site_id"] == current_site_id:
        return False, ""  # updating own site — keep the slug
    return True, (
        f"短域名 `{slug}` 已被其他站点占用（{site.get('name') or site['site_id']}），"
        f"请更换，或先删除旧站点"
    )


# ── combined API ─────────────────────────────────────────────────────────────

def validate_slug(slug: str, current_site_id: str = "",
                  registry=None) -> tuple[bool, str]:
    """Run all three validation layers. Returns (ok, error_message)."""
    slug = slug.strip().lower()

    ok, msg = check_format(slug)
    if not ok:
        return False, msg

    hit, msg = check_reserved(slug)
    if hit:
        return False, msg

    occupied, msg = check_occupation(slug, current_site_id, registry)
    if occupied:
        return False, msg

    return True, ""


# ── CLI (debug) ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="短域名校验工具（调试用）")
    parser.add_argument("slug", help="要校验的短域名")
    parser.add_argument("--site-id", default="", help="当前站点 site_id（更新场景用）")
    args = parser.parse_args()

    ok, msg = validate_slug(args.slug, args.site_id)
    if ok:
        print(f"✅ 短域名 '{args.slug}' 校验通过，可以使用")
    else:
        print(f"❌ {msg}")
        sys.exit(1)
