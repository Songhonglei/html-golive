"""Real socket and CLI acceptance for each server-proxied SQL data backend."""
import io
import json
import os
import tarfile
import threading
import uuid
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace

import pytest
import requests

from golive.config import Config, set_config, reset_config
from golive.core.paths import reset_cache


@pytest.fixture(params=['sqlite','postgres','mysql'])
def live(request, tmp_path, monkeypatch):
    backend = request.param
    env = {'postgres':'GOLIVE_PG_DSN','mysql':'GOLIVE_MYSQL_DSN'}.get(backend)
    if env and not os.environ.get(env): pytest.skip(env+' not configured')
    monkeypatch.setenv('GOLIVE_HOME', str(tmp_path)); monkeypatch.setenv('GOLIVE_LANG','en')
    reset_cache(); reset_config()
    from golive.i18n import set_language
    set_language('en')
    cfg=Config(); cfg.data.backend=cfg.registry.backend=backend
    cfg.data.templates_table='http_' + uuid.uuid4().hex[:12]
    config=tmp_path/'golive.yaml'
    config.write_text(f'data:\n  backend: {backend}\n  supabase:\n    templates_table: {cfg.data.templates_table}\nregistry:\n  backend: {backend}\n')
    cfg.source_path=str(config); set_config(cfg)
    from golive.server.app import make_server
    from golive.backends.factory import get_registry, get_template_store
    server=make_server('127.0.0.1',0); thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_address[1]}'
    s=get_template_store(cfg); r=get_registry(cfg); ids=[]
    yield SimpleNamespace(cfg=cfg, base=base, data=s, registry=r, ids=ids, home=tmp_path, backend=backend)
    server.shutdown();server.server_close();thread.join(5)
    for ident in ids:r.delete(ident)
    if env:
        with s._conn() as c:c.execute(f'DROP TABLE {s.table}');c.commit()
    reset_config();reset_cache()


def cli(*args):
    from golive.cli import main
    output=io.StringIO()
    with redirect_stdout(output),redirect_stderr(io.StringIO()): code=main(list(args))
    assert code==0,output.getvalue()
    return output.getvalue()


def test_publish_page_http_crud_and_admin(live):
    page=live.home/'notes.html';page.write_text('<!doctype html><title>Acceptance</title><script>document.addEventListener("templateapi:ready",function(){window.ready=true;});</script><p>TemplateAPI.list()</p>')
    slug='accept-'+uuid.uuid4().hex[:10]
    cli('publish',str(page),'--slug',slug,'--data-model','http_notes')
    site=live.registry.get_by_slug(slug);live.ids.append(site['site_id'])
    response=requests.get(live.base+'/'+slug,timeout=10);assert response.ok
    assert 'TemplateAPI' in response.text
    for key in ['GOLIVE_PG_DSN','GOLIVE_MYSQL_DSN']:
        secret=os.environ.get(key)
        if secret and secret in response.text:pytest.fail('Database credential leaked into HTML')
    url=live.base+'/api/data/'+live.data.table
    payload={'model_code':'http_notes','name':'中文 🧪','content':{'nested':[1,True,None]}}
    response=requests.post(url,json=[payload],headers={'Prefer':'return=representation'},timeout=10)
    assert response.status_code in (200,201),response.text
    ident=response.json()[0]['id']
    response=requests.get(url,params={'id':'eq.'+ident},timeout=10);assert response.json()[0]['content']==payload['content']
    response=requests.patch(url,params={'id':'eq.'+ident},json={'content':{'updated':True}},timeout=10);assert response.ok
    assert requests.get(url,params={'id':'eq.'+ident},timeout=10).json()[0]['content']=={'updated':True}
    response=requests.get(live.base+'/api/admin/data/models',timeout=10);assert response.ok
    assert any(m['model_code']=='http_notes' for m in response.json()['models'])
    detail=requests.get(live.base+'/api/admin/sites/'+slug,timeout=10);assert detail.ok
    assert requests.delete(url,params={'id':'eq.'+ident},timeout=10).status_code in (200,204)
    assert requests.get(url,params={'id':'eq.'+ident},timeout=10).json()==[]


def test_verify_database_probe_and_no_probe_residue(live):
    from golive.server.connection_checks import check_data_backend
    before=live.data.query({},limit=1000,want_count=True)[1]
    status,result=check_data_backend({'backend':live.backend},live.cfg)
    assert status==200 and result['ok'] is True
    assert live.data.query({},limit=1000,want_count=True)[1]==before
    result=json.loads(cli('verify','--json'))
    assert result['ok'] is True
    assert any(s['step']=='data' and s['ok'] for s in result['steps'])
    assert live.data.query({},limit=1000,want_count=True)[1]==before


def test_export_import_and_persistence(live):
    slug='archive-'+uuid.uuid4().hex[:10]
    page=live.home/'archive.html';page.write_text('<html><title>Archive</title><p>persistent page</p></html>')
    cli('publish',str(page),'--slug',slug)
    site=live.registry.get_by_slug(slug);live.ids.append(site['site_id'])
    row=live.data.create('archive','row',content={'text':'持久化 🧪'})
    archive=live.home/'archive.tar.gz';cli('export','--output',str(archive))
    with tarfile.open(archive) as tf:
        rows=[json.loads(s) for s in tf.extractfile('data.jsonl').read().decode().splitlines()]
    assert any(r['content']=={'text':'持久化 🧪'} for r in rows)
    live.registry.delete(site['site_id']);live.data.delete(row['id'])
    cli('import',str(archive),'--yes')
    assert live.registry.get(site['site_id'])['slug']==slug
    from golive.backends.factory import get_template_store
    assert get_template_store(live.cfg).list('archive')['list'][0]['content']=={'text':'持久化 🧪'}
    cli('doctor','--port',str(live.base.rsplit(':',1)[1]),'--json')
