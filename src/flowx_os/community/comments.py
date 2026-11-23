"""Authorized, read-only ingestion of first-party platform comments.

Provider responses are untrusted data.  This module validates and fingerprints
them, but it deliberately grants no moderation, reply, publishing, or account
connection authority.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flowx_os.publishing.reconciliation import PublicationPlatform


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_COMMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SAFE_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")

YOUTUBE_COMMENT_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
INSTAGRAM_BASIC_SCOPE = "instagram_business_basic"
INSTAGRAM_COMMENT_READ_SCOPE = "instagram_business_manage_comments"
FACEBOOK_PAGE_LIST_SCOPE = "pages_show_list"
FACEBOOK_COMMENT_READ_SCOPE = "pages_read_engagement"


def _aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _bounded_untrusted_text(value: str | None, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and not any(
            (ord(character) < 32 and character not in "\n\r\t")
            or ord(character) == 127
            for character in value
        )
    )


def _cursor_valid(value: str | None) -> bool:
    return value is None or (
        isinstance(value, str)
        and 1 <= len(value) <= 2_048
        and value.strip() == value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp_token(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_remote_url(
    platform: PublicationPlatform, remote_object_id: str, remote_url: str,
) -> bool:
    if platform is PublicationPlatform.YOUTUBE:
        return remote_url == f"https://www.youtube.com/watch?v={remote_object_id}"
    if platform is PublicationPlatform.FACEBOOK:
        return remote_url == f"https://www.facebook.com/reel/{remote_object_id}"
    return re.fullmatch(
        r"https://www[.]instagram[.]com/reel/[A-Za-z0-9_-]+/?", remote_url,
    ) is not None


class CommentState(StrEnum):
    ACTIVE = "ACTIVE"
    EDITED = "EDITED"
    DELETED = "DELETED"


class CommentIngestionError(RuntimeError):
    """Stable operator-safe error that never includes provider payloads."""

    def __init__(self, code: str, message: str) -> None:
        if _ERROR_CODE.fullmatch(code) is None:
            raise ValueError("comment ingestion error code is invalid")
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CommentIngestionAbandonment:
    request_id: UUID
    sync_id: UUID
    code: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.sync_id, UUID)
            or self.code != "RETRY_LIMIT_REACHED"
        ):
            raise ValueError("comment ingestion abandonment is invalid")


@dataclass(frozen=True, slots=True)
class CommentIngestionRequest:
    request_id: UUID
    sync_id: UUID
    publication_id: UUID
    owner_user_id: str
    page_index: int

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.sync_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(owner) is None
            or type(self.page_index) is not int
            or not 1 <= self.page_index <= 1_000
        ):
            raise ValueError("comment ingestion request identity is invalid")
        object.__setattr__(self, "owner_user_id", owner)


@dataclass(frozen=True, slots=True)
class CommentIngestionTarget:
    reservation_request_id: UUID
    reservation_sync_id: UUID
    reservation_generation: int
    publication_id: UUID
    owner_user_id: str
    platform: PublicationPlatform
    publication_state_version: int
    publication_request_fingerprint: str
    channel_id: UUID
    destination_id: str
    credentials_ref: str
    destination_fingerprint: str
    remote_object_id: str
    remote_url: str
    reconciliation_request_id: UUID
    reconciliation_target_fingerprint: str
    reconciliation_observation_fingerprint: str
    reconciliation_observed_at: datetime
    page_index: int
    cursor: str | None

    def __post_init__(self) -> None:
        expected_destination = _sha256(f"{self.destination_id}|{self.credentials_ref}")
        if (
            not isinstance(self.reservation_request_id, UUID)
            or not isinstance(self.reservation_sync_id, UUID)
            or type(self.reservation_generation) is not int
            or not 1 <= self.reservation_generation <= 10
            or not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.platform, PublicationPlatform)
            or type(self.publication_state_version) is not int
            or not 0 <= self.publication_state_version <= 9_223_372_036_854_775_807
            or _HEX64.fullmatch(self.publication_request_fingerprint or "") is None
            or not isinstance(self.channel_id, UUID)
            or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
            or _SECRET_REF.fullmatch(self.credentials_ref or "") is None
            or self.destination_fingerprint != expected_destination
            or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
            or not isinstance(self.remote_url, str)
            or not _canonical_remote_url(
                self.platform, self.remote_object_id, self.remote_url,
            )
            or not isinstance(self.reconciliation_request_id, UUID)
            or _HEX64.fullmatch(self.reconciliation_target_fingerprint or "") is None
            or _HEX64.fullmatch(self.reconciliation_observation_fingerprint or "") is None
            or not _aware(self.reconciliation_observed_at)
            or type(self.page_index) is not int
            or not 1 <= self.page_index <= 1_000
            or not _cursor_valid(self.cursor)
        ):
            raise ValueError("comment ingestion target is invalid")

    @property
    def cursor_fingerprint(self) -> str:
        return _sha256(self.cursor or "")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.publication_id),
            self.owner_user_id,
            self.platform.value,
            str(self.publication_state_version),
            self.publication_request_fingerprint,
            str(self.channel_id),
            self.destination_id,
            self.destination_fingerprint,
            self.remote_object_id,
            self.remote_url,
            str(self.reconciliation_request_id),
            self.reconciliation_target_fingerprint,
            self.reconciliation_observation_fingerprint,
        )
        return _sha256("|".join(values))


def required_comment_read_scopes(platform: PublicationPlatform) -> frozenset[str]:
    if platform is PublicationPlatform.YOUTUBE:
        return frozenset({YOUTUBE_COMMENT_READ_SCOPE})
    if platform is PublicationPlatform.INSTAGRAM:
        return frozenset({INSTAGRAM_BASIC_SCOPE, INSTAGRAM_COMMENT_READ_SCOPE})
    if platform is PublicationPlatform.FACEBOOK:
        return frozenset({FACEBOOK_PAGE_LIST_SCOPE, FACEBOOK_COMMENT_READ_SCOPE})
    raise ValueError("comment platform is invalid")


@dataclass(frozen=True, slots=True)
class CommentReadAuthorization:
    platform: PublicationPlatform
    destination_id: str
    granted_scopes: tuple[str, ...]
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
            or not isinstance(self.granted_scopes, tuple)
            or not self.granted_scopes
            or any(_SAFE_SCOPE.fullmatch(value or "") is None for value in self.granted_scopes)
            or tuple(sorted(set(self.granted_scopes))) != self.granted_scopes
            or not _aware(self.checked_at)
            or not _aware(self.valid_until)
            or self.valid_until <= self.checked_at
        ):
            raise ValueError("comment read authorization evidence is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            self.platform.value,
            self.destination_id,
            ",".join(self.granted_scopes),
            _timestamp_token(self.checked_at),
            _timestamp_token(self.valid_until),
        )
        return _sha256("|".join(values))


@dataclass(frozen=True, slots=True)
class ProviderComment:
    remote_comment_id: str
    parent_remote_comment_id: str | None
    author_external_id: str | None
    text: str | None
    state: CommentState
    published_at: datetime
    provider_updated_at: datetime

    def __post_init__(self) -> None:
        if (
            _SAFE_COMMENT_ID.fullmatch(self.remote_comment_id or "") is None
            or (
                self.parent_remote_comment_id is not None
                and _SAFE_COMMENT_ID.fullmatch(self.parent_remote_comment_id) is None
            )
            or self.parent_remote_comment_id == self.remote_comment_id
            or not isinstance(self.state, CommentState)
            or not _aware(self.published_at)
            or not _aware(self.provider_updated_at)
            or self.provider_updated_at < self.published_at
        ):
            raise ValueError("provider comment identity is invalid")
        if self.state is CommentState.DELETED:
            if self.author_external_id is not None or self.text is not None:
                raise ValueError("deleted comment must not retain author or text")
        elif (
            not _bounded_untrusted_text(self.author_external_id, maximum=512)
            or not _bounded_untrusted_text(self.text, maximum=10_000)
        ):
            raise ValueError("active comment content is invalid")

    @property
    def author_external_id_hash(self) -> str | None:
        return None if self.author_external_id is None else _sha256(self.author_external_id)

    @property
    def fingerprint(self) -> str:
        values = (
            self.remote_comment_id,
            self.parent_remote_comment_id or "",
            self.author_external_id_hash or "",
            self.text or "",
            self.state.value,
            _timestamp_token(self.published_at),
            _timestamp_token(self.provider_updated_at),
        )
        return _sha256("|".join(values))


@dataclass(frozen=True, slots=True)
class ProviderCommentBatch:
    request_id: UUID
    sync_id: UUID
    publication_id: UUID
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    page_index: int
    cursor_fingerprint: str
    comments: tuple[ProviderComment, ...]
    has_more: bool
    next_cursor: str | None
    observed_at: datetime
    evidence_id: str
    authorization_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.comments, tuple) or any(
            not isinstance(comment, ProviderComment) for comment in self.comments
        ):
            raise ValueError("provider comment batch entries are invalid")
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.sync_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
            or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
            or type(self.page_index) is not int
            or not 1 <= self.page_index <= 1_000
            or _HEX64.fullmatch(self.cursor_fingerprint or "") is None
            or type(self.has_more) is not bool
            or not _cursor_valid(self.next_cursor)
            or self.has_more is not (self.next_cursor is not None)
            or not _aware(self.observed_at)
            or _SAFE_EVIDENCE_ID.fullmatch(self.evidence_id or "") is None
            or _HEX64.fullmatch(self.authorization_fingerprint or "") is None
        ):
            raise ValueError("provider comment batch is invalid")
        identities = [comment.remote_comment_id for comment in self.comments]
        if (
            len(identities) != len(set(identities))
            or any(comment.provider_updated_at > self.observed_at for comment in self.comments)
        ):
            raise ValueError("provider comment batch entries are invalid")

    @property
    def next_cursor_fingerprint(self) -> str:
        return _sha256(self.next_cursor or "")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id),
            str(self.sync_id),
            str(self.publication_id),
            self.platform.value,
            self.destination_id,
            self.remote_object_id,
            str(self.page_index),
            self.cursor_fingerprint,
            ",".join(comment.fingerprint for comment in self.comments),
            str(self.has_more).lower(),
            self.next_cursor_fingerprint,
            _timestamp_token(self.observed_at),
            self.evidence_id,
            self.authorization_fingerprint,
        )
        return _sha256("|".join(values))


@dataclass(frozen=True, slots=True)
class CommentIngestionBatch:
    request_id: UUID
    sync_id: UUID
    publication_id: UUID
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    page_index: int
    target_fingerprint: str
    batch_fingerprint: str
    cursor_fingerprint: str
    next_cursor_fingerprint: str
    comment_count: int
    has_more: bool
    evidence_id: str
    observed_at: datetime
    created_at: datetime
    authorization_fingerprint: str
    authorization_scopes: tuple[str, ...]
    authorization_checked_at: datetime
    authorization_valid_until: datetime

    def __post_init__(self) -> None:
        authorization_values_valid = (
            isinstance(self.platform, PublicationPlatform)
            and isinstance(self.authorization_scopes, tuple)
            and bool(self.authorization_scopes)
            and all(
                _SAFE_SCOPE.fullmatch(value or "") is not None
                for value in self.authorization_scopes
            )
            and tuple(sorted(set(self.authorization_scopes))) == self.authorization_scopes
            and _aware(self.authorization_checked_at)
            and _aware(self.authorization_valid_until)
            and self.authorization_valid_until > self.authorization_checked_at
        )
        expected_authorization = ""
        if authorization_values_valid:
            expected_authorization = _sha256("|".join((
                self.platform.value,
                self.destination_id,
                ",".join(self.authorization_scopes),
                _timestamp_token(self.authorization_checked_at),
                _timestamp_token(self.authorization_valid_until),
            )))
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.sync_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
            or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
            or type(self.page_index) is not int
            or not 1 <= self.page_index <= 1_000
            or any(
                _HEX64.fullmatch(value or "") is None
                for value in (
                    self.target_fingerprint,
                    self.batch_fingerprint,
                    self.cursor_fingerprint,
                    self.next_cursor_fingerprint,
                    self.authorization_fingerprint,
                )
            )
            or type(self.comment_count) is not int
            or not 0 <= self.comment_count <= 500
            or type(self.has_more) is not bool
            or _SAFE_EVIDENCE_ID.fullmatch(self.evidence_id or "") is None
            or not _aware(self.observed_at)
            or not _aware(self.created_at)
            or not authorization_values_valid
            or self.authorization_fingerprint != expected_authorization
            or not required_comment_read_scopes(self.platform).issubset(
                self.authorization_scopes
            )
        ):
            raise ValueError("stored comment ingestion batch is invalid")


@dataclass(frozen=True, slots=True)
class CommentIngestionPolicy:
    enabled: bool = False
    page_size: int = 100
    maximum_pages_per_sync: int = 100
    maximum_observation_age_seconds: int = 300
    maximum_clock_skew_seconds: int = 30
    maximum_reconciliation_age_seconds: int = 3_600
    maximum_authorization_age_seconds: int = 300
    maximum_provider_attempts: int = 3
    reservation_lease_seconds: int = 120

    def __post_init__(self) -> None:
        if (
            type(self.enabled) is not bool
            or type(self.page_size) is not int
            or not 1 <= self.page_size <= 500
            or type(self.maximum_pages_per_sync) is not int
            or not 1 <= self.maximum_pages_per_sync <= 1_000
            or type(self.maximum_observation_age_seconds) is not int
            or not 30 <= self.maximum_observation_age_seconds <= 3_600
            or type(self.maximum_clock_skew_seconds) is not int
            or not 0 <= self.maximum_clock_skew_seconds <= 120
            or type(self.maximum_reconciliation_age_seconds) is not int
            or not 300 <= self.maximum_reconciliation_age_seconds <= 86_400
            or type(self.maximum_authorization_age_seconds) is not int
            or not 30 <= self.maximum_authorization_age_seconds <= 3_600
            or type(self.maximum_provider_attempts) is not int
            or not 1 <= self.maximum_provider_attempts <= 10
            or type(self.reservation_lease_seconds) is not int
            or not 30 <= self.reservation_lease_seconds <= 900
        ):
            raise ValueError("comment ingestion policy is invalid")


class CommentProvider(Protocol):
    async def check_authorization(
        self,
        *,
        platform: PublicationPlatform,
        credentials_ref: str,
        destination_id: str,
    ) -> CommentReadAuthorization: ...

    async def fetch_comments(
        self,
        *,
        request_id: UUID,
        sync_id: UUID,
        publication_id: UUID,
        platform: PublicationPlatform,
        credentials_ref: str,
        destination_id: str,
        remote_object_id: str,
        page_index: int,
        cursor: str | None,
        limit: int,
    ) -> ProviderCommentBatch: ...


class CommentIngestionStore(Protocol):
    async def get_existing(
        self, request: CommentIngestionRequest,
    ) -> CommentIngestionBatch | None: ...

    async def reserve(
        self,
        request: CommentIngestionRequest,
        *,
        maximum_pages: int,
        maximum_reconciliation_age_seconds: int,
        maximum_provider_attempts: int,
        reservation_lease_seconds: int,
    ) -> CommentIngestionTarget | CommentIngestionBatch | CommentIngestionAbandonment: ...

    async def assert_network_ready(self, target: CommentIngestionTarget) -> None: ...

    async def record_failure(
        self,
        *,
        request: CommentIngestionRequest,
        target: CommentIngestionTarget,
        error_code: str,
    ) -> None: ...

    async def record(
        self,
        *,
        request: CommentIngestionRequest,
        target: CommentIngestionTarget,
        batch: ProviderCommentBatch,
        authorization: CommentReadAuthorization,
    ) -> CommentIngestionBatch: ...


class AuthorizedCommentIngestor:
    """Fetch and persist one bounded page from one verified owned publication."""

    def __init__(
        self,
        *,
        store: CommentIngestionStore,
        provider: CommentProvider,
        policy: CommentIngestionPolicy | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._policy = policy or CommentIngestionPolicy()

    async def ingest(self, request: CommentIngestionRequest) -> CommentIngestionBatch:
        if not isinstance(request, CommentIngestionRequest):
            raise ValueError("comment ingestion request is required")
        existing = await self._store.get_existing(request)
        if existing is not None:
            return existing
        if not self._policy.enabled:
            raise CommentIngestionError(
                "CAPABILITY_DISABLED", "comment ingestion is disabled",
            )
        reserved = await self._store.reserve(
            request,
            maximum_pages=self._policy.maximum_pages_per_sync,
            maximum_reconciliation_age_seconds=(
                self._policy.maximum_reconciliation_age_seconds
            ),
            maximum_provider_attempts=self._policy.maximum_provider_attempts,
            reservation_lease_seconds=self._policy.reservation_lease_seconds,
        )
        if isinstance(reserved, CommentIngestionBatch):
            return reserved
        if isinstance(reserved, CommentIngestionAbandonment):
            raise CommentIngestionError(
                reserved.code, "comment ingestion retry limit requires a new sync",
            )
        target = reserved
        if (
            not isinstance(target, CommentIngestionTarget)
            or target.reservation_request_id != request.request_id
            or target.reservation_sync_id != request.sync_id
            or target.publication_id != request.publication_id
            or target.owner_user_id != request.owner_user_id
            or target.page_index != request.page_index
        ):
            raise CommentIngestionError(
                "RESERVATION_INVALID", "comment ingestion reservation is invalid",
            )
        authorization_now = datetime.now(timezone.utc)
        if (
            target.reconciliation_observed_at
            > authorization_now + timedelta(seconds=self._policy.maximum_clock_skew_seconds)
            or authorization_now - target.reconciliation_observed_at
            > timedelta(seconds=self._policy.maximum_reconciliation_age_seconds)
        ):
            raise CommentIngestionError(
                "AUTHORIZATION_STALE",
                "verified publication authorization is outside the allowed time window",
            )
        await self._assert_network_ready(request, target)
        try:
            authorization = await self._provider.check_authorization(
                platform=target.platform,
                credentials_ref=target.credentials_ref,
                destination_id=target.destination_id,
            )
        except CommentIngestionError as exc:
            await self._store.record_failure(
                request=request, target=target, error_code=exc.code,
            )
            raise
        except Exception as exc:
            await self._store.record_failure(
                request=request, target=target, error_code="AUTHORIZATION_UNAVAILABLE",
            )
            raise CommentIngestionError(
                "AUTHORIZATION_UNAVAILABLE", "comment authorization check is unavailable",
            ) from exc
        try:
            self._validate_authorization(target, authorization)
        except CommentIngestionError as exc:
            await self._store.record_failure(
                request=request, target=target, error_code=exc.code,
            )
            raise
        await self._assert_network_ready(request, target)
        try:
            batch = await self._provider.fetch_comments(
                request_id=request.request_id,
                sync_id=request.sync_id,
                publication_id=target.publication_id,
                platform=target.platform,
                credentials_ref=target.credentials_ref,
                destination_id=target.destination_id,
                remote_object_id=target.remote_object_id,
                page_index=target.page_index,
                cursor=target.cursor,
                limit=self._policy.page_size,
            )
        except CommentIngestionError as exc:
            await self._store.record_failure(
                request=request, target=target, error_code=exc.code,
            )
            raise
        except Exception as exc:
            await self._store.record_failure(
                request=request, target=target, error_code="PROVIDER_UNAVAILABLE",
            )
            raise CommentIngestionError(
                "PROVIDER_UNAVAILABLE", "comment provider response is unavailable",
            ) from exc
        try:
            self._validate_batch(request, target, authorization, batch)
        except CommentIngestionError as exc:
            await self._store.record_failure(
                request=request, target=target, error_code=exc.code,
            )
            raise
        return await self._store.record(
            request=request, target=target, batch=batch, authorization=authorization,
        )

    async def _assert_network_ready(
        self, request: CommentIngestionRequest, target: CommentIngestionTarget,
    ) -> None:
        try:
            await self._store.assert_network_ready(target)
        except Exception as exc:
            await self._store.record_failure(
                request=request, target=target, error_code="NETWORK_NOT_READY",
            )
            raise CommentIngestionError(
                "NETWORK_NOT_READY", "comment ingestion authorization changed",
            ) from exc

    def _validate_authorization(
        self,
        target: CommentIngestionTarget,
        authorization: CommentReadAuthorization,
    ) -> None:
        if not isinstance(authorization, CommentReadAuthorization):
            raise CommentIngestionError(
                "AUTHORIZATION_INVALID", "comment authorization evidence is invalid",
            )
        now = datetime.now(timezone.utc)
        if (
            authorization.platform is not target.platform
            or authorization.destination_id != target.destination_id
            or not required_comment_read_scopes(target.platform).issubset(
                authorization.granted_scopes
            )
            or authorization.checked_at
            > now + timedelta(seconds=self._policy.maximum_clock_skew_seconds)
            or now - authorization.checked_at
            > timedelta(seconds=self._policy.maximum_authorization_age_seconds)
            or authorization.valid_until <= now
        ):
            raise CommentIngestionError(
                "AUTHORIZATION_INVALID", "comment authorization is not ready",
            )

    def _validate_batch(
        self,
        request: CommentIngestionRequest,
        target: CommentIngestionTarget,
        authorization: CommentReadAuthorization,
        batch: ProviderCommentBatch,
    ) -> None:
        if not isinstance(batch, ProviderCommentBatch):
            raise CommentIngestionError("BATCH_INVALID", "comment provider response is invalid")
        if (
            batch.request_id != request.request_id
            or batch.sync_id != request.sync_id
            or batch.publication_id != target.publication_id
            or batch.platform is not target.platform
            or batch.destination_id != target.destination_id
            or batch.remote_object_id != target.remote_object_id
            or batch.page_index != target.page_index
            or batch.cursor_fingerprint != target.cursor_fingerprint
            or batch.authorization_fingerprint != authorization.fingerprint
        ):
            raise CommentIngestionError(
                "BATCH_IDENTITY_MISMATCH", "comment provider response identity is invalid",
            )
        if len(batch.comments) > self._policy.page_size:
            raise CommentIngestionError(
                "BATCH_LIMIT_EXCEEDED", "comment provider response exceeds the page limit",
            )
        now = datetime.now(timezone.utc)
        if (
            batch.observed_at > now + timedelta(seconds=self._policy.maximum_clock_skew_seconds)
            or now - batch.observed_at
            > timedelta(seconds=self._policy.maximum_observation_age_seconds)
        ):
            raise CommentIngestionError(
                "BATCH_STALE", "comment provider response is outside the allowed time window",
            )
