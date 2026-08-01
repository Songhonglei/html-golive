"""v0.8.0 OIDC hardening tests: signature verification, nonce, claims.

All tests are offline — JWKS is served by a local HTTP stub, tokens
are signed with a self-signed RSA key pair generated at test time.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOLIVE_HOME",
                      tempfile.mkdtemp(prefix="golive_test_oidc_h_"))

from golive.backends.auth.oidc_verify import (
    JWKSProvider, TokenValidationError, verify_id_token,
    is_available, require_cryptography,
)


# ── RSA key generation for tests ─────────────────────────────────────────────

def _generate_rsa_keypair():
    """Generate an RSA key pair for test signing."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # JWK format
    pub_numbers = public_key.public_numbers()
    def _int_b64url(n: int) -> str:
        byte_len = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(
            n.to_bytes(byte_len, "big")).rstrip(b"=").decode("ascii")

    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "kid": "test-key-1",
        "n": _int_b64url(pub_numbers.n),
        "e": _int_b64url(pub_numbers.e),
    }
    return private_key, public_key, jwk


def _sign_jwt(private_key, header: dict, payload: dict) -> str:
    """Create a signed JWT (RS256) for testing."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_b = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = (header_b + "." + payload_b).encode("ascii")
    signature = private_key.sign(
        signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b}.{payload_b}.{_b64url(signature)}"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_int(n: int) -> str:
    byte_len = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(
        n.to_bytes(byte_len, "big")).rstrip(b"=").decode("ascii")


class _JWKSStubHandler(BaseHTTPRequestHandler):
    """Serves a JWKS document with a single test key."""

    jwks = {"keys": []}

    def do_GET(self):  # noqa: N802
        payload = json.dumps(self.jwks).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


class TestOIDCSignatureVerification(unittest.TestCase):
    """Verify id_token signature, claims, and nonce."""

    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("cryptography not installed")
        cls.priv_key, cls.pub_key, cls.jwk = _generate_rsa_keypair()

        # Start JWKS stub server
        cls.jwks_server = HTTPServer(("127.0.0.1", 0), _JWKSStubHandler)
        cls.jwks_port = cls.jwks_server.server_address[1]
        cls.jwks_uri = f"http://127.0.0.1:{cls.jwks_port}/jwks"
        _JWKSStubHandler.jwks = {"keys": [cls.jwk]}
        cls.thread = threading.Thread(
            target=cls.jwks_server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.jwks_server.shutdown()
        cls.jwks_server.server_close()

    def _make_token(self, *, payload_overrides=None, header_overrides=None,
                    alg="RS256", kid="test-key-1", sign_with=None):
        """Create a signed JWT with the given overrides."""
        header = {"alg": alg, "kid": kid, "typ": "JWT"}
        if header_overrides:
            header.update(header_overrides)
        now = int(time.time())
        payload = {
            "iss": "https://test-idp.example.com",
            "aud": "test-client-id",
            "sub": "user-123",
            "email": "test@example.com",
            "iat": now,
            "exp": now + 3600,
        }
        if payload_overrides:
            payload.update(payload_overrides)

        signer = sign_with or self.priv_key
        if alg == "none":
            # alg=none: no signature
            header_b = _b64url(json.dumps(header, separators=(",", ":")).encode())
            payload_b = _b64url(json.dumps(payload, separators=(",", ":")).encode())
            return f"{header_b}.{payload_b}."

        return _sign_jwt(signer, header, payload)

    def _provider(self):
        return JWKSProvider(self.jwks_uri)

    # ── happy path ──

    def test_valid_token_passes(self):
        token = self._make_token()
        claims = verify_id_token(
            token,
            issuer="https://test-idp.example.com",
            client_id="test-client-id",
            jwks_provider=self._provider(),
            nonce=None,
        )
        self.assertEqual(claims["sub"], "user-123")
        self.assertEqual(claims["email"], "test@example.com")

    def test_valid_token_with_nonce(self):
        token = self._make_token(payload_overrides={"nonce": "abc123"})
        claims = verify_id_token(
            token,
            issuer="https://test-idp.example.com",
            client_id="test-client-id",
            jwks_provider=self._provider(),
            nonce="abc123",
        )
        self.assertEqual(claims["nonce"], "abc123")

    # ── signature attacks ──

    def test_tampered_payload_rejected(self):
        token = self._make_token()
        # Tamper with the payload
        parts = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        payload["email"] = "attacker@example.com"
        tampered_payload = _b64url(
            json.dumps(payload, separators=(",", ":")).encode())
        tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                tampered,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("signature", str(ctx.exception).lower())

    def test_alg_none_rejected(self):
        token = self._make_token(alg="none")
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("alg=none", str(ctx.exception))

    def test_wrong_key_rejected(self):
        """Token signed with a different key than the JWKS advertises."""
        other_priv, _, _ = _generate_rsa_keypair()
        token = self._make_token(sign_with=other_priv)
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("signature", str(ctx.exception).lower())

    # ── claims validation ──

    def test_expired_token_rejected(self):
        token = self._make_token(payload_overrides={
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,
        })
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("expired", str(ctx.exception).lower())

    def test_aud_mismatch_rejected(self):
        token = self._make_token(payload_overrides={"aud": "wrong-client"})
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("aud", str(ctx.exception).lower())

    def test_iss_mismatch_rejected(self):
        token = self._make_token(
            payload_overrides={"iss": "https://evil.example.com"})
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("iss", str(ctx.exception).lower())

    def test_nonce_mismatch_rejected(self):
        token = self._make_token(payload_overrides={"nonce": "correct"})
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
                nonce="wrong-nonce",
            )
        self.assertIn("nonce", str(ctx.exception).lower())

    # ── JWKS refresh ──

    def test_unknown_kid_triggers_refresh(self):
        """When kid is not in cache, a refresh is attempted."""
        token = self._make_token(kid="new-key-after-rotation")
        # Add the rotated key to the stub server
        new_priv, _, new_jwk = _generate_rsa_keypair()
        new_jwk["kid"] = "new-key-after-rotation"
        _JWKSStubHandler.jwks = {"keys": [self.jwk, new_jwk]}

        # Re-sign with the new key
        token = self._make_token(kid="new-key-after-rotation",
                                  sign_with=new_priv)
        claims = verify_id_token(
            token,
            issuer="https://test-idp.example.com",
            client_id="test-client-id",
            jwks_provider=self._provider(),
        )
        self.assertEqual(claims["sub"], "user-123")

        # Restore original JWKS
        _JWKSStubHandler.jwks = {"keys": [self.jwk]}

    def test_truly_unknown_kid_rejected(self):
        """When kid is not in JWKS even after refresh, reject."""
        token = self._make_token(kid="nonexistent-key")
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("kid", str(ctx.exception).lower())

    # ── nbf (not-before) ──

    def test_nbf_in_future_rejected(self):
        token = self._make_token(payload_overrides={
            "nbf": int(time.time()) + 600,
        })
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
            )
        self.assertIn("not yet valid", str(ctx.exception).lower())

    # ── verify_signature=False ──

    def test_verify_signature_false_skips_verification(self):
        """When verify_signature=False, signature is not checked."""
        token = self._make_token()
        # Tamper the signature
        parts = token.split(".")
        tampered = f"{parts[0]}.{parts[1]}.AAAA"
        claims = verify_id_token(
            tampered,
            issuer="https://test-idp.example.com",
            client_id="test-client-id",
            jwks_provider=self._provider(),
            verify_signature=False,
        )
        self.assertEqual(claims["sub"], "user-123")

    def test_alg_none_with_verify_false_still_rejected(self):
        """alg=none is rejected even when verify_signature=False."""
        token = self._make_token(alg="none")
        with self.assertRaises(TokenValidationError) as ctx:
            verify_id_token(
                token,
                issuer="https://test-idp.example.com",
                client_id="test-client-id",
                jwks_provider=self._provider(),
                verify_signature=False,
            )
        self.assertIn("alg=none", str(ctx.exception))


class TestCryptographyAvailability(unittest.TestCase):
    """Ensure the availability check and require_cryptography work."""

    def test_is_available(self):
        # In the test environment, cryptography should be installed
        self.assertTrue(is_available())

    def test_require_cryptography_when_available(self):
        # Should not raise when available
        require_cryptography()


if __name__ == "__main__":
    unittest.main()
