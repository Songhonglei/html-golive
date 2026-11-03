"""P2: real local storage, HTTP revisions, explicit-login team permissions."""

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from golive.backends.registry.group_store import GroupStore
from golive.backends.registry.sqlite_store import SqliteRegistry
from golive.backends.storage.local import LocalStorage
from golive.config import Config, reset_config, set_config
from golive.core.content_revision import ContentConflict, content_revision
from golive.server import admin_api, authz, editor_api


@pytest.fixture
def team(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith('GOLIVE_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('GOLIVE_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('GOLIVE_CONFIG', str(tmp_path / 'empty.yaml'))
    (tmp_path / 'empty.yaml').write_text('{}')
    from golive.core import paths
    monkeypatch.setattr(paths, '_resolved_home', None)
    cfg = Config()
    cfg.auth.token = 'test-operator'
    cfg.editor.token = 'test-editor'
    cfg.admin.admins = ['root@example.com']
    set_config(cfg)
    registry, storage = SqliteRegistry(), LocalStorage()
    site = registry.create('Team', 'team-page', owner='owner@example.com')
    registry.set_editable(site['site_id'], True)
    site = registry.get(site['site_id'])
    from golive.inject.editor import inject_into_html
    storage.publish(inject_into_html('<html><head><title>Team</title></head><body><h1>original</h1></body></html>', slug='team-page'), site['site_id'], False)
    groups = GroupStore()
    root = authz.Identity('root@example.com', is_superadmin=True)
    def api(method, path='', data=None, identity=root, query=None):
        return admin_api.handle(method, '/api/admin/' + path, query or {},
            json.dumps(data).encode() if data is not None else b'', identity, registry, storage)
    result = SimpleNamespace(cfg=cfg, registry=registry, storage=storage, site=site,
        groups=groups, root=root, api=api, home=tmp_path / 'home')
    yield result
    reset_config()


def create_group(team, role='maintainer', email='member@example.com', name='Design'):
    code, body = team.api('POST', 'permissions/groups', {'name': name})
    assert code == 200, body
    group_id = body['group_id']
    assert team.api('POST', f'permissions/groups/{group_id}/members', {'email': email})[0] == 200
    assert team.api('POST', f'permissions/groups/{group_id}/sites', {'site': 'team-page', 'role': role})[0] == 200
    return group_id


def save(team, html, revision):
    return editor_api.save_content(team.site, html, 'owner@example.com',
        team.registry, team.storage, cfg=team.cfg, expected_revision=revision)


def test_two_editors_conflict_preserves_content_and_snapshots_then_reload_retry(team):
    revision = content_revision(team.storage.read(team.site['site_id']))
    first, body = save(team, '<h1>first draft</h1>', revision)
    assert first == 200
    stored = team.storage.read(team.site['site_id'])
    snapshots = team.storage.list_snapshots(team.site['site_id'])
    updated = team.registry.get(team.site['site_id'])['updated_at']
    code, conflict = save(team, '<h1>second draft</h1>', revision)
    assert code == 409 and conflict['code'] == 'edit_conflict'
    assert conflict['current_revision'] == body['revision'] == content_revision(stored)
    assert team.storage.read(team.site['site_id']) == stored
    assert team.storage.list_snapshots(team.site['site_id']) == snapshots
    assert team.registry.get(team.site['site_id'])['updated_at'] == updated
    assert save(team, '<h1>merged after comparison</h1>', conflict['current_revision'])[0] == 200


@pytest.mark.parametrize('revision,code', [(None, 428), ('*', 400), ('W/"abc"', 400), ('"abc"', 400), ('', 400), ('"' + '0' * 64 + '"', 409)])
def test_missing_invalid_or_stale_revision_never_writes(team, revision, code):
    before = team.storage.read(team.site['site_id'])
    assert save(team, '<h1>changed</h1>', revision)[0] == code
    assert team.storage.read(team.site['site_id']) == before
    assert team.storage.list_snapshots(team.site['site_id']) == []


def test_parallel_threads_exactly_one_success(team):
    revision = content_revision(team.storage.read(team.site['site_id']))
    barrier = threading.Barrier(4)
    def write(i):
        barrier.wait()
        return save(team, f'<h1>thread {i}</h1>', revision)[0]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(write, range(4)))
    assert sorted(results) == [200, 409, 409, 409]
    assert len(team.storage.list_snapshots(team.site['site_id'])) == 1


def test_separate_processes_share_storage_write_lock(team):
    revision = content_revision(team.storage.read(team.site['site_id']))
    program = '''import sys,time
from golive.backends.storage.local import LocalStorage
from golive.core.content_revision import ContentConflict
while time.time() < float(sys.argv[3]): time.sleep(.005)
try:
 LocalStorage().publish_if_revision(sys.argv[4], sys.argv[1], sys.argv[2])
 print('saved')
except ContentConflict: print('conflict')
'''
    deadline = str(time.time() + .6)
    processes = [subprocess.Popen([sys.executable, '-c', program, team.site['site_id'], revision,
        deadline, f'<h1>process {i}</h1>'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i in range(3)]
    results = [p.communicate(timeout=15) for p in processes]
    assert all(p.returncode == 0 for p in processes), results
    assert sorted(out.strip() for out, err in results) == ['conflict', 'conflict', 'saved']
    assert len(team.storage.list_snapshots(team.site['site_id'])) == 1


def test_publish_and_rollback_invalidate_editor_revision(team):
    sid = team.site['site_id']
    old = content_revision(team.storage.read(sid))
    team.storage.publish('<h1>CLI publish</h1>', sid)
    assert save(team, '<h1>stale editor</h1>', old)[0] == 409
    after_publish = content_revision(team.storage.read(sid))
    team.storage.rollback(sid)
    assert save(team, '<h1>stale after rollback</h1>', after_publish)[0] == 409


def test_deleted_content_not_recreated_by_stale_editor(team):
    revision = content_revision(team.storage.read(team.site['site_id']))
    team.storage.delete(team.site['site_id'])
    code, body = save(team, '<h1>resurrect</h1>', revision)
    assert code == 409 and body['current_revision'] is None
    assert not team.storage.exists(team.site['site_id'])


@pytest.mark.parametrize('backend', ['s3', 'supabase'])
def test_nonconditional_storage_refuses_save_without_publish(team, backend):
    from unittest.mock import Mock
    storage = Mock(spec=['publish', 'read'])
    storage.backend = backend
    code, body = editor_api.save_content(team.site, '<h1>safe</h1>', 'owner@example.com',
        team.registry, storage, cfg=team.cfg, expected_revision='"' + '0'*64 + '"')
    assert code == 501 and body['code'] == 'conditional_write_unsupported'
    storage.publish.assert_not_called()


@pytest.mark.parametrize('role', ['viewer', 'maintainer'])
def test_group_access_scope_and_write_privileges(team, role):
    create_group(team, role)
    member = authz.Identity('member@example.com')
    assert authz.site_role(member, team.site) == role
    assert team.api('GET', 'sites/team-page', identity=member)[0] == 200
    status, listing = team.api('GET', 'sites', identity=member)
    assert status == 200 and listing['total'] == 1 and listing['sites'][0]['role'] == role
    for path, method, data in [('sites/team-page', 'PATCH', {'name':'Hijack'}),
        ('sites/team-page', 'DELETE', {'confirm':'team-page'}),
        ('sites/team-page/transfer', 'POST', {'email':'member@example.com'}),
        ('sites/team-page/maintainers', 'POST', {'email':'x@example.com'}),
        ('permissions/groups', 'POST', {'name':'Escalate'})]:
        assert team.api(method, path, data, member)[0] == 403
    assert authz.can_rollback(member, team.site) == (role == 'maintainer')
    other = team.registry.create('Other', 'other', owner='else@example.com')
    assert authz.site_role(member, other) == ''
    allowed = editor_api.check_editor_auth({}, team.site, cfg=team.cfg,
        session_user={'email':'member@example.com'})
    assert allowed[0] == (role == 'maintainer')


@pytest.mark.parametrize('revocation', ['member', 'grant', 'delete'])
def test_revocation_applies_to_same_identity_and_existing_session(team, revocation):
    gid = create_group(team)
    member = authz.Identity('member@example.com')
    session = {'email':'member@example.com', 'groups':['Design']}
    assert authz.site_role(member, team.site) == 'maintainer'
    if revocation == 'member':
        status, _ = team.api('DELETE', f'permissions/groups/{gid}/members', {'email':member.email})
    elif revocation == 'grant':
        status, _ = team.api('DELETE', f'permissions/groups/{gid}/sites', {'site':'team-page'})
    else:
        status, _ = team.api('DELETE', f'permissions/groups/{gid}')
    assert status == 200
    assert authz.site_role(member, team.site) == ''
    assert team.api('GET', 'sites/team-page', identity=member)[0] == 403
    assert not editor_api.check_editor_auth({}, team.site, cfg=team.cfg, session_user=session)[0]


def test_roles_union_and_personal_permissions_survive_group_revocation(team):
    viewer = create_group(team, 'viewer', name='Viewers')
    editor = create_group(team, 'maintainer', name='Editors')
    member = authz.Identity('member@example.com')
    assert authz.site_role(member, team.site) == 'maintainer'
    team.api('DELETE', f'permissions/groups/{editor}')
    assert authz.site_role(member, team.site) == 'viewer'
    team.registry.add_maintainer(team.site['site_id'], member.email)
    current = team.registry.get(team.site['site_id'])
    assert authz.site_role(member, current) == 'maintainer'
    team.api('DELETE', f'permissions/groups/{viewer}')
    assert authz.site_role(member, current) == 'maintainer'
    assert authz.site_role(authz.Identity('owner@example.com'), current) == 'owner'
    assert authz.site_role(team.root, current) == 'superadmin'


def test_same_name_recreation_does_not_resurrect_grants_or_members(team):
    gid = create_group(team)
    team.api('DELETE', f'permissions/groups/{gid}')
    code, result = team.api('POST', 'permissions/groups', {'name':'Design'})
    assert code == 200 and result['group_id'] != gid
    assert team.groups.list()[0]['members'] == team.groups.list()[0]['grants'] == []
    assert GroupStore().role('member@example.com', team.site['site_id']) == ''


def test_ownerless_site_does_not_reopen_legacy_editor_access_after_revocation(team):
    team.registry.set_owner(team.site['site_id'], '')
    site = team.registry.get(team.site['site_id'])
    gid = create_group(team)
    team.api('DELETE', f'permissions/groups/{gid}')
    assert not editor_api.check_editor_auth({'Authorization':'Bearer test-editor'}, site, cfg=team.cfg)[0]
    assert not editor_api.check_editor_auth({}, site, cfg=team.cfg, session_user={'email':'member@example.com'})[0]


def test_group_identity_cannot_be_claimed_by_editor_headers(team):
    create_group(team)
    headers = {'Authorization':'Bearer test-editor', 'X-Editor-User':'member@example.com',
               'X-Golive-Groups':'Design'}
    assert not editor_api.check_editor_auth(headers, team.site, cfg=team.cfg)[0]
    assert not editor_api.check_editor_auth(headers, team.site, cfg=team.cfg,
        session_user={'email':'outsider@example.com','groups':['Design']})[0]
    assert editor_api.check_editor_auth(headers, team.site, cfg=team.cfg,
        session_user={'email':'member@example.com'})[0]


@pytest.mark.parametrize('role', ['owner', 'superadmin', '', None, ['maintainer']])
def test_invalid_group_role_never_grants_access(team, role):
    gid = team.api('POST', 'permissions/groups', {'name':'Editors'})[1]['group_id']
    assert team.api('POST', f'permissions/groups/{gid}/sites', {'site':'team-page','role':role})[0] == 400
    assert team.groups.list()[0]['grants'] == []
    assert [e['action'] for e in team.groups.events()] == ['create']


@pytest.mark.parametrize('method,path,data', [('POST','',{'name':[]}), ('POST','',{'name':' '}),
    ('POST','/absent/members',{'email':'x@example.com'}), ('POST','/absent/sites',{'site':'missing','role':'viewer'})])
def test_invalid_group_requests(team, method, path, data):
    code, _ = team.api(method, 'permissions/groups' + path, data)
    assert code in (400, 404)
    assert team.groups.list() == []


def test_changes_persist_and_audit_is_transactional_and_idempotent(team):
    gid = create_group(team, email='Member@Example.com')
    assert GroupStore().role('MEMBER@example.com', team.site['site_id']) == 'maintainer'
    count = len(team.groups.events())
    assert team.api('POST', f'permissions/groups/{gid}/members', {'email':'member@example.com'})[1]['changed'] is False
    assert team.api('POST', f'permissions/groups/{gid}/sites', {'site':'team-page','role':'maintainer'})[1]['changed'] is False
    assert len(team.groups.events()) == count == 3
    import sqlite3
    with sqlite3.connect(team.groups.db_path) as c:
        c.execute("CREATE TRIGGER reject_group_audit BEFORE INSERT ON permission_group_events BEGIN SELECT RAISE(ABORT,'audit failed'); END;")
    assert team.api('DELETE', f'permissions/groups/{gid}')[0] == 503
    assert GroupStore().role('member@example.com', team.site['site_id']) == 'maintainer'
    assert all(e['actor'] == 'root@example.com' for e in team.groups.events())


def test_group_store_failure_denies_inherited_access_without_losing_owner(team, monkeypatch):
    create_group(team)
    from golive.backends.registry import group_store
    def unavailable():
        raise OSError('sensitive-path')
    monkeypatch.setattr(group_store, 'get_group_store', unavailable)
    assert authz.site_role(authz.Identity('member@example.com'), team.site) == ''
    assert authz.site_role(authz.Identity('owner@example.com'), team.site) == 'owner'
    # group_api imports factory at module import, patch its bound name as well.
    from golive.server import group_api
    monkeypatch.setattr(group_api, 'get_group_store', unavailable)
    code, body = team.api('GET', 'permissions/groups')
    assert code == 503 and 'sensitive-path' not in json.dumps(body)


def test_group_audit_pages_cover_every_change_without_duplicate_entries(team):
    create_group(team)
    code, first = team.api('GET', 'permissions/groups/audit', query={'limit':['2']})
    assert code == 200 and len(first['events']) == 2
    code, last = team.api('GET', 'permissions/groups/audit',
                          query={'limit':['2'], 'before':[str(first['next_before'])]})
    assert code == 200 and len(last['events']) == 1 and last['next_before'] is None
    assert [e['action'] for e in first['events'] + last['events']] == ['grant','member.add','create']


def test_failed_atomic_replace_preserves_old_content_and_releases_lock(team, monkeypatch):
    original = team.storage.read(team.site['site_id'])
    replace = os.replace
    def fail(*args):
        raise OSError('simulated write failure')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        team.storage.publish_if_revision('<h1>replacement</h1>', team.site['site_id'], content_revision(original))
    assert team.storage.read(team.site['site_id']) == original
    assert not list(team.storage.site_path(team.site['site_id']).parent.glob('.content-*'))
    monkeypatch.setattr(os, 'replace', replace)
    team.storage.publish_if_revision('<h1>retry</h1>', team.site['site_id'], content_revision(original))
    assert team.storage.read(team.site['site_id']) == '<h1>retry</h1>'


@pytest.fixture
def http_team(team):
    from golive.server.app import make_server
    from golive.backends.auth.oauth import OIDCAuth
    server = make_server('127.0.0.1', 0)
    oidc = OIDCAuth(issuer='https://identity.test.invalid', client_id='fixture', cookie_secret='fixture-cookie-secret')
    # Seed an actual signed session: tests exercise cookie verification and
    # revocation after login, not external IdP discovery/code exchange.
    oidc._sessions['member'] = {'email':'member@example.com','exp':time.time()+300}
    oidc._sessions['root'] = {'email':'root@example.com','exp':time.time()+300}
    server.RequestHandlerClass.oidc = oidc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    team.base = f'http://127.0.0.1:{server.server_port}'
    team.member_cookie = 'golive_session=' + oidc._sign_sid('member')
    team.root_cookie = 'golive_session=' + oidc._sign_sid('root')
    yield team
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_http_content_revision_read_stale_save_and_missing_header(http_team):
    team = http_team
    headers = {'Authorization':'Bearer test-editor', 'X-Editor-User':'owner@example.com'}
    url = team.base + '/api/sites/team-page/content'
    r = requests.get(url, headers=headers, timeout=5)
    assert r.status_code == 200
    revision = r.json()['revision']
    assert revision == r.headers['ETag'] == content_revision(r.json()['html'])
    page = requests.get(team.base + '/team-page', timeout=5)
    assert page.headers['ETag'] == revision
    assert f'content="{revision.strip(chr(34))}"' in page.text
    headers['Content-Type'] = 'text/html'
    assert requests.put(url, headers=headers, data=b'<h1>missing</h1>', timeout=5).status_code == 428
    headers['If-Match'] = revision
    assert requests.put(url, headers=headers, data=b'<h1>editor one</h1>', timeout=5).status_code == 200
    conflict = requests.put(url, headers=headers, data=b'<h1>editor two</h1>', timeout=5)
    assert conflict.status_code == 409 and conflict.json()['code'] == 'edit_conflict'
    assert 'editor one' in team.storage.read(team.site['site_id'])


def test_http_signed_session_group_access_revoke_and_forgery(http_team):
    team = http_team
    gid = create_group(team)
    url = team.base + '/api/sites/team-page/content'
    headers = {'Cookie':team.member_cookie, 'X-Editor-User':'owner@example.com'}
    r = requests.get(url, headers=headers, timeout=5)
    assert r.status_code == 200
    headers.update({'If-Match':r.json()['revision'], 'Content-Type':'text/html'})
    assert requests.put(url, headers=headers, data=b'<h1>group member</h1>', timeout=5).status_code == 200
    assert requests.get(team.base + '/api/admin/sites/team-page', headers=headers, timeout=5).json()['role'] == 'maintainer'
    assert requests.post(team.base + '/api/admin/permissions/groups', headers=headers, json={'name':'Escalate'}, timeout=5).status_code == 403
    # Real HTTP revocation, using an operator token; old session stays signed.
    assert requests.delete(team.base + f'/api/admin/permissions/groups/{gid}/members',
        headers={'Authorization':'Bearer test-operator'}, json={'email':'member@example.com'}, timeout=5).status_code == 200
    assert requests.get(url, headers=headers, timeout=5).status_code == 403
    assert requests.put(url, headers=headers, data=b'<h1>revoked</h1>', timeout=5).status_code == 403
    assert requests.get(url, headers={'Cookie':team.member_cookie + 'forged'}, timeout=5).status_code in (401, 403)
    assert requests.get(team.base + '/api/admin/permissions/groups', timeout=5).status_code == 401
