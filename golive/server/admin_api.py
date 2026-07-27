"""golive.server.admin_api — JSON API behind the admin portal (M5).

All endpoints live under ``/api/admin/``; every response is JSON.
Auth: 401 when the caller has no identity at all, 403 when the identity
lacks the required role. Identity resolution is in golive.server.authz.

Endpoints (dispatched from app.py):
  GET    /api/admin/me                          identity + roles
  GET    /api/admin/sites?page=&size=&q=        list (scoped by role)
  GET    /api/admin/sites/<slug>                detail + snapshots
  PATCH  /api/admin/sites/<slug>                edit name/notes/editable
  DELETE /api/admin/sites/<slug>                delete (confirm required)
  POST   /api/admin/sites/<slug>/transfer       transfer ownership
  POST   /api/admin/sites/<slug>/maintainers    add maintainer
  DELETE /api/admin/sites/<slug>/maintainers    remove maintainer
  POST   /api/admin/sites/<slug>/rollback       roll back to a snapshot
  GET    /api/admin/stats                       superadmin dashboard numbers
  GET    /api/admin/audit?page=&size=&slug=&action=   audit trail
  GET    /api/admin/data/models                 data backend model list (M6)
  GET    /api/admin/data/rows?model=&page=&size=&q=   paged template rows
  POST   /api/admin/data/rows                   create row {model, data}
  PATCH  /api/admin/data/rows/<id>              update row {data}
  DELETE /api/admin/data/rows/<id>              delete row

Data endpoints are superadmin-only (the data backend is shared across
sites) and return 400 with a hint when no data backend is configured.

This module is transport-free: ``handle()`` gets plain values and returns
``(status_code, payload_dict)`` — easy to unit-test without sockets.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Optional

from golive.core.audit import read_entries, record
from golive.server import authz

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY_BYTES = 64 * 1024


def _err(status: int, msg: str) -> tuple:
    return status, {"error": msg}


def _who(identity: authz.Identity) -> str:
    return identity.email or "(token)"


def _site_public(site: dict, storage=None) -> dict:
    """Registry row -> API shape (adds size when storage given)."""
    out = {
        "site_id": site["site_id"],
        "name": site.get("name") or "",
        "slug": site.get("slug") or "",
        "owner": site.get("owner") or "",
        "notes": site.get("notes") or "",
        "editable": bool(site.get("editable")),
        "maintainers": list(site.get("maintainers") or []),
        "created_at": site.get("created_at") or "",
        "updated_at": site.get("updated_at") or "",
    }
    if storage is not None:
        out["size"] = _site_size(storage, site["site_id"])
    return out


def _site_size(storage, site_id: str) -> int:
    try:
        p = storage.site_path(site_id)
        return p.stat().st_size if p.exists() else 0
    except Exception:  # noqa: BLE001 — non-local storage / missing file
        try:
            return len(storage.read(site_id).encode("utf-8"))
        except Exception:  # noqa: BLE001
            return 0


def _parse_body(body: bytes) -> Optional[dict]:
    if not body:
        return {}
    try:
        obj = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _valid_email(s: str) -> bool:
    return bool(_EMAIL_RE.match(s or ""))


# ── dispatcher ───────────────────────────────────────────────────────────────

def handle(method: str, path: str, query: dict, body: bytes,
           identity: Optional[authz.Identity],
           registry, storage) -> tuple:
    """Route an /api/admin/* request. Returns (status, payload)."""
    if identity is None:
        return _err(401, "authentication required (OIDC session or token)")

    parts = [p for p in path.strip("/").split("/") if p]
    # parts[0:2] == ['api', 'admin']
    rest = parts[2:]

    if rest == ["me"] and method == "GET":
        return _me(identity, registry)
    if rest == ["sites"] and method == "GET":
        return _list_sites(identity, query, registry, storage)
    if rest == ["stats"] and method == "GET":
        return _stats(identity, registry, storage)
    if rest == ["audit"] and method == "GET":
        return _audit(identity, query)

    if rest[:1] == ["data"]:
        return _data_dispatch(method, rest[1:], query, body, identity)

    if len(rest) >= 2 and rest[0] == "sites":
        slug_ref = rest[1]
        site = registry.resolve(slug_ref)
        if site is None:
            return _err(404, f"unknown site: {slug_ref}")
        sub = rest[2] if len(rest) > 2 else ""

        if not sub:
            if method == "GET":
                return _site_detail(identity, site, storage)
            if method == "PATCH":
                return _site_patch(identity, site, body, registry)
            if method == "DELETE":
                return _site_delete(identity, site, body, registry, storage)
        elif sub == "transfer" and method == "POST":
            return _site_transfer(identity, site, body, registry)
        elif sub == "maintainers" and method in ("POST", "DELETE"):
            return _site_maintainers(identity, site, method, body, registry)
        elif sub == "rollback" and method == "POST":
            return _site_rollback(identity, site, body, registry, storage)

    return _err(404, "unknown admin endpoint")


# ── endpoints ────────────────────────────────────────────────────────────────

def _me(identity: authz.Identity, registry) -> tuple:
    owned, maintained = [], []
    if identity.email:
        for s in registry.list_all(limit=1000):
            role = authz.site_role(identity, s)
            if role == "owner" or \
                    (identity.email == (s.get("owner") or "").strip().lower()):
                owned.append(s.get("slug") or s["site_id"])
            elif identity.email in [str(m).strip().lower()
                                    for m in (s.get("maintainers") or [])]:
                maintained.append(s.get("slug") or s["site_id"])
    return 200, {
        "identity": identity.as_dict(),
        "role": "superadmin" if identity.is_superadmin else "user",
        "owned": owned,
        "maintained": maintained,
    }


def _list_sites(identity, query, registry, storage) -> tuple:
    try:
        page = max(1, int((query.get("page") or ["1"])[0]))
        size = max(1, min(int((query.get("size") or ["20"])[0]), 100))
    except (ValueError, TypeError):
        return _err(400, "page/size must be integers")
    q = ((query.get("q") or [""])[0] or "").strip().lower()

    sites = registry.list_all(limit=10000)
    if not identity.is_superadmin:
        sites = [s for s in sites if authz.can_view(identity, s)]
    if q:
        sites = [s for s in sites
                 if q in (s.get("slug") or "").lower()
                 or q in (s.get("name") or "").lower()]
    total = len(sites)
    start = (page - 1) * size
    rows = [_site_public(s, storage) for s in sites[start:start + size]]
    for s, row in zip(sites[start:start + size], rows):
        row["role"] = authz.site_role(identity, s)
    return 200, {"sites": rows, "total": total, "page": page, "size": size}


def _site_detail(identity, site, storage) -> tuple:
    if not authz.can_view(identity, site):
        return _err(403, "not owner/maintainer of this site")
    out = _site_public(site, storage)
    out["role"] = authz.site_role(identity, site)
    try:
        snaps = storage.list_snapshots(site["site_id"])
        out["snapshots"] = [{"ts": s["ts"], "size": s.get("size", 0)}
                            for s in snaps]
    except Exception:  # noqa: BLE001
        out["snapshots"] = []
    return 200, out


def _site_patch(identity, site, body, registry) -> tuple:
    if not authz.can_edit_meta(identity, site):
        return _err(403, "owner or superadmin required")
    data = _parse_body(body)
    if data is None:
        return _err(400, "body must be a JSON object")
    allowed = {"name", "notes", "editable"}
    unknown = set(data) - allowed
    if unknown:
        return _err(400, f"unknown fields: {', '.join(sorted(unknown))}")
    if not data:
        return _err(400, "nothing to update (name/notes/editable)")

    changes = {}
    if "name" in data:
        if not isinstance(data["name"], str) or len(data["name"]) > 200:
            return _err(400, "name must be a string (<=200 chars)")
        changes["name"] = data["name"]
    if "notes" in data:
        if not isinstance(data["notes"], str) or len(data["notes"]) > 2000:
            return _err(400, "notes must be a string (<=2000 chars)")
        changes["notes"] = data["notes"]
    if "editable" in data and not isinstance(data["editable"], bool):
        return _err(400, "editable must be a boolean")

    site_id = site["site_id"]
    if "name" in changes or "notes" in changes:
        registry.update(site_id, name=changes.get("name"),
                        notes=changes.get("notes"))
    if "editable" in data:
        registry.set_editable(site_id, data["editable"])
        changes["editable"] = data["editable"]

    record(_who(identity), "site.update", site.get("slug") or site_id,
           {"fields": sorted(changes)})
    return 200, {"success": True,
                 "site": _site_public(registry.get(site_id))}


def _site_delete(identity, site, body, registry, storage) -> tuple:
    if not authz.can_delete(identity, site):
        return _err(403, "owner or superadmin required")
    data = _parse_body(body)
    if data is None:
        return _err(400, "body must be a JSON object")
    ref = site.get("slug") or site["site_id"]
    if data.get("confirm") != ref:
        return _err(400, f'deletion requires body {{"confirm": "{ref}"}}')
    try:
        storage.delete(site["site_id"])
    except Exception:  # noqa: BLE001 — registry cleanup still proceeds
        pass
    registry.delete(site["site_id"])
    record(_who(identity), "site.delete", ref,
           {"site_id": site["site_id"], "name": site.get("name") or ""})
    return 200, {"success": True, "deleted": ref}


def _site_transfer(identity, site, body, registry) -> tuple:
    if not authz.can_transfer(identity, site):
        return _err(403, "owner or superadmin required")
    data = _parse_body(body)
    if data is None:
        return _err(400, "body must be a JSON object")
    to = str(data.get("to") or "").strip().lower()
    if not _valid_email(to):
        return _err(400, "body.to must be a valid email")
    old = (site.get("owner") or "").strip().lower()
    registry.set_owner(site["site_id"], to)
    record(_who(identity), "site.transfer",
           site.get("slug") or site["site_id"], {"from": old, "to": to})
    return 200, {"success": True, "owner": to, "previous_owner": old}


def _site_maintainers(identity, site, method, body, registry) -> tuple:
    if not authz.can_manage_maintainers(identity, site):
        return _err(403, "owner or superadmin required")
    data = _parse_body(body)
    if data is None:
        return _err(400, "body must be a JSON object")
    email = str(data.get("email") or "").strip().lower()
    if not _valid_email(email):
        return _err(400, "body.email must be a valid email")
    if method == "POST":
        maintainers = registry.add_maintainer(site["site_id"], email)
        action = "maintainer.add"
    else:
        maintainers = registry.remove_maintainer(site["site_id"], email)
        action = "maintainer.remove"
    record(_who(identity), action, site.get("slug") or site["site_id"],
           {"email": email})
    return 200, {"success": True, "maintainers": maintainers}


def _site_rollback(identity, site, body, registry, storage) -> tuple:
    if not authz.can_rollback(identity, site):
        return _err(403, "owner/maintainer/superadmin required")
    data = _parse_body(body)
    if data is None:
        return _err(400, "body must be a JSON object")
    ts = str(data.get("snapshot") or "").strip()
    try:
        storage.rollback(site["site_id"], ts)
    except FileNotFoundError as e:
        return _err(404, str(e))
    registry.touch(site["site_id"])
    record(_who(identity), "site.rollback",
           site.get("slug") or site["site_id"],
           {"snapshot": ts or "(latest)"})
    return 200, {"success": True, "snapshot": ts or "(latest)"}


def _stats(identity, registry, storage) -> tuple:
    if not identity.is_superadmin:
        return _err(403, "superadmin required")
    sites = registry.list_all(limit=100000)
    sized = [(s, _site_size(storage, s["site_id"])) for s in sites]
    total_bytes = sum(n for _, n in sized)

    cutoff = (datetime.datetime.now()
              - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    recent = sum(1 for s in sites if (s.get("updated_at") or "") >= cutoff)

    top = sorted(sized, key=lambda t: t[1], reverse=True)[:10]
    top_rows = [{"slug": s.get("slug") or s["site_id"],
                 "name": s.get("name") or "", "size": n} for s, n in top]
    editable = sum(1 for s in sites if s.get("editable"))
    return 200, {
        "total_sites": len(sites),
        "total_bytes": total_bytes,
        "updated_last_7d": recent,
        "editable_sites": editable,
        "top_sites": top_rows,
    }


def _audit(identity, query) -> tuple:
    if not identity.is_superadmin:
        return _err(403, "superadmin required")
    try:
        page = int((query.get("page") or ["1"])[0])
        size = int((query.get("size") or ["50"])[0])
    except (ValueError, TypeError):
        return _err(400, "page/size must be integers")
    slug = ((query.get("slug") or [""])[0] or "").strip()
    action = ((query.get("action") or [""])[0] or "").strip()
    return 200, read_entries(page=page, size=size, slug=slug, action=action)


# ── data management (M6) ─────────────────────────────────────────────────────

_DATA_HINT = ("set data.backend: supabase plus supabase.url and an API key "
              "in golive.yaml (see golive.example.yaml), then restart serve")
_MAX_ROW_JSON_BYTES = 256 * 1024


def _data_store():
    """Return a TemplateStore or None when no data backend is configured."""
    from golive.config import get_config
    cfg = get_config()
    if cfg.data.backend != "supabase" or not cfg.supabase.configured:
        return None
    from golive.backends.data.supabase import TemplateStore
    return TemplateStore()


def _data_dispatch(method, rest, query, body, identity) -> tuple:
    """Route /api/admin/data/*. superadmin only; 400 without a backend."""
    if not identity.is_superadmin:
        return _err(403, "superadmin required")
    try:
        store = _data_store()
    except Exception as e:  # noqa: BLE001 — config/backend init failure
        return 400, {"error": f"data backend init failed: {e}",
                     "hint": _DATA_HINT}
    if store is None:
        return 400, {"error": "no data backend configured",
                     "hint": _DATA_HINT}

    try:
        if rest == ["models"] and method == "GET":
            return _data_models(store)
        if rest == ["rows"] and method == "GET":
            return _data_rows_list(store, query)
        if rest == ["rows"] and method == "POST":
            return _data_row_create(store, body, identity)
        if len(rest) == 2 and rest[0] == "rows":
            if method == "PATCH":
                return _data_row_update(store, rest[1], body, identity)
            if method == "DELETE":
                return _data_row_delete(store, rest[1], identity)
    except Exception as e:  # noqa: BLE001 — PostgREST/network errors -> 502
        return 502, {"error": f"data backend error: {e}"}
    return _err(404, "unknown admin endpoint")


def _data_models(store) -> tuple:
    return 200, {"models": store.list_models()}


def _data_rows_list(store, query) -> tuple:
    model = ((query.get("model") or [""])[0] or "").strip()
    if not model:
        return _err(400, "query param 'model' is required")
    try:
        page = max(1, int((query.get("page") or ["1"])[0]))
        size = max(1, min(int((query.get("size") or ["20"])[0]), 200))
    except (ValueError, TypeError):
        return _err(400, "page/size must be integers")
    q = ((query.get("q") or [""])[0] or "").strip()
    out = store.search(model, q=q, page_no=page, page_size=size)
    return 200, {"model": model, "total": out.get("total", 0),
                 "rows": out.get("list", []), "page": page, "size": size}


def _row_payload(data) -> tuple:
    """Validate the ``data`` field of a row body. Returns (err, row_dict)."""
    if not isinstance(data, dict):
        return _err(400, "body.data must be a JSON object"), None
    try:
        blob = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return _err(400, "body.data is not JSON-serializable"), None
    if len(blob.encode("utf-8")) > _MAX_ROW_JSON_BYTES:
        return _err(400, "body.data too large (max 256 KB)"), None
    return None, data


def _data_row_create(store, body, identity) -> tuple:
    payload = _parse_body(body)
    if payload is None:
        return _err(400, "body must be a JSON object")
    model = str(payload.get("model") or "").strip()
    if not model or len(model) > 200:
        return _err(400, "body.model is required (string, <=200 chars)")
    err, data = _row_payload(payload.get("data"))
    if err:
        return err
    name = str(payload.get("name") or data.get("name") or "").strip() \
        or f"row-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    row = store.create(model, name, content=data,
                       description=str(payload.get("description") or ""))
    record(_who(identity), "data.create", "",
           {"model": model, "id": row.get("id") or "", "name": name})
    return 200, {"success": True, "row": row}


def _data_row_update(store, row_id, body, identity) -> tuple:
    payload = _parse_body(body)
    if payload is None:
        return _err(400, "body must be a JSON object")
    patch = {}
    if "data" in payload:
        err, data = _row_payload(payload.get("data"))
        if err:
            return err
        patch["content"] = data
    for k in ("name", "description", "version"):
        if k in payload:
            v = payload[k]
            if not isinstance(v, str) or len(v) > 500:
                return _err(400, f"body.{k} must be a string (<=500 chars)")
            patch[k] = v
    if not patch:
        return _err(400, "nothing to update (data/name/description/version)")
    try:
        row = store.update(row_id, patch)
    except KeyError:
        return _err(404, f"row not found: {row_id}")
    record(_who(identity), "data.update", "",
           {"model": row.get("model_code") or "", "id": row_id,
            "fields": sorted(patch)})
    return 200, {"success": True, "row": row}


def _data_row_delete(store, row_id, identity) -> tuple:
    row = store.get(row_id)
    if row is None:
        return _err(404, f"row not found: {row_id}")
    store.delete(row_id)
    record(_who(identity), "data.delete", "",
           {"model": row.get("model_code") or "", "id": row_id,
            "name": row.get("name") or ""})
    return 200, {"success": True, "deleted": row_id}
