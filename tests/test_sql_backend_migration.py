"""Real migration pairs across SQLite, PostgreSQL and MySQL."""
import os
import uuid
from dataclasses import replace
from itertools import permutations

import pytest

from golive.config import Config,set_config,reset_config
from golive.core.paths import reset_cache
from golive.backends.factory import get_template_store,get_registry
from golive.core.portability import migrate_backend


@pytest.mark.parametrize('source,target',list(permutations(['sqlite','postgres','mysql'],2)))
def test_business_data_migration_pair(source,target,tmp_path,monkeypatch):
    for backend in (source,target):
        env={'postgres':'GOLIVE_PG_DSN','mysql':'GOLIVE_MYSQL_DSN'}.get(backend)
        if env and not os.environ.get(env): pytest.skip(env+' not configured')
    monkeypatch.setenv('GOLIVE_HOME',str(tmp_path));reset_cache();reset_config()
    cfg=Config();cfg.data.backend=source;cfg.data.templates_table='migration_'+uuid.uuid4().hex[:10];set_config(cfg)
    source_store=get_template_store(cfg)
    for i in range(5):source_store.create('model','row-'+str(i),content={'中文':'迁移 🧪','index':i},user_id='acceptance')
    target_cfg=replace(cfg,data=replace(cfg.data,backend=target))
    try:
        preview=migrate_backend('data',target,dry_run=True,cfg=cfg)
        assert preview['source_count']==5
        result=migrate_backend('data',target,cfg=cfg)
        assert result['ok'] and result['count_ok'], result
        assert result['migrated']==5
        target_store=get_template_store(target_cfg)
        assert {r['name']:r['content'] for r in target_store.list('model')['list']}=={r['name']:r['content'] for r in source_store.list('model')['list']}
        assert source_store.count('model')==5
    finally:
        for backend in set((source,target)) & {'postgres','mysql'}:
            st=get_template_store(replace(cfg,data=replace(cfg.data,backend=backend)))
            with st._conn() as c:c.execute(f'DROP TABLE {st.table}');c.commit()
        reset_cache();reset_config()
