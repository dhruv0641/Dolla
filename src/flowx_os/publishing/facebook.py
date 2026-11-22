"""Disabled-by-default official Facebook Page Reels publishing boundary.

No OAuth flow, token resolver, or HTTP client lives here. Deployments inject a
transport backed by Meta's official Page Reels API. Upload initialization,
binary transfer, and publish finalization are separately fenced because each
remote mutation can succeed even when its response is lost.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Protocol
import unicodedata
from uuid import UUID


FACEBOOK_PAGES_SHOW_LIST_SCOPE = "pages_show_list"
FACEBOOK_PAGES_READ_ENGAGEMENT_SCOPE = "pages_read_engagement"
FACEBOOK_PAGES_MANAGE_POSTS_SCOPE = "pages_manage_posts"
FACEBOOK_CREATE_CONTENT_TASK = "CREATE_CONTENT"
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_PAGE_ID = re.compile(r"^[0-9]{1,50}$")
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_PERMALINK = re.compile(r"^https://(?:www\.)?facebook\.com/[A-Za-z0-9._/-]+(?:\?[A-Za-z0-9_=&.-]+)?$")
_BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


class FacebookVideoState(StrEnum):
    UPLOADING = "uploading"
    UPLOAD_COMPLETE = "upload_complete"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    EXPIRED = "expired"
    UPLOAD_FAILED = "upload_failed"


class FacebookError(RuntimeError):
    """Stable, operator-safe Facebook publishing failure."""

    def __init__(self, code: str, message: str, *, ambiguous: bool = False) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("Facebook error code is invalid")
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(message)


def _safe_text(value: str, *, maximum: int, label: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (len(normalized) > maximum
            or any(unicodedata.category(char) == "Cc"
                   or unicodedata.bidirectional(char) in _BIDI for char in normalized)):
        raise ValueError(f"Facebook {label} is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class FacebookPublishRequest:
    request_id: UUID
    publication_id: UUID
    brand_id: UUID
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    owner_user_id: str
    artifact_version: int
    title: str = ""
    description: str = ""
    is_ai_generated: bool = True

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.request_id, self.publication_id, self.brand_id,
                self.content_id, self.channel_id, self.asset_id))
                or type(self.artifact_version) is not int
                or not 1 <= self.artifact_version <= 1_000_000
                or type(self.is_ai_generated) is not bool):
            raise ValueError("Facebook publication identity is invalid")
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        if _SAFE_OWNER.fullmatch(owner) is None:
            raise ValueError("Facebook publication owner is invalid")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "title", _safe_text(self.title, maximum=255, label="title"))
        object.__setattr__(
            self, "description", _safe_text(self.description, maximum=5_000, label="description"),
        )

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id), str(self.publication_id), str(self.brand_id),
            str(self.content_id), str(self.channel_id), str(self.asset_id),
            self.owner_user_id, str(self.artifact_version), self.title,
            self.description, "true" if self.is_ai_generated else "false",
            "PUBLIC", "FACEBOOK_REELS_V1",
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "title": self.title,
            "description": self.description,
            "video_state": "PUBLISHED",
            "is_ai_generated": self.is_ai_generated,
        }


@dataclass(frozen=True, slots=True)
class FacebookAuthorization:
    page_id: str
    granted_scopes: tuple[str, ...]
    granted_tasks: tuple[str, ...]
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (_SAFE_PAGE_ID.fullmatch(self.page_id or "") is None
                or not self.granted_scopes or not self.granted_tasks
                or len(self.granted_scopes) != len(set(self.granted_scopes))
                or len(self.granted_tasks) != len(set(self.granted_tasks))
                or any(not isinstance(value, str) or not value
                       for value in self.granted_scopes + self.granted_tasks)
                or not all(isinstance(value, datetime) and value.tzinfo is not None
                           for value in (self.checked_at, self.valid_until))
                or self.valid_until <= self.checked_at):
            raise ValueError("Facebook authorization evidence is invalid")


@dataclass(frozen=True, slots=True)
class FacebookUploadSession:
    video_id: str
    upload_session_ref: str

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.video_id or "") is None
                or _SECRET_REF.fullmatch(self.upload_session_ref or "") is None):
            raise ValueError("Facebook upload session evidence is invalid")


@dataclass(frozen=True, slots=True)
class FacebookUploadReceipt:
    video_id: str
    accepted: bool

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.video_id or "") is None
                or self.accepted is not True):
            raise ValueError("Facebook upload receipt is invalid")


@dataclass(frozen=True, slots=True)
class FacebookVideoStatus:
    video_id: str
    page_id: str
    state: FacebookVideoState
    uploading_status: str
    processing_status: str
    publishing_status: str
    publish_status: str
    bytes_transferred: int
    source_file_size: int

    def __post_init__(self) -> None:
        phase_states = {"completed", "error", "not_started", "in_progress"}
        if (_SAFE_REMOTE_ID.fullmatch(self.video_id or "") is None
                or _SAFE_PAGE_ID.fullmatch(self.page_id or "") is None
                or not isinstance(self.state, FacebookVideoState)
                or self.uploading_status not in phase_states
                or self.processing_status not in phase_states
                or self.publishing_status not in phase_states
                or self.publish_status not in {
                    "draft", "error", "not_started", "published", "scheduled",
                }
                or type(self.bytes_transferred) is not int or self.bytes_transferred < 0
                or type(self.source_file_size) is not int or self.source_file_size < 0
                or self.bytes_transferred > self.source_file_size):
            raise ValueError("Facebook video status evidence is invalid")


@dataclass(frozen=True, slots=True)
class FacebookPublishReceipt:
    video_id: str
    success: bool
    post_id: str | None = None

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.video_id or "") is None
                or self.success is not True
                or (self.post_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.post_id) is None)):
            raise ValueError("Facebook publish receipt is invalid")


@dataclass(frozen=True, slots=True)
class FacebookRemoteReel:
    video_id: str
    page_id: str
    post_id: str
    permalink: str
    published: bool

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.video_id or "") is None
                or _SAFE_PAGE_ID.fullmatch(self.page_id or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.post_id or "") is None
                or _PERMALINK.fullmatch(self.permalink or "") is None
                or self.published is not True):
            raise ValueError("Facebook remote Reel evidence is invalid")


@dataclass(frozen=True, slots=True)
class FacebookPublicationClaim:
    publication_id: UUID
    request_fingerprint: str
    brand_id: UUID
    owner_user_id: str
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    approval_decision_id: UUID
    artifact_version: int
    page_id: str
    credentials_ref: str
    destination_fingerprint: str
    asset_storage_uri: str
    asset_sha256_hex: str
    asset_size_bytes: int
    asset_mime_type: str
    status: str
    phase: str
    verification_attempt_count: int = 0
    remote_video_id: str | None = None
    upload_session_ref: str | None = None
    remote_post_id: str | None = None
    remote_url: str | None = None

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.publication_id, self.brand_id, self.content_id, self.channel_id,
                self.asset_id, self.approval_decision_id))
                or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
                or re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint or "") is None
                or _SAFE_PAGE_ID.fullmatch(self.page_id or "") is None
                or _SECRET_REF.fullmatch(self.credentials_ref or "") is None
                or self.destination_fingerprint != hashlib.sha256(
                    f"{self.page_id}|{self.credentials_ref}".encode("utf-8")
                ).hexdigest()
                or self.asset_storage_uri != f"managed://assets/{self.asset_id.hex}/payload"
                or re.fullmatch(r"[0-9a-f]{64}", self.asset_sha256_hex or "") is None
                or type(self.asset_size_bytes) is not int or self.asset_size_bytes <= 0
                or self.asset_mime_type != "video/mp4"
                or self.status not in {
                    "DRAFT", "UPLOAD_STARTED", "PROCESSING", "PUBLISH_REQUESTED",
                    "VERIFY_PENDING", "PUBLISHED", "FAILED", "CANCELLED",
                }
                or self.phase not in {
                    "CLAIMED", "START_RESERVED", "SESSION_CREATED", "UPLOAD_RESERVED",
                    "UPLOAD_ACCEPTED", "VIDEO_PROCESSING", "VIDEO_READY",
                    "PUBLISH_RESERVED", "PUBLISH_ACCEPTED", "VERIFIED", "FAILED", "CANCELLED",
                }
                or type(self.verification_attempt_count) is not int
                or not 0 <= self.verification_attempt_count <= 1_000
                or (self.remote_video_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_video_id) is None)
                or (self.upload_session_ref is not None
                    and _SECRET_REF.fullmatch(self.upload_session_ref) is None)
                or (self.remote_post_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_post_id) is None)
                or (self.remote_url is not None
                    and _PERMALINK.fullmatch(self.remote_url) is None)):
            raise ValueError("Facebook publication claim is invalid")


@dataclass(frozen=True, slots=True)
class FacebookPolicy:
    enabled: bool = False
    maximum_asset_bytes: int = 300_000_000
    maximum_authorization_age_seconds: int = 300
    maximum_verification_attempts: int = 8

    def __post_init__(self) -> None:
        if (type(self.enabled) is not bool
                or type(self.maximum_asset_bytes) is not int
                or not 1_024 <= self.maximum_asset_bytes <= 300_000_000
                or type(self.maximum_authorization_age_seconds) is not int
                or not 30 <= self.maximum_authorization_age_seconds <= 3_600
                or type(self.maximum_verification_attempts) is not int
                or not 1 <= self.maximum_verification_attempts <= 100):
            raise ValueError("Facebook publishing policy is invalid")


@dataclass(frozen=True, slots=True)
class FacebookPublicationResult:
    publication_id: UUID
    status: str
    remote_video_id: str | None = None
    remote_url: str | None = None


class FacebookTransport(Protocol):
    async def check_authorization(
        self, *, credentials_ref: str, expected_page_id: str,
    ) -> FacebookAuthorization: ...

    async def start_reel_upload(
        self, *, credentials_ref: str, expected_page_id: str,
        idempotency_fingerprint: str,
    ) -> FacebookUploadSession: ...

    async def upload_reel(
        self, *, credentials_ref: str, upload_session_ref: str,
        source_path: Path, content_length: int, sha256_hex: str,
    ) -> FacebookUploadReceipt: ...

    async def get_video_status(
        self, *, credentials_ref: str, video_id: str,
    ) -> FacebookVideoStatus: ...

    async def finish_reel(
        self, *, credentials_ref: str, expected_page_id: str,
        video_id: str, metadata: dict[str, object],
    ) -> FacebookPublishReceipt: ...

    async def get_reel(
        self, *, credentials_ref: str, expected_page_id: str, video_id: str,
    ) -> FacebookRemoteReel: ...


class FacebookPublicationStore(Protocol):
    async def claim(self, request: FacebookPublishRequest) -> FacebookPublicationClaim: ...
    async def assert_network_ready(self, claim: FacebookPublicationClaim) -> None: ...
    async def reserve_start(self, claim: FacebookPublicationClaim) -> FacebookPublicationClaim: ...
    async def record_session(
        self, *, claim: FacebookPublicationClaim, session: FacebookUploadSession,
    ) -> FacebookPublicationClaim: ...
    async def reserve_upload(self, claim: FacebookPublicationClaim) -> FacebookPublicationClaim: ...
    async def record_upload(
        self, *, claim: FacebookPublicationClaim, receipt: FacebookUploadReceipt,
    ) -> FacebookPublicationClaim: ...
    async def record_video_status(
        self, *, claim: FacebookPublicationClaim, remote: FacebookVideoStatus,
    ) -> FacebookPublicationClaim: ...
    async def reserve_publish(self, claim: FacebookPublicationClaim) -> FacebookPublicationClaim: ...
    async def record_publish(
        self, *, claim: FacebookPublicationClaim, receipt: FacebookPublishReceipt,
    ) -> FacebookPublicationClaim: ...
    async def record_transport_failure(
        self, *, claim: FacebookPublicationClaim, error: FacebookError,
    ) -> None: ...
    async def record_verification(
        self, *, claim: FacebookPublicationClaim, status: FacebookVideoStatus,
        remote: FacebookRemoteReel,
    ) -> FacebookPublicationResult: ...
    async def recover_session(
        self, *, request: FacebookPublishRequest, session: FacebookUploadSession,
    ) -> FacebookPublicationClaim: ...
    async def recover_upload(
        self, *, request: FacebookPublishRequest, status: FacebookVideoStatus,
    ) -> FacebookPublicationClaim: ...
    async def recover_publish(
        self, *, request: FacebookPublishRequest, receipt: FacebookPublishReceipt,
    ) -> FacebookPublicationClaim: ...
    async def cancel_unknown(
        self, *, request: FacebookPublishRequest, reason: str,
    ) -> FacebookPublicationResult: ...


class FacebookPublisher:
    """Advance at most one Facebook remote mutation per call."""

    def __init__(
        self, *, storage_root: Path, store: FacebookPublicationStore,
        transport: FacebookTransport, policy: FacebookPolicy | None = None,
    ) -> None:
        self._root = Path(storage_root).expanduser().resolve() / "assets"
        self._store = store
        self._transport = transport
        self._policy = policy or FacebookPolicy()

    async def publish(self, request: FacebookPublishRequest) -> FacebookPublicationResult:
        if not isinstance(request, FacebookPublishRequest):
            raise ValueError("Facebook publication request is required")
        if not self._policy.enabled:
            raise FacebookError("PUBLISHING_DISABLED", "Facebook publishing is disabled")
        claim = await self._store.claim(request)
        if claim.request_fingerprint != request.fingerprint:
            raise FacebookError("REQUEST_CONFLICT", "Facebook request conflicts with stored work")
        if claim.status == "PUBLISHED":
            return FacebookPublicationResult(
                claim.publication_id, "PUBLISHED", claim.remote_video_id, claim.remote_url,
            )
        if claim.status in {"FAILED", "CANCELLED"}:
            raise FacebookError("PUBLICATION_TERMINAL", "Facebook publication is terminal")
        if claim.phase in {"START_RESERVED", "UPLOAD_RESERVED", "PUBLISH_RESERVED"}:
            raise FacebookError(
                "PUBLICATION_OUTCOME_UNKNOWN",
                "Facebook mutation outcome requires operator reconciliation",
                ambiguous=True,
            )

        await self._authorize(claim)
        if claim.phase == "CLAIMED":
            await asyncio.to_thread(self._verify_asset, claim, None)
            claim = await self._store.reserve_start(claim)
            await self._authorize(claim)
            try:
                session = await self._transport.start_reel_upload(
                    credentials_ref=claim.credentials_ref,
                    expected_page_id=claim.page_id,
                    idempotency_fingerprint=claim.request_fingerprint,
                )
                claim = await self._store.record_session(claim=claim, session=session)
            except Exception as exc:
                return await self._transport_unknown(claim, "START_OUTCOME_UNKNOWN", exc)
            return FacebookPublicationResult(claim.publication_id, "UPLOAD_STARTED", claim.remote_video_id)

        if claim.phase == "SESSION_CREATED":
            claim = await self._store.reserve_upload(claim)
            await self._authorize(claim)
            try:
                with tempfile.TemporaryDirectory(prefix="flowx-facebook-") as directory:
                    snapshot = Path(directory) / "upload.mp4"
                    await asyncio.to_thread(self._verify_asset, claim, snapshot)
                    # Snapshotting can be long-running. Recheck both provider and
                    # owner-scoped Page evidence immediately before transfer.
                    await self._authorize(claim)
                    receipt = await self._transport.upload_reel(
                        credentials_ref=claim.credentials_ref,
                        upload_session_ref=claim.upload_session_ref or "",
                        source_path=snapshot,
                        content_length=claim.asset_size_bytes,
                        sha256_hex=claim.asset_sha256_hex,
                    )
                if receipt.video_id != claim.remote_video_id:
                    raise FacebookError("REMOTE_IDENTITY_MISMATCH", "Facebook upload identity is invalid")
                claim = await self._store.record_upload(claim=claim, receipt=receipt)
            except Exception as exc:
                return await self._transport_unknown(claim, "UPLOAD_OUTCOME_UNKNOWN", exc)
            return FacebookPublicationResult(claim.publication_id, "PROCESSING", claim.remote_video_id)

        if claim.remote_video_id is None:
            raise FacebookError(
                "PUBLICATION_OUTCOME_UNKNOWN", "Facebook video identity requires reconciliation",
                ambiguous=True,
            )
        if claim.phase == "PUBLISH_ACCEPTED":
            return await self._verify_safely(claim)

        remote = await self._status_safely(claim)
        if remote.publish_status == "published":
            error = FacebookError(
                "PUBLISH_RECEIPT_UNKNOWN",
                "published Facebook Reel requires publish recovery evidence",
                ambiguous=True,
            )
            await self._store.record_transport_failure(claim=claim, error=error)
            raise error
        claim = await self._store.record_video_status(claim=claim, remote=remote)
        if (remote.state in {FacebookVideoState.ERROR, FacebookVideoState.EXPIRED,
                             FacebookVideoState.UPLOAD_FAILED}
                or remote.publish_status == "error"):
            return FacebookPublicationResult(claim.publication_id, "FAILED", claim.remote_video_id)
        if remote.state != FacebookVideoState.READY:
            return FacebookPublicationResult(claim.publication_id, "PROCESSING", claim.remote_video_id)
        claim = await self._store.reserve_publish(claim)
        await self._authorize(claim)
        try:
            receipt = await self._transport.finish_reel(
                credentials_ref=claim.credentials_ref,
                expected_page_id=claim.page_id,
                video_id=claim.remote_video_id,
                metadata=request.metadata,
            )
            if receipt.video_id != claim.remote_video_id:
                raise FacebookError("REMOTE_IDENTITY_MISMATCH", "Facebook publish identity is invalid")
            claim = await self._store.record_publish(claim=claim, receipt=receipt)
        except Exception as exc:
            return await self._transport_unknown(claim, "PUBLISH_OUTCOME_UNKNOWN", exc)
        return FacebookPublicationResult(claim.publication_id, "VERIFY_PENDING", claim.remote_video_id)

    async def reconcile(self, request: FacebookPublishRequest) -> FacebookPublicationResult:
        return await self.publish(request)

    async def recover_session(
        self, *, request: FacebookPublishRequest, session: FacebookUploadSession,
    ) -> FacebookPublicationClaim:
        if not isinstance(request, FacebookPublishRequest) or not isinstance(session, FacebookUploadSession):
            raise ValueError("Facebook session recovery is invalid")
        return await self._store.recover_session(request=request, session=session)

    async def recover_upload(
        self, *, request: FacebookPublishRequest, status: FacebookVideoStatus,
    ) -> FacebookPublicationClaim:
        if not isinstance(request, FacebookPublishRequest) or not isinstance(status, FacebookVideoStatus):
            raise ValueError("Facebook upload recovery is invalid")
        return await self._store.recover_upload(request=request, status=status)

    async def recover_publish(
        self, *, request: FacebookPublishRequest, receipt: FacebookPublishReceipt,
    ) -> FacebookPublicationClaim:
        if not isinstance(request, FacebookPublishRequest) or not isinstance(receipt, FacebookPublishReceipt):
            raise ValueError("Facebook publish recovery is invalid")
        return await self._store.recover_publish(request=request, receipt=receipt)

    async def cancel_unknown(
        self, *, request: FacebookPublishRequest, reason: str,
    ) -> FacebookPublicationResult:
        if not isinstance(request, FacebookPublishRequest):
            raise ValueError("Facebook cancellation is invalid")
        return await self._store.cancel_unknown(request=request, reason=reason)

    async def _authorize(self, claim: FacebookPublicationClaim) -> None:
        await self._store.assert_network_ready(claim)
        try:
            authorization = await self._transport.check_authorization(
                credentials_ref=claim.credentials_ref, expected_page_id=claim.page_id,
            )
        except FacebookError:
            raise
        except Exception as exc:
            raise FacebookError(
                "AUTHORIZATION_UNAVAILABLE", "Facebook authorization check is unavailable",
            ) from exc
        now = datetime.now(timezone.utc)
        required_scopes = {
            FACEBOOK_PAGES_SHOW_LIST_SCOPE,
            FACEBOOK_PAGES_READ_ENGAGEMENT_SCOPE,
            FACEBOOK_PAGES_MANAGE_POSTS_SCOPE,
        }
        if (authorization.page_id != claim.page_id
                or not required_scopes.issubset(authorization.granted_scopes)
                or FACEBOOK_CREATE_CONTENT_TASK not in authorization.granted_tasks
                or authorization.checked_at > now + timedelta(seconds=30)
                or now - authorization.checked_at > timedelta(
                    seconds=self._policy.maximum_authorization_age_seconds,
                )
                or authorization.valid_until <= now):
            raise FacebookError("AUTHORIZATION_INVALID", "Facebook authorization is not ready")
        await self._store.assert_network_ready(claim)

    async def _status_safely(self, claim: FacebookPublicationClaim) -> FacebookVideoStatus:
        if claim.verification_attempt_count >= self._policy.maximum_verification_attempts:
            raise FacebookError(
                "VERIFY_LIMIT_REACHED", "Facebook verification limit requires operator review",
            )
        await self._authorize(claim)
        try:
            remote = await self._transport.get_video_status(
                credentials_ref=claim.credentials_ref, video_id=claim.remote_video_id or "",
            )
        except FacebookError:
            raise
        except Exception as exc:
            raise FacebookError(
                "VERIFY_OUTCOME_UNKNOWN", "Facebook video status is unavailable", ambiguous=True,
            ) from exc
        if (remote.video_id != claim.remote_video_id or remote.page_id != claim.page_id
                or remote.source_file_size != claim.asset_size_bytes):
            raise FacebookError("REMOTE_IDENTITY_MISMATCH", "Facebook video evidence is invalid")
        if remote.uploading_status == "completed" and remote.bytes_transferred != claim.asset_size_bytes:
            raise FacebookError("REMOTE_BYTES_MISMATCH", "Facebook uploaded bytes are invalid")
        return remote

    async def _verify_safely(self, claim: FacebookPublicationClaim) -> FacebookPublicationResult:
        try:
            status = await self._status_safely(claim)
            claim = await self._store.record_video_status(claim=claim, remote=status)
            if (status.state in {
                FacebookVideoState.ERROR,
                FacebookVideoState.EXPIRED,
                FacebookVideoState.UPLOAD_FAILED,
            } or status.publish_status == "error"):
                return FacebookPublicationResult(
                    claim.publication_id, "FAILED", claim.remote_video_id,
                )
            if (status.state != FacebookVideoState.READY
                    or status.uploading_status != "completed"
                    or status.processing_status != "completed"
                    or status.publishing_status != "completed"
                    or status.publish_status != "published"):
                return FacebookPublicationResult(
                    claim.publication_id, "VERIFY_PENDING", claim.remote_video_id,
                )
            await self._authorize(claim)
            remote = await self._transport.get_reel(
                credentials_ref=claim.credentials_ref,
                expected_page_id=claim.page_id,
                video_id=claim.remote_video_id or "",
            )
            if (remote.video_id != claim.remote_video_id or remote.page_id != claim.page_id
                    or (claim.remote_post_id is not None
                        and remote.post_id != claim.remote_post_id)):
                raise FacebookError("REMOTE_IDENTITY_MISMATCH", "Facebook Reel identity is invalid")
            return await self._store.record_verification(claim=claim, status=status, remote=remote)
        except FacebookError as exc:
            await self._store.record_transport_failure(claim=claim, error=exc)
            raise
        except Exception as exc:
            error = FacebookError(
                "VERIFY_OUTCOME_UNKNOWN",
                "Facebook verification outcome requires reconciliation",
                ambiguous=True,
            )
            await self._store.record_transport_failure(claim=claim, error=error)
            raise error from exc

    async def _transport_unknown(
        self, claim: FacebookPublicationClaim, code: str, cause: Exception,
    ) -> FacebookPublicationResult:
        error = cause if isinstance(cause, FacebookError) and cause.ambiguous else FacebookError(
            code, "Facebook transport outcome requires reconciliation", ambiguous=True,
        )
        assert isinstance(error, FacebookError)
        await self._store.record_transport_failure(claim=claim, error=error)
        raise error from cause

    def _verify_asset(self, claim: FacebookPublicationClaim, destination: Path | None) -> None:
        path = self._root / claim.asset_id.hex / "payload"
        digest = hashlib.sha256()
        size = 0
        try:
            if (claim.asset_size_bytes > self._policy.maximum_asset_bytes
                    or self._root.is_symlink() or path.parent.is_symlink() or path.is_symlink()
                    or path.parent.resolve().parent != self._root
                    or not stat.S_ISREG(path.lstat().st_mode) or path.lstat().st_nlink != 1):
                raise FacebookError("ASSET_UNAVAILABLE", "approved Facebook export is unavailable")
            with path.open("rb") as incoming:
                output = destination.open("xb") if destination is not None else None
                try:
                    before = os.fstat(incoming.fileno())
                    prefix = incoming.read(12)
                    if len(prefix) != 12 or prefix[4:8] != b"ftyp":
                        raise FacebookError("ASSET_FORMAT_INVALID", "approved Facebook export is not MP4")
                    digest.update(prefix)
                    size = len(prefix)
                    if output is not None:
                        output.write(prefix)
                    while block := incoming.read(1024 * 1024):
                        size += len(block)
                        if size > self._policy.maximum_asset_bytes:
                            raise FacebookError("ASSET_SIZE_LIMIT", "approved Facebook export exceeds the limit")
                        digest.update(block)
                        if output is not None:
                            output.write(block)
                    if output is not None:
                        output.flush()
                        os.fsync(output.fileno())
                    after = os.fstat(incoming.fileno())
                finally:
                    if output is not None:
                        output.close()
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            if (identity(before) != identity(after) or size != claim.asset_size_bytes
                    or digest.hexdigest() != claim.asset_sha256_hex):
                raise FacebookError("ASSET_INTEGRITY_MISMATCH", "approved Facebook export integrity changed")
        except FacebookError:
            raise
        except OSError as exc:
            raise FacebookError("ASSET_UNAVAILABLE", "approved Facebook export is unavailable") from exc
