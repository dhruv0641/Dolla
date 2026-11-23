"""Owner-scoped persistence for immutable platform reconciliation evidence."""

from __future__ import annotations

from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import (
    PlatformPublicationObservation,
    PlatformReconciliationRequest,
    PublicationPlatform,
    PublicationReconciliationRecord,
    PublicationReconciliationTarget,
    ReconciliationVerdict,
    RemotePublicationState,
    PlatformReconciliationError,
    classify_publication_state,
)


class PublicationReconciliationNotFound(RuntimeError):
    """The publication is absent or not owned by the requesting principal."""


class PublicationReconciliationNotAllowed(RuntimeError):
    """The channel or publication is not eligible for an independent read."""


class PublicationReconciliationConflict(RuntimeError):
    """An idempotency key or target snapshot identifies different evidence."""


_RECORD_COLUMNS = """r.request_id, r.publication_id, r.platform,
    r.local_status, r.remote_state, r.verdict, r.requires_human_review,
    r.target_fingerprint, r.observation_fingerprint, r.destination_id,
    r.remote_object_id, r.remote_url, r.provider_evidence_id,
    r.observed_at, r.created_at"""
_RETURN_COLUMNS = """request_id, publication_id, platform,
    local_status, remote_state, verdict, requires_human_review,
    target_fingerprint, observation_fingerprint, destination_id,
    remote_object_id, remote_url, provider_evidence_id,
    observed_at, created_at"""

_TARGET_SELECT = """SELECT p.id, b.owner_user_id, ch.platform, p.status,
    p.publication_state_version, p.request_fingerprint, p.channel_id,
    p.channel_external_id_snapshot, p.credentials_ref_snapshot,
    p.destination_fingerprint,
    CASE ch.platform
      WHEN 'YOUTUBE' THEN p.remote_post_id
      WHEN 'INSTAGRAM' THEN p.remote_post_id
      WHEN 'FACEBOOK' THEN p.remote_upload_id
    END AS remote_object_id,
    p.remote_url
  FROM publication_jobs AS p
  JOIN social_channels AS ch ON ch.id = p.channel_id
  JOIN brands AS b ON b.id = ch.brand_id
  WHERE p.id = %s AND b.owner_user_id = %s
    AND ch.enabled = true AND ch.permissions_status = 'VALID'
    AND ch.external_channel_id = p.channel_external_id_snapshot
    AND ch.credentials_ref = p.credentials_ref_snapshot
    AND (
      (ch.platform = 'YOUTUBE' AND p.publication_contract = 'YOUTUBE_V1') OR
      (ch.platform = 'INSTAGRAM' AND p.publication_contract = 'INSTAGRAM_REELS_V1') OR
      (ch.platform = 'FACEBOOK' AND p.publication_contract = 'FACEBOOK_REELS_V1')
    )"""


class PublicationReconciliationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_existing(
        self, request: PlatformReconciliationRequest,
    ) -> PublicationReconciliationRecord | None:
        if not isinstance(request, PlatformReconciliationRequest):
            raise ValueError("platform reconciliation request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_existing(connection, request)
                return None if row is None else self._record(row)
        except (PublicationReconciliationConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("publication reconciliation storage is unavailable") from exc

    async def reserve(
        self, request: PlatformReconciliationRequest, *, maximum_attempts: int,
    ) -> PublicationReconciliationTarget | PublicationReconciliationRecord:
        if not isinstance(request, PlatformReconciliationRequest):
            raise ValueError("platform reconciliation request is required")
        if type(maximum_attempts) is not int or not 1 <= maximum_attempts <= 1_000:
            raise ValueError("platform reconciliation attempt bound is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p",
                    (request.publication_id, request.owner_user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise PublicationReconciliationNotFound("publication not found")
                target = self._target(row)
                if target.remote_object_id is None:
                    raise PlatformReconciliationError(
                        "REMOTE_ID_UNAVAILABLE", "exact remote publication identity is unavailable",
                    )
                cursor = await connection.execute(
                    """SELECT publication_id, owner_user_id, target_fingerprint,
                              attempt_index, status
                       FROM publication_reconciliation_attempts
                       WHERE request_id = %s
                       FOR UPDATE""",
                    (request.request_id,),
                )
                attempt = await cursor.fetchone()
                if attempt is not None:
                    publication_id, owner_user_id, fingerprint, _, status = attempt
                    if (publication_id != request.publication_id
                            or owner_user_id != request.owner_user_id
                            or fingerprint.strip() != target.fingerprint):
                        raise PublicationReconciliationConflict(
                            "reconciliation request already identifies different work"
                        )
                    if status == "RECORDED":
                        existing = await self._find_existing(connection, request)
                        if existing is None:
                            raise RepositoryUnavailable(
                                "recorded reconciliation evidence is unavailable"
                            )
                        return self._record(existing)
                    raise PlatformReconciliationError(
                        "REQUEST_OUTCOME_UNKNOWN",
                        "reconciliation request is already reserved and requires operator review",
                    )
                cursor = await connection.execute(
                    """SELECT count(*)
                       FROM publication_reconciliation_attempts
                       WHERE publication_id = %s""",
                    (request.publication_id,),
                )
                count_row = await cursor.fetchone()
                attempt_count = count_row[0] if count_row is not None else 0
                if type(attempt_count) is not int or attempt_count < 0:
                    raise RepositoryUnavailable("stored reconciliation attempt count is invalid")
                if attempt_count >= maximum_attempts:
                    raise PlatformReconciliationError(
                        "OBSERVATION_LIMIT_REACHED",
                        "platform observation limit requires operator review",
                    )
                cursor = await connection.execute(
                    """INSERT INTO publication_reconciliation_attempts
                         (request_id, publication_id, owner_user_id,
                          target_fingerprint, attempt_index, status)
                       VALUES (%s, %s, %s, %s, %s, 'RESERVED')
                       RETURNING request_id""",
                    (
                        request.request_id, request.publication_id,
                        request.owner_user_id, target.fingerprint, attempt_count + 1,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise PublicationReconciliationConflict(
                        "reconciliation request could not be reserved"
                    )
                return target
        except (
            PlatformReconciliationError,
            PublicationReconciliationConflict,
            PublicationReconciliationNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("publication reconciliation storage is unavailable") from exc

    async def record(
        self, *, request: PlatformReconciliationRequest,
        target: PublicationReconciliationTarget,
        observation: PlatformPublicationObservation,
        verdict: ReconciliationVerdict,
    ) -> PublicationReconciliationRecord:
        if (not isinstance(request, PlatformReconciliationRequest)
                or not isinstance(target, PublicationReconciliationTarget)
                or not isinstance(observation, PlatformPublicationObservation)
                or not isinstance(verdict, ReconciliationVerdict)):
            raise ValueError("platform reconciliation evidence is invalid")
        if (target.publication_id != request.publication_id
                or target.owner_user_id != request.owner_user_id
                or observation.request_id != request.request_id
                or observation.publication_id != target.publication_id
                or observation.platform is not target.platform
                or observation.destination_id != target.destination_id
                or observation.remote_object_id != target.remote_object_id
                or verdict is not classify_publication_state(
                    target.local_status, observation.state,
                )):
            raise ValueError("platform reconciliation evidence identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_existing(connection, request)
                if existing is not None:
                    return self._require_replay(
                        existing, target=target, observation=observation, verdict=verdict,
                    )
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p",
                    (request.publication_id, request.owner_user_id),
                )
                current_row = await cursor.fetchone()
                if current_row is None:
                    raise PublicationReconciliationNotFound("publication not found")
                current = self._target(current_row)
                if current != target:
                    raise PublicationReconciliationConflict(
                        "publication changed while reconciliation was in progress"
                    )
                cursor = await connection.execute(
                    """SELECT publication_id, owner_user_id, target_fingerprint,
                              attempt_index, status
                       FROM publication_reconciliation_attempts
                       WHERE request_id = %s
                       FOR UPDATE""",
                    (request.request_id,),
                )
                attempt = await cursor.fetchone()
                if attempt is None:
                    raise PublicationReconciliationConflict(
                        "reconciliation request was not reserved"
                    )
                attempt_publication, attempt_owner, attempt_target, _, attempt_status = attempt
                if (attempt_publication != request.publication_id
                        or attempt_owner != request.owner_user_id
                        or attempt_target.strip() != target.fingerprint):
                    raise PublicationReconciliationConflict(
                        "reconciliation reservation identifies different work"
                    )
                if attempt_status == "RECORDED":
                    existing = await self._find_existing(connection, request)
                    if existing is None:
                        raise RepositoryUnavailable(
                            "recorded reconciliation evidence is unavailable"
                        )
                    return self._require_replay(
                        existing, target=target, observation=observation, verdict=verdict,
                    )
                if attempt_status != "RESERVED":
                    raise PublicationReconciliationConflict(
                        "reconciliation reservation state is invalid"
                    )
                cursor = await connection.execute(
                    f"""INSERT INTO publication_reconciliations
                        (request_id, publication_id, owner_user_id, platform,
                         local_status, publication_state_version, request_fingerprint,
                         channel_id, destination_id, destination_fingerprint,
                         remote_object_id, remote_state, remote_url,
                         provider_evidence_id, observed_at, target_fingerprint,
                         observation_fingerprint, verdict, requires_human_review)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (request_id) DO NOTHING
                       RETURNING {_RETURN_COLUMNS}""",
                    (
                        request.request_id, target.publication_id, request.owner_user_id,
                        target.platform.value, target.local_status,
                        target.publication_state_version, target.request_fingerprint,
                        target.channel_id, target.destination_id,
                        target.destination_fingerprint, observation.remote_object_id,
                        observation.state.value, observation.remote_url,
                        observation.evidence_id, observation.observed_at,
                        target.fingerprint, observation.fingerprint, verdict.value,
                        verdict is not ReconciliationVerdict.IN_SYNC,
                    ),
                )
                row = await cursor.fetchone()
                if row is not None:
                    cursor = await connection.execute(
                        """UPDATE publication_reconciliation_attempts
                           SET status = 'RECORDED', recorded_at = now()
                           WHERE request_id = %s AND status = 'RESERVED'
                           RETURNING request_id""",
                        (request.request_id,),
                    )
                    if await cursor.fetchone() is None:
                        raise PublicationReconciliationConflict(
                            "reconciliation reservation could not be completed"
                        )
                    return self._record(row)
                existing = await self._find_existing(connection, request)
                if existing is None:
                    raise PublicationReconciliationConflict(
                        "reconciliation request could not be persisted"
                    )
                return self._require_replay(
                    existing, target=target, observation=observation, verdict=verdict,
                )
        except (
            PublicationReconciliationConflict,
            PublicationReconciliationNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("publication reconciliation storage is unavailable") from exc

    @staticmethod
    async def _find_existing(connection, request: PlatformReconciliationRequest):
        cursor = await connection.execute(
            f"""SELECT {_RECORD_COLUMNS}
                FROM publication_reconciliations AS r
                JOIN publication_jobs AS p ON p.id = r.publication_id
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                WHERE r.request_id = %s AND b.owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        row = await cursor.fetchone()
        if row is not None and row[1] != request.publication_id:
            raise PublicationReconciliationConflict(
                "reconciliation request already identifies different work"
            )
        return row

    @classmethod
    def _require_replay(
        cls, row, *, target: PublicationReconciliationTarget,
        observation: PlatformPublicationObservation, verdict: ReconciliationVerdict,
    ) -> PublicationReconciliationRecord:
        record = cls._record(row)
        if (record.target_fingerprint != target.fingerprint
                or record.observation_fingerprint != observation.fingerprint
                or record.verdict is not verdict):
            raise PublicationReconciliationConflict(
                "reconciliation request already identifies different evidence"
            )
        return record

    @staticmethod
    def _target(row) -> PublicationReconciliationTarget:
        try:
            (
                publication_id, owner_user_id, platform, status, state_version,
                request_fingerprint, channel_id, destination_id, credentials_ref,
                destination_fingerprint, remote_object_id, remote_url,
            ) = row
            return PublicationReconciliationTarget(
                publication_id=publication_id,
                owner_user_id=owner_user_id,
                platform=PublicationPlatform(platform),
                local_status=status,
                publication_state_version=state_version,
                request_fingerprint=request_fingerprint.strip(),
                channel_id=channel_id,
                destination_id=destination_id,
                credentials_ref=credentials_ref,
                destination_fingerprint=destination_fingerprint.strip(),
                remote_object_id=remote_object_id,
                remote_url=remote_url,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored publication reconciliation target is invalid") from exc

    @staticmethod
    def _record(row) -> PublicationReconciliationRecord:
        try:
            (
                request_id, publication_id, platform, local_status, remote_state,
                verdict, requires_review, target_fingerprint, observation_fingerprint,
                destination_id, remote_object_id, remote_url, evidence_id,
                observed_at, created_at,
            ) = row
            return PublicationReconciliationRecord(
                request_id=request_id,
                publication_id=publication_id,
                platform=PublicationPlatform(platform),
                local_status=local_status,
                remote_state=RemotePublicationState(remote_state),
                verdict=ReconciliationVerdict(verdict),
                requires_human_review=requires_review,
                target_fingerprint=target_fingerprint.strip(),
                observation_fingerprint=observation_fingerprint.strip(),
                destination_id=destination_id,
                remote_object_id=remote_object_id,
                remote_url=remote_url,
                evidence_id=evidence_id,
                observed_at=observed_at,
                created_at=created_at,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored publication reconciliation evidence is invalid") from exc
