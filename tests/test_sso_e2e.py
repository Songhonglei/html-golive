"""End-to-end SSO: a real login round trip against a real (small) IdP.

The unit tests prove the token verifier is sound in isolation. These prove
it is actually *wired into* the login path — a verifier that is correct but
never called would pass the former and fail the latter.

Each test drives the whole sequence a browser would: /auth/login → the IdP's
authorize endpoint → back to /auth/callback → an authenticated session.
"""
from __future__ import annotations

import http.cookiejar
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests.fake_idp import FakeIdP


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects by hand so each hop can be inspected."""

    def redirect_request(self, *args):
        return None


class OIDCLoginTestBase(unittest.TestCase):
    """Boots an IdP and a golive server wired to it, once per class."""

    @classmethod
    def setUpClass(cls):
        cls.idp_port = free_port()
        cls.app_port = free_port()
        cls.idp = FakeIdP(cls.idp_port).start()
        time.sleep(0.3)

        cls.home = tempfile.mkdtemp(prefix="golive-sso-")
        with open(os.path.join(cls.home, "golive.yaml"), "w") as fh:
            fh.write(
                "admin:\n"
                "  admins: [alice@corp.example]\n"
                "auth:\n"
                "  provider: oidc\n"
                "  oidc:\n"
                "    issuer: http://127.0.0.1:{}\n"
                "    client_id: golive-test\n"
                "    redirect_uri: http://127.0.0.1:{}/auth/callback\n"
                .format(cls.idp_port, cls.app_port)
            )
        cls._env_backup = {k: os.environ.get(k) for k in
                           ("GOLIVE_HOME", "GOLIVE_OIDC_CLIENT_SECRET",
                            "GOLIVE_COOKIE_SECRET")}
        os.environ["GOLIVE_HOME"] = cls.home
        os.environ["GOLIVE_OIDC_CLIENT_SECRET"] = "s3cr3t"
        os.environ["GOLIVE_COOKIE_SECRET"] = "test-cookie-secret"

        import golive.config as cfg_mod
        cfg_mod._current = None

        from golive.server import app as appmod
        cls._app = appmod
        threading.Thread(
            target=lambda: appmod.serve(port=cls.app_port, host="127.0.0.1"),
            daemon=True,
        ).start()

        cls.base = "http://127.0.0.1:{}".format(cls.app_port)
        cls._wait_until_up()

    @classmethod
    def _wait_until_up(cls, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(cls.base + "/health", timeout=2)
                return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("golive server never came up")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.idp.stop()
        except Exception:
            pass
        for k, v in cls._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import golive.config as cfg_mod
        cfg_mod._current = None

    # ── one full browser-like login ────────────────────────────────────
    def login(self):
        """Returns (session_opener, granted: bool)."""
        jar = http.cookiejar.CookieJar()
        follow = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        manual = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar), _NoRedirect)

        authorize_url = None
        try:
            manual.open(self.base + "/auth/login", timeout=8)
        except urllib.error.HTTPError as e:
            authorize_url = e.headers.get("Location", "")
        self.assertTrue(authorize_url, "/auth/login did not redirect to the IdP")

        callback_url = None
        try:
            manual.open(authorize_url, timeout=8)
        except urllib.error.HTTPError as e:
            callback_url = e.headers.get("Location", "")
        self.assertTrue(callback_url, "the IdP did not redirect back")

        try:
            follow.open(callback_url, timeout=10)
        except urllib.error.HTTPError:
            pass  # a rejected login is a valid outcome here

        try:
            resp = follow.open(self.base + "/auth/me", timeout=8)
            return follow, resp.status == 200
        except urllib.error.HTTPError:
            return follow, False


class TestHappyPath(OIDCLoginTestBase):

    def test_anonymous_request_is_unauthorized(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/auth/me", timeout=8)
        self.assertEqual(ctx.exception.code, 401)

    def test_login_redirects_with_state_nonce_and_pkce(self):
        import urllib.parse
        try:
            opener = urllib.request.build_opener(_NoRedirect)
            opener.open(self.base + "/auth/login", timeout=8)
            self.fail("expected a redirect")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location", "")
        params = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        self.assertEqual(params.get("response_type"), ["code"])
        self.assertEqual(params.get("client_id"), ["golive-test"])
        for guard in ("state", "nonce", "code_challenge"):
            self.assertIn(guard, params, "missing {} in the auth request".format(guard))
        self.assertEqual(params.get("code_challenge_method"), ["S256"])

    def test_full_round_trip_creates_a_session(self):
        opener, granted = self.login()
        self.assertTrue(granted, "a valid login was refused")
        body = opener.open(self.base + "/auth/me", timeout=8).read().decode()
        self.assertIn("alice@corp.example", body)

    def test_configured_admin_gets_superadmin_after_sso_login(self):
        """Declared admins must be recognised when they arrive via SSO."""
        opener, granted = self.login()
        self.assertTrue(granted)
        body = opener.open(self.base + "/api/admin/me", timeout=8).read().decode()
        self.assertIn('"superadmin": true', body)


class TestHostileIdP(OIDCLoginTestBase):
    """A compromised or impersonating IdP must not be able to log anyone in."""

    def _login_with(self, flag):
        setattr(self.idp, flag, True)
        try:
            _, granted = self.login()
            return granted
        finally:
            setattr(self.idp, flag, False)

    def test_baseline_honest_idp_is_accepted(self):
        """Guard: the rejections below must not come from a broken flow."""
        _, granted = self.login()
        self.assertTrue(granted)

    def test_token_signed_with_unpublished_key_is_rejected(self):
        self.assertFalse(self._login_with("evil_sign_with_other_key"))

    def test_token_for_another_client_is_rejected(self):
        self.assertFalse(self._login_with("evil_wrong_aud"))

    def test_expired_token_is_rejected(self):
        self.assertFalse(self._login_with("evil_expired"))

    def test_token_without_nonce_is_rejected(self):
        self.assertFalse(self._login_with("evil_drop_nonce"))


if __name__ == "__main__":
    unittest.main()
