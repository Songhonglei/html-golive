"""Two actual processes/HOMEs, shared control DB, signed local IdP flow.

Pages/registry here are identical isolated fixtures, NOT a content replication
implementation. The test proves shared identity/control state only.
"""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import requests

CHILD = r'''
import json, sys, threading
from golive.config import Config, set_config
from golive.backends.registry.sqlite_store import SqliteRegistry
from golive.backends.storage.local import LocalStorage
from golive.server.app import make_server
cfg = Config()
cfg.auth.provider = 'oidc'
cfg.auth.oidc_issuer = sys.argv[1]
cfg.auth.oidc_client_id = 'p3-client'
cfg.auth.oidc_redirect_uri = 'http://gateway.test/auth/callback'
cfg.admin.admins = ['root@example.com']
cfg.data.backend = 'none'
set_config(cfg)
registry = SqliteRegistry()
if not registry.get('shared-site'):
    site = registry.create('P3 fixture', 'team', owner='owner@example.com')
    with registry._conn() as c:
        c.execute("UPDATE sites SET site_id='shared-site',editable=1 WHERE site_id=?", (site['site_id'],))
    LocalStorage().publish('<h1>Shared identity fixture</h1>', 'shared-site', False)
server = make_server('127.0.0.1', 0)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
print(json.dumps({'port': server.server_port, 'pid': __import__('os').getpid(),
                  'module': __import__('golive').__file__}), flush=True)
sys.stdin.readline()
server.shutdown()
server.server_close()
thread.join(3)
'''


@pytest.fixture
def pair(tmp_path):
    pytest.importorskip('cryptography')
    from tests.test_oidc_hardening import _generate_rsa_keypair, _sign_jwt
    private, _, jwk = _generate_rsa_keypair()
    codes, token_exchanges = {}, []

    class IdP(BaseHTTPRequestHandler):
        def reply(self, code, body, location=None):
            payload = json.dumps(body).encode()
            self.send_response(code)
            if location:
                self.send_header('Location', location)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == '/.well-known/openid-configuration':
                return self.reply(200, dict(issuer=issuer, authorization_endpoint=issuer+'/authorize',
                    token_endpoint=issuer+'/token', jwks_uri=issuer+'/jwks'))
            if path.path == '/jwks':
                return self.reply(200, {'keys': [jwk]})
            if path.path == '/authorize':
                query = {k: v[0] for k, v in parse_qs(path.query).items()}
                code = secrets.token_hex(16)
                codes[code] = dict(query, email=self.headers['X-Test-User'])
                return self.reply(302, {}, query['redirect_uri']+'?'+urlencode(
                    {'code': code, 'state': query['state']}))
            self.reply(404, {})

        def do_POST(self):
            form = {k: v[0] for k, v in parse_qs(
                self.rfile.read(int(self.headers['Content-Length'])).decode()).items()}
            record = codes.pop(form.get('code'), None)
            if not record:
                return self.reply(400, {'error': 'invalid_grant'})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'].encode()).digest()).rstrip(b'=').decode()
            if challenge != record['code_challenge'] or form['redirect_uri'] != record['redirect_uri']:
                return self.reply(400, {'error': 'invalid_grant'})
            token_exchanges.append(record['email'])
            now = time.time()
            token = _sign_jwt(private, {'alg': 'RS256', 'kid': 'test-key-1'},
                {'iss': issuer, 'aud': 'p3-client', 'sub': record['email'],
                 'email': record['email'], 'nonce': record['nonce'], 'iat': now, 'exp': now+300})
            self.reply(200, {'id_token': token})

        def log_message(self, *args):
            pass

    idp = ThreadingHTTPServer(('127.0.0.1', 0), IdP)
    issuer = 'http://127.0.0.1:%s' % idp.server_port
    thread = threading.Thread(target=idp.serve_forever, daemon=True)
    thread.start()
    active = []
    import golive
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GOLIVE_', 'PYTHON'))}
    env.update(HOME=str(tmp_path/'os-home'), XDG_CONFIG_HOME=str(tmp_path/'xdg'),
               GOLIVE_STATE_DIR=str(tmp_path/'control'),
               PYTHONPATH=str(Path(golive.__file__).resolve().parent.parent),
               NO_PROXY='127.0.0.1,localhost')
    config = tmp_path/'empty.yaml'
    config.write_text('{}')
    env['GOLIVE_CONFIG'] = str(config)

    def start(name):
        err = open(tmp_path/(name+'-stderr.log'), 'a')
        proc = subprocess.Popen([sys.executable, '-u', '-c', CHILD, issuer],
            env=dict(env, GOLIVE_HOME=str(tmp_path/name)), cwd=tmp_path,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True)
        active.append((proc, err))
        # Child writes one line only after the HTTP socket is ready.
        import select
        assert select.select([proc.stdout], [], [], 15)[0], 'child startup timed out'
        line = proc.stdout.readline()
        assert line, (tmp_path/(name+'-stderr.log')).read_text()
        record = json.loads(line)
        assert Path(record['module']).resolve() == Path(golive.__file__).resolve()
        return proc, 'http://127.0.0.1:%s' % record['port']

    def stop(proc):
        if proc.poll() is None:
            proc.communicate('stop\n', timeout=10)
        assert proc.returncode == 0

    def get(base, path, cookie=''):
        return requests.get(base+path, headers={'Cookie': cookie}, timeout=5, allow_redirects=False)

    def prepare(base, email):
        auth = get(base, '/auth/login')
        assert auth.status_code == 302
        redirect = requests.get(auth.headers['Location'], headers={'X-Test-User': email},
                                timeout=5, allow_redirects=False)
        assert redirect.status_code == 302
        return urlsplit(redirect.headers['Location']).path + '?' + urlsplit(redirect.headers['Location']).query

    def login(first, second, email):
        callback = prepare(first, email)
        response = get(second, callback)
        assert response.status_code == 302, response.text
        assert get(first, callback).status_code == 401
        return response.headers['Set-Cookie'].split(';')[0]

    try:
        yield dict(start=start, stop=stop, get=get, login=login, prepare=prepare,
                   root=tmp_path, exchanges=token_exchanges)
    finally:
        for proc, err in active:
            if proc.poll() is None:
                try:
                    proc.communicate('stop\n', timeout=10)
                except subprocess.TimeoutExpired:
                    proc.terminate()  # only child created by this fixture
                    proc.wait(5)
            err.close()
        idp.shutdown()
        idp.server_close()
        thread.join(3)


