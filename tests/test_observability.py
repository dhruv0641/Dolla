import base64
import hashlib
import hmac
import json
import time
import unittest
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.auth.tokens import TokenVerifier


def _segment(value: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def _signed_token(key: bytes, roles: list[str]) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    claims = _segment({
        "sub": "admin-observability-test",
        "roles": roles,
        "iss": "flowx-test",
        "aud": "flowx-api",
        "exp": int(time.time()) + 60,
    })
    signature = hmac.new(key, f"{header}.{claims}".encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{header}.{claims}.{encoded_signature}"


class RequestObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = create_app()

        async def fail_with_sensitive_message(marker: str) -> None:
            raise RuntimeError(f"provider credential {marker}")

        self.app.add_api_route("/__test_failure/{marker}", fail_with_sensitive_message, methods=["GET"])
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_logs_route_template_and_request_id_without_query_or_secret(self) -> None:
        with self.assertLogs("flowx.api.request", level="INFO") as captured:
            response = await self.client.get(
                "/healthz?access_token=hidden-query-secret",
                headers={"Authorization": "Bearer hidden-header-secret"},
            )

        self.assertEqual(response.status_code, 200)
        request_id = response.headers["X-Request-ID"]
        UUID(request_id)
        event = json.loads(captured.records[-1].getMessage())
        self.assertEqual(event["event"], "http.request")
        self.assertEqual(event["request_id"], request_id)
        self.assertEqual(event["route"], "/healthz")
        self.assertEqual(event["status_code"], 200)
        self.assertNotIn("hidden-query-secret", captured.output[0])
        self.assertNotIn("hidden-header-secret", captured.output[0])

    async def test_unhandled_error_returns_safe_id_and_does_not_log_exception_text(self) -> None:
        with self.assertLogs("flowx.api.request", level="ERROR") as captured:
            response = await self.client.get("/__test_failure/private-marker")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "internal_server_error")
        self.assertEqual(response.json()["request_id"], response.headers["X-Request-ID"])
        self.assertNotIn("provider credential", captured.output[0])
        self.assertNotIn("private-marker", captured.output[0])
        event = json.loads(captured.records[-1].getMessage())
        self.assertEqual(event["route"], "/__test_failure/{marker}")
        self.assertEqual(event["exception_type"], "RuntimeError")

    async def test_metrics_endpoint_is_admin_only_and_uses_bounded_route_labels(self) -> None:
        await self.client.get("/healthz")
        unauthenticated = await self.client.get("/api/v1/admin/metrics")
        self.assertEqual(unauthenticated.status_code, 503)

        key = b"observability-test-key-long-enough-for-hmac"
        verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
        reviewer_token = _signed_token(key, ["reviewer"])
        reviewer_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        async with reviewer_client:
            forbidden = await reviewer_client.get("/api/v1/admin/metrics")
        self.assertEqual(forbidden.status_code, 403)

        admin_token = _signed_token(key, ["admin"])
        admin_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        async with admin_client:
            await admin_client.get("/healthz")
            response = await admin_client.get("/api/v1/admin/metrics")

        self.assertEqual(response.status_code, 200)
        metrics = response.json()
        self.assertEqual(metrics["scope"], "process_lifetime")
        health = next(item for item in metrics["requests"] if item["route"] == "/healthz")
        self.assertEqual(health["count"], 1)
        self.assertEqual(health["status_class"], "2xx")
        self.assertGreater(health["duration_ms_buckets"]["5000"], 0)
        self.assertEqual(health["duration_ms_inf"], health["count"])


if __name__ == "__main__":
    unittest.main()
