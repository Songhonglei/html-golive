"""v0.7.1 — ``golive init``.

The wizard's whole justification is a first-time user who took an
evening to string six documented steps together. So these tests check
the properties that make it trustworthy rather than just "it ran":
it is idempotent, it never blocks without a TTY, it reports *which*
step failed and how to fix it, and it does not claim success until an
HTTP round-trip actually succeeded.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class WizardBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="golive_init_"))
        self.home = self.tmp / "gh"
        self.agent_home = self.tmp / "agent-home"
        (self.agent_home / ".codex").mkdir(parents=True)
        self._saved = {k: os.environ.get(k)
                       for k in ("GOLIVE_HOME", "GOLIVE_CONFIG",
                                 "XDG_CONFIG_HOME", "HOME", "GOLIVE_LANG")}
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
        os.environ["HOME"] = str(self.agent_home)
        os.environ.pop("GOLIVE_CONFIG", None)
        os.environ.pop("GOLIVE_HOME", None)
        os.environ["GOLIVE_LANG"] = "en"
        from golive.i18n import set_language
        set_language("en")
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

    def run_init(self, **kw):
        """Run the wizard non-interactively, capturing its output."""
        from golive.core.init_wizard import InitOptions, run
        buf = io.StringIO()
        opts = InitOptions(stream=buf, interactive=False,
                           no_serve=kw.pop("no_serve", True),
                           port=kw.pop("port", None) or _free_port(),
                           **kw)
        self._reset()
        code, steps = run(opts)
        return code, steps, buf.getvalue()

    @staticmethod
    def step(steps, name):
        for s in steps:
            if s.name == name:
                return s
        raise AssertionError(f"no step named {name}: "
                             f"{[s.name for s in steps]}")


class TestFreshRun(WizardBase):
    def test_zero_to_three_urls(self):
        code, steps, out = self.run_init(home=str(self.home))
        self.assertEqual(code, 0, out)
        for step in steps:
            self.assertTrue(step.ok, f"{step.name}: {step.detail}")
        self.assertIn("/demo-static", out)
        self.assertIn("/demo-crud", out)
        self.assertIn("/admin", out)

    def test_home_is_created_and_populated(self):
        self.run_init(home=str(self.home))
        self.assertTrue(self.home.is_dir())
        self.assertTrue((self.home / "registry.db").is_file())
        self.assertTrue((self.home / "data.db").is_file())
        self.assertTrue((self.home / "sites").is_dir())

    def test_home_choice_is_persisted_for_later_runs(self):
        """The P0 fix: a later CLI in a fresh shell must find the same home."""
        import golive.core.paths as p
        self.run_init(home=str(self.home))
        self.assertEqual(p.read_home_pointer(), self.home)

        os.environ.pop("GOLIVE_HOME", None)
        p.reset_cache()
        self.assertEqual(p.bootstrap_home_env(), "pointer")
        self.assertEqual(Path(os.environ["GOLIVE_HOME"]), self.home)

    def test_demos_are_published(self):
        self.run_init(home=str(self.home))
        self._reset()
        from golive.core import demo
        self.assertEqual(demo.status()["published"], 2)

    def test_skill_lands_in_the_detected_agent(self):
        self.run_init(home=str(self.home))
        installed = self.agent_home / ".codex" / "skills" / "html-golive"
        self.assertTrue((installed / "SKILL.md").is_file(),
                        "the skill should go where the agent actually is")

    def test_every_step_is_narrated(self):
        _c, steps, out = self.run_init(home=str(self.home))
        for name in ("Data directory", "Environment check", "agent skill", "Data layer",
                     "Demo sites", "Start server", "Health check"):
            self.assertIn(name, out)
        self.assertGreaterEqual(len(steps), 7)


class TestIdempotence(WizardBase):
    def test_running_twice_is_safe(self):
        code1, _s, _o = self.run_init(home=str(self.home))
        code2, steps2, out2 = self.run_init(home=str(self.home))
        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0, out2)
        self.assertIn("already exists, reusing", out2)
        for step in steps2:
            self.assertTrue(step.ok, f"{step.name}: {step.detail}")

    def test_second_run_does_not_duplicate_sites(self):
        self.run_init(home=str(self.home))
        self.run_init(home=str(self.home))
        self._reset()
        from golive.backends.factory import get_registry
        slugs = [s["slug"] for s in get_registry().list_all()]
        self.assertEqual(sorted(slugs), ["demo-crud", "demo-static"])

    def test_second_run_keeps_user_data(self):
        self.run_init(home=str(self.home))
        self._reset()
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core import demo
        TemplateStore().create(demo.DEMO_MODEL_CODE, "mine",
                               content={"title": "别删我"})
        self.run_init(home=str(self.home))
        self._reset()
        rows = TemplateStore().list(demo.DEMO_MODEL_CODE)["list"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"]["title"], "别删我")

    def test_second_run_reports_skill_already_current(self):
        self.run_init(home=str(self.home))
        _c, steps, _o = self.run_init(home=str(self.home))
        self.assertIn("Already installed and up to date", self.step(steps, "agent skill").detail)


class TestFlags(WizardBase):
    def test_skip_skill(self):
        _c, steps, out = self.run_init(home=str(self.home), skip_skill=True)
        step = self.step(steps, "agent skill")
        self.assertTrue(step.skipped)
        self.assertIn("--skip-skill", step.detail)
        self.assertFalse((self.agent_home / ".codex" / "skills").exists())

    def test_no_serve_stops_the_server(self):
        port = _free_port()
        code, _s, out = self.run_init(home=str(self.home), port=port,
                                      no_serve=True)
        self.assertEqual(code, 0)
        self.assertIn("--no-serve", out)
        # the port must be free again
        with socket.socket() as s:
            s.settimeout(0.5)
            self.assertNotEqual(s.connect_ex(("127.0.0.1", port)), 0)

    def test_skill_target_overrides_detection(self):
        target = self.tmp / "custom-skills"
        target.mkdir()
        _c, steps, _o = self.run_init(home=str(self.home),
                                      skill_target=str(target))
        self.assertTrue((target / "html-golive" / "SKILL.md").is_file())
        self.assertFalse((self.agent_home / ".codex" / "skills").exists())

    def test_default_home_when_not_specified(self):
        code, steps, out = self.run_init()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.agent_home / ".golive").is_dir())

    def test_env_home_is_honoured_and_labelled(self):
        os.environ["GOLIVE_HOME"] = str(self.home)
        code, _s, out = self.run_init()
        self.assertEqual(code, 0, out)
        self.assertIn("$GOLIVE_HOME", out)
        self.assertTrue((self.home / "registry.db").is_file())

    def test_env_home_is_not_written_to_the_pointer(self):
        """Only an explicit --home is a durable decision."""
        import golive.core.paths as p
        os.environ["GOLIVE_HOME"] = str(self.home)
        self.run_init()
        self.assertIsNone(p.read_home_pointer())


class TestVerification(WizardBase):
    def test_success_is_backed_by_real_http(self):
        port = _free_port()
        _c, steps, _o = self.run_init(home=str(self.home), port=port)
        detail = self.step(steps, "Health check").detail
        self.assertIn("health ✅", detail)
        self.assertIn("demo-static ✅", detail)
        self.assertIn("demo-crud ✅", detail)
        self.assertIn("crud ✅", detail)

    def test_crud_probe_leaves_no_residue(self):
        self.run_init(home=str(self.home))
        self._reset()
        from golive.backends.data.sqlite_store import TemplateStore
        from golive.core import demo
        self.assertEqual(TemplateStore().count(demo.DEMO_MODEL_CODE), 0)

    def test_reuses_an_already_running_golive(self):
        import threading

        self.run_init(home=str(self.home))
        self._reset()
        os.environ["GOLIVE_HOME"] = str(self.home)
        from golive.server.app import make_server
        port = _free_port()
        srv = make_server(host="127.0.0.1", port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

        code, _s, out = self.run_init(home=str(self.home), port=port,
                                      no_serve=False)
        self.assertEqual(code, 0, out)
        self.assertIn("already has golive", out)
        # and the pre-existing server is still up
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=5) as r:
            self.assertEqual(r.status, 200)


class TestFailuresAreReadable(WizardBase):
    def test_unwritable_home_reports_the_step_and_the_fix(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        blocked = self.tmp / "nope"
        blocked.mkdir()
        blocked.chmod(0o500)
        # restore before tearDown removes the tree (cleanups run after it)
        self.addCleanup(lambda: blocked.exists() and blocked.chmod(0o700))
        try:
            code, steps, out = self.run_init(home=str(blocked / "inner"))
        finally:
            blocked.chmod(0o700)
        self.assertEqual(code, 1)
        step = self.step(steps, "Data directory")
        self.assertFalse(step.ok)
        self.assertIn("--home", step.hint)
        self.assertIn("How to fix", out)
        self.assertNotIn("Traceback", out)

    def test_occupied_port_reports_the_step_and_the_fix(self):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]
        self.addCleanup(blocker.close)
        code, steps, out = self.run_init(home=str(self.home), port=port)
        self.assertEqual(code, 1)
        step = self.step(steps, "Environment check")
        self.assertFalse(step.ok)
        self.assertIn("--port", step.hint)
        self.assertNotIn("Traceback", out)

    def test_broken_config_is_reported_not_raised(self):
        self.home.mkdir(parents=True)
        (self.home / "golive.yaml").write_text("data: [unclosed\n",
                                               encoding="utf-8")
        code, steps, out = self.run_init(home=str(self.home))
        self.assertEqual(code, 1)
        self.assertFalse(self.step(steps, "Config file").ok)
        self.assertNotIn("Traceback", out)

    def test_missing_agent_is_skipped_not_failed(self):
        """Most people have no AI agent installed; that is not a failure.

        The step is reported as skipped, init still succeeds, and the rest
        of the bootstrap (demos, data layer) goes ahead as normal.
        """
        shutil.rmtree(self.agent_home / ".codex")
        code, steps, out = self.run_init(home=str(self.home))
        skill_step = self.step(steps, "agent skill")
        self.assertTrue(skill_step.ok, "a missing agent must not fail the step")
        self.assertTrue(getattr(skill_step, "skipped", False),
                        "the step should be marked as skipped")
        self.assertTrue(self.step(steps, "Demo sites").ok)
        self.assertEqual(code, 0, out)


class TestNonInteractive(WizardBase):
    def test_never_prompts_even_with_several_agents(self):
        import builtins
        (self.agent_home / ".claude" / "skills").mkdir(parents=True)
        (self.agent_home / ".cursor").mkdir()
        original = builtins.input

        def explode(*_a, **_kw):  # pragma: no cover — must never run
            raise AssertionError("golive init prompted in a non-TTY run")

        builtins.input = explode
        try:
            code, _s, out = self.run_init(home=str(self.home))
        finally:
            builtins.input = original
        self.assertEqual(code, 0, out)

    def test_multi_agent_choice_is_explained(self):
        (self.agent_home / ".claude" / "skills").mkdir(parents=True)
        _c, steps, _o = self.run_init(home=str(self.home))
        self.assertTrue(self.step(steps, "agent skill").ok)


class TestCliEntry(WizardBase):
    def test_init_via_cli_returns_zero(self):
        import contextlib

        from golive.cli import main
        buf = io.StringIO()
        port = _free_port()
        with contextlib.redirect_stdout(buf):
            code = main(["init", "--home", str(self.home),
                         "--port", str(port), "--no-serve"])
        out = buf.getvalue()
        self.assertEqual(code, 0, out)
        self.assertIn("demo-static", out)

    def test_init_then_context_agree_on_the_home(self):
        """The exact scenario the user hit: two commands, one home."""
        import contextlib

        from golive.cli import main
        port = _free_port()
        with contextlib.redirect_stdout(io.StringIO()):
            main(["init", "--home", str(self.home), "--port", str(port),
                  "--no-serve", "--skip-skill"])

        os.environ.pop("GOLIVE_HOME", None)
        self._reset()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["context", "--json", "--port", str(_free_port())])
        info = json.loads(buf.getvalue())
        self.assertEqual(Path(info["home"]["path"]), self.home.resolve())
        self.assertEqual(info["home"]["source"], "pointer")
        self.assertEqual(info["registry"]["sites"], 2)

    def test_init_then_list_sees_the_demos(self):
        import contextlib

        from golive.cli import main
        port = _free_port()
        with contextlib.redirect_stdout(io.StringIO()):
            main(["init", "--home", str(self.home), "--port", str(port),
                  "--no-serve", "--skip-skill"])
        os.environ.pop("GOLIVE_HOME", None)
        self._reset()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["list"])
        out = buf.getvalue()
        self.assertIn("demo-static", out)
        self.assertIn("demo-crud", out)


if __name__ == "__main__":
    unittest.main()
