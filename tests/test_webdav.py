"""Real loopback WebDAV requests; storage/failure/security contracts."""

import pytest
import requests

from golive.backends.storage.webdav import WebDAVStorage, WebDAVError
from tests.fake_webdav import DAVFixture


@pytest.fixture
def dav():
    fixture = DAVFixture()
    try:
        yield fixture, WebDAVStorage(fixture.url, 'test-user', 'test-password', 2)
    finally:
        fixture.close()


def test_publish_read_snapshots_rollback_and_scoped_delete(dav):
    fixture, store = dav
    assert not store.exists('site-a')
    assert store.list_snapshots('site-a') == []
    with pytest.raises(FileNotFoundError):
        store.read('site-a')
    assert store.publish('<h1>初始</h1>', 'site-a') == 'webdav://site-a/index.html'
    assert store.exists('site-a') and store.read('site-a') == '<h1>初始</h1>'
    for i in range(12):
        store.publish('<h1>%s</h1>' % i, 'site-a')
    snapshots = store.list_snapshots('site-a')
    assert len(snapshots) == 10
    expected = fixture.files['/dav/' + snapshots[-1]['path']].decode()
    store.rollback('site-a', snapshots[-1]['ts'])
    assert store.read('site-a') == expected
    assert len(store.list_snapshots('site-a')) == 10
    store.publish('unrelated', 'site-b')
    store.delete('site-a')
    store.delete('site-a')
    assert not store.exists('site-a')
    assert store.read('site-b') == 'unrelated'
    assert not any('/site-a/' in key for key in fixture.files)
    assert store.public_url('site-a') == ''
    assert not hasattr(store, 'publish_if_revision')  # editor must return 501


@pytest.mark.parametrize('status', [301, 302, 307, 308, 409, 423, 500, 507])
def test_http_failures_do_not_follow_or_echo_response(dav, status):
    fixture, store = dav
    fixture.failure = status, b'password=remote-secret'
    with pytest.raises(WebDAVError) as exc:
        store.publish('content', 'site-a', False)
    assert 'remote-secret' not in str(exc.value)
    assert 'test-password' not in str(exc.value)
    assert len(fixture.calls) == 1


def test_credentials_fail_explicitly_never_as_missing(dav):
    fixture, store = dav
    store.auth = ('wrong-user', 'private-password')
    for operation in [lambda: store.exists('site-a'), lambda: store.read('site-a'),
                      lambda: store.delete('site-a'), lambda: store.list_snapshots('site-a')]:
        with pytest.raises(PermissionError, match='access denied'):
            operation()


@pytest.mark.parametrize('site', ['..', '../other', 'a/b', '%2e%2e', '', 'a?token=x', 'a\\b', 'a\x00'])
def test_path_boundaries_before_io(dav, site):
    fixture, store = dav
    with pytest.raises(ValueError):
        store.delete(site)
    with pytest.raises(ValueError):
        store.publish('html', site, False)
    assert fixture.calls == []


@pytest.mark.parametrize('url', ['https://user:secret@host/dav', 'http://nas.local/dav',
    'https://nas/dav?token=secret', 'https://nas/dav#secret', 'https://nas/dav/../x',
    'https://nas/dav/%2e%2e/x', 'file:///tmp/dav', 'https://nas:bad/dav'])
def test_unsafe_endpoint_configuration(url):
    with pytest.raises(ValueError) as exc:
        WebDAVStorage(url)
    assert 'secret' not in str(exc.value)


@pytest.mark.parametrize('payload', [b'not XML', b'<other/>',
    b'<!DOCTYPE a [<!ENTITY secret "expanded">]><a/>', b'<d:multistatus xmlns:d="DAV:">'])
def test_untrusted_xml_rejected(dav, payload):
    fixture, store = dav
    fixture.propfind = payload
    with pytest.raises(WebDAVError):
        store.list_snapshots('site-a')


def test_foreign_propfind_hrefs_cannot_delete_other_resources(dav):
    fixture, store = dav
    ts = '20261103_120000_123456'
    fixture.propfind = ('<d:multistatus xmlns:d="DAV:">' + ''.join(
        '<d:response><d:href>%s</d:href><d:propstat><d:status>HTTP/1.1 200 OK</d:status>'
        '<d:prop><d:getcontentlength>10</d:getcontentlength></d:prop></d:propstat></d:response>' % href
        for href in ['https://other/dav/site-a/backups/' + ts + '.html',
                     '/dav/site-b/backups/' + ts + '.html',
                     '/dav/site-a/backups/%2e%2e/' + ts + '.html']) + '</d:multistatus>').encode()
    assert store.list_snapshots('site-a') == []


def test_partial_delete_not_success(dav):
    fixture, store = dav
    fixture.failure = 207, b'<multistatus>partial deletion</multistatus>'
    with pytest.raises(WebDAVError, match='207'):
        store.delete('site-a')


