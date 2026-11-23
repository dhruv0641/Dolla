"""Fail-closed approval, spend and descriptive-outcome feedback boundaries."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flowx_os.analytics.cohorts import (
    CohortAnalysisReport,
    CohortAnalysisRequest,
    CohortReportStatus,
)
from flowx_os.analytics.metrics import MetricRegistry
from flowx_os.analytics.recommendations import ExperimentProposal
from flowx_os.credits.reservations import CreditReservationRecord, CreditReservationState
from flowx_os.flow_mcp.capabilities import FlowOperation


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _aware_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None
        and value.utcoffset() is not None and value.utcoffset() == timedelta(0)
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash(*values: str) -> str:
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


class FeedbackGateCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    PROPOSAL_MISMATCH = "PROPOSAL_MISMATCH"
    RESERVATION_MISMATCH = "RESERVATION_MISMATCH"
    SPEND_STATE_INVALID = "SPEND_STATE_INVALID"
    HUMAN_APPROVAL_UNAVAILABLE = "HUMAN_APPROVAL_UNAVAILABLE"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    SPEND_APPROVAL_UNAVAILABLE = "SPEND_APPROVAL_UNAVAILABLE"
    SPEND_APPROVAL_REQUIRED = "SPEND_APPROVAL_REQUIRED"
    OUTCOME_MISMATCH = "OUTCOME_MISMATCH"


class FeedbackGateError(RuntimeError):
    def __init__(self, code: FeedbackGateCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class FeedbackGateStatus(StrEnum):
    APPROVED_PENDING_FRESH_EXECUTOR_REVALIDATION = "APPROVED_PENDING_FRESH_EXECUTOR_REVALIDATION"


class FeedbackOutcomeStatus(StrEnum):
    DESCRIPTIVE_FEEDBACK_ONLY_NOT_CAUSAL = "DESCRIPTIVE_FEEDBACK_ONLY_NOT_CAUSAL"


class FeedbackApprovalKind(StrEnum):
    HUMAN_EXPERIMENT = "HUMAN_EXPERIMENT"
    SPEND = "SPEND"


@dataclass(frozen=True, slots=True)
class FeedbackApprovalAttestation:
    attestation_id: UUID
    kind: FeedbackApprovalKind
    approval_ref: str
    owner_user_id: str
    proposal_id: UUID
    proposal_fingerprint: str
    account_id: UUID | None
    maximum_credits: int | None
    operation: FlowOperation | None
    verifier_ref: str
    verifier_version: str
    evidence_fingerprint: str
    verified_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        spend = self.kind is FeedbackApprovalKind.SPEND
        if (
            not isinstance(self.attestation_id, UUID)
            or not isinstance(self.kind, FeedbackApprovalKind)
            or _SAFE_REF.fullmatch(self.approval_ref or "") is None
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.proposal_id, UUID)
            or _HEX64.fullmatch(self.proposal_fingerprint or "") is None
            or (spend != isinstance(self.account_id, UUID))
            or (spend != (type(self.maximum_credits) is int))
            or (spend != isinstance(self.operation, FlowOperation))
            or (spend and self.operation is not FlowOperation.VIDEO_GENERATE)
            or (spend and not 1 <= self.maximum_credits <= 1_000_000_000)
            or _SAFE_REF.fullmatch(self.verifier_ref or "") is None
            or _SAFE_VERSION.fullmatch(self.verifier_version or "") is None
            or _HEX64.fullmatch(self.evidence_fingerprint or "") is None
            or not _aware_utc(self.verified_at)
            or not _aware_utc(self.expires_at)
            or self.expires_at <= self.verified_at
        ):
            raise FeedbackGateError(FeedbackGateCode.INVALID_REQUEST, "approval attestation is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            str(self.attestation_id), self.kind.value, self.approval_ref,
            self.owner_user_id, str(self.proposal_id), self.proposal_fingerprint,
            str(self.account_id) if self.account_id else "",
            str(self.maximum_credits) if self.maximum_credits is not None else "",
            self.operation.value if self.operation else "",
            self.verifier_ref, self.verifier_version, self.evidence_fingerprint,
            _timestamp(self.verified_at), _timestamp(self.expires_at),
        )


class ExperimentApprovalVerifier(Protocol):
    async def verify(
        self, *, approval_ref: str, owner_user_id: str,
        proposal_id: UUID, proposal_fingerprint: str,
    ) -> FeedbackApprovalAttestation | None: ...


class FeedbackSpendApprovalVerifier(Protocol):
    async def verify(
        self, *, approval_ref: str, owner_user_id: str,
        proposal_id: UUID, proposal_fingerprint: str,
        account_id: UUID, operation: FlowOperation,
        maximum_credits: int,
    ) -> FeedbackApprovalAttestation | None: ...


@dataclass(frozen=True, slots=True)
class FeedbackGateRequest:
    gate_id: UUID
    owner_user_id: str
    proposal_id: UUID
    proposal_fingerprint: str
    account_id: UUID
    reservation_id: UUID
    reservation_request_id: UUID
    maximum_credits: int
    human_approval_ref: str
    spend_approval_ref: str
    definition_version: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.gate_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.proposal_id, UUID)
            or _HEX64.fullmatch(self.proposal_fingerprint or "") is None
            or not isinstance(self.account_id, UUID)
            or not isinstance(self.reservation_id, UUID)
            or not isinstance(self.reservation_request_id, UUID)
            or type(self.maximum_credits) is not int
            or not 1 <= self.maximum_credits <= 1_000_000_000
            or _SAFE_REF.fullmatch(self.human_approval_ref or "") is None
            or _SAFE_REF.fullmatch(self.spend_approval_ref or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or not _aware_utc(self.requested_at)
        ):
            raise FeedbackGateError(FeedbackGateCode.INVALID_REQUEST, "feedback gate request is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            str(self.gate_id), self.owner_user_id, str(self.proposal_id),
            self.proposal_fingerprint, str(self.account_id),
            str(self.reservation_id), str(self.reservation_request_id),
            str(self.maximum_credits), self.human_approval_ref,
            self.spend_approval_ref, self.definition_version,
            _timestamp(self.requested_at),
        )


@dataclass(frozen=True, slots=True)
class FeedbackGateDecision:
    gate_id: UUID
    owner_user_id: str
    request_fingerprint: str
    proposal_id: UUID
    proposal_fingerprint: str
    account_id: UUID
    reservation_id: UUID
    reservation_request_id: UUID
    maximum_credits: int
    quoted_credits: int
    quote_expires_at: datetime
    human_attestation_id: UUID
    human_approval_fingerprint: str
    spend_attestation_id: UUID
    spend_approval_fingerprint: str
    definition_version: str
    requested_at: datetime
    approved_at: datetime
    status: FeedbackGateStatus = FeedbackGateStatus.APPROVED_PENDING_FRESH_EXECUTOR_REVALIDATION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.gate_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or _HEX64.fullmatch(self.request_fingerprint or "") is None
            or not isinstance(self.proposal_id, UUID)
            or _HEX64.fullmatch(self.proposal_fingerprint or "") is None
            or not isinstance(self.account_id, UUID)
            or not isinstance(self.reservation_id, UUID)
            or not isinstance(self.reservation_request_id, UUID)
            or type(self.maximum_credits) is not int
            or type(self.quoted_credits) is not int
            or not 1 <= self.quoted_credits <= self.maximum_credits <= 1_000_000_000
            or not _aware_utc(self.quote_expires_at)
            or not isinstance(self.human_attestation_id, UUID)
            or _HEX64.fullmatch(self.human_approval_fingerprint or "") is None
            or not isinstance(self.spend_attestation_id, UUID)
            or _HEX64.fullmatch(self.spend_approval_fingerprint or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or not _aware_utc(self.requested_at)
            or not _aware_utc(self.approved_at)
            or self.approved_at < self.requested_at
            or self.quote_expires_at <= self.approved_at
            or not isinstance(self.status, FeedbackGateStatus)
        ):
            raise FeedbackGateError(FeedbackGateCode.INVALID_REQUEST, "feedback gate decision is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            str(self.gate_id), self.owner_user_id, self.request_fingerprint,
            str(self.proposal_id), self.proposal_fingerprint,
            str(self.account_id), str(self.reservation_id),
            str(self.reservation_request_id), str(self.maximum_credits),
            str(self.quoted_credits), _timestamp(self.quote_expires_at),
            str(self.human_attestation_id), self.human_approval_fingerprint,
            str(self.spend_attestation_id), self.spend_approval_fingerprint,
            self.definition_version, self.status.value,
            _timestamp(self.approved_at),
        )

    def canonical(self) -> dict[str, object]:
        return {
            "gate_id": str(self.gate_id), "owner_user_id": self.owner_user_id,
            "request_fingerprint": self.request_fingerprint,
            "proposal_id": str(self.proposal_id),
            "proposal_fingerprint": self.proposal_fingerprint,
            "account_id": str(self.account_id),
            "reservation_id": str(self.reservation_id),
            "reservation_request_id": str(self.reservation_request_id),
            "maximum_credits": self.maximum_credits,
            "quoted_credits": self.quoted_credits,
            "quote_expires_at": _timestamp(self.quote_expires_at),
            "human_attestation_id": str(self.human_attestation_id),
            "human_approval_fingerprint": self.human_approval_fingerprint,
            "spend_attestation_id": str(self.spend_attestation_id),
            "spend_approval_fingerprint": self.spend_approval_fingerprint,
            "definition_version": self.definition_version,
            "requested_at": _timestamp(self.requested_at),
            "status": self.status.value,
            "separate_executor_must_revalidate_exact_reservation": True,
            "execution_authorized": False,
            "automatic_execution": False,
            "account_connection_authorized": False,
            "scheduling_authorized": False,
            "upload_authorized": False,
            "publishing_authorized": False,
            "approved_at": _timestamp(self.approved_at),
        }


class FeedbackGateStore(Protocol):
    async def assert_proposal_owned(
        self, *, proposal_id: UUID, proposal_fingerprint: str,
        owner_user_id: str,
    ) -> None: ...

    async def get_owned_reservation(
        self, *, reservation_id: UUID, account_id: UUID,
        owner_user_id: str,
    ) -> CreditReservationRecord: ...

    async def record_gate(
        self, *, request: FeedbackGateRequest,
        decision: FeedbackGateDecision,
        human_attestation: FeedbackApprovalAttestation,
        spend_attestation: FeedbackApprovalAttestation,
    ) -> FeedbackGateDecision: ...


class FeedbackGateService:
    """Verify approvals and persist eligibility without calling any executor."""

    def __init__(
        self, store: FeedbackGateStore,
        human_verifier: ExperimentApprovalVerifier | None,
        spend_verifier: FeedbackSpendApprovalVerifier | None,
        *, now=None,
    ) -> None:
        self._store = store
        self._human = human_verifier
        self._spend = spend_verifier
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def approve(
        self, *, request: FeedbackGateRequest,
        proposal: ExperimentProposal,
    ) -> FeedbackGateDecision:
        if (
            not isinstance(request, FeedbackGateRequest)
            or not isinstance(proposal, ExperimentProposal)
            or proposal.proposal_id != request.proposal_id
            or proposal.owner_user_id != request.owner_user_id
            or proposal.fingerprint != request.proposal_fingerprint
        ):
            raise FeedbackGateError(FeedbackGateCode.PROPOSAL_MISMATCH, "experiment proposal does not match")
        await self._store.assert_proposal_owned(
            proposal_id=request.proposal_id,
            proposal_fingerprint=request.proposal_fingerprint,
            owner_user_id=request.owner_user_id,
        )
        reservation = await self._store.get_owned_reservation(
            reservation_id=request.reservation_id,
            account_id=request.account_id,
            owner_user_id=request.owner_user_id,
        )
        now = self._now()
        if not _aware_utc(now):
            raise FeedbackGateError(FeedbackGateCode.SPEND_STATE_INVALID, "decision time is invalid")
        if (
            not isinstance(reservation, CreditReservationRecord)
            or reservation.id != request.reservation_id
            or reservation.flow_account_id != request.account_id
            or reservation.request_id != request.reservation_request_id
        ):
            raise FeedbackGateError(FeedbackGateCode.RESERVATION_MISMATCH, "credit reservation does not match")
        if (
            reservation.state is not CreditReservationState.RESERVED
            or reservation.quote_expires_at <= now
            or reservation.quoted_credits > request.maximum_credits
        ):
            raise FeedbackGateError(FeedbackGateCode.SPEND_STATE_INVALID, "credit reservation is not safely claimable")
        if self._human is None:
            raise FeedbackGateError(FeedbackGateCode.HUMAN_APPROVAL_UNAVAILABLE, "human approval verifier is unavailable")
        try:
            human_attestation = await self._human.verify(
                approval_ref=request.human_approval_ref,
                owner_user_id=request.owner_user_id,
                proposal_id=request.proposal_id,
                proposal_fingerprint=request.proposal_fingerprint,
            )
        except Exception as exc:
            raise FeedbackGateError(FeedbackGateCode.HUMAN_APPROVAL_UNAVAILABLE, "human approval could not be verified") from exc
        if not _valid_attestation(
            human_attestation, kind=FeedbackApprovalKind.HUMAN_EXPERIMENT,
            request=request, quoted_credits=None, now=now,
        ):
            raise FeedbackGateError(FeedbackGateCode.HUMAN_APPROVAL_REQUIRED, "explicit experiment approval is required")
        if self._spend is None:
            raise FeedbackGateError(FeedbackGateCode.SPEND_APPROVAL_UNAVAILABLE, "spend approval verifier is unavailable")
        try:
            spend_attestation = await self._spend.verify(
                approval_ref=request.spend_approval_ref,
                owner_user_id=request.owner_user_id,
                proposal_id=request.proposal_id,
                proposal_fingerprint=request.proposal_fingerprint,
                account_id=request.account_id,
                operation=FlowOperation.VIDEO_GENERATE,
                maximum_credits=reservation.quoted_credits,
            )
        except Exception as exc:
            raise FeedbackGateError(FeedbackGateCode.SPEND_APPROVAL_UNAVAILABLE, "spend approval could not be verified") from exc
        if not _valid_attestation(
            spend_attestation, kind=FeedbackApprovalKind.SPEND,
            request=request, quoted_credits=reservation.quoted_credits, now=now,
        ):
            raise FeedbackGateError(FeedbackGateCode.SPEND_APPROVAL_REQUIRED, "explicit spend approval is required")
        approved_at = self._now()
        if (
            not _aware_utc(approved_at)
            or approved_at >= reservation.quote_expires_at
            or approved_at >= human_attestation.expires_at
            or approved_at >= spend_attestation.expires_at
        ):
            raise FeedbackGateError(FeedbackGateCode.SPEND_STATE_INVALID, "approval expired before commit")
        decision = FeedbackGateDecision(
            gate_id=request.gate_id, owner_user_id=request.owner_user_id,
            request_fingerprint=request.fingerprint,
            proposal_id=request.proposal_id,
            proposal_fingerprint=request.proposal_fingerprint,
            account_id=request.account_id,
            reservation_id=request.reservation_id,
            reservation_request_id=request.reservation_request_id,
            maximum_credits=request.maximum_credits,
            quoted_credits=reservation.quoted_credits,
            quote_expires_at=reservation.quote_expires_at,
            human_attestation_id=human_attestation.attestation_id,
            human_approval_fingerprint=human_attestation.fingerprint,
            spend_attestation_id=spend_attestation.attestation_id,
            spend_approval_fingerprint=spend_attestation.fingerprint,
            definition_version=request.definition_version,
            requested_at=request.requested_at,
            approved_at=approved_at,
        )
        return await self._store.record_gate(
            request=request, decision=decision,
            human_attestation=human_attestation,
            spend_attestation=spend_attestation,
        )


def _valid_attestation(
    value: FeedbackApprovalAttestation | None, *, kind: FeedbackApprovalKind,
    request: FeedbackGateRequest, quoted_credits: int | None, now: datetime,
) -> bool:
    return (
        isinstance(value, FeedbackApprovalAttestation)
        and value.kind is kind
        and value.approval_ref == (
            request.human_approval_ref
            if kind is FeedbackApprovalKind.HUMAN_EXPERIMENT
            else request.spend_approval_ref
        )
        and value.owner_user_id == request.owner_user_id
        and value.proposal_id == request.proposal_id
        and value.proposal_fingerprint == request.proposal_fingerprint
        and value.verified_at <= now < value.expires_at
        and (
            (value.account_id is None and value.maximum_credits is None)
            if kind is FeedbackApprovalKind.HUMAN_EXPERIMENT
            else (
                value.account_id == request.account_id
                and value.maximum_credits == quoted_credits
                and value.operation is FlowOperation.VIDEO_GENERATE
            )
        )
    )


@dataclass(frozen=True, slots=True)
class FeedbackOutcomeRequest:
    outcome_id: UUID
    owner_user_id: str
    gate_id: UUID
    gate_fingerprint: str
    report_request_id: UUID
    report_fingerprint: str
    definition_version: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.outcome_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.gate_id, UUID)
            or _HEX64.fullmatch(self.gate_fingerprint or "") is None
            or not isinstance(self.report_request_id, UUID)
            or _HEX64.fullmatch(self.report_fingerprint or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or not _aware_utc(self.recorded_at)
        ):
            raise FeedbackGateError(FeedbackGateCode.INVALID_REQUEST, "feedback outcome request is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            str(self.outcome_id), self.owner_user_id, str(self.gate_id),
            self.gate_fingerprint, str(self.report_request_id),
            self.report_fingerprint, self.definition_version,
            _timestamp(self.recorded_at),
        )


@dataclass(frozen=True, slots=True)
class FeedbackOutcome:
    outcome_id: UUID
    owner_user_id: str
    request_fingerprint: str
    gate_id: UUID
    gate_fingerprint: str
    proposal_id: UUID
    proposal_fingerprint: str
    report_request_id: UUID
    report_request_fingerprint: str
    report_fingerprint: str
    definition_version: str
    source_count: int
    recorded_at: datetime
    status: FeedbackOutcomeStatus = FeedbackOutcomeStatus.DESCRIPTIVE_FEEDBACK_ONLY_NOT_CAUSAL

    def __post_init__(self) -> None:
        if (
            not isinstance(self.outcome_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or any(_HEX64.fullmatch(value or "") is None for value in (
                self.request_fingerprint, self.gate_fingerprint,
                self.proposal_fingerprint, self.report_request_fingerprint,
                self.report_fingerprint,
            ))
            or not all(isinstance(value, UUID) for value in (
                self.gate_id, self.proposal_id, self.report_request_id,
            ))
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or type(self.source_count) is not int or not 1 <= self.source_count <= 10_000
            or not _aware_utc(self.recorded_at)
            or not isinstance(self.status, FeedbackOutcomeStatus)
        ):
            raise FeedbackGateError(FeedbackGateCode.INVALID_REQUEST, "feedback outcome is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            str(self.outcome_id), self.owner_user_id, self.request_fingerprint,
            str(self.gate_id), self.gate_fingerprint, str(self.proposal_id),
            self.proposal_fingerprint, str(self.report_request_id),
            self.report_request_fingerprint, self.report_fingerprint,
            self.definition_version, str(self.source_count), self.status.value,
            _timestamp(self.recorded_at),
        )

    def canonical(self) -> dict[str, object]:
        return {
            "outcome_id": str(self.outcome_id), "owner_user_id": self.owner_user_id,
            "request_fingerprint": self.request_fingerprint,
            "gate_id": str(self.gate_id), "gate_fingerprint": self.gate_fingerprint,
            "proposal_id": str(self.proposal_id),
            "proposal_fingerprint": self.proposal_fingerprint,
            "report_request_id": str(self.report_request_id),
            "report_request_fingerprint": self.report_request_fingerprint,
            "report_fingerprint": self.report_fingerprint,
            "definition_version": self.definition_version,
            "source_count": self.source_count, "status": self.status.value,
            "new_recommendation_requires_separate_human_review": True,
            "causal_claim_authorized": False,
            "automatic_execution": False,
            "recorded_at": _timestamp(self.recorded_at),
        }


class FeedbackOutcomeStore(Protocol):
    async def record_outcome(
        self, *, request: FeedbackOutcomeRequest,
        outcome: FeedbackOutcome,
    ) -> FeedbackOutcome: ...


class FeedbackOutcomeRecorder:
    """Link post-gate typed cohort evidence; never execute or infer causality."""

    def __init__(self, store: FeedbackOutcomeStore) -> None:
        self._store = store

    async def record(
        self, *, request: FeedbackOutcomeRequest,
        gate: FeedbackGateDecision, proposal: ExperimentProposal,
        analysis_request: CohortAnalysisRequest,
        report: CohortAnalysisReport, registry: MetricRegistry,
    ) -> FeedbackOutcome:
        cohorts = {item.label: item for item in report.cohorts}
        control = cohorts.get(proposal.control_label)
        treatment = cohorts.get(proposal.treatment_label)
        if (
            not isinstance(request, FeedbackOutcomeRequest)
            or not isinstance(gate, FeedbackGateDecision)
            or not isinstance(proposal, ExperimentProposal)
            or not isinstance(analysis_request, CohortAnalysisRequest)
            or not isinstance(report, CohortAnalysisReport)
            or not isinstance(registry, MetricRegistry)
            or request.owner_user_id != gate.owner_user_id
            or request.gate_id != gate.gate_id
            or request.gate_fingerprint != gate.fingerprint
            or request.report_request_id != analysis_request.request_id
            or request.report_fingerprint != report.fingerprint
            or gate.proposal_id != proposal.proposal_id
            or gate.proposal_fingerprint != proposal.fingerprint
            or proposal.owner_user_id != request.owner_user_id
            or analysis_request.owner_user_id != request.owner_user_id
            or report.request_fingerprint != analysis_request.fingerprint
            or report.status is not CohortReportStatus.DESCRIPTIVE
            or analysis_request.factor is not proposal.factor
            or analysis_request.metric_id != proposal.metric_id
            or analysis_request.window is not proposal.window
            or analysis_request.registry_version != proposal.registry_version
            or analysis_request.registry_fingerprint != proposal.registry_fingerprint
            or registry.version != proposal.registry_version
            or registry.fingerprint != proposal.registry_fingerprint
            or registry.require(proposal.metric_id).platform is not proposal.platform
            or control is None or treatment is None
            or not control.eligible or not treatment.eligible
            or control.sample_size < proposal.control_target_size
            or treatment.sample_size < proposal.treatment_target_size
            or request.recorded_at < gate.approved_at
        ):
            raise FeedbackGateError(FeedbackGateCode.OUTCOME_MISMATCH, "feedback outcome is not exact post-gate evidence")
        outcome = FeedbackOutcome(
            outcome_id=request.outcome_id, owner_user_id=request.owner_user_id,
            request_fingerprint=request.fingerprint,
            gate_id=request.gate_id, gate_fingerprint=request.gate_fingerprint,
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            report_request_id=request.report_request_id,
            report_request_fingerprint=analysis_request.fingerprint,
            report_fingerprint=report.fingerprint,
            definition_version=request.definition_version,
            source_count=len(report.sources), recorded_at=request.recorded_at,
        )
        return await self._store.record_outcome(request=request, outcome=outcome)
