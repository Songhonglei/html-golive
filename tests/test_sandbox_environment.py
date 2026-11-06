"""ENV-01: immutable ownership before Docker control; opt-in real lifecycle/TLS."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import socket
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/mysql_sandbox.py'
spec = importlib.util.spec_from_file_location('mysql_sandbox', SCRIPT)
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


def state(root):
    return {'engine': 'docker', 'container': 'golive-mysql-' + 'a'*12,
            'container_id': 'b'*64, 'sandbox_id': 'owned', 'directory': str(root)}


@pytest.mark.parametrize('reply',[
    'c'*64+'\ntrue\nowned\n{root}\n',
    'b'*64+'\ntrue\nother\n{root}\n',
    'b'*64+'\ntrue\nowned\n/other/home\n',
    'b'*64+'\ntrue\n\n{root}\n',
])
def test_mismatched_identity_never_sends_control(tmp_path,reply):
    with patch.object(sandbox.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=reply.format(root=tmp_path),stderr='')) as invoke:
        with pytest.raises(RuntimeError,match='identity mismatch'):sandbox.stop(tmp_path,state(tmp_path))
    assert invoke.call_count==1 and invoke.call_args.args[0][1]=='inspect'


@pytest.mark.parametrize('message,missing', [('Error: No such object',True),('Cannot connect to the Docker daemon',False)])
def test_missing_container_vs_unavailable_daemon_preserves_distinction(tmp_path,message,missing):
    with patch.object(sandbox.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='',stderr=message)):
        if missing:assert sandbox.docker_identity(tmp_path,state(tmp_path)) is None
        else:
            with pytest.raises(RuntimeError,match='preserving'):sandbox.docker_identity(tmp_path,state(tmp_path))


def test_failure_log_is_private_scrubbed_and_does_not_include_arguments(tmp_path,monkeypatch):
    monkeypatch.setattr(sandbox,'_log_root',tmp_path)
    monkeypatch.setattr(sandbox,'_secrets',['private-password'])
    with patch.object(sandbox.subprocess,'run',side_effect=subprocess.TimeoutExpired(['docker'],120,stderr=b'private-password failed')):
        with pytest.raises(RuntimeError,match='timed out'):sandbox.run(['docker','--private-argument'])
    log=tmp_path/'commands.log'
    assert stat.S_IMODE(log.stat().st_mode)==0o600
    assert 'private' not in log.read_text() and '[redacted]' in log.read_text()


def test_docker_readiness_uses_final_tcp_server_not_temporary_socket(tmp_path,monkeypatch):
    monkeypatch.setattr(sandbox, 'docker_identity', lambda *args: {'id': 'b'*64, 'running': True})
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return '1\n'
    monkeypatch.setattr(sandbox, 'run', run)
    assert sandbox.client(tmp_path, state(tmp_path), 'SELECT 1;') == '1\n'
    command, kwargs = calls[0]
    assert '--protocol=TCP' in command and '--host=127.0.0.1' in command and '--port=3306' in command
    assert '--defaults-extra-file=/run/golive-root.cnf' in command
    assert kwargs['input'] == 'SELECT 1;'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def command(*args):
    return subprocess.run(list(args),capture_output=True,text=True,timeout=120)


def invoke(action,root,*args):
    return command(sys.executable,str(SCRIPT),action,'--directory',str(root),*args)


@pytest.mark.skipif(os.environ.get('GOLIVE_TEST_DOCKER')!='1',reason='explicit isolated Docker acceptance only')
def test_real_docker_lifecycle_permissions_identity_and_mysql_tls(tmp_path,record_property):
    """Uses only a newly labelled container. Never inspect/stop unrelated stacks."""
    pytest.importorskip('pymysql')
    root=tmp_path/'sandbox';port=free_port();service_port=free_port()
    started=invoke('start',root,'--engine','docker','--port',str(port),'--server-port',str(service_port))
    if started.returncode and root.exists():
        saved=sandbox.load(root);owned=sandbox.docker_identity(root,saved)
        detail=command('docker','logs',owned['id']).stdout if owned else ''
        for line in (root/'root.cnf').read_text().splitlines():
            if line.startswith('password='):detail=detail.replace(line.split('=',1)[1],'[redacted]')
        cleanup=invoke('cleanup',root)
        pytest.fail(started.stderr+detail+'; owned cleanup exit='+str(cleanup.returncode))
    assert started.returncode==0,started.stderr
    saved=sandbox.load(root);owned=sandbox.docker_identity(root,saved)
    container=owned['id']
    record_property('image','mysql:8.4.13')
    try:
        variables={}
        for line in (root/'environment.sh').read_text().splitlines():
            key,value=shlex.split(line)[1].split('=',1);variables[key]=value
        password=urlsplit(variables['GOLIVE_MYSQL_DSN']).password
        assert password not in started.stdout+started.stderr
        refused=invoke('start',root,'--engine','docker','--port',str(port),'--server-port',str(service_port))
        assert refused.returncode==1 and 'existing directories' in refused.stderr
        assert stat.S_IMODE(root.stat().st_mode)==0o700
        for name in ('root.cnf','docker.env','environment.sh','sandbox.json'):
            assert stat.S_IMODE((root/name).stat().st_mode)==0o600
        sandbox.client(root,saved,'CREATE TABLE golive_acceptance.restart_proof (id INT); INSERT INTO golive_acceptance.restart_proof VALUES (42);')
        # A copied/mutated record cannot control even the container it names.
        with pytest.raises(RuntimeError):sandbox.stop(root,dict(saved,sandbox_id='replaced'))
        assert sandbox.docker_identity(root,saved)['running']
        assert invoke('stop',root).returncode==0
        assert invoke('stop',root).returncode==0
        assert not sandbox.docker_identity(root,saved)['running']
        assert command('docker','start',container).returncode==0
        for _ in range(90):
            try:
                assert sandbox.client(root,saved,'SELECT id FROM golive_acceptance.restart_proof;').strip()=='42';break
            except RuntimeError:time.sleep(.5)
        else:pytest.fail('owned sandbox did not restart')
        tls=root/'tls';tls.mkdir(mode=0o700)
        def openssl(*args):
            result=command('openssl',*args);assert result.returncode==0,result.stderr
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'ca.key'),'-out',str(tls/'ca.pem'),'-days','2','-subj','/CN=OpenGoLive controlled test CA')
        openssl('req','-newkey','rsa:2048','-nodes','-keyout',str(tls/'server-key.pem'),'-out',str(tls/'server.csr'),'-subj','/CN=localhost')
        (tls/'extensions').write_text('subjectAltName=DNS:localhost\nextendedKeyUsage=serverAuth\n')
        openssl('x509','-req','-in',str(tls/'server.csr'),'-CA',str(tls/'ca.pem'),'-CAkey',str(tls/'ca.key'),'-CAcreateserial','-out',str(tls/'server-cert.pem'),'-days','2','-extfile',str(tls/'extensions'))
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'other.key'),'-out',str(tls/'other.pem'),'-days','2','-subj','/CN=Untrusted test CA')
        for path in tls.iterdir():path.chmod(0o600)
        # Copy only test certificates into the owned volume. No host HOME bind.
        assert command('docker','cp',str(tls),container+':/tmp/golive-tls').returncode==0
        result=command('docker','exec','--user','0',container,'sh','-c',
                       'cp /tmp/golive-tls/ca.pem /var/lib/mysql/ca.pem && cp /tmp/golive-tls/server-cert.pem /var/lib/mysql/server-cert.pem && cp /tmp/golive-tls/server-key.pem /var/lib/mysql/server-key.pem && chown mysql:mysql /var/lib/mysql/ca.pem /var/lib/mysql/server-*.pem && chmod 600 /var/lib/mysql/server-key.pem')
        assert result.returncode==0,result.stderr
        assert command('docker','restart',container).returncode==0
        from golive.backends._mysql import connection_options
        import pymysql
        original=urlsplit(variables['GOLIVE_MYSQL_DSN'])
        def connect(host,ca):
            dsn=original._replace(netloc=f'{original.username}:{original.password}@{host}:{port}',query=urlencode({'ssl_ca':str(ca)})).geturl()
            return pymysql.connect(**connection_options(dsn))
        for _ in range(90):
            try:
                conn=connect('localhost',tls/'ca.pem');break
            except pymysql.err.OperationalError as error:
                if error.args[0] not in (2003,2013):raise
                time.sleep(.5)
        else:pytest.fail('TLS sandbox did not restart')
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
                cipher=cursor.fetchone()[1];assert cipher
                record_property('tls_cipher',cipher)
                cursor.execute('SELECT id FROM golive_acceptance.restart_proof');assert cursor.fetchone()[0]==42
        for host,ca in [('127.0.0.1',tls/'ca.pem'),('localhost',tls/'other.pem')]:
            with pytest.raises(pymysql.err.OperationalError,match='CERTIFICATE_VERIFY_FAILED'):connect(host,ca)
        record_property('tls_scope','controlled loopback Docker endpoint; not external network')
        volumes=json.loads(command('docker','inspect','--format','{{json .Mounts}}',container).stdout)
        volumes=[v['Name'] for v in volumes if v['Type']=='volume']
    finally:
        cleanup=invoke('cleanup',root)
        assert cleanup.returncode==0,cleanup.stderr
    assert not root.exists()
    assert command('docker','inspect',container).returncode!=0
    for volume in volumes:assert command('docker','volume','inspect',volume).returncode!=0


@pytest.mark.skipif(os.environ.get('GOLIVE_TEST_DOCKER')!='1',reason='explicit isolated Docker acceptance only')
def test_real_occupied_port_and_missing_image(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen()
        root=tmp_path/'occupied'
        result=invoke('start',root,'--engine','docker','--port',str(listener.getsockname()[1]),'--server-port',str(free_port()))
        assert result.returncode==1 and not root.exists()
    root=tmp_path/'missing-image'
    try:
        result=invoke('start',root,'--engine','docker','--port',str(free_port()),'--server-port',str(free_port()),'--image','mysql:opengolive-intentionally-missing-image')
        assert result.returncode==1 and (root/'sandbox.json').exists()
        assert 'private sandbox logs' in result.stderr or 'timed out' in result.stderr
        assert stat.S_IMODE((root/'commands.log').stat().st_mode)==0o600
    finally:
        if root.exists():assert invoke('cleanup',root).returncode==0


@pytest.mark.skipif(os.environ.get('GOLIVE_TEST_DOCKER')!='1',reason='explicit isolated Docker acceptance only')
def test_real_unreachable_daemon_does_not_create_resources(tmp_path,monkeypatch):
    monkeypatch.setenv('DOCKER_HOST','unix://'+str(tmp_path/'absent-docker.sock'))
    root=tmp_path/'no-daemon'
    result=invoke('start',root,'--engine','docker','--port',str(free_port()),'--server-port',str(free_port()))
    assert result.returncode==1 and not root.exists()
    assert 'Sandbox command failed' in result.stderr
