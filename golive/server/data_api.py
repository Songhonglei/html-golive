"""golive.server.data_api — PostgREST-shaped adapter over the SQLite data layer.

Published pages talk to ``window.TemplateAPI``, which speaks PostgREST.
With ``data.backend: supabase`` that traffic goes straight to Supabase.
With the default ``data.backend: sqlite`` there is no remote endpoint —
a browser cannot open ``$GOLIVE_HOME/data.db`` — so ``golive serve``
exposes the same request shape locally:

    GET    /api/data/golive_templates?model_code=eq.kb&order=...&limit=20
    POST   /api/data/golive_templates          (body: row or [row])
    PATCH  /api/data/golive_templates?id=eq.<id>
    DELETE /api/data/golive_templates?id=eq.<id>

Supported query grammar (the subset the injected JS emits):
  ``<col>=eq.<value>`` / ``<col>=like.<prefix>*`` / ``order`` / ``limit``
  / ``offset``. ``Prefer: count=exact`` yields a ``Content-Range`` header;
  ``Prefer: return=representation`` yields the affected rows.

Access model: same as a Supabase project whose anon key is embedded in
the page — anyone who can load the site can call the data layer. Only the
configured templates table is reachable, values are always bound
parameters, and columns are whitelisted (see sqlite_store.FILTERABLE).
Put the server behind auth (GOLIVE_TOKEN / OIDC / reverse proxy) when the
data must not be world-writable.

Transport-free: :func:`handle` takes plain values and returns
``(status, payload, headers)``.
"""

from __future__ import annotations

import json
from typing import Optional

MAX_BODY_BYTES = 256 * 1024
DEFAULT_LIMIT = 20
MAX_LIMIT = 1000

_META_PARAMS = ("order", "limit", "offset", "select")


def _err(status: int, msg: str) -> tuple:
    return status, {"message": msg}, {}


def _first(query: dict, key: str, default: str = "") -> str:
    vals = query.get(key)
    if not vals:
        return default
    return str(vals[0])


def _parse_filters(query: dict) -> tuple:
    """Query dict -> ({col: (op, value)}, error_message)."""
    filters = {}
    for key, vals in (query or {}).items():
        if key in _META_PARAMS or not vals:
            continue
        raw = str(vals[0])
        op, _, value = raw.partition(".")
        if not _:
            return None, f"filter '{key}={raw}' must look like <op>.<value>"
        if op not in ("eq", "like"):
            return None, f"unsupported operator '{op}' on column '{key}'"
        filters[key] = (op, value)
    return filters, ""


def _int_param(query: dict, key: str, default: int, cap: int) -> int:
    try:
        n = int(_first(query, key, str(default)) or default)
    except (TypeError, ValueError):
        return default
    return max(0, min(n, cap))


def _prefer(headers: dict) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == "prefer":
            return str(v).lower()
    return ""


def _store(cfg=None):
    """SQLite TemplateStore when data.backend == sqlite, else None."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    if cfg.data.backend != "sqlite":
        return None
    from golive.backends.data.sqlite_store import TemplateStore
    return TemplateStore()


def handle(method: str, path: str, query: dict, body: bytes,
           headers: Optional[dict] = None, cfg=None) -> tuple:
    """Route an /api/data/* request. Returns (status, payload, headers)."""
    if cfg is None:
        from golive.config import get_config
        cfg = get_config()
    if cfg.data.backend != "sqlite":
        return _err(404, "local data API is only served when "
                         "data.backend is 'sqlite'")

    parts = [p for p in (path or "").strip("/").split("/") if p]
    # parts[0:2] == ['api', 'data']
    rest = parts[2:]
    if len(rest) != 1:
        return _err(404, "expected /api/data/<table>")

    from golive.backends.data.sqlite_store import DEFAULT_TABLE
    allowed = cfg.data.templates_table or DEFAULT_TABLE
    if rest[0] != allowed:
        return _err(404, f"unknown table: {rest[0]}")

    try:
        store = _store(cfg)
    except Exception as e:  # noqa: BLE001 — surface init failure as 500
        return _err(500, f"data backend init failed: {e}")
    if store is None:  # pragma: no cover — guarded above
        return _err(404, "no local data backend")

    filters, ferr = _parse_filters(query)
    if ferr:
        return _err(400, ferr)

    prefer = _prefer(headers)
    try:
        if method == "GET":
            return _select(store, query, filters, prefer)
        if method == "POST":
            return _insert(store, body, prefer)
        if method == "PATCH":
            return _update(store, filters, body, prefer)
        if method == "DELETE":
            return _delete(store, filters, prefer)
    except ValueError as e:      # whitelist violations -> 400
        return _err(400, str(e))
    except Exception as e:       # noqa: BLE001 — backend failure -> 500
        return _err(500, f"data backend error: {e}")
    return _err(405, f"method not allowed: {method}")


def _select(store, query, filters, prefer) -> tuple:
    want_count = "count=exact" in prefer
    limit = _int_param(query, "limit", DEFAULT_LIMIT, MAX_LIMIT) or DEFAULT_LIMIT
    offset = _int_param(query, "offset", 0, 10 ** 9)
    rows, total = store.query(filters, order=_first(query, "order"),
                              limit=limit, offset=offset,
                              want_count=want_count)
    out_headers = {}
    if want_count:
        end = offset + len(rows) - 1
        out_headers["Content-Range"] = \
            f"{offset}-{max(end, offset)}/{total if total is not None else '*'}"
    return 200, rows, out_headers


def _parse_body(body: bytes):
    if not body:
        return None, "empty body"
    if len(body) > MAX_BODY_BYTES:
        return None, "body too large (max 256 KB)"
    try:
        return json.loads(body.decode("utf-8")), ""
    except (ValueError, UnicodeDecodeError):
        return None, "body must be valid UTF-8 JSON"


def _insert(store, body, prefer) -> tuple:
    payload, err = _parse_body(body)
    if err:
        return _err(400, err)
    rows = payload if isinstance(payload, list) else [payload]
    if not all(isinstance(r, dict) for r in rows):
        return _err(400, "body must be a row object or an array of rows")
    if not rows:
        return _err(400, "no rows to insert")
    created = [store.insert_row(r) for r in rows]
    if "return=representation" in prefer:
        return 201, created, {}
    return 201, [], {}


def _update(store, filters, body, prefer) -> tuple:
    if not filters:
        return _err(400, "PATCH requires a filter (e.g. ?id=eq.<id>)")
    payload, err = _parse_body(body)
    if err:
        return _err(400, err)
    if not isinstance(payload, dict):
        return _err(400, "PATCH body must be a JSON object")
    rows = store.update_rows(filters, payload)
    if "return=representation" in prefer:
        return 200, rows, {}
    return 200, [], {}


def _delete(store, filters, prefer) -> tuple:
    if not filters:
        return _err(400, "DELETE requires a filter (e.g. ?id=eq.<id>)")
    n = store.delete_rows(filters)
    if "return=representation" in prefer:
        return 200, [], {}
    return 200, {"deleted": n}, {}
