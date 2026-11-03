"""P3 control state: private local disk, race/restart/failure boundaries."""

import concurrent.futures
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from golive.backends.auth.oauth import OIDCAuth
from golive.backends.auth.state_store import AuthState, StateUnavailable
from golive.core import paths
from golive.core.state import inventory, management_db


@pytest.fixture
def control(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith('GOLIVE_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('GOLIVE_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('GOLIVE_STATE_DIR', str(tmp_path / 'shared'))
    monkeypatch.setattr(paths, '_resolved_home', None)
    return tmp_path


def provider(**overrides):
    return OIDCAuth(**dict({'issuer': 'https://idp.test.invalid',
                           'client_id': 'p3-test'}, **overrides))


def test_restart_shared_login_logout_expiry_and_private_files(control):
    first, second = provider(), provider()
    first._sessions['session-id'] = {'email': 'member@example.com', 'exp': time.time()+300}
    cookie = {'Cookie': 'golive_session=' + first._sign_sid('session-id')}
    assert second.session_user(cookie)['email'] == 'member@example.com'
    assert provider().session_user(cookie)['email'] == 'member@example.com'
    second.logout(cookie)
    assert first.session_user(cookie) is None and provider().session_user(cookie) is None
    first._sessions['expired'] = {'email': 'member@example.com', 'exp': time.time()-1}
    assert second.session_user({'Cookie': 'golive_session=' + first._sign_sid('expired')}) is None
    root = control / 'shared'
    assert root.stat().st_mode & 0o777 == 0o700
    for name in ['sessions.db', '.cookie_secret', '.cookie_secret.lock']:
        assert (root / name).stat().st_mode & 0o777 == 0o600
    assert b'session-id' not in (root / 'sessions.db').read_bytes()


def test_realm_and_key_isolation(control):
    first = provider(cookie_secret='first-key')
    first._sessions['session-id'] = {'email': 'member@example.com', 'exp': time.time()+300}
    cookie = {'Cookie': 'golive_session=' + first._sign_sid('session-id')}
    for other in [provider(issuer='https://other.invalid', cookie_secret='first-key'),
                  provider(client_id='other', cookie_secret='first-key'),
                  provider(cookie_secret='second-key')]:
        assert other.session_user(cookie) is None
    assert first.session_user({'Cookie': 'golive_session=😀.invalid'}) is None


def test_state_consumption_is_atomic_across_processes(control):
    root = control / 'shared'
    root.mkdir(mode=0o700)
    store = AuthState(root / 'state.db', 'realm', 'pending')
    store['single-use'] = {'nonce': 'private-nonce', 'exp': time.time()+300}
    import golive
    env = dict(os.environ, PYTHONPATH=str(Path(golive.__file__).resolve().parent.parent))
    code = ('from golive.backends.auth.state_store import AuthState; import sys; '
            'print(bool(AuthState(sys.argv[1], "realm", "pending").pop("single-use")))')
    procs = [subprocess.Popen([sys.executable, '-c', code, str(root/'state.db')],
                             env=env, cwd=control, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(6)]
    results = [p.communicate(timeout=15) for p in procs]
    assert all(p.returncode == 0 for p in procs), results
    assert [out.strip() for out, _ in results].count('True') == 1
    assert [out.strip() for out, _ in results].count('False') == 5


def test_initial_cookie_key_race_one_key(control):
    def create(_):
        return provider()._cookie_secret
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(create, range(16)))
    assert len(set(keys)) == 1


def test_store_failure_is_explicit_and_never_local_fallback(control):
    first = provider()
    first._sessions['valid'] = {'email': 'member@example.com', 'exp': time.time()+300}
    cookie = {'Cookie': 'golive_session=' + first._sign_sid('valid')}
    (control/'shared'/'sessions.db').write_bytes(b'corrupt database')
    with pytest.raises(StateUnavailable):
        first.session_user(cookie)
    with pytest.raises(StateUnavailable):
        first.logout(cookie)


def test_inventory_readonly_and_legacy_path(control, monkeypatch):
    before = set(control.iterdir())
    result = inventory()
    assert result['mode'] == 'same_host_shared'
    assert result['source'] == 'GOLIVE_STATE_DIR'
    assert set(control.iterdir()) == before
    assert not (control/'shared').exists() and not (control/'home').exists()
    monkeypatch.delenv('GOLIVE_STATE_DIR')
    assert inventory()['mode'] == 'single_instance'
    assert management_db() == control/'home'/'registry.db'


def test_group_admin_and_guards_shared_between_homes(control, monkeypatch):
    from golive.backends.registry.group_store import GroupStore
    from golive.backends.registry.admin_store import get_managed_admins
    first = GroupStore()
    group = first.change('create', 'root@example.com', value='Team')['group_id']
    first.change('member.add', 'root@example.com', group, value='member@example.com')
    first.change('grant', 'root@example.com', group, site_id='shared-site', role='maintainer')
    get_managed_admins().add('member@example.com', 'root@example.com')
    monkeypatch.setenv('GOLIVE_HOME', str(control/'second-home'))
    monkeypatch.setattr(paths, '_resolved_home', None)
    second = GroupStore()
    assert second.role('member@example.com', 'shared-site') == 'maintainer'
    assert get_managed_admins().has('member@example.com')
    second.change('member.remove', 'root@example.com', group, value='member@example.com')
    get_managed_admins().remove('member@example.com')
    assert first.role('member@example.com', 'shared-site') == ''
    assert not get_managed_admins().has('member@example.com')
    assert first.requires_identity('shared-site')
    assert len(first.events()) == 4
    assert (control/'shared'/'management.db').stat().st_mode & 0o777 == 0o600


def test_parallel_admin_add_is_idempotent(control):
    from golive.backends.registry.admin_store import ManagedAdmins
    store = ManagedAdmins()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: store.add('member@example.com', 'root@example.com'), range(12)))
    assert results.count(True) == 1 and results.count(False) == 11


def test_context_has_readonly_state_inventory(control):
    from golive.config import Config
    from golive.core.context import collect
    result = collect(cfg=Config(), port=65530)
    assert result['local_state']['mode'] == 'same_host_shared'
    assert not (control/'shared').exists() and not (control/'home').exists()


@pytest.mark.parametrize('shared', [True, False])
def test_shared_startup_refuses_broken_store(control, monkeypatch, shared):
    from golive.config import Config, set_config, reset_config
    from golive.server.app import _make_oidc
    if shared:
        (control/'shared').write_text('not a directory')
    else:
        monkeypatch.delenv('GOLIVE_STATE_DIR')
        (control/'home').write_text('not a directory')
    cfg = Config()
    cfg.auth.provider = 'oidc'
    cfg.auth.oidc_issuer = 'https://idp.test.invalid'
    cfg.auth.oidc_client_id = 'test'
    set_config(cfg)
    try:
        with pytest.raises(RuntimeError, match='server not started'):
            _make_oidc()
    finally:
        reset_config()