def test_failed_snapshot_read_or_put_does_not_replace_saved_page(dav):
    fixture, store = dav
    store.publish('original', 'site-a', False)
    fixture.failures['GET', '/dav/site-a/index.html'] = 500, b'private remote body'
    with pytest.raises(WebDAVError):
        store.publish('new', 'site-a')
    assert fixture.files['/dav/site-a/index.html'] == b'original'
    fixture.failures.clear()
    fixture.failures['PUT', '/dav/site-a/index.html'] = 507, b'private remote body'
    with pytest.raises(WebDAVError):
        store.publish('new', 'site-a')
    assert fixture.files['/dav/site-a/index.html'] == b'original'
    assert len(store.list_snapshots('site-a')) == 1


def test_response_limit_and_incomplete_listing(dav, monkeypatch):
    fixture, store = dav
    monkeypatch.setattr('golive.backends.storage.webdav.MAX_RESPONSE', 200)
    fixture.files['/dav/site-a/index.html'] = b'x' * 201
    with pytest.raises(WebDAVError, match='size limit'):
        store.read('site-a')
    fixture.propfind = b'<d:multistatus xmlns:d="DAV:"><d:response><d:status>HTTP/1.1 403 Forbidden</d:status></d:response></d:multistatus>'
    with pytest.raises(WebDAVError, match='incomplete'):
        store.list_snapshots('site-a')


def test_timeout_redaction_and_default_tls(monkeypatch):
    def request(*args, **kwargs):
        assert kwargs.get('verify', True) is True
        assert kwargs['allow_redirects'] is False
        assert kwargs['timeout'] == (0.25, 0.25)
        raise requests.exceptions.SSLError('private-password https://user:secret@nas')
    monkeypatch.setattr(requests, 'request', request)
    with pytest.raises(WebDAVError) as exc:
        WebDAVStorage('https://nas/dav', timeout=.25).read('site-a')
    assert 'secret' not in str(exc.value) and 'private-password' not in str(exc.value)


def test_config_factory_and_invalid_timeout(tmp_path, monkeypatch):
    from golive.config import load_config, ConfigError
    from golive.backends.factory import get_storage
    monkeypatch.setenv('MY_DAV_PASS', 'password-kept-server-side')
    config = tmp_path / 'dav.yaml'
    config.write_text('storage:\n  backend: webdav\n  webdav:\n    url: https://nas/dedicated/\n    password_env: MY_DAV_PASS\n    timeout: 7.5\n')
    cfg = load_config(str(config), apply_settings=False)
    store = get_storage(cfg)
    assert store.timeout == 7.5 and store.auth[1] == 'password-kept-server-side'
    for value in ['0', 'nan', '121', 'nope']:
        config.write_text('storage:\n  webdav:\n    timeout: ' + value)
        with pytest.raises(ConfigError):
            load_config(str(config), apply_settings=False)


def test_golive_serve_reads_webdav_and_editor_returns_501(dav, tmp_path, monkeypatch):
    import os
    import threading
    from golive.config import Config, set_config, reset_config
    from golive.core import paths
    from golive.core.content_revision import content_revision
    from golive.server.app import make_server
    from golive.backends.factory import get_registry, get_storage
    fixture, _ = dav
    for key in list(os.environ):
        if key.startswith('GOLIVE_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('GOLIVE_HOME', str(tmp_path/'golive'))
    monkeypatch.setenv('GOLIVE_TOKEN', 'fixture-operator')
    monkeypatch.setenv('GOLIVE_WEBDAV_USERNAME', 'test-user')
    monkeypatch.setenv('GOLIVE_WEBDAV_PASSWORD', 'test-password')
    monkeypatch.setattr(paths, '_resolved_home', None)
    cfg = Config()
    cfg.storage.backend, cfg.storage.webdav_url = 'webdav', fixture.url
    cfg.auth.provider, cfg.auth.token = 'token', 'fixture-operator'
    cfg.editor.token, cfg.data.backend = 'fixture-editor', 'none'
    set_config(cfg)
    server = None
    try:
        registry, storage = get_registry(), get_storage()
        site = registry.create('DAV served fixture', 'dav-page', owner='owner@example.com')
        registry.set_editable(site['site_id'], True)
        html = '<html><head><title>DAV</title></head><body><h1>remote page</h1></body></html>'
        storage.publish(html, site['site_id'], False)
        server = make_server('127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:%s' % server.server_port
        response = requests.get(base+'/dav-page', timeout=5)
        assert response.status_code == 200 and '<h1>remote page</h1>' in response.text
        response = requests.put(base+'/api/sites/dav-page/content', json={'html': '<h1>new</h1>'},
            headers={'Authorization': 'Bearer fixture-editor', 'X-Editor-User': 'owner@example.com',
                     'If-Match': content_revision(html)}, timeout=5)
        assert response.status_code == 501
        assert storage.read(site['site_id']) == html
        assert storage.list_snapshots(site['site_id']) == []
        assert 'test-password' not in response.text
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(3)
        reset_config()
