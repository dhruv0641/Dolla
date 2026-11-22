import base64
import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from flowx_os.api.main import create_app
from flowx_os.auth.tokens import TokenVerifier
from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.human_reviews import HumanReviewConflict, HumanReviewNotAllowed
from flowx_os.qa.human_review import HumanReviewRecord


KEY = b"test-key-that-is-long-enough-for-hmac"
BRAND_ID = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
ASSET_ID = UUID("c968b108-6450-472d-8358-7439dd66d109")
REPORT_ID = UUID("246b6765-566d-46cb-acad-24f3d248e2fc")
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


class StubPool:
    pass


class StubReviewRepository:
    failure = None
    calls = []

    def __init__(self, _pool):
        pass

    async def create_or_get(self, *, decision_id, brand_id, owner_user_id, request):
        self.calls.append((decision_id, brand_id, owner_user_id, request))
        if self.failure:
            raise self.failure
        return HumanReviewRecord(decision_id, request, request.next_status, NOW)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _token(role: str) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iss": "flowx-test", "aud": "flowx-api", "sub": "owner-1",
        "roles": [role], "iat": now - 1, "nbf": now - 1, "exp": now + 60,
    }).encode())
    signing_input = f"{header}.{claims}"
    signature = _b64(hmac.new(KEY, signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


def payload(*, decision="APPROVE", revision_target=None):
    value = {
        "request_id": str(uuid4()), "asset_id": str(ASSET_ID),
        "qa_report_id": str(REPORT_ID), "decision": decision,
        "reason": "Reviewed the final media and evidence.",
    }
    if revision_target is not None:
        value["revision_target"] = revision_target
    return value


class HumanReviewApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        StubReviewRepository.failure = None
        StubReviewRepository.calls = []
        verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        self.patch = patch("flowx_os.api.main.HumanReviewRepository", StubReviewRepository)
        self.patch.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(
                token_verifier=verifier, database_pool=StubPool(),
            )), base_url="http://testserver",
            headers={"Authorization": f"Bearer {_token('reviewer')}"},
        )
        await self.client.__aenter__()

    async def asyncTearDown(self):
        await self.client.__aexit__(None, None, None)
        self.patch.stop()

    async def test_reviewer_records_owner_scoped_approval(self):
        body = payload()
        response = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/human-reviews", json=body,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["next_status"], "READY")
        call = StubReviewRepository.calls[0]
        self.assertEqual(call[0], UUID(body["request_id"]))
        self.assertEqual((call[1], call[2]), (BRAND_ID, "owner-1"))
        self.assertEqual(call[3].content_id, CONTENT_ID)

    async def test_operator_cannot_submit_human_decision(self):
        verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(
                token_verifier=verifier, database_pool=StubPool(),
            )), base_url="http://testserver",
            headers={"Authorization": f"Bearer {_token('operator')}"},
        ) as client:
            response = await client.post(
                f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/human-reviews",
                json=payload(),
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(StubReviewRepository.calls, [])

    async def test_safe_error_mapping_conceals_storage_details(self):
        cases = [
            (OwnedContentNotFound("foreign"), 404, "content_not_found"),
            (HumanReviewConflict("private conflict"), 409, "human_review_conflict"),
            (HumanReviewNotAllowed("private evidence"), 409, "human_review_not_allowed"),
            (RepositoryUnavailable("private database"), 503, "database_unavailable"),
        ]
        for failure, status, detail in cases:
            StubReviewRepository.failure = failure
            response = await self.client.post(
                f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/human-reviews",
                json=payload(),
            )
            self.assertEqual((response.status_code, response.json()), (status, {"detail": detail}))
            self.assertNotIn("private", response.text)

    async def test_changes_required_needs_explicit_target_and_safe_reason(self):
        missing = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/human-reviews",
            json=payload(decision="CHANGES_REQUIRED"),
        )
        secret = payload(decision="REJECT")
        secret["reason"] = "token=private-value"
        unsafe = await self.client.post(
            f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/human-reviews", json=secret,
        )
        self.assertEqual((missing.status_code, unsafe.status_code), (422, 422))
        self.assertNotIn("private-value", unsafe.text)


if __name__ == "__main__":
    unittest.main()
