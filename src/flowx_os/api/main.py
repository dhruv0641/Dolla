"""FastAPI application shell; no external services are assumed ready."""

from collections.abc import Callable

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from flowx_os.auth.dependencies import current_principal, require_roles
from flowx_os.auth.tokens import Principal, Role, TokenVerifier
from flowx_os.db.content import (
    BrandRecord,
    ContentRecord,
    ContentRepository,
    InvalidContentTransition,
    OwnedBrandNotFound,
    OwnedContentNotFound,
    RepositoryUnavailable,
)
from flowx_os.db.transaction import ConnectionPool
from flowx_os.domain.content_state import ContentStatus


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


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=100)
    niche: str = Field(default="", max_length=500)
    audience: str = Field(default="", max_length=1000)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class BrandResponse(BaseModel):
    id: UUID
    name: str
    timezone: str
    niche: str
    audience: str
    created_at: datetime
    updated_at: datetime


class ContentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    idea_text: str = Field(min_length=1, max_length=20_000)
    topic: str | None = Field(default=None, max_length=300)
    audience_segment: str | None = Field(default=None, max_length=300)
    language: str = Field(default="en-IN", min_length=2, max_length=20)
    target_duration_seconds: int = Field(default=32, ge=4, le=180)
    priority: int = Field(default=3, ge=1, le=5)

    @field_validator("title", "idea_text")
    @classmethod
    def non_blank_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ContentResponse(BaseModel):
    id: UUID
    brand_id: UUID
    title: str
    idea_text: str
    topic: str | None
    audience_segment: str | None
    language: str
    target_duration_seconds: int
    priority: int
    status: ContentStatus
    created_at: datetime


class ContentTransition(BaseModel):
    target_status: ContentStatus


def create_app(
    readiness_checks: dict[str, Callable[[], bool]] | None = None,
    token_verifier: TokenVerifier | None = None,
    database_pool: ConnectionPool | None = None,
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
    app.state.token_verifier = token_verifier
    app.state.database_pool = database_pool

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

    @app.get("/api/v1/me", tags=["authentication"])
    async def who_am_i(principal: Principal = Depends(current_principal)) -> dict[str, object]:
        return {"subject": principal.subject, "roles": sorted(role.value for role in principal.roles)}

    @app.get("/api/v1/admin/access-check", tags=["authentication"])
    async def admin_access_check(
        principal: Principal = Depends(require_roles(Role.ADMIN)),
    ) -> dict[str, bool]:
        return {"allowed": True}

    @app.post("/api/v1/brands", response_model=BrandResponse, status_code=201, tags=["content"])
    async def create_brand(
        body: BrandCreate,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> BrandResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            record: BrandRecord = await ContentRepository(database_pool).create_brand(
                owner_user_id=principal.subject,
                name=body.name.strip(),
                timezone_name=body.timezone,
                niche=body.niche,
                audience=body.audience,
            )
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return BrandResponse(
            id=record.id, name=record.name, timezone=record.timezone, niche=record.niche,
            audience=record.audience, created_at=record.created_at, updated_at=record.updated_at,
        )

    @app.get("/api/v1/brands", response_model=list[BrandResponse], tags=["content"])
    async def list_brands(
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[BrandResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            records = await ContentRepository(database_pool).list_brands(owner_user_id=principal.subject)
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [BrandResponse(
            id=row.id, name=row.name, timezone=row.timezone, niche=row.niche, audience=row.audience,
            created_at=row.created_at, updated_at=row.updated_at,
        ) for row in records]

    @app.post(
        "/api/v1/brands/{brand_id}/content",
        response_model=ContentResponse,
        status_code=201,
        tags=["content"],
    )
    async def create_content(
        brand_id: UUID,
        body: ContentCreate,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> ContentResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            row: ContentRecord = await ContentRepository(database_pool).create_content(
                brand_id=brand_id,
                owner_user_id=principal.subject,
                title=body.title.strip(),
                idea_text=body.idea_text.strip(),
                topic=body.topic,
                audience_segment=body.audience_segment,
                language=body.language,
                target_duration_seconds=body.target_duration_seconds,
                priority=body.priority,
            )
        except OwnedBrandNotFound as exc:
            raise HTTPException(status_code=404, detail="brand_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return ContentResponse(
            id=row.id, brand_id=row.brand_id, title=row.title, idea_text=row.idea_text,
            topic=row.topic, audience_segment=row.audience_segment, language=row.language,
            target_duration_seconds=row.target_duration_seconds, priority=row.priority,
            status=row.status, created_at=row.created_at,
        )

    @app.get(
        "/api/v1/brands/{brand_id}/content",
        response_model=list[ContentResponse],
        tags=["content"],
    )
    async def list_content(
        brand_id: UUID,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[ContentResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            records = await ContentRepository(database_pool).list_content(
                brand_id=brand_id, owner_user_id=principal.subject
            )
        except OwnedBrandNotFound as exc:
            raise HTTPException(status_code=404, detail="brand_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [ContentResponse(
            id=row.id, brand_id=row.brand_id, title=row.title, idea_text=row.idea_text,
            topic=row.topic, audience_segment=row.audience_segment, language=row.language,
            target_duration_seconds=row.target_duration_seconds, priority=row.priority,
            status=row.status, created_at=row.created_at,
        ) for row in records]

    @app.post(
        "/api/v1/brands/{brand_id}/content/{content_id}/transition",
        response_model=ContentResponse,
        tags=["content"],
    )
    async def transition_content(
        brand_id: UUID,
        content_id: UUID,
        body: ContentTransition,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> ContentResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            row = await ContentRepository(database_pool).transition_content(
                brand_id=brand_id,
                content_id=content_id,
                owner_user_id=principal.subject,
                target_status=body.target_status,
            )
        except (OwnedBrandNotFound, OwnedContentNotFound) as exc:
            raise HTTPException(status_code=404, detail="content_not_found") from exc
        except InvalidContentTransition as exc:
            raise HTTPException(status_code=409, detail="invalid_content_transition") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return ContentResponse(
            id=row.id, brand_id=row.brand_id, title=row.title, idea_text=row.idea_text,
            topic=row.topic, audience_segment=row.audience_segment, language=row.language,
            target_duration_seconds=row.target_duration_seconds, priority=row.priority,
            status=row.typed_status, created_at=row.created_at,
        )

    return app


app = create_app()
