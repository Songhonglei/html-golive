"""DATA-01: exact business-record restore, failure and conflict contracts."""
import io
import json
import os
import tarfile
import uuid
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from golive.config import Config, reset_config, set_config
from golive.core.paths import reset_cache
from golive.backends.factory import get_template_store
from golive.core.portability import export_archive, import_archive


@pytest.fixture(params=['sqlite', 'supabase', 'postgres', 'mysql'])
def pair(request, tmp_path, monkeypatch):
    backend=request.param
    env={'postgres':'GOLIVE_PG_DSN','mysql':'GOLIVE_MYSQL_DSN'}.get(backend)
    if env and not os.environ.get(env):pytest.skip(env+' not configured')
    monkeypatch.setenv('GOLIVE_HOME',str(tmp_path));reset_cache();reset_config()
    fake=None
    cfg=Config();cfg.data.backend=backend
    if backend=='supabase':
        from tests.fake_postgrest import FakePostgrest
        fake=FakePostgrest();cfg.supabase.url=fake.start()
        monkeypatch.setenv('GOLIVE_SUPABASE_SERVICE_KEY','test-key')
        monkeypatch.setenv('GOLIVE_SUPABASE_ANON_KEY','test-key')
    cfg.data.templates_table='restore_src_'+uuid.uuid4().hex[:10]
    cfg.data.sqlite_path=str(tmp_path/'source.db');set_config(cfg)
    target=replace(cfg,data=replace(cfg.data,templates_table='restore_dst_'+uuid.uuid4().hex[:10],sqlite_path=str(tmp_path/'target.db')))
    source_store,dest=get_template_store(cfg),get_template_store(target)
    yield SimpleNamespace(source=source_store,dest=dest,cfg=cfg,target=target,tmp=tmp_path,fake=fake)
    if env:
        for store in (source_store,dest):
            with store._conn() as connection:connection.execute(f'DROP TABLE {store.table}');connection.commit()
    if fake:fake.stop()
    reset_cache();reset_config()


def payload(**values):
    return dict(id=str(uuid.uuid4()),model_code='linked',name='first',user_id='',description='中文 🧪',content={'nested':[None,True,1]},version='2.0',sort_index=17,created_at='2020-01-02T03:04:05+00:00',updated_at='2021-02-03T04:05:06+00:00',**values)


def seed(pair):
    a=pair.source.create('linked','a',content={})
    b=pair.source.create('linked','b',content={'parent':a['id']})
    pair.source.update(a['id'],{'content':{'self':a['id'],'child':b['id']},'sort_index':31})
    if pair.fake:
        for row in pair.fake.table(pair.source.table):
            row.update(created_at='2020-01-02T03:04:05+00:00',updated_at='2021-02-03T04:05:06+00:00',sort_index=row.get('sort_index',0))
    archive=pair.tmp/'backup.tar.gz';export_archive(str(archive),data_only=True,cfg=pair.cfg)
    return archive,{row['id']:row for row in pair.source.list('linked')['list']}


def test_archive_restores_record_ids_and_references(pair):
    archive,expected=seed(pair)
    set_config(pair.target)
    pair.dest=get_template_store(pair.target)
    result=import_archive(str(archive),yes=True,cfg=pair.target)
    for ident,row in expected.items():
        assert pair.dest.get(ident)==row
    # Assert the record contract even with an older implementation that lacks report fields.
    assert result['ok'] and result['data_exact_restore'] and result['data_identity_preserved']
    assert pair.dest.list('linked')['list'][0]['sort_index']==31
    rerun=import_archive(str(archive),yes=True,cfg=pair.target)
    assert rerun['data_rows_imported']==0 and rerun['data_rows_skipped']==2
    assert rerun['data_exact_restore']


@pytest.mark.parametrize('content',[{'x':[1,None,True]},[1,'二'],'plain string','123','null','{"key":1}','"quoted"',4,False,None])
def test_restore_primitive_preserves_scalars_and_metadata(pair,content):
    row=payload();row['content']=content
    assert pair.dest.restore_row(row)==row
    changed=dict(row,content={'changed':True},sort_index=-7,updated_at='2022-01-01T00:00:00+00:00')
    assert pair.dest.restore_row(changed,overwrite=True)==changed


def test_skip_changed_record_and_overwrite_same_id(pair):
    archive,rows=seed(pair);import_archive(str(archive),yes=True,cfg=pair.target)
    ident=next(iter(rows));pair.dest.update(ident,{'content':{'changed':True},'sort_index':-99})
    skipped=import_archive(str(archive),yes=True,cfg=pair.target)
    assert skipped['ok'] and skipped['data_identity_preserved'] and not skipped['data_exact_restore']
    result=import_archive(str(archive),yes=True,on_conflict='overwrite',cfg=pair.target)
    assert result['data_exact_restore'] and pair.dest.get(ident)==rows[ident]