def test_two_process_signed_login_restart_permissions_logout_and_store_failure(pair):
    start, stop, get, login = (pair[k] for k in ['start', 'stop', 'get', 'login'])
    process_a, a = start('a')
    process_b, b = start('b')
    assert process_a.pid != process_b.pid
    root = login(a, b, 'root@example.com')
    member = login(a, b, 'member@example.com')
    assert pair['exchanges'] == ['root@example.com', 'member@example.com']
    for base in [a, b]:
        assert get(base, '/auth/me', member).status_code == 200
        assert get(base, '/api/sites/team/content', member).status_code == 403

    def change(base, method, path, body):
        response = requests.request(method, base+'/api/admin/permissions/'+path,
            json=body, headers={'Cookie': root}, timeout=5)
        assert response.status_code == 200, response.text
        return response.json()

    group = change(a, 'POST', 'groups', {'name': 'P3 team'})['group_id']
    change(a, 'POST', 'groups/'+group+'/members', {'email': 'member@example.com'})
    change(a, 'POST', 'groups/'+group+'/sites', {'site': 'team', 'role': 'maintainer'})
    assert all(get(base, '/api/sites/team/content', member).status_code == 200 for base in [a, b])
    # Pending login and existing sessions both survive process replacement.
    pending = pair['prepare'](a, 'restart@example.com')
    stop(process_a)
    process_a, a = start('a')
    assert get(b, pending).status_code == 302
    assert get(a, '/auth/me', member).status_code == 200
    assert get(a, '/api/sites/team/content', member).status_code == 200
    change(a, 'DELETE', 'groups/'+group+'/members', {'email': 'member@example.com'})
    assert all(get(base, '/api/sites/team/content', member).status_code == 403 for base in [a, b])
    assert get(b, '/auth/me', member).status_code == 200  # logged in, access revoked
    change(a, 'POST', 'admins', {'email': 'member@example.com'})
    assert all(get(base, '/api/admin/permissions', member).status_code == 200 for base in [a, b])
    change(a, 'DELETE', 'admins', {'email': 'member@example.com'})
    assert all(get(base, '/api/admin/permissions', member).status_code == 403 for base in [a, b])
    assert get(b, '/auth/logout', member).status_code == 200
    assert all(get(base, '/auth/me', member).status_code == 401 for base in [a, b])
    stop(process_a)
    process_a, a = start('a')
    assert get(a, '/auth/me', member).status_code == 401
    assert get(a, '/auth/me', root).status_code == 200
    (pair['root']/'control'/'sessions.db').write_bytes(b'broken fixture state')
    response = get(a, '/auth/me', root)
    assert response.status_code == 503 and response.json()['code'] == 'session_store_unavailable'
    response = get(b, '/auth/logout', root)
    assert response.status_code == 503 and 'Set-Cookie' not in response.headers
