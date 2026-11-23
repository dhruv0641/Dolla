"""Owner-scoped approval and delivery reservation persistence."""

from __future__ import annotations

from datetime import timedelta, timezone
from uuid import UUID

from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.outbox import enqueue_job
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import PublicationPlatform
from flowx_os.publishing.scheduling import (
    PublicationApprovalDecision,
    PublicationApprovalRecord,
    PublicationApprovalRequest,
    PublicationDeliveryState,
    PublicationSchedulePolicy,
    PublicationScheduleRecord,
    PublicationScheduleRequest,
    PublicationSchedulingError,
)


class PublicationScheduleNotFound(RuntimeError):
    """The publication is absent or belongs to another owner."""


class PublicationScheduleConflict(RuntimeError):
    """An idempotency key, approval or duplicate slot conflicts."""


class PublicationScheduleNotAllowed(RuntimeError):
    """Current evidence does not permit approval or scheduling."""


_TARGET_SELECT = """SELECT p.id, b.owner_user_id, ch.platform, p.status,
    p.publication_contract, p.request_fingerprint, p.publication_state_version,
    p.content_id, p.channel_id, p.asset_id, p.artifact_version,
    p.destination_fingerprint, b.timezone, ch.enabled, ch.permissions_status,
    ch.external_channel_id = p.channel_external_id_snapshot,
    ch.credentials_ref = p.credentials_ref_snapshot,
    p.remote_upload_id, p.remote_post_id, p.instagram_phase, p.facebook_phase
  FROM publication_jobs AS p
  JOIN social_channels AS ch ON ch.id = p.channel_id
  JOIN brands AS b ON b.id = ch.brand_id
  WHERE p.id = %s AND b.owner_user_id = %s"""

_APPROVAL_COLUMNS = """a.id, a.request_id, a.publication_id,
    a.owner_user_id, a.decision, a.valid_until, a.reason, a.platform,
    a.content_id, a.channel_id, a.asset_id, a.artifact_version,
    a.publication_state_version, a.destination_fingerprint, a.created_at"""

_SCHEDULE_COLUMNS = """r.id, r.request_id, r.publication_id, r.approval_id,
    r.owner_user_id, r.platform, r.channel_id, r.content_id, r.asset_id,
    r.artifact_version, r.local_scheduled_at, r.timezone_name,
    r.schedule_fold, r.utc_offset_minutes, r.scheduled_at_utc, r.state,
    r.outbox_job_id, r.created_at"""


class PublicationScheduleRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def record_approval(
        self, request: PublicationApprovalRequest,
    ) -> PublicationApprovalRecord:
        if not isinstance(request, PublicationApprovalRequest):
            raise ValueError("publication approval request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_approval_request(connection, request)
                if existing is not None:
                    record = self._approval(existing)
                    if (record.approval_id != request.approval_id
                            or record.publication_id != request.publication_id
                            or record.decision is not request.decision
                            or record.valid_until != request.valid_until
                            or record.reason != request.reason):
                        raise PublicationScheduleConflict(
                            "approval request already identifies different work"
                        )
                    return record
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p, ch",
                    (request.publication_id, request.owner_user_id),
                )
                target = await cursor.fetchone()
                if target is None:
                    raise PublicationScheduleNotFound("publication not found")
                values = self._require_approvable(target)
                cursor = await connection.execute(
                    f"""INSERT INTO publication_delivery_approvals
                        (id, request_id, publication_id, owner_user_id,
                         approver_user_id, decision, reason, valid_until,
                         publication_request_fingerprint, publication_state_version,
                         content_id, channel_id, asset_id, artifact_version,
                         platform, destination_fingerprint)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING {_APPROVAL_COLUMNS.replace('a.', '')}""",
                    (
                        request.approval_id, request.request_id, request.publication_id,
                        request.owner_user_id, request.approver_user_id,
                        request.decision.value, request.reason, request.valid_until,
                        values["request_fingerprint"], values["state_version"],
                        values["content_id"], values["channel_id"], values["asset_id"],
                        values["artifact_version"], values["platform"].value,
                        values["destination_fingerprint"],
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise PublicationScheduleConflict("approval could not be recorded")
                return self._approval(row)
        except (
            PublicationScheduleConflict,
            PublicationScheduleNotAllowed,
            PublicationScheduleNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("publication approval storage is unavailable") from exc

    async def schedule(
        self, request: PublicationScheduleRequest, *, now,
        policy: PublicationSchedulePolicy,
    ) -> PublicationScheduleRecord:
        if (not isinstance(request, PublicationScheduleRequest)
                or not isinstance(policy, PublicationSchedulePolicy)
                or now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("publication schedule evidence is invalid")
        now_utc = now.astimezone(timezone.utc)
        scheduled = request.scheduled_at_utc
        if (scheduled < now_utc + timedelta(seconds=policy.minimum_lead_seconds)
                or scheduled > now_utc + timedelta(days=policy.maximum_horizon_days)):
            raise PublicationSchedulingError(
                "SCHEDULE_WINDOW_INVALID", "publication schedule is outside the allowed window",
            )
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_schedule_request(connection, request)
                if existing is not None:
                    record = self._schedule(existing)
                    if (record.schedule_id != request.schedule_id
                            or record.publication_id != request.publication_id
                            or record.approval_id != request.approval_id
                            or record.local_scheduled_at != request.local_scheduled_at
                            or record.timezone_name != request.timezone_name
                            or record.fold != request.fold):
                        raise PublicationScheduleConflict(
                            "schedule request already identifies different work"
                        )
                    return record
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p, ch",
                    (request.publication_id, request.owner_user_id),
                )
                target = await cursor.fetchone()
                if target is None:
                    raise PublicationScheduleNotFound("publication not found")
                values = self._require_approvable(target)
                if values["timezone_name"] != request.timezone_name:
                    raise PublicationScheduleNotAllowed("brand timezone changed")
                cursor = await connection.execute(
                    f"""SELECT {_APPROVAL_COLUMNS}
                        FROM publication_delivery_approvals AS a
                        WHERE a.id = %s AND a.publication_id = %s
                          AND a.owner_user_id = %s
                        FOR KEY SHARE OF a""",
                    (request.approval_id, request.publication_id, request.owner_user_id),
                )
                approval_row = await cursor.fetchone()
                if approval_row is None:
                    raise PublicationScheduleNotAllowed("publication approval is unavailable")
                approval = self._approval(approval_row)
                if (approval.decision is not PublicationApprovalDecision.APPROVE
                        or approval.valid_until <= scheduled
                        or approval.platform is not values["platform"]
                        or approval.content_id != values["content_id"]
                        or approval.channel_id != values["channel_id"]
                        or approval.asset_id != values["asset_id"]
                        or approval.artifact_version != values["artifact_version"]
                        or approval.publication_state_version != values["state_version"]
                        or approval.destination_fingerprint != values["destination_fingerprint"]):
                    raise PublicationScheduleNotAllowed("publication approval is stale or rejected")
                day_start, day_end = request.day_bounds_utc
                cursor = await connection.execute(
                    """SELECT count(*) FROM publication_delivery_reservations
                       WHERE channel_id = %s AND state <> 'CANCELLED'
                         AND scheduled_at_utc >= %s AND scheduled_at_utc < %s""",
                    (values["channel_id"], day_start, day_end),
                )
                count_row = await cursor.fetchone()
                active_count = count_row[0] if count_row is not None else 0
                if type(active_count) is not int or active_count < 0:
                    raise RepositoryUnavailable("stored publication schedule count is invalid")
                if active_count >= policy.maximum_per_local_day:
                    raise PublicationSchedulingError(
                        "DAILY_CAP_REACHED", "publication channel daily cap is reached",
                    )
                cursor = await connection.execute(
                    """SELECT 1 FROM publication_delivery_reservations
                       WHERE channel_id = %s AND state <> 'CANCELLED'
                         AND abs(EXTRACT(EPOCH FROM (scheduled_at_utc - %s))) < %s
                       LIMIT 1""",
                    (values["channel_id"], scheduled, policy.minimum_gap_seconds),
                )
                if await cursor.fetchone() is not None:
                    raise PublicationSchedulingError(
                        "MINIMUM_GAP_VIOLATION", "publication channel minimum gap is not satisfied",
                    )
                outbox_id = await enqueue_job(
                    connection,
                    idempotency_key=request.request_id,
                    event_name="publication.dispatch_due",
                    correlation_id=request.publication_id,
                    payload={
                        "schema_version": 1,
                        "schedule_id": str(request.schedule_id),
                        "publication_id": str(request.publication_id),
                        "platform": values["platform"].value,
                    },
                    max_attempts=policy.outbox_max_attempts,
                    run_after=scheduled,
                )
                cursor = await connection.execute(
                    f"""INSERT INTO publication_delivery_reservations
                        (id, request_id, publication_id, approval_id, owner_user_id,
                         content_id, platform, channel_id, asset_id, artifact_version,
                         publication_state_version, destination_fingerprint,
                         local_scheduled_at, timezone_name, schedule_fold,
                         utc_offset_minutes, scheduled_at_utc,
                         local_day_start_utc, local_day_end_utc, daily_cap,
                         minimum_gap_seconds, state, outbox_job_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, 'SCHEDULED', %s)
                       RETURNING {_SCHEDULE_COLUMNS.replace('r.', '')}""",
                    (
                        request.schedule_id, request.request_id, request.publication_id,
                        request.approval_id, request.owner_user_id, values["content_id"],
                        values["platform"].value, values["channel_id"], values["asset_id"],
                        values["artifact_version"], values["state_version"],
                        values["destination_fingerprint"], request.local_scheduled_at,
                        request.timezone_name, request.fold, request.utc_offset_minutes,
                        scheduled, day_start, day_end, policy.maximum_per_local_day,
                        policy.minimum_gap_seconds, outbox_id,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise PublicationScheduleConflict("publication schedule could not be reserved")
                return self._schedule(row)
        except (
            PublicationScheduleConflict,
            PublicationScheduleNotAllowed,
            PublicationScheduleNotFound,
            PublicationSchedulingError,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("publication schedule storage is unavailable") from exc

    @staticmethod
    async def _find_approval_request(connection, request):
        cursor = await connection.execute(
            f"""SELECT {_APPROVAL_COLUMNS}
                FROM publication_delivery_approvals AS a
                WHERE a.request_id = %s AND a.owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_schedule_request(connection, request):
        cursor = await connection.execute(
            f"""SELECT {_SCHEDULE_COLUMNS}
                FROM publication_delivery_reservations AS r
                WHERE r.request_id = %s AND r.owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _require_approvable(row):
        (
            _, owner, platform, status, contract, request_fingerprint,
            state_version, content_id, channel_id, asset_id, artifact_version,
            destination_fingerprint, timezone_name, enabled, permissions,
            destination_current, credentials_current, remote_upload, remote_post,
            instagram_phase, facebook_phase,
        ) = row
        expected_contract = {
            "YOUTUBE": "YOUTUBE_V1",
            "INSTAGRAM": "INSTAGRAM_REELS_V1",
            "FACEBOOK": "FACEBOOK_REELS_V1",
        }.get(platform)
        if (expected_contract is None or contract != expected_contract or status != "DRAFT"
                or enabled is not True or permissions != "VALID"
                or destination_current is not True or credentials_current is not True
                or remote_upload is not None or remote_post is not None
                or (platform == "INSTAGRAM" and instagram_phase != "CLAIMED")
                or (platform == "FACEBOOK" and facebook_phase != "CLAIMED")):
            raise PublicationScheduleNotAllowed("publication is not approvable")
        return {
            "owner": owner,
            "platform": PublicationPlatform(platform),
            "request_fingerprint": request_fingerprint.strip(),
            "state_version": state_version,
            "content_id": content_id,
            "channel_id": channel_id,
            "asset_id": asset_id,
            "artifact_version": artifact_version,
            "destination_fingerprint": destination_fingerprint.strip(),
            "timezone_name": timezone_name,
        }

    @staticmethod
    def _approval(row):
        try:
            return PublicationApprovalRecord(
                approval_id=row[0], request_id=row[1], publication_id=row[2],
                owner_user_id=row[3], decision=PublicationApprovalDecision(row[4]),
                valid_until=row[5], reason=row[6], platform=PublicationPlatform(row[7]),
                content_id=row[8], channel_id=row[9], asset_id=row[10],
                artifact_version=row[11], publication_state_version=row[12],
                destination_fingerprint=row[13].strip(), created_at=row[14],
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored publication approval is invalid") from exc

    @staticmethod
    def _schedule(row):
        try:
            return PublicationScheduleRecord(
                schedule_id=row[0], request_id=row[1], publication_id=row[2],
                approval_id=row[3], owner_user_id=row[4],
                platform=PublicationPlatform(row[5]), channel_id=row[6],
                content_id=row[7], asset_id=row[8], artifact_version=row[9],
                local_scheduled_at=row[10], timezone_name=row[11], fold=row[12],
                utc_offset_minutes=row[13], scheduled_at_utc=row[14],
                state=PublicationDeliveryState(row[15]), outbox_job_id=row[16],
                created_at=row[17],
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored publication schedule is invalid") from exc