def test_logical_key_collision_never_substitutes_ids(pair):
    archive,rows=seed(pair);row=next(iter(rows.values()))
    existing=pair.dest.create(row['model_code'],row['name'],content={'keep':True})
    result=import_archive(str(archive),yes=True,on_conflict='overwrite',cfg=pair.target)
    assert not result['ok'] and result['data_errors'][0]['code']=='identity_conflict'
    assert pair.dest.get(existing['id'])==existing and pair.dest.get(row['id']) is None
    assert not result['data_identity_preserved'] and result['partial']


def test_rename_reports_new_ids_and_does_not_guess_reference_rewrites(pair):
    archive,rows=seed(pair);import_archive(str(archive),yes=True,cfg=pair.target)
    result=import_archive(str(archive),yes=True,on_conflict='rename',cfg=pair.target)
    assert result['ok'] and not result['data_identity_preserved'] and not result['data_exact_restore']
    assert not result['references_rewritten']
    assert all(old!=new for old,new in result['data_id_map'].items())
    for old,new in result['data_id_map'].items():
        assert pair.dest.get(new)['content']==rows[old]['content']


def test_partial_failure_is_redacted_and_retry_keeps_ids(pair):
    archive,rows=seed(pair);original=pair.dest.restore_row;attempts=[]
    def flaky(row,**kw):
        attempts.append(row['id'])
        if len(attempts)==2:raise RuntimeError('mysql://private:do-not-leak@localhost/fixture')
        return original(row,**kw)
    with patch.object(pair.dest,'restore_row',side_effect=flaky),patch('golive.backends.factory.get_template_store',return_value=pair.dest):
        result=import_archive(str(archive),yes=True,cfg=pair.target)
    assert not result['ok'] and result['partial'] and result['data_rows_imported']==1
    assert 'do-not-leak' not in json.dumps(result)
    rerun=import_archive(str(archive),yes=True,cfg=pair.target)
    assert rerun['ok'] and rerun['data_exact_restore'] and rerun['data_rows_skipped']==1
    assert {pair.dest.get(ident)['id'] for ident in rows}==set(rows)


def archive_rows(path,rows,extra=None):
    with tarfile.open(path,'w:gz') as tar:
        values={'manifest.json':json.dumps({'counts':{'sites':0,'data_rows':len(rows),'html_files':0}}),'data.jsonl':'\n'.join(json.dumps(r) for r in rows),'registry.jsonl':''}
        for name,value in values.items():
            raw=value.encode();info=tarfile.TarInfo(name);info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
        if extra:extra(tar)


@pytest.mark.parametrize('bad',['duplicate_id','duplicate_key','invalid_sort','invalid_timestamp','unknown_field','invalid_row','symlink','duplicate_member'])
def test_invalid_archive_rejected_before_opening_target(tmp_path,bad):
    row=payload();rows=[row]
    if bad=='duplicate_id':rows.append(dict(row,name='other'))
    if bad=='duplicate_key':rows.append(dict(row,id=str(uuid.uuid4())))
    if bad=='invalid_sort':row['sort_index']=True
    if bad=='invalid_timestamp':row['created_at']='not-a-time'
    if bad=='unknown_field':row['unrestorable_field']='secret'
    if bad=='invalid_row':rows=[None]
    def extra(tar):
        info=tarfile.TarInfo('data.jsonl' if bad=='duplicate_member' else 'link')
        if bad=='symlink':info.type=tarfile.SYMTYPE;info.linkname='data.jsonl'
        tar.addfile(info,io.BytesIO(b''))
    path=tmp_path/'bad.tar.gz';archive_rows(path,rows,extra if bad in ('symlink','duplicate_member') else None)
    with patch('golive.backends.factory.get_registry') as factory:
        with pytest.raises(ValueError):import_archive(str(path),yes=True,cfg=Config())
        factory.assert_not_called()


def test_empty_user_identity_lookup_pages_past_other_users(tmp_path):
    from golive.backends.data.sqlite_store import TemplateStore
    from golive.core.portability import _find_existing_row
    store=TemplateStore(tmp_path/'users.db')
    for index in range(55):store.create('m','same',user_id='user-'+str(index))
    wanted=store.create('m','same')
    assert _find_existing_row(store,'m','same')['id']==wanted['id']


def test_import_json_errors_are_structured_and_redacted(tmp_path,capsys):
    from golive.cli import main
    assert main(['import',str(tmp_path/'missing.tar.gz'),'--yes','--json'])==1
    result=json.loads(capsys.readouterr().out)
    assert result['code']=='invalid_archive' and not result['ok']


def test_archive_only_preview_does_not_open_target(tmp_path):
    archive=tmp_path/'valid.tar.gz';archive_rows(archive,[payload()])
    with patch('golive.backends.factory.get_registry') as registry,patch('golive.backends.factory.get_template_store') as store:
        result=import_archive(str(archive),dry_run=True,cfg=Config())
    assert result['ok'] and not result['summary']['target_inspected']
    assert result['summary']['conflict_count'] is None
    registry.assert_not_called();store.assert_not_called()


