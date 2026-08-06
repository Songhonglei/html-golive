"""A minimal but standards-correct OIDC identity provider, for end-to-end tests.

Real IdPs are heavy to run in CI; this one is ~200 lines and speaks enough
of the protocol to prove the whole login round trip works: discovery, JWKS,
the authorization redirect, code exchange, and a properly signed id_token.

It can also misbehave on purpose (see the `evil_*` flags) so we can prove the
client rejects a hostile IdP rather than merely tolerating a friendly one.
"""
from __future__ import annotations

import base64
import json
import socketserver
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes


class _QuietHTTPServer(HTTPServer):
    """HTTPServer without the reverse-DNS lookup in server_bind().

    The stock implementation calls socket.getfqdn(), which can hang for
    a long time on macOS when asked to resolve 127.0.0.1 — the same trap
    the production server had to work around.
    """

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class FakeIdP:
    def __init__(self, port: int, client_id="golive-test", client_secret="s3cr3t"):
        self.port = port
        self.issuer = "http://127.0.0.1:{}".format(port)
        self.client_id = client_id
        self.client_secret = client_secret
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key-1"
        self.codes = {}          # code -> {nonce, sub, email}
        self.user = {"sub": "u-1001", "email": "alice@corp.example",
                     "name": "Alice", "preferred_username": "alice"}
        # deliberate misbehaviour switches, off by default
        self.evil_sign_with_other_key = False
        self.evil_wrong_aud = False
        self.evil_expired = False
        self.evil_drop_nonce = False
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._srv = None
        self._thread = None

    # ── protocol documents ──────────────────────────────────────────────
    def discovery(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": self.issuer + "/authorize",
            "token_endpoint": self.issuer + "/token",
            "userinfo_endpoint": self.issuer + "/userinfo",
            "jwks_uri": self.issuer + "/jwks",
            "end_session_endpoint": self.issuer + "/logout",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "email"],
            "code_challenge_methods_supported": ["S256"],
        }

    def jwks(self) -> dict:
        pub = self.key.public_key().public_numbers()
        return {"keys": [{
            "kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid,
            "n": b64(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")),
            "e": b64(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")),
        }]}

    def make_id_token(self, nonce: str) -> str:
        now = int(time.time())
        payload = dict(self.user)
        payload.update({
            "iss": self.issuer,
            "aud": "wrong-client" if self.evil_wrong_aud else self.client_id,
            "iat": now,
            "exp": now - 3600 if self.evil_expired else now + 600,
        })
        if not self.evil_drop_nonce and nonce:
            payload["nonce"] = nonce
        header = {"alg": "RS256", "typ": "JWT", "kid": self.kid}
        h = b64(json.dumps(header).encode())
        p = b64(json.dumps(payload).encode())
        signer = self.other_key if self.evil_sign_with_other_key else self.key
        sig = signer.sign("{}.{}".format(h, p).encode(),
                          padding.PKCS1v15(), hashes.SHA256())
        return "{}.{}.{}".format(h, p, b64(sig))

    # ── server plumbing ─────────────────────────────────────────────────
    def start(self):
        idp = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path, _, qs = self.path.partition("?")
                q = urllib.parse.parse_qs(qs)
                if path == "/.well-known/openid-configuration":
                    return self._json(idp.discovery())
                if path == "/jwks":
                    return self._json(idp.jwks())
                if path == "/authorize":
                    # a real IdP would show a login form; we auto-approve
                    code = "code-{}".format(len(idp.codes) + 1)
                    idp.codes[code] = {"nonce": (q.get("nonce") or [""])[0]}
                    redirect = (q.get("redirect_uri") or [""])[0]
                    state = (q.get("state") or [""])[0]
                    dest = "{}?code={}&state={}".format(redirect, code, urllib.parse.quote(state))
                    self.send_response(302)
                    self.send_header("Location", dest)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if path == "/userinfo":
                    return self._json(idp.user)
                if path == "/logout":
                    self.send_response(302)
                    self.send_header("Location", (q.get("post_logout_redirect_uri") or ["/"])[0])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._json({"error": "not_found"}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode()
                form = urllib.parse.parse_qs(raw)
                if self.path.startswith("/token"):
                    code = (form.get("code") or [""])[0]
                    entry = idp.codes.pop(code, None)
                    if entry is None:
                        return self._json({"error": "invalid_grant"}, 400)
                    return self._json({
                        "access_token": "at-" + code,
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "id_token": idp.make_id_token(entry["nonce"]),
                    })
                self._json({"error": "not_found"}, 404)

        self._srv = _QuietHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
