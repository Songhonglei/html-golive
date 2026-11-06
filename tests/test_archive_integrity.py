"""Malformed compressed archives fail before opening any restore target."""
import gzip
import io
import json
import tarfile
import zlib
from unittest.mock import patch

import pytest

from golive.cli import main
from golive.config import reset_config
from golive.core.paths import reset_cache
from golive.core.portability import import_archive


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / 'target-home'
    config = tmp_path / 'golive.yaml'
    config.write_text('{}\n')
    monkeypatch.setenv('GOLIVE_HOME', str(home))
    monkeypatch.setenv('GOLIVE_CONFIG', str(config))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    reset_cache(); reset_config()
    yield home, config
    reset_cache(); reset_config()


def valid_archive():
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as tar:
        for name, value in {
            'manifest.json': json.dumps({'counts': {'sites': 0, 'data_rows': 0, 'html_files': 0}}),
            'registry.jsonl': '', 'data.jsonl': '',
        }.items():
            content = value.encode()
            member = tarfile.TarInfo(name); member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    return gzip.compress(raw.getvalue(), mtime=0)


def damaged_archive(kind):
    data = valid_archive()
    if kind == 'empty': return b''
    if kind == 'header': return data[:5]
    if kind == 'body': return data[:100]
    if kind == 'deflate': return data[:10] + b'\x07' + data[11:]
    if kind == 'short_trailer': return data[:-1]
    if kind == 'missing_trailer': return data[:-8]
    offset = -8 if kind == 'crc' else -4
    changed = bytearray(data); changed[offset] ^= 1
    return bytes(changed)


@pytest.mark.parametrize('backend', ['sqlite', 'mysql', 'postgres'])
@pytest.mark.parametrize('mode', ['--dry-run', '--yes'])
@pytest.mark.parametrize('damage', ['empty', 'header', 'body', 'deflate', 'short_trailer', 'missing_trailer', 'crc', 'size'])
def test_corrupt_gzip_is_invalid_archive_before_target_access(project, tmp_path, capsys, backend, mode, damage):
    home, config = project
    config.write_text(f'registry:\n  backend: {backend}\ndata:\n  backend: {backend}\n')
    archive = tmp_path / 'private-backup.tar.gz'
    archive.write_bytes(damaged_archive(damage))
    with patch('golive.backends.factory.get_registry') as registry, \
            patch('golive.backends.factory.get_storage') as storage, \
            patch('golive.backends.factory.get_template_store') as store:
        status = main(['import', str(archive), mode, '--json'])
        captured = capsys.readouterr(); result = json.loads(captured.out)
        assert status == 1 and result['ok'] is False
        assert result['code'] == 'invalid_archive'
        assert not captured.err and str(archive) not in captured.out
        registry.assert_not_called(); storage.assert_not_called(); store.assert_not_called()
    assert not home.exists()


def test_valid_gzip_preview_stays_target_free(project, tmp_path):
    archive = tmp_path / 'valid.tar.gz'; archive.write_bytes(valid_archive())
    with patch('golive.backends.factory.get_registry') as registry:
        result = import_archive(str(archive), dry_run=True)
        assert result['ok'] and result['summary']['target_inspected'] is False
        registry.assert_not_called()
    assert not project[0].exists()


@pytest.mark.parametrize('mode', ['--dry-run', '--yes'])
def test_original_truncation_keeps_existing_sqlite_database_unchanged(project, tmp_path, capsys, mode):
    import hashlib
    import sqlite3
    from golive.backends.data.sqlite_store import TemplateStore
    home, config = project
    database = tmp_path / 'existing.sqlite'
    store = TemplateStore(db_path=database, table='sentinel')
    record = store.create('sentinel', 'preserve', content={'do_not_change': True})
    config.write_text(f'data:\n  backend: sqlite\n  templates_table: sentinel\n  sqlite:\n    path: {database}\n')
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    archive = tmp_path / 'broken.tar.gz'; archive.write_bytes(damaged_archive('body'))
    assert main(['import', str(archive), mode, '--json']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['code'] == 'invalid_archive'
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with sqlite3.connect(database) as connection:
        rows = connection.execute('SELECT id, model_code, name, content FROM sentinel').fetchall()
    assert len(rows) == 1 and rows[0][:3] == (record['id'], 'sentinel', 'preserve')
    assert json.loads(rows[0][3]) == {'do_not_change': True}
    assert not home.exists()


@pytest.mark.parametrize('error', [EOFError('private-target-secret'), zlib.error('private-target-secret')])
def test_backend_errors_are_not_relabelled_as_corrupt_archives(project, tmp_path, capsys, error):
    archive = tmp_path / 'valid.tar.gz'; archive.write_bytes(valid_archive())
    with patch('golive.backends.factory.get_registry', side_effect=error):
        assert main(['import', str(archive), '--yes', '--json']) == 1
    captured = capsys.readouterr(); result = json.loads(captured.out)
    assert result['code'] == 'backend_error' and not result['ok']
    assert 'private-target-secret' not in captured.out and not captured.err
