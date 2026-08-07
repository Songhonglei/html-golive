"""golive.server.app — built-in static hosting server (stdlib http.server).

Routes:
  GET  /                          site index (name + links)
  GET  /health                    {"status","version","home","data_backend","pid"}
  GET  /api/sites                 registry listing (token / session protected)
  GET  /s/<site_id>               site HTML by id
  GET  /<slug>                    site HTML by slug
  PUT  /api/sites/<ref>/content   online-editor save (M3, editor_api)
  POST /api/sites/<ref>/upload    online-editor image upload (M3)
  GET  /auth/login                OIDC login redirect (M3, provider=oidc)
  GET  /auth/callback             OIDC callback -> session cookie
  GET  /auth/logout               clear session
  GET  /auth/me                   current session identity JSON
  GET  /admin                     admin portal SPA (M5)
  *    /api/admin/...             admin JSON API (M5, admin_api)
  *    /api/data/<table>          local data layer (M7, sqlite backend)

Start: ``golive serve [--port 8787] [--host 0.0.0.0]``.

Note: this is a lightweight single-process server intended for personal /
small-team intranet use. Put nginx/caddy in front for TLS or heavy traffic.
"""


from __future__ import annotations
import html as html_mod
import http.server
import json
import os
import socket
import socketserver
import sys
import urllib.parse

from golive.backends.auth.token import get_auth_provider
from golive.backends.registry.sqlite_store import SqliteRegistry
from golive.backends.storage.local import LocalStorage
from golive.i18n import t

DEFAULT_PORT = 8787


