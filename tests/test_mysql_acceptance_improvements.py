"""Regression coverage for diagnostics and CLI parity reported on 0.9.7.post1."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from golive.cli import main
from golive.config import Config, reset_config, set_config
from golive.core.paths import reset_cache


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLIVE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("GOLIVE_CONFIG", raising=False)
    reset_cache(); reset_config()
    config = Config()
    config.server.port = 8788
    config.source_path = str(tmp_path / "golive.yaml")
    set_config(config)
    yield config
    reset_cache(); reset_config()


def cli(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(list(args))
    return code, json.loads(output.getvalue())


def test_context_uses_config_without_creating_home(cfg):
    from golive.core.context import collect
    with patch("golive.core.context._server_info", return_value={}) as probe:
        info = collect(cfg)
    probe.assert_called_once_with(8788)
    assert info["server"]["port_source"] == "config"
    assert not Path(os.environ["GOLIVE_HOME"]).exists()


def test_context_port_precedence_and_stale_record(cfg):
    from golive.core.context import resolve_server_port
    from golive.core.service import write_pidfile
    write_pidfile(os.getpid(), "127.0.0.1", 9876)
    assert resolve_server_port(cfg) == (9876, "service_record")
    assert resolve_server_port(cfg, 8787) == (8787, "cli")
    with patch("golive.core.service.pid_alive", return_value=False):
        assert resolve_server_port(cfg) == (8788, "config")
    for port in ("bad", -1, 99999, {}, []):
        path = Path(os.environ["GOLIVE_HOME"]) / "golive.pid"
        path.write_text(json.dumps({"pid": os.getpid(), "port": port}))
        assert resolve_server_port(cfg) == (8788, "config")


def test_cli_mutations_pagination_and_sort(cfg):
    first = cli("data", "create", "--name", "中文🧪", "--content", '{"nested":{"n":1}}', "--json")[1]
    second = cli("data", "create", "--name", "second", "--json")[1]
    assert first["ok"] and first["code"] == "ok"
    ident = first["id"]
    sorted_row = cli("data", "sort", "--id", ident, "--sort-index", "99", "--json")[1]
    assert sorted_row["record"]["sort_index"] == 99
    page = cli("data", "list", "--page-no", "2", "--page-size", "1", "--limit", "5")[1]
    assert page["total"] == 2 and [r["id"] for r in page["list"]] == [second["id"]]
    updated = cli("data", "update", "--id", ident, "--content", '{"updated":true}', "--json")[1]
    assert updated["record"]["content"] == {"updated": True}
    upserted = cli("data", "upsert", "--name", "中文🧪", "--content", '{"upserted":true}', "--json")[1]
    assert upserted["id"] == ident
    assert cli("data", "delete", "--id", ident, "--json")[1]["ok"]
    code, result = cli("data", "delete", "--id", ident, "--json")
    assert code == 1 and result["code"] == "not_found"


@pytest.mark.parametrize("args,code", [
    (("create",), "invalid_arguments"), (("update",), "invalid_arguments"),
    (("sort", "--id", "x"), "invalid_arguments"),
    (("list", "--page-no", "0"), "invalid_arguments"),
    (("list", "--page-size", "-1"), "invalid_arguments"),
    (("create", "--name", "n", "--content", "{"), "invalid_input"),
    (("update", "--id", "missing"), "not_found"),
])
def test_cli_json_errors(cfg, args, code):
    status, result = cli("data", *args, "--json")
    assert status == 1 and result["ok"] is False and result["code"] == code


def test_backend_exception_is_json_and_does_not_leak(cfg):
    with patch("golive.backends.factory.get_template_store", side_effect=RuntimeError("password-secret")):
        status, result = cli("data", "create", "--name", "n", "--json")
    assert status == 1 and result["code"] == "backend_error"
    assert "password-secret" not in json.dumps(result)


def test_mysql_target_redacts_credentials_and_tls_paths(cfg, monkeypatch):
    from golive.core.backend_info import data_backend_info
    cfg.data.backend = "mysql"
    monkeypatch.setenv("GOLIVE_MYSQL_DSN", "mysql://private-user:private-password@127.0.0.1:13306/acceptance?ssl_ca=/private/ca.pem")
    info = data_backend_info(cfg)
    assert info["host"] == "127.0.0.1" and info["port"] == 13306
    assert info["database"] == "acceptance" and info["table"] == "golive_templates"
    assert "private" not in json.dumps(info)


def test_probe_failure_identifies_mysql(cfg, monkeypatch):
    from golive.server.connection_checks import check_data_backend
    cfg.data.backend = "mysql"
    monkeypatch.delenv("GOLIVE_MYSQL_DSN", raising=False)
    status, result = check_data_backend({}, cfg)
    assert status == 400 and result["backend"] == "mysql"
    assert "GOLIVE_MYSQL_DSN" in result["location"]


def test_environment_diagnostics_are_offline_and_redacted(cfg, monkeypatch):
    from golive.core.environment import collect_environment
    monkeypatch.setenv("HTTPS_PROXY", "http://secret-user:secret-pass@proxy:8080")
    with patch("ssl.OPENSSL_VERSION", "LibreSSL 2.8.3"):
        result = collect_environment(cfg)
    assert result["ssl"]["urllib3_v2_supported"] is False
    assert result["warnings"] and "HTTPS_PROXY" in result["proxy"]["environment_variables"]
    assert result["proxy"]["remote_tls_verified"] is False
    assert "secret" not in json.dumps(result)


def test_doctor_explicit_default_port_overrides_service_record(cfg):
    from golive.core.service import write_pidfile
    from golive.cli import _doctor_target_port
    from types import SimpleNamespace
    write_pidfile(os.getpid(), "127.0.0.1", 9876)
    assert _doctor_target_port(SimpleNamespace(port=8787)) == 8787
    assert _doctor_target_port(SimpleNamespace(port=None)) == 9876


def test_admin_model_counts_are_not_table_counts(cfg):
    from golive.backends.factory import get_template_store
    from golive.server.admin_api import _data_models
    store = get_template_store(cfg)
    store.create('model-one', 'a')
    store.create('model-one', 'b')
    store.create('model-two', 'c')
    status, result = _data_models(store)
    info = result['data_backend']
    assert status == 200
    assert (info['table_count'], info['model_count'], info['row_count']) == (1, 2, 3)


def test_sandbox_recognizes_symlinked_parent(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('mysql_sandbox', Path(__file__).resolve().parents[1] / 'scripts/mysql_sandbox.py')
    sandbox = importlib.util.module_from_spec(spec); spec.loader.exec_module(sandbox)
    actual = tmp_path / 'actual'; actual.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(actual, target_is_directory=True)
    root = actual / 'sandbox'; root.mkdir()
    (root / 'sandbox.json').write_text(json.dumps({'marker': sandbox.MARKER, 'directory': str(alias / 'sandbox')}))
    assert sandbox.load(root)['marker'] == sandbox.MARKER
