"""Verified credit quote and spend-approval boundary for account reservations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Callable, Protocol
from uuid import UUID

from flowx_os.flow_mcp.adapter import SpendAuthorizationVerifier
from flowx_os.flow_mcp.capabilities import FlowOperation


class CreditOperationError(RuntimeError):
    """Safe, stable error raised when quote or reservation prerequisites fail."""


class CreditQuoteUnavailable(CreditOperationError):
    pass


class InvalidCreditQuote(CreditOperationError):
    pass


class CreditApprovalUnavailable(CreditOperationError):
    pass


class CreditApprovalRequired(CreditOperationError):
    pass


class CreditQuoteSource(StrEnum):
    FLOW_QUOTE = "FLOW_QUOTE"
    APPROVED_RATE_CARD = "APPROVED_RATE_CARD"


class CreditReservationState(StrEnum):
    RESERVED = "RESERVED"
    RECONCILE_PENDING = "RECONCILE_PENDING"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


@dataclass(frozen=True, slots=True)
class CreditQuoteRequest:
    account_ref: str
    request_id: UUID
    model_name: str
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class CreditQuoteEvidence:
    quote_ref: str
    account_ref: str
    request_id: UUID
    model_name: str
    duration_seconds: int
    quoted_credits: int
    source: CreditQuoteSource
    quoted_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CreditReservationRecord:
    id: UUID
    flow_account_id: UUID
    request_id: UUID
    model_name: str
    duration_seconds: int
    quote_ref: str
    quoted_credits: int
    quote_source: CreditQuoteSource
    quoted_at: datetime
    quote_expires_at: datetime
    state: CreditReservationState
    created_at: datetime


class CreditQuoteProvider(Protocol):
    async def get_quote(self, request: CreditQuoteRequest) -> CreditQuoteEvidence | None:
        """Return a verifiable quote or None when the provider cannot quote."""


class CreditReservationStore(Protocol):
    async def reserve(
        self,
        *,
        account_id: UUID,
        owner_user_id: str,
        request_id: UUID,
        quote: CreditQuoteEvidence,
        now: datetime,
        max_quote_age: timedelta,
        max_balance_age: timedelta,
    ) -> CreditReservationRecord: ...


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class CreditReservationService:
    """Obtains a bounded quote, verifies explicit approval, then reserves atomically."""

    def __init__(
        self,
        store: CreditReservationStore,
        quote_provider: CreditQuoteProvider | None,
        spend_authorizer: SpendAuthorizationVerifier | None,
        *,
        max_credits_per_request: int | None,
        max_quote_age: timedelta = timedelta(minutes=5),
        max_balance_age: timedelta = timedelta(minutes=15),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._quote_provider = quote_provider
        self._spend_authorizer = spend_authorizer
        self._max_credits = max_credits_per_request
        self._max_quote_age = max_quote_age
        self._max_balance_age = max_balance_age
        self._now = now or (lambda: datetime.now(timezone.utc))
        if max_quote_age <= timedelta(0) or max_balance_age <= timedelta(0):
            raise ValueError("quote and balance freshness windows must be positive")

    async def reserve(
        self,
        *,
        account_id: UUID,
        owner_user_id: str,
        request_id: UUID,
        model_name: str,
        duration_seconds: int,
        approval_ref: str,
    ) -> CreditReservationRecord:
        if self._quote_provider is None or self._max_credits is None:
            raise CreditQuoteUnavailable("credit quote capability is not configured")
        if (
            isinstance(self._max_credits, bool)
            or not isinstance(self._max_credits, int)
            or self._max_credits <= 0
        ):
            raise CreditQuoteUnavailable("credit limit policy is not configured")
        if (
            not isinstance(model_name, str)
            or not model_name.strip()
            or len(model_name) > 100
            or any(ord(char) < 32 or ord(char) == 127 for char in model_name)
            or isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, int)
            or not 4 <= duration_seconds <= 180
        ):
            raise InvalidCreditQuote("requested model or duration is invalid")
        model_name = model_name.strip()
        request = CreditQuoteRequest(
            account_ref=str(account_id),
            request_id=request_id,
            model_name=model_name,
            duration_seconds=duration_seconds,
        )
        try:
            evidence = await self._quote_provider.get_quote(request)
        except Exception as exc:
            raise CreditQuoteUnavailable("credit quote provider is unavailable") from exc
        now = self._now()
        self._validate_quote(evidence, request=request, now=now)
        if evidence.quoted_credits > self._max_credits:
            raise InvalidCreditQuote("credit quote exceeds configured per-request limit")

        if self._spend_authorizer is None:
            raise CreditApprovalUnavailable("spend approval verifier is not configured")
        if not isinstance(approval_ref, str) or not approval_ref.strip():
            raise CreditApprovalRequired("explicit spend approval is required")
        try:
            approved = await self._spend_authorizer.is_authorized(
                approval_ref=approval_ref,
                account_ref=request.account_ref,
                operation=FlowOperation.VIDEO_GENERATE,
                max_allowed_credits=evidence.quoted_credits,
            )
        except Exception as exc:
            raise CreditApprovalUnavailable("spend approval could not be verified") from exc
        if approved is not True:
            raise CreditApprovalRequired("explicit spend approval is required")

        # Recheck quote freshness after provider and approval awaits, immediately
        # before asking the repository to lock and reserve the account wallet.
        now = self._now()
        self._validate_quote(evidence, request=request, now=now)
        return await self._store.reserve(
            account_id=account_id,
            owner_user_id=owner_user_id,
            request_id=request_id,
            quote=evidence,
            now=now,
            max_quote_age=self._max_quote_age,
            max_balance_age=self._max_balance_age,
        )

    def _validate_quote(
        self,
        evidence: CreditQuoteEvidence | None,
        *,
        request: CreditQuoteRequest,
        now: datetime,
    ) -> None:
        if not isinstance(evidence, CreditQuoteEvidence):
            raise InvalidCreditQuote("provider returned no supported quote")
        if (
            not isinstance(evidence.quote_ref, str)
            or not evidence.quote_ref.strip()
            or len(evidence.quote_ref) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in evidence.quote_ref)
            or evidence.account_ref != request.account_ref
            or evidence.request_id != request.request_id
            or evidence.model_name != request.model_name
            or evidence.duration_seconds != request.duration_seconds
            or isinstance(evidence.quoted_credits, bool)
            or not isinstance(evidence.quoted_credits, int)
            or evidence.quoted_credits <= 0
            or not isinstance(evidence.source, CreditQuoteSource)
            or not isinstance(evidence.quoted_at, datetime)
            or not isinstance(evidence.expires_at, datetime)
            or not isinstance(now, datetime)
            or not _is_aware(evidence.quoted_at)
            or not _is_aware(evidence.expires_at)
            or not _is_aware(now)
        ):
            raise InvalidCreditQuote("provider quote did not match the requested account and operation")
        if evidence.quoted_at > now or evidence.quoted_at < now - self._max_quote_age:
            raise InvalidCreditQuote("provider quote is stale")
        if evidence.expires_at <= now or evidence.expires_at <= evidence.quoted_at:
            raise InvalidCreditQuote("provider quote is expired")
