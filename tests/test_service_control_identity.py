"""REL-01: lifecycle commands may control only identity-verified services."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

from golive.core import service
from golive.config import get_config
from tests.test_service_record_identity import project, endpoint, free_port, write_record


@pytest.fixture
def sleeper():
    child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    try:
        yield child
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize('action', ['stop', 'restart'])
def test_live_unrelated_pid_never_signalled_or_replaced(project, sleeper, action):
    home, _ = project
    record = write_record(home, free_port(), sleeper.pid)
    before = record.read_bytes()
    with patch.object(service, 'start') as start:
        result = getattr(service, action)()
    assert sleeper.poll() is None
    assert not result['ok'] and result['state'] == 'identity-unverified'
    assert record.read_bytes() == before
    start.assert_not_called()


@pytest.mark.parametrize('case', ['pid', 'home', 'missing_pid', 'missing_home', 'http'])
def test_stop_rejects_mismatched_health(project, sleeper, case):
    home, _ = project
    payload = {'status': 'ok', 'pid': sleeper.pid, 'home': str(home)}
    if case == 'pid': payload['pid'] += 1
    if case == 'home': payload['home'] = str(home.parent / 'other')
    if case == 'missing_pid': payload.pop('pid')
    if case == 'missing_home': payload.pop('home')
    if case == 'http': payload = {'message': 'another application'}
    with endpoint(payload) as port:
        record = write_record(home, port, sleeper.pid)
        before = record.read_bytes()
        result = service.stop(timeout=.01)
        assert not result['ok'] and result['state'] == 'identity-unverified'
        assert sleeper.poll() is None and record.read_bytes() == before


@pytest.mark.parametrize('content', ['{broken', '', '{"pid":true,"port":8791}', '{"pid":3.2,"port":8791}', '{"pid":-2,"port":8791}'])
def test_corrupt_record_is_preserved_and_blocks_control(project, content):
    home, _ = project
    path = home / 'golive.pid'; path.write_text(content)
    # Guard the OS boundary even when exercising the broken parser: never signal
    # any PID from a deliberately malformed fixture.
    with patch.object(service, 'start') as start, patch.object(service.os, 'kill', side_effect=PermissionError('fixture signal denied')):
        result = service.restart()
    assert not result['ok'] and path.read_text() == content
    start.assert_not_called()


def test_start_does_not_overwrite_live_unverifiable_record(project, sleeper):
    home, _ = project
    path = write_record(home, free_port(), sleeper.pid); before = path.read_bytes()
    with patch.object(service, '_spawn') as spawn:
        result = service.start(port=free_port())
    assert not result['ok'] and result['state'] == 'identity-unverified'
    spawn.assert_not_called()
    assert sleeper.poll() is None and path.read_bytes() == before


@pytest.mark.parametrize('state', ['failed', 'unmanaged', 'identity-unverified'])
def test_restart_aborts_after_every_stop_failure(project, state):
    with patch.object(service, 'stop', return_value={'ok': False, 'state': state, 'pid': 123, 'message': 'stop refused'}), patch.object(service, 'start') as start:
        result = service.restart(port=8787)
    assert result['ok'] is False and result['state'] == state
    start.assert_not_called()


@pytest.mark.parametrize('explicit_port', [None, 8787])
def test_restart_dead_record_uses_configuration_not_record(project, explicit_port):
    home, config_port = project
    dead = subprocess.Popen([sys.executable, '-c', 'pass']); dead.wait(timeout=5)
    write_record(home, free_port(), dead.pid)
    with patch.object(service, 'start', return_value={'ok': True, 'state': 'started'}) as start:
        result = service.restart(port=explicit_port)
    assert result['ok']
    assert start.call_args.kwargs['port'] == (explicit_port if explicit_port is not None else config_port)
    assert start.call_args.kwargs['host'] == get_config().server.host
    assert not (home / 'golive.pid').exists()


@pytest.mark.parametrize('payload_case', ['other_home', 'missing_home', 'missing_pid', 'not_ok'])
def test_start_does_not_adopt_other_application_or_home(project, payload_case):
    home, _ = project
    payload = {'status': 'ok', 'pid': os.getpid(), 'home': str(home)}
    if payload_case == 'other_home': payload['home'] = str(home.parent / 'other')
    if payload_case == 'missing_home': payload.pop('home')
    if payload_case == 'missing_pid': payload.pop('pid')
    if payload_case == 'not_ok': payload['status'] = 'ready'
    with endpoint(payload) as port, patch.object(service, '_spawn') as spawn:
        result = service.start(port=port)
    assert not result['ok'] and result['state'] == 'port-taken'
    assert not (home / 'golive.pid').exists()
    spawn.assert_not_called()


@pytest.mark.parametrize('mismatch', ['pid', 'home'])
def test_startup_health_must_match_spawned_child(project, sleeper, mismatch):
    home, _ = project
    payload = {'status': 'ok', 'pid': sleeper.pid, 'home': str(home)}
    payload['pid' if mismatch == 'pid' else 'home'] = sleeper.pid + 1 if mismatch == 'pid' else str(home.parent / 'other')
    with patch.object(service, '_spawn', return_value=sleeper), patch.object(service, 'describe_port', return_value=('free', None)), patch.object(service, 'probe_health', return_value=payload):
        result = service.start(port=free_port(), timeout=.01)
    assert not result['ok'] and not (home / 'golive.pid').exists()
    assert sleeper.poll() is None


def verified_record(home):
    write_record(home, free_port())
    rec = service.read_pidfile()
    return {'exists': True, 'valid': True, 'reason': 'identity_matched',
            'record': rec, 'health': {'status': 'ok', 'pid': rec['pid'], 'home': str(home)}}


def test_force_kill_requires_fresh_identity(project):
    home, _ = project
    info = verified_record(home); before = (home / 'golive.pid').read_bytes()
    invalid = {**info, 'valid': False, 'reason': 'health_unavailable'}
    with patch.object(service, 'inspect_service_record', side_effect=[info, invalid]), patch.object(service, 'pid_alive', return_value=True), patch.object(service.os, 'kill') as kill:
        result = service.stop(timeout=0)
    assert not result['ok'] and result['state'] == 'identity-unverified'
    assert kill.call_args_list == [((info['record']['pid'], signal.SIGTERM),)]
    assert (home / 'golive.pid').read_bytes() == before


def test_verified_force_kill_still_works(project):
    home, _ = project
    info = verified_record(home)
    # No real signals are sent: simulate a verified process ignoring TERM.
    with patch.object(service, 'inspect_service_record', return_value=info), patch.object(service, 'pid_alive', side_effect=[True, False, False]), patch.object(service.os, 'kill') as kill:
        result = service.stop(timeout=0)
    assert result['ok'] and result['state'] == 'killed'
    assert [c.args[1] for c in kill.call_args_list] == [signal.SIGTERM, signal.SIGKILL]
    assert not (home / 'golive.pid').exists()


def test_stop_failure_preserves_record(project):
    home, _ = project
    info = verified_record(home); before = (home / 'golive.pid').read_bytes()
    with patch.object(service, 'inspect_service_record', return_value=info), patch.object(service.os, 'kill', side_effect=PermissionError('test denial')):
        result = service.stop()
    assert not result['ok'] and result['state'] == 'failed'
    assert (home / 'golive.pid').read_bytes() == before


def test_stop_does_not_delete_replacement_record(project):
    home, _ = project
    info = verified_record(home)
    def replace_record(*args):
        write_record(home, free_port(), os.getpid() + 1)
    with patch.object(service, 'inspect_service_record', return_value=info), patch.object(service, 'pid_alive', return_value=False), patch.object(service.os, 'kill', side_effect=replace_record):
        result = service.stop()
    assert result['ok'] and result['state'] == 'stopped'
    assert service.read_pidfile()['pid'] == os.getpid() + 1


def test_start_refuses_second_port_for_valid_managed_service(project):
    home, _ = project
    first = service.start(port=free_port())
    try:
        assert first['ok']
        before = (home / 'golive.pid').read_bytes()
        with patch.object(service, '_spawn') as spawn:
            result = service.start(port=free_port())
        assert not result['ok'] and (home / 'golive.pid').read_bytes() == before
        spawn.assert_not_called()
    finally:
        service.stop()


def test_health_change_before_start_is_not_accepted(project):
    home, _ = project
    info = verified_record(home)
    other = {**info['health'], 'pid': info['record']['pid'] + 1}
    with patch.object(service, 'inspect_service_record', return_value=info), patch.object(service, 'describe_port', return_value=('golive', other)), patch.object(service, '_spawn') as spawn:
        result = service.start(port=info['record']['port'])
    assert not result['ok'] and result['state'] == 'identity-unverified'
    spawn.assert_not_called()


def test_dead_legacy_record_is_safe_to_clean(project):
    home, _ = project
    dead = subprocess.Popen([sys.executable, '-c', 'pass']); dead.wait(timeout=5)
    path = home / 'golive.pid'; path.write_text(str(dead.pid))
    result = service.stop()
    assert result['ok'] and result['state'] == 'stale-cleaned'
    assert not path.exists()


def test_record_replaced_before_stop_is_not_signalled(project):
    home, _ = project
    info = verified_record(home)
    write_record(home, free_port(), os.getpid() + 1)
    with patch.object(service, 'inspect_service_record', return_value=info), patch.object(service.os, 'kill') as kill:
        result = service.stop()
    assert not result['ok'] and result['reason'] == 'record_changed'
    kill.assert_not_called()
    assert service.read_pidfile()['pid'] == os.getpid() + 1


def test_record_changed_during_startup_is_preserved(project, sleeper):
    home, _ = project
    payload = {'status': 'ok', 'pid': sleeper.pid, 'home': str(home)}
    def concurrent_health(*args, **kwargs):
        write_record(home, free_port(), os.getpid())
        return payload
    with patch.object(service, '_spawn', return_value=sleeper), patch.object(service, 'describe_port', return_value=('free', None)), patch.object(service, 'probe_health', side_effect=concurrent_health):
        result = service.start(port=free_port(), timeout=.1)
    assert not result['ok'] and result['reason'] == 'record_changed'
    assert service.read_pidfile()['pid'] == os.getpid()
    assert sleeper.poll() is None
