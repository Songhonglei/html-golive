"""ENV-02: real HTTP proxy/HTTPS CONNECT/CA verification on isolated sockets."""
import base64
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import select
import socket
import ssl
import subprocess
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
import requests

from golive.backends.postgrest import PostgrestClient
from golive.cli import main
from golive.config import reset_config
from golive.core.paths import reset_cache


@contextlib.contextmanager
def serving(server):
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.fixture
def environment(tmp_path,monkeypatch):
    for key in list(__import__('os').environ):
        if key.lower().endswith('_proxy'):monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('GOLIVE_HOME',str(tmp_path/'home'))
    monkeypatch.setenv('GOLIVE_CONFIG',str(tmp_path/'golive.yaml'))
    (tmp_path/'golive.yaml').write_text('{}\n');reset_config();reset_cache()
    cert=tmp_path/'ca.pem';key=tmp_path/'ca.key'
    result=subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','2','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],capture_output=True,text=True)
    assert result.returncode==0
    cert.chmod(0o600);key.chmod(0o600)
    monkeypatch.setenv('REQUESTS_CA_BUNDLE',str(cert))
    yield cert,key
    reset_config();reset_cache()


def test_real_proxy_inheritance_https_connect_trust_and_timeout(environment,monkeypatch,capsys):
    cert,key=environment;events=[]
    class Origin(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            events.append(('origin',self.path))
            body=b'[{"id":"verified"}]';self.send_response(200)
            self.send_header('Content-Range','0-0/12050');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_CONNECT(self):
            events.append(('connect',self.path,self.headers.get('Proxy-Authorization')))
            host,port=self.path.rsplit(':',1)
            if host!='localhost':self.send_error(403);return
            with socket.create_connection(('127.0.0.1',int(port)),timeout=2) as remote:
                self.send_response(200);self.end_headers()
                try:
                    while True:
                        ready,_,_=select.select([self.connection,remote],[],[],2)
                        if not ready:return
                        for source in ready:
                            data=source.recv(65536)
                            if not data:return
                            (remote if source is self.connection else self.connection).sendall(data)
                except OSError:return
        def do_GET(self):
            events.append(('proxy',self.path,self.headers.get('Proxy-Authorization')))
            target=urlsplit(self.path)
            if target.path.endswith('/slow'):
                time.sleep(.4);return
            if target.hostname!='localhost':self.send_error(403);return
            # Real forward-proxy hop, using a Session with env disabled to avoid recursion.
            with requests.Session() as direct:
                direct.trust_env=False
                response=direct.get(self.path,timeout=2,headers={'apikey':self.headers.get('apikey','')})
            self.send_response(response.status_code)
            self.send_header('Content-Range',response.headers['Content-Range'])
            self.send_header('Content-Length',str(len(response.content)))
            self.end_headers();self.wfile.write(response.content)
    http=ThreadingHTTPServer(('127.0.0.1',0),Origin)
    https=ThreadingHTTPServer(('127.0.0.1',0),Origin)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    https.socket=context.wrap_socket(https.socket,server_side=True)
    proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
    proxy_url=f'http://proxy-user:private-proxy-password@127.0.0.1:{proxy.server_port}'
    monkeypatch.setenv('HTTP_PROXY',proxy_url);monkeypatch.setenv('HTTPS_PROXY',proxy_url)
    expected='Basic '+base64.b64encode(b'proxy-user:private-proxy-password').decode()
    with serving(http),serving(https),serving(proxy):
        for scheme,port in [('http',http.server_port),('https',https.server_port)]:
            client=PostgrestClient(f'{scheme}://localhost:{port}','private-service-key',timeout=2)
            rows,total=client.select('records',count=True)
            assert total==12050 and rows==[{'id':'verified'}]
        assert any(e[0]=='proxy' and e[2]==expected for e in events)
        assert any(e[0]=='connect' and e[2]==expected for e in events)
        # Remove explicit trust: requests must reject this private CA.
        monkeypatch.delenv('REQUESTS_CA_BUNDLE')
        with pytest.raises(requests.exceptions.SSLError):
            PostgrestClient(f'https://localhost:{https.server_port}','private-service-key').count('records')
        monkeypatch.setenv('REQUESTS_CA_BUNDLE',str(cert))
        client=PostgrestClient(f'http://localhost:{http.server_port}','private-service-key',timeout=.05)
        def backend():client.select('slow')
        with patch('golive.backends.factory.get_template_store',side_effect=backend):
            status=main(['data','list','--json'])
        captured=capsys.readouterr();value=json.loads(captured.out)
        assert status==1 and value['code']=='backend_timeout' and not captured.err
        assert 'private-' not in json.dumps(value)
