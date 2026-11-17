"""Minimal HS256 bearer JWT verification and role model."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TokenError(ValueError):
    """Raised for invalid, expired, or unauthorized bearer tokens."""


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    REVIEWER = "reviewer"


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    roles: frozenset[Role]


def _decode_segment(segment: str) -> bytes:
    if not segment or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=" for char in segment):
        raise TokenError("invalid bearer token")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise TokenError("invalid bearer token") from exc


class TokenVerifier:
    """Verify signed access tokens using a key obtained from a secret store."""

    def __init__(self, key: bytes, *, issuer: str, audience: str, clock_skew_seconds: int = 30):
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("token verification key must contain at least 32 bytes")
        if not issuer or not audience:
            raise ValueError("issuer and audience are required")
        if isinstance(clock_skew_seconds, bool) or not isinstance(clock_skew_seconds, int) or not 0 <= clock_skew_seconds <= 120:
            raise ValueError("clock skew must be between 0 and 120 seconds")
        self._key = key
        self._issuer = issuer
        self._audience = audience
        self._clock_skew = clock_skew_seconds

    def verify(self, token: str, *, now: int | None = None) -> Principal:
        if not isinstance(token, str) or len(token) > 8192:
            raise TokenError("invalid bearer token")
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenError("invalid bearer token")
        header_bytes, claims_bytes, signature = (_decode_segment(part) for part in parts)
        try:
            header = json.loads(header_bytes)
            claims = json.loads(claims_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TokenError("invalid bearer token") from exc
        if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise TokenError("unsupported bearer token")
        expected = hmac.new(self._key, f"{parts[0]}.{parts[1]}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            raise TokenError("invalid bearer token")
        if not isinstance(claims, dict):
            raise TokenError("invalid bearer token")
        current = int(time.time()) if now is None else now
        exp = claims.get("exp")
        nbf = claims.get("nbf", 0)
        if (isinstance(exp, bool) or not isinstance(exp, (int, float))
                or not math.isfinite(exp) or current >= exp + self._clock_skew):
            raise TokenError("bearer token expired or missing expiration")
        if (isinstance(nbf, bool) or not isinstance(nbf, (int, float))
                or not math.isfinite(nbf) or current + self._clock_skew < nbf):
            raise TokenError("bearer token is not active")
        if claims.get("iss") != self._issuer:
            raise TokenError("invalid bearer token")
        audience = claims.get("aud")
        if not (audience == self._audience or (isinstance(audience, list) and self._audience in audience)):
            raise TokenError("invalid bearer token")
        subject = claims.get("sub")
        raw_roles = claims.get("roles")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 256:
            raise TokenError("invalid bearer token")
        if not isinstance(raw_roles, list) or not raw_roles:
            raise TokenError("bearer token has no roles")
        try:
            roles = frozenset(Role(item) for item in raw_roles)
        except (ValueError, TypeError) as exc:
            raise TokenError("bearer token has an unsupported role") from exc
        return Principal(subject=subject, roles=roles)
