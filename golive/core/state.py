"""Optional same-host control state, independent of per-process HOME.

SQLite must reside on local disk. This is not a distributed state backend.
Resolution is environment-only, before config/settings are loaded.
"""

import os
from pathlib import Path


def state_dir(create=False):
    from golive.core.paths import peek_home
    value = os.environ.get('GOLIVE_STATE_DIR', '').strip()
    path = Path(value).expanduser() if value else peek_home()
    if not path.is_absolute():
        raise ValueError('GOLIVE_STATE_DIR must be an absolute local-disk path')
    path = path.resolve()
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def management_db():
    """Legacy path stays unchanged until explicit opt-in (no implicit migration)."""
    if os.environ.get('GOLIVE_STATE_DIR', '').strip():
        path = state_dir(create=True) / 'management.db'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        return path
    from golive.core.paths import get_registry_db
    return get_registry_db()


def inventory():
    """Read-only inventory; no filesystem creation or secret reads."""
    from golive.core.paths import peek_home
    home = peek_home()
    root = state_dir()
    shared = bool(os.environ.get('GOLIVE_STATE_DIR', '').strip())
    return {
        'mode': 'same_host_shared' if shared else 'single_instance',
        'directory': str(root),
        'source': 'GOLIVE_STATE_DIR' if shared else 'home',
        'sessions': str(root / 'sessions.db'),
        'cookie_key': str(root / '.cookie_secret'),
        'management': str(root / 'management.db' if shared else home / 'registry.db'),
        'instance_local': ['registry (unless remote)', 'page files/backups (unless remote)',
                           'data (unless remote)', 'config/settings', 'service PID/logs',
                           'scan/rule stores', 'cache', 'audit.log'],
        'constraints': ['local disk only; no NFS/SMB SQLite',
                        'same issuer/client/signing key required',
                        'matching config and shared registry/page/data backends required for one logical service',
                        'no cross-host HA or distributed background jobs'],
    }
