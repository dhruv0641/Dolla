"""FastAPI application shell; no external services are assumed ready."""

from collections.abc import Callable

from fastapi import FastAPI, Response
from pydantic import BaseModel


class ServiceDescriptor(BaseModel):
    service: str
    api_version: str
    stage: str


class Liveness(BaseModel):
    status: str
    scope: str


class DependencyState(BaseModel):
    status: str


class Readiness(BaseModel):
    status: str
    checks: dict[str, DependencyState]


def create_app(
    readiness_checks: dict[str, Callable[[], bool]] | None = None,
) -> FastAPI:
    """Create the API and accept simple, local dependency readiness probes.

    A probe should be fast, side-effect free, and return only whether its
    dependency can accept work. Probe exceptions are reported as unavailable;
    exception text and credentials are never returned to callers.
    """
    configured_checks = readiness_checks or {}
    app = FastAPI(
        title="FLOW AI Content OS API",
        version="0.1.0",
        description="Backend shell for FLOW AI Content OS. Integration readiness is reported separately.",
    )

    @app.get("/", response_model=ServiceDescriptor, tags=["service"])
    async def describe_service() -> ServiceDescriptor:
        return ServiceDescriptor(
            service="FLOW AI Content OS",
            api_version="0.1.0",
            stage="application-shell",
        )

    @app.get("/healthz", response_model=Liveness, tags=["service"])
    async def liveness() -> Liveness:
        """Report only that this process can answer HTTP; this is not readiness."""
        return Liveness(status="alive", scope="process-only")

    @app.get("/readyz", response_model=Readiness, tags=["service"])
    async def readiness(response: Response) -> Readiness:
        """Report configured dependency checks without claiming absent systems."""
        checks: dict[str, DependencyState] = {}
        for name, probe in sorted(configured_checks.items()):
            try:
                state = "ready" if probe() else "unavailable"
            except Exception:
                state = "unavailable"
            checks[name] = DependencyState(status=state)
        if not checks:
            checks["dependencies"] = DependencyState(status="not_configured")
        ready = bool(configured_checks) and all(
            item.status == "ready" for item in checks.values()
        )
        response.status_code = 200 if ready else 503
        return Readiness(status="ready" if ready else "not_ready", checks=checks)

    return app


app = create_app()
