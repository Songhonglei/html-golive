"""Tests for v0.4.1 security hardening: API read protection + serve bind."""
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestApiReadProtection(unittest.TestCase):
    """GET /api/sites must not leak the registry to unauthenticated
    remote callers when no auth is configured."""

    def setUp(self):
        os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
        os.environ.pop("GOLIVE_TOKEN", None)
        os.environ.pop("GOLIVE_EDITOR_TOKEN", None)
        import golive.core.paths as p
        p._resolved_home = None

    def _start(self, host="0.0.0.0"):
        from golive.server.app import make_server
        port = _free_port()
        srv = make_server(host=host, port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.3)
        self.addCleanup(srv.shutdown)
        return port

    def test_loopback_allowed_without_auth(self):
        port = self._start()
        r = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/sites", timeout=5)
        self.assertEqual(r.status, 200)

    def test_remote_denied_without_auth(self):
        port = self._start()
        lan_ip = socket.gethostbyname(socket.gethostname())
        if lan_ip.startswith("127."):
            self.skipTest("no non-loopback interface available")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(
                f"http://{lan_ip}:{port}/api/sites", timeout=5)
        self.assertEqual(cm.exception.code, 401)

    def test_remote_allowed_with_token(self):
        os.environ["GOLIVE_TOKEN"] = "t-0401-secret"
        try:
            port = self._start()
            lan_ip = socket.gethostbyname(socket.gethostname())
            if lan_ip.startswith("127."):
                self.skipTest("no non-loopback interface available")
            req = urllib.request.Request(
                f"http://{lan_ip}:{port}/api/sites",
                headers={"Authorization": "Bearer t-0401-secret"})
            self.assertEqual(urllib.request.urlopen(req, timeout=5).status, 200)
            # and without the token it's still denied
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(
                    f"http://{lan_ip}:{port}/api/sites", timeout=5)
            self.assertEqual(cm.exception.code, 401)
        finally:
            os.environ.pop("GOLIVE_TOKEN", None)


class TestServeDefaultBind(unittest.TestCase):
    def test_make_server_defaults_to_loopback(self):
        os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
        import golive.core.paths as p
        p._resolved_home = None
        from golive.server.app import make_server
        srv = make_server(port=_free_port())
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.server_address[0], "127.0.0.1")

    def test_config_default_host_is_loopback(self):
        os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
        import golive.core.paths as p
        p._resolved_home = None
        from golive.config import load_config
        cfg_path = os.path.join(tempfile.mkdtemp(), "golive.yaml")
        with open(cfg_path, "w") as f:
            f.write("style:\n  default: none\n")
        c = load_config(cfg_path)
        self.assertEqual(c.server.host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
