"""Full acceptance must fail explicitly when required coverage cannot run."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from golive.config import Config, set_config, reset_config
from golive.core.full_verify import COVERAGE, run


def options(tmp_path, **values):
    return SimpleNamespace(report_dir=str(tmp_path / 'report'), json=True, keep=False,
                           browser_channel='chromium', **values)


def test_full_mode_marks_unsupported_backend_and_unreached_checks(tmp_path, capsys):
    cfg = Config(); cfg.data.backend = 'none'; set_config(cfg)
    try:
        assert run(options(tmp_path)) == 1
        report = json.loads(capsys.readouterr().out)
        assert not report['ok'] and report['mode'] == 'full'
        assert {step['step'] for step in report['steps']} == set(COVERAGE)
        assert any(s['step'] == 'preflight' and s['status'] == 'failed' for s in report['steps'])
        assert any(s['step'] == 'restart_persistence' and s['status'] == 'skipped' for s in report['steps'])
        assert (tmp_path / 'report' / 'report.md').exists()
        assert (tmp_path / 'report').stat().st_mode & 0o777 == 0o700
        assert (tmp_path / 'report' / 'report.json').stat().st_mode & 0o777 == 0o600
    finally:
        reset_config()


def test_full_mode_missing_browser_dependency_is_not_success(tmp_path, capsys):
    set_config(Config())
    try:
        with patch.dict('sys.modules', {'playwright.sync_api': None}):
            assert run(options(tmp_path)) == 1
        report = json.loads(capsys.readouterr().out)
        assert 'html-golive[verify]' in report['steps'][0]['detail']
        assert not report['ok']
    finally:
        reset_config()


def test_existing_reports_are_never_overwritten(tmp_path, capsys):
    folder = tmp_path / 'report'; folder.mkdir(); sentinel = folder / 'report.json'
    sentinel.write_text('existing evidence')
    assert run(options(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'report_directory_unavailable'
    assert sentinel.read_text() == 'existing evidence'


def test_report_flags_require_full_mode(capsys):
    from golive.cli import main
    assert main(['verify', '--report-dir', 'unused', '--json']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'invalid_arguments'
