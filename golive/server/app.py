"""golive.server.app — built-in static hosting server (stdlib http.server).

Routes:
  GET /                 site index (name + links)
  GET /health           {"status": "ok"}
  GET /api/sites        registry listing (token-protected when GOLIVE_TOKEN set)
  GET /s/<site_id>      site HTML by id
  GET /<slug>           site HTML by slug

Start: ``golive serve [--port 8787] [--host 0.0.0.0]``.

Note: this is a lightweight single-process server intended for personal /
small-team intranet use. Put nginx/caddy in front for TLS or heavy traffic.
"""

import html as html_mod
import http.server
import json
import socket
import socketserver
import sys

from golive.backends.auth.token import get_auth_provider
from golive.backends.registry.sqlite_store import SqliteRegistry
from golive.backends.storage.local import LocalStorage

DEFAULT_PORT = 8787


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class GoliveHandler(http.server.BaseHTTPRequestHandler):
    server_version = "golive/0.1"

    # injected by make_server()
    registry: SqliteRegistry = None
    storage: LocalStorage = None
    auth = None

    # ── helpers ─────────────────────────────────────────────────────────────

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _send_site(self, site: dict):
        try:
            content = self.storage.read(site["site_id"])
        except FileNotFoundError:
            self._send(404, "<h1>404</h1><p>site content missing</p>".encode())
            return
        self._send(200, content.encode("utf-8"))

    def log_message(self, fmt, *args):  # quieter default log
        sys.stderr.write("[serve] %s - %s\n" % (self.address_string(), fmt % args))

    # ── routing ─────────────────────────────────────────────────────────────

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/api/sites":
            if self.auth is not None and not self.auth.verify(dict(self.headers)):
                self._send_json(401, {"error": "unauthorized"})
                return
            sites = self.registry.list_all()
            self._send_json(200, {"sites": sites, "total": len(sites)})
            return

        if path == "/":
            self._send_index()
            return

        if path.startswith("/s/"):
            site_id = path[3:].strip("/")
            site = self.registry.get(site_id)
            if site is None:
                self._send(404, "<h1>404</h1><p>unknown site id</p>".encode())
                return
            self._send_site(site)
            return

        # /<slug>
        slug = path.lstrip("/")
        if "/" not in slug:
            site = self.registry.get_by_slug(slug)
            if site is not None:
                self._send_site(site)
                return

        self._send(404, "<h1>404</h1><p>not found</p>".encode())

    def _send_index(self):
        sites = self.registry.list_all(limit=100)
        rows = []
        for s in sites:
            label = html_mod.escape(s.get("name") or s["site_id"])
            href = f"/{s['slug']}" if s.get("slug") else f"/s/{s['site_id']}"
            rows.append(f'<li><a href="{href}">{label}</a>'
                        f' <small>{s.get("updated_at", "")}</small></li>')
        body = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>golive</title>"
            "<style>body{font-family:system-ui;max-width:640px;margin:48px auto;"
            "padding:0 16px}h1{font-size:22px}li{margin:6px 0}small{color:#999}"
            "</style></head><body>"
            f"<h1>🚀 golive — {len(sites)} site(s)</h1>"
            f"<ul>{''.join(rows) or '<li>暂无站点，试试 golive publish</li>'}</ul>"
            "</body></html>"
        )
        self._send(200, body.encode("utf-8"))


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT):
    from golive.backends.factory import get_registry, get_storage
    handler = GoliveHandler
    handler.registry = get_registry()
    handler.storage = get_storage()
    handler.auth = get_auth_provider()
    return _ThreadingServer((host, port), handler)


def serve(host: str = "0.0.0.0", port: int = DEFAULT_PORT):
    srv = make_server(host, port)
    ip = _lan_ip()
    print(f"🚀 golive serve 已启动")
    print(f"   本机:  http://localhost:{port}/")
    if ip != "127.0.0.1":
        print(f"   局域网: http://{ip}:{port}/")
    print("   Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
    finally:
        srv.server_close()
