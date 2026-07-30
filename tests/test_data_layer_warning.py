"""Startup warning when the in-page data layer is network-reachable."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout


class TestOpenDataLayerWarning(unittest.TestCase):
    """`_warn_open_data_layer` must fire exactly when the data API is
    reachable from the network without any access control."""

    def setUp(self):
        os.environ["GOLIVE_HOME"] = tempfile.mkdtemp()
        os.environ.pop("GOLIVE_TOKEN", None)
        import golive.core.paths as p
        p._resolved_home = None
        import golive.config as cfg_mod
        cfg_mod._current = None

    def _run(self, host):
        from golive.server.app import _warn_open_data_layer
        buf = io.StringIO()
        with redirect_stdout(buf):
            _warn_open_data_layer(host)
        return buf.getvalue()

    def test_warns_when_exposed_without_auth(self):
        out = self._run("0.0.0.0")
        self.assertIn("⚠️", out)
        self.assertIn("/api/data", out)
        self.assertIn("GOLIVE_TOKEN", out)

    def test_silent_on_loopback(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            self.assertEqual(self._run(host), "", f"warned on {host}")

    def test_silent_when_token_configured(self):
        os.environ["GOLIVE_TOKEN"] = "a-shared-token"
        try:
            self.assertEqual(self._run("0.0.0.0"), "")
        finally:
            os.environ.pop("GOLIVE_TOKEN", None)

    def test_silent_when_data_backend_disabled(self):
        home = os.environ["GOLIVE_HOME"]
        cfg_path = os.path.join(home, "golive.yaml")
        with open(cfg_path, "w") as f:
            f.write("data:\n  backend: none\n")
        os.environ["GOLIVE_CONFIG"] = cfg_path
        import golive.config as cfg_mod
        cfg_mod._current = None
        try:
            self.assertEqual(self._run("0.0.0.0"), "")
        finally:
            os.environ.pop("GOLIVE_CONFIG", None)
            cfg_mod._current = None

    def test_never_raises_on_broken_config(self):
        """A warning helper must not be able to break startup."""
        home = os.environ["GOLIVE_HOME"]
        cfg_path = os.path.join(home, "golive.yaml")
        with open(cfg_path, "w") as f:
            f.write("data: [this is not a mapping\n")   # malformed
        os.environ["GOLIVE_CONFIG"] = cfg_path
        import golive.config as cfg_mod
        cfg_mod._current = None
        try:
            self._run("0.0.0.0")     # must not raise
        finally:
            os.environ.pop("GOLIVE_CONFIG", None)
            cfg_mod._current = None


if __name__ == "__main__":
    unittest.main()
