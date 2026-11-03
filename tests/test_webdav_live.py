"""Optional real WsgiDAV + verified local TLS (CI P3 job installs it)."""

import datetime
import threading

import pytest

from golive.backends.storage.webdav import WebDAVStorage, WebDAVError


def test_real_webdav_tls_lifecycle_and_certificate_failures(tmp_path, monkeypatch):
    pytest.importorskip('wsgidav')
    pytest.importorskip('cheroot')
    pytest.importorskip('cryptography')
    from wsgidav.wsgidav_app import WsgiDAVApp
    from cheroot import wsgi
    from cheroot.ssl.builtin import BuiltinSSLAdapter
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'P3 isolated CA')])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-datetime.timedelta(minutes=5))
          .not_valid_after(now+datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
              content_commitment=False, data_encipherment=False, key_agreement=False,
              key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')]))
            .issuer_name(ca_name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now-datetime.timedelta(minutes=5))
            .not_valid_after(now+datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca_file, cert_file, key_file = [tmp_path/name for name in ['ca.pem', 'cert.pem', 'key.pem']]
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_file.chmod(0o600)
    root = tmp_path/'dav'
    root.mkdir()
    (root/'dedicated').mkdir()
    app = WsgiDAVApp({'provider_mapping': {'/': str(root)}, 'verbose': 0,
        'logging': {'enable': False}, 'dir_browser': {'enable': False},
        'http_authenticator': {'accept_basic': True, 'accept_digest': False, 'default_to_digest': False},
        'simple_dc': {'user_mapping': {'*': {'fixture-user': {'password': 'fixture-pass'}}}}})

    server = wsgi.Server(('127.0.0.1', 0), app, numthreads=3)
    server.ssl_adapter = BuiltinSSLAdapter(str(cert_file), str(key_file))
    server.prepare()
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    monkeypatch.setenv('NO_PROXY', 'localhost,127.0.0.1')
    monkeypatch.delenv('REQUESTS_CA_BUNDLE', raising=False)
    monkeypatch.delenv('CURL_CA_BUNDLE', raising=False)
    url = 'https://localhost:%s/dedicated/' % port
    store = WebDAVStorage(url, 'fixture-user', 'fixture-pass', 2)
    try:
        with pytest.raises(WebDAVError, match='TLS'):
            store.exists('site-a')  # untrusted CA rejected
        monkeypatch.setenv('REQUESTS_CA_BUNDLE', str(ca_file))
        with pytest.raises(WebDAVError, match='TLS'):
            WebDAVStorage(url.replace('localhost', '127.0.0.1'), 'fixture-user', 'fixture-pass', 2).exists('site-a')
        assert not store.exists('site-a')
        store.publish('initial', 'site-a', False)
        assert store.read('site-a') == 'initial'
        for i in range(12):
            store.publish('version %s' % i, 'site-a')
        assert len(store.list_snapshots('site-a')) == 10
        store.rollback('site-a')
        assert store.read('site-a') == 'version 10'
        with pytest.raises(PermissionError):
            WebDAVStorage(url, 'fixture-user', 'wrong-pass', 2).exists('site-a')
        store.publish('keep', 'unrelated-site', False)
        store.delete('site-a')
        assert not store.exists('site-a')
        assert store.read('unrelated-site') == 'keep'
        assert (root/'dedicated').is_dir()
        assert not (root/'dedicated'/'site-a').exists()
    finally:
        server.stop()
        thread.join(3)
