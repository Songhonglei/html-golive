"""Config keys that are silently ignored are a support burden.

Someone who writes `admins:` at the top level (a reasonable guess) gets a
server that starts fine, accepts their file, and then denies them access.
These tests pin the warnings that make that mistake self-evident.
"""
from __future__ import annotations

import unittest

from golive.config import check_unknown_sections, KNOWN_SECTIONS


class TestUnknownSectionWarnings(unittest.TestCase):

    def test_valid_config_is_quiet(self):
        raw = {"server": {"port": 8787}, "auth": {"provider": "token"},
               "admin": {"admins": ["a@x.com"]}}
        self.assertEqual(check_unknown_sections(raw), [])

    def test_every_documented_section_is_accepted(self):
        raw = {name: {} for name in KNOWN_SECTIONS}
        self.assertEqual(check_unknown_sections(raw), [])

    def test_misplaced_admins_names_the_right_home(self):
        [warning] = check_unknown_sections({"admins": ["a@x.com"]})
        self.assertIn("admin.admins", warning)

    def test_misplaced_port_names_the_right_home(self):
        [warning] = check_unknown_sections({"port": 9000})
        self.assertIn("server.port", warning)

    def test_misplaced_auth_keys_name_the_right_home(self):
        for key, expected in (("token", "auth.token"),
                              ("provider", "auth.provider"),
                              ("oidc", "auth.oidc")):
            [warning] = check_unknown_sections({key: "x"})
            self.assertIn(expected, warning, "no fix offered for '{}'".format(key))

    def test_genuinely_unknown_key_is_reported_without_a_guess(self):
        [warning] = check_unknown_sections({"frobnicate": True})
        self.assertIn("frobnicate", warning)
        self.assertNotIn("move it to", warning)

    def test_extension_keys_are_left_alone(self):
        """`x-` and `_` prefixes are conventional escape hatches."""
        self.assertEqual(check_unknown_sections({"x-notes": 1, "_local": 2}), [])

    def test_bad_input_does_not_raise(self):
        for junk in (None, [], "text", 42):
            self.assertEqual(check_unknown_sections(junk), [])

    def test_warnings_do_not_block_loading(self):
        """A stray key is a warning, never a fatal error."""
        raw = {"frobnicate": True, "admin": {"admins": ["a@x.com"]}}
        self.assertEqual(len(check_unknown_sections(raw)), 1)


if __name__ == "__main__":
    unittest.main()
