"""A reused PID cannot give an unrelated endpoint service-record priority."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from golive.cli import main
from golive.config import reset_config
from golive.core.paths import reset_cache
from golive.core import service


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    config_port = free_port()
    config = home / 'golive.yaml'
    config.write_text(f'server:\n  host: 127.0.0.1\n  port: {config_port}\n')
    monkeypatch.setenv('GOLIVE_HOME', str(home))
    monkeypatch.setenv('GOLIVE_CONFIG', str(config))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.delenv('GOLIVE_TOKEN', raising=False)
    reset_cache(); reset_config()
    yield home, config_port
    reset_cache(); reset_config()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def call(command, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main([command, '--json', *args])
    assert code == 0, output.getvalue()
    result = json.loads(output.getvalue())
    return result['server' if command == 'context' else 'service']


def write_record(home, port, pid=None):
    path = home / 'golive.pid'
    path.write_text(json.dumps({'pid': pid or os.getpid(), 'host': '127.0.0.1',
                                'port': port, 'version': '0.9.7.post1'}))
    return path


@contextlib.contextmanager
def endpoint(payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown(); server.server_close(); worker.join()


@pytest.mark.parametrize('command', ['context', 'doctor'])
def test_live_sleep_pid_without_listener_is_stale(project, command):
    home, expected_port = project
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        path = write_record(home, free_port(), child.pid)
        before = path.read_bytes()
        result = call(command)
        assert result['port'] == expected_port
        assert result['service_record']['reason'] == 'health_unavailable'
        assert not result['service_record']['valid']
        assert result.get('port_source', 'config') == 'config'
        if command == 'doctor':
            assert result['stale_pidfile'] and not result['managed']
            assert result['pid'] is None
        assert path.read_bytes() == before and child.poll() is None
    finally:
        child.terminate(); child.wait(timeout=5)


@pytest.mark.parametrize('command', ['context', 'doctor'])
@pytest.mark.parametrize('case,reason', [
    ('http', 'health_unavailable'), ('pid', 'pid_mismatch'), ('home', 'home_mismatch'),
    ('missing_pid', 'pid_mismatch'), ('missing_home', 'home_mismatch'),
    ('relative_home', 'home_mismatch'),
])
def test_health_identity_must_match(project, command, case, reason):
    home, expected_port = project
    payload = {'status': 'ok', 'pid': os.getpid(), 'home': str(home),
               'version': '0.9.7.post1', 'data_backend': 'sqlite'}
    if case == 'http': payload = {'message': 'ordinary HTTP service'}
    if case == 'pid': payload['pid'] += 1
    if case == 'home': payload['home'] = str(home.parent / 'other')
    if case == 'missing_pid': payload.pop('pid')
    if case == 'missing_home': payload.pop('home')
    if case == 'relative_home': payload['home'] = '.'
    with endpoint(payload) as port:
        path = write_record(home, port)
        before = path.read_bytes()
        result = call(command)
        assert result['port'] == expected_port
        assert result['service_record']['reason'] == reason
        if command == 'doctor': assert result['stale_pidfile'] and not result['managed']
        else: assert result['port_source'] == 'config'
        assert path.read_bytes() == before


@pytest.mark.parametrize('command', ['context', 'doctor'])
def test_valid_record_preserves_version_and_backend_drift(project, command):
    home, _ = project
    payload = {'status': 'ok', 'pid': os.getpid(), 'home': str(home),
               'version': 'older-version', 'data_backend': 'mysql'}
    with endpoint(payload) as port:
        write_record(home, port)
        result = call(command)
        assert result['port'] == port and result['running']
        assert result['version'] == 'older-version' and result['data_backend'] == 'mysql'
        assert result['backend_match'] is False
        assert result['service_record']['valid']
        if command == 'doctor':
            assert result['managed'] and not result['stale_pidfile'] and not result['version_match']
        else:
            assert result['port_source'] == 'service_record' and not result['matches_cli']
        # Explicit default is an override even when a valid service record exists.
        explicit = call(command, '--port', '8787')
        assert explicit['port'] == 8787
        if command == 'context': assert explicit['port_source'] == 'cli'
        else: assert not explicit['managed']


@pytest.mark.parametrize('command', ['context', 'doctor'])
@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'dead', 'bad_port'])
def test_missing_dead_and_corrupt_records(project, command, kind, monkeypatch):
    home, expected_port = project
    if kind == 'corrupt': (home / 'golive.pid').write_text('{broken')
    if kind == 'dead':
        write_record(home, free_port())
        monkeypatch.setattr(service, 'pid_alive', lambda pid: False)
    if kind == 'bad_port': write_record(home, 'bad')
    result = call(command)
    assert result['port'] == expected_port
    assert not result['service_record']['valid']
    if command == 'doctor': assert result['stale_pidfile'] == (kind != 'missing')
    else: assert result['port_source'] == 'config'


def test_context_missing_home_is_read_only(tmp_path, monkeypatch):
    home = tmp_path / 'absent'
    monkeypatch.setenv('GOLIVE_HOME', str(home))
    monkeypatch.delenv('GOLIVE_CONFIG', raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.chdir(tmp_path)
    reset_cache(); reset_config()
    try:
        result = call('context')
        assert result['port'] == 8787 and result['port_source'] == 'default'
        assert not home.exists()
    finally:
        reset_cache(); reset_config()


@pytest.mark.parametrize('command', ['context', 'doctor'])
def test_real_golive_server_identity(project, command):
    from golive.server.app import make_server
    home, _ = project
    server = make_server(host='127.0.0.1', port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        record = write_record(home, server.server_port)
        before = record.read_bytes()
        result = call(command)
        assert result['port'] == server.server_port and result['running']
        assert result['service_record']['valid'] and result['backend_match']
        if command == 'doctor': assert result['managed'] and result['version_match']
        else: assert result['port_source'] == 'service_record' and result['matches_cli']
        assert record.read_bytes() == before
    finally:
        server.shutdown(); server.server_close(); worker.join()


@pytest.mark.parametrize('command', ['context', 'doctor'])
@pytest.mark.parametrize('record_value', [
    {'pid': 10**100, 'port': 8791},
    {'pid': os.getpid(), 'port': 8791.25},
    {'pid': os.getpid(), 'port': True},
])
def test_malformed_record_never_crashes_or_overrides(project, command, record_value):
    home, expected_port = project
    (home / 'golive.pid').write_text(json.dumps(record_value))
    result = call(command)
    assert result['port'] == expected_port and not result['service_record']['valid']
    if command == 'doctor': assert result['stale_pidfile']
