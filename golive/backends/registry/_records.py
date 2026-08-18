"""Field definitions shared by every registry backend.

Six implementations (three backends × manifests and policies) have to agree
on field names, defaults and JSON handling. They agree by importing from
here rather than by looking alike — a divergence between SQLite and Supabase
is invisible until someone switches backend and their watermark silently
turns off.

The row dicts these helpers produce are the public shape: the CLI, the
doctor and the admin API all consume them, so a backend that returns
something else is broken even if its own tests pass.
"""
from __future__ import annotations

import datetime
import json
from typing import Optional

#: Bumped when the manifest row layout changes in a way readers must notice.
#: Distinct from the injection LAYER_SCHEMA in golive.inject.
MANIFEST_SCHEMA_VERSION = 1

#: Where a published page came from. Recorded so the doctor can tell a page
#: golive assembled from a directory apart from one a person hand-edited.
SOURCE_TYPES = ("file", "dir", "zip", "clone", "import", "editor", "demo",
                "unknown")

#: Visibility is stored from 0.9.0 but not enforced until access control
#: lands. Kept as a string so adding a level does not need a migration.
VISIBILITY_LEVELS = ("public", "authenticated", "restricted")
DEFAULT_VISIBILITY = "public"

SECURITY_POLICIES = ("baseline", "strict")
DEFAULT_SECURITY_POLICY = "baseline"


def now() -> str:
    """Timestamp with microseconds, matching the sites table.

    Second precision would let a publish and its manifest write land on the
    same value, which makes "which came first" unanswerable when debugging.
    """
    return datetime.datetime.now().isoformat(timespec="microseconds")


# ── JSON columns ────────────────────────────────────────────────────────────
# SQLite stores TEXT, Postgres and Supabase store JSONB and hand back parsed
# objects. Every backend routes through these two so a caller never has to
# ask which one it is talking to.

def dump_json(value) -> str:
    """Serialise for a TEXT column."""
    return json.dumps(value if value is not None else [],
                      ensure_ascii=False, sort_keys=True)


def load_json(value, fallback=None):
    """Parse a JSON column that may arrive as text or already parsed.

    Returns ``fallback`` for anything unreadable rather than raising: a
    corrupt manifest should show up as a doctor finding, not as a crash that
    stops someone listing their sites.
    """
    if value is None or value == "":
        return [] if fallback is None else fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return [] if fallback is None else fallback


# ── manifest rows ───────────────────────────────────────────────────────────

def manifest_row(site_id: str, content_sha256: str = "",
                 source_type: str = "unknown", injections=None,
                 data_models=None, published_with: str = "",
                 published_at: str = "",
                 schema_version: int = MANIFEST_SCHEMA_VERSION) -> dict:
    """Normalise a manifest into the shape every backend stores and returns."""
    return {
        "site_id": site_id,
        "schema_version": int(schema_version or MANIFEST_SCHEMA_VERSION),
        "content_sha256": content_sha256 or "",
        "source_type": (source_type if source_type in SOURCE_TYPES
                        else "unknown"),
        "injections": injections if injections is not None else [],
        "data_models": data_models if data_models is not None else [],
        "published_with": published_with or "",
        "published_at": published_at or now(),
    }


def manifest_from_db(row: dict) -> Optional[dict]:
    """Turn a raw DB row into the public manifest shape."""
    if not row:
        return None
    return {
        "site_id": row.get("site_id", ""),
        "schema_version": int(row.get("schema_version")
                              or MANIFEST_SCHEMA_VERSION),
        "content_sha256": row.get("content_sha256") or "",
        "source_type": row.get("source_type") or "unknown",
        "injections": load_json(row.get("injections"), []),
        "data_models": load_json(row.get("data_models"), []),
        "published_with": row.get("published_with") or "",
        "published_at": row.get("published_at") or "",
    }


# ── policy rows ─────────────────────────────────────────────────────────────

def policy_defaults(site_id: str = "") -> dict:
    """The policy a site has before anyone sets one.

    Returned instead of None for sites with no row, so callers never branch
    on "has a policy yet" — the absence of a row and an explicit default row
    mean the same thing.
    """
    return {
        "site_id": site_id,
        "visibility": DEFAULT_VISIBILITY,
        "security_policy": DEFAULT_SECURITY_POLICY,
        "watermark_enabled": False,
        "watermark_config": {},
        "updated_at": "",
        "updated_by": "",
    }


def policy_from_db(row: dict, site_id: str = "") -> dict:
    if not row:
        return policy_defaults(site_id)
    vis = row.get("visibility") or DEFAULT_VISIBILITY
    pol = row.get("security_policy") or DEFAULT_SECURITY_POLICY
    return {
        "site_id": row.get("site_id", site_id),
        # An unknown level must not silently widen access: fall back to the
        # strictest known level, not to public.
        "visibility": vis if vis in VISIBILITY_LEVELS else "restricted",
        "security_policy": (pol if pol in SECURITY_POLICIES
                            else DEFAULT_SECURITY_POLICY),
        "watermark_enabled": bool(row.get("watermark_enabled")),
        "watermark_config": load_json(row.get("watermark_config"), {}) or {},
        "updated_at": row.get("updated_at") or "",
        "updated_by": row.get("updated_by") or "",
    }


def content_sha256(html: str) -> str:
    """Hash of the page as published, so drift is detectable later."""
    import hashlib
    if isinstance(html, str):
        html = html.encode("utf-8")
    return hashlib.sha256(html).hexdigest()
