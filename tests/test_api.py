import unittest
import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.auth.tokens import TokenVerifier


class ApiShellTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        transport = httpx.ASGITransport(app=create_app())
        self.client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_root_describes_service_without_claiming_integrations(self) -> None:
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "service": "FLOW AI Content OS",
                "api_version": "0.1.0",
                "stage": "application-shell",
            },
        )

    async def test_health_route_reports_process_liveness_only(self) -> None:
        response = await self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "alive", "scope": "process-only"})

    async def test_readiness_is_not_ready_when_dependencies_are_unconfigured(self) -> None:
        response = await self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"status": "not_ready", "checks": {"dependencies": {"status": "not_configured"}}},
        )

    async def test_readiness_reports_configured_probe_results(self) -> None:
        ready_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app({"database": lambda: True, "flow_mcp": lambda: False})
            ),
            base_url="http://testserver",
        )
        async with ready_client:
            response = await ready_client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "status": "not_ready",
                "checks": {
                    "database": {"status": "ready"},
                    "flow_mcp": {"status": "unavailable"},
                },
            },
        )

    async def test_readiness_returns_ok_when_all_configured_probes_pass(self) -> None:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app({"database": lambda: True})),
            base_url="http://testserver",
        )
        async with client:
            response = await client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ready", "checks": {"database": {"status": "ready"}}},
        )

    async def test_readiness_suppresses_probe_exceptions(self) -> None:
        def failed_probe() -> bool:
            raise RuntimeError("private connection information")

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app({"database": failed_probe})),
            base_url="http://testserver",
        )
        async with client:
            response = await client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)

    async def test_openapi_exposes_service_auth_and_content_routes(self) -> None:
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()["paths"]),
            {
                "/", "/healthz", "/readyz", "/api/v1/me", "/api/v1/admin/access-check", "/api/v1/admin/metrics",
                "/api/v1/brands", "/api/v1/brands/{brand_id}/content",
                "/api/v1/flow-accounts",
                "/api/v1/flow-accounts/{account_id}/pause",
                "/api/v1/flow-accounts/{account_id}/credit-reservations",
                "/api/v1/flow-accounts/{account_id}/credit-reconciliations",
                "/api/v1/flow-accounts/{account_id}/credit-entries",
                "/api/v1/flow-accounts/{account_id}/credit-alarms",
                "/api/v1/flow-accounts/{account_id}/credit-reservations/{request_id}/unknown-spend",
                "/api/v1/flow-accounts/{account_id}/credit-alarms",
                "/api/v1/flow-accounts/{account_id}/credit-reservations/{request_id}/unknown-spend",
                "/api/v1/brands/{brand_id}/content/{content_id}/transition",
                "/api/v1/brands/{brand_id}/content/{content_id}/storyboard",
                "/api/v1/brands/{brand_id}/content/{content_id}/storyboard/versions",
                "/api/v1/brands/{brand_id}/content/{content_id}/assets",
            },
        )

    async def test_storyboard_route_persists_owner_scoped_version_and_returns_snapshot(self) -> None:
        key = b"test-key-that-is-long-enough-for-hmac"
        verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        now = int(time.time())
        content_id = "64135a38-e28b-4e22-bebf-c1906761b681"
        brand_id = "b6bb37b4-a27f-4de4-9277-45a6449aef01"
        storyboard = {
            "title": "A falling apple",
            "scenes": [
                {"scene_number": 1, "start_ms": 0, "end_ms": 4_000, "beat": "Setup", "visual_prompt": "Tree"},
                {"scene_number": 2, "start_ms": 4_000, "end_ms": 8_000, "beat": "Turn", "visual_prompt": "Apple"},
            ],
        }
        snapshot = {
            "title": "A falling apple",
            "scenes": [
                {"scene_number": 1, "start_ms": 0, "end_ms": 4_000, "beat": "Setup", "narration_text": "", "visual_prompt": "Tree", "prompt_version": 1},
                {"scene_number": 2, "start_ms": 4_000, "end_ms": 8_000, "beat": "Turn", "narration_text": "", "visual_prompt": "Apple", "prompt_version": 1},
            ],
        }
        pool = _FakePool([
            _FakeCursor((0, 8, "SCRIPT_READY")),
            _FakeCursor((UUID(content_id), 1, "A falling apple", 8_000, snapshot, datetime.now(timezone.utc))),
            _FakeCursor(),
            _FakeCursor(),
            _FakeCursor((1, "STORYBOARD_READY")),
        ])
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier, database_pool=pool)),
            base_url="http://testserver",
        )
        async with client:
            response = await client.put(
                f"/api/v1/brands/{brand_id}/content/{content_id}/storyboard",
                headers={"Authorization": f"Bearer {_signed_token(key, roles=['operator'], now=now)}"},
                json={"expected_version": 0, "storyboard": storyboard},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 1)
        self.assertEqual(response.json()["storyboard"], snapshot)
        self.assertEqual(pool.connection_value.queries[0][1], (UUID(content_id), UUID(brand_id), "operator-1"))

    async def test_storyboard_route_reports_conflicts_and_unconfigured_database(self) -> None:
        key = b"test-key-that-is-long-enough-for-hmac"
        verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        now = int(time.time())
        content_id = "64135a38-e28b-4e22-bebf-c1906761b681"
        brand_id = "b6bb37b4-a27f-4de4-9277-45a6449aef01"
        headers = {"Authorization": f"Bearer {_signed_token(key, roles=['operator'], now=now)}"}
        request_body = {"expected_version": 0, "storyboard": {"title": "A", "scenes": [
            {"scene_number": 1, "start_ms": 0, "end_ms": 8_000, "beat": "Setup", "visual_prompt": "Tree"},
        ]}}
        pool = _FakePool([_FakeCursor((1, 8, "STORYBOARD_READY"))])
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier, database_pool=pool)),
            base_url="http://testserver",
        )
        async with client:
            conflict = await client.put(
                f"/api/v1/brands/{brand_id}/content/{content_id}/storyboard",
                headers=headers, json=request_body,
            )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"], {
            "code": "storyboard_version_conflict", "current_version": 1,
        })

        unconfigured = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver",
        )
        async with unconfigured:
            response = await unconfigured.put(
                f"/api/v1/brands/{brand_id}/content/{content_id}/storyboard",
                headers=headers, json=request_body,
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "database_not_configured")

    async def test_asset_listing_returns_owner_scoped_metadata_only(self) -> None:
        key = b"test-key-that-is-long-enough-for-hmac"
        verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        now = int(time.time())
        content_id = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
        brand_id = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
        asset_id = UUID("f2c13904-9b62-4a5d-9459-617b87946132")
        created_at = datetime.now(timezone.utc)
        pool = _FakePool([
            _FakeCursor((1,)),
            _FakeCursor(many=[(
                asset_id, content_id, None, "THUMBNAIL",
                f"managed://assets/{asset_id.hex}/payload", "a" * 64,
                "image/png", 24, {"width": 1080}, None, created_at,
            )]),
        ])
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier, database_pool=pool)),
            base_url="http://testserver",
        )
        async with client:
            response = await client.get(
                f"/api/v1/brands/{brand_id}/content/{content_id}/assets",
                headers={"Authorization": f"Bearer {_signed_token(key, roles=['reviewer'], now=now)}"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["asset_id"], str(asset_id))
        self.assertEqual(response.json()[0]["sha256_hex"], "a" * 64)
        self.assertNotIn("storage_path", response.json()[0])

    async def test_authenticated_identity_route_fails_closed_when_not_configured(self) -> None:
        response = await self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "authentication_not_configured")

    async def test_configured_auth_requires_bearer_and_hides_invalid_token(self) -> None:
        verifier = TokenVerifier(b"test-key-that-is-long-enough-for-hmac", issuer="flowx-test", audience="flowx-api")
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver",
        )
        async with client:
            missing = await client.get("/api/v1/me")
            invalid = await client.get("/api/v1/me", headers={"Authorization": "Bearer private-token"})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("private-token", invalid.text)

    async def test_authenticated_identity_and_role_gate(self) -> None:
        key = b"test-key-that-is-long-enough-for-hmac"
        verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        token = _signed_token(key, roles=["reviewer"], now=int(time.time()))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            who = await client.get("/api/v1/me")
            admin = await client.get("/api/v1/admin/access-check")
        self.assertEqual(who.status_code, 200)
        self.assertEqual(who.json(), {"subject": "operator-1", "roles": ["reviewer"]})
        self.assertEqual(admin.status_code, 403)

    async def test_admin_role_can_pass_role_gate(self) -> None:
        key = b"test-key-that-is-long-enough-for-hmac"
        verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        token = _signed_token(key, roles=["admin"], now=int(time.time()))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.get("/api/v1/admin/access-check")
        self.assertEqual(response.status_code, 200)


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


class _FakeCursor:
    def __init__(self, one=None, many=None):
        self.one = one
        self.many = list(many or [])

    async def fetchone(self):
        return self.one

    async def fetchall(self):
        return self.many


class _FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        return self.responses.pop(0)


class _FakePool:
    def __init__(self, responses):
        self.connection_value = _FakeConnection(responses)

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


if __name__ == "__main__":
    unittest.main()
