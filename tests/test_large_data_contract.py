"""DATA-02: counts/search past old caps, stable pages and complete backups."""
import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_restore_identity import pair
from golive.backends.data._restore import FIELDS


def large_rows():
    for index in range(12050):
        yield dict(id=str(uuid.UUID(int=index+1)),model_code='large' if index<11000 else 'late_model' if index<12000 else '',
                   name=f'row-{index:05d}',user_id='',description='note',
                   content={'payload':'late needle %_! 中文' if index==10999 else 'ordinary'},
                   version='1',sort_index=0,created_at='2020-01-01T00:00:00+00:00',updated_at='2020-01-01T00:00:00+00:00')


def bulk_seed(store,rows,backend):
    placeholder='?' if backend=='sqlite' else '%s'
    sql=f"INSERT INTO {store.table} ({', '.join(FIELDS)}) VALUES ({', '.join([placeholder]*len(FIELDS))})"
    values=[tuple(json.dumps(row[k],ensure_ascii=False) if k=='content' else row[k] for k in FIELDS) for row in rows]
    with store._conn() as connection:
        raw=connection.connection if backend=='mysql' else connection
        cursor=raw.cursor();cursor.executemany(sql,values);connection.commit();cursor.close()


def test_large_exact_stats_search_and_stable_pages(pair,record_property):
    rows=list(large_rows());start=time.monotonic()
    if pair.fake:pair.fake.table(pair.source.table).extend(rows)
    else:bulk_seed(pair.source,rows,pair.cfg.data.backend)
    record_property('seed_seconds',time.monotonic()-start)
    start=time.monotonic()
    assert pair.source.total_count()==12050
    assert {r['model_code']:r['count'] for r in pair.source.list_models()}=={'large':11000,'late_model':1000}
    assert pair.source.search('large','needle')['total']==1
    assert pair.source.search('large','%_! 中文')['list'][0]['id']==rows[10999]['id']
    assert pair.source.search('large','does-not-exist')['total']==0
    assert len(pair.source.search('large','ordinary',page_no=2,page_size=200)['list'])==200
    assert pair.source.search('large','ordinary',page_no=99999)['list']==[]
    actual=[]
    for page in range(1,6):actual.extend(r['id'] for r in pair.source.list('large',page_no=page,page_size=200)['list'])
    assert actual==[row['id'] for row in rows[:1000]] and len(set(actual))==1000
    if not pair.fake:
        page,_=pair.source.query({'model_code':('eq','large')},order='sort_index.desc',limit=50,offset=50)
        assert [row['id'] for row in page]==[row['id'] for row in rows[50:100]]
        assert sum(m['count'] for m in pair.source.list_models(scan_limit=2))==12000
    record_property('queries_seconds',time.monotonic()-start)
    # Blank legacy namespaces must also be backed up; use an independent COUNT.
    from golive.core.portability import export_archive
    archive=pair.tmp/'large.tar.gz';export_archive(str(archive),data_only=True,cfg=pair.cfg)
    import tarfile
    with tarfile.open(archive) as tar:
        assert json.load(tar.extractfile('manifest.json'))['counts']['data_rows']==12050
        assert len(tar.extractfile('data.jsonl').read().splitlines())==12050


def test_postgrest_server_cap_and_missing_pages_never_fake_complete_counts():
    from golive.backends.data.supabase import TemplateStore
    from types import SimpleNamespace
    rows=list(large_rows())[:7];calls=[]
    def capped(table,params,count=False):
        offset=int(params.get('offset',0));calls.append(offset)
        return rows[offset:offset+2],len(rows)
    store=TemplateStore(SimpleNamespace(select=capped),table='records')
    assert store.list_models(scan_limit=10000)==[{'model_code':'large','count':7}]
    assert calls==[0,2,4,6]
    with patch.object(store.client,'select',return_value=([],7)):
        with pytest.raises(RuntimeError):store.list_models()
    with patch.object(store.client,'select',return_value=([rows[0]],None)):
        with pytest.raises(RuntimeError):store.list_models()
        with pytest.raises(RuntimeError):store.list('large')
