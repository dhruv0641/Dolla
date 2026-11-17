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

    async def test_openapi_exposes_only_shell_routes(self) -> None:
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()["paths"]), {"/", "/healthz"})


if __name__ == "__main__":
    unittest.main()
