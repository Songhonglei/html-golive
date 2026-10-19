"""Identify deliberately public Supabase keys without trusting script markers."""
import base64
import json
import re

_TOKEN = re.compile(r'\bsb_publishable_[A-Za-z0-9_-]+\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def jwt_payload(key):
    try:
        part = key.split('.')[1]
        payload = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        return payload if isinstance(payload, dict) else {}
    except (ValueError, IndexError, UnicodeError):
        return {}


def is_public_supabase_key(key):
    if re.fullmatch(r'sb_publishable_[A-Za-z0-9_-]{20,}', key):
        return True
    payload = jwt_payload(key)
    return payload.get('role') == 'anon' and payload.get('iss') == 'supabase'


def mask_public_keys(content):
    # Only the token value is exempted. Everything else, including a secret
    # inserted inside a forged golive <script>, still goes through the scan.
    return _TOKEN.sub(lambda m: '<public-supabase-key>'
                      if is_public_supabase_key(m.group()) else m.group(), content)


def require_public_key(key):
    role = jwt_payload(key).get('role')
    if key.startswith('sb_secret_') or (role and role != 'anon'):
        raise ValueError('Supabase browser injection requires an anon/publishable key; '
                         'keep the service/secret key in GOLIVE_SUPABASE_SERVICE_KEY on the server.')
