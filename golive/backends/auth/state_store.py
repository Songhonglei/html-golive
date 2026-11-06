"""Durable OIDC maps with hashed identifiers and atomic single-use state.

No connection or authorization cache: every lookup observes committed logout.
"""

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import MutableMapping
from contextlib import contextmanager


class StateUnavailable(RuntimeError):
    pass


class AuthState(MutableMapping):
    def __init__(self, path, realm, kind):
        self.path, self.realm, self.kind = str(path), realm, kind
        # Precreate privately; SQLite's default creation permissions follow umask.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        with self._conn() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS oidc_state ('
                         'realm TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, '
                         'value TEXT NOT NULL, exp REAL NOT NULL, '
                         'PRIMARY KEY(realm,kind,key))')
            conn.execute('CREATE INDEX IF NOT EXISTS oidc_state_exp ON oidc_state(exp)')

    @contextmanager
    def _conn(self):
        conn = None
        try:
            conn = sqlite3.connect(self.path, timeout=10)
            with conn:
                yield conn
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise StateUnavailable('OIDC state store unavailable') from None
        finally:
            if conn is not None:
                conn.close()

    def _args(self, key):
        return self.realm, self.kind, hashlib.sha256(key.encode('utf-8')).hexdigest()

    def __setitem__(self, key, value):
        with self._conn() as c:
            c.execute('DELETE FROM oidc_state WHERE exp<=?', (time.time(),))
            c.execute('INSERT OR REPLACE INTO oidc_state VALUES (?,?,?,?,?)',
                      (*self._args(key), json.dumps(value), value['exp']))

    def __getitem__(self, key):
        with self._conn() as c:
            row = c.execute('SELECT value FROM oidc_state WHERE realm=? AND kind=? AND key=? AND exp>?',
                            (*self._args(key), time.time())).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def pop(self, key, default=None):
        # Consumption must precede token exchange, and have exactly one winner.
        with self._conn() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT value,exp FROM oidc_state WHERE realm=? AND kind=? AND key=?',
                            self._args(key)).fetchone()
            c.execute('DELETE FROM oidc_state WHERE realm=? AND kind=? AND key=?', self._args(key))
        return json.loads(row[0]) if row and row[1] > time.time() else default

    def __delitem__(self, key):
        marker = object()
        if self.pop(key, marker) is marker:
            raise KeyError(key)

    def __iter__(self):
        # Identifiers are deliberately not recoverable from storage.
        raise TypeError('AuthState identifiers are not enumerable')

    def __len__(self):
        with self._conn() as c:
            return c.execute('SELECT count(*) FROM oidc_state WHERE realm=? AND kind=? AND exp>?',
                             (self.realm, self.kind, time.time())).fetchone()[0]

    def prune(self):
        with self._conn() as c:
            c.execute('DELETE FROM oidc_state WHERE exp<=?', (time.time(),))
