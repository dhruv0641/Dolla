"""Owner-scoped persistence for authorized, read-only comment ingestion."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from flowx_os.community.comments import (
    CommentIngestionBatch,
    CommentIngestionAbandonment,
    CommentIngestionError,
    CommentIngestionRequest,
    CommentIngestionTarget,
    CommentReadAuthorization,
    CommentState,
    ProviderCommentBatch,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import PublicationPlatform


class CommentIngestionNotFound(RuntimeError):
    """The publication is absent or concealed from the requesting owner."""


class CommentIngestionConflict(RuntimeError):
    """A sync, page, or idempotency key identifies different evidence."""


_BATCH_COLUMNS = """b.request_id, b.sync_id, b.publication_id, b.platform,
    b.destination_id, b.remote_object_id,
    b.page_index, b.target_fingerprint, b.batch_fingerprint,
    b.cursor_fingerprint, b.next_cursor_fingerprint, b.comment_count,
    b.has_more, b.provider_evidence_id, b.observed_at, b.created_at,
    b.authorization_fingerprint, b.authorization_scopes,
    b.authorization_checked_at, b.authorization_valid_until"""
_BATCH_RETURN_COLUMNS = """request_id, sync_id, publication_id, platform,
    destination_id, remote_object_id,
    page_index, target_fingerprint, batch_fingerprint,
    cursor_fingerprint, next_cursor_fingerprint, comment_count,
    has_more, provider_evidence_id, observed_at, created_at,
    authorization_fingerprint, authorization_scopes,
    authorization_checked_at, authorization_valid_until"""

_TARGET_SELECT = """SELECT p.id, b.owner_user_id, ch.platform,
    p.publication_state_version, p.request_fingerprint, p.channel_id,
    p.channel_external_id_snapshot, p.credentials_ref_snapshot,
    p.destination_fingerprint,
    CASE ch.platform
      WHEN 'YOUTUBE' THEN p.remote_post_id
      WHEN 'INSTAGRAM' THEN p.remote_post_id
      WHEN 'FACEBOOK' THEN p.remote_upload_id
    END AS remote_object_id,
    p.remote_url, r.request_id, r.target_fingerprint,
    r.observation_fingerprint, r.observed_at
  FROM publication_jobs AS p
  JOIN social_channels AS ch ON ch.id = p.channel_id
  JOIN brands AS b ON b.id = ch.brand_id
  JOIN LATERAL (
    SELECT request_id, target_fingerprint, observation_fingerprint, observed_at
    FROM publication_reconciliations
    WHERE publication_id = p.id
      AND platform = ch.platform
    ORDER BY observed_at DESC, request_id DESC
    LIMIT 1
  ) AS r ON true
  WHERE p.id = %s AND b.owner_user_id = %s
    AND p.status = 'PUBLISHED'
    AND ch.enabled = true AND ch.permissions_status = 'VALID'
    AND r.request_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM publication_reconciliations AS latest
      WHERE latest.request_id = r.request_id
        AND latest.local_status = 'PUBLISHED'
        AND latest.remote_state = 'PUBLISHED'
        AND latest.verdict = 'IN_SYNC'
        AND latest.requires_human_review = false
        AND latest.remote_object_id = CASE ch.platform
          WHEN 'YOUTUBE' THEN p.remote_post_id
          WHEN 'INSTAGRAM' THEN p.remote_post_id
          WHEN 'FACEBOOK' THEN p.remote_upload_id
        END
        AND latest.remote_url = p.remote_url
    )
    AND ch.external_channel_id = p.channel_external_id_snapshot
    AND ch.credentials_ref = p.credentials_ref_snapshot
    AND (
      (ch.platform = 'YOUTUBE' AND p.publication_contract = 'YOUTUBE_V1') OR
      (ch.platform = 'INSTAGRAM' AND p.publication_contract = 'INSTAGRAM_REELS_V1') OR
      (ch.platform = 'FACEBOOK' AND p.publication_contract = 'FACEBOOK_REELS_V1')
    )"""


class CommentIngestionRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_existing(
        self, request: CommentIngestionRequest,
    ) -> CommentIngestionBatch | None:
        if not isinstance(request, CommentIngestionRequest):
            raise ValueError("comment ingestion request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_existing(connection, request)
                return None if row is None else self._batch(row)
        except (CommentIngestionConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("comment ingestion storage is unavailable") from exc

    async def reserve(
        self,
        request: CommentIngestionRequest,
        *,
        maximum_pages: int,
        maximum_reconciliation_age_seconds: int,
        maximum_provider_attempts: int,
        reservation_lease_seconds: int,
    ) -> CommentIngestionTarget | CommentIngestionBatch | CommentIngestionAbandonment:
        if not isinstance(request, CommentIngestionRequest):
            raise ValueError("comment ingestion request is required")
        if type(maximum_pages) is not int or not 1 <= maximum_pages <= 1_000:
            raise ValueError("comment ingestion page bound is invalid")
        if (
            type(maximum_reconciliation_age_seconds) is not int
            or not 300 <= maximum_reconciliation_age_seconds <= 86_400
        ):
            raise ValueError("comment ingestion authorization age is invalid")
        if request.page_index > maximum_pages:
            raise CommentIngestionError(
                "PAGE_LIMIT_REACHED", "comment sync page limit requires operator review",
            )
        if (
            type(maximum_provider_attempts) is not int
            or not 1 <= maximum_provider_attempts <= 10
            or type(reservation_lease_seconds) is not int
            or not 30 <= reservation_lease_seconds <= 900
        ):
            raise ValueError("comment ingestion retry policy is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p, ch",
                    (request.publication_id, request.owner_user_id),
                )
                target_row = await cursor.fetchone()
                if target_row is None:
                    raise CommentIngestionNotFound("eligible publication not found")
                authorization_now = datetime.now(timezone.utc)
                reconciliation_observed_at = target_row[14]
                if (
                    not isinstance(reconciliation_observed_at, datetime)
                    or reconciliation_observed_at.tzinfo is None
                    or reconciliation_observed_at.utcoffset() is None
                    or reconciliation_observed_at > authorization_now + timedelta(minutes=2)
                    or authorization_now - reconciliation_observed_at
                    > timedelta(seconds=maximum_reconciliation_age_seconds)
                ):
                    raise CommentIngestionError(
                        "AUTHORIZATION_STALE",
                        "verified publication authorization is outside the allowed time window",
                    )

                cursor = await connection.execute(
                    """SELECT publication_id, owner_user_id, platform,
                              target_fingerprint, reconciliation_request_id,
                              last_page_index, next_cursor, status
                       FROM comment_ingestion_runs
                       WHERE sync_id = %s
                       FOR UPDATE""",
                    (request.sync_id,),
                )
                run = await cursor.fetchone()
                if run is None:
                    cursor = await connection.execute(
                        """SELECT sync_id
                           FROM comment_ingestion_runs
                           WHERE publication_id = %s AND status = 'ACTIVE'
                           FOR UPDATE""",
                        (request.publication_id,),
                    )
                    active = await cursor.fetchone()
                    if active is not None:
                        raise CommentIngestionConflict(
                            "another comment sync is already active for this publication"
                        )
                    if request.page_index != 1:
                        raise CommentIngestionConflict("a comment sync must start at page one")
                    target = self._target(
                        target_row,
                        request=request,
                        page_index=1,
                        page_cursor=None,
                        reservation_generation=1,
                    )
                    cursor = await connection.execute(
                        """INSERT INTO comment_ingestion_runs
                             (sync_id, publication_id, owner_user_id, platform,
                              target_fingerprint, reconciliation_request_id,
                              last_page_index, next_cursor, status)
                           VALUES (%s, %s, %s, %s, %s, %s, 0, NULL, 'ACTIVE')
                           RETURNING sync_id""",
                        (
                            request.sync_id,
                            request.publication_id,
                            request.owner_user_id,
                            target.platform.value,
                            target.fingerprint,
                            target.reconciliation_request_id,
                        ),
                    )
                    if await cursor.fetchone() is None:
                        raise CommentIngestionConflict("comment sync could not be created")
                else:
                    (
                        run_publication,
                        run_owner,
                        run_platform,
                        run_target,
                        run_reconciliation,
                        last_page,
                        next_cursor,
                        run_status,
                    ) = run
                    target = self._target(
                        target_row,
                        request=request,
                        page_index=request.page_index,
                        page_cursor=next_cursor,
                        reservation_generation=1,
                    )
                    if (
                        run_publication != request.publication_id
                        or run_owner != request.owner_user_id
                        or run_platform != target.platform.value
                        or run_target.strip() != target.fingerprint
                        or run_reconciliation != target.reconciliation_request_id
                    ):
                        raise CommentIngestionConflict(
                            "comment sync identifies different publication evidence"
                        )
                    if run_status == "COMPLETE":
                        raise CommentIngestionError(
                            "SYNC_COMPLETE", "comment sync is already complete",
                        )
                    if run_status == "ABANDONED":
                        raise CommentIngestionError(
                            "SYNC_ABANDONED", "comment sync was abandoned",
                        )
                    if (
                        run_status != "ACTIVE"
                        or type(last_page) is not int
                        or request.page_index != last_page + 1
                        or (request.page_index > 1 and next_cursor is None)
                    ):
                        raise CommentIngestionConflict("comment sync page sequence is invalid")

                cursor = await connection.execute(
                    """SELECT sync_id, publication_id, owner_user_id,
                              target_fingerprint, page_index, cursor_fingerprint,
                              status, attempt_count,
                              lease_expires_at <= clock_timestamp() AS lease_expired
                       FROM comment_ingestion_attempts
                       WHERE request_id = %s
                       FOR UPDATE""",
                    (request.request_id,),
                )
                attempt = await cursor.fetchone()
                if attempt is not None:
                    (
                        attempt_sync,
                        attempt_publication,
                        attempt_owner,
                        attempt_target,
                        attempt_page,
                        attempt_cursor,
                        attempt_status,
                        attempt_count,
                        lease_expired,
                    ) = attempt
                    target = replace(target, reservation_generation=attempt_count)
                    if (
                        attempt_sync != request.sync_id
                        or attempt_publication != request.publication_id
                        or attempt_owner != request.owner_user_id
                        or attempt_target.strip() != target.fingerprint
                        or attempt_page != request.page_index
                        or attempt_cursor.strip() != target.cursor_fingerprint
                    ):
                        raise CommentIngestionConflict(
                            "comment ingestion request identifies different work"
                        )
                    if attempt_status == "RECORDED":
                        existing = await self._find_existing(connection, request)
                        if existing is None:
                            raise RepositoryUnavailable(
                                "recorded comment ingestion batch is unavailable"
                            )
                        return self._batch(existing)
                    if attempt_status == "ABANDONED":
                        raise CommentIngestionError(
                            "REQUEST_ABANDONED", "comment ingestion request was abandoned",
                        )
                    if attempt_status != "RESERVED" or lease_expired is not True:
                        raise CommentIngestionError(
                            "REQUEST_IN_PROGRESS", "comment ingestion request is still leased",
                        )
                    if attempt_count >= maximum_provider_attempts:
                        cursor = await connection.execute(
                            """UPDATE comment_ingestion_attempts
                               SET status = 'ABANDONED', abandoned_at = clock_timestamp(),
                                   lease_expires_at = NULL,
                                   last_error_code = 'RETRY_LIMIT_REACHED'
                               WHERE request_id = %s AND status = 'RESERVED'
                               RETURNING request_id""",
                            (request.request_id,),
                        )
                        if await cursor.fetchone() is None:
                            raise CommentIngestionConflict(
                                "comment ingestion request could not be abandoned"
                            )
                        cursor = await connection.execute(
                            """UPDATE comment_ingestion_runs
                               SET status = 'ABANDONED', next_cursor = NULL,
                                   updated_at = clock_timestamp()
                               WHERE sync_id = %s AND status = 'ACTIVE'
                               RETURNING sync_id""",
                            (request.sync_id,),
                        )
                        if await cursor.fetchone() is None:
                            raise CommentIngestionConflict(
                                "comment sync could not be abandoned"
                            )
                        return CommentIngestionAbandonment(
                            request_id=request.request_id,
                            sync_id=request.sync_id,
                            code="RETRY_LIMIT_REACHED",
                        )
                    cursor = await connection.execute(
                        """UPDATE comment_ingestion_attempts
                           SET attempt_count = attempt_count + 1,
                               lease_expires_at = clock_timestamp()
                                 + (%s * interval '1 second'),
                               last_error_code = NULL
                           WHERE request_id = %s AND status = 'RESERVED'
                             AND lease_expires_at <= clock_timestamp()
                           RETURNING request_id""",
                        (reservation_lease_seconds, request.request_id),
                    )
                    if await cursor.fetchone() is None:
                        raise CommentIngestionConflict(
                            "comment ingestion retry could not be leased"
                        )
                    return replace(
                        target, reservation_generation=attempt_count + 1,
                    )

                cursor = await connection.execute(
                    """SELECT request_id
                       FROM comment_ingestion_attempts
                       WHERE sync_id = %s AND page_index = %s
                       FOR UPDATE""",
                    (request.sync_id, request.page_index),
                )
                if await cursor.fetchone() is not None:
                    raise CommentIngestionConflict("comment sync page is already reserved")
                cursor = await connection.execute(
                    """INSERT INTO comment_ingestion_attempts
                         (request_id, sync_id, publication_id, owner_user_id,
                          target_fingerprint, page_index, cursor_fingerprint,
                          status, attempt_count, lease_expires_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'RESERVED', 1,
                               clock_timestamp() + (%s * interval '1 second'))
                       RETURNING request_id""",
                    (
                        request.request_id,
                        request.sync_id,
                        request.publication_id,
                        request.owner_user_id,
                        target.fingerprint,
                        request.page_index,
                        target.cursor_fingerprint,
                        reservation_lease_seconds,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise CommentIngestionConflict("comment ingestion page could not be reserved")
                return target
        except (
            CommentIngestionConflict,
            CommentIngestionError,
            CommentIngestionNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("comment ingestion storage is unavailable") from exc

    async def assert_network_ready(self, target: CommentIngestionTarget) -> None:
        if not isinstance(target, CommentIngestionTarget):
            raise ValueError("comment ingestion target is required")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR KEY SHARE OF p, ch",
                    (target.publication_id, target.owner_user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CommentIngestionNotFound(
                        "comment ingestion authorization is not ready"
                    )
                current = self._target(
                    row,
                    request=CommentIngestionRequest(
                        request_id=target.reservation_request_id,
                        sync_id=target.reservation_sync_id,
                        publication_id=target.publication_id,
                        owner_user_id=target.owner_user_id,
                        page_index=target.page_index,
                    ),
                    page_index=target.page_index,
                    page_cursor=target.cursor,
                    reservation_generation=target.reservation_generation,
                )
                if current != target:
                    raise CommentIngestionConflict(
                        "comment ingestion authorization changed"
                    )
                cursor = await connection.execute(
                    """SELECT request_id
                       FROM comment_ingestion_attempts
                       WHERE request_id = %s AND sync_id = %s
                         AND publication_id = %s AND owner_user_id = %s
                         AND target_fingerprint = %s AND page_index = %s
                         AND cursor_fingerprint = %s AND status = 'RESERVED'
                         AND attempt_count = %s
                         AND lease_expires_at > clock_timestamp()
                       FOR KEY SHARE""",
                    (
                        target.reservation_request_id,
                        target.reservation_sync_id,
                        target.publication_id,
                        target.owner_user_id,
                        target.fingerprint,
                        target.page_index,
                        target.cursor_fingerprint,
                        target.reservation_generation,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise CommentIngestionConflict(
                        "comment ingestion lease changed"
                    )
        except (
            CommentIngestionConflict,
            CommentIngestionNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("comment authorization storage is unavailable") from exc

    async def record_failure(
        self,
        *,
        request: CommentIngestionRequest,
        target: CommentIngestionTarget,
        error_code: str,
    ) -> None:
        if (
            not isinstance(request, CommentIngestionRequest)
            or not isinstance(target, CommentIngestionTarget)
            or target.reservation_request_id != request.request_id
            or target.reservation_sync_id != request.sync_id
            or not isinstance(error_code, str)
            or not error_code
            or len(error_code) > 64
            or not error_code.replace("_", "").isalnum()
            or error_code != error_code.upper()
        ):
            raise ValueError("comment ingestion failure evidence is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE comment_ingestion_attempts
                       SET last_error_code = %s,
                           lease_expires_at = clock_timestamp()
                       WHERE request_id = %s AND sync_id = %s
                         AND publication_id = %s AND owner_user_id = %s
                         AND target_fingerprint = %s
                         AND page_index = %s AND status = 'RESERVED'
                         AND attempt_count = %s
                         AND lease_expires_at > clock_timestamp()
                       RETURNING request_id""",
                    (
                        error_code,
                        request.request_id,
                        request.sync_id,
                        request.publication_id,
                        request.owner_user_id,
                        target.fingerprint,
                        request.page_index,
                        target.reservation_generation,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise CommentIngestionConflict(
                        "comment ingestion failure could not be recorded"
                    )
        except (CommentIngestionConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("comment failure storage is unavailable") from exc

    async def record(
        self,
        *,
        request: CommentIngestionRequest,
        target: CommentIngestionTarget,
        batch: ProviderCommentBatch,
        authorization: CommentReadAuthorization,
    ) -> CommentIngestionBatch:
        self._validate_record(request, target, batch, authorization)
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_existing(connection, request)
                if existing is not None:
                    return self._require_replay(existing, target=target, provider_batch=batch)

                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p, ch",
                    (request.publication_id, request.owner_user_id),
                )
                current_row = await cursor.fetchone()
                if current_row is None:
                    raise CommentIngestionNotFound("eligible publication not found")
                current = self._target(
                    current_row,
                    request=request,
                    page_index=target.page_index,
                    page_cursor=target.cursor,
                    reservation_generation=target.reservation_generation,
                )
                if current != target:
                    raise CommentIngestionConflict(
                        "publication changed while comments were being observed"
                    )

                cursor = await connection.execute(
                    """SELECT publication_id, owner_user_id, platform,
                              target_fingerprint, reconciliation_request_id,
                              last_page_index, next_cursor, status
                       FROM comment_ingestion_runs
                       WHERE sync_id = %s
                       FOR UPDATE""",
                    (request.sync_id,),
                )
                run = await cursor.fetchone()
                if run is None:
                    raise CommentIngestionConflict("comment sync reservation is missing")
                if (
                    run[0] != request.publication_id
                    or run[1] != request.owner_user_id
                    or run[2] != target.platform.value
                    or run[3].strip() != target.fingerprint
                    or run[4] != target.reconciliation_request_id
                    or run[5] != request.page_index - 1
                    or run[6] != target.cursor
                    or run[7] != "ACTIVE"
                ):
                    raise CommentIngestionConflict("comment sync reservation changed")

                cursor = await connection.execute(
                    """SELECT sync_id, publication_id, owner_user_id,
                              target_fingerprint, page_index, cursor_fingerprint,
                              status, attempt_count,
                              lease_expires_at > clock_timestamp() AS lease_current
                       FROM comment_ingestion_attempts
                       WHERE request_id = %s
                       FOR UPDATE""",
                    (request.request_id,),
                )
                attempt = await cursor.fetchone()
                if attempt is None:
                    raise CommentIngestionConflict("comment ingestion reservation is missing")
                if (
                    attempt[0] != request.sync_id
                    or attempt[1] != request.publication_id
                    or attempt[2] != request.owner_user_id
                    or attempt[3].strip() != target.fingerprint
                    or attempt[4] != request.page_index
                    or attempt[5].strip() != target.cursor_fingerprint
                    or attempt[6] != "RESERVED"
                    or attempt[7] != target.reservation_generation
                    or attempt[8] is not True
                ):
                    raise CommentIngestionConflict("comment ingestion reservation changed")

                comment_fingerprints = [comment.fingerprint for comment in batch.comments]
                comment_remote_ids = [comment.remote_comment_id for comment in batch.comments]
                cursor = await connection.execute(
                    f"""INSERT INTO comment_ingestion_batches
                         (request_id, sync_id, publication_id, owner_user_id, platform,
                          destination_id, remote_object_id, page_index,
                          target_fingerprint, cursor_fingerprint,
                          next_cursor_fingerprint, comment_count, comment_remote_ids,
                          comment_fingerprints,
                          has_more, provider_evidence_id, observed_at, batch_fingerprint,
                          authorization_fingerprint, authorization_scopes,
                          authorization_checked_at, authorization_valid_until)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s)
                       ON CONFLICT (request_id) DO NOTHING
                       RETURNING {_BATCH_RETURN_COLUMNS}""",
                    (
                        request.request_id,
                        request.sync_id,
                        request.publication_id,
                        request.owner_user_id,
                        target.platform.value,
                        target.destination_id,
                        target.remote_object_id,
                        request.page_index,
                        target.fingerprint,
                        target.cursor_fingerprint,
                        batch.next_cursor_fingerprint,
                        len(batch.comments),
                        comment_remote_ids,
                        comment_fingerprints,
                        batch.has_more,
                        batch.evidence_id,
                        batch.observed_at,
                        batch.fingerprint,
                        batch.authorization_fingerprint,
                        list(authorization.granted_scopes),
                        authorization.checked_at,
                        authorization.valid_until,
                    ),
                )
                stored_row = await cursor.fetchone()
                if stored_row is None:
                    existing = await self._find_existing(connection, request)
                    if existing is None:
                        raise CommentIngestionConflict(
                            "comment ingestion batch could not be persisted"
                        )
                    return self._require_replay(
                        existing, target=target, provider_batch=batch,
                    )

                for ordinal, comment in enumerate(batch.comments, 1):
                    cursor = await connection.execute(
                        """SELECT id
                           FROM community_comment_versions
                           WHERE publication_id = %s
                             AND remote_comment_id = %s
                             AND comment_fingerprint = %s""",
                        (
                            request.publication_id,
                            comment.remote_comment_id,
                            comment.fingerprint,
                        ),
                    )
                    version_row = await cursor.fetchone()
                    if version_row is None:
                        cursor = await connection.execute(
                            """INSERT INTO community_comment_versions
                             (publication_id, owner_user_id, platform,
                              destination_id, remote_object_id, remote_comment_id,
                              parent_remote_comment_id, author_external_id_hash,
                              comment_text, state, published_at, provider_updated_at,
                              comment_fingerprint, first_batch_request_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                   %s, %s, %s, %s, %s, %s)
                           ON CONFLICT
                             (publication_id, remote_comment_id, comment_fingerprint)
                           DO NOTHING
                           RETURNING id""",
                            (
                                request.publication_id,
                                request.owner_user_id,
                                target.platform.value,
                                target.destination_id,
                                target.remote_object_id,
                                comment.remote_comment_id,
                                comment.parent_remote_comment_id,
                                comment.author_external_id_hash,
                                comment.text,
                                comment.state.value,
                                comment.published_at,
                                comment.provider_updated_at,
                                comment.fingerprint,
                                request.request_id,
                            ),
                        )
                        version_row = await cursor.fetchone()
                        if version_row is None:
                            cursor = await connection.execute(
                                """SELECT id
                                   FROM community_comment_versions
                                   WHERE publication_id = %s
                                     AND remote_comment_id = %s
                                     AND comment_fingerprint = %s""",
                                (
                                    request.publication_id,
                                    comment.remote_comment_id,
                                    comment.fingerprint,
                                ),
                            )
                            version_row = await cursor.fetchone()
                    if version_row is None:
                        raise CommentIngestionConflict(
                            "comment version could not be persisted"
                        )
                    cursor = await connection.execute(
                        """INSERT INTO comment_ingestion_batch_items
                             (batch_request_id, ordinal, comment_version_id)
                           VALUES (%s, %s, %s)
                           RETURNING batch_request_id""",
                        (request.request_id, ordinal, version_row[0]),
                    )
                    if await cursor.fetchone() is None:
                        raise CommentIngestionConflict(
                            "comment batch item could not be persisted"
                        )

                cursor = await connection.execute(
                    """UPDATE comment_ingestion_runs
                       SET last_page_index = %s,
                           next_cursor = %s,
                           status = %s,
                           updated_at = now()
                       WHERE sync_id = %s AND status = 'ACTIVE'
                       RETURNING sync_id""",
                    (
                        request.page_index,
                        batch.next_cursor,
                        "ACTIVE" if batch.has_more else "COMPLETE",
                        request.sync_id,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise CommentIngestionConflict("comment sync could not be advanced")
                cursor = await connection.execute(
                    """UPDATE comment_ingestion_attempts
                       SET status = 'RECORDED', recorded_at = now(),
                           lease_expires_at = NULL
                       WHERE request_id = %s AND status = 'RESERVED'
                       RETURNING request_id""",
                    (request.request_id,),
                )
                if await cursor.fetchone() is None:
                    raise CommentIngestionConflict(
                        "comment ingestion reservation could not be completed"
                    )
                return self._batch(stored_row)
        except (
            CommentIngestionConflict,
            CommentIngestionNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("comment ingestion storage is unavailable") from exc

    @staticmethod
    async def _find_existing(connection, request: CommentIngestionRequest):
        cursor = await connection.execute(
            f"""SELECT {_BATCH_COLUMNS}
                FROM comment_ingestion_batches AS b
                JOIN publication_jobs AS p ON p.id = b.publication_id
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS br ON br.id = ch.brand_id
                WHERE b.request_id = %s AND br.owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        row = await cursor.fetchone()
        if row is not None and (
            row[1] != request.sync_id
            or row[2] != request.publication_id
            or row[6] != request.page_index
        ):
            raise CommentIngestionConflict(
                "comment ingestion request already identifies different work"
            )
        return row

    @classmethod
    def _require_replay(
        cls,
        row,
        *,
        target: CommentIngestionTarget,
        provider_batch: ProviderCommentBatch,
    ) -> CommentIngestionBatch:
        stored = cls._batch(row)
        if (
            stored.target_fingerprint != target.fingerprint
            or stored.batch_fingerprint != provider_batch.fingerprint
        ):
            raise CommentIngestionConflict(
                "comment ingestion request already identifies different evidence"
            )
        return stored

    @staticmethod
    def _validate_record(
        request: CommentIngestionRequest,
        target: CommentIngestionTarget,
        batch: ProviderCommentBatch,
        authorization: CommentReadAuthorization,
    ) -> None:
        if (
            not isinstance(request, CommentIngestionRequest)
            or not isinstance(target, CommentIngestionTarget)
            or not isinstance(batch, ProviderCommentBatch)
            or not isinstance(authorization, CommentReadAuthorization)
        ):
            raise ValueError("comment ingestion evidence is invalid")
        if (
            target.publication_id != request.publication_id
            or target.owner_user_id != request.owner_user_id
            or target.reservation_request_id != request.request_id
            or target.reservation_sync_id != request.sync_id
            or target.page_index != request.page_index
            or batch.request_id != request.request_id
            or batch.sync_id != request.sync_id
            or batch.publication_id != request.publication_id
            or batch.platform is not target.platform
            or batch.destination_id != target.destination_id
            or batch.remote_object_id != target.remote_object_id
            or batch.page_index != request.page_index
            or batch.cursor_fingerprint != target.cursor_fingerprint
            or authorization.platform is not target.platform
            or authorization.destination_id != target.destination_id
            or batch.authorization_fingerprint != authorization.fingerprint
        ):
            raise ValueError("comment ingestion evidence identity is invalid")

    @staticmethod
    def _target(
        row,
        *,
        request: CommentIngestionRequest,
        page_index: int,
        page_cursor: str | None,
        reservation_generation: int,
    ) -> CommentIngestionTarget:
        try:
            (
                publication_id,
                owner_user_id,
                platform,
                state_version,
                request_fingerprint,
                channel_id,
                destination_id,
                credentials_ref,
                destination_fingerprint,
                remote_object_id,
                remote_url,
                reconciliation_request_id,
                reconciliation_target,
                reconciliation_observation,
                reconciliation_observed_at,
            ) = row
            return CommentIngestionTarget(
                reservation_request_id=request.request_id,
                reservation_sync_id=request.sync_id,
                reservation_generation=reservation_generation,
                publication_id=publication_id,
                owner_user_id=owner_user_id,
                platform=PublicationPlatform(platform),
                publication_state_version=state_version,
                publication_request_fingerprint=request_fingerprint.strip(),
                channel_id=channel_id,
                destination_id=destination_id,
                credentials_ref=credentials_ref,
                destination_fingerprint=destination_fingerprint.strip(),
                remote_object_id=remote_object_id,
                remote_url=remote_url,
                reconciliation_request_id=reconciliation_request_id,
                reconciliation_target_fingerprint=reconciliation_target.strip(),
                reconciliation_observation_fingerprint=reconciliation_observation.strip(),
                reconciliation_observed_at=reconciliation_observed_at,
                page_index=page_index,
                cursor=page_cursor,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored comment ingestion target is invalid") from exc

    @staticmethod
    def _batch(row) -> CommentIngestionBatch:
        try:
            (
                request_id,
                sync_id,
                publication_id,
                platform,
                destination_id,
                remote_object_id,
                page_index,
                target_fingerprint,
                batch_fingerprint,
                cursor_fingerprint,
                next_cursor_fingerprint,
                comment_count,
                has_more,
                evidence_id,
                observed_at,
                created_at,
                authorization_fingerprint,
                authorization_scopes,
                authorization_checked_at,
                authorization_valid_until,
            ) = row
            return CommentIngestionBatch(
                request_id=request_id,
                sync_id=sync_id,
                publication_id=publication_id,
                platform=PublicationPlatform(platform),
                destination_id=destination_id,
                remote_object_id=remote_object_id,
                page_index=page_index,
                target_fingerprint=target_fingerprint.strip(),
                batch_fingerprint=batch_fingerprint.strip(),
                cursor_fingerprint=cursor_fingerprint.strip(),
                next_cursor_fingerprint=next_cursor_fingerprint.strip(),
                comment_count=comment_count,
                has_more=has_more,
                evidence_id=evidence_id,
                observed_at=observed_at,
                created_at=created_at,
                authorization_fingerprint=authorization_fingerprint.strip(),
                authorization_scopes=tuple(authorization_scopes),
                authorization_checked_at=authorization_checked_at,
                authorization_valid_until=authorization_valid_until,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored comment ingestion batch is invalid") from exc
