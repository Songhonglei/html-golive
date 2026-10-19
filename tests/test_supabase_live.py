"""Opt-in real Supabase acceptance (Postgres + PostgREST + Storage + RLS).

Set GOLIVE_TEST_SUPABASE_URL, GOLIVE_TEST_SUPABASE_DB_DSN,
GOLIVE_TEST_SUPABASE_ANON_KEY and GOLIVE_TEST_SUPABASE_SERVICE_KEY.
Use a disposable local/test project: each case creates unique tables/bucket,
then removes them. No existing tables or buckets are read or altered.
"""
import json
import os
import threading
import time
import uuid
from types import SimpleNamespace

import pytest
import requests

from golive.backends.postgrest import PostgrestClient, PostgrestError, supabase_headers
from golive.config import Config, set_config, reset_config
from golive.core.paths import reset_cache
from tests.test_backend_http_contract import cli


@pytest.fixture
def supabase_live(tmp_path, monkeypatch):
    names = ('URL', 'DB_DSN', 'ANON_KEY', 'SERVICE_KEY')
    settings = {n: os.environ.get('GOLIVE_TEST_SUPABASE_' + n, '') for n in names}
    if not any(settings.values()):
        pytest.skip('real Supabase test environment not configured')
    if not all(settings.values()):
        pytest.fail('all four GOLIVE_TEST_SUPABASE_* variables are required', pytrace=False)
    import psycopg
    from golive.backends.data.supabase import CREATE_TABLE_SQL as DATA_SQL
    from golive.backends.registry.supabase_store import CREATE_TABLE_SQL as REGISTRY_SQL
    from golive.backends.factory import get_storage, get_registry, get_template_store
    suffix = uuid.uuid4().hex[:12]
    table, registry, bucket = 'live_data_' + suffix, 'live_sites_' + suffix, 'live-' + suffix
    monkeypatch.setenv('GOLIVE_HOME', str(tmp_path))
    monkeypatch.setenv('GOLIVE_LANG', 'en')
    monkeypatch.setenv('GOLIVE_SUPABASE_ANON_KEY', settings['ANON_KEY'])
    monkeypatch.setenv('GOLIVE_SUPABASE_SERVICE_KEY', settings['SERVICE_KEY'])
    monkeypatch.setenv('GOLIVE_SUPABASE_URL', settings['URL'])
    reset_cache(); reset_config()
    cfg = Config()
    cfg.supabase.url = settings['URL']
    cfg.registry.backend = cfg.data.backend = cfg.storage.backend = 'supabase'
    cfg.registry.supabase_table = registry
    cfg.data.templates_table = table
    cfg.storage.supabase_bucket = bucket
    config = tmp_path / 'golive.yaml'
    config.write_text(f'''supabase:
  url: {settings['URL']}
registry:
  backend: supabase
  supabase:
    table: {registry}
data:
  backend: supabase
  templates_table: {table}
storage:
  backend: supabase
  supabase:
    bucket: {bucket}
''')
    cfg.source_path = str(config); set_config(cfg)
    headers = supabase_headers(settings['SERVICE_KEY'])
    storage_api = settings['URL'].rstrip('/') + '/storage/v1'
    with psycopg.connect(settings['DB_DSN']) as db:
        db.execute(DATA_SQL.format(table=table))
        db.execute(REGISTRY_SQL.format(table=registry))
        db.execute(f'GRANT ALL ON {table}, {registry} TO service_role')
        db.execute(f'ALTER TABLE {registry} ENABLE ROW LEVEL SECURITY')
        db.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        db.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO anon')
        db.execute(f'''CREATE POLICY acceptance ON {table} FOR ALL TO anon
                      USING (model_code <> 'private') WITH CHECK (model_code <> 'private')''')
        db.execute("NOTIFY pgrst, 'reload schema'")
    response = requests.post(storage_api + '/bucket', headers=headers,
                             json={'id': bucket, 'name': bucket, 'public': False}, timeout=20)
    if not response.ok:
        pytest.fail(f'cannot create isolated Storage bucket: HTTP {response.status_code}', pytrace=False)
    public = PostgrestClient(settings['URL'], settings['ANON_KEY'])
    for attempt in range(30):
        try:
            public.select(table); break
        except PostgrestError:
            if attempt == 29: raise
            time.sleep(.2)
    from golive.server.app import make_server
    server = make_server('127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    state = SimpleNamespace(cfg=cfg, home=tmp_path, data=get_template_store(cfg),
                            registry=get_registry(cfg), storage=get_storage(cfg),
                            public=public, base=f'http://127.0.0.1:{server.server_address[1]}')
    try:
        yield state
    finally:
        server.shutdown(); server.server_close(); thread.join(5)
        # Empty only this case's bucket, including unreferenced rollback snapshots.
        empty = requests.post(storage_api + f'/bucket/{bucket}/empty', headers=headers, timeout=20)
        deleted = requests.delete(storage_api + '/bucket/' + bucket, headers=headers, timeout=20)
        with psycopg.connect(settings['DB_DSN']) as db:
            db.execute(f'DROP TABLE {table}, {registry}')
            db.execute("NOTIFY pgrst, 'reload schema'")
        reset_config(); reset_cache()
        assert empty.ok and deleted.ok, 'isolated Supabase bucket cleanup failed'


