"""Idempotent, transactional dispatch for already leased outbox jobs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from flowx_os.db.outbox import complete_job
from flowx_os.db.transaction import ConnectionPool, TransactionConnection, unit_of_work


class UnknownWorkflowHandler(LookupError):
    """Raised when an outbox event has no explicitly registered handler."""


class WorkflowDispatchValidationError(ValueError):
    """Raised when a leased job or worker identity is invalid."""


@dataclass(frozen=True, slots=True)
class LeasedJob:
    """Validated representation of one row returned by ``lease_due_jobs``."""

    id: UUID
    event_name: str
    correlation_id: UUID
    payload: Mapping[str, Any]
    attempt_count: int
    lease_owner: str
    lease_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.correlation_id, UUID):
            raise WorkflowDispatchValidationError("job and correlation IDs must be UUID values")
        if not isinstance(self.event_name, str) or not self.event_name.strip():
            raise WorkflowDispatchValidationError("event name must be non-empty")
        if not isinstance(self.payload, Mapping):
            raise WorkflowDispatchValidationError("job payload must be a JSON object")
        if isinstance(self.attempt_count, bool) or not isinstance(self.attempt_count, int) or self.attempt_count < 1:
            raise WorkflowDispatchValidationError("attempt count must be a positive integer")
        if not isinstance(self.lease_owner, str) or not self.lease_owner.strip():
            raise WorkflowDispatchValidationError("lease owner must be non-empty")
        if (not isinstance(self.lease_until, datetime) or self.lease_until.tzinfo is None
                or self.lease_until.utcoffset() is None):
            raise WorkflowDispatchValidationError("lease expiration must be timezone-aware")

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> "LeasedJob":
        """Convert the seven-column row returned by ``lease_due_jobs``."""
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 7:
            raise WorkflowDispatchValidationError("leased job row must contain seven columns")
        return cls(*row)

    @property
    def idempotency_key(self) -> UUID:
        """Stable source-job key handlers use to deduplicate their writes."""
        return self.id


class WorkflowHandler(Protocol):
    """A handler performs transactional database/outbox work only.

    The ``job.id`` is a stable idempotency key. Handlers must not call external
    services or perform non-transactional side effects because dispatch may be
    retried after a lease expires.
    """

    async def __call__(self, connection: TransactionConnection, job: LeasedJob) -> None: ...


class OutboxDispatcher:
    """Run a registered handler and acknowledge its job atomically."""

    def __init__(self, pool: ConnectionPool, handlers: Mapping[str, WorkflowHandler]):
        for event_name, handler in handlers.items():
            if not isinstance(event_name, str) or not event_name.strip() or len(event_name) > 160:
                raise WorkflowDispatchValidationError("handler event names must be non-empty and at most 160 characters")
            if not callable(handler):
                raise WorkflowDispatchValidationError("registered workflow handlers must be callable")
        self._pool = pool
        self._handlers = dict(handlers)

    async def dispatch(self, job: LeasedJob, *, worker_id: str) -> None:
        if not isinstance(job, LeasedJob):
            raise WorkflowDispatchValidationError("job must be a validated LeasedJob")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise WorkflowDispatchValidationError("worker ID must be non-empty")
        if len(worker_id) > 200:
            raise WorkflowDispatchValidationError("worker ID exceeds the 200-character limit")
        if worker_id.strip() != job.lease_owner:
            raise WorkflowDispatchValidationError("worker does not own this job lease")
        handler = self._handlers.get(job.event_name)
        if handler is None:
            raise UnknownWorkflowHandler("no handler registered for outbox event")

        # Handler writes and acknowledgement share one transaction. A crash or
        # lease-loss before commit rolls back both, allowing safe redelivery.
        async with unit_of_work(self._pool) as connection:
            await handler(connection, job)
            await complete_job(connection, job_id=job.id, worker_id=worker_id.strip())
