"""WebDAV page files (RFC 4918), served through OpenGoLive.

Use a dedicated, pre-created collection URL. No browser credentials, cache,
redirect following or remote conditional editor writes. Requests verify TLS.
"""

import datetime
import re
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

import requests

BACKUP_MAX_KEEP = 10
MAX_RESPONSE = 16 * 1024 * 1024
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_TS = re.compile(r'\d{8}_\d{6}_\d{6}\Z')


class WebDAVError(RuntimeError):
    pass


class WebDAVStorage:
    def __init__(self, url, username='', password='', timeout=15):
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in ('https', 'http') and parsed.hostname and
                     not parsed.username and not parsed.password and
                     not parsed.query and not parsed.fragment)
            # Cleartext only for literal loopback fixtures/local servers.
            valid = valid and (parsed.scheme == 'https' or parsed.hostname in
                               ('127.0.0.1', '::1', 'localhost'))
            parts = unquote(parsed.path).split('/')
            valid = valid and not any(p in ('.', '..') for p in parts)
            valid = valid and not any(c in unquote(url) for c in ('\\', '\r', '\n', '\x00'))
            parsed.port  # validate port without leaking URL in errors
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError('WebDAV requires a credential-free HTTPS collection URL (HTTP allowed on loopback only)')
        if not 0 < float(timeout) <= 120:
            raise ValueError('WebDAV timeout must be >0 and <=120 seconds')
        self.url = url.rstrip('/') + '/'
        self.timeout = float(timeout)
        self.auth = (username, password) if username or password else None

    def _key(self, site_id, name='index.html'):
        if not isinstance(site_id, str) or not _ID.fullmatch(site_id):
            raise ValueError('invalid WebDAV site id')
        return site_id + '/' + name

    def _request(self, method, key, allowed, **kwargs):
        # No response/exception text or remote URL escapes this boundary.
        try:
            with requests.request(method, self.url + quote(key, safe='/'),
                                  auth=self.auth, timeout=(self.timeout, self.timeout),
                                  allow_redirects=False, stream=True, **kwargs) as r:
                code = r.status_code
                if code in (401, 403):
                    raise PermissionError('WebDAV access denied; check server credentials and collection permissions')
                if code == 404 and code not in allowed:
                    raise FileNotFoundError('WebDAV resource not found')
                if code not in allowed:
                    raise WebDAVError(f'WebDAV {method} failed (HTTP {code})')
                chunks, size = [], 0
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise WebDAVError('WebDAV response exceeds size limit')
                    chunks.append(chunk)
                return code, b''.join(chunks)
        except requests.RequestException:
            raise WebDAVError('WebDAV connection/TLS/timeout failure; verify endpoint, CA and proxy') from None

    def exists(self, site_id):
        return self._request('HEAD', self._key(site_id), {200, 404})[0] == 200

    def read(self, site_id, use_cache=True):
        payload = self._request('GET', self._key(site_id), {200})[1]
        try:
            return payload.decode('utf-8')
        except UnicodeDecodeError:
            raise WebDAVError('WebDAV page is not UTF-8') from None

    def public_url(self, site_id):
        return ''  # credentials and private NAS endpoints never injected into pages

    def _mkdir(self, key):
        self._request('MKCOL', key, {201, 405})

    def _put(self, key, html):
        self._request('PUT', key, {200, 201, 204}, data=html.encode('utf-8'),
                      headers={'Content-Type': 'text/html; charset=utf-8'})

    def publish(self, html, site_id, backup_previous=True):
        key = self._key(site_id)
        previous = None
        if backup_previous:
            try:
                previous = self.read(site_id)
            except FileNotFoundError:
                pass
        self._mkdir(self._key(site_id, ''))
        if previous is not None:
            self._mkdir(self._key(site_id, 'backups/'))
            ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self._put(self._key(site_id, 'backups/' + ts + '.html'), previous)
        self._put(key, html)
        if previous is not None:
            for snap in self.list_snapshots(site_id)[BACKUP_MAX_KEEP:]:
                self._request('DELETE', snap['path'], {200, 204, 404})
        return 'webdav://' + key

    def delete(self, site_id):
        # A 207 DELETE can contain partial failures. Never claim it succeeded.
        self._request('DELETE', self._key(site_id, ''), {200, 204, 404})

    def list_snapshots(self, site_id):
        key = self._key(site_id, 'backups/')
        code, payload = self._request('PROPFIND', key, {207, 404},
            headers={'Depth': '1', 'Content-Type': 'application/xml; charset=utf-8'},
            data=b'<d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/><d:resourcetype/></d:prop></d:propfind>')
        if code == 404:
            return []
        if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
            raise WebDAVError('unsafe WebDAV XML response')
        try:
            tree = ET.fromstring(payload)
            if tree.tag != '{DAV:}multistatus':
                raise ValueError()
            out = []
            prefix = unquote(urlsplit(self.url).path) + key
            origin = urlsplit(self.url)
            for row in tree.findall('{DAV:}response'):
                status = row.findtext('{DAV:}status', '')
                if status and status.split()[1:2] != ['200']:
                    raise WebDAVError('WebDAV snapshot listing incomplete')
                href = urlsplit(row.findtext('{DAV:}href', ''))
                if href.netloc and (href.netloc != origin.netloc or href.scheme != origin.scheme):
                    continue
                path = unquote(href.path)
                if not path.startswith(prefix):
                    continue
                name = path[len(prefix):]
                if not name.endswith('.html') or not _TS.fullmatch(name[:-5]):
                    continue
                for ps in row.findall('{DAV:}propstat'):
                    if ps.findtext('{DAV:}status', '').split()[1:2] != ['200']:
                        raise WebDAVError('WebDAV snapshot properties unavailable')
                    prop = ps.find('{DAV:}prop')
                    if prop is not None and prop.find('{DAV:}resourcetype/{DAV:}collection') is None:
                        out.append({'path': key + name, 'ts': name[:-5],
                                    'size': int(prop.findtext('{DAV:}getcontentlength', '0'))})
            return sorted(out, key=lambda s: s['ts'], reverse=True)
        except (ET.ParseError, ValueError, TypeError):
            raise WebDAVError('invalid WebDAV snapshot response') from None

    def rollback(self, site_id, snapshot_ts=''):
        if snapshot_ts and not _TS.fullmatch(snapshot_ts):
            raise ValueError('invalid WebDAV snapshot timestamp')
        snapshots = self.list_snapshots(site_id)
        matches = [s for s in snapshots if not snapshot_ts or s['ts'] == snapshot_ts]
        if not matches:
            raise FileNotFoundError('WebDAV snapshot not found')
        html = self._request('GET', matches[0]['path'], {200})[1].decode('utf-8')
        return self.publish(html, site_id)