def test_live_supabase_registry_storage_and_rollback(supabase_live):
    s = supabase_live
    site = s.registry.create('中文 🚀', slug='live', owner='owner')
    s.registry.set_editable(site['site_id'], True)
    s.registry.add_maintainer(site['site_id'], 'editor')
    reopened = __import__('golive.backends.factory', fromlist=['get_registry']).get_registry(s.cfg)
    assert reopened.get_by_slug('live')['owner'] == 'owner'
    assert reopened.get(site['site_id'])['maintainers'] == ['editor']
    s.storage.publish('<html>第一版 🚀</html>', site['site_id'])
    assert s.storage.read(site['site_id']) == '<html>第一版 🚀</html>'
    s.storage.publish('<html>第二版 🧪</html>', site['site_id'])
    snapshots = s.storage.list_snapshots(site['site_id'])
    assert snapshots
    s.storage.rollback(site['site_id'], snapshots[0]['ts'])
    assert s.storage.read(site['site_id']) == '<html>第一版 🚀</html>'
    s.storage.delete(site['site_id']); s.registry.delete(site['site_id'])
    assert not s.storage.exists(site['site_id'])


def test_live_supabase_public_crud_and_rls(supabase_live):
    s = supabase_live; table = s.cfg.data.templates_table
    row = s.public.insert(table, {'model_code': 'live', 'name': '公开 🧪', 'content': {'中文': [True, None]}})[0]
    assert s.public.select(table, {'id': 'eq.' + row['id']})[0][0]['content'] == {'中文': [True, None]}
    assert s.public.update(table, {'id': 'eq.' + row['id']}, {'content': {'updated': True}})[0]['content'] == {'updated': True}
    assert s.public.delete(table, {'id': 'eq.' + row['id']}) == 1
    private = s.data.create('private', '隐藏', content={'secret': True})
    assert s.public.select(table, {'id': 'eq.' + private['id']})[0] == []
    assert s.public.update(table, {'id': 'eq.' + private['id']}, {'name': 'denied'}) == []
    assert s.public.delete(table, {'id': 'eq.' + private['id']}) == 0
    with pytest.raises(PostgrestError):
        s.public.insert(table, {'model_code': 'private', 'name': 'denied'})
    assert s.data.get(private['id'])['name'] == '隐藏'


def test_live_supabase_cli_verify_publish_export_import(supabase_live):
    s = supabase_live
    result = json.loads(cli('verify', '--json'))
    assert result['ok'] and any(x['step'] == 'data' and x['ok'] for x in result['steps'])
    assert s.data.count('verify_test') == 0
    page = s.home / 'app.html'; page.write_text('<html><title>Live</title><p>中文 🚀 TemplateAPI.list()</p></html>')
    cli('publish', str(page), '--slug', 'live-app', '--data-model', 'live')
    site = s.registry.get_by_slug('live-app')
    response = requests.get(s.base + '/live-app', timeout=20)
    assert response.ok and '中文 🚀' in response.content.decode()
    assert s.cfg.supabase.service_key not in response.text
    row = s.data.create('live', 'archive', content={'汉字': '🚀'})
    archive = s.home / 'all.tar.gz'
    cli('export', '--output', str(archive))
    s.storage.delete(site['site_id']); s.registry.delete(site['site_id']); s.data.delete(row['id'])
    cli('import', str(archive), '--yes')
    assert s.data.list('live')['list'][0]['content'] == {'汉字': '🚀'}
    assert s.registry.get(site['site_id'])['slug'] == 'live-app'
    assert '中文 🚀' in s.storage.read(site['site_id'])
    cli('doctor', '--port', s.base.rsplit(':', 1)[1], '--json')


@pytest.mark.parametrize('sql_backend', ['sqlite', 'postgres', 'mysql'])
def test_live_supabase_migration_round_trip(supabase_live, sql_backend, monkeypatch):
    s = supabase_live
    env = {'postgres': 'GOLIVE_PG_DSN', 'mysql': 'GOLIVE_MYSQL_DSN'}.get(sql_backend)
    if env and not os.environ.get(env): pytest.skip(env + ' not configured')
    from golive.core.portability import migrate_backend
    from golive.backends.factory import get_template_store
    row = s.data.create('live', 'migration', content={'往返': [1, '🚀']})
    result = migrate_backend('data', sql_backend)
    assert result['ok'], result.get('error')
    from copy import deepcopy
    sql_cfg = deepcopy(s.cfg); sql_cfg.data.backend = sql_backend
    sql_store = get_template_store(sql_cfg)
    try:
        assert sql_store.list('live')['list'][0]['content'] == {'往返': [1, '🚀']}
        s.data.delete(row['id'])
        set_config(sql_cfg)
        result = migrate_backend('data', 'supabase')
        assert result['ok'], result.get('error')
        assert s.data.list('live')['list'][0]['content'] == {'往返': [1, '🚀']}
    finally:
        set_config(s.cfg)
        if env:
            with sql_store._conn() as db:
                db.execute(f'DROP TABLE {sql_store.table}')
