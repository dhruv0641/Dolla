"""Lease-safe consumer for due publication outbox events."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from flowx_os.db.outbox import complete_job, record_job_failure
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import PublicationPlatform
from flowx_os.publishing.scheduling import PublicationDeliveryState
from flowx_os.workflow.dispatcher import DispatchOutcome, LeasedJob, WorkflowDispatchValidationError


PUBLICATION_DISPATCH_EVENT = "publication.dispatch_due"
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class PublicationDispatchEnvelope:
    schedule_id: UUID
    publication_id: UUID
    platform: PublicationPlatform

    @classmethod
    def from_job(cls, job: LeasedJob) -> "PublicationDispatchEnvelope":
        if job.event_name != PUBLICATION_DISPATCH_EVENT:
            raise WorkflowDispatchValidationError("publication dispatch event is invalid")
        if set(job.payload) != {"schema_version", "schedule_id", "publication_id", "platform"}:
            raise WorkflowDispatchValidationError("publication dispatch payload shape is invalid")
        if job.payload.get("schema_version") != 1:
            raise WorkflowDispatchValidationError("publication dispatch schema version is invalid")
        try:
            value = cls(
                schedule_id=UUID(str(job.payload["schedule_id"])),
                publication_id=UUID(str(job.payload["publication_id"])),
                platform=PublicationPlatform(str(job.payload["platform"])),
            )
        except (ValueError, TypeError) as exc:
            raise WorkflowDispatchValidationError("publication dispatch identity is invalid") from exc
        if value.publication_id != job.correlation_id:
            raise WorkflowDispatchValidationError("publication dispatch correlation is invalid")
        return value


@dataclass(frozen=True, slots=True)
class PublicationDispatchCommand:
    outbox_job_id: UUID
    schedule_id: UUID
    publication_id: UUID
    owner_user_id: str
    platform: PublicationPlatform
    state: PublicationDeliveryState
    scheduled_at_utc: datetime

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.outbox_job_id, self.schedule_id, self.publication_id))
                or not isinstance(self.owner_user_id, str)
                or self.owner_user_id != self.owner_user_id.strip()
                or not 1 <= len(self.owner_user_id) <= 200
                or not isinstance(self.platform, PublicationPlatform)
                or not isinstance(self.state, PublicationDeliveryState)
                or self.state not in {
                    PublicationDeliveryState.SCHEDULED,
                    PublicationDeliveryState.DISPATCH_RESERVED,
                }
                or not isinstance(self.scheduled_at_utc, datetime)
                or self.scheduled_at_utc.tzinfo is None
                or self.scheduled_at_utc.utcoffset() is None):
            raise ValueError("publication dispatch command is invalid")


class PublicationDispatchFailure(RuntimeError):
    """Safe executor classification; ambiguity is never retried blindly."""

    def __init__(self, code: str, *, retryable: bool = False, ambiguous: bool = False) -> None:
        if _SAFE_ERROR.fullmatch(code) is None:
            raise ValueError("publication dispatch failure code is invalid")
        self.code = code
        self.ambiguous = bool(ambiguous)
        self.retryable = bool(retryable) and not self.ambiguous
        super().__init__(code)


class PublicationDispatchStore(Protocol):
    async def load_due_dispatch(
        self, *, job: LeasedJob, envelope: PublicationDispatchEnvelope,
    ) -> PublicationDispatchCommand: ...


class PublicationDispatchExecutor(Protocol):
    """Advance the exact platform publication through its idempotent publisher."""

    async def __call__(self, command: PublicationDispatchCommand) -> None: ...


class ScheduledPublicationDispatcher:
    """Consume a leased due event and invoke one configured platform executor.

    Provider work runs outside an outbox acknowledgement transaction. Existing
    publisher state machines and the database reservation trigger are the
    idempotency barrier if a worker crashes after a provider outcome. Unknown
    executor failures are therefore dead-lettered for reconciliation, never
    retried blindly.
    """

    def __init__(
        self, *, pool: ConnectionPool, store: PublicationDispatchStore,
        executors: Mapping[PublicationPlatform, PublicationDispatchExecutor],
    ) -> None:
        if not isinstance(executors, Mapping):
            raise ValueError("publication dispatch executors are required")
        for platform, executor in executors.items():
            if not isinstance(platform, PublicationPlatform) or not callable(executor):
                raise ValueError("publication dispatch executor configuration is invalid")
        self._pool = pool
        self._store = store
        self._executors = dict(executors)

    async def dispatch(self, job: LeasedJob, *, worker_id: str) -> DispatchOutcome:
        if not isinstance(job, LeasedJob):
            raise WorkflowDispatchValidationError("job must be a validated LeasedJob")
        worker = worker_id.strip() if isinstance(worker_id, str) else ""
        if not worker or len(worker) > 200 or worker != job.lease_owner:
            raise WorkflowDispatchValidationError("worker does not own this publication job")
        try:
            envelope = PublicationDispatchEnvelope.from_job(job)
        except WorkflowDispatchValidationError:
            return await self._fail(
                job, worker=worker, code="publication_dispatch_invalid", retryable=False,
            )
        try:
            command = await self._store.load_due_dispatch(job=job, envelope=envelope)
        except Exception:
            return await self._fail(
                job, worker=worker, code="publication_dispatch_load_failed", retryable=True,
            )
        if (not isinstance(command, PublicationDispatchCommand)
                or command.outbox_job_id != job.id
                or command.schedule_id != envelope.schedule_id
                or command.publication_id != envelope.publication_id
                or command.platform is not envelope.platform):
            return await self._fail(
                job, worker=worker, code="publication_dispatch_mismatch", retryable=False,
            )
        executor = self._executors.get(command.platform)
        if executor is None:
            return await self._fail(
                job, worker=worker, code="publication_executor_unavailable", retryable=False,
            )
        try:
            await executor(command)
        except PublicationDispatchFailure as exc:
            return await self._fail(
                job, worker=worker, code=exc.code, retryable=exc.retryable,
            )
        except Exception:
            return await self._fail(
                job, worker=worker, code="publication_outcome_unknown", retryable=False,
            )
        async with unit_of_work(self._pool) as connection:
            await complete_job(
                connection, job_id=job.id, worker_id=worker,
                attempt_count=job.attempt_count,
            )
        return DispatchOutcome.DONE

    async def _fail(
        self, job: LeasedJob, *, worker: str, code: str, retryable: bool,
    ) -> DispatchOutcome:
        async with unit_of_work(self._pool) as connection:
            result = await record_job_failure(
                connection, job_id=job.id, worker_id=worker,
                attempt_count=job.attempt_count, max_attempts=job.max_attempts,
                error_code=code, retryable=retryable,
            )
        return DispatchOutcome.DEAD if result.status == "DEAD" else DispatchOutcome.RETRY_SCHEDULED
