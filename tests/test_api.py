import unittest
import base64
import hashlib
import hmac
import json
import time

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
                "/api/v1/brands/{brand_id}/content/{content_id}/transition",
            },
        )

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


if __name__ == "__main__":
    unittest.main()
