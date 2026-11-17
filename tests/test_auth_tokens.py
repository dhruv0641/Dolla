import base64
import hashlib
import hmac
import json
import unittest

from flowx_os.auth.tokens import Role, TokenError, TokenVerifier


KEY = b"unit-test-key-with-at-least-32-bytes"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def token_for(claims: dict, *, alg: str = "HS256") -> str:
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    signed = f"{head}.{body}"
    signature = b64(hmac.new(KEY, signed.encode("ascii"), hashlib.sha256).digest())
    return f"{signed}.{signature}"


def claims(**overrides):
    result = {
        "iss": "flowx-test", "aud": "flowx-api", "sub": "user-7",
        "roles": ["operator"], "exp": 1100, "nbf": 900,
    }
    result.update(overrides)
    return result


class TokenVerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)

    def test_verifies_identity_and_supported_roles(self):
        principal = self.verifier.verify(token_for(claims()), now=1000)
        self.assertEqual(principal.subject, "user-7")
        self.assertEqual(principal.roles, frozenset({Role.OPERATOR}))

    def test_rejects_expired_token(self):
        with self.assertRaisesRegex(TokenError, "expired"):
            self.verifier.verify(token_for(claims(exp=999)), now=1000)

    def test_rejects_non_finite_expiration(self):
        with self.assertRaisesRegex(TokenError, "expired"):
            self.verifier.verify(token_for(claims(exp=float("nan"))), now=1000)

    def test_rejects_not_yet_valid_token(self):
        with self.assertRaisesRegex(TokenError, "not active"):
            self.verifier.verify(token_for(claims(nbf=1001)), now=1000)

    def test_rejects_wrong_issuer_or_audience(self):
        for token_claims in (claims(iss="other"), claims(aud="other")):
            with self.subTest(claims=token_claims):
                with self.assertRaisesRegex(TokenError, "invalid bearer"):
                    self.verifier.verify(token_for(token_claims), now=1000)

    def test_rejects_unknown_role_and_unsupported_algorithm(self):
        with self.assertRaisesRegex(TokenError, "unsupported role"):
            self.verifier.verify(token_for(claims(roles=["root"])), now=1000)
        with self.assertRaisesRegex(TokenError, "unsupported"):
            self.verifier.verify(token_for(claims(), alg="none"), now=1000)

    def test_rejects_tampered_signature(self):
        signed = token_for(claims())
        changed = signed[:-1] + ("A" if signed[-1] != "A" else "B")
        with self.assertRaises(TokenError):
            self.verifier.verify(changed, now=1000)

    def test_requires_sufficient_key_length(self):
        with self.assertRaises(ValueError):
            TokenVerifier(b"short", issuer="i", audience="a")


if __name__ == "__main__":
    unittest.main()
