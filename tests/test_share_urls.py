"""Tests for golive.core.urls — shareable URL computation.

Covers:
  - public_base configured → that URL wins, no LAN probe
  - public_base with trailing slash / path prefix → normalised
  - no public_base → LAN IP used
  - LAN probe failure → localhost fallback, no exception
  - server bound to 127.0.0.1 → needs_host_flag=True
  - server bound to 0.0.0.0 → needs_host_flag=False
  - format_share_message produces sensible output in each mode
  - site_path normalisation (leading slash)
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest import mock

from golive.core.urls import share_urls, format_share_message


@dataclass
class _ServerCfg:
    """Minimal stand-in for golive.config.ServerConfig."""
    host: str = "0.0.0.0"
    port: int = 8787
    public_base: str = ""


class TestPublicBaseWins(unittest.TestCase):
    def test_public_base_used_when_configured(self):
        cfg = _ServerCfg(public_base="https://pages.example.com")
        urls = share_urls("/s/abc123", 8787, cfg)
        self.assertEqual(urls["public"], "https://pages.example.com/s/abc123")
        self.assertIsNone(urls["lan"])
        self.assertFalse(urls["needs_host_flag"])

    def test_trailing_slash_stripped(self):
        cfg = _ServerCfg(public_base="https://pages.example.com/")
        urls = share_urls("/s/abc123", 8787, cfg)
        self.assertEqual(urls["public"], "https://pages.example.com/s/abc123")

    def test_public_base_with_path_prefix(self):
        cfg = _ServerCfg(public_base="https://corp.example.com/golive")
        urls = share_urls("/s/abc123", 8787, cfg)
        self.assertEqual(urls["public"],
                         "https://corp.example.com/golive/s/abc123")

    def test_public_base_with_path_prefix_and_slash(self):
        cfg = _ServerCfg(public_base="https://corp.example.com/golive/")
        urls = share_urls("/s/abc123", 8787, cfg)
        self.assertEqual(urls["public"],
                         "https://corp.example.com/golive/s/abc123")

    def test_local_always_present_even_with_public_base(self):
        cfg = _ServerCfg(public_base="https://pages.example.com")
        urls = share_urls("/s/abc123", 8787, cfg)
        self.assertEqual(urls["local"], "http://localhost:8787/s/abc123")


class TestLanFallback(unittest.TestCase):
    def test_lan_ip_used_when_no_public_base(self):
        cfg = _ServerCfg(host="0.0.0.0")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertIsNone(urls["public"])
        self.assertEqual(urls["lan"], "http://192.168.1.23:8787/s/abc123")
        self.assertEqual(urls["lan_ip"], "192.168.1.23")
        self.assertFalse(urls["needs_host_flag"])

    def test_probe_failure_returns_localhost(self):
        cfg = _ServerCfg(host="0.0.0.0")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="127.0.0.1"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertIsNone(urls["lan"])
        self.assertEqual(urls["local"], "http://localhost:8787/s/abc123")
        self.assertEqual(urls["lan_ip"], "127.0.0.1")
        # 0.0.0.0 is not loopback, so needs_host_flag is still False
        self.assertFalse(urls["needs_host_flag"])


class TestNeedsHostFlag(unittest.TestCase):
    def test_loopback_host_sets_flag(self):
        cfg = _ServerCfg(host="127.0.0.1")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertTrue(urls["needs_host_flag"])
        # LAN URL is still computed (the IP exists), but the flag says
        # others can't actually reach it
        self.assertIsNotNone(urls["lan"])

    def test_localhost_host_sets_flag(self):
        cfg = _ServerCfg(host="localhost")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertTrue(urls["needs_host_flag"])

    def test_wildcard_host_clears_flag(self):
        cfg = _ServerCfg(host="0.0.0.0")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertFalse(urls["needs_host_flag"])

    def test_empty_host_treated_as_wildcard(self):
        cfg = _ServerCfg(host="")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertFalse(urls["needs_host_flag"])

    def test_ipv6_loopback_sets_flag(self):
        cfg = _ServerCfg(host="::1")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, cfg)
        self.assertTrue(urls["needs_host_flag"])


class TestPathNormalisation(unittest.TestCase):
    def test_leading_slash_added(self):
        cfg = _ServerCfg(public_base="https://pages.example.com")
        urls = share_urls("s/abc123", 8787, cfg)
        self.assertEqual(urls["public"], "https://pages.example.com/s/abc123")

    def test_already_has_slash(self):
        cfg = _ServerCfg(public_base="https://pages.example.com")
        urls = share_urls("/s/abc123", 8787, cfg)
        self.assertEqual(urls["public"], "https://pages.example.com/s/abc123")

    def test_slug_path(self):
        cfg = _ServerCfg(host="0.0.0.0")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/my-report", 8787, cfg)
        self.assertEqual(urls["lan"], "http://192.168.1.23:8787/my-report")
        self.assertEqual(urls["local"], "http://localhost:8787/my-report")


class TestNoneConfig(unittest.TestCase):
    def test_none_cfg_uses_defaults(self):
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            urls = share_urls("/s/abc123", 8787, None)
        self.assertIsNone(urls["public"])
        self.assertEqual(urls["lan"], "http://192.168.1.23:8787/s/abc123")
        self.assertFalse(urls["needs_host_flag"])


class TestFormatShareMessage(unittest.TestCase):
    def test_public_mode_single_url(self):
        cfg = _ServerCfg(public_base="https://pages.example.com")
        msg = format_share_message("Q3 Report", "/s/abc123", 8787, cfg)
        self.assertIn("✅ 发布成功「Q3 Report」", msg)
        self.assertIn("https://pages.example.com/s/abc123", msg)
        self.assertNotIn("局域网", msg)
        self.assertNotIn("本机", msg)

    def test_lan_mode_shows_both_urls(self):
        cfg = _ServerCfg(host="0.0.0.0")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            msg = format_share_message("Demo", "/s/abc123", 8787, cfg)
        self.assertIn("✅ 发布成功「Demo」", msg)
        self.assertIn("http://localhost:8787/s/abc123", msg)
        self.assertIn("http://192.168.1.23:8787/s/abc123", msg)
        self.assertIn("← 分享给同事用这个", msg)
        # 0.0.0.0 → no host flag warning
        self.assertNotIn("--host 0.0.0.0", msg)

    def test_loopback_shows_host_warning(self):
        cfg = _ServerCfg(host="127.0.0.1")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="192.168.1.23"):
            msg = format_share_message("Demo", "/s/abc123", 8787, cfg)
        self.assertIn("需要 golive serve --host 0.0.0.0", msg)

    def test_no_lan_shows_fallback(self):
        cfg = _ServerCfg(host="0.0.0.0")
        with mock.patch("golive.core.urls._lan_ip",
                        return_value="127.0.0.1"):
            msg = format_share_message("Demo", "/s/abc123", 8787, cfg)
        self.assertIn("未检测到", msg)


if __name__ == "__main__":
    unittest.main()
