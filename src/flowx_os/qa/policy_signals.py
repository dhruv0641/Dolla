"""Evidence-bound policy, factuality and copyright QA signals.

This module does not decide that content is lawful, true, safe, or approved. It
turns an already validated automated content review into deterministic signals
and keeps the human-approval boundary explicit.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.agents.review import (
    HumanReviewResult,
    ReviewCategory,
    ReviewContext,
    ReviewDisposition,
    ReviewSeverity,
    review_context_fingerprint,
)
from flowx_os.qa.av_evaluation import AvDecision, AvEvaluationReport


class SignalDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class SignalDomain(StrEnum):
    POLICY = "POLICY"
    FACTUALITY = "FACTUALITY"
    COPYRIGHT = "COPYRIGHT"


class SignalState(StrEnum):
    NO_AUTOMATED_FLAG = "NO_AUTOMATED_FLAG"
    FLAGGED = "FLAGGED"
    UNAVAILABLE = "UNAVAILABLE"


class SignalFindingSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    REVIEW = "REVIEW"


class SignalFindingCode(StrEnum):
    POLICY_CRITICAL = "POLICY_CRITICAL"
    POLICY_REVIEW_REQUIRED = "POLICY_REVIEW_REQUIRED"
    FACTUALITY_CRITICAL = "FACTUALITY_CRITICAL"
    FACTUALITY_REVIEW_REQUIRED = "FACTUALITY_REVIEW_REQUIRED"
    COPYRIGHT_CRITICAL = "COPYRIGHT_CRITICAL"
    COPYRIGHT_REVIEW_REQUIRED = "COPYRIGHT_REVIEW_REQUIRED"
    COPYRIGHT_AUTHORITY_UNAVAILABLE = "COPYRIGHT_AUTHORITY_UNAVAILABLE"
    AUTOMATED_REVIEW_BLOCKED = "AUTOMATED_REVIEW_BLOCKED"
    AUTOMATED_REVIEW_NEEDS_REVISION = "AUTOMATED_REVIEW_NEEDS_REVISION"


class ContentSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    domain: SignalDomain
    state: SignalState
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    authority_refs: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("authority_refs")
    @classmethod
    def authority_refs_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("authority references must be unique")
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value) for value in values):
            raise ValueError("authority reference is invalid")
        return values

    @model_validator(mode="after")
    def state_matches_evidence(self) -> "ContentSignal":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("signal evidence IDs must be unique")
        if self.domain == SignalDomain.POLICY and not self.authority_refs:
            raise ValueError("policy signal requires a pinned policy authority")
        if self.domain == SignalDomain.COPYRIGHT:
            if self.state == SignalState.UNAVAILABLE and self.authority_refs:
                raise ValueError("unavailable copyright signal cannot contain authority")
            if self.state == SignalState.NO_AUTOMATED_FLAG and not self.authority_refs:
                raise ValueError("copyright no-flag signal requires supplied rights authority")
        elif self.state == SignalState.UNAVAILABLE:
            raise ValueError("only copyright authority can be unavailable")
        return self


class SignalFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: SignalFindingCode
    severity: SignalFindingSeverity


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def signal_evidence_fingerprint(
    *, asset_id: UUID, content_id: UUID, av_evidence_fingerprint: str,
    context_fingerprint: str, prompt_id: str, prompt_version: int,
    policy_version: int, review: HumanReviewResult,
    signals: tuple[ContentSignal, ...], findings: tuple[SignalFinding, ...],
) -> str:
    return _canonical_hash({
        "asset_id": str(asset_id),
        "content_id": str(content_id),
        "av_evidence_fingerprint": av_evidence_fingerprint,
        "review_context_fingerprint": context_fingerprint,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "policy_version": policy_version,
        "review_assessment": review.assessment.model_dump(mode="json"),
        "signals": [signal.model_dump(mode="json") for signal in signals],
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "human_approval_required": True,
        "content_approved": False,
    })


class ContentSignalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    asset_id: UUID
    content_id: UUID
    av_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_id: str = Field(min_length=1, max_length=100)
    prompt_version: int = Field(ge=1, le=100_000)
    policy_version: int = Field(ge=1, le=100_000)
    review: HumanReviewResult
    signals: tuple[ContentSignal, ContentSignal, ContentSignal]
    findings: tuple[SignalFinding, ...] = Field(max_length=9)
    decision: SignalDecision
    human_approval_required: Literal[True] = True
    content_approved: Literal[False] = False
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def envelope_is_canonical(self) -> "ContentSignalReport":
        if self.review.context_fingerprint != self.review_context_fingerprint:
            raise ValueError("review result context fingerprint does not match the report")
        if tuple(signal.domain for signal in self.signals) != tuple(SignalDomain):
            raise ValueError("signals must contain policy, factuality and copyright in order")
        order = {code: index for index, code in enumerate(SignalFindingCode)}
        codes = tuple(finding.code for finding in self.findings)
        if len(codes) != len(set(codes)) or tuple(sorted(codes, key=order.get)) != codes:
            raise ValueError("signal findings must be unique and canonically ordered")
        domain_codes = {
            SignalDomain.POLICY: {
                SignalFindingCode.POLICY_CRITICAL,
                SignalFindingCode.POLICY_REVIEW_REQUIRED,
            },
            SignalDomain.FACTUALITY: {
                SignalFindingCode.FACTUALITY_CRITICAL,
                SignalFindingCode.FACTUALITY_REVIEW_REQUIRED,
            },
            SignalDomain.COPYRIGHT: {
                SignalFindingCode.COPYRIGHT_CRITICAL,
                SignalFindingCode.COPYRIGHT_REVIEW_REQUIRED,
            },
        }
        blocker_codes = {
            SignalFindingCode.POLICY_CRITICAL,
            SignalFindingCode.FACTUALITY_CRITICAL,
            SignalFindingCode.COPYRIGHT_CRITICAL,
            SignalFindingCode.AUTOMATED_REVIEW_BLOCKED,
        }
        for finding in self.findings:
            expected_severity = (
                SignalFindingSeverity.BLOCKER
                if finding.code in blocker_codes else SignalFindingSeverity.REVIEW
            )
            if finding.severity != expected_severity:
                raise ValueError("signal finding severity is not canonical")
        for signal in self.signals:
            domain_count = sum(code in domain_codes[signal.domain] for code in codes)
            if domain_count > 1:
                raise ValueError("signal domain has conflicting findings")
            flagged = domain_count == 1
            expected_state = (
                SignalState.FLAGGED if flagged else
                SignalState.UNAVAILABLE
                if signal.domain == SignalDomain.COPYRIGHT and not signal.authority_refs
                else SignalState.NO_AUTOMATED_FLAG
            )
            if signal.state != expected_state:
                raise ValueError("signal state does not match findings and authority")
        if self.signals[0].authority_refs != (f"policy:{self.policy_version}",):
            raise ValueError("policy signal is not bound to the pinned policy version")
        if self.signals[1].authority_refs:
            raise ValueError("factuality signal cannot invent an authority reference")
        unavailable = SignalFindingCode.COPYRIGHT_AUTHORITY_UNAVAILABLE in codes
        if unavailable != (not self.signals[2].authority_refs):
            raise ValueError("copyright availability does not match findings")
        blocker = any(item.severity == SignalFindingSeverity.BLOCKER for item in self.findings)
        expected_decision = (
            SignalDecision.FAIL if blocker else
            SignalDecision.NEEDS_HUMAN if self.findings else SignalDecision.PASS
        )
        if self.decision != expected_decision:
            raise ValueError("signal decision does not match findings")
        expected = signal_evidence_fingerprint(
            asset_id=self.asset_id, content_id=self.content_id,
            av_evidence_fingerprint=self.av_evidence_fingerprint,
            context_fingerprint=self.review_context_fingerprint,
            prompt_id=self.prompt_id, prompt_version=self.prompt_version,
            policy_version=self.policy_version, review=self.review,
            signals=self.signals, findings=self.findings,
        )
        if self.evidence_fingerprint != expected:
            raise ValueError("signal evidence fingerprint is invalid")
        return self


_CATEGORY_DOMAIN = {
    ReviewCategory.POLICY: SignalDomain.POLICY,
    ReviewCategory.FACTUALITY: SignalDomain.FACTUALITY,
    ReviewCategory.RIGHTS: SignalDomain.COPYRIGHT,
}

_CRITICAL_CODE = {
    SignalDomain.POLICY: SignalFindingCode.POLICY_CRITICAL,
    SignalDomain.FACTUALITY: SignalFindingCode.FACTUALITY_CRITICAL,
    SignalDomain.COPYRIGHT: SignalFindingCode.COPYRIGHT_CRITICAL,
}

_REVIEW_CODE = {
    SignalDomain.POLICY: SignalFindingCode.POLICY_REVIEW_REQUIRED,
    SignalDomain.FACTUALITY: SignalFindingCode.FACTUALITY_REVIEW_REQUIRED,
    SignalDomain.COPYRIGHT: SignalFindingCode.COPYRIGHT_REVIEW_REQUIRED,
}


class PolicySignalService:
    """Derive conservative signals from validated review evidence only."""

    def evaluate(
        self, *, av_report: AvEvaluationReport, context: ReviewContext,
        review: HumanReviewResult, rights_authority_refs: tuple[str, ...] = (),
    ) -> ContentSignalReport:
        if (not isinstance(av_report, AvEvaluationReport)
                or av_report.decision != AvDecision.PASS or av_report.findings
                or not isinstance(context, ReviewContext)
                or not isinstance(review, HumanReviewResult)
                or context.content_id != av_report.content_id
                or not isinstance(rights_authority_refs, tuple)):
            raise ValueError("policy signals require passing AV evidence and validated review context")
        source_ids = {source.evidence.citation_id for source in context.sources}
        context_hash = review_context_fingerprint(context)
        if review.context_fingerprint != context_hash:
            raise ValueError("review result is not bound to the supplied context")
        if any(
            evidence_id not in source_ids
            for finding in review.assessment.findings
            for evidence_id in finding.evidence_ids
        ):
            raise ValueError("review findings reference unknown source evidence")
        policy_ref = (f"policy:{context.policy_version}",)
        grouped = {domain: [] for domain in SignalDomain}
        for finding in review.assessment.findings:
            domain = _CATEGORY_DOMAIN.get(finding.category)
            if domain is not None:
                grouped[domain].append(finding)

        signals: list[ContentSignal] = []
        findings: list[SignalFinding] = []
        for domain in SignalDomain:
            domain_findings = grouped[domain]
            evidence_ids = tuple(dict.fromkeys(
                evidence_id for finding in domain_findings for evidence_id in finding.evidence_ids
            ))
            authority = (
                policy_ref if domain == SignalDomain.POLICY else
                rights_authority_refs if domain == SignalDomain.COPYRIGHT else ()
            )
            if domain_findings:
                state = SignalState.FLAGGED
            elif domain == SignalDomain.COPYRIGHT and not authority:
                state = SignalState.UNAVAILABLE
            else:
                state = SignalState.NO_AUTOMATED_FLAG
            signals.append(ContentSignal(
                domain=domain, state=state, evidence_ids=evidence_ids,
                authority_refs=tuple(authority),
            ))
            if domain_findings:
                critical = any(item.severity == ReviewSeverity.CRITICAL for item in domain_findings)
                findings.append(SignalFinding(
                    code=_CRITICAL_CODE[domain] if critical else _REVIEW_CODE[domain],
                    severity=(SignalFindingSeverity.BLOCKER if critical
                              else SignalFindingSeverity.REVIEW),
                ))
            if domain == SignalDomain.COPYRIGHT and not authority:
                findings.append(SignalFinding(
                    code=SignalFindingCode.COPYRIGHT_AUTHORITY_UNAVAILABLE,
                    severity=SignalFindingSeverity.REVIEW,
                ))

        if review.assessment.disposition == ReviewDisposition.BLOCKED:
            findings.append(SignalFinding(
                code=SignalFindingCode.AUTOMATED_REVIEW_BLOCKED,
                severity=SignalFindingSeverity.BLOCKER,
            ))
        elif review.assessment.disposition == ReviewDisposition.NEEDS_REVISION:
            findings.append(SignalFinding(
                code=SignalFindingCode.AUTOMATED_REVIEW_NEEDS_REVISION,
                severity=SignalFindingSeverity.REVIEW,
            ))
        ordered = tuple(findings)
        decision = (
            SignalDecision.FAIL
            if any(item.severity == SignalFindingSeverity.BLOCKER for item in ordered)
            else SignalDecision.NEEDS_HUMAN if ordered else SignalDecision.PASS
        )
        signal_tuple = tuple(signals)
        fingerprint = signal_evidence_fingerprint(
            asset_id=av_report.asset_id, content_id=av_report.content_id,
            av_evidence_fingerprint=av_report.evidence_fingerprint,
            context_fingerprint=context_hash, prompt_id=context.prompt_id,
            prompt_version=context.prompt_version, policy_version=context.policy_version,
            review=review, signals=signal_tuple, findings=ordered,
        )
        return ContentSignalReport(
            asset_id=av_report.asset_id, content_id=av_report.content_id,
            av_evidence_fingerprint=av_report.evidence_fingerprint,
            review_context_fingerprint=context_hash,
            prompt_id=context.prompt_id, prompt_version=context.prompt_version,
            policy_version=context.policy_version, review=review,
            signals=signal_tuple, findings=ordered, decision=decision,
            evidence_fingerprint=fingerprint,
        )
