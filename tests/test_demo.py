"""v0.7.1 — the two bundled demo sites.

The point of demo-crud is to *prove* the data layer works, so these
tests do the same thing a user would: publish the page, start a real
server, POST a row through the HTTP endpoint the page itself uses, then
read it back. Asserting that a file exists would prove nothing.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class DemoBase(unittest.TestCase):
    def setUp(self):
        os.environ["GOLIVE_LANG"] = "en"
        from golive.i18n import set_language
        set_language("en")
        self.tmp = Path(tempfile.mkdtemp(prefix="golive_demo_"))
        self._saved = {k: os.environ.get(k)
                       for k in ("GOLIVE_HOME", "GOLIVE_CONFIG",
                                 "XDG_CONFIG_HOME")}
        os.environ["GOLIVE_HOME"] = str(self.tmp / "gh")
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
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

    def start_server(self):
        from golive.server.app import make_server
        port = _free_port()
        srv = make_server(host="127.0.0.1", port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return port

    @staticmethod
    def get(url, timeout=5):
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")


class TestPackaging(DemoBase):
    def test_demo_sources_ship_with_the_package(self):
        from golive.core import demo
        d = demo.demo_dir()
        self.assertTrue(d.is_dir(), f"{d} must exist inside the package")
        for spec in demo.list_demos():
            self.assertTrue(spec.path.is_file(), f"missing {spec.filename}")

    def test_pyproject_declares_the_demo_package_data(self):
        """Otherwise the wheel builds fine and ships nothing."""
        root = Path(__file__).resolve().parent.parent
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("resources/demo/*.html", text)

    def test_demo_crud_actually_uses_the_data_layer(self):
        from golive.core import demo
        html = (demo.demo_dir() / "demo-crud.html").read_text(encoding="utf-8")
        for needle in ("TemplateAPI.create", "TemplateAPI.update",
                       "TemplateAPI.delete", "TemplateAPI.listAll"):
            self.assertIn(needle, html, f"demo-crud must call {needle}")

    def test_demo_static_documents_the_commands(self):
        from golive.core import demo
        html = (demo.demo_dir() / "demo-static.html").read_text(
            encoding="utf-8")
        for needle in ("golive publish", "golive serve", "golive context",
                       "golive rollback", "golive skill install"):
            self.assertIn(needle, html)

    def test_demo_pages_are_self_contained(self):
        """No external CDN: the whole point is that this works offline."""
        from golive.core import demo
        for spec in demo.list_demos():
            html = spec.path.read_text(encoding="utf-8")
            self.assertNotIn("http://", html.replace("http://localhost", ""),
                             f"{spec.filename} must not load remote http")
            self.assertNotIn("https://", html,
                             f"{spec.filename} must not load remote https")


class TestInstallRemove(DemoBase):
    def test_install_publishes_both(self):
        from golive.core import demo
        res = demo.install()
        self.assertEqual(res["created"], 2)
        st = demo.status()
        self.assertEqual(st["published"], 2)

    def test_install_is_idempotent(self):
        from golive.core import demo
        first = demo.install()
        second = demo.install()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["refreshed"], 2)
        ids_a = sorted(d["site_id"] for d in first["demos"])
        ids_b = sorted(d["site_id"] for d in second["demos"])
        self.assertEqual(ids_a, ids_b, "re-install must not duplicate sites")

    def test_reinstall_keeps_user_rows(self):
        """Someone typed to-dos in; re-running init must not wipe them."""
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core import demo
        demo.install()
        store = TemplateStore()
        store.create(demo.DEMO_MODEL_CODE, "mine", content={"title": "keep"})
        demo.install()
        self.assertEqual(store.count(demo.DEMO_MODEL_CODE), 1)

    def test_remove_deletes_sites_and_rows(self):
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core import demo
        demo.install()
        store = TemplateStore()
        store.create(demo.DEMO_MODEL_CODE, "t1", content={"title": "x"})
        res = demo.remove()
        self.assertEqual(sorted(res["removed"]),
                         ["demo-crud", "demo-static"])
        self.assertEqual(res["rows_deleted"], 1)
        self.assertEqual(demo.status()["published"], 0)

    def test_remove_can_keep_data(self):
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core import demo
        demo.install()
        store = TemplateStore()
        store.create(demo.DEMO_MODEL_CODE, "t1", content={"title": "x"})
        demo.remove(drop_data=False)
        self.assertEqual(store.count(demo.DEMO_MODEL_CODE), 1)

    def test_remove_when_nothing_installed_is_not_an_error(self):
        from golive.core import demo
        res = demo.remove()
        self.assertEqual(res["removed"], [])
        self.assertEqual(len(res["missing"]), 2)

    def test_data_layer_is_injected_into_demo_crud(self):
        from golive.backends.factory import get_registry, get_storage
        from golive.core import demo
        demo.install()
        site = get_registry().get_by_slug("demo-crud")
        html = get_storage().read(site["site_id"])
        self.assertIn("window.TemplateAPI", html)
        self.assertIn(demo.DEMO_MODEL_CODE, html)
        self.assertIn("/api/data", html)

    def test_static_demo_gets_no_data_layer(self):
        from golive.backends.factory import get_registry, get_storage
        from golive.core import demo
        demo.install()
        site = get_registry().get_by_slug("demo-static")
        html = get_storage().read(site["site_id"])
        self.assertNotIn("SYSTEM INJECTED CODE", html)


class TestServedOverHttp(DemoBase):
    def test_both_demos_are_reachable(self):
        from golive.core import demo
        demo.install()
        port = self.start_server()
        for slug in ("demo-static", "demo-crud"):
            status, body = self.get(f"http://127.0.0.1:{port}/{slug}")
            self.assertEqual(status, 200, slug)
            self.assertGreater(len(body), 500, slug)

    def test_crud_page_carries_a_live_endpoint(self):
        from golive.core import demo
        demo.install()
        port = self.start_server()
        _s, body = self.get(f"http://127.0.0.1:{port}/demo-crud")
        self.assertIn("golive_templates", body)


class TestRealCrudRoundTrip(DemoBase):
    """Write through the same HTTP endpoint the page uses, then read back."""

    def _api(self, port):
        return f"http://127.0.0.1:{port}/api/data/golive_templates"

    def _call(self, url, method="GET", body=None, prefer=""):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if prefer:
            req.add_header("Prefer", prefer)
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None)

    def test_create_read_update_delete_over_http(self):
        from golive.core import demo
        demo.install()
        port = self.start_server()
        api = self._api(port)
        mc = demo.DEMO_MODEL_CODE

        # CREATE — exactly the shape the injected TemplateAPI.create sends
        status, rows = self._call(
            api, "POST",
            [{"model_code": mc, "name": "todo-1",
              "content": {"title": "买牛奶", "done": False}}],
            prefer="return=representation")
        self.assertEqual(status, 201)
        row_id = rows[0]["id"]

        # READ
        q = "?" + urllib.parse.urlencode({"model_code": f"eq.{mc}",
                                          "limit": "20"})
        status, rows = self._call(api + q)
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"]["title"], "买牛奶")
        self.assertFalse(rows[0]["content"]["done"])

        # UPDATE (tick the checkbox)
        one = "?" + urllib.parse.urlencode({"id": f"eq.{row_id}"})
        status, rows = self._call(
            api + one, "PATCH",
            {"content": {"title": "买牛奶", "done": True}},
            prefer="return=representation")
        self.assertEqual(status, 200)
        self.assertTrue(rows[0]["content"]["done"])

        # DELETE
        status, _ = self._call(api + one, "DELETE")
        self.assertEqual(status, 200)
        status, rows = self._call(api + q)
        self.assertEqual(rows, [])

    def test_data_survives_a_server_restart(self):
        """'Refresh the browser and it's still there' — the actual promise."""
        import socket as _s

        from golive.core import demo
        from golive.server.app import make_server
        demo.install()
        mc = demo.DEMO_MODEL_CODE

        def _spin_up():
            sk = _s.socket()
            sk.bind(("127.0.0.1", 0))
            p = sk.getsockname()[1]
            sk.close()
            srv = make_server(host="127.0.0.1", port=p)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return srv, p

        srv1, port1 = _spin_up()
        try:
            self._call(self._api(port1), "POST",
                       [{"model_code": mc, "name": "persist-me",
                         "content": {"title": "还在吗", "done": False}}],
                       prefer="return=representation")
        finally:
            srv1.shutdown()
            srv1.server_close()

        srv2, port2 = _spin_up()
        try:
            q = "?" + urllib.parse.urlencode({"model_code": f"eq.{mc}"})
            status, rows = self._call(self._api(port2) + q)
        finally:
            srv2.shutdown()
            srv2.server_close()
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"]["title"], "还在吗")

    def test_health_check_helper_passes_end_to_end(self):
        from golive.core import demo
        demo.install()
        port = self.start_server()
        checks = demo.health_check(port=port)
        for name, res in checks.items():
            self.assertTrue(res["ok"], f"{name} failed: {res['detail']}")
        self.assertIn("crud", checks)

    def test_health_check_probe_cleans_up_after_itself(self):
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core import demo
        demo.install()
        port = self.start_server()
        demo.health_check(port=port)
        self.assertEqual(TemplateStore().count(demo.DEMO_MODEL_CODE), 0,
                         "the probe row must not be left behind")

    def test_health_check_reports_failure_when_nothing_is_listening(self):
        from golive.core import demo
        checks = demo.health_check(port=_free_port(), timeout=1.0)
        self.assertFalse(checks["health"]["ok"])
        self.assertFalse(checks["crud"]["ok"])


class TestDemoCli(DemoBase):
    def _cli(self, *argv):
        from golive.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(argv))
        return code, buf.getvalue()

    def test_install_then_status_then_remove(self):
        code, out = self._cli("demo", "install")
        self.assertEqual(code, 0)
        self.assertIn("demo-static", out)
        self.assertIn("demo-crud", out)

        code, out = self._cli("demo", "status")
        self.assertEqual(code, 0)
        self.assertIn("2/2", out)

        code, out = self._cli("demo", "remove")
        self.assertEqual(code, 0)
        self.assertIn("Removed", out)

        code, out = self._cli("demo", "status")
        self.assertIn("0/2", out)

    def test_urls_helper(self):
        from golive.core import demo
        u = demo.urls(port=9999)
        self.assertEqual(u["demo-static"], "http://localhost:9999/demo-static")
        self.assertEqual(u["admin"], "http://localhost:9999/admin")


if __name__ == "__main__":
    unittest.main()
