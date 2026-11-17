import base64
import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.auth.tokens import TokenVerifier
from flowx_os.db.content import (
    BrandRecord,
    ContentRecord,
    OwnedBrandNotFound,
    OwnedContentNotFound,
    RepositoryUnavailable,
)
from flowx_os.domain.content_state import InvalidContentTransition


KEY = b"test-key-that-is-long-enough-for-hmac"
BRAND_ID = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


class StubPool:
    """Marker pool; repository calls are replaced at the API boundary."""


class StubRepository:
    owner_ids: list[str] = []
    brand_ids: list[UUID] = []
    failures: dict[str, Exception] = {}

    def __init__(self, _pool):
        pass

    async def create_brand(self, *, owner_user_id, name, timezone_name, niche, audience):
        self._raise_configured("create_brand")
        self.owner_ids.append(owner_user_id)
        return BrandRecord(BRAND_ID, name, owner_user_id, timezone_name, niche, audience, NOW, NOW)

    async def list_brands(self, *, owner_user_id):
        self._raise_configured("list_brands")
        self.owner_ids.append(owner_user_id)
        return [BrandRecord(BRAND_ID, "Studio", owner_user_id, "Asia/Kolkata", "", "", NOW, NOW)]

    async def create_content(self, *, brand_id, owner_user_id, title, idea_text, topic,
                             audience_segment, language, target_duration_seconds, priority):
        self._raise_configured("create_content")
        self.owner_ids.append(owner_user_id)
        self.brand_ids.append(brand_id)
        return ContentRecord(CONTENT_ID, brand_id, title, idea_text, topic, audience_segment,
                             language, target_duration_seconds, priority, "IDEA", NOW)

    async def list_content(self, *, brand_id, owner_user_id):
        self._raise_configured("list_content")
        self.owner_ids.append(owner_user_id)
        self.brand_ids.append(brand_id)
        return [ContentRecord(CONTENT_ID, brand_id, "Launch", "An idea", None, None,
                              "en-IN", 32, 3, "IDEA", NOW)]

    async def transition_content(self, *, brand_id, content_id, owner_user_id, target_status):
        self._raise_configured("transition_content")
        self.owner_ids.append(owner_user_id)
        self.brand_ids.append(brand_id)
        return ContentRecord(content_id, brand_id, "Launch", "An idea", None, None,
                             "en-IN", 32, 3, target_status.value, NOW)

    @classmethod
    def _raise_configured(cls, operation):
        if operation in cls.failures:
            raise cls.failures[operation]


class ContentApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        StubRepository.owner_ids = []
        StubRepository.brand_ids = []
        StubRepository.failures = {}
        verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        token = _signed_token(KEY, roles=["operator"], now=int(time.time()))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(token_verifier=verifier, database_pool=StubPool())
            ),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.repository_patch = patch("flowx_os.api.main.ContentRepository", StubRepository)
        self.repository_patch.start()

    async def asyncTearDown(self):
        self.repository_patch.stop()
        await self.client.aclose()

    async def test_brand_create_and_list_are_bound_to_authenticated_owner(self):
        created = await self.client.post("/api/v1/brands", json={"name": " Studio "})
        listed = await self.client.get("/api/v1/brands")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "Studio")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(StubRepository.owner_ids, ["operator-1", "operator-1"])

    async def test_content_create_and_list_use_requested_brand_and_owner(self):
        payload = {"title": " Launch ", "idea_text": " An idea ", "priority": 5}
        created = await self.client.post(f"/api/v1/brands/{BRAND_ID}/content", json=payload)
        listed = await self.client.get(f"/api/v1/brands/{BRAND_ID}/content")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "IDEA")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(StubRepository.owner_ids, ["operator-1", "operator-1"])
        self.assertEqual(StubRepository.brand_ids, [BRAND_ID, BRAND_ID])

    async def test_empty_or_whitespace_required_fields_are_rejected(self):
        blank_brand = await self.client.post("/api/v1/brands", json={"name": "   "})
        blank_content = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content",
            json={"title": "Title", "idea_text": "  "},
        )
        invalid_priority = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content",
            json={"title": "Title", "idea_text": "Idea", "priority": 0},
        )
        self.assertEqual(blank_brand.status_code, 422)
        self.assertEqual(blank_content.status_code, 422)
        self.assertEqual(invalid_priority.status_code, 422)

    async def test_content_routes_fail_closed_when_database_is_unconfigured(self):
        verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        app = create_app(token_verifier=verifier)
        token = _signed_token(KEY, roles=["operator"], now=int(time.time()))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.get("/api/v1/brands")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "database_not_configured")

    async def test_missing_or_foreign_brand_maps_to_same_404_for_both_content_routes(self):
        StubRepository.failures = {
            "create_content": OwnedBrandNotFound("brand not found"),
            "list_content": OwnedBrandNotFound("brand not found"),
        }
        created = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content",
            json={"title": "Launch", "idea_text": "An idea"},
        )
        listed = await self.client.get(f"/api/v1/brands/{BRAND_ID}/content")
        self.assertEqual((created.status_code, created.json()), (404, {"detail": "brand_not_found"}))
        self.assertEqual((listed.status_code, listed.json()), (404, {"detail": "brand_not_found"}))

    async def test_configured_database_failures_return_safe_503(self):
        StubRepository.failures = {"list_brands": RepositoryUnavailable("private db details")}
        response = await self.client.get("/api/v1/brands")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "database_unavailable"})
        self.assertNotIn("private", response.text)

    async def test_reviewer_role_cannot_write_brands(self):
        verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        token = _signed_token(KEY, roles=["reviewer"], now=int(time.time()))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier, database_pool=StubPool())),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.post("/api/v1/brands", json={"name": "Studio"})
        self.assertEqual(response.status_code, 403)

    async def test_transition_route_returns_typed_status_and_owner_subject(self):
        response = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/transition",
            json={"target_status": "RESEARCHED"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "RESEARCHED")
        self.assertEqual(StubRepository.owner_ids, ["operator-1"])
        self.assertEqual(StubRepository.brand_ids, [BRAND_ID])

    async def test_transition_route_maps_domain_errors_safely(self):
        url = f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/transition"
        StubRepository.failures = {"transition_content": InvalidContentTransition("private details")}
        invalid = await self.client.post(url, json={"target_status": "RESEARCHED"})
        StubRepository.failures = {"transition_content": OwnedContentNotFound("private details")}
        missing = await self.client.post(url, json={"target_status": "RESEARCHED"})
        self.assertEqual((invalid.status_code, invalid.json()), (409, {"detail": "invalid_content_transition"}))
        self.assertEqual((missing.status_code, missing.json()), (404, {"detail": "content_not_found"}))
        self.assertNotIn("private", invalid.text + missing.text)

    async def test_unknown_transition_target_is_rejected(self):
        response = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/transition",
            json={"target_status": "UNKNOWN"},
        )
        self.assertEqual(response.status_code, 422)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _signed_token(key: bytes, *, roles: list[str], now: int) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iss": "flowx-test", "aud": "flowx-api", "sub": "operator-1",
        "roles": roles, "iat": now - 1, "nbf": now - 1, "exp": now + 60,
    }).encode())
    signing_input = f"{header}.{claims}"
    signature = _b64(hmac.new(key, signing_input.encode("ascii"), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


if __name__ == "__main__":
    unittest.main()
