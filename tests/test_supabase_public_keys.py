"""Public Supabase keys survive restore, while privileged keys stay blocked."""
import base64
import json
import pytest
from golive.security.scanner import scan_html
from golive.inject import template_api, supabase_api


def token(role, issuer='supabase'):
    encode=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
    return encode({'alg':'HS256','typ':'JWT'})+'.'+encode({'iss':issuer,'role':role})+'.'+'a'*40


@pytest.mark.parametrize('key',['sb_publishable_'+'p'*32,token('anon')])
def test_public_key_does_not_block_archive(key):
    html=template_api.generate_js('notes',rest_url='https://project.supabase.co/rest/v1',anon_key=key)
    assert not scan_html(html).blocked
    # Merely labelling a script as golive never exempts an unrelated secret.
    assert scan_html(html.replace('</script>', 'const password="ActualSecretPassword42";</script>')).blocked


@pytest.mark.parametrize('key',['sb_secret_'+'s'*32,token('service_role'),token('authenticated')])
def test_privileged_key_cannot_reach_page(key):
    with pytest.raises(ValueError,match='anon/publishable'):
        template_api.generate_js('notes',anon_key=key)
    with pytest.raises(ValueError,match='anon/publishable'):
        supabase_api.generate_js('https://project.supabase.co',key)
    assert scan_html('<script>const apiKey="'+key+'";</script>').blocked


def test_unrelated_anon_jwt_is_still_scanned():
    assert scan_html('<script>const apiKey="'+token('anon','other-issuer')+'";</script>').blocked


def test_storage_factory_requires_explicit_project_credentials(monkeypatch):
    from golive.config import Config
    from golive.backends.factory import get_storage
    from unittest import mock
    cfg = Config(); cfg.storage.backend = 'supabase'
    cfg.supabase.url = 'https://other-project.supabase.co'
    monkeypatch.delenv('GOLIVE_SUPABASE_SERVICE_KEY', raising=False)
    monkeypatch.delenv('GOLIVE_SUPABASE_ANON_KEY', raising=False)
    with mock.patch('golive.backends.storage.supabase_store.SupabaseStorage') as constructor:
        with pytest.raises(ValueError, match="selected project's"):
            get_storage(cfg)
        constructor.assert_not_called()


def test_storage_redirect_never_counts_as_a_prune_lock():
    from golive.backends.storage.supabase_store import SupabaseStorage
    from unittest import mock
    from types import SimpleNamespace
    storage = SupabaseStorage(url='https://project.supabase.co', key='test-key', bucket='test')
    with mock.patch.object(storage, '_download', return_value=None), \
            mock.patch('requests.post', return_value=SimpleNamespace(status_code=302)) as post:
        assert not storage._try_acquire_prune_lock('synthetic')
        assert post.call_args.kwargs['allow_redirects'] is False
