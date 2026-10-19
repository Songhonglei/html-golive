"""MySQL parsing, lazy dependency and protocol checks require no live server."""
import inspect
import sys
from unittest import mock

import pytest
from golive.backends._mysql import connection_options, mysql_connect


def test_percent_encoded_credentials_and_ipv6():
    options = connection_options('mysql://name%40team:p%40ss%3Aword@[::1]:3307/db%2Dtest')
    assert options['user'] == 'name@team'
    assert options['password'] == 'p@ss:word'
    assert options['host'] == '::1' and options['port'] == 3307
    assert options['database'] == 'db-test' and options['local_infile'] is False


def test_remote_tls_verifies_peer_and_hostname():
    options = connection_options('mysql://user:pass@db.example/test?ssl_ca=/tmp/ca.pem')
    assert options['ssl_ca'] == '/tmp/ca.pem'
    assert options['ssl_verify_cert'] and options['ssl_verify_identity']
    options = connection_options('mysql://user:pass@db.example/test')
    assert options['ssl_verify_cert'] and options['ssl_verify_identity']


@pytest.mark.parametrize('dsn', [
    'postgres://user:SECRET@host/db', 'mysql://user:SECRET@host',
    'mysql://user:SECRET@host:bad/db', 'mysql://user:SECRET@host/db?local_infile=1',
    'mysql://user:SECRET@host/db?ssl_verify_identity=false',
    'mysql://user:SECRET@host/db?ssl_ca=a&ssl_ca=b',
])
def test_invalid_dsn_never_echoes_password(dsn):
    with pytest.raises(ValueError) as error:
        connection_options(dsn)
    assert 'SECRET' not in str(error.value)


def test_missing_driver_is_actionable():
    with mock.patch.dict(sys.modules, {'pymysql': None}):
        with pytest.raises(ImportError, match=r'html-golive\[mysql\]'):
            mysql_connect()


def test_mysql_methods_match_sqlite_contract():
    from golive.backends.data.sqlite_store import TemplateStore as SQLiteData
    from golive.backends.data.mysql_store import TemplateStore as MySQLData
    from golive.backends.registry.sqlite_store import SqliteRegistry
    from golive.backends.registry.mysql_store import MySQLRegistry
    for source, target in [(SQLiteData, MySQLData), (SqliteRegistry, MySQLRegistry)]:
        expected = {n: inspect.signature(f) for n,f in inspect.getmembers(source, inspect.isfunction) if not n.startswith('_')}
        actual = {n: inspect.signature(f) for n,f in inspect.getmembers(target, inspect.isfunction) if not n.startswith('_')}
        assert expected == actual


def test_explicit_config_reaches_mysql_store():
    from golive.config import Config
    from golive.backends.factory import get_template_store
    cfg = Config(); cfg.data.backend = 'mysql'
    cfg.registry.mysql_dsn_env = 'PRIVATE_MYSQL_ENV'; cfg.data.templates_table = 'custom_data'
    with mock.patch('golive.backends.data.mysql_store.TemplateStore') as constructor:
        get_template_store(cfg)
        constructor.assert_called_once_with(dsn_env='PRIVATE_MYSQL_ENV', table='custom_data')


@pytest.mark.parametrize('backend', ['postgres', 'mysql'])
def test_print_sql_works_without_driver_or_connection(backend, monkeypatch, capsys):
    from types import SimpleNamespace
    from golive.config import Config, set_config, reset_config
    from golive.cli import cmd_db
    cfg = Config(); cfg.registry.backend = cfg.data.backend = backend
    set_config(cfg)
    try:
        monkeypatch.delenv('GOLIVE_MYSQL_DSN', raising=False)
        monkeypatch.delenv('GOLIVE_PG_DSN', raising=False)
        with mock.patch('golive.backends.factory.get_template_store', side_effect=AssertionError('must not connect')):
            assert cmd_db(SimpleNamespace(print_sql=True)) == 0
        output = capsys.readouterr().out
        assert 'CREATE TABLE' in output and 'sites' in output and 'golive_templates' in output
        assert ('ENGINE=InnoDB' in output) == (backend == 'mysql')
    finally:
        reset_config()
