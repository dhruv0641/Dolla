"""Disabled-by-default, transport-injected official YouTube publishing workflow.

This module contains no OAuth flow and no HTTP client. A deployment must inject
an official YouTube Data API transport, explicitly enable the policy, and supply
only opaque secret references. Upload acceptance is never treated as proof of a
published video; owner-only ``videos.list`` evidence is required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Protocol
import unicodedata
from uuid import UUID


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


class YouTubePrivacy(StrEnum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class YouTubeUploadState(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"
    UNKNOWN = "UNKNOWN"


class YouTubeError(RuntimeError):
    """Stable operator-safe publishing failure."""

    def __init__(self, code: str, message: str, *, ambiguous: bool = False) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("YouTube error code is invalid")
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(message)


def _safe_text(value: str, *, minimum: int, maximum: int, label: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (not minimum <= len(normalized) <= maximum
            or any(unicodedata.category(char) == "Cc"
                   or unicodedata.bidirectional(char) in _BIDI for char in normalized)):
        raise ValueError(f"YouTube {label} is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class YouTubePublishRequest:
    request_id: UUID
    publication_id: UUID
    brand_id: UUID
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    owner_user_id: str
    artifact_version: int
    title: str
    description: str
    privacy_status: YouTubePrivacy = YouTubePrivacy.PRIVATE
    contains_synthetic_media: bool = True

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.request_id, self.publication_id, self.brand_id,
                self.content_id, self.channel_id, self.asset_id))
                or type(self.artifact_version) is not int
                or not 1 <= self.artifact_version <= 1_000_000
                or not isinstance(self.privacy_status, YouTubePrivacy)
                or type(self.contains_synthetic_media) is not bool):
            raise ValueError("YouTube publication identity is invalid")
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        if _SAFE_OWNER.fullmatch(owner) is None:
            raise ValueError("YouTube publication owner is invalid")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "title", _safe_text(
            self.title, minimum=1, maximum=100, label="title",
        ))
        object.__setattr__(self, "description", _safe_text(
            self.description, minimum=0, maximum=5_000, label="description",
        ))

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id), str(self.publication_id), str(self.brand_id),
            str(self.content_id), str(self.channel_id), str(self.asset_id),
            self.owner_user_id, str(self.artifact_version), self.title,
            self.description, self.privacy_status.value,
            "true" if self.contains_synthetic_media else "false", "false",
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "title": self.title,
            "description": self.description,
            "privacy_status": self.privacy_status.value,
            "contains_synthetic_media": self.contains_synthetic_media,
            "notify_subscribers": False,
        }


@dataclass(frozen=True, slots=True)
class YouTubeAuthorization:
    channel_external_id: str
    granted_scopes: tuple[str, ...]
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.channel_external_id) is None
                or not self.granted_scopes
                or len(self.granted_scopes) != len(set(self.granted_scopes))
                or any(not isinstance(scope, str) or not scope for scope in self.granted_scopes)
                or not all(isinstance(value, datetime) and value.tzinfo is not None
                           for value in (self.checked_at, self.valid_until))
                or self.valid_until <= self.checked_at):
            raise ValueError("YouTube authorization evidence is invalid")


@dataclass(frozen=True, slots=True)
class YouTubeUploadSession:
    session_ref: str
    upload_id: str

    def __post_init__(self) -> None:
        if (_SECRET_REF.fullmatch(self.session_ref) is None
                or _SAFE_REMOTE_ID.fullmatch(self.upload_id) is None):
            raise ValueError("YouTube upload session evidence is invalid")


@dataclass(frozen=True, slots=True)
class YouTubeUploadOutcome:
    state: YouTubeUploadState
    committed_bytes: int
    video_id: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.state, YouTubeUploadState)
                or type(self.committed_bytes) is not int or self.committed_bytes < 0
                or (self.video_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.video_id) is None)
                or (self.state == YouTubeUploadState.COMPLETE) != (self.video_id is not None)):
            raise ValueError("YouTube upload outcome is invalid")


@dataclass(frozen=True, slots=True)
class YouTubeRemoteVideo:
    video_id: str
    channel_external_id: str
    upload_status: str
    processing_status: str
    privacy_status: YouTubePrivacy

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.video_id) is None
                or _SAFE_REMOTE_ID.fullmatch(self.channel_external_id) is None
                or self.upload_status not in {
                    "deleted", "failed", "processed", "rejected", "uploaded",
                }
                or self.processing_status not in {
                    "failed", "processing", "succeeded", "terminated",
                }
                or not isinstance(self.privacy_status, YouTubePrivacy)):
            raise ValueError("YouTube remote video evidence is invalid")

    @property
    def canonical_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class YouTubePublicationClaim:
    publication_id: UUID
    request_fingerprint: str
    brand_id: UUID
    owner_user_id: str
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    approval_decision_id: UUID
    artifact_version: int
    channel_external_id: str
    credentials_ref: str
    destination_fingerprint: str
    asset_storage_uri: str
    asset_sha256_hex: str
    asset_size_bytes: int
    asset_mime_type: str
    privacy_status: YouTubePrivacy
    status: str
    upload_session_ref: str | None = None
    remote_upload_id: str | None = None
    remote_video_id: str | None = None

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.publication_id, self.brand_id, self.content_id, self.channel_id,
                self.asset_id, self.approval_decision_id))
                or _SAFE_OWNER.fullmatch(self.owner_user_id) is None
                or re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint) is None
                or _SAFE_REMOTE_ID.fullmatch(self.channel_external_id) is None
                or _SECRET_REF.fullmatch(self.credentials_ref) is None
                or self.destination_fingerprint != hashlib.sha256(
                    f"{self.channel_external_id}|{self.credentials_ref}".encode("utf-8")
                ).hexdigest()
                or self.asset_storage_uri != f"managed://assets/{self.asset_id.hex}/payload"
                or re.fullmatch(r"[0-9a-f]{64}", self.asset_sha256_hex) is None
                or type(self.asset_size_bytes) is not int or self.asset_size_bytes <= 0
                or self.asset_mime_type != "video/mp4"
                or not isinstance(self.privacy_status, YouTubePrivacy)
                or self.status not in {
                    "DRAFT", "PUBLISH_REQUESTED", "UPLOAD_STARTED", "PROCESSING", "VERIFY_PENDING",
                    "PUBLISHED", "FAILED", "CANCELLED",
                }
                or (self.upload_session_ref is not None
                    and _SECRET_REF.fullmatch(self.upload_session_ref) is None)
                or (self.remote_upload_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_upload_id) is None)
                or (self.remote_video_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_video_id) is None)):
            raise ValueError("YouTube publication claim is invalid")


@dataclass(frozen=True, slots=True)
class YouTubePolicy:
    enabled: bool = False
    allowed_privacy: tuple[YouTubePrivacy, ...] = (YouTubePrivacy.PRIVATE,)
    maximum_asset_bytes: int = 4_000_000_000
    maximum_authorization_age_seconds: int = 300

    def __post_init__(self) -> None:
        if (type(self.enabled) is not bool or not self.allowed_privacy
                or len(self.allowed_privacy) != len(set(self.allowed_privacy))
                or any(not isinstance(value, YouTubePrivacy) for value in self.allowed_privacy)
                or type(self.maximum_asset_bytes) is not int
                or not 1_024 <= self.maximum_asset_bytes <= 4_000_000_000
                or type(self.maximum_authorization_age_seconds) is not int
                or not 30 <= self.maximum_authorization_age_seconds <= 3_600):
            raise ValueError("YouTube publishing policy is invalid")


@dataclass(frozen=True, slots=True)
class YouTubePublicationResult:
    publication_id: UUID
    status: str
    remote_video_id: str | None = None
    remote_url: str | None = None


class YouTubeTransport(Protocol):
    async def check_authorization(
        self, *, credentials_ref: str, expected_channel_id: str,
    ) -> YouTubeAuthorization: ...

    async def start_resumable_upload(
        self, *, credentials_ref: str, expected_channel_id: str,
        metadata: dict[str, object], content_length: int, mime_type: str,
        idempotency_fingerprint: str,
    ) -> YouTubeUploadSession: ...

    async def resume_upload(
        self, *, credentials_ref: str, session_ref: str, source_path: Path,
        content_length: int, sha256_hex: str,
    ) -> YouTubeUploadOutcome: ...

    async def get_video(
        self, *, credentials_ref: str, video_id: str,
    ) -> YouTubeRemoteVideo: ...


class YouTubePublicationStore(Protocol):
    async def claim(self, request: YouTubePublishRequest) -> YouTubePublicationClaim: ...
    async def assert_network_ready(self, claim: YouTubePublicationClaim) -> None: ...
    async def reserve_start(self, claim: YouTubePublicationClaim) -> YouTubePublicationClaim: ...
    async def record_session(
        self, *, claim: YouTubePublicationClaim, session: YouTubeUploadSession,
    ) -> YouTubePublicationClaim: ...
    async def record_upload(
        self, *, claim: YouTubePublicationClaim, outcome: YouTubeUploadOutcome,
    ) -> YouTubePublicationClaim: ...
    async def record_transport_failure(
        self, *, claim: YouTubePublicationClaim, error: YouTubeError,
    ) -> None: ...
    async def record_verification(
        self, *, claim: YouTubePublicationClaim, remote: YouTubeRemoteVideo,
        status: str,
    ) -> YouTubePublicationResult: ...
    async def recover_unknown_session(
        self, *, request: YouTubePublishRequest, session: YouTubeUploadSession,
    ) -> YouTubePublicationClaim: ...
    async def cancel_unknown(
        self, *, request: YouTubePublishRequest, reason: str,
    ) -> YouTubePublicationResult: ...


class YouTubePublisher:
    """Run one resumable step and one remote verification step safely."""

    def __init__(
        self, *, storage_root: Path, store: YouTubePublicationStore,
        transport: YouTubeTransport, policy: YouTubePolicy | None = None,
    ) -> None:
        self._root = Path(storage_root).expanduser().resolve() / "assets"
        self._store = store
        self._transport = transport
        self._policy = policy or YouTubePolicy()

    async def publish(self, request: YouTubePublishRequest) -> YouTubePublicationResult:
        if not isinstance(request, YouTubePublishRequest):
            raise ValueError("YouTube publication request is required")
        if not self._policy.enabled:
            raise YouTubeError("PUBLISHING_DISABLED", "YouTube publishing is disabled")
        if request.privacy_status not in self._policy.allowed_privacy:
            raise YouTubeError("PRIVACY_NOT_ALLOWED", "requested YouTube privacy is not enabled")
        claim = await self._store.claim(request)
        if claim.request_fingerprint != request.fingerprint:
            raise YouTubeError("REQUEST_CONFLICT", "YouTube publication request conflicts with stored work")
        if claim.status == "PUBLISHED":
            return YouTubePublicationResult(
                claim.publication_id, "PUBLISHED", claim.remote_video_id,
                (f"https://www.youtube.com/watch?v={claim.remote_video_id}"
                 if claim.remote_video_id else None),
            )
        if claim.status in {"FAILED", "CANCELLED"}:
            raise YouTubeError("PUBLICATION_TERMINAL", "YouTube publication is terminal")
        if (claim.status in {"PUBLISH_REQUESTED", "VERIFY_PENDING"}
                and claim.upload_session_ref is None
                and claim.remote_video_id is None):
            raise YouTubeError(
                "PUBLICATION_OUTCOME_UNKNOWN",
                "YouTube publication outcome requires operator reconciliation",
                ambiguous=True,
            )

        await self._store.assert_network_ready(claim)
        try:
            authorization = await self._transport.check_authorization(
                credentials_ref=claim.credentials_ref,
                expected_channel_id=claim.channel_external_id,
            )
        except YouTubeError:
            raise
        except Exception as exc:
            raise YouTubeError(
                "AUTHORIZATION_UNAVAILABLE", "YouTube authorization check is unavailable",
            ) from exc
        self._require_authorization(claim, authorization)
        if claim.remote_video_id is not None and claim.status in {"PROCESSING", "VERIFY_PENDING"}:
            return await self._verify_safely(claim, claim.remote_video_id)
        try:
            if claim.upload_session_ref is None:
                claim = await self._store.reserve_start(claim)
                await self._store.assert_network_ready(claim)
                session = await self._transport.start_resumable_upload(
                    credentials_ref=claim.credentials_ref,
                    expected_channel_id=claim.channel_external_id,
                    metadata=request.metadata,
                    content_length=claim.asset_size_bytes,
                    mime_type=claim.asset_mime_type,
                    idempotency_fingerprint=claim.request_fingerprint,
                )
                claim = await self._store.record_session(claim=claim, session=session)
            assert claim.upload_session_ref is not None
            await self._store.assert_network_ready(claim)
            with tempfile.TemporaryDirectory(prefix="flowx-youtube-") as directory:
                snapshot = Path(directory) / "upload.mp4"
                await asyncio.to_thread(self._snapshot, claim, snapshot)
                outcome = await self._transport.resume_upload(
                    credentials_ref=claim.credentials_ref,
                    session_ref=claim.upload_session_ref,
                    source_path=snapshot,
                    content_length=claim.asset_size_bytes,
                    sha256_hex=claim.asset_sha256_hex,
                )
            if (outcome.committed_bytes > claim.asset_size_bytes
                    or (outcome.state == YouTubeUploadState.COMPLETE
                        and outcome.committed_bytes != claim.asset_size_bytes)):
                raise YouTubeError("REMOTE_RESPONSE_INVALID", "YouTube upload progress is invalid")
            claim = await self._store.record_upload(claim=claim, outcome=outcome)
        except YouTubeError as exc:
            await self._store.record_transport_failure(claim=claim, error=exc)
            raise
        except Exception as exc:
            error = YouTubeError(
                "TRANSPORT_OUTCOME_UNKNOWN",
                "YouTube transport outcome requires reconciliation", ambiguous=True,
            )
            await self._store.record_transport_failure(claim=claim, error=error)
            raise error from exc

        if outcome.state != YouTubeUploadState.COMPLETE:
            return YouTubePublicationResult(
                claim.publication_id,
                "VERIFY_PENDING" if outcome.state == YouTubeUploadState.UNKNOWN else "UPLOAD_STARTED",
            )
        assert outcome.video_id is not None
        return await self._verify_safely(claim, outcome.video_id)

    async def reconcile(
        self, request: YouTubePublishRequest,
    ) -> YouTubePublicationResult:
        """Re-enter safely: the store returns the existing claim/session/video identity."""
        return await self.publish(request)

    async def recover_session(
        self, *, request: YouTubePublishRequest, session: YouTubeUploadSession,
    ) -> YouTubePublicationClaim:
        """Bind an operator-recovered official session without calling YouTube."""
        if not isinstance(request, YouTubePublishRequest) or not isinstance(session, YouTubeUploadSession):
            raise ValueError("YouTube unknown-outcome recovery is invalid")
        return await self._store.recover_unknown_session(request=request, session=session)

    async def cancel_unknown(
        self, *, request: YouTubePublishRequest, reason: str,
    ) -> YouTubePublicationResult:
        """Resolve an unknown initiation terminally without calling YouTube."""
        if not isinstance(request, YouTubePublishRequest):
            raise ValueError("YouTube unknown-outcome cancellation is invalid")
        return await self._store.cancel_unknown(request=request, reason=reason)

    def _require_authorization(
        self, claim: YouTubePublicationClaim, authorization: YouTubeAuthorization,
    ) -> None:
        now = datetime.now(timezone.utc)
        maximum_age = timedelta(seconds=self._policy.maximum_authorization_age_seconds)
        if (authorization.channel_external_id != claim.channel_external_id
                or YOUTUBE_UPLOAD_SCOPE not in authorization.granted_scopes
                or authorization.checked_at > now + timedelta(seconds=30)
                or now - authorization.checked_at > maximum_age
                or authorization.valid_until <= now):
            raise YouTubeError("AUTHORIZATION_INVALID", "YouTube authorization is not ready")

    async def _verify(
        self, claim: YouTubePublicationClaim, video_id: str,
    ) -> YouTubePublicationResult:
        await self._store.assert_network_ready(claim)
        remote = await self._transport.get_video(
            credentials_ref=claim.credentials_ref, video_id=video_id,
        )
        if remote.video_id != video_id or remote.channel_external_id != claim.channel_external_id:
            raise YouTubeError("REMOTE_IDENTITY_MISMATCH", "YouTube video identity is invalid")
        if remote.upload_status in {"failed", "rejected", "deleted"} or remote.processing_status in {
            "failed", "terminated",
        }:
            return await self._store.record_verification(
                claim=claim, remote=remote, status="FAILED",
            )
        if (remote.upload_status == "processed"
                and remote.processing_status == "succeeded"
                and remote.privacy_status == claim.privacy_status):
            return await self._store.record_verification(
                claim=claim, remote=remote, status="PUBLISHED",
            )
        return await self._store.record_verification(
            claim=claim, remote=remote, status="PROCESSING",
        )

    async def _verify_safely(
        self, claim: YouTubePublicationClaim, video_id: str,
    ) -> YouTubePublicationResult:
        try:
            return await self._verify(claim, video_id)
        except YouTubeError as exc:
            await self._store.record_transport_failure(claim=claim, error=exc)
            raise
        except Exception as exc:
            error = YouTubeError(
                "VERIFY_OUTCOME_UNKNOWN",
                "YouTube verification outcome requires reconciliation", ambiguous=True,
            )
            await self._store.record_transport_failure(claim=claim, error=error)
            raise error from exc

    def _snapshot(self, claim: YouTubePublicationClaim, destination: Path) -> None:
        path = self._root / claim.asset_id.hex / "payload"
        digest = hashlib.sha256()
        size = 0
        try:
            if (claim.asset_size_bytes > self._policy.maximum_asset_bytes
                    or self._root.is_symlink() or path.parent.is_symlink() or path.is_symlink()
                    or path.parent.resolve().parent != self._root
                    or not stat.S_ISREG(path.lstat().st_mode) or path.lstat().st_nlink != 1):
                raise YouTubeError("ASSET_UNAVAILABLE", "approved YouTube export is unavailable")
            with path.open("rb") as incoming, destination.open("xb") as output:
                before = os.fstat(incoming.fileno())
                prefix = incoming.read(12)
                if len(prefix) != 12 or prefix[4:8] != b"ftyp":
                    raise YouTubeError("ASSET_FORMAT_INVALID", "approved YouTube export is not MP4")
                digest.update(prefix)
                size = len(prefix)
                output.write(prefix)
                while block := incoming.read(1024 * 1024):
                    size += len(block)
                    if size > self._policy.maximum_asset_bytes:
                        raise YouTubeError("ASSET_SIZE_LIMIT", "approved YouTube export exceeds the limit")
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
                after = os.fstat(incoming.fileno())
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            if (identity(before) != identity(after) or size != claim.asset_size_bytes
                    or digest.hexdigest() != claim.asset_sha256_hex):
                raise YouTubeError("ASSET_INTEGRITY_MISMATCH", "approved YouTube export integrity changed")
        except YouTubeError:
            raise
        except OSError as exc:
            raise YouTubeError("ASSET_UNAVAILABLE", "approved YouTube export is unavailable") from exc