def test_readback_failure_reports_uncertain_write_and_retry_is_safe(pair):
    archive,rows=seed(pair);original=pair.dest.restore_row
    def bad_response(row,**kw):
        restored=original(row,**kw)
        return dict(restored,sort_index=99999)
    with patch.object(pair.dest,'restore_row',side_effect=bad_response),patch('golive.backends.factory.get_template_store',return_value=pair.dest):
        result=import_archive(str(archive),yes=True,cfg=pair.target)
    assert not result['ok'] and result['data_writes_uncertain'] and result['partial']
    assert all(error['code']=='restore_mismatch' for error in result['data_errors'])
    assert import_archive(str(archive),yes=True,cfg=pair.target)['data_exact_restore']


def test_same_id_different_logical_key_is_not_overwritten(pair):
    archive,rows=seed(pair);row=next(iter(rows.values()))
    existing=dict(row,name='unrelated')
    pair.dest.restore_row(existing)
    result=import_archive(str(archive),yes=True,on_conflict='overwrite',cfg=pair.target)
    assert not result['ok'] and result['data_errors'][0]['code']=='identity_conflict'
    assert pair.dest.get(row['id'])==existing


def test_failed_conflict_lookup_never_attempts_insert(pair):
    archive,rows=seed(pair)
    with patch.object(pair.dest,'list',side_effect=RuntimeError('password=do-not-leak')),patch.object(pair.dest,'restore_row') as insert,patch('golive.backends.factory.get_template_store',return_value=pair.dest):
        result=import_archive(str(archive),yes=True,cfg=pair.target)
    assert not result['ok'] and 'do-not-leak' not in json.dumps(result)
    insert.assert_not_called()


def test_import_json_backend_errors_do_not_impersonate_invalid_archives(tmp_path,capsys):
    from golive.cli import main
    with patch('golive.core.portability.import_archive',side_effect=ValueError('password=do-not-leak')):
        assert main(['import',str(tmp_path/'fixture.tar.gz'),'--yes','--json'])==1
    text=capsys.readouterr().out;result=json.loads(text)
    assert result['code']=='backend_error' and not result['ok'] and 'do-not-leak' not in text


def test_migration_json_failure_is_redacted(capsys):
    from golive.cli import main
    with patch('golive.core.portability.migrate_backend',side_effect=RuntimeError('password=do-not-leak')):
        assert main(['migrate','data','--to','mysql','--json'])==1
    text=capsys.readouterr().out;result=json.loads(text)
    assert result['code']=='backend_error' and not result['ok'] and 'do-not-leak' not in text


def test_migration_preview_never_opens_target(pair):
    from golive.core.portability import migrate_backend
    pair.source.create('m','source')
    with patch('golive.backends.factory.get_template_store',return_value=pair.source) as factory:
        target='sqlite' if pair.cfg.data.backend!='sqlite' else 'mysql'
        result=migrate_backend('data',target,dry_run=True,cfg=pair.cfg)
    assert result['ok'] and result['target_existing'] is None and not result['target_inspected']
    assert factory.call_count==1


def test_json_restore_requires_explicit_noninteractive_mode(tmp_path,capsys):
    from golive.cli import main
    with patch('golive.core.portability.import_archive') as restore:
        assert main(['import',str(tmp_path/'fixture.tar.gz'),'--json'])==2
    result=json.loads(capsys.readouterr().out)
    assert result['code']=='confirmation_required' and not result['ok']
    restore.assert_not_called()


def test_sql_driver_decoding_keeps_jsonb_strings_distinct_from_json_text():
    from golive.backends.data.postgres_store import TemplateStore as Postgres
    from golive.backends.data.mysql_store import TemplateStore as MySQL
    for value in ('plain string','123','null','{"key":1}','"quoted"'):
        assert Postgres._row_to_dict({'content':value})['content']==value
        assert MySQL._row_to_dict({'content':json.dumps(value)})['content']==value


def test_migration_commit_then_readback_failure_reports_partial_and_can_resume(tmp_path):
    from golive.backends.data.sqlite_store import TemplateStore
    from golive.core.portability import migrate_backend
    source=TemplateStore(tmp_path/'migration-source.db',table='records')
    target=TemplateStore(tmp_path/'migration-target.db',table='records')
    source.create('m','committed',content={'keep':True})
    cfg=Config();original=target.restore_row
    def factory(selected):return source if selected.data.backend=='sqlite' else target
    def wrong_readback(row,**kw):return dict(original(row,**kw),sort_index=99999)
    with patch('golive.backends.factory.get_template_store',side_effect=factory):
        with patch.object(target,'restore_row',side_effect=wrong_readback):
            failed=migrate_backend('data','supabase',cfg=cfg)
        assert not failed['ok'] and failed['migrated']==0 and failed['target_count_after']==1
        assert failed['partial']
        retried=migrate_backend('data','supabase',cfg=cfg)
        assert retried['ok'] and retried['migrated']==0 and retried['skipped']==1
        assert target.list('m')['list']==source.list('m')['list']
