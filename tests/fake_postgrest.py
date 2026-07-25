"""tests.fake_postgrest — in-process fake PostgREST server for e2e tests.

Implements just enough of the PostgREST dialect for golive's backends:
  GET    /rest/v1/<table>?col=eq.v&limit=&offset=&order=   select (+count)
  POST   /rest/v1/<table>                                  insert / upsert
  PATCH  /rest/v1/<table>?col=eq.v                         update
  DELETE /rest/v1/<table>?col=eq.v                         delete

Rows live in an in-memory dict per table. Filters support eq. and like.
(with * wildcard). Ordering supports "col.desc,col2.asc" (nulls ignored).
Auto-fills uuid "id" on insert when the table has no explicit pk value.
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlparse


class FakePostgrest:
    def __init__(self):
        self.tables: dict = {}
        self.requests: list = []  # (method, table, params, body) log
        self._server = None
        self._thread = None
        self.port = 0

    # ── data helpers ────────────────────────────────────────────────────────

    def table(self, name: str) -> list:
        return self.tables.setdefault(name, [])

    def _match(self, row: dict, filters: dict) -> bool:
        for col, expr in filters.items():
            if col in ("select", "limit", "offset", "order", "on_conflict"):
                continue
            if "." not in expr:
                return False
            op, val = expr.split(".", 1)
            actual = row.get(col)
            if op == "eq":
                if val == "" and actual in (None, ""):
                    continue
                if str(actual) != val:
                    return False
            elif op == "like":
                import fnmatch
                if not fnmatch.fnmatch(str(actual or ""), val):
                    return False
            else:
                return False
        return True

    def _apply_order(self, rows: list, order: str) -> list:
        for part in reversed([p for p in order.split(",") if p]):
            bits = part.split(".")
            col = bits[0]
            desc = "desc" in bits[1:]
            rows = sorted(rows, key=lambda r: (r.get(col) is None,
                                               str(r.get(col, ""))),
                          reverse=desc)
        return rows

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silent
                pass

            def _table_and_params(self):
                parsed = urlparse(self.path)
                table = parsed.path.rsplit("/", 1)[-1]
                params = dict(parse_qsl(parsed.query))
                return table, params

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                return json.loads(raw) if raw else None

            def _reply(self, code, obj=None, headers=None):
                body = json.dumps(obj, default=str).encode() \
                    if obj is not None else b"[]"
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                table, params = self._table_and_params()
                fake.requests.append(("GET", table, params, None))
                if not self.headers.get("apikey"):
                    self._reply(401, {"message": "No API key found"})
                    return
                rows = [r for r in fake.table(table)
                        if fake._match(r, params)]
                total = len(rows)
                if params.get("order"):
                    rows = fake._apply_order(rows, params["order"])
                off = int(params.get("offset", 0))
                lim = int(params.get("limit", len(rows) or 1))
                page = rows[off:off + lim]
                hdrs = {}
                if "count=exact" in (self.headers.get("Prefer") or ""):
                    end = off + len(page) - 1 if page else off
                    hdrs["Content-Range"] = f"{off}-{end}/{total}"
                self._reply(200, page, hdrs)

            def do_POST(self):  # noqa: N802
                table, params = self._table_and_params()
                body = self._body()
                fake.requests.append(("POST", table, params, body))
                rows = body if isinstance(body, list) else [body]
                prefer = self.headers.get("Prefer") or ""
                out = []
                for row in rows:
                    row = dict(row)
                    row.setdefault("id", str(uuid.uuid4()))
                    # unique check on (model_code,name,user_id) style upsert
                    conflict = params.get("on_conflict", "")
                    merged = False
                    if "merge-duplicates" in prefer and conflict:
                        keys = conflict.split(",")
                        for existing in fake.table(table):
                            if all(existing.get(k) == row.get(k) for k in keys):
                                existing.update(row)
                                out.append(existing)
                                merged = True
                                break
                    if not merged:
                        fake.table(table).append(row)
                        out.append(row)
                if "return=representation" in prefer:
                    self._reply(201, out)
                else:
                    self._reply(201, [])

            def do_PATCH(self):  # noqa: N802
                table, params = self._table_and_params()
                body = self._body() or {}
                fake.requests.append(("PATCH", table, params, body))
                out = []
                for row in fake.table(table):
                    if fake._match(row, params):
                        row.update(body)
                        out.append(row)
                self._reply(200, out)

            def do_DELETE(self):  # noqa: N802
                table, params = self._table_and_params()
                fake.requests.append(("DELETE", table, params, None))
                keep, removed = [], []
                for row in fake.table(table):
                    (removed if fake._match(row, params) else keep).append(row)
                fake.tables[table] = keep
                self._reply(200, removed)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
