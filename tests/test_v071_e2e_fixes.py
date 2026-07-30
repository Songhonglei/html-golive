"""Fixes found while dry-running the v0.7.1 new-user flow end to end.

Two gaps that only show up when you actually walk through what a new
user does, rather than testing each command in isolation:

  1. ``golive init`` left the server bound to the wizard process, so the
     three URLs it proudly printed died the moment the command exited.
  2. ``golive doctor`` always probed the default port, so anyone running
     on a different port was told "not running" while their site was
     perfectly reachable.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest


class TestInitBackgroundOption(unittest.TestCase):
    """`golive init --background` must hand the port to a detached server."""

    def test_init_options_accepts_background(self):
        from golive.core.init_wizard import InitOptions
        opts = InitOptions(background=True)
        self.assertTrue(opts.background)

    def test_background_defaults_off(self):
        """Bare `golive init` keeps the historical foreground behaviour."""
        from golive.core.init_wizard import InitOptions
        self.assertFalse(InitOptions().background)

    def test_cli_exposes_background_flag(self):
        """The flag must be wired into the parser and passed to the wizard."""
        import inspect
        from golive import cli
        src = inspect.getsource(cli)
        self.assertIn('"--background"', src)
        self.assertIn("background=getattr(args", src)

    def test_foreground_hint_mentions_the_alternative(self):
        """A user stuck with an occupied terminal should be told the way out."""
        import inspect
        from golive.core import init_wizard
        src = inspect.getsource(init_wizard)
        self.assertIn("--background", src)


class TestDoctorPortDiscovery(unittest.TestCase):
    """doctor should look where the server actually is."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["GOLIVE_HOME"] = self.home
        import golive.core.paths as p
        p._resolved_home = None

    def _args(self, port):
        import argparse
        return argparse.Namespace(port=port, json=False)

    def _write_pidfile(self, pid, port):
        from golive.core import service
        path = service.pidfile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": pid, "port": port}),
                        encoding="utf-8")

    def test_explicit_port_always_wins(self):
        from golive.cli import _doctor_target_port
        self._write_pidfile(os.getpid(), 19999)
        self.assertEqual(_doctor_target_port(self._args(9123)), 9123)

    def test_falls_back_to_recorded_port(self):
        """The real bug: serve on 18899, doctor said 'not running'."""
        from golive.cli import _doctor_target_port, DEFAULT_SERVE_PORT
        self._write_pidfile(os.getpid(), 18899)
        self.assertEqual(_doctor_target_port(self._args(DEFAULT_SERVE_PORT)),
                         18899)

    def test_default_when_no_pidfile(self):
        from golive.cli import _doctor_target_port, DEFAULT_SERVE_PORT
        self.assertEqual(_doctor_target_port(self._args(DEFAULT_SERVE_PORT)),
                         DEFAULT_SERVE_PORT)

    def test_dead_process_does_not_hijack_the_port(self):
        """A stale pidfile must not send doctor probing a dead port."""
        from golive.cli import _doctor_target_port, DEFAULT_SERVE_PORT
        self._write_pidfile(999999, 18899)     # pid that cannot be alive
        self.assertEqual(_doctor_target_port(self._args(DEFAULT_SERVE_PORT)),
                         DEFAULT_SERVE_PORT)

    def test_recorded_port_none_without_pidfile(self):
        from golive.core import service
        self.assertIsNone(service.recorded_port())

    def test_recorded_port_survives_a_corrupt_pidfile(self):
        from golive.core import service
        path = service.pidfile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json at all", encoding="utf-8")
        self.assertIsNone(service.recorded_port())


if __name__ == "__main__":
    unittest.main()
