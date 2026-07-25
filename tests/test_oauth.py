"""M3 OAuth/OIDC tests: fake IdP, full auth flow, state/PKCE tampering."""

import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOLIVE_HOME",
                      tempfile.mkdtemp(prefix="golive_test_oauth_"))


class _FakeIdPHandler(BaseHTTPRequestHandler):
    """Minimal OIDC provider: discovery + token + userinfo."""

    base = ""                  # filled after server binds
    expected_verifier = None   # captured challenge for PKCE verification
    last_token_request = None
    fail_token = False

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/.well-known/openid-configuration":
            self._json(200, {
                "issuer": self.base,
                "authorization_endpoint": f"{self.base}/authorize",
                "token_endpoint": f"{self.base}/token",
                "userinfo_endpoint": f"{self.base}/userinfo",
                "end_session_endpoint": f"{self.base}/logout",
            })
        elif path == "/userinfo":
            auth = self.headers.get("Authorization", "")
            if auth != "Bearer fake-access-token":
                self._json(401, {"error": "bad token"})
            else:
                self._json(200, {"sub": "user-42",
                                 "email": "Alice@Example.com",
                                 "name": "Alice"})
        else:
            self._json(404, {"error": "nope"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/token":
            self._json(404, {"error": "nope"})
            return
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        _FakeIdPHandler.last_token_request = form
        if self.fail_token:
            self._json(400, {"error": "invalid_grant"})
            return
        # verify PKCE: sha256(code_verifier) must equal the challenge that
        # was sent to /authorize (stashed by the test through the client)
        verifier = (form.get("code_verifier") or [""])[0]
        if _FakeIdPHandler.expected_verifier is not None:
            digest = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if digest != _FakeIdPHandler.expected_verifier:
                self._json(400, {"error": "invalid_grant",
                                 "error_description": "PKCE mismatch"})
                return
        if (form.get("code") or [""])[0] != "good-code":
            self._json(400, {"error": "invalid_grant"})
            return
        self._json(200, {"access_token": "fake-access-token",
                         "token_type": "Bearer",
                         "id_token": ""})

    def _json(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


class TestOIDCFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idp = HTTPServer(("127.0.0.1", 0), _FakeIdPHandler)
        port = cls.idp.server_address[1]
        _FakeIdPHandler.base = f"http://127.0.0.1:{port}"
        cls.thread = threading.Thread(target=cls.idp.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.idp.shutdown()
        cls.idp.server_close()

    def _provider(self):
        from golive.backends.auth.oauth import OIDCAuth
        return OIDCAuth(issuer=_FakeIdPHandler.base,
                        client_id="test-client",
                        client_secret="test-secret",
                        redirect_uri="http://localhost:8787/auth/callback",
                        cookie_secret="unit-test-secret")

    def _extract_login_params(self, url):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    def test_full_flow(self):
        p = self._provider()
        # 1. login -> authorization URL with state + PKCE challenge
        url = p.begin_login()
        q = self._extract_login_params(url)
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["client_id"], ["test-client"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        state = q["state"][0]
        _FakeIdPHandler.expected_verifier = q["code_challenge"][0]

        # 2. callback: code exchange + userinfo + session cookie
        result = p.complete_login("good-code", state)
        self.assertEqual(result["user"]["email"], "alice@example.com")
        self.assertEqual(result["user"]["sub"], "user-42")
        cookie_value = result["cookie_value"]
        self.assertIn(".", cookie_value)

        # 3. session cookie resolves back to the user
        headers = {"Cookie": f"golive_session={cookie_value}"}
        user = p.session_user(headers)
        self.assertEqual(user["email"], "alice@example.com")
        self.assertTrue(p.verify(headers))
        self.assertEqual(p.identity(headers), "alice@example.com")

        # 4. token endpoint got the client secret + PKCE verifier
        form = _FakeIdPHandler.last_token_request
        self.assertEqual(form["client_secret"], ["test-secret"])
        self.assertIn("code_verifier", form)

        # 5. logout kills the session
        p.logout(headers)
        self.assertIsNone(p.session_user(headers))
        _FakeIdPHandler.expected_verifier = None

    def test_state_tampering_rejected(self):
        from golive.backends.auth.oauth import OIDCError
        p = self._provider()
        p.begin_login()
        with self.assertRaises(OIDCError):
            p.complete_login("good-code", "forged-state")

    def test_state_single_use(self):
        from golive.backends.auth.oauth import OIDCError
        p = self._provider()
        q = self._extract_login_params(p.begin_login())
        state = q["state"][0]
        _FakeIdPHandler.expected_verifier = q["code_challenge"][0]
        p.complete_login("good-code", state)
        with self.assertRaises(OIDCError):   # replay
            p.complete_login("good-code", state)
        _FakeIdPHandler.expected_verifier = None

    def test_pkce_enforced_by_idp(self):
        """A different provider instance (wrong verifier) must fail."""
        from golive.backends.auth.oauth import OIDCError
        p1 = self._provider()
        q1 = self._extract_login_params(p1.begin_login())
        _FakeIdPHandler.expected_verifier = q1["code_challenge"][0]
        # attacker: fresh state from their own instance, different verifier
        p2 = self._provider()
        q2 = self._extract_login_params(p2.begin_login())
        with self.assertRaises(OIDCError):
            p2.complete_login("good-code", q2["state"][0])
        _FakeIdPHandler.expected_verifier = None

    def test_cookie_forgery_rejected(self):
        p = self._provider()
        self.assertIsNone(p.session_user(
            {"Cookie": "golive_session=fakesid.deadbeef"}))
        self.assertIsNone(p.session_user({"Cookie": "golive_session=x"}))
        self.assertIsNone(p.session_user({}))

    def test_session_ttl_expiry(self):
        import time
        p = self._provider()
        p.session_ttl = 1
        q = self._extract_login_params(p.begin_login())
        _FakeIdPHandler.expected_verifier = q["code_challenge"][0]
        result = p.complete_login("good-code", q["state"][0])
        headers = {"Cookie": f"golive_session={result['cookie_value']}"}
        self.assertIsNotNone(p.session_user(headers))
        time.sleep(1.2)
        self.assertIsNone(p.session_user(headers))
        _FakeIdPHandler.expected_verifier = None

    def test_cookie_attributes(self):
        p = self._provider()
        c = p.build_cookie("sid.mac", secure=False)
        self.assertIn("HttpOnly", c)
        self.assertIn("SameSite=Lax", c)
        self.assertNotIn("Secure", c)
        self.assertIn("Secure", p.build_cookie("sid.mac", secure=True))
        p.force_secure_cookie = True
        self.assertIn("Secure", p.build_cookie("sid.mac", secure=False))
        self.assertIn("Max-Age=0", p.clear_cookie())

    def test_end_session_url(self):
        p = self._provider()
        url = p.end_session_url("http://localhost:8787/")
        self.assertIn("/logout", url)
        self.assertIn("post_logout_redirect_uri", url)


class TestServerAuthRoutes(unittest.TestCase):
    """HTTP round-trip: /auth/login|callback|me|logout + protected API."""

    @classmethod
    def setUpClass(cls):
        cls.idp = HTTPServer(("127.0.0.1", 0), _FakeIdPHandler)
        _FakeIdPHandler.base = f"http://127.0.0.1:{cls.idp.server_address[1]}"
        threading.Thread(target=cls.idp.serve_forever, daemon=True).start()

        from golive.backends.auth.oauth import OIDCAuth
        from golive.server.app import make_server

        # token auth intentionally NOT set: /api/sites should accept sessions
        os.environ.pop("GOLIVE_TOKEN", None)
        from golive.config import Config, set_config
        cfg = Config()
        cfg.auth.provider = "token"
        cfg.auth.token = "list-token"
        set_config(cfg)

        cls.srv = make_server(host="127.0.0.1", port=0)
        # wire a real provider manually (config-independent for the test)
        cls.oidc = OIDCAuth(issuer=_FakeIdPHandler.base,
                            client_id="test-client",
                            redirect_uri="http://localhost/auth/callback",
                            cookie_secret="srv-secret")
        from golive.backends.auth.token import TokenAuth
        cls.srv.RequestHandlerClass.oidc = cls.oidc
        cls.srv.RequestHandlerClass.auth = TokenAuth("list-token")
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.idp.shutdown()
        cls.idp.server_close()
        from golive.config import reset_config
        reset_config()

    def _get(self, path, headers=None, follow=False):
        req = urllib.request.Request(self.base + path)
        for k, v in (headers or {}).items():
            req.add_header(k, v)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(
            *([] if follow else [NoRedirect()]))
        try:
            resp = opener.open(req, timeout=10)
            return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_login_redirects_to_idp(self):
        status, headers, _ = self._get("/auth/login")
        self.assertEqual(status, 302)
        self.assertIn("/authorize", headers.get("Location", ""))

    def test_callback_sets_cookie_and_me_works(self):
        status, hdrs, _ = self._get("/auth/login")
        loc = hdrs["Location"]
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)
        _FakeIdPHandler.expected_verifier = q["code_challenge"][0]
        state = q["state"][0]

        status, hdrs, _ = self._get(
            f"/auth/callback?code=good-code&state={state}")
        self.assertEqual(status, 302)
        set_cookie = hdrs.get("Set-Cookie", "")
        self.assertIn("golive_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        cookie = set_cookie.split(";")[0]

        status, _, body = self._get("/auth/me", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["email"], "alice@example.com")

        # protected /api/sites accepts session cookie (no token header)
        status, _, _ = self._get("/api/sites", headers={"Cookie": cookie})
        self.assertEqual(status, 200)

        # logout clears
        status, _, _ = self._get("/auth/logout", headers={"Cookie": cookie})
        self.assertIn(status, (200, 302))
        status, _, _ = self._get("/auth/me", headers={"Cookie": cookie})
        self.assertEqual(status, 401)
        _FakeIdPHandler.expected_verifier = None

    def test_callback_bad_state_rejected(self):
        status, _, body = self._get("/auth/callback?code=good-code&state=evil")
        self.assertEqual(status, 401)
        self.assertIn("state", json.loads(body)["error"])

    def test_api_sites_rejects_anonymous(self):
        status, _, _ = self._get("/api/sites")
        self.assertEqual(status, 401)
        status, _, _ = self._get("/api/sites",
                                 headers={"Authorization": "Bearer list-token"})
        self.assertEqual(status, 200)

    def test_me_without_session_401(self):
        status, _, _ = self._get("/auth/me")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
