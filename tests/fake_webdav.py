"""Isolated RFC4918 subset fixture; no external NAS credentials or state."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import threading
from urllib.parse import unquote
from xml.etree import ElementTree as ET


class DAVFixture:
    def __init__(self):
        self.files = {}
        self.collections = {'/dav/'}
        self.calls = []
        self.failure = None
        self.failures = {}
        self.propfind = None
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                path = unquote(self.path)
                fixture.calls.append((self.command, path))
                length = int(self.headers.get('Content-Length', 0))
                data = self.rfile.read(length)
                expected = 'Basic ' + base64.b64encode(b'test-user:test-password').decode()
                if self.headers.get('Authorization') != expected:
                    return self.respond(401)
                failure = fixture.failures.get((self.command, path)) or fixture.failure
                if failure:
                    code, payload = failure
                    return self.respond(code, payload)
                if self.command == 'MKCOL':
                    if path in fixture.collections:
                        return self.respond(405)
                    parent = path.rstrip('/').rsplit('/', 1)[0] + '/'
                    if parent not in fixture.collections:
                        return self.respond(409)
                    fixture.collections.add(path)
                    return self.respond(201)
                if self.command in ('GET', 'HEAD'):
                    if path not in fixture.files:
                        return self.respond(404)
                    return self.respond(200, fixture.files[path])
                if self.command == 'PUT':
                    if path.rsplit('/', 1)[0] + '/' not in fixture.collections:
                        return self.respond(409)
                    fixture.files[path] = data
                    return self.respond(201)
                if self.command == 'DELETE':
                    fixture.files = {k: v for k, v in fixture.files.items()
                                     if k != path and not k.startswith(path if path.endswith('/') else path + '/')}
                    fixture.collections = {k for k in fixture.collections if not k.startswith(path)}
                    return self.respond(204)
                if self.command == 'PROPFIND':
                    assert self.headers['Depth'] == '1'
                    if fixture.propfind is not None:
                        return self.respond(207, fixture.propfind)
                    if path not in fixture.collections:
                        return self.respond(404)
                    tree = ET.Element('{DAV:}multistatus')
                    for key in [path] + sorted(k for k in fixture.files if k.startswith(path)):
                        row = ET.SubElement(tree, '{DAV:}response')
                        ET.SubElement(row, '{DAV:}href').text = key
                        ps = ET.SubElement(row, '{DAV:}propstat')
                        ET.SubElement(ps, '{DAV:}status').text = 'HTTP/1.1 200 OK'
                        prop = ET.SubElement(ps, '{DAV:}prop')
                        ET.SubElement(prop, '{DAV:}getcontentlength').text = str(len(fixture.files.get(key, b'')))
                        rt = ET.SubElement(prop, '{DAV:}resourcetype')
                        if key == path:
                            ET.SubElement(rt, '{DAV:}collection')
                    return self.respond(207, ET.tostring(tree))
                return self.respond(405)

            def respond(self, code, data=b''):
                self.send_response(code)
                if code in (301, 302, 307, 308):
                    self.send_header('Location', fixture.url + 'redirected')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(data)

            do_GET = do_HEAD = do_PUT = do_DELETE = do_MKCOL = do_PROPFIND = handle_request

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:%s/dav/' % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
