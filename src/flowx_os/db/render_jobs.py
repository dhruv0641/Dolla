"""Owner-scoped durable render versions, leases and artifact references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
import math
import re
from typing import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_BANNED_KEYS = ("password", "secret", "token", "credential", "authorization", "cookie")


class RenderJobConflict(RuntimeError):
    """A render version, lease or terminal result conflicts with durable state."""


class RenderJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class RenderArtifactRole(StrEnum):
    FINAL_VIDEO = "FINAL_VIDEO"
    EXPORT_VARIANT = "EXPORT_VARIANT"


class RenderArtifactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    asset_id: UUID
    role: RenderArtifactRole
    profile_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def profile_matches_role(self) -> "RenderArtifactSpec":
        if self.role == RenderArtifactRole.FINAL_VIDEO and self.profile_id is not None:
            raise ValueError("final video artifact cannot have a profile")
        if self.role == RenderArtifactRole.EXPORT_VARIANT:
            if not isinstance(self.profile_id, str) or not _SAFE_CODE.fullmatch(self.profile_id):
                raise ValueError("export artifact profile is invalid")
        return self


class RenderVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    job_id: UUID
    brand_id: UUID
    content_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=200)
    render_version: int = Field(ge=1, le=1_000_000)
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    inputs_manifest: dict[str, object]
    command_manifest: dict[str, object]

    @field_validator("owner_user_id")
    @classmethod
    def owner_is_safe(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("owner identity is invalid")
        return value

    @model_validator(mode="after")
    def manifests_are_canonical(self) -> "RenderVersionRequest":
        _canonical_manifests(self.inputs_manifest, self.command_manifest)
        return self


@dataclass(frozen=True, slots=True)
class RenderJobRecord:
    job_id: UUID
    content_id: UUID
    render_version: int
    status: RenderJobStatus
    inputs_manifest: dict[str, object]
    command_manifest: dict[str, object]
    plan_fingerprint: str
    attempt_count: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    final_asset_id: UUID | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class RenderLeaseClaim:
    record: RenderJobRecord
    claimed: bool


def _walk_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or not key or len(key) > 100:
                raise ValueError("render manifest keys are invalid")
            if any(marker in key.casefold() for marker in _BANNED_KEYS):
                raise ValueError("render manifest contains a forbidden secret field")
            _walk_keys(nested)
    elif isinstance(value, list):
        if len(value) > 1_000:
            raise ValueError("render manifest collection is too large")
        for nested in value:
            _walk_keys(nested)
    elif value is None or isinstance(value, (str, bool, int)):
        return
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("render manifest numbers must be finite")
    else:
        raise ValueError("render manifest contains an unsupported value")


def _canonical_manifests(
    inputs_manifest: dict[str, object], command_manifest: dict[str, object],
) -> tuple[str, str]:
    if not isinstance(inputs_manifest, dict) or set(inputs_manifest) != {"asset_ids"}:
        raise ValueError("render inputs require asset_ids only")
    raw_ids = inputs_manifest.get("asset_ids")
    if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 100:
        raise ValueError("render input asset list is invalid")
    parsed: list[str] = []
    try:
        for raw in raw_ids:
            if not isinstance(raw, str):
                raise ValueError
            value = UUID(raw)
            if raw != str(value):
                raise ValueError
            parsed.append(raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("render input asset identity is invalid") from exc
    if len(set(parsed)) != len(parsed):
        raise ValueError("render input asset identities must be unique")
    if not isinstance(command_manifest, dict) or not command_manifest:
        raise ValueError("render command manifest is required")
    _walk_keys(command_manifest)
    try:
        inputs_json = json.dumps(inputs_manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)
        command_json = json.dumps(command_manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("render manifests must be canonical JSON") from exc
    if len(inputs_json.encode("utf-8")) > 4_096 or len(command_json.encode("utf-8")) > 65_536:
        raise ValueError("render manifests exceed their byte limits")
    return inputs_json, command_json


def _parse_json(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("stored render manifest is invalid")
    return value


def _record(row: tuple[object, ...]) -> RenderJobRecord:
    try:
        (job_id, content_id, version, status, inputs, command, fingerprint, attempts,
         lease_owner, lease_expires, final_asset_id, error_code, created_at,
         started_at, finished_at) = row
        record = RenderJobRecord(
            job_id=job_id, content_id=content_id, render_version=version,
            status=RenderJobStatus(status), inputs_manifest=_parse_json(inputs),
            command_manifest=_parse_json(command), plan_fingerprint=fingerprint.strip(),
            attempt_count=attempts, lease_owner=lease_owner,
            lease_expires_at=lease_expires, final_asset_id=final_asset_id,
            error_code=error_code, created_at=created_at,
            started_at=started_at, finished_at=finished_at,
        )
        if (not isinstance(job_id, UUID) or not isinstance(content_id, UUID)
                or type(version) is not int or version < 1
                or not _FINGERPRINT.fullmatch(record.plan_fingerprint)
                or type(attempts) is not int or not 0 <= attempts <= 10
                or not isinstance(created_at, datetime)):
            raise ValueError("stored render fields are invalid")
        _canonical_manifests(record.inputs_manifest, record.command_manifest)
        return record
    except Exception as exc:
        raise RepositoryUnavailable("stored render job is invalid") from exc


_COLUMNS = """r.id, r.content_id, r.render_version, r.status, r.inputs_manifest,
               r.command_manifest, r.plan_fingerprint, r.attempt_count,
               r.lease_owner, r.lease_expires_at, r.final_asset_id, r.error_code,
               r.created_at, r.started_at, r.finished_at"""


class RenderJobRepository:
    """Persist one versioned plan and safely lease its local execution."""

    def __init__(
        self, pool: ConnectionPool, *, lease_duration: timedelta = timedelta(minutes=5),
        max_attempts: int = 3, now=None,
    ) -> None:
        if not timedelta(seconds=1) <= lease_duration <= timedelta(hours=1):
            raise ValueError("render lease duration is invalid")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError("render attempt limit is invalid")
        self._pool = pool
        self._lease_duration = lease_duration
        self._max_attempts = max_attempts
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def create_or_get(self, request: RenderVersionRequest) -> RenderJobRecord:
        if not isinstance(request, RenderVersionRequest):
            raise ValueError("render version request is required")
        inputs_json, command_json = _canonical_manifests(request.inputs_manifest, request.command_manifest)
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM content_items AS c JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
                       FOR KEY SHARE OF c""",
                    (request.content_id, request.brand_id, request.owner_user_id),
                )
                if await cursor.fetchone() is None:
                    raise OwnedContentNotFound("content not found")
                cursor = await connection.execute(
                    f"""INSERT INTO render_jobs
                           (id, content_id, render_version, status, inputs_manifest,
                            command_manifest, plan_fingerprint)
                         VALUES (%s, %s, %s, 'PENDING', %s::jsonb, %s::jsonb, %s)
                         ON CONFLICT (content_id, render_version) DO NOTHING
                         RETURNING {_COLUMNS.replace('r.', '')}""",
                    (request.job_id, request.content_id, request.render_version,
                     inputs_json, command_json, request.plan_fingerprint),
                )
                row = await cursor.fetchone()
                if row is not None:
                    return _record(row)
                cursor = await connection.execute(
                    f"""SELECT {_COLUMNS} FROM render_jobs AS r
                         JOIN content_items AS c ON c.id = r.content_id
                         JOIN brands AS b ON b.id = c.brand_id
                         WHERE r.content_id = %s AND r.render_version = %s
                           AND b.id = %s AND b.owner_user_id = %s FOR UPDATE OF r""",
                    (request.content_id, request.render_version, request.brand_id, request.owner_user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RenderJobConflict("render version is unavailable")
                existing = _record(row)
                if (existing.job_id != request.job_id
                        or existing.plan_fingerprint != request.plan_fingerprint
                        or existing.inputs_manifest != request.inputs_manifest
                        or existing.command_manifest != request.command_manifest):
                    raise RenderJobConflict("render version already refers to another plan")
                return existing
        except (OwnedContentNotFound, RenderJobConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("render job storage is unavailable") from exc

    async def claim(
        self, *, job_id: UUID, brand_id: UUID, content_id: UUID,
        owner_user_id: str, worker_id: str,
    ) -> RenderLeaseClaim:
        self._validate_identity(job_id, brand_id, content_id, owner_user_id)
        worker_id = self._validate_worker(worker_id)
        now = self._clock()
        try:
            async with unit_of_work(self._pool) as connection:
                current = await self._lock_owned(
                    connection, job_id=job_id, brand_id=brand_id,
                    content_id=content_id, owner_user_id=owner_user_id,
                )
                if current.status == RenderJobStatus.RUNNING:
                    if current.lease_owner == worker_id and current.lease_expires_at and current.lease_expires_at > now:
                        return RenderLeaseClaim(current, False)
                    if current.lease_expires_at is None or current.lease_expires_at > now:
                        raise RenderJobConflict("render job already has an active lease")
                elif current.status != RenderJobStatus.PENDING:
                    raise RenderJobConflict("render job is not claimable")
                if current.attempt_count >= self._max_attempts:
                    raise RenderJobConflict("render attempt limit is exhausted")
                cursor = await connection.execute(
                    f"""UPDATE render_jobs AS r SET status = 'RUNNING',
                           attempt_count = attempt_count + 1, lease_owner = %s,
                           lease_expires_at = %s, started_at = COALESCE(started_at, %s),
                           finished_at = NULL, error_code = NULL, updated_at = %s
                         WHERE id = %s AND status = %s
                         RETURNING {_COLUMNS}""",
                    (worker_id, now + self._lease_duration, now, now,
                     job_id, current.status.value),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RenderJobConflict("render job changed before lease acquisition")
                return RenderLeaseClaim(_record(row), True)
        except (OwnedContentNotFound, RenderJobConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("render job storage is unavailable") from exc

    async def mark_failed(
        self, *, job_id: UUID, brand_id: UUID, content_id: UUID,
        owner_user_id: str, worker_id: str, error_code: str,
    ) -> RenderJobRecord:
        self._validate_identity(job_id, brand_id, content_id, owner_user_id)
        worker_id = self._validate_worker(worker_id)
        if not isinstance(error_code, str) or not _SAFE_CODE.fullmatch(error_code):
            raise ValueError("render failure code is invalid")
        now = self._clock()
        try:
            async with unit_of_work(self._pool) as connection:
                current = await self._lock_owned(connection, job_id=job_id, brand_id=brand_id, content_id=content_id, owner_user_id=owner_user_id)
                if current.status == RenderJobStatus.FAILED and current.error_code == error_code:
                    return current
                if (current.status != RenderJobStatus.RUNNING or current.lease_owner != worker_id
                        or current.lease_expires_at is None or current.lease_expires_at <= now):
                    raise RenderJobConflict("render failure requires the active lease")
                cursor = await connection.execute(
                    f"""UPDATE render_jobs AS r SET status = 'FAILED', error_code = %s,
                           lease_owner = NULL, lease_expires_at = NULL,
                           finished_at = %s, updated_at = %s
                         WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                         RETURNING {_COLUMNS}""",
                    (error_code, now, now, job_id, worker_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RenderJobConflict("render job changed before failure was recorded")
                return _record(row)
        except (OwnedContentNotFound, RenderJobConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("render job storage is unavailable") from exc

    async def retry_failed(
        self, *, job_id: UUID, brand_id: UUID, content_id: UUID, owner_user_id: str,
    ) -> RenderJobRecord:
        self._validate_identity(job_id, brand_id, content_id, owner_user_id)
        now = self._clock()
        try:
            async with unit_of_work(self._pool) as connection:
                current = await self._lock_owned(connection, job_id=job_id, brand_id=brand_id, content_id=content_id, owner_user_id=owner_user_id)
                if current.status == RenderJobStatus.PENDING:
                    return current
                if current.status != RenderJobStatus.FAILED:
                    raise RenderJobConflict("only failed renders can be retried")
                if current.attempt_count >= self._max_attempts:
                    raise RenderJobConflict("render attempt limit is exhausted")
                cursor = await connection.execute(
                    f"""UPDATE render_jobs AS r SET status = 'PENDING', error_code = NULL,
                           finished_at = NULL, updated_at = %s
                         WHERE id = %s AND status = 'FAILED'
                         RETURNING {_COLUMNS}""",
                    (now, job_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RenderJobConflict("render job changed before retry was scheduled")
                return _record(row)
        except (OwnedContentNotFound, RenderJobConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("render job storage is unavailable") from exc

    async def complete(
        self, *, job_id: UUID, brand_id: UUID, content_id: UUID,
        owner_user_id: str, worker_id: str, final_asset_id: UUID,
        artifacts: tuple[RenderArtifactSpec, ...],
    ) -> RenderJobRecord:
        self._validate_identity(job_id, brand_id, content_id, owner_user_id)
        worker_id = self._validate_worker(worker_id)
        if not isinstance(final_asset_id, UUID) or not isinstance(artifacts, tuple) or not 1 <= len(artifacts) <= 4:
            raise ValueError("render completion artifacts are invalid")
        if any(not isinstance(item, RenderArtifactSpec) for item in artifacts):
            raise ValueError("render completion artifact type is invalid")
        if len({item.asset_id for item in artifacts}) != len(artifacts):
            raise ValueError("render completion artifact identities must be unique")
        finals = [item for item in artifacts if item.role == RenderArtifactRole.FINAL_VIDEO]
        profiles = [item.profile_id for item in artifacts if item.role == RenderArtifactRole.EXPORT_VARIANT]
        if len(finals) != 1 or finals[0].asset_id != final_asset_id or len(set(profiles)) != len(profiles):
            raise ValueError("render completion requires one matching final and unique export profiles")
        now = self._clock()
        try:
            async with unit_of_work(self._pool) as connection:
                current = await self._lock_owned(connection, job_id=job_id, brand_id=brand_id, content_id=content_id, owner_user_id=owner_user_id)
                if current.status == RenderJobStatus.DONE:
                    if current.final_asset_id != final_asset_id:
                        raise RenderJobConflict("completed render has another final asset")
                    cursor = await connection.execute(
                        """SELECT asset_id, artifact_role, profile_id FROM render_job_artifacts
                           WHERE render_job_id = %s ORDER BY artifact_role, profile_id NULLS FIRST, asset_id""",
                        (job_id,),
                    )
                    rows = await cursor.fetchall()
                    expected = sorted((item.asset_id, item.role.value, item.profile_id) for item in artifacts)
                    if sorted(rows) != expected:
                        raise RenderJobConflict("completed render artifacts differ")
                    return current
                if (current.status != RenderJobStatus.RUNNING or current.lease_owner != worker_id
                        or current.lease_expires_at is None or current.lease_expires_at <= now):
                    raise RenderJobConflict("render completion requires the active lease")
                asset_ids = tuple(item.asset_id for item in artifacts)
                cursor = await connection.execute(
                    """SELECT id, asset_kind FROM assets
                       WHERE content_id = %s AND retention_state = 'ACTIVE' AND id = ANY(%s)
                       FOR SHARE""",
                    (content_id, list(asset_ids)),
                )
                rows = await cursor.fetchall()
                kinds = {asset_id: kind for asset_id, kind in rows}
                if len(kinds) != len(artifacts) or any(kinds.get(item.asset_id) != item.role.value for item in artifacts):
                    raise RenderJobConflict("render artifact is outside active content lineage")
                for item in artifacts:
                    await connection.execute(
                        """INSERT INTO render_job_artifacts
                             (render_job_id, asset_id, artifact_role, profile_id)
                           VALUES (%s, %s, %s, %s)""",
                        (job_id, item.asset_id, item.role.value, item.profile_id),
                    )
                cursor = await connection.execute(
                    f"""UPDATE render_jobs AS r SET status = 'DONE', final_asset_id = %s,
                           lease_owner = NULL, lease_expires_at = NULL,
                           finished_at = %s, updated_at = %s
                         WHERE id = %s AND status = 'RUNNING' AND lease_owner = %s
                         RETURNING {_COLUMNS}""",
                    (final_asset_id, now, now, job_id, worker_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RenderJobConflict("render job changed before completion")
                return _record(row)
        except (OwnedContentNotFound, RenderJobConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("render job storage is unavailable") from exc

    async def _lock_owned(self, connection, *, job_id, brand_id, content_id, owner_user_id):
        cursor = await connection.execute(
            f"""SELECT {_COLUMNS} FROM render_jobs AS r
                 JOIN content_items AS c ON c.id = r.content_id
                 JOIN brands AS b ON b.id = c.brand_id
                 WHERE r.id = %s AND r.content_id = %s AND b.id = %s AND b.owner_user_id = %s
                 FOR UPDATE OF r""",
            (job_id, content_id, brand_id, owner_user_id.strip()),
        )
        row = await cursor.fetchone()
        if row is None:
            raise OwnedContentNotFound("render job not found")
        return _record(row)

    @staticmethod
    def _validate_identity(job_id, brand_id, content_id, owner_user_id):
        if (not isinstance(job_id, UUID) or not isinstance(brand_id, UUID)
                or not isinstance(content_id, UUID) or not isinstance(owner_user_id, str)
                or not owner_user_id.strip() or len(owner_user_id.strip()) > 200
                or any(ord(character) < 32 or ord(character) == 127
                       for character in owner_user_id)):
            raise ValueError("owner-scoped render identity is invalid")

    @staticmethod
    def _validate_worker(worker_id: str) -> str:
        if (not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id.strip()) > 100
                or any(ord(character) < 32 or ord(character) == 127 for character in worker_id)):
            raise ValueError("render worker identity is invalid")
        return worker_id.strip()

    def _clock(self) -> datetime:
        now = self._now()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("render clock must be timezone-aware")
        return now