def _lan_ip() -> str:
    """Best-effort LAN address, for printing a reachable URL.

    This is cosmetic — never let it hold up the server. The UDP socket
    does not actually send anything, but on some networks (notably
    macOS CI runners) ``connect`` can block for a long time without an
    explicit timeout, which would stall startup before we even bind the
    port and leave the user staring at a silent process.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _health_payload() -> dict:
    """Body of ``GET /health``.

    Deliberately more than ``{"status": "ok"}``: a user updated the code,
    left the old server running and spent a while wondering why the page
    behaved like the previous version. ``version`` + ``pid`` + ``home``
    make that diagnosable in one request — ``golive doctor`` and
    ``golive context`` both compare these against the local CLI.

    Shape is a contract; add fields, never rename or remove them.
    """
    from golive import __version__
    payload = {"status": "ok", "version": __version__, "pid": os.getpid()}
    try:
        from golive.core.paths import peek_home
        payload["home"] = str(peek_home())
    except Exception:  # noqa: BLE001 — /health must never 500
        payload["home"] = ""
    try:
        from golive.config import get_config
        payload["data_backend"] = get_config().data.backend or "none"
    except Exception:  # noqa: BLE001
        payload["data_backend"] = ""
    return payload


def _make_oidc():
    """OIDCAuth instance when auth.provider == oidc, else None."""
    from golive.config import get_config
    cfg = get_config()
    if cfg.auth.provider != "oidc":
        return None
    try:
        from golive.backends.auth.oauth import OIDCAuth
        return OIDCAuth()
    except Exception as e:  # noqa: BLE001 — misconfig shouldn't kill serve
        print(t("serve.app.oidc_misconfig", error=e), file=sys.stderr)
        return None


class GoliveHandler(http.server.BaseHTTPRequestHandler):
    server_version = "golive/0.3"

    # injected by make_server()
    registry: SqliteRegistry = None
    storage: LocalStorage = None
    auth = None          # token provider (GOLIVE_TOKEN) for /api/sites
    oidc = None          # OIDCAuth | None

    # ── helpers ─────────────────────────────────────────────────────────────

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8",
              extra_headers: dict = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj, extra_headers: dict = None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", extra_headers)

    def _redirect(self, url: str, extra_headers: dict = None):
        self.send_response(302)
        self.send_header("Location", url)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_site(self, site: dict):
        try:
            content = self.storage.read(site["site_id"])
        except FileNotFoundError:
            self._send(404, "<h1>404</h1><p>site content missing</p>".encode())
            return
        self._send(200, content.encode("utf-8"))

    def _session_user(self):
        if self.oidc is None:
            return None
        return self.oidc.session_user(dict(self.headers))

    def _api_read_allowed(self) -> bool:
        """/api/sites listing: token (when set) or OIDC session.

        With no auth configured at all, listing is only served to loopback
        clients — a remote caller must present a token or an OIDC session.
        (The site registry reveals every site_id/slug; don't expose it to
        the whole network just because the operator skipped auth setup.)
        """
        _auth_is_real = (self.auth is not None
                         and getattr(self.auth, "name", "none") != "none")
        if _auth_is_real and self.auth.verify(dict(self.headers)):
            return True
        if self._session_user() is not None:
            return True
        if not _auth_is_real:
            client_ip = self.client_address[0] if self.client_address else ""
            return client_ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
        return False

    def _is_secure(self) -> bool:
        # honor reverse-proxy TLS termination
        proto = self.headers.get("X-Forwarded-Proto", "")
        return proto.lower() == "https"

    # ── admin portal helpers (M5) ───────────────────────────────────────────

    def _is_loopback(self) -> bool:
        client_ip = self.client_address[0] if self.client_address else ""
        return client_ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _admin_identity(self):
        """Resolve the caller Identity for /admin + /api/admin.

        Sources: OIDC session > static token (=> superadmin). With *no*
        auth configured at all, a loopback caller is treated as
        superadmin — same trust model as _api_read_allowed: the operator
        sitting on the box already owns GOLIVE_HOME.
        """
        from golive.server import authz
        session_user = self._session_user()
        _auth_is_real = (self.auth is not None
                         and getattr(self.auth, "name", "none") != "none")
        token_ok = _auth_is_real and self.auth.verify(dict(self.headers))
        ident = authz.resolve_identity(session_user, token_ok)
        if ident is None and not _auth_is_real and self.oidc is None \
                and self._is_loopback():
            ident = authz.Identity(email="", via_token=True,
                                   is_superadmin=True)
        return ident

    def _handle_admin_api(self, method: str, parsed):
        from golive.server import admin_api
        body = b""
        if method in ("POST", "PATCH", "DELETE", "PUT"):
            body = self._read_body(admin_api.MAX_BODY_BYTES)
            if body is None:
                self._send_json(413, {"error": "body too large"})
                return
        query = urllib.parse.parse_qs(parsed.query)
        status, payload = admin_api.handle(
            method, parsed.path, query, body,
            self._admin_identity(), self.registry, self.storage)
        self._send_json(status, payload)

    def _handle_data_api(self, method: str, parsed):
        """PostgREST-shaped local data endpoint (sqlite data backend)."""
        from golive.server import data_api
        body = b""
        if method in ("POST", "PATCH", "PUT", "DELETE"):
            body = self._read_body(data_api.MAX_BODY_BYTES)
            if body is None:
                self._send_json(413, {"message": "body too large"})
                return
        query = urllib.parse.parse_qs(parsed.query)
        status, payload, headers = data_api.handle(
            method, parsed.path, query, body, dict(self.headers))
        self._send_json(status, payload, extra_headers=headers or None)

    def _read_body(self, limit: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return b""
        if length <= 0 or length > limit:
            return b"" if length <= 0 else None   # None => too large
        remaining = length
        chunks = []
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def log_message(self, fmt, *args):  # quieter default log
        sys.stderr.write("[serve] %s - %s\n" % (self.address_string(), fmt % args))

    # ── routing: GET ────────────────────────────────────────────────────────

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            self._send_json(200, _health_payload())
            return

        if path.startswith("/auth/"):
            self._handle_auth(path, query)
            return

        if path == "/admin":
            self._send_admin_page()
            return

        if path.startswith("/api/admin"):
            self._handle_admin_api("GET", parsed)
            return

        if path.startswith("/api/data"):
            self._handle_data_api("GET", parsed)
            return

        if path == "/api/sites":
            if not self._api_read_allowed():
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

    # ── routing: PUT / POST (editor API, M3) ────────────────────────────────

    def _match_editor_route(self, suffix: str):
        """/api/sites/<ref>/<suffix> -> site dict | None (after sending err)."""
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        # ['api', 'sites', '<ref>', suffix]
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "sites" \
                or parts[3] != suffix:
            return None, False
        ref = urllib.parse.unquote(parts[2])
        site = self.registry.resolve(ref)
        if site is None:
            self._send_json(404, {"error": f"unknown site: {ref}"})
            return None, True
        return site, True

    def do_PUT(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/admin"):
            self._handle_admin_api("PUT", parsed)
            return
        site, matched = self._match_editor_route("content")
        if not matched:
            self._send_json(404, {"error": "not found"})
            return
        if site is None:
            return  # 404 already sent

        from golive.server import editor_api

        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype not in ("text/html", "application/xhtml+xml"):
            self._send_json(415, {"error": "Content-Type must be text/html"})
            return

        ok, code, msg, editor = editor_api.check_editor_auth(
            dict(self.headers), site, session_user=self._session_user())
        if not ok:
            self._send_json(code, {"error": msg})
            return

        body = self._read_body(editor_api.MAX_HTML_BYTES)
        if body is None:
            self._send_json(413, {"error": "HTML too large (10MB limit)"})
            return
        if not body:
            self._send_json(400, {"error": "empty body"})
            return
        try:
            html = body.decode("utf-8")
        except UnicodeDecodeError:
            self._send_json(400, {"error": "body must be UTF-8 HTML"})
            return

        status, payload = editor_api.save_content(
            site, html, editor, self.registry, self.storage)
        self._send_json(status, payload)

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/admin"):
            self._handle_admin_api("POST", parsed)
            return
        if parsed.path.startswith("/api/data"):
            self._handle_data_api("POST", parsed)
            return
        site, matched = self._match_editor_route("upload")
        if not matched:
            self._send_json(404, {"error": "not found"})
            return
        if site is None:
            return

        from golive.server import editor_api

        ok, code, msg, editor = editor_api.check_editor_auth(
            dict(self.headers), site, session_user=self._session_user())
        if not ok:
            self._send_json(code, {"error": msg})
            return

        data = self._read_body(editor_api.MAX_UPLOAD_BYTES)
        if data is None:
            self._send_json(413, {"error": "file too large"})
            return
        if not data:
            self._send_json(400, {"error": "empty body"})
            return
        filename = self.headers.get("X-Filename", "image.png")
        status, payload = editor_api.upload_image(site, data, filename, editor)
        self._send_json(status, payload)

    def do_PATCH(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/admin"):
            self._handle_admin_api("PATCH", parsed)
            return
        if parsed.path.startswith("/api/data"):
            self._handle_data_api("PATCH", parsed)
            return
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/admin"):
            self._handle_admin_api("DELETE", parsed)
            return
        if parsed.path.startswith("/api/data"):
            self._handle_data_api("DELETE", parsed)
            return
        self._send_json(404, {"error": "not found"})

    # ── admin portal page (M5) ──────────────────────────────────────────────

    def _send_admin_page(self):
        """Serve the admin SPA.

        - identity resolved (OIDC session / token header / zero-config
          loopback) -> full page.
        - no identity but OIDC configured -> redirect to /auth/login.
        - no identity but token auth configured -> serve the static shell
          anyway: it contains no data (the JSON API enforces auth on every
          call) and the SPA prompts for the token, sent via X-Golive-Token.
        - no identity, no auth, remote caller -> 401 (mirror of
          _api_read_allowed's loopback-only rule).
        """
        ident = self._admin_identity()
        _auth_is_real = (self.auth is not None
                         and getattr(self.auth, "name", "none") != "none")
        if ident is None and self.oidc is not None:
            self._redirect("/auth/login")
            return
        if ident is None and not _auth_is_real:
            self._send_json(401, {"error": "authentication required "
                                           "(set GOLIVE_TOKEN or OIDC)"})
            return
        from golive.server.admin_ui import render_admin_page
        self._send(200, render_admin_page(ident).encode("utf-8"))

    # ── OIDC auth endpoints (M3) ────────────────────────────────────────────

    def _handle_auth(self, path: str, query: dict):
        if path == "/auth/me":
            user = self._session_user()
            if user is None:
                self._send_json(401, {"error": "no active session"})
            else:
                self._send_json(200, user)
            return

        if self.oidc is None:
            self._send_json(404, {"error": "OAuth is not configured "
                                           "(auth.provider != oidc)"})
            return

        if path == "/auth/login":
            try:
                self._redirect(self.oidc.begin_login())
            except Exception as e:  # noqa: BLE001
                self._send_json(502, {"error": f"OIDC discovery/login failed: {e}"})
            return

        if path == "/auth/callback":
            err = (query.get("error") or [""])[0]
            if err:
                desc = (query.get("error_description") or [""])[0]
                self._send_json(400, {"error": f"IdP error: {err} {desc}".strip()})
                return
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            if not code or not state:
                self._send_json(400, {"error": "missing code/state"})
                return
            try:
                result = self.oidc.complete_login(code, state)
            except Exception as e:  # noqa: BLE001
                self._send_json(401, {"error": f"login failed: {e}"})
                return
            cookie = self.oidc.build_cookie(result["cookie_value"],
                                            secure=self._is_secure())
            self._redirect("/", extra_headers={"Set-Cookie": cookie})
            return

        if path == "/auth/logout":
            self.oidc.logout(dict(self.headers))
            headers = {"Set-Cookie": self.oidc.clear_cookie()}
            end_url = self.oidc.end_session_url()
            if end_url:
                self.send_response(302)
                self.send_header("Location", end_url)
                self.send_header("Set-Cookie", self.oidc.clear_cookie())
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_json(200, {"success": True}, extra_headers=headers)
            return

        self._send_json(404, {"error": "unknown auth endpoint"})

    # ── index page ──────────────────────────────────────────────────────────

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
            f"<ul>{''.join(rows) or '<li>' + t('serve.app.index_empty') + '</li>'}</ul>"
            "</body></html>"
        )
        self._send(200, body.encode("utf-8"))


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        """Bind without the stdlib's reverse-DNS lookup.

        ``HTTPServer.server_bind`` calls ``socket.getfqdn(host)`` purely
        to fill in ``server_name``, which we only ever use for logging.
        On some systems — macOS in particular — resolving a name for
        127.0.0.1 blocks until the resolver gives up, so the server
        appears to hang: the process is alive, nothing is logged, and
        the port never answers. Skip the lookup entirely.
        """
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT):
    from golive.backends.factory import get_registry, get_storage
    handler = GoliveHandler
    handler.registry = get_registry()
    handler.storage = get_storage()
    handler.auth = get_auth_provider()
    handler.oidc = _make_oidc()
    return _ThreadingServer((host, port), handler)


def _warn_open_data_layer(host: str) -> None:
    """Loud warning when the data layer is reachable from the network.

    The in-page data API is deliberately unauthenticated — the browser
    calls it directly, exactly like a Supabase anon key embedded in the
    page. That is fine on loopback, but once the server is bound to a
    routable address anyone who can reach the port can read and write
    the data tables. Say so plainly instead of letting people find out
    the hard way.
    """
    if host in ("127.0.0.1", "::1", "localhost"):
        return
    try:
        from golive.config import get_config
        cfg = get_config()
        if cfg.data.backend in ("", "none"):
            return          # no data layer at all, nothing to expose
        has_token = bool(getattr(cfg.auth, "token", "")) or bool(
            os.environ.get("GOLIVE_TOKEN", ""))
        has_oidc = GoliveHandler.oidc is not None
    except Exception:       # never let a warning break startup
        return
    if has_token or has_oidc:
        return
    print("")
    print(t("serve.app.data_layer_warn_1"))
    print(t("serve.app.data_layer_warn_2"))
    print(t("serve.app.data_layer_warn_3"))
    print(t("serve.app.data_layer_warn_4"))
    print(t("serve.app.data_layer_warn_5"))


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT):
    srv = make_server(host, port)
    loopback = host in ("127.0.0.1", "::1", "localhost")
    print(t("serve.app.started"))
    print(t("serve.app.localhost", port=port))
    if not loopback:
        ip = _lan_ip()
        if ip != "127.0.0.1":
            print(t("serve.app.lan", ip=ip, port=port))
    else:
        print(t("serve.app.loopback_only"))
    if GoliveHandler.oidc is not None:
        print(t("serve.app.oauth", port=port))
    print(t("serve.app.admin", port=port))

    _warn_open_data_layer(host)

    print(t("serve.app.stop"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(t("serve.app.stopped"))
    finally:
        srv.server_close()
