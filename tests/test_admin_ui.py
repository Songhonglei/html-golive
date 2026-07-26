"""Tests for the M5 admin portal page (golive/server/admin_ui.py + /admin)."""

import json
import os
import re
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


def _fresh_home():
    os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
    os.environ.pop("GOLIVE_TOKEN", None)
    os.environ.pop("GOLIVE_ADMINS", None)
    import golive.core.paths as p
    p._resolved_home = None
    from golive.config import reset_config
    reset_config()


class TestRenderAdminPage(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def _render(self, identity=None):
        from golive.server.admin_ui import render_admin_page
        return render_admin_page(identity)

    def test_key_dom_ids_present(self):
        html = self._render()
        for dom_id in ("view-sites", "view-stats", "view-audit", "drawer",
                       "site-rows", "stat-cards", "audit-rows",
                       "login-gate", "d-maints", "d-snaps", "toast"):
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_no_external_cdn_references(self):
        html = self._render()
        # every http(s):// occurrence must be inside a code string that the
        # page never fetches — the M5 page must not fetch anything remote.
        for m in re.finditer(r'(?:src|href)\s*=\s*["\'](https?:)?//', html):
            self.fail(f"external resource reference found: {m.group(0)}")
        self.assertNotIn("cdn.", html.lower())
        self.assertNotIn("googleapis", html.lower())
        self.assertNotIn("@import", html.lower())

    def test_boot_json_injected_and_escaped(self):
        from golive.server import authz
        evil = authz.Identity(email='x</script><script>alert(1)//@e.com')
        html = self._render(evil)
        # raw close-tag from the payload must not survive into the script
        self.assertNotIn('x</script><script>alert(1)', html)
        self.assertIn("<\\/script>", html)
        # boot JSON parses back
        m = re.search(r"window\.GOLIVE_BOOT = (.*?);</script>", html)
        self.assertIsNotNone(m)
        boot = json.loads(m.group(1).replace("<\\/", "</").replace("<\\!--", "<!--"))
        self.assertTrue(boot["authenticated"])

    def test_version_embedded(self):
        from golive import __version__
        html = self._render()
        self.assertIn(__version__, html)


class TestAdminPageHttp(unittest.TestCase):
    def setUp(self):
        _fresh_home()

    def _start(self):
        from golive.config import reset_config
        reset_config()
        from golive.server.app import make_server
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        srv = make_server(port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.25)
        self.addCleanup(srv.shutdown)
        return port

    def test_admin_page_loopback_200(self):
        port = self._start()
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/admin", timeout=5)
        self.assertEqual(r.status, 200)
        body = r.read().decode("utf-8")
        self.assertIn('id="view-sites"', body)
        self.assertIn("GOLIVE_BOOT", body)
        self.assertIn("text/html", r.headers.get("Content-Type", ""))

    def test_admin_page_remote_denied_without_auth(self):
        port = self._start()
        lan_ip = socket.gethostbyname(socket.gethostname())
        if lan_ip.startswith("127."):
            self.skipTest("no non-loopback interface available")
        # rebind on all interfaces for this case
        from golive.server.app import make_server
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port2 = s.getsockname()[1]
        s.close()
        srv = make_server(host="0.0.0.0", port=port2)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.25)
        self.addCleanup(srv.shutdown)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(f"http://{lan_ip}:{port2}/admin", timeout=5)
        self.assertEqual(cm.exception.code, 401)

    def test_admin_page_served_when_token_auth_on(self):
        """With token auth the shell is served (API still enforces auth)."""
        os.environ["GOLIVE_TOKEN"] = "ui-secret"
        try:
            port = self._start()
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/admin",
                                       timeout=5)
            self.assertEqual(r.status, 200)
            self.assertIn("login-gate", r.read().decode("utf-8"))
            # but the API refuses without the token
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/admin/sites", timeout=5)
            self.assertEqual(cm.exception.code, 401)
        finally:
            os.environ.pop("GOLIVE_TOKEN", None)

    def test_serve_banner_mentions_admin(self):
        """The startup banner prints the portal URL (spec M5-D)."""
        import inspect
        from golive.server import app as app_mod
        src = inspect.getsource(app_mod.serve)
        self.assertIn("/admin", src)


if __name__ == "__main__":
    unittest.main()
