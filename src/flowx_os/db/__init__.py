"""Database boundary helpers."""

from flowx_os.db.transaction import ConnectionPool, TransactionConnection, unit_of_work
from flowx_os.db.workflow_events import EventValidationError, WorkflowEventStore
from flowx_os.db.outbox import (
    DeadLetter, FailureOutcome, JobNotDeadLetteredError, LeaseLostError,
    OutboxValidationError, complete_job, enqueue_job, lease_due_jobs,
    list_dead_jobs, record_job_failure, requeue_dead_job,
)

__all__ = [
    "ConnectionPool", "EventValidationError", "TransactionConnection",
    "LeaseLostError", "OutboxValidationError", "WorkflowEventStore",
    "DeadLetter", "FailureOutcome", "JobNotDeadLetteredError",
    "complete_job", "enqueue_job", "lease_due_jobs", "list_dead_jobs",
    "record_job_failure", "requeue_dead_job", "unit_of_work",
]
