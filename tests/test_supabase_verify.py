"""Verify really probes the public Supabase path, including failure/cleanup."""
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

import pytest
import requests
from golive.config import Config,set_config,reset_config
from golive.core.paths import reset_cache
from golive.backends.postgrest import PostgrestClient,PostgrestError,supabase_headers
from tests.fake_postgrest import FakePostgrest


@pytest.fixture
def remote(tmp_path,monkeypatch):
    fake=FakePostgrest();url=fake.start()
    monkeypatch.setenv('GOLIVE_HOME',str(tmp_path))
    monkeypatch.setenv('GOLIVE_SUPABASE_ANON_KEY','sb_publishable_public_test')
    monkeypatch.setenv('GOLIVE_SUPABASE_SERVICE_KEY','sb_secret_server_test')
    reset_cache();reset_config()
    cfg=Config();cfg.data.backend='supabase';cfg.supabase.url=url
    set_config(cfg)
    yield fake,cfg
    fake.stop();reset_cache();reset_config()


def verify():
    from golive.cli import cmd_verify
    from types import SimpleNamespace
    output=io.StringIO()
    with redirect_stdout(output),redirect_stderr(io.StringIO()):
        code=cmd_verify(SimpleNamespace(json=True,keep=False))
    return code,json.loads(output.getvalue())


def test_opaque_key_and_legacy_jwt_headers():
    assert supabase_headers('sb_publishable_public_test')=={'apikey':'sb_publishable_public_test'}
    assert supabase_headers('sb_secret_server_test')=={'apikey':'sb_secret_server_test'}
    assert supabase_headers('eyJlegacy.payload.signature')['Authorization']=='Bearer eyJlegacy.payload.signature'


def test_verification_uses_public_key_and_all_crud(remote,monkeypatch):
    fake,cfg=remote;headers=[];real=requests.request
    def request(*args,**kwargs):
        headers.append(kwargs['headers'])
        assert kwargs['allow_redirects'] is False
        return real(*args,**kwargs)
    monkeypatch.setattr(requests,'request',request)
    code,result=verify()
    assert code==0 and result['ok']
    assert {m for m,t,p,b in fake.requests}>={'POST','GET','PATCH','DELETE'}
    assert headers and all(h['apikey']=='sb_publishable_public_test' for h in headers)
    assert all('Authorization' not in h for h in headers)
    assert fake.table(cfg.data.templates_table)==[]


@pytest.mark.parametrize('operation',['insert','select','update','delete'])
def test_rls_denial_never_reports_success(remote,operation):
    replacement=([],None) if operation=='select' else 0 if operation=='delete' else []
    with mock.patch.object(PostgrestClient,operation,return_value=replacement):
        code,result=verify()
    assert code==1 and result['ok'] is False
    assert any(s['step']=='data' and not s['ok'] for s in result['steps'])


def test_cleanup_failure_is_nonzero_and_in_json(remote):
    with mock.patch('golive.backends.storage.local.LocalStorage.delete',side_effect=OSError('fixture cleanup error')):
        code,result=verify()
    assert code==1 and result['ok'] is False
    assert any(s['step']=='cleanup' and not s['ok'] for s in result['steps'])


def test_service_only_config_cannot_pass_browser_verification(remote,monkeypatch):
    monkeypatch.delenv('GOLIVE_SUPABASE_ANON_KEY')
    code,result=verify()
    assert code==1 and not result['ok']
    assert not remote[0].requests
