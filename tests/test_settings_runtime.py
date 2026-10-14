"""Settings writes must affect runtime behavior, not just the admin readback."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from golive.backends.registry.settings_store import SettingsStore
from golive.config import get_config, load_config, reset_config, set_config
from golive.server import admin_api
from golive.server.authz import Identity


class TestSettingsRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        self.yaml = home / "golive.yaml"
        self.yaml.write_text("watermark: {text: inherited}\nserver: {port: 8787}\n")
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GOLIVE_")}
        clean.update(GOLIVE_HOME=str(home), GOLIVE_CONFIG=str(self.yaml))
        env = patch.dict(os.environ, clean, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(reset_config)
        from golive.core.paths import reset_cache
        reset_cache()
        self.addCleanup(reset_cache)
        reset_config()
        set_config(load_config())
        self.store = SettingsStore(home / "registry.db")
        self.root = Identity(email="admin@example.com", is_superadmin=True)

    def call(self, method, body=None, suffix="", identity=None):
        return admin_api.handle(
            method, "/api/admin/settings" + suffix, {},
            json.dumps(body).encode() if body is not None else b"",
            identity or self.root, None, None,
        )

    def test_hot_save_and_reset_restore_runtime_and_file_source(self):
        original = self.yaml.read_text()
        status, result = self.call("PUT", {"watermark.text": "managed"})
        self.assertEqual(status, 200)
        self.assertEqual(result["needs_restart"], [])
        self.assertEqual(get_config().watermark.text, "managed")
        status, data = self.call("GET")
        item = next(x for x in data["settings"]["watermark"] if x["key"] == "watermark.text")
        self.assertEqual((item["value"], item["source"]), ("managed", "database"))
        status, _ = self.call("DELETE", suffix="/watermark.text")
        self.assertEqual(status, 200)
        self.assertEqual(get_config().watermark.text, "inherited")
        _, data = self.call("GET")
        item = next(x for x in data["settings"]["watermark"] if x["key"] == "watermark.text")
        self.assertEqual(item["source"], "yaml")
        self.assertEqual(self.yaml.read_text(), original)

    def test_restart_setting_waits_until_fresh_config_load(self):
        status, result = self.call("PUT", {"server.port": 9876})
        self.assertEqual(status, 200)
        self.assertEqual(result["needs_restart"], ["server.port"])
        self.assertEqual(get_config().server.port, 8787)
        self.assertEqual(load_config().server.port, 9876)

    def test_invalid_batch_changes_nothing(self):
        for bad in (70000, True, "9000", 1.25, float("nan")):
            with self.subTest(value=bad):
                status, _ = self.call("PUT", {"watermark.text": "must not save", "server.port": bad})
                self.assertEqual(status, 400)
                self.assertEqual(self.store.get_flat()["watermark.text"], "")
                self.assertEqual(get_config().watermark.text, "inherited")

    def test_unknown_key_does_not_partially_write_batch(self):
        status, _ = self.call("PUT", {"watermark.text": "not saved", "unknown.key": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(self.store.get_flat()["watermark.text"], "")

    def test_ranges_enums_and_boolean_types_are_validated(self):
        for body in ({"watermark.enabled": "false"}, {"watermark.opacity": 1.5},
                     {"data.backend": "invalid"}, {"auth.provider": "invalid"},
                     {"watermark.color": "256,0,0"}, {"server.host": ""},
                     {"security.llm.base_url": "not a URL"}):
            with self.subTest(body=body):
                self.assertEqual(self.call("PUT", body)[0], 400)

    def test_environment_value_remains_effective_and_is_readonly(self):
        with patch.dict(os.environ, {"GOLIVE_WATERMARK_TEXT": "from environment"}):
            self.assertEqual(self.call("PUT", {"watermark.text": "not applied"})[0], 400)
            _, data = self.call("GET")
            item = next(x for x in data["settings"]["watermark"] if x["key"] == "watermark.text")
            self.assertEqual(item["source"], "environment")
            self.assertTrue(item["readonly"])
            self.assertEqual(item["value"], "from environment")

    def test_non_admin_cannot_modify_or_reset(self):
        user = Identity(email="viewer@example.com")
        self.assertEqual(self.call("PUT", {"watermark.text": "x"}, identity=user)[0], 403)
        self.assertEqual(self.call("DELETE", suffix="/watermark.text", identity=user)[0], 403)

    def test_overrides_loaded_in_a_fresh_process(self):
        import subprocess
        import sys
        self.call("PUT", {"watermark.opacity": 0.25, "server.port": 9876})
        result = subprocess.run(
            [sys.executable, "-c", "from golive.config import get_config; "
             "c=get_config(); print(c.watermark.opacity, c.server.port)"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "0.25 9876")

    def test_cli_serve_uses_saved_port_when_no_argument_is_given(self):
        from argparse import Namespace
        from golive.cli import cmd_serve
        self.call("PUT", {"server.port": 9876})
        set_config(load_config())
        with patch("golive.server.app.serve") as serve:
            cmd_serve(Namespace(serve_action="", host="127.0.0.1", port=None))
        serve.assert_called_once_with(host="127.0.0.1", port=9876)

    def test_cli_restart_honors_saved_port_and_explicit_arguments(self):
        from argparse import Namespace
        from golive.cli import cmd_serve
        self.call("PUT", {"server.port": 9876})
        args = Namespace(serve_action="restart", host="127.0.0.1", port=None, config="")
        with patch("golive.core.service.restart", return_value={
            "state": "started", "port": 9876, "pid": 1,
        }) as restart:
            cmd_serve(args)
            self.assertEqual(restart.call_args.kwargs["port"], 9876)
            args.port = 9998
            cmd_serve(args)
            self.assertEqual(restart.call_args.kwargs["port"], 9998)

    def test_disabling_ai_review_keeps_rule_findings_without_network(self):
        from golive.security.ai_review import review_hits
        self.call("PUT", {"security.ai_review_enabled": False})
        cfg = get_config()
        cfg.security.llm.base_url = "https://example.invalid/v1"
        candidates = [{"type": "weak", "keyword": "sample"}]
        with patch("golive.security.ai_review._call_llm") as request:
            result = review_hits(candidates, cfg)
        request.assert_not_called()
        self.assertEqual(result.kept, candidates)
        self.assertFalse(result.ai_used)
