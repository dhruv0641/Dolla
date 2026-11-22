"""FastAPI application shell; no external services are assumed ready."""

from collections.abc import Callable

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from time import perf_counter
from uuid import UUID
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from flowx_os.auth.dependencies import current_principal, require_roles
from flowx_os.auth.tokens import Principal, Role, TokenVerifier
from flowx_os.credits.reservations import (
    CreditApprovalRequired,
    CreditApprovalUnavailable,
    CreditQuoteUnavailable,
    CreditReservationRecord,
    CreditReservationService,
    InvalidCreditQuote,
)
from flowx_os.credits.ledger import (
    CreditLedgerEntry,
    CreditObservationUnavailable,
    CreditReconciliationConflict,
    CreditReconciliationService,
    InvalidCreditObservation,
)
from flowx_os.credits.alarms import (
    CreditRiskAlarmConflict,
    CreditRiskAlarmRecord,
    CreditRiskAlarmState,
    CreditRiskAlarmService,
    CreditRiskReservationUnavailable,
    UnknownSpendReason,
)
from flowx_os.db.content import (
    BrandRecord,
    ContentRecord,
    ContentRepository,
    InvalidContentTransition,
    OwnedBrandNotFound,
    OwnedContentNotFound,
    RepositoryUnavailable,
)
from flowx_os.db.assets import AssetRepository, AssetRecord, InvalidAssetLineage
from flowx_os.db.asset_catalog import AssetCatalogRepository, AssetRetentionBlocked
from flowx_os.db.storyboards import (
    InvalidStoryboardTimeline,
    StoryboardRepository,
    StoryboardVersionConflict,
    StoryboardVersionRecord,
)
from flowx_os.db.transaction import ConnectionPool
from flowx_os.db.flow_accounts import (
    FlowAccountAliasConflict,
    FlowAccountRecord,
    FlowAccountRepository,
    OwnedFlowAccountNotFound,
)
from flowx_os.db.credit_reservations import (
    CreditAccountIneligible,
    CreditBalanceUnknown,
    CreditLimitExceeded,
    CreditReservationConflict,
)
from flowx_os.db.credit_ledger import FlowCreditLedgerRepository
from flowx_os.db.credit_alarms import FlowCreditRiskAlarmRepository
from flowx_os.domain.content_state import ContentStatus
from flowx_os.domain.assets import AssetKind
from flowx_os.domain.storyboard import StoryboardTimeline
from flowx_os.api.observability import RequestMetrics
from flowx_os.assets.audio_preview import AudioPreviewError, AudioPreviewService


_request_logger = logging.getLogger("flowx.api.request")
_request_logger.setLevel(logging.INFO)


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


class StoryboardSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=0, le=100_000)
    storyboard: StoryboardTimeline


class StoryboardVersionResponse(BaseModel):
    content_id: UUID
    version: int
    title: str
    total_duration_ms: int
    storyboard: StoryboardTimeline
    created_at: datetime


class AssetResponse(BaseModel):
    asset_id: UUID
    content_id: UUID
    scene_id: UUID | None
    source_job_id: UUID | None
    kind: AssetKind
    storage_uri: str
    sha256_hex: str
    mime_type: str
    size_bytes: int
    media_metadata: dict[str, object]
    created_at: datetime


class AudioAssetResponse(BaseModel):
    asset_id: UUID
    content_id: UUID
    scene_id: UUID | None
    kind: AssetKind
    mime_type: str
    size_bytes: int
    duration_ms: int | None
    timeline_start_ms: int | None
    created_at: datetime


class AudioRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_before: datetime
    reason: str = Field(min_length=3, max_length=100)

    @field_validator("created_before")
    @classmethod
    def cutoff_is_aware_and_past(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value >= datetime.now(timezone.utc):
            raise ValueError("an explicit past retention cutoff is required")
        return value

    @field_validator("reason")
    @classmethod
    def reason_is_safe(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3 or any(ord(character) < 32 for character in value):
            raise ValueError("retention reason is invalid")
        return value


class FlowAccountCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=64)
    credentials_ref: SecretStr
    mcp_adapter: str = Field(default="google_flow_via_user_authorized_mcp", min_length=1, max_length=100)

    @field_validator("alias")
    @classmethod
    def valid_alias(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 64:
            raise ValueError("account alias must contain 1 to 64 characters")
        if not value[0].isalnum() or any(not (char.isalnum() or char in " ._-") for char in value):
            raise ValueError("account alias contains unsupported characters")
        return value

    @field_validator("credentials_ref")
    @classmethod
    def secret_reference_only(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+", value.get_secret_value()):
            raise ValueError("credentials_ref must be a secret reference; raw credentials are not accepted")
        return value

    @field_validator("mcp_adapter")
    @classmethod
    def known_adapter(cls, value: str) -> str:
        value = value.strip()
        if value != "google_flow_via_user_authorized_mcp":
            raise ValueError("unsupported Flow adapter identifier")
        return value


class FlowAccountResponse(BaseModel):
    id: UUID
    alias: str
    mcp_adapter: str
    plan_name: str | None
    monthly_allowance_estimate: int | None
    daily_allowance_estimate: int | None
    observed_monthly_available: int | None
    observed_daily_available: int | None
    monthly_cycle_starts_at: datetime | None
    next_daily_reset_at: datetime | None
    last_reconciled_at: datetime | None
    session_health: str
    paused: bool
    compliance_approved: bool
    max_inflight: int
    created_at: datetime


class CreditReservationCreate(BaseModel):
    request_id: UUID
    model_name: str = Field(min_length=1, max_length=100)
    duration_seconds: int = Field(ge=4, le=180)
    approval_ref: SecretStr

    @field_validator("model_name")
    @classmethod
    def non_blank_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model name must not be blank")
        return value

    @field_validator("approval_ref")
    @classmethod
    def non_blank_approval_ref(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("approval reference must not be blank")
        return value


class CreditReservationResponse(BaseModel):
    id: UUID
    flow_account_id: UUID
    request_id: UUID
    model_name: str
    duration_seconds: int
    quote_ref: str
    quoted_credits: int
    quote_source: str
    quoted_at: datetime
    quote_expires_at: datetime
    state: str
    created_at: datetime


class CreditLedgerEntryResponse(BaseModel):
    id: UUID
    flow_account_id: UUID
    generation_job_id: UUID | None
    wallet_type: str
    action: str
    credit_delta: int
    source: str
    details: dict[str, object]
    created_at: datetime


class CreditReconciliationRequest(BaseModel):
    request_id: UUID


class UnknownSpendReport(BaseModel):
    reason: UnknownSpendReason


class CreditRiskAlarmResponse(BaseModel):
    id: UUID
    flow_account_id: UUID
    request_id: UUID
    alarm_type: str
    reason_code: UnknownSpendReason
    state: CreditRiskAlarmState
    created_at: datetime


def _flow_account_response(record: FlowAccountRecord) -> FlowAccountResponse:
    return FlowAccountResponse(
        id=record.id,
        alias=record.alias,
        mcp_adapter=record.mcp_adapter,
        plan_name=record.plan_name,
        monthly_allowance_estimate=record.monthly_allowance_estimate,
        daily_allowance_estimate=record.daily_allowance_estimate,
        observed_monthly_available=record.observed_monthly_available,
        observed_daily_available=record.observed_daily_available,
        monthly_cycle_starts_at=record.monthly_cycle_starts_at,
        next_daily_reset_at=record.next_daily_reset_at,
        last_reconciled_at=record.last_reconciled_at,
        session_health=record.session_health,
        paused=record.paused,
        compliance_approved=record.compliance_approved,
        max_inflight=record.max_inflight,
        created_at=record.created_at,
    )


def _credit_reservation_response(record: CreditReservationRecord) -> CreditReservationResponse:
    return CreditReservationResponse(
        id=record.id,
        flow_account_id=record.flow_account_id,
        request_id=record.request_id,
        model_name=record.model_name,
        duration_seconds=record.duration_seconds,
        quote_ref=record.quote_ref,
        quoted_credits=record.quoted_credits,
        quote_source=record.quote_source.value,
        quoted_at=record.quoted_at,
        quote_expires_at=record.quote_expires_at,
        state=record.state.value,
        created_at=record.created_at,
    )


def _credit_ledger_entry_response(record: CreditLedgerEntry) -> CreditLedgerEntryResponse:
    allowed_detail_keys = {
        "available_after", "available_before", "observation_fingerprint",
        "observed_at", "baseline", "delta_semantics",
        "previous_daily_reset_at", "next_daily_reset_at",
        "previous_monthly_cycle_starts_at", "monthly_cycle_starts_at",
    }
    details = {
        key: value
        for key, value in record.details.items()
        if key in allowed_detail_keys
        and (
            value is None
            or isinstance(value, (int, bool, str))
        )
        and (not isinstance(value, str) or len(value) <= 256)
    }
    return CreditLedgerEntryResponse(
        id=record.id,
        flow_account_id=record.flow_account_id,
        generation_job_id=record.generation_job_id,
        wallet_type=record.wallet_type,
        action=record.action,
        credit_delta=record.credit_delta,
        source=record.source,
        details=details,
        created_at=record.created_at,
    )


def _credit_risk_alarm_response(record: CreditRiskAlarmRecord) -> CreditRiskAlarmResponse:
    return CreditRiskAlarmResponse(
        id=record.id,
        flow_account_id=record.flow_account_id,
        request_id=record.request_id,
        alarm_type=record.alarm_type,
        reason_code=record.reason_code,
        state=record.state,
        created_at=record.created_at,
    )


def create_app(
    readiness_checks: dict[str, Callable[[], bool]] | None = None,
    token_verifier: TokenVerifier | None = None,
    database_pool: ConnectionPool | None = None,
    credit_reservation_service: CreditReservationService | None = None,
    credit_reconciliation_service: CreditReconciliationService | None = None,
    credit_risk_alarm_service: CreditRiskAlarmService | None = None,
    storage_root: Path | None = None,
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

    @app.exception_handler(RequestValidationError)
    async def redact_validation_inputs(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Return field-level errors without echoing submitted credentials or payload values."""
        details = [
            {
                "type": error.get("type", "value_error"),
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", "invalid request field"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

    app.state.token_verifier = token_verifier
    app.state.database_pool = database_pool
    app.state.storage_root = storage_root
    configured_credit_ledger_service = credit_reconciliation_service
    if configured_credit_ledger_service is None and database_pool is not None:
        configured_credit_ledger_service = CreditReconciliationService(
            FlowCreditLedgerRepository(database_pool), None
        )
    configured_credit_risk_alarm_service = credit_risk_alarm_service
    if configured_credit_risk_alarm_service is None and database_pool is not None:
        configured_credit_risk_alarm_service = CreditRiskAlarmService(
            FlowCreditRiskAlarmRepository(database_pool)
        )
    request_metrics = RequestMetrics()
    app.state.request_metrics = request_metrics

    @app.middleware("http")
    async def observe_request(request: Request, call_next: Callable) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        status_code = 500
        error_type: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            error_type = type(exc).__name__
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal_server_error", "request_id": request_id},
            )
        duration_ms = (perf_counter() - started) * 1000
        route = request.scope.get("route")
        route_template = getattr(route, "path", "unmatched")
        if not isinstance(route_template, str) or not route_template.startswith("/"):
            route_template = "unmatched"
        request_metrics.observe(
            method=request.method,
            route=route_template,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        event: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "error" if status_code >= 500 else "info",
            "event": "http.request",
            "request_id": request_id,
            "method": request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} else "OTHER",
            "route": route_template,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 3),
        }
        if error_type is not None:
            event["exception_type"] = error_type
        _request_logger.log(logging.ERROR if status_code >= 500 else logging.INFO, json.dumps(event, separators=(",", ":")))
        response.headers["X-Request-ID"] = request_id
        return response

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

    @app.get("/api/v1/admin/metrics", tags=["operations"])
    async def process_metrics(
        principal: Principal = Depends(require_roles(Role.ADMIN)),
    ) -> dict[str, object]:
        """Return low-cardinality, process-local counters to administrators only."""
        return request_metrics.snapshot()

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
        "/api/v1/flow-accounts",
        response_model=FlowAccountResponse,
        status_code=201,
        tags=["flow-accounts"],
    )
    async def register_flow_account(
        body: FlowAccountCreate,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> FlowAccountResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            record = await FlowAccountRepository(database_pool).register(
                owner_user_id=principal.subject,
                alias=body.alias,
                credentials_ref=body.credentials_ref.get_secret_value(),
                mcp_adapter=body.mcp_adapter,
            )
        except FlowAccountAliasConflict as exc:
            raise HTTPException(status_code=409, detail="flow_account_alias_unavailable") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return _flow_account_response(record)

    @app.get(
        "/api/v1/flow-accounts",
        response_model=list[FlowAccountResponse],
        tags=["flow-accounts"],
    )
    async def list_flow_accounts(
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> list[FlowAccountResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            records = await FlowAccountRepository(database_pool).list_for_owner(owner_user_id=principal.subject)
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [_flow_account_response(record) for record in records]

    @app.post(
        "/api/v1/flow-accounts/{account_id}/pause",
        response_model=FlowAccountResponse,
        tags=["flow-accounts"],
    )
    async def pause_flow_account(
        account_id: UUID,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> FlowAccountResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            record = await FlowAccountRepository(database_pool).pause(
                account_id=account_id, owner_user_id=principal.subject
            )
        except OwnedFlowAccountNotFound as exc:
            raise HTTPException(status_code=404, detail="flow_account_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return _flow_account_response(record)

    @app.post(
        "/api/v1/flow-accounts/{account_id}/credit-reservations",
        response_model=CreditReservationResponse,
        tags=["flow-accounts"],
    )
    async def reserve_flow_credits(
        account_id: UUID,
        body: CreditReservationCreate,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> CreditReservationResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        if credit_reservation_service is None:
            raise HTTPException(status_code=503, detail="credit_quote_unavailable")
        try:
            record = await credit_reservation_service.reserve(
                account_id=account_id,
                owner_user_id=principal.subject,
                request_id=body.request_id,
                model_name=body.model_name,
                duration_seconds=body.duration_seconds,
                approval_ref=body.approval_ref.get_secret_value(),
            )
        except OwnedFlowAccountNotFound as exc:
            raise HTTPException(status_code=404, detail="flow_account_not_found") from exc
        except CreditApprovalRequired as exc:
            raise HTTPException(status_code=403, detail="spend_approval_required") from exc
        except (CreditQuoteUnavailable, CreditApprovalUnavailable, InvalidCreditQuote) as exc:
            raise HTTPException(status_code=503, detail="credit_quote_unavailable") from exc
        except CreditAccountIneligible as exc:
            raise HTTPException(status_code=409, detail="flow_account_not_eligible") from exc
        except CreditBalanceUnknown as exc:
            raise HTTPException(status_code=409, detail="credit_balance_unknown") from exc
        except CreditLimitExceeded as exc:
            raise HTTPException(status_code=409, detail="credit_limit_exceeded") from exc
        except CreditReservationConflict as exc:
            raise HTTPException(status_code=409, detail="credit_reservation_conflict") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return _credit_reservation_response(record)

    @app.post(
        "/api/v1/flow-accounts/{account_id}/credit-reconciliations",
        response_model=list[CreditLedgerEntryResponse],
        tags=["flow-accounts"],
    )
    async def reconcile_flow_credits(
        account_id: UUID,
        body: CreditReconciliationRequest,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> list[CreditLedgerEntryResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        if configured_credit_ledger_service is None:
            raise HTTPException(status_code=503, detail="credit_observation_unavailable")
        try:
            entries = await configured_credit_ledger_service.reconcile(
                account_id=account_id,
                owner_user_id=principal.subject,
                request_id=body.request_id,
            )
        except OwnedFlowAccountNotFound as exc:
            raise HTTPException(status_code=404, detail="flow_account_not_found") from exc
        except CreditReconciliationConflict as exc:
            raise HTTPException(status_code=409, detail="credit_reconciliation_conflict") from exc
        except InvalidCreditObservation as exc:
            raise HTTPException(status_code=502, detail="credit_observation_invalid") from exc
        except CreditObservationUnavailable as exc:
            raise HTTPException(status_code=503, detail="credit_observation_unavailable") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [_credit_ledger_entry_response(entry) for entry in entries]

    @app.get(
        "/api/v1/flow-accounts/{account_id}/credit-entries",
        response_model=list[CreditLedgerEntryResponse],
        tags=["flow-accounts"],
    )
    async def list_flow_credit_entries(
        account_id: UUID,
        limit: int = 100,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[CreditLedgerEntryResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        if configured_credit_ledger_service is None:
            raise HTTPException(status_code=503, detail="credit_ledger_unavailable")
        try:
            entries = await configured_credit_ledger_service.list_entries(
                account_id=account_id, owner_user_id=principal.subject, limit=limit
            )
        except OwnedFlowAccountNotFound as exc:
            raise HTTPException(status_code=404, detail="flow_account_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_credit_ledger_page_size") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [_credit_ledger_entry_response(entry) for entry in entries]

    @app.post(
        "/api/v1/flow-accounts/{account_id}/credit-reservations/{request_id}/unknown-spend",
        response_model=CreditRiskAlarmResponse,
        tags=["flow-accounts"],
    )
    async def report_unknown_credit_spend(
        account_id: UUID,
        request_id: UUID,
        body: UnknownSpendReport,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> CreditRiskAlarmResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        if configured_credit_risk_alarm_service is None:
            raise HTTPException(status_code=503, detail="credit_risk_alarm_unavailable")
        try:
            alarm = await configured_credit_risk_alarm_service.report_unknown_spend(
                account_id=account_id,
                owner_user_id=principal.subject,
                request_id=request_id,
                reason=body.reason,
                actor=f"user:{principal.subject}",
            )
        except OwnedFlowAccountNotFound as exc:
            raise HTTPException(status_code=404, detail="flow_account_not_found") from exc
        except CreditRiskReservationUnavailable as exc:
            raise HTTPException(status_code=404, detail="credit_reservation_not_found") from exc
        except CreditRiskAlarmConflict as exc:
            raise HTTPException(status_code=409, detail="credit_risk_alarm_conflict") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return _credit_risk_alarm_response(alarm)

    @app.get(
        "/api/v1/flow-accounts/{account_id}/credit-alarms",
        response_model=list[CreditRiskAlarmResponse],
        tags=["flow-accounts"],
    )
    async def list_credit_risk_alarms(
        account_id: UUID,
        limit: int = 100,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[CreditRiskAlarmResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        if configured_credit_risk_alarm_service is None:
            raise HTTPException(status_code=503, detail="credit_risk_alarm_unavailable")
        try:
            alarms = await configured_credit_risk_alarm_service.list_open_alarms(
                account_id=account_id,
                owner_user_id=principal.subject,
                limit=limit,
            )
        except OwnedFlowAccountNotFound as exc:
            raise HTTPException(status_code=404, detail="flow_account_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_credit_alarm_page_size") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [_credit_risk_alarm_response(alarm) for alarm in alarms]

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

    @app.put(
        "/api/v1/brands/{brand_id}/content/{content_id}/storyboard",
        response_model=StoryboardVersionResponse,
        tags=["content"],
    )
    async def save_storyboard(
        brand_id: UUID,
        content_id: UUID,
        body: StoryboardSaveRequest,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> StoryboardVersionResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            record: StoryboardVersionRecord = await StoryboardRepository(database_pool).save_version(
                brand_id=brand_id,
                content_id=content_id,
                owner_user_id=principal.subject,
                expected_version=body.expected_version,
                storyboard=body.storyboard,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="content_not_found") from exc
        except StoryboardVersionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "storyboard_version_conflict", "current_version": exc.current_version},
            ) from exc
        except InvalidContentTransition as exc:
            raise HTTPException(status_code=409, detail="storyboard_not_allowed_in_current_content_state") from exc
        except InvalidStoryboardTimeline as exc:
            raise HTTPException(status_code=422, detail="storyboard_duration_mismatch") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return StoryboardVersionResponse(
            content_id=record.content_id,
            version=record.version,
            title=record.title,
            total_duration_ms=record.total_duration_ms,
            storyboard=record.storyboard,
            created_at=record.created_at,
        )

    @app.get(
        "/api/v1/brands/{brand_id}/content/{content_id}/storyboard",
        response_model=StoryboardVersionResponse,
        tags=["content"],
    )
    async def get_current_storyboard(
        brand_id: UUID,
        content_id: UUID,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> StoryboardVersionResponse:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            versions = await StoryboardRepository(database_pool).list_versions(
                brand_id=brand_id, content_id=content_id, owner_user_id=principal.subject,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="content_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        if not versions:
            raise HTTPException(status_code=404, detail="storyboard_not_found")
        record = versions[-1]
        return StoryboardVersionResponse(
            content_id=record.content_id,
            version=record.version,
            title=record.title,
            total_duration_ms=record.total_duration_ms,
            storyboard=record.storyboard,
            created_at=record.created_at,
        )

    @app.get(
        "/api/v1/brands/{brand_id}/content/{content_id}/storyboard/versions",
        response_model=list[StoryboardVersionResponse],
        tags=["content"],
    )
    async def list_storyboard_versions(
        brand_id: UUID,
        content_id: UUID,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[StoryboardVersionResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            versions = await StoryboardRepository(database_pool).list_versions(
                brand_id=brand_id, content_id=content_id, owner_user_id=principal.subject,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="content_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [StoryboardVersionResponse(
            content_id=record.content_id,
            version=record.version,
            title=record.title,
            total_duration_ms=record.total_duration_ms,
            storyboard=record.storyboard,
            created_at=record.created_at,
        ) for record in versions]

    @app.get(
        "/api/v1/brands/{brand_id}/content/{content_id}/assets",
        response_model=list[AssetResponse],
        tags=["content"],
    )
    async def list_content_assets(
        brand_id: UUID,
        content_id: UUID,
        scene_id: UUID | None = None,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[AssetResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            records: list[AssetRecord] = await AssetRepository(database_pool).list_for_content(
                brand_id=brand_id, content_id=content_id,
                owner_user_id=principal.subject, scene_id=scene_id,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="content_not_found") from exc
        except InvalidAssetLineage as exc:
            raise HTTPException(status_code=404, detail="scene_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return [AssetResponse(
            asset_id=record.metadata.asset_id,
            content_id=record.metadata.content_id,
            scene_id=record.metadata.scene_id,
            source_job_id=record.metadata.source_job_id,
            kind=record.metadata.kind,
            storage_uri=record.metadata.storage_uri,
            sha256_hex=record.metadata.sha256_hex,
            mime_type=record.metadata.mime_type,
            size_bytes=record.metadata.size_bytes,
            media_metadata=record.metadata.media_metadata,
            created_at=record.created_at,
        ) for record in records]

    @app.get(
        "/api/v1/brands/{brand_id}/content/{content_id}/audio-assets",
        response_model=list[AudioAssetResponse],
        tags=["audio"],
    )
    async def list_audio_assets(
        brand_id: UUID,
        content_id: UUID,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> list[AudioAssetResponse]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            records = await AssetRepository(database_pool).list_for_content(
                brand_id=brand_id, content_id=content_id, owner_user_id=principal.subject,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="content_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        response: list[AudioAssetResponse] = []
        for record in records:
            asset = record.metadata
            if not asset.mime_type.startswith("audio/"):
                continue
            duration = asset.media_metadata.get("duration_ms")
            start = asset.media_metadata.get("timeline_start_ms")
            response.append(AudioAssetResponse(
                asset_id=asset.asset_id, content_id=asset.content_id, scene_id=asset.scene_id,
                kind=asset.kind, mime_type=asset.mime_type, size_bytes=asset.size_bytes,
                duration_ms=duration if type(duration) is int and duration >= 0 else None,
                timeline_start_ms=start if type(start) is int and start >= 0 else None,
                created_at=record.created_at,
            ))
        return response

    @app.get(
        "/api/v1/brands/{brand_id}/content/{content_id}/audio-assets/{asset_id}/preview",
        tags=["audio"],
    )
    async def preview_audio_asset(
        brand_id: UUID,
        content_id: UUID,
        asset_id: UUID,
        range_header: str | None = Header(default=None, alias="Range"),
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.REVIEWER)),
    ) -> Response:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        if storage_root is None:
            raise HTTPException(status_code=503, detail="audio_preview_not_configured")
        try:
            payload = await AudioPreviewService(
                storage_root=storage_root,
                store=AssetCatalogRepository(database_pool),
            ).preview(
                asset_id=asset_id, brand_id=brand_id, content_id=content_id,
                owner_user_id=principal.subject, range_header=range_header,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="audio_asset_not_found") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        except AudioPreviewError as exc:
            if exc.code.startswith("RANGE_"):
                headers = {"Accept-Ranges": "bytes"}
                if exc.total is not None:
                    headers["Content-Range"] = f"bytes */{exc.total}"
                raise HTTPException(status_code=416, detail="audio_range_invalid", headers=headers) from exc
            raise HTTPException(status_code=409, detail="audio_preview_unavailable") from exc
        selected = payload.selected_range
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "ETag": payload.etag,
            "Content-Length": str(selected.length),
            "X-Content-Type-Options": "nosniff",
        }
        if payload.partial:
            headers["Content-Range"] = f"bytes {selected.start}-{selected.end}/{selected.total}"
        return Response(
            content=payload.data, status_code=206 if payload.partial else 200,
            media_type=payload.mime_type, headers=headers,
        )

    @app.post(
        "/api/v1/brands/{brand_id}/content/{content_id}/audio-assets/{asset_id}/retire",
        tags=["audio"],
    )
    async def retire_audio_asset(
        brand_id: UUID,
        content_id: UUID,
        asset_id: UUID,
        body: AudioRetireRequest,
        principal: Principal = Depends(require_roles(Role.ADMIN, Role.OPERATOR)),
    ) -> dict[str, bool]:
        if database_pool is None:
            raise HTTPException(status_code=503, detail="database_not_configured")
        catalog = AssetCatalogRepository(database_pool)
        try:
            await catalog.get_active_audio(
                asset_id=asset_id, brand_id=brand_id, content_id=content_id,
                owner_user_id=principal.subject,
            )
            retired = await catalog.tombstone(
                asset_id=asset_id, owner_user_id=principal.subject,
                created_before=body.created_before, reason=body.reason,
            )
        except OwnedContentNotFound as exc:
            raise HTTPException(status_code=404, detail="audio_asset_not_found") from exc
        except AssetRetentionBlocked as exc:
            raise HTTPException(status_code=409, detail="audio_retention_blocked") from exc
        except RepositoryUnavailable as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return {"retired": retired}

    return app


app = create_app()
