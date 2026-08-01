"""Adversarial tests for the OIDC id_token verifier.

Written against the verifier rather than alongside it: each case is an
attack someone would actually try, and every one of them must be
rejected. Two real holes were found this way and are pinned below —
a token with no `exp` (valid forever) and a clock-skew window wide
enough to keep expired tokens alive for minutes.
"""
from __future__ import annotations

import base64
import json
import time

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

import unittest

from golive.backends.auth import oidc_verify as V

ISS = "https://idp.example.com"
AUD = "my-client-id"

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pub = key.public_key()
evil = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwks_of(public_key, kid="k1"):
    n = public_key.public_numbers().n
    e = public_key.public_numbers().e
    return {"keys": [{
        "kty": "RSA", "kid": kid, "alg": "RS256", "use": "sig",
        "n": b64(n.to_bytes((n.bit_length() + 7) // 8, "big")),
        "e": b64(e.to_bytes((e.bit_length() + 7) // 8, "big")),
    }]}


def make(payload, signer=None, alg="RS256", kid="k1", sig=None):
    head = {"alg": alg, "typ": "JWT"}
    if kid:
        head["kid"] = kid
    h = b64(json.dumps(head).encode())
    p = b64(json.dumps(payload).encode())
    signing_input = f"{h}.{p}".encode()
    if sig is not None:
        s = sig
    elif signer is None:
        s = ""
    else:
        s = b64(signer.sign(signing_input, padding.PKCS1v15(), hashes.SHA256()))
    return f"{h}.{p}.{s}"


def good_payload(**over):
    now = int(time.time())
    p = {"iss": ISS, "aud": AUD, "sub": "user-1", "email": "u@example.com",
         "exp": now + 600, "iat": now, "nonce": "N1"}
    p.update(over)
    return p


def verify(token, nonce="N1", jwks=None):
    doc = jwks if jwks is not None else jwks_of(pub)
    provider = V.JWKSProvider("https://idp.example.com/jwks",
                              fetcher=lambda url, **kw: doc)
    return V.verify_id_token(
        token, issuer=ISS, client_id=AUD, nonce=nonce,
        jwks_provider=provider,
    )




class TestForgedSignatures(unittest.TestCase):
    """Nothing may be accepted without a valid signature from the IdP."""

    def _rejects(self, token, **kw):
        with self.assertRaises(Exception):
            verify(token, **kw)

    def test_control_legitimate_token_is_accepted(self):
        """Guard against a verifier that simply rejects everything."""
        claims = verify(make(good_payload(), key))
        self.assertEqual(claims["sub"], "user-1")

    def test_alg_none_is_rejected(self):
        self._rejects(make(good_payload(), None, alg="none"))

    def test_alg_none_uppercase_is_rejected(self):
        """A case-insensitive bypass of the alg check."""
        self._rejects(make(good_payload(), None, alg="NONE"))

    def test_attacker_signed_token_is_rejected(self):
        self._rejects(make(good_payload(), evil))

    def test_tampered_payload_is_rejected(self):
        tok = make(good_payload(), key)
        h, _, s = tok.split(".")
        forged = b64(json.dumps(good_payload(sub="admin")).encode())
        self._rejects(f"{h}.{forged}.{s}")

    def test_stripped_signature_is_rejected(self):
        h, p, _ = make(good_payload(), key).split(".")
        self._rejects(f"{h}.{p}.")

    def test_hs256_algorithm_confusion_is_rejected(self):
        """The classic attack: sign with HMAC using the RSA public key."""
        import hmac as _h, hashlib
        head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
        body_ = b64(json.dumps(good_payload()).encode())
        pem = pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        mac = _h.new(pem, f"{head}.{body_}".encode(), hashlib.sha256).digest()
        self._rejects(f"{head}.{body_}.{b64(mac)}")

    def test_unknown_kid_is_rejected(self):
        self._rejects(make(good_payload(), key, kid="unknown-kid"))

    def test_empty_jwks_is_rejected(self):
        self._rejects(make(good_payload(), key), jwks={"keys": []})

    def test_garbage_input_is_rejected(self):
        self._rejects("not.a.jwt")


class TestClaimValidation(unittest.TestCase):

    def _rejects(self, token, **kw):
        with self.assertRaises(Exception):
            verify(token, **kw)

    def test_token_without_exp_is_rejected(self):
        """A token with no expiry would be valid forever if leaked."""
        p = good_payload()
        p.pop("exp")
        self._rejects(make(p, key))

    def test_expired_token_is_rejected(self):
        self._rejects(make(good_payload(exp=int(time.time()) - 3600), key))

    def test_expiry_just_past_the_skew_window_is_rejected(self):
        """Clock tolerance must not quietly extend a token's life."""
        self._rejects(make(good_payload(exp=int(time.time()) - 120), key))

    def test_clock_skew_stays_tight(self):
        """A generous skew silently keeps every expired token alive."""
        self.assertLessEqual(
            V.CLOCK_SKEW, 120,
            "clock skew tolerance is wide enough to weaken exp checks")

    def test_recently_expired_within_skew_is_accepted(self):
        """Real clock drift between hosts must not lock users out."""
        claims = verify(make(good_payload(exp=int(time.time()) - 5), key))
        self.assertEqual(claims["sub"], "user-1")

    def test_lookalike_issuer_is_rejected(self):
        self._rejects(make(good_payload(iss=ISS + ".evil.co"), key))

    def test_audience_mismatch_is_rejected(self):
        self._rejects(make(good_payload(aud="someone-else"), key))

    def test_nonce_mismatch_is_rejected(self):
        """Replaying an old token with a stale nonce."""
        self._rejects(make(good_payload(nonce="OLD"), key))

    def test_missing_nonce_is_rejected_when_one_was_requested(self):
        p = good_payload()
        p.pop("nonce")
        self._rejects(make(p, key))

    def test_future_nbf_is_rejected(self):
        self._rejects(make(good_payload(nbf=int(time.time()) + 3600), key))


if __name__ == "__main__":
    unittest.main()
