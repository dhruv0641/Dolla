"""Disabled-by-default Instagram Reels publishing boundary.

The module deliberately contains no OAuth flow, secret resolver, HTTP client, or
public media host.  A deployment injects the official Instagram transport and
resolves only opaque media/credential references.  Container creation and
``media_publish`` are independently fenced because either response can be lost
after Meta accepted the mutation.
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
from typing import Protocol
import unicodedata
from uuid import UUID


INSTAGRAM_BASIC_SCOPE = "instagram_business_basic"
INSTAGRAM_PUBLISH_SCOPE = "instagram_business_content_publish"
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_PERMALINK = re.compile(r"^https://www\.instagram\.com/reel/[A-Za-z0-9_-]+/?$")
_BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


class InstagramContainerState(StrEnum):
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"
    FINISHED = "FINISHED"
    IN_PROGRESS = "IN_PROGRESS"
    PUBLISHED = "PUBLISHED"


class InstagramAccountType(StrEnum):
    BUSINESS = "BUSINESS"
    CREATOR = "CREATOR"


class InstagramError(RuntimeError):
    """Stable, operator-safe Instagram failure."""

    def __init__(self, code: str, message: str, *, ambiguous: bool = False) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("Instagram error code is invalid")
        self.code = code
        self.ambiguous = ambiguous
        super().__init__(message)


def _safe_caption(value: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (len(normalized) > 2_200
            or any(unicodedata.category(char) == "Cc"
                   or unicodedata.bidirectional(char) in _BIDI for char in normalized)):
        raise ValueError("Instagram caption is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class InstagramPublishRequest:
    request_id: UUID
    publication_id: UUID
    brand_id: UUID
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    owner_user_id: str
    artifact_version: int
    media_source_ref: str
    caption: str = ""
    share_to_feed: bool = False
    is_ai_generated: bool = True

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.request_id, self.publication_id, self.brand_id,
                self.content_id, self.channel_id, self.asset_id))
                or type(self.artifact_version) is not int
                or not 1 <= self.artifact_version <= 1_000_000
                or _SECRET_REF.fullmatch(self.media_source_ref or "") is None
                or type(self.share_to_feed) is not bool
                or type(self.is_ai_generated) is not bool):
            raise ValueError("Instagram publication identity is invalid")
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        if _SAFE_OWNER.fullmatch(owner) is None:
            raise ValueError("Instagram publication owner is invalid")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "caption", _safe_caption(self.caption))

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id), str(self.publication_id), str(self.brand_id),
            str(self.content_id), str(self.channel_id), str(self.asset_id),
            self.owner_user_id, str(self.artifact_version), self.media_source_ref,
            self.caption, "true" if self.share_to_feed else "false",
            "true" if self.is_ai_generated else "false", "INSTAGRAM_LOGIN_V1",
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "api_login": "INSTAGRAM_LOGIN",
            "media_type": "REELS",
            "caption": self.caption,
            "share_to_feed": self.share_to_feed,
            "is_ai_generated": self.is_ai_generated,
        }


@dataclass(frozen=True, slots=True)
class InstagramAuthorization:
    professional_account_id: str
    account_type: InstagramAccountType
    granted_scopes: tuple[str, ...]
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.professional_account_id or "") is None
                or not isinstance(self.account_type, InstagramAccountType)
                or not self.granted_scopes
                or len(self.granted_scopes) != len(set(self.granted_scopes))
                or any(not isinstance(scope, str) or not scope for scope in self.granted_scopes)
                or not all(isinstance(value, datetime) and value.tzinfo is not None
                           for value in (self.checked_at, self.valid_until))
                or self.valid_until <= self.checked_at):
            raise ValueError("Instagram authorization evidence is invalid")


@dataclass(frozen=True, slots=True)
class InstagramContainer:
    container_id: str

    def __post_init__(self) -> None:
        if _SAFE_REMOTE_ID.fullmatch(self.container_id or "") is None:
            raise ValueError("Instagram container identity is invalid")


@dataclass(frozen=True, slots=True)
class InstagramContainerStatus:
    container_id: str
    state: InstagramContainerState

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.container_id or "") is None
                or not isinstance(self.state, InstagramContainerState)):
            raise ValueError("Instagram container status is invalid")


@dataclass(frozen=True, slots=True)
class InstagramPublishedMedia:
    media_id: str

    def __post_init__(self) -> None:
        if _SAFE_REMOTE_ID.fullmatch(self.media_id or "") is None:
            raise ValueError("Instagram media identity is invalid")


@dataclass(frozen=True, slots=True)
class InstagramRemoteMedia:
    media_id: str
    owner_id: str
    media_type: str
    permalink: str

    def __post_init__(self) -> None:
        if (_SAFE_REMOTE_ID.fullmatch(self.media_id or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.owner_id or "") is None
                or self.media_type != "VIDEO"
                or _PERMALINK.fullmatch(self.permalink or "") is None):
            raise ValueError("Instagram remote media evidence is invalid")


@dataclass(frozen=True, slots=True)
class InstagramPublicationClaim:
    publication_id: UUID
    request_fingerprint: str
    brand_id: UUID
    owner_user_id: str
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    approval_decision_id: UUID
    artifact_version: int
    professional_account_id: str
    credentials_ref: str
    destination_fingerprint: str
    media_source_ref: str
    asset_storage_uri: str
    asset_sha256_hex: str
    asset_size_bytes: int
    asset_mime_type: str
    status: str
    phase: str
    verification_attempt_count: int = 0
    remote_container_id: str | None = None
    remote_media_id: str | None = None
    remote_url: str | None = None

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.publication_id, self.brand_id, self.content_id, self.channel_id,
                self.asset_id, self.approval_decision_id))
                or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
                or re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.professional_account_id or "") is None
                or _SECRET_REF.fullmatch(self.credentials_ref or "") is None
                or _SECRET_REF.fullmatch(self.media_source_ref or "") is None
                or self.destination_fingerprint != hashlib.sha256(
                    f"{self.professional_account_id}|{self.credentials_ref}".encode("utf-8")
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
                    "CLAIMED", "CONTAINER_RESERVED", "CONTAINER_CREATED",
                    "CONTAINER_PROCESSING", "CONTAINER_READY", "PUBLISH_RESERVED",
                    "MEDIA_RECORDED", "MEDIA_ID_UNKNOWN", "VERIFIED", "FAILED", "CANCELLED",
                }
                or type(self.verification_attempt_count) is not int
                or not 0 <= self.verification_attempt_count <= 1_000
                or (self.remote_container_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_container_id) is None)
                or (self.remote_media_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_media_id) is None)
                or (self.remote_url is not None
                    and _PERMALINK.fullmatch(self.remote_url) is None)):
            raise ValueError("Instagram publication claim is invalid")


@dataclass(frozen=True, slots=True)
class InstagramPolicy:
    enabled: bool = False
    maximum_asset_bytes: int = 300_000_000
    maximum_authorization_age_seconds: int = 300
    maximum_verification_attempts: int = 5

    def __post_init__(self) -> None:
        if (type(self.enabled) is not bool
                or type(self.maximum_asset_bytes) is not int
                or not 1_024 <= self.maximum_asset_bytes <= 300_000_000
                or type(self.maximum_authorization_age_seconds) is not int
                or not 30 <= self.maximum_authorization_age_seconds <= 3_600
                or type(self.maximum_verification_attempts) is not int
                or not 1 <= self.maximum_verification_attempts <= 100):
            raise ValueError("Instagram publishing policy is invalid")


@dataclass(frozen=True, slots=True)
class InstagramPublicationResult:
    publication_id: UUID
    status: str
    remote_media_id: str | None = None
    remote_url: str | None = None


class InstagramTransport(Protocol):
    async def check_authorization(
        self, *, credentials_ref: str, expected_account_id: str,
    ) -> InstagramAuthorization: ...

    async def create_reel_container(
        self, *, credentials_ref: str, expected_account_id: str,
        media_source_ref: str, metadata: dict[str, object], asset_sha256_hex: str,
        asset_size_bytes: int, idempotency_fingerprint: str,
    ) -> InstagramContainer: ...

    async def get_container(
        self, *, credentials_ref: str, container_id: str,
    ) -> InstagramContainerStatus: ...

    async def publish_container(
        self, *, credentials_ref: str, expected_account_id: str, container_id: str,
    ) -> InstagramPublishedMedia: ...

    async def get_media(
        self, *, credentials_ref: str, media_id: str,
    ) -> InstagramRemoteMedia: ...


class InstagramPublicationStore(Protocol):
    async def claim(self, request: InstagramPublishRequest) -> InstagramPublicationClaim: ...
    async def assert_network_ready(self, claim: InstagramPublicationClaim) -> None: ...
    async def reserve_container(self, claim: InstagramPublicationClaim) -> InstagramPublicationClaim: ...
    async def record_container(
        self, *, claim: InstagramPublicationClaim, container: InstagramContainer,
    ) -> InstagramPublicationClaim: ...
    async def record_container_status(
        self, *, claim: InstagramPublicationClaim, remote: InstagramContainerStatus,
    ) -> InstagramPublicationClaim: ...
    async def reserve_publish(self, claim: InstagramPublicationClaim) -> InstagramPublicationClaim: ...
    async def record_media(
        self, *, claim: InstagramPublicationClaim, media: InstagramPublishedMedia,
    ) -> InstagramPublicationClaim: ...
    async def record_transport_failure(
        self, *, claim: InstagramPublicationClaim, error: InstagramError,
    ) -> None: ...
    async def record_verification(
        self, *, claim: InstagramPublicationClaim, container: InstagramContainerStatus,
        media: InstagramRemoteMedia,
    ) -> InstagramPublicationResult: ...
    async def recover_container(
        self, *, request: InstagramPublishRequest, container: InstagramContainer,
    ) -> InstagramPublicationClaim: ...
    async def recover_media(
        self, *, request: InstagramPublishRequest, media: InstagramPublishedMedia,
    ) -> InstagramPublicationClaim: ...
    async def cancel_unknown(
        self, *, request: InstagramPublishRequest, reason: str,
    ) -> InstagramPublicationResult: ...


class InstagramPublisher:
    """Advance at most one safe Instagram external mutation per call."""

    def __init__(
        self, *, storage_root: Path, store: InstagramPublicationStore,
        transport: InstagramTransport, policy: InstagramPolicy | None = None,
    ) -> None:
        self._root = Path(storage_root).expanduser().resolve() / "assets"
        self._store = store
        self._transport = transport
        self._policy = policy or InstagramPolicy()

    async def publish(self, request: InstagramPublishRequest) -> InstagramPublicationResult:
        if not isinstance(request, InstagramPublishRequest):
            raise ValueError("Instagram publication request is required")
        if not self._policy.enabled:
            raise InstagramError("PUBLISHING_DISABLED", "Instagram publishing is disabled")
        claim = await self._store.claim(request)
        if claim.request_fingerprint != request.fingerprint:
            raise InstagramError("REQUEST_CONFLICT", "Instagram publication request conflicts with stored work")
        if claim.status == "PUBLISHED":
            return InstagramPublicationResult(
                claim.publication_id, "PUBLISHED", claim.remote_media_id,
                claim.remote_url,
            )
        if claim.status in {"FAILED", "CANCELLED"}:
            raise InstagramError("PUBLICATION_TERMINAL", "Instagram publication is terminal")
        if claim.phase in {"CONTAINER_RESERVED", "PUBLISH_RESERVED", "MEDIA_ID_UNKNOWN"}:
            raise InstagramError(
                "PUBLICATION_OUTCOME_UNKNOWN",
                "Instagram publication outcome requires operator reconciliation",
                ambiguous=True,
            )

        await self._authorize(claim)
        if claim.phase == "CLAIMED":
            await asyncio.to_thread(self._verify_asset, claim)
            claim = await self._store.reserve_container(claim)
            await self._authorize(claim)
            try:
                container = await self._transport.create_reel_container(
                    credentials_ref=claim.credentials_ref,
                    expected_account_id=claim.professional_account_id,
                    media_source_ref=claim.media_source_ref,
                    metadata=request.metadata,
                    asset_sha256_hex=claim.asset_sha256_hex,
                    asset_size_bytes=claim.asset_size_bytes,
                    idempotency_fingerprint=claim.request_fingerprint,
                )
                claim = await self._store.record_container(claim=claim, container=container)
            except Exception as exc:
                return await self._transport_unknown(claim, "CONTAINER_OUTCOME_UNKNOWN", exc)

        if claim.remote_container_id is None:
            raise InstagramError(
                "PUBLICATION_OUTCOME_UNKNOWN", "Instagram container identity requires reconciliation",
                ambiguous=True,
            )
        if claim.remote_media_id is not None:
            return await self._verify_safely(claim)
        container_status = await self._get_container_safely(claim)
        claim = await self._store.record_container_status(claim=claim, remote=container_status)
        if container_status.state in {InstagramContainerState.ERROR, InstagramContainerState.EXPIRED}:
            return InstagramPublicationResult(claim.publication_id, "FAILED")
        if container_status.state == InstagramContainerState.IN_PROGRESS:
            return InstagramPublicationResult(claim.publication_id, "PROCESSING")
        if container_status.state == InstagramContainerState.PUBLISHED and claim.remote_media_id is None:
            raise InstagramError(
                "MEDIA_ID_UNKNOWN", "published Instagram media identity requires reconciliation",
                ambiguous=True,
            )

        if claim.remote_media_id is None:
            if container_status.state != InstagramContainerState.FINISHED:
                raise InstagramError("REMOTE_STATE_INVALID", "Instagram container is not publishable")
            claim = await self._store.reserve_publish(claim)
            await self._authorize(claim)
            try:
                media = await self._transport.publish_container(
                    credentials_ref=claim.credentials_ref,
                    expected_account_id=claim.professional_account_id,
                    container_id=claim.remote_container_id,
                )
                claim = await self._store.record_media(claim=claim, media=media)
            except Exception as exc:
                return await self._transport_unknown(claim, "PUBLISH_OUTCOME_UNKNOWN", exc)

        assert claim.remote_media_id is not None
        return await self._verify_safely(claim)

    async def reconcile(self, request: InstagramPublishRequest) -> InstagramPublicationResult:
        return await self.publish(request)

    async def recover_container(
        self, *, request: InstagramPublishRequest, container: InstagramContainer,
    ) -> InstagramPublicationClaim:
        if not isinstance(request, InstagramPublishRequest) or not isinstance(container, InstagramContainer):
            raise ValueError("Instagram container recovery is invalid")
        return await self._store.recover_container(request=request, container=container)

    async def recover_media(
        self, *, request: InstagramPublishRequest, media: InstagramPublishedMedia,
    ) -> InstagramPublicationClaim:
        if not isinstance(request, InstagramPublishRequest) or not isinstance(media, InstagramPublishedMedia):
            raise ValueError("Instagram media recovery is invalid")
        return await self._store.recover_media(request=request, media=media)

    async def cancel_unknown(
        self, *, request: InstagramPublishRequest, reason: str,
    ) -> InstagramPublicationResult:
        if not isinstance(request, InstagramPublishRequest):
            raise ValueError("Instagram cancellation is invalid")
        return await self._store.cancel_unknown(request=request, reason=reason)

    async def _authorize(self, claim: InstagramPublicationClaim) -> None:
        await self._store.assert_network_ready(claim)
        try:
            authorization = await self._transport.check_authorization(
                credentials_ref=claim.credentials_ref,
                expected_account_id=claim.professional_account_id,
            )
        except InstagramError:
            raise
        except Exception as exc:
            raise InstagramError(
                "AUTHORIZATION_UNAVAILABLE", "Instagram authorization check is unavailable",
            ) from exc
        now = datetime.now(timezone.utc)
        maximum_age = timedelta(seconds=self._policy.maximum_authorization_age_seconds)
        if (authorization.professional_account_id != claim.professional_account_id
                or INSTAGRAM_BASIC_SCOPE not in authorization.granted_scopes
                or INSTAGRAM_PUBLISH_SCOPE not in authorization.granted_scopes
                or authorization.checked_at > now + timedelta(seconds=30)
                or now - authorization.checked_at > maximum_age
                or authorization.valid_until <= now):
            raise InstagramError("AUTHORIZATION_INVALID", "Instagram authorization is not ready")
        # The provider check is asynchronous. Re-read the owner-scoped channel
        # immediately afterwards so revocation or destination changes during the
        # await cannot authorize the following external action.
        await self._store.assert_network_ready(claim)

    async def _get_container_safely(
        self, claim: InstagramPublicationClaim,
    ) -> InstagramContainerStatus:
        if claim.verification_attempt_count >= self._policy.maximum_verification_attempts:
            raise InstagramError(
                "VERIFY_LIMIT_REACHED", "Instagram verification limit requires operator review",
            )
        await self._authorize(claim)
        try:
            remote = await self._transport.get_container(
                credentials_ref=claim.credentials_ref,
                container_id=claim.remote_container_id or "",
            )
        except InstagramError:
            raise
        except Exception as exc:
            raise InstagramError(
                "VERIFY_OUTCOME_UNKNOWN", "Instagram container status is unavailable", ambiguous=True,
            ) from exc
        if remote.container_id != claim.remote_container_id:
            raise InstagramError("REMOTE_IDENTITY_MISMATCH", "Instagram container identity is invalid")
        return remote

    async def _verify_safely(
        self, claim: InstagramPublicationClaim,
    ) -> InstagramPublicationResult:
        try:
            container = await self._get_container_safely(claim)
            if container.state != InstagramContainerState.PUBLISHED:
                return InstagramPublicationResult(
                    claim.publication_id, "VERIFY_PENDING", claim.remote_media_id,
                )
            await self._authorize(claim)
            remote = await self._transport.get_media(
                credentials_ref=claim.credentials_ref,
                media_id=claim.remote_media_id or "",
            )
            if (remote.media_id != claim.remote_media_id
                    or remote.owner_id != claim.professional_account_id):
                raise InstagramError("REMOTE_IDENTITY_MISMATCH", "Instagram media identity is invalid")
            return await self._store.record_verification(
                claim=claim, container=container, media=remote,
            )
        except InstagramError as exc:
            await self._store.record_transport_failure(claim=claim, error=exc)
            raise
        except Exception as exc:
            error = InstagramError(
                "VERIFY_OUTCOME_UNKNOWN", "Instagram verification outcome requires reconciliation",
                ambiguous=True,
            )
            await self._store.record_transport_failure(claim=claim, error=error)
            raise error from exc

    async def _transport_unknown(
        self, claim: InstagramPublicationClaim, code: str, cause: Exception,
    ) -> InstagramPublicationResult:
        error = cause if isinstance(cause, InstagramError) else InstagramError(
            code, "Instagram transport outcome requires reconciliation", ambiguous=True,
        )
        assert isinstance(error, InstagramError)
        await self._store.record_transport_failure(claim=claim, error=error)
        raise error from cause

    def _verify_asset(self, claim: InstagramPublicationClaim) -> None:
        path = self._root / claim.asset_id.hex / "payload"
        digest = hashlib.sha256()
        size = 0
        try:
            if (claim.asset_size_bytes > self._policy.maximum_asset_bytes
                    or self._root.is_symlink() or path.parent.is_symlink() or path.is_symlink()
                    or path.parent.resolve().parent != self._root
                    or not stat.S_ISREG(path.lstat().st_mode) or path.lstat().st_nlink != 1):
                raise InstagramError("ASSET_UNAVAILABLE", "approved Instagram export is unavailable")
            with path.open("rb") as incoming:
                before = os.fstat(incoming.fileno())
                prefix = incoming.read(12)
                if len(prefix) != 12 or prefix[4:8] != b"ftyp":
                    raise InstagramError("ASSET_FORMAT_INVALID", "approved Instagram export is not MP4")
                digest.update(prefix)
                size = len(prefix)
                while block := incoming.read(1024 * 1024):
                    size += len(block)
                    if size > self._policy.maximum_asset_bytes:
                        raise InstagramError("ASSET_SIZE_LIMIT", "approved Instagram export exceeds the limit")
                    digest.update(block)
                after = os.fstat(incoming.fileno())
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            if (identity(before) != identity(after) or size != claim.asset_size_bytes
                    or digest.hexdigest() != claim.asset_sha256_hex):
                raise InstagramError("ASSET_INTEGRITY_MISMATCH", "approved Instagram export integrity changed")
        except InstagramError:
            raise
        except OSError as exc:
            raise InstagramError("ASSET_UNAVAILABLE", "approved Instagram export is unavailable") from exc
