"""FastAPI application shell; no external services are assumed ready."""

from fastapi import FastAPI
from pydantic import BaseModel


class ServiceDescriptor(BaseModel):
    service: str
    api_version: str
    stage: str


class Liveness(BaseModel):
    status: str
    scope: str


def create_app() -> FastAPI:
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

    return app


app = create_app()
