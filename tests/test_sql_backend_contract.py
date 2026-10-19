"""One behavioral contract against real SQLite/PostgreSQL/MySQL databases.

External integrations skip only when their explicitly named DSN is absent.
CI provisions both SQL servers and requires their test cases to run.
"""
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from golive.config import Config, set_config, reset_config
from golive.core.paths import reset_cache


@pytest.fixture(params=['sqlite', 'postgres', 'mysql'])
def stores(request, tmp_path, monkeypatch):
    backend = request.param
    env = {'postgres':'GOLIVE_PG_DSN', 'mysql':'GOLIVE_MYSQL_DSN'}.get(backend)
    if env and not os.environ.get(env):
        pytest.skip(env + ' not configured')
    monkeypatch.setenv('GOLIVE_HOME', str(tmp_path))
    reset_cache(); reset_config()
    cfg = Config(); cfg.data.backend = backend; cfg.registry.backend = backend
    cfg.data.templates_table = 'contract_' + uuid.uuid4().hex[:12]
    set_config(cfg)
    from golive.backends.factory import get_registry, get_template_store
    data, registry = get_template_store(cfg), get_registry(cfg)
    ids = []
    yield SimpleNamespace(data=data, registry=registry, ids=ids, backend=backend, cfg=cfg)
    for ident in ids:
        registry.delete(ident)
    if env:
        with data._conn() as c:
            c.execute(f'DROP TABLE {data.table}')
            c.commit()
    reset_cache(); reset_config()


def test_crud_json_unicode_and_update(stores):
    s = stores.data
    value = {'中文': '你好 🧪', 'nested': {'list': [1, None, True]}}
    row = s.create('notes', '你好', content=value, user_id='user-one')
    assert s.get(row['id'])['content'] == value
    assert s.update(row['id'], {'content': [1, '更新'], 'desc': '说明'})['content'] == [1, '更新']
    assert s.get(row['id'])['description'] == '说明'
    assert s.delete(row['id']) is True
    assert s.get(row['id']) is None
    assert s.delete(row['id']) is False
    with pytest.raises(KeyError): s.update(row['id'], {'content': {}})


def test_upsert_unique_identity_and_case(stores):
    s = stores.data
    a = s.upsert('notes', 'Note', content={'v': 1}, user_id='alice')
    b = s.upsert('notes', 'Note', content={'v': 2}, user_id='alice')
    c = s.upsert('notes', 'Note', content={}, user_id='bob')
    lower = s.create('notes', 'note', user_id='alice')
    assert a['id'] == b['id'] and a['id'] != c['id'] != lower['id']
    assert s.count('notes') == 3
    assert s.list('notes', user_id='alice')['total'] == 2
    with pytest.raises(Exception): s.create('notes', 'Note', user_id='alice')


def test_pagination_search_and_literal_prefix(stores):
    s = stores.data
    for i in range(7): s.create('notes', 'item-' + str(i), content={'n': i})
    assert s.list('notes', page_no=2, page_size=3)['total'] == 7
    assert len(s.list('notes', page_no=2, page_size=3)['list']) == 3
    assert s.search('notes', 'item-4')['total'] == 1
    s.create('notes', '100% done')
    s.create('notes', '1000 done')
    assert s.list('notes', name_prefix='100%')['total'] == 1
    assert {m['model_code']:m['count'] for m in s.list_models()} == {'notes':9}


def test_filter_sort_update_delete_and_injection(stores):
    s = stores.data
    for i in range(3):
        row = s.insert_row({'model_code':'notes', 'name':str(i), 'content':{'i':i}})
        s.update(row['id'], {'sort_index':i})
    rows, count = s.query({'model_code':('eq','notes')}, order='sort_index.desc', want_count=True)
    assert count == 3 and rows[0]['name'] == '2'
    changed = s.update_rows({'name':('eq','2')}, {'content':{'changed':True}})
    assert changed[0]['content'] == {'changed':True}
    assert s.delete_rows({'name':('eq',"' OR 1=1 --")}) == 0
    with pytest.raises(ValueError): s.query({'name OR 1=1':('eq','x')})
    with pytest.raises(ValueError): s.query({'name':('gt','x')})
    assert s.delete_rows({'model_code':('eq','notes')}) == 3


def test_registry_crud_slug_and_multiple_empty_slugs(stores):
    r = stores.registry
    prefix = 'contract-' + uuid.uuid4().hex[:10]
    a = r.create('中文 🧪', slug=prefix.upper(), owner='alice'); stores.ids.append(a['site_id'])
    b = r.create('no slug'); stores.ids.append(b['site_id'])
    c = r.create('no slug again'); stores.ids.append(c['site_id'])
    assert r.get_by_slug(prefix)['site_id'] == a['site_id']
    assert r.resolve(a['site_id'])['slug'] == prefix
    assert r.slug_taken(prefix) and not r.slug_taken(prefix, exclude_site_id=a['site_id'])
    assert r.update(a['site_id'], name='Changed')['name'] == 'Changed'
    before = r.get(a['site_id'])['updated_at']; r.touch(a['site_id'])
    assert r.get(a['site_id'])['updated_at'] > before
    assert r.get_by_slug('') is None
    with pytest.raises(Exception): r.create('duplicate', slug=prefix)
    assert r.delete(c['site_id']); stores.ids.remove(c['site_id'])
    assert r.resolve(c['site_id']) is None


def test_registry_roles_and_persistence(stores):
    r = stores.registry; a = r.create('roles'); stores.ids.append(a['site_id'])
    assert r.add_maintainer(a['site_id'], ' Alice@Example.com ') == ['alice@example.com']
    assert r.add_maintainer(a['site_id'], 'alice@example.com') == ['alice@example.com']
    r.set_editable(a['site_id'], True); r.set_editable(a['site_id'], True)
    r.set_owner(a['site_id'], 'owner@example.com')
    from golive.backends.factory import get_registry
    fresh = get_registry(stores.cfg)
    assert fresh.get(a['site_id'])['editable'] is True
    assert fresh.get(a['site_id'])['owner'] == 'owner@example.com'
    assert fresh.list_maintainers(a['site_id']) == ['alice@example.com']
    assert r.remove_maintainer(a['site_id'], 'ALICE@example.com') == []
    with pytest.raises(KeyError): r.set_owner('missing-site', 'x')
