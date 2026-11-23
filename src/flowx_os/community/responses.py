"""Human-approved, disabled-by-default official community responses.

Provider transports are injected and untrusted.  An approval authorizes one
exact draft, not a provider call.  A response becomes final only after an
independent official read proves the exact parent, destination and text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import re
import unicodedata
from typing import Protocol
from uuid import UUID

from flowx_os.auth.tokens import Principal, Role
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import ReplyDisposition
from flowx_os.publishing.reconciliation import PublicationPlatform


YOUTUBE_REPLY_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
INSTAGRAM_REPLY_SCOPE = "instagram_business_manage_comments"
FACEBOOK_REPLY_SCOPE = "pages_manage_engagement"
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SAFE_REASON = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]{1,1000}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SECRET_ASSIGNMENT = re.compile(
    r"(?:password|secret|token|credential|api[_-]?key|authorization|cookie)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash(*values: object) -> str:
    return hashlib.sha256("|".join(str(value) for value in values).encode()).hexdigest()


def _safe_human_text(value: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (
        _SAFE_REASON.fullmatch(normalized) is None
        or _SECRET_ASSIGNMENT.search(normalized)
        or any(unicodedata.bidirectional(char) in _BIDI for char in normalized)
    ):
        raise ValueError("response approval reason is invalid")
    return normalized


def required_reply_scopes(platform: PublicationPlatform) -> frozenset[str]:
    if platform is PublicationPlatform.YOUTUBE:
        return frozenset({YOUTUBE_REPLY_SCOPE})
    if platform is PublicationPlatform.INSTAGRAM:
        return frozenset({INSTAGRAM_REPLY_SCOPE})
    if platform is PublicationPlatform.FACEBOOK:
        return frozenset({FACEBOOK_REPLY_SCOPE})
    raise ValueError("response platform is invalid")


class CommunityResponseError(RuntimeError):
    def __init__(self, code: str, message: str, *, ambiguous: bool = False) -> None:
        if _ERROR.fullmatch(code or "") is None:
            raise ValueError("community response error code is invalid")
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(message)


class ApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ResponseState(StrEnum):
    DRAFT = "DRAFT"
    MUTATION_RESERVED = "MUTATION_RESERVED"
    VERIFY_PENDING = "VERIFY_PENDING"
    RESPONDED = "RESPONDED"
    FAILED = "FAILED"


class ProviderMutationState(StrEnum):
    ACCEPTED = "ACCEPTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResponseApprovalRequest:
    approval_id: UUID
    draft_request_id: UUID
    owner_user_id: str
    reviewer_user_id: str
    reviewer_role: Role
    decision: ApprovalDecision
    reason: str
    decided_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        reviewer = self.reviewer_user_id.strip() if isinstance(self.reviewer_user_id, str) else ""
        reason = _safe_human_text(self.reason)
        if (
            not isinstance(self.approval_id, UUID)
            or not isinstance(self.draft_request_id, UUID)
            or _SAFE_OWNER.fullmatch(owner) is None
            or _SAFE_OWNER.fullmatch(reviewer) is None
            or self.reviewer_role not in {Role.ADMIN, Role.REVIEWER}
            or not isinstance(self.decision, ApprovalDecision)
            or not _aware(self.decided_at)
            or not _aware(self.valid_until)
            or not self.decided_at < self.valid_until <= self.decided_at + timedelta(hours=24)
        ):
            raise ValueError("response approval request is invalid")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "reviewer_user_id", reviewer)
        object.__setattr__(self, "reason", reason)

    @property
    def fingerprint(self) -> str:
        return _hash(
            self.approval_id, self.draft_request_id, self.owner_user_id,
            self.reviewer_user_id, self.reviewer_role.value,
            self.decision.value, self.reason,
            _time(self.decided_at), _time(self.valid_until),
        )


@dataclass(frozen=True, slots=True)
class ApprovableDraft:
    draft_request_id: UUID
    owner_user_id: str
    publication_id: UUID
    comment_version_id: UUID
    record_fingerprint: str
    classification_fingerprint: str
    disposition: ReplyDisposition
    draft_text: str | None
    escalation_reasons: tuple[str, ...]
    outbound_action_authorized: bool
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    remote_comment_id: str
    comment_state: CommentState

    def __post_init__(self) -> None:
        text_valid = (
            isinstance(self.draft_text, str)
            and 1 <= len(self.draft_text) <= 500
            and self.draft_text == self.draft_text.strip()
            and not any(
                unicodedata.category(char) == "Cc"
                or unicodedata.bidirectional(char) in _BIDI
                for char in self.draft_text
            )
        )
        if (
            not isinstance(self.draft_request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.comment_version_id, UUID)
            or _HEX64.fullmatch(self.record_fingerprint or "") is None
            or _HEX64.fullmatch(self.classification_fingerprint or "") is None
            or not isinstance(self.disposition, ReplyDisposition)
            or not isinstance(self.escalation_reasons, tuple)
            or type(self.outbound_action_authorized) is not bool
            or not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE.fullmatch(self.destination_id or "") is None
            or _SAFE_REMOTE.fullmatch(self.remote_object_id or "") is None
            or _SAFE_REMOTE.fullmatch(self.remote_comment_id or "") is None
            or not isinstance(self.comment_state, CommentState)
            or (self.disposition is ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL) is not text_valid
        ):
            raise ValueError("approvable reply draft is invalid")

    @property
    def text_fingerprint(self) -> str:
        return _hash(self.draft_text or "")

    @property
    def fingerprint(self) -> str:
        return _hash(
            self.draft_request_id, self.owner_user_id, self.publication_id,
            self.comment_version_id, self.record_fingerprint,
            self.classification_fingerprint, self.disposition.value,
            self.text_fingerprint, ",".join(self.escalation_reasons),
            str(self.outbound_action_authorized).lower(), self.platform.value,
            self.destination_id, self.remote_object_id, self.remote_comment_id,
            self.comment_state.value,
        )


@dataclass(frozen=True, slots=True)
class ResponseApprovalRecord:
    request: ResponseApprovalRequest
    draft_fingerprint: str
    draft_text_fingerprint: str
    record_fingerprint: str

    def __post_init__(self) -> None:
        expected = _hash(
            self.request.fingerprint, self.draft_fingerprint,
            self.draft_text_fingerprint,
        )
        if (
            not isinstance(self.request, ResponseApprovalRequest)
            or _HEX64.fullmatch(self.draft_fingerprint or "") is None
            or _HEX64.fullmatch(self.draft_text_fingerprint or "") is None
            or self.record_fingerprint != expected
        ):
            raise ValueError("response approval record is invalid")


@dataclass(frozen=True, slots=True)
class OfficialResponseRequest:
    request_id: UUID
    approval_id: UUID
    owner_user_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.approval_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not _aware(self.requested_at)
        ):
            raise ValueError("official response request is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(self.request_id, self.approval_id, self.owner_user_id, _time(self.requested_at))


@dataclass(frozen=True, slots=True)
class OfficialResponseClaim:
    request_id: UUID
    approval_id: UUID
    owner_user_id: str
    request_fingerprint: str
    approval_fingerprint: str
    draft_fingerprint: str
    draft_text: str
    draft_text_fingerprint: str
    publication_id: UUID
    comment_version_id: UUID
    platform: PublicationPlatform
    destination_id: str
    credentials_ref: str
    remote_object_id: str
    remote_comment_id: str
    state: ResponseState
    remote_response_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.approval_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or any(_HEX64.fullmatch(value or "") is None for value in (
                self.request_fingerprint, self.approval_fingerprint,
                self.draft_fingerprint, self.draft_text_fingerprint,
            ))
            or not 1 <= len(self.draft_text) <= 500
            or self.draft_text_fingerprint != _hash(self.draft_text)
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.comment_version_id, UUID)
            or not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE.fullmatch(self.destination_id or "") is None
            or not re.fullmatch(r"secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+", self.credentials_ref or "")
            or _SAFE_REMOTE.fullmatch(self.remote_object_id or "") is None
            or _SAFE_REMOTE.fullmatch(self.remote_comment_id or "") is None
            or not isinstance(self.state, ResponseState)
            or (self.remote_response_id is not None and _SAFE_REMOTE.fullmatch(self.remote_response_id) is None)
        ):
            raise ValueError("official response claim is invalid")


@dataclass(frozen=True, slots=True)
class ReplyAuthorization:
    platform: PublicationPlatform
    destination_id: str
    granted_scopes: tuple[str, ...]
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE.fullmatch(self.destination_id or "") is None
            or not self.granted_scopes
            or tuple(sorted(set(self.granted_scopes))) != self.granted_scopes
            or any(_SAFE_SCOPE.fullmatch(value or "") is None for value in self.granted_scopes)
            or not _aware(self.checked_at)
            or not _aware(self.valid_until)
            or self.valid_until <= self.checked_at
        ):
            raise ValueError("reply authorization is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            self.platform.value, self.destination_id, ",".join(self.granted_scopes),
            _time(self.checked_at), _time(self.valid_until),
        )


@dataclass(frozen=True, slots=True)
class ProviderResponseReceipt:
    state: ProviderMutationState
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    parent_remote_comment_id: str
    text_fingerprint: str
    authorization_fingerprint: str
    remote_response_id: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state, ProviderMutationState)
            or not isinstance(self.platform, PublicationPlatform)
            or any(_SAFE_REMOTE.fullmatch(value or "") is None for value in (
                self.destination_id, self.remote_object_id, self.parent_remote_comment_id,
            ))
            or _HEX64.fullmatch(self.text_fingerprint or "") is None
            or _HEX64.fullmatch(self.authorization_fingerprint or "") is None
            or (self.remote_response_id is not None and _SAFE_REMOTE.fullmatch(self.remote_response_id) is None)
            or (self.state is ProviderMutationState.ACCEPTED and self.remote_response_id is None)
        ):
            raise ValueError("provider response receipt is invalid")


@dataclass(frozen=True, slots=True)
class RemoteResponseProof:
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    remote_response_id: str
    parent_remote_comment_id: str
    text_fingerprint: str
    visible: bool
    observed_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.platform, PublicationPlatform)
            or any(_SAFE_REMOTE.fullmatch(value or "") is None for value in (
                self.destination_id, self.remote_object_id, self.remote_response_id,
                self.parent_remote_comment_id, self.evidence_id,
            ))
            or _HEX64.fullmatch(self.text_fingerprint or "") is None
            or type(self.visible) is not bool
            or not _aware(self.observed_at)
        ):
            raise ValueError("remote response proof is invalid")

    @property
    def fingerprint(self) -> str:
        return _hash(
            self.platform.value, self.destination_id, self.remote_object_id,
            self.remote_response_id, self.parent_remote_comment_id,
            self.text_fingerprint, str(self.visible).lower(),
            _time(self.observed_at), self.evidence_id,
        )


@dataclass(frozen=True, slots=True)
class OfficialResponseResult:
    request_id: UUID
    state: ResponseState
    remote_response_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommunityResponsePolicy:
    enabled: bool = False
    maximum_authorization_age_seconds: int = 300

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or not 30 <= self.maximum_authorization_age_seconds <= 300:
            raise ValueError("community response policy is invalid")


class CommunityResponseStore(Protocol):
    async def load_approvable_draft(self, request: ResponseApprovalRequest) -> ApprovableDraft: ...
    async def save_approval(
        self, request: ResponseApprovalRequest, draft: ApprovableDraft,
        record: ResponseApprovalRecord,
    ) -> ResponseApprovalRecord: ...
    async def claim(self, request: OfficialResponseRequest) -> OfficialResponseClaim: ...
    async def assert_network_ready(self, claim: OfficialResponseClaim) -> None: ...
    async def reserve_mutation(
        self, claim: OfficialResponseClaim, authorization: ReplyAuthorization,
    ) -> OfficialResponseClaim: ...
    async def refresh_mutation_authorization(
        self, claim: OfficialResponseClaim, authorization: ReplyAuthorization,
    ) -> OfficialResponseClaim: ...
    async def record_receipt(
        self, claim: OfficialResponseClaim, receipt: ProviderResponseReceipt,
    ) -> OfficialResponseClaim: ...
    async def record_transport_failure(
        self, claim: OfficialResponseClaim, error: CommunityResponseError,
    ) -> None: ...
    async def record_verification(
        self, claim: OfficialResponseClaim, proof: RemoteResponseProof,
    ) -> OfficialResponseResult: ...
    async def recover_response_identity(
        self, request: OfficialResponseRequest, remote_response_id: str,
        recovery_evidence_id: str,
    ) -> OfficialResponseClaim: ...


class OfficialResponseTransport(Protocol):
    async def check_authorization(
        self, *, credentials_ref: str, platform: PublicationPlatform,
        destination_id: str,
    ) -> ReplyAuthorization: ...
    async def create_response(
        self, *, credentials_ref: str, platform: PublicationPlatform,
        destination_id: str, remote_object_id: str, parent_remote_comment_id: str,
        text: str, idempotency_fingerprint: str,
        authorization_fingerprint: str,
    ) -> ProviderResponseReceipt: ...
    async def get_response(
        self, *, credentials_ref: str, platform: PublicationPlatform,
        destination_id: str, remote_object_id: str, remote_response_id: str,
    ) -> RemoteResponseProof: ...


class CommunityResponseService:
    def __init__(
        self, *, store: CommunityResponseStore,
        transport: OfficialResponseTransport,
        policy: CommunityResponsePolicy | None = None,
    ) -> None:
        self._store = store
        self._transport = transport
        self._policy = policy or CommunityResponsePolicy()

    async def decide(
        self, request: ResponseApprovalRequest, principal: Principal, *, now: datetime,
    ) -> ResponseApprovalRecord:
        if (
            not isinstance(request, ResponseApprovalRequest)
            or not isinstance(principal, Principal)
            or not _aware(now)
        ):
            raise ValueError("response approval invocation is invalid")
        if request.decided_at > now or request.valid_until <= now:
            raise CommunityResponseError("APPROVAL_TIME_INVALID", "approval decision time is invalid")
        if (
            principal.subject != request.reviewer_user_id
            or request.reviewer_role not in principal.roles
            or request.reviewer_role not in {Role.REVIEWER, Role.ADMIN}
        ):
            raise CommunityResponseError("REVIEWER_NOT_AUTHORIZED", "reviewer authorization is required")
        draft = await self._store.load_approvable_draft(request)
        if (
            not isinstance(draft, ApprovableDraft)
            or draft.draft_request_id != request.draft_request_id
            or draft.owner_user_id != request.owner_user_id
        ):
            raise CommunityResponseError("DRAFT_IDENTITY_MISMATCH", "reply draft identity changed")
        if request.decision is ApprovalDecision.APPROVE and (
            draft.disposition is not ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL
            or draft.draft_text is None
            or draft.escalation_reasons
            or draft.outbound_action_authorized
            or draft.comment_state is CommentState.DELETED
        ):
            raise CommunityResponseError("DRAFT_NOT_APPROVABLE", "reply draft cannot be approved")
        record = ResponseApprovalRecord(
            request=request,
            draft_fingerprint=draft.fingerprint,
            draft_text_fingerprint=draft.text_fingerprint,
            record_fingerprint=_hash(request.fingerprint, draft.fingerprint, draft.text_fingerprint),
        )
        stored = await self._store.save_approval(request, draft, record)
        if stored != record:
            raise CommunityResponseError("APPROVAL_REPLAY_CONFLICT", "stored approval differs from exact decision")
        return stored

    async def respond(
        self, request: OfficialResponseRequest, *, now: datetime,
    ) -> OfficialResponseResult:
        if not isinstance(request, OfficialResponseRequest) or not _aware(now):
            raise ValueError("official response invocation is invalid")
        if not self._policy.enabled:
            raise CommunityResponseError("RESPONSES_DISABLED", "official responses are disabled")
        if now < request.requested_at:
            raise CommunityResponseError("REQUEST_FROM_FUTURE", "official response request is in the future")
        claim = await self._store.claim(request)
        self._require_claim_request(claim, request)
        if claim.state is ResponseState.RESPONDED:
            return OfficialResponseResult(claim.request_id, claim.state, claim.remote_response_id)
        if claim.state is ResponseState.FAILED:
            raise CommunityResponseError("RESPONSE_TERMINAL", "official response is terminal")

        if claim.state in {ResponseState.MUTATION_RESERVED, ResponseState.VERIFY_PENDING}:
            if claim.remote_response_id is None:
                raise CommunityResponseError(
                    "RESPONSE_OUTCOME_UNKNOWN",
                    "official response outcome requires read-only reconciliation",
                    ambiguous=True,
                )
        await self._store.assert_network_ready(claim)
        authorization = await self._authorization(claim, now)
        if claim.remote_response_id is not None:
            return await self._verify(claim, now=now)
        prior_claim = claim
        claim = await self._store.reserve_mutation(claim, authorization)
        self._require_claim_transition(prior_claim, claim, ResponseState.MUTATION_RESERVED)
        rechecked_authorization = await self._authorization(claim, now)
        claim_after_recheck = await self._store.refresh_mutation_authorization(
            claim, rechecked_authorization,
        )
        self._require_claim_transition(
            claim, claim_after_recheck, ResponseState.MUTATION_RESERVED,
        )
        claim = claim_after_recheck
        await self._store.assert_network_ready(claim)
        try:
            receipt = await self._transport.create_response(
                credentials_ref=claim.credentials_ref, platform=claim.platform,
                destination_id=claim.destination_id,
                remote_object_id=claim.remote_object_id,
                parent_remote_comment_id=claim.remote_comment_id,
                text=claim.draft_text,
                idempotency_fingerprint=claim.request_fingerprint,
                authorization_fingerprint=rechecked_authorization.fingerprint,
            )
        except CommunityResponseError as exc:
            await self._store.record_transport_failure(claim, exc)
            raise
        except Exception as exc:
            error = CommunityResponseError(
                "TRANSPORT_OUTCOME_UNKNOWN",
                "official response outcome requires read-only reconciliation",
                ambiguous=True,
            )
            await self._store.record_transport_failure(claim, error)
            raise error from exc
        try:
            self._require_receipt(claim, rechecked_authorization, receipt)
        except CommunityResponseError as exc:
            await self._store.record_transport_failure(claim, exc)
            raise
        prior_claim = claim
        claim = await self._store.record_receipt(claim, receipt)
        self._require_claim_transition(
            prior_claim, claim, ResponseState.VERIFY_PENDING,
            remote_response_id=receipt.remote_response_id,
        )
        if receipt.remote_response_id is None:
            return OfficialResponseResult(claim.request_id, ResponseState.VERIFY_PENDING)
        return await self._verify(claim, now=now)

    async def reconcile(
        self, request: OfficialResponseRequest, *, now: datetime,
    ) -> OfficialResponseResult:
        return await self.respond(request, now=now)

    async def recover_identity(
        self, request: OfficialResponseRequest, remote_response_id: str,
        recovery_evidence_id: str,
    ) -> OfficialResponseClaim:
        if (
            not isinstance(request, OfficialResponseRequest)
            or _SAFE_REMOTE.fullmatch(remote_response_id or "") is None
            or _SAFE_REMOTE.fullmatch(recovery_evidence_id or "") is None
        ):
            raise ValueError("official response recovery is invalid")
        claim = await self._store.recover_response_identity(
            request, remote_response_id, recovery_evidence_id,
        )
        self._require_claim_request(claim, request)
        if claim.state is not ResponseState.VERIFY_PENDING or claim.remote_response_id != remote_response_id:
            raise CommunityResponseError("RECOVERY_RESULT_INVALID", "recovered response identity is invalid")
        return claim

    async def _authorization(self, claim: OfficialResponseClaim, now: datetime) -> ReplyAuthorization:
        try:
            authorization = await self._transport.check_authorization(
                credentials_ref=claim.credentials_ref, platform=claim.platform,
                destination_id=claim.destination_id,
            )
        except CommunityResponseError:
            raise
        except Exception as exc:
            raise CommunityResponseError("AUTHORIZATION_UNAVAILABLE", "reply authorization is unavailable") from exc
        if (
            not isinstance(authorization, ReplyAuthorization)
            or
            authorization.platform is not claim.platform
            or authorization.destination_id != claim.destination_id
            or not required_reply_scopes(claim.platform).issubset(authorization.granted_scopes)
            or authorization.checked_at > now
            or authorization.valid_until <= now
            or authorization.valid_until < now + timedelta(seconds=30)
            or now - authorization.checked_at > timedelta(seconds=self._policy.maximum_authorization_age_seconds)
        ):
            raise CommunityResponseError("AUTHORIZATION_INVALID", "current official reply authorization is invalid")
        return authorization

    @staticmethod
    def _require_receipt(
        claim: OfficialResponseClaim, authorization: ReplyAuthorization,
        receipt: ProviderResponseReceipt,
    ) -> None:
        if (
            not isinstance(receipt, ProviderResponseReceipt)
            or
            receipt.platform is not claim.platform
            or receipt.destination_id != claim.destination_id
            or receipt.remote_object_id != claim.remote_object_id
            or receipt.parent_remote_comment_id != claim.remote_comment_id
            or receipt.text_fingerprint != claim.draft_text_fingerprint
            or receipt.authorization_fingerprint != authorization.fingerprint
        ):
            raise CommunityResponseError("REMOTE_RESPONSE_INVALID", "official response receipt is invalid", ambiguous=True)

    async def _verify(
        self, claim: OfficialResponseClaim, *, now: datetime,
    ) -> OfficialResponseResult:
        if claim.remote_response_id is None:
            raise CommunityResponseError("REMOTE_IDENTITY_UNKNOWN", "remote response identity is unknown", ambiguous=True)
        await self._store.assert_network_ready(claim)
        try:
            proof = await self._transport.get_response(
                credentials_ref=claim.credentials_ref, platform=claim.platform,
                destination_id=claim.destination_id,
                remote_object_id=claim.remote_object_id,
                remote_response_id=claim.remote_response_id,
            )
        except CommunityResponseError:
            raise
        except Exception as exc:
            raise CommunityResponseError("VERIFICATION_UNAVAILABLE", "official response verification is unavailable") from exc
        if (
            not isinstance(proof, RemoteResponseProof)
            or
            proof.platform is not claim.platform
            or proof.destination_id != claim.destination_id
            or proof.remote_object_id != claim.remote_object_id
            or proof.remote_response_id != claim.remote_response_id
            or proof.parent_remote_comment_id != claim.remote_comment_id
            or proof.text_fingerprint != claim.draft_text_fingerprint
            or not proof.visible
            or proof.observed_at > now
        ):
            raise CommunityResponseError("REMOTE_PROOF_INVALID", "official response is not independently proven")
        result = await self._store.record_verification(claim, proof)
        if (
            not isinstance(result, OfficialResponseResult)
            or result.request_id != claim.request_id
            or result.state is not ResponseState.RESPONDED
            or result.remote_response_id != claim.remote_response_id
        ):
            raise CommunityResponseError("VERIFICATION_RESULT_INVALID", "stored response proof result is invalid")
        return result

    @staticmethod
    def _require_claim_request(
        claim: OfficialResponseClaim, request: OfficialResponseRequest,
    ) -> None:
        if (
            not isinstance(claim, OfficialResponseClaim)
            or claim.request_id != request.request_id
            or claim.approval_id != request.approval_id
            or claim.owner_user_id != request.owner_user_id
            or claim.request_fingerprint != request.fingerprint
        ):
            raise CommunityResponseError("REQUEST_CONFLICT", "official response request conflicts with stored work")

    @staticmethod
    def _require_claim_transition(
        before: OfficialResponseClaim, after: OfficialResponseClaim,
        expected_state: ResponseState, *, remote_response_id: str | None = None,
    ) -> None:
        if (
            not isinstance(after, OfficialResponseClaim)
            or replace_claim_state(before, expected_state, remote_response_id) != after
        ):
            raise CommunityResponseError("STORED_CLAIM_INVALID", "stored official response claim changed identity")


def replace_claim_state(
    claim: OfficialResponseClaim, state: ResponseState,
    remote_response_id: str | None,
) -> OfficialResponseClaim:
    """Build the only accepted store transition without importing dataclasses.replace."""
    return OfficialResponseClaim(
        request_id=claim.request_id, approval_id=claim.approval_id,
        owner_user_id=claim.owner_user_id,
        request_fingerprint=claim.request_fingerprint,
        approval_fingerprint=claim.approval_fingerprint,
        draft_fingerprint=claim.draft_fingerprint, draft_text=claim.draft_text,
        draft_text_fingerprint=claim.draft_text_fingerprint,
        publication_id=claim.publication_id,
        comment_version_id=claim.comment_version_id, platform=claim.platform,
        destination_id=claim.destination_id, credentials_ref=claim.credentials_ref,
        remote_object_id=claim.remote_object_id,
        remote_comment_id=claim.remote_comment_id, state=state,
        remote_response_id=remote_response_id,
    )
