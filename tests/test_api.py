import unittest

import httpx

from flowx_os.api.main import create_app


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

    async def test_openapi_exposes_only_shell_routes(self) -> None:
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()["paths"]), {"/", "/healthz", "/readyz"})


if __name__ == "__main__":
    unittest.main()
