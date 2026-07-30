"""Unit tests for golive.config — lookup priority, env overrides, errors."""

import os
import tempfile
import unittest
from pathlib import Path

from golive.config import Config, ConfigError, load_config, reset_config

ENV_KEYS = [
    "GOLIVE_CONFIG", "GOLIVE_HOME", "GOLIVE_TOKEN", "GOLIVE_UPLOADER_CMD",
    "GOLIVE_FONT_CDN_BASE", "GOLIVE_SUPABASE_URL", "GOLIVE_SUPABASE_ANON_KEY",
    "GOLIVE_SUPABASE_SERVICE_KEY", "GOLIVE_S3_ENDPOINT", "GOLIVE_S3_BUCKET",
]


class ConfigTestBase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self._tmp = tempfile.TemporaryDirectory(prefix="golive_cfg_")
        self.tmp = Path(self._tmp.name)
        self._old_cwd = os.getcwd()
        os.chdir(self.tmp)  # ensure no stray ./golive.yaml is picked up
        reset_config()

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_config()

    def write_yaml(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestLookupPriority(ConfigTestBase):
    def test_defaults_when_no_file(self):
        os.environ["GOLIVE_HOME"] = str(self.tmp / "nohome")
        cfg = load_config()
        self.assertEqual(cfg.storage.backend, "local")
        self.assertEqual(cfg.registry.backend, "sqlite")
        self.assertEqual(cfg.data.backend, "sqlite")
        self.assertEqual(cfg.auth.provider, "none")
        self.assertEqual(cfg.source_path, "")

    def test_cli_beats_env_and_cwd(self):
        cli = self.write_yaml(self.tmp / "cli.yaml", "storage: {backend: s3}")
        envf = self.write_yaml(self.tmp / "env.yaml", "storage: {backend: supabase}")
        self.write_yaml(self.tmp / "golive.yaml", "storage: {backend: local}")
        os.environ["GOLIVE_CONFIG"] = str(envf)
        cfg = load_config(cli_path=str(cli))
        self.assertEqual(cfg.storage.backend, "s3")
        self.assertEqual(cfg.source_path, str(cli))

    def test_env_config_beats_cwd(self):
        envf = self.write_yaml(self.tmp / "env.yaml", "registry: {backend: postgres}")
        self.write_yaml(self.tmp / "golive.yaml", "registry: {backend: supabase}")
        os.environ["GOLIVE_CONFIG"] = str(envf)
        cfg = load_config()
        self.assertEqual(cfg.registry.backend, "postgres")

    def test_cwd_beats_home(self):
        home = self.tmp / "home"
        os.environ["GOLIVE_HOME"] = str(home)
        self.write_yaml(home / "golive.yaml", "data: {backend: supabase}")
        self.write_yaml(self.tmp / "golive.yaml", "data: {backend: none}")
        cfg = load_config()
        self.assertEqual(cfg.data.backend, "none")

    def test_home_fallback(self):
        home = self.tmp / "home"
        os.environ["GOLIVE_HOME"] = str(home)
        self.write_yaml(home / "golive.yaml",
                        "supabase: {url: 'https://example.supabase.co'}")
        cfg = load_config()
        self.assertEqual(cfg.supabase.url, "https://example.supabase.co")

    def test_missing_cli_path_raises(self):
        with self.assertRaises(ConfigError):
            load_config(cli_path=str(self.tmp / "nope.yaml"))


class TestEnvOverrides(ConfigTestBase):
    def test_token_env_wins_and_implies_provider(self):
        self.write_yaml(self.tmp / "golive.yaml",
                        "auth: {provider: none, token: 'from-yaml'}")
        os.environ["GOLIVE_TOKEN"] = "from-env"
        cfg = load_config()
        self.assertEqual(cfg.auth.token, "from-env")
        self.assertEqual(cfg.auth.provider, "token")

    def test_uploader_cmd_env_wins(self):
        self.write_yaml(self.tmp / "golive.yaml",
                        "uploader: {command: 'yamltool {file}'}")
        os.environ["GOLIVE_UPLOADER_CMD"] = "envtool {file}"
        cfg = load_config()
        self.assertEqual(cfg.uploader.command, "envtool {file}")

    def test_supabase_url_env_wins(self):
        self.write_yaml(self.tmp / "golive.yaml",
                        "supabase: {url: 'https://yaml.supabase.co'}")
        os.environ["GOLIVE_SUPABASE_URL"] = "https://env.supabase.co"
        cfg = load_config()
        self.assertEqual(cfg.supabase.url, "https://env.supabase.co")

    def test_supabase_keys_from_env(self):
        os.environ["GOLIVE_SUPABASE_URL"] = "https://x.supabase.co"
        os.environ["GOLIVE_SUPABASE_ANON_KEY"] = "anon-1"
        cfg = load_config()
        self.assertEqual(cfg.supabase.anon_key, "anon-1")
        self.assertEqual(cfg.supabase.key, "anon-1")
        os.environ["GOLIVE_SUPABASE_SERVICE_KEY"] = "svc-1"
        self.assertEqual(cfg.supabase.service_key, "svc-1")
        self.assertEqual(cfg.supabase.key, "svc-1")  # service wins
        self.assertTrue(cfg.supabase.configured)

    def test_custom_key_env_indirection(self):
        self.write_yaml(self.tmp / "golive.yaml",
                        "supabase:\n  url: https://x.supabase.co\n"
                        "  anon_key_env: MY_CUSTOM_KEY\n")
        os.environ["MY_CUSTOM_KEY"] = "indirect-key"
        try:
            cfg = load_config()
            self.assertEqual(cfg.supabase.anon_key, "indirect-key")
        finally:
            os.environ.pop("MY_CUSTOM_KEY", None)


class TestBrokenFiles(ConfigTestBase):
    def test_invalid_yaml_friendly_error(self):
        self.write_yaml(self.tmp / "golive.yaml", "storage: [unclosed")
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("golive.yaml", str(ctx.exception))

    def test_non_mapping_top_level(self):
        self.write_yaml(self.tmp / "golive.yaml", "- just\n- a list\n")
        with self.assertRaises(ConfigError):
            load_config()

    def test_empty_file_is_defaults(self):
        self.write_yaml(self.tmp / "golive.yaml", "")
        cfg = load_config()
        self.assertEqual(cfg.storage.backend, "local")

    def test_bad_port_raises(self):
        self.write_yaml(self.tmp / "golive.yaml", "server: {port: notaport}")
        with self.assertRaises(ConfigError):
            load_config()


class TestSectionParsing(ConfigTestBase):
    def test_full_yaml_round_trip(self):
        self.write_yaml(self.tmp / "golive.yaml", """
supabase:
  url: https://proj.supabase.co
storage:
  backend: supabase
  supabase: {bucket: my-sites}
registry:
  backend: supabase
  supabase: {table: my_sites}
data:
  backend: supabase
  supabase: {templates_table: my_tpl, user_id: alice}
server:
  host: 127.0.0.1
  port: 9000
  public_base: https://pages.example.com/
slug:
  reserved: [Internal, beta]
""")
        cfg = load_config()
        self.assertEqual(cfg.storage.backend, "supabase")
        self.assertEqual(cfg.storage.supabase_bucket, "my-sites")
        self.assertEqual(cfg.registry.supabase_table, "my_sites")
        self.assertEqual(cfg.data.templates_table, "my_tpl")
        self.assertEqual(cfg.data.user_id, "alice")
        self.assertEqual(cfg.server.port, 9000)
        self.assertEqual(cfg.server.public_base, "https://pages.example.com")
        self.assertEqual(cfg.slug_reserved, ["internal", "beta"])


if __name__ == "__main__":
    unittest.main()
