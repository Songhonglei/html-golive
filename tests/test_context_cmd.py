"""v0.7.1 — ``golive context``.

Motivating bug report: ``golive list`` showed nothing right after a
successful ``golive publish``. Cause: the shell running the CLI had no
``GOLIVE_HOME`` while the server did, so the two used different
registries. Nothing was broken, nothing printed an error, and there was
no way to see the mismatch. ``golive context`` exists to make provenance
visible — which is why most of these tests assert on the *source*
annotations rather than the paths.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class ContextBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="golive_ctx_"))
        self.home = self.tmp / "gh"
        self._saved = {k: os.environ.get(k)
                       for k in ("GOLIVE_HOME", "GOLIVE_CONFIG",
                                 "XDG_CONFIG_HOME", "HOME")}
        # isolate the pointer file so a developer's real ~/.config is safe
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdgcfg")
        os.environ.pop("GOLIVE_CONFIG", None)
        self._reset()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._reset()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reset(self):
        import golive.core.paths as p
        from golive.config import reset_config
        p.reset_cache()
        reset_config()

    def collect(self, port: int = 65500):
        from golive.core import context as ctx
        self._reset()
        return ctx.collect(port=port)

    def render(self, info=None):
        from golive.core import context as ctx
        return ctx.render(info if info is not None else self.collect())


class TestHomeProvenance(ContextBase):
    def test_env_var_is_labelled_as_such(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        info = self.collect()
        self.assertEqual(info["home"]["source"], "env")
        self.assertIn("$GOLIVE_HOME", info["home"]["source_label"])
        self.assertIn("$GOLIVE_HOME", self.render(info))

    def test_default_is_labelled_as_default(self):
        os.environ.pop("GOLIVE_HOME", None)
        os.environ["HOME"] = str(self.tmp / "fakehome")
        info = self.collect()
        self.assertEqual(info["home"]["source"], "default")
        self.assertIn("default", info["home"]["source_label"])

    def test_pointer_file_is_labelled_and_used(self):
        os.environ.pop("GOLIVE_HOME", None)
        import golive.core.paths as p
        pointer = p.write_home_pointer(self.home)
        info = self.collect()
        self.assertEqual(info["home"]["source"], "pointer")
        self.assertIn(str(pointer), info["home"]["source_label"])
        self.assertEqual(Path(info["home"]["path"]), self.home.resolve())

    def test_env_beats_pointer(self):
        import golive.core.paths as p
        p.write_home_pointer(self.tmp / "pointed")
        os.environ["GOLIVE_HOME"] = str(self.home)
        info = self.collect()
        self.assertEqual(info["home"]["source"], "env")
        self.assertEqual(Path(info["home"]["path"]), self.home.resolve())


class TestMissingIsExplicit(ContextBase):
    def test_brand_new_home_reports_missing_everywhere(self):
        os.environ["GOLIVE_HOME"] = str(self.home)     # never created
        info = self.collect()
        self.assertFalse(info["home"]["exists"])
        self.assertFalse(info["registry"]["exists"])
        self.assertFalse(info["data"]["exists"])
        text = self.render(info)
        self.assertIn("(missing)", text)
        self.assertIn("registry", text)

    def test_no_config_file_says_defaults(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        info = self.collect()
        self.assertEqual(info["config"]["path"], "")
        self.assertIn("built-in defaults", self.render(info))

    def test_collect_creates_nothing(self):
        """Strictly read-only — running context must not mkdir a home."""
        os.environ["GOLIVE_HOME"] = str(self.home)
        self.collect()
        self.assertFalse(self.home.exists(),
                         "golive context must never create GOLIVE_HOME")

    def test_render_never_leaves_a_value_blank(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        for line in self.render().splitlines():
            label, _, rest = line.partition(" ")
            self.assertTrue(rest.strip(), f"empty value on line: {line!r}")


class TestPopulatedHome(ContextBase):
    def setUp(self):
        super().setUp()
        os.environ["GOLIVE_HOME"] = str(self.home)
        self._reset()
        from golive.backends.factory import get_registry
        from golive.backends.data.sqlite_store import TemplateStore
        reg = get_registry()
        reg.create(name="one", slug="one")
        reg.create(name="two", slug="two")
        TemplateStore().create("ctx_demo", "row-1", content={"a": 1})

    def test_registry_row_count_is_reported(self):
        info = self.collect()
        self.assertTrue(info["registry"]["exists"])
        self.assertEqual(info["registry"]["sites"], 2)
        self.assertIn("2 sites", self.render(info))

    def test_data_table_and_row_counts_are_reported(self):
        info = self.collect()
        self.assertEqual(info["data"]["backend"], "sqlite")
        self.assertTrue(info["data"]["exists"])
        self.assertGreaterEqual(info["data"]["tables"], 1)
        self.assertGreaterEqual(info["data"]["rows"], 1)
        self.assertIn("sqlite →", self.render(info))

    def test_storage_dir_count(self):
        info = self.collect()
        self.assertEqual(info["storage"]["backend"], "local")
        self.assertTrue(str(info["storage"]["path"]).endswith("sites"))


class TestConfigProvenance(ContextBase):
    def test_config_in_home_is_labelled(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        self.home.mkdir(parents=True)
        (self.home / "golive.yaml").write_text("data:\n  backend: sqlite\n",
                                               encoding="utf-8")
        info = self.collect()
        self.assertTrue(info["config"]["exists"])
        self.assertIn("GOLIVE_HOME", info["config"]["source"])

    def test_golive_config_env_is_labelled(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        cfg = self.tmp / "custom.yaml"
        cfg.write_text("data:\n  backend: sqlite\n", encoding="utf-8")
        os.environ["GOLIVE_CONFIG"] = str(cfg)
        info = self.collect()
        self.assertIn("$GOLIVE_CONFIG", info["config"]["source"])

    def test_data_backend_none_is_shown_as_disabled(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        self.home.mkdir(parents=True)
        (self.home / "golive.yaml").write_text("data:\n  backend: none\n",
                                               encoding="utf-8")
        info = self.collect()
        self.assertEqual(info["data"]["backend"], "none")
        self.assertIn("data layer disabled", self.render(info))


class TestJsonOutput(ContextBase):
    def _cli(self, *argv):
        from golive.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(argv))
        return code, buf.getvalue()

    def test_json_is_parseable_and_complete(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        code, out = self._cli("context", "--json", "--port", "65501")
        self.assertEqual(code, 0)
        data = json.loads(out)
        for key in ("home", "config", "registry", "data", "storage",
                    "skill", "server", "golive_version"):
            self.assertIn(key, data)
        self.assertIn("source", data["home"])

    def test_text_output_has_one_line_per_topic(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        code, out = self._cli("context", "--port", "65502")
        self.assertEqual(code, 0)
        for label in ("GOLIVE_HOME", "config file", "registry",
                      "data backend", "storage", "skill", "server"):
            self.assertIn(label, out)

    def test_cli_does_not_create_the_home_either(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        self._cli("context", "--port", "65503")
        self.assertFalse(self.home.exists())


class TestServerProbe(ContextBase):
    def test_no_server_is_stated_plainly(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        info = self.collect(port=65504)
        self.assertFalse(info["server"]["running"])
        self.assertIn("not running", self.render(info))

    def test_running_server_reports_version_and_home(self):
        import threading

        os.environ["GOLIVE_HOME"] = str(self.home)
        self._reset()
        from golive import __version__
        from golive.server.app import make_server
        import socket as _s
        sk = _s.socket()
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
        sk.close()
        srv = make_server(host="127.0.0.1", port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

        info = self.collect(port=port)
        self.assertTrue(info["server"]["running"])
        self.assertEqual(info["server"]["version"], __version__)
        self.assertTrue(info["server"]["matches_cli"])
        self.assertTrue(info["server"]["same_home"])
        self.assertIn("running", self.render(info))


class TestHealthEndpointShape(ContextBase):
    """Task E — /health carries enough to diagnose a stale server."""

    def _start(self):
        import socket as _s
        import threading

        from golive.server.app import make_server
        sk = _s.socket()
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
        sk.close()
        srv = make_server(host="127.0.0.1", port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return port

    def test_health_has_every_documented_field(self):
        import urllib.request

        os.environ["GOLIVE_HOME"] = str(self.home)
        self._reset()
        port = self._start()
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=5) as r:
            self.assertEqual(r.status, 200)
            payload = json.loads(r.read().decode("utf-8"))

        from golive import __version__
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], __version__)
        self.assertEqual(Path(payload["home"]).resolve(),
                         self.home.resolve())
        self.assertEqual(payload["data_backend"], "sqlite")
        self.assertEqual(payload["pid"], os.getpid())

    def test_health_is_json_content_type(self):
        import urllib.request

        os.environ["GOLIVE_HOME"] = str(self.home)
        port = self._start()
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=5) as r:
            self.assertIn("application/json", r.headers.get("Content-Type"))


class TestHomePointer(ContextBase):
    def test_write_then_read_roundtrip(self):
        import golive.core.paths as p
        p.write_home_pointer(self.home)
        self.assertEqual(p.read_home_pointer(), self.home)

    def test_missing_pointer_reads_as_none(self):
        import golive.core.paths as p
        self.assertIsNone(p.read_home_pointer())

    def test_empty_pointer_reads_as_none(self):
        import golive.core.paths as p
        f = p.home_pointer_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("   \n", encoding="utf-8")
        self.assertIsNone(p.read_home_pointer())

    def test_bootstrap_exports_pointer_into_env(self):
        import golive.core.paths as p
        os.environ.pop("GOLIVE_HOME", None)
        p.write_home_pointer(self.home)
        self.assertEqual(p.bootstrap_home_env(), "pointer")
        self.assertEqual(Path(os.environ["GOLIVE_HOME"]), self.home)

    def test_bootstrap_never_overrides_an_explicit_env(self):
        import golive.core.paths as p
        os.environ["GOLIVE_HOME"] = str(self.home)
        p.write_home_pointer(self.tmp / "other")
        self.assertEqual(p.bootstrap_home_env(), "env")
        self.assertEqual(Path(os.environ["GOLIVE_HOME"]), self.home)

    def test_bootstrapped_pointer_still_reports_pointer_as_source(self):
        """Exporting into the env must not disguise the real provenance."""
        import golive.core.paths as p
        os.environ.pop("GOLIVE_HOME", None)
        p.write_home_pointer(self.home)
        p.bootstrap_home_env()
        self.assertEqual(p.home_source(), "pointer")

    def test_clear_pointer(self):
        import golive.core.paths as p
        p.write_home_pointer(self.home)
        self.assertTrue(p.clear_home_pointer())
        self.assertFalse(p.clear_home_pointer())


if __name__ == "__main__":
    unittest.main()
