"""Superadmin-only group management, behind admin_api's identity gate."""

import json

from golive.backends.registry.group_store import get_group_store
from golive.core.audit import record


def handle_groups(method, rest, body, identity, registry, query=None):
    # Also guard direct callers: never trust a claimed member/actor in JSON.
    if not identity or not identity.is_superadmin:
        return 403, {'error': 'superadmin required'}
    try:
        store = get_group_store()
        if not rest and method == 'GET':
            return 200, {'groups': store.list()}
        if rest == ['audit'] and method == 'GET':
            query = query or {}
            limit = max(1, min(200, int((query.get('limit') or ['100'])[0])))
            before = int(query['before'][0]) if query.get('before') else None
            rows = store.events(limit + 1, before)
            return 200, {'events': rows[:limit],
                         'next_before': rows[limit-1]['id'] if len(rows) > limit else None}
        data = json.loads(body or b'{}')
        if not isinstance(data, dict):
            raise ValueError('body must be a JSON object')
        actor = identity.email or '(token)'
        if not rest and method == 'POST':
            action, args = 'create', {'value': data.get('name')}
        elif len(rest) == 1 and method == 'DELETE':
            action, args = 'delete', {'group_id': rest[0]}
        elif len(rest) == 2 and rest[1] == 'members' and method in ('POST', 'DELETE'):
            action = 'member.add' if method == 'POST' else 'member.remove'
            args = {'group_id': rest[0], 'value': data.get('email')}
        elif len(rest) == 2 and rest[1] == 'sites' and method in ('POST', 'DELETE'):
            ref = data.get('site')
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError('site must be a non-empty slug or ID')
            site = registry.resolve(ref)
            if not site:
                return 404, {'error': 'unknown site'}
            action = 'grant' if method == 'POST' else 'revoke'
            args = {'group_id': rest[0], 'site_id': site['site_id'], 'role': data.get('role', '')}
        else:
            return 404, {'error': 'unknown group endpoint'}
        result = store.change(action, actor, **args)
        if result['changed']:
            record(actor, 'perm.group.' + action, '', dict(args, group_id=result['group_id']))
        return 200, result
    except KeyError:
        return 404, {'error': 'unknown group'}
    except (ValueError, UnicodeDecodeError):
        return 400, {'error': 'invalid group request: check name, email, site and role'}
    except Exception:
        return 503, {'error': 'group permission store unavailable'}
