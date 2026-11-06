"""Automation contract for parser/config, operation failures and uncertain writes."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from golive.cli import main
from golive.config import reset_config
from golive.core.paths import reset_cache


@pytest.fixture(autouse=True)
def project(tmp_path,monkeypatch):
    monkeypatch.setenv('GOLIVE_HOME',str(tmp_path/'home'))
    monkeypatch.setenv('GOLIVE_CONFIG',str(tmp_path/'golive.yaml'))
    (tmp_path/'golive.yaml').write_text('{}\n')
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'xdg'))
    reset_cache();reset_config()
    yield tmp_path
    reset_cache();reset_config()


def result(capsys,args):
    code=main(args);captured=capsys.readouterr()
    assert not captured.err
    return code,json.loads(captured.out)


@pytest.mark.parametrize('args',[
    ['data','list','--page-no','private-input','--json'],
    ['data','missing-action','--json'],['data','create','--unexpected-secret','--json'],
    ['import','--json'],['migrate','data','--json'],['unknown-secret','--json'],
    ['data','list','--json=true'],
])
def test_parser_failures_are_one_json_document_without_private_arguments(project,capsys,args):
    code,value=result(capsys,args)
    assert code==2 and value['code']=='invalid_arguments' and not value['ok']
    assert 'private-input' not in json.dumps(value) and 'unexpected-secret' not in json.dumps(value)
    assert not (project/'home').exists()


@pytest.mark.parametrize('command',[['data','list'],['doctor'],['context'],['import','archive','--yes'],['migrate','data','--to','mysql'],['verify']])
def test_bad_config_is_json_without_yaml_contents(project,capsys,command):
    (project/'golive.yaml').write_text('auth: [broken-password-private')
    code,value=result(capsys,command+['--json'])
    assert code==1 and value['code']=='invalid_config' and 'password-private' not in json.dumps(value)
    assert not (project/'home').exists()


def test_input_validation_precedes_backend_connection(capsys):
    with patch('golive.backends.factory.get_template_store') as backend:
        code,value=result(capsys,['data','create','--name','n','--content','NaN','--json'])
    assert code==1 and value['code']=='invalid_input'
    backend.assert_not_called()


@pytest.mark.parametrize('error,expected',[(TimeoutError('token-private'),'backend_timeout'),(ConnectionError('mysql://private'),'backend_unavailable')])
def test_connection_failures_mark_mutations_uncertain(capsys,error,expected):
    with patch('golive.backends.factory.get_template_store',side_effect=error):
        code,value=result(capsys,['data','create','--name','n','--json'])
    assert code==1 and value['code']==expected and value['write_state']=='unknown'
    assert 'token-private' not in json.dumps(value)


def test_duplicate_create_reports_conflict_and_upsert_is_repeatable(capsys):
    first=result(capsys,['data','upsert','--name','same','--content','{"n":1}','--json'])[1]
    second=result(capsys,['data','upsert','--name','same','--content','{"n":2}','--json'])[1]
    assert first['id']==second['id'] and second['record']['content']=={'n':2}
    code,value=result(capsys,['data','create','--name','same','--json'])
    assert code==1 and value['code']=='conflict'
    # Preserve successful list/get JSON shapes, with or without --json.
    row=result(capsys,['data','get','--id',first['id'],'--json'])[1]
    page=result(capsys,['data','list','--json'])[1]
    assert row['id']==first['id'] and 'record' not in row and page['total']==1


def test_partial_output_and_unhandled_exception_never_leak(capsys):
    def fail(args):
        print('password-private')
        raise RuntimeError('DSN-private')
    with patch('golive.cli.cmd_context',side_effect=fail):
        code,value=result(capsys,['context','--json'])
    assert code==1 and value['code']=='backend_error'
    assert 'private' not in json.dumps(value)


def test_invalid_output_after_write_is_reported_uncertain(capsys):
    def invalid(args):print('partial secret');return 0
    with patch('golive.cli.cmd_migrate',side_effect=invalid):
        code,value=result(capsys,['migrate','data','--to','mysql','--json'])
    assert code==1 and value['code']=='invalid_output' and value['write_state']=='unknown'


def test_failed_diagnostics_redact_custom_env_credentials(project,monkeypatch,capsys):
    (project/'golive.yaml').write_text('registry:\n  mysql:\n    dsn_env: CUSTOM_DATABASE\n')
    monkeypatch.setenv('CUSTOM_DATABASE','mysql://user:private-password@127.0.0.1/db')
    def failed(args):
        print(json.dumps({'ok':False,'error':'private-password in mysql://user:private-password@127.0.0.1/db'}));return 1
    with patch('golive.cli.cmd_doctor',side_effect=failed):
        code,value=result(capsys,['doctor','--json'])
    assert code==1 and 'private-password' not in json.dumps(value) and '[redacted]' in value['error']


def test_interrupt_returns_130_json_without_traceback(capsys):
    with patch('golive.cli.cmd_migrate',side_effect=KeyboardInterrupt):
        code,value=result(capsys,['migrate','data','--to','mysql','--json'])
    assert code==130 and value['code']=='interrupted' and value['write_state']=='unknown'


def test_help_keeps_text_and_exit_zero(capsys):
    with pytest.raises(SystemExit) as exitinfo:main(['data','--help','--json'])
    assert exitinfo.value.code==0 and '--page-no' in capsys.readouterr().out
