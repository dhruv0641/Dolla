"""Transactional outbox enqueue, lease, and completion operations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID


class OutboxConnection(Protocol):
    async def execute(self, query: str, params: Sequence[Any] = ()) -> "OutboxCursor": ...


class OutboxCursor(Protocol):
    rowcount: int

    async def fetchone(self) -> Any: ...

    async def fetchall(self) -> list[Any]: ...


class LeaseLostError(RuntimeError):
    """Raised when a worker no longer owns the requested lease."""


class OutboxValidationError(ValueError):
    """Raised for invalid outbox operation arguments."""


class JobNotDeadLetteredError(LookupError):
    """Raised when an operator tries to requeue a job that is not DEAD."""


@dataclass(frozen=True, slots=True)
class FailureOutcome:
    status: str
    attempt_count: int
    run_after: datetime
    error_code: str


@dataclass(frozen=True, slots=True)
class DeadLetter:
    id: UUID
    event_name: str
    correlation_id: UUID
    attempt_count: int
    max_attempts: int
    error_code: str | None
    updated_at: datetime


async def enqueue_job(
    connection: OutboxConnection,
    *,
    idempotency_key: UUID,
    event_name: str,
    correlation_id: UUID,
    payload: Mapping[str, Any],
    max_attempts: int = 5,
    run_after: datetime | None = None,
) -> UUID:
    """Insert an outbox item in the caller's domain transaction, idempotently."""
    if not isinstance(idempotency_key, UUID) or not isinstance(correlation_id, UUID):
        raise OutboxValidationError("idempotency_key and correlation_id must be UUID values")
    if not isinstance(event_name, str) or not event_name.strip() or len(event_name) > 160:
        raise OutboxValidationError("event_name must be a non-empty string of at most 160 characters")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 100:
        raise OutboxValidationError("max_attempts must be between 1 and 100")
    if run_after is not None and (run_after.tzinfo is None or run_after.utcoffset() is None):
        raise OutboxValidationError("run_after must be timezone-aware")
    try:
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise OutboxValidationError("payload must be JSON serializable") from exc
    if len(payload_json.encode("utf-8")) > 64 * 1024:
        raise OutboxValidationError("payload exceeds the 65536-byte limit")

    cursor = await connection.execute(
        """INSERT INTO outbox_jobs
           (idempotency_key, event_name, correlation_id, payload, max_attempts, run_after)
           VALUES (%s, %s, %s, %s::jsonb, %s, COALESCE(%s, now()))
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING id""",
        (idempotency_key, event_name.strip(), correlation_id, payload_json, max_attempts,
         run_after.astimezone(timezone.utc) if run_after is not None else None),
    )
    row = await cursor.fetchone()
    if row is not None:
        return row[0]
    cursor = await connection.execute(
        "SELECT id FROM outbox_jobs WHERE idempotency_key = %s",
        (idempotency_key,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("idempotent outbox insert did not return an existing row")
    return row[0]


async def lease_due_jobs(
    connection: OutboxConnection,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int = 120,
    limit: int = 10,
) -> list[Any]:
    """Atomically claim due jobs using row locks and SKIP LOCKED.

    Must run inside ``unit_of_work``. Returned database rows include the lease
    owner and expiry so workers can verify ownership during completion.
    """
    if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 200:
        raise OutboxValidationError("worker_id must be a non-empty string of at most 200 characters")
    if now.tzinfo is None or now.utcoffset() is None:
        raise OutboxValidationError("now must be timezone-aware")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 3600:
        raise OutboxValidationError("lease_seconds must be between 1 and 3600")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise OutboxValidationError("limit must be between 1 and 100")
    cursor = await connection.execute(
        """WITH exhausted AS (
             UPDATE outbox_jobs
             SET status = 'DEAD', lease_owner = NULL, lease_until = NULL,
                 error_detail = COALESCE(error_detail, 'max_attempts_exhausted'), updated_at = %s
             WHERE status = 'LEASED' AND lease_until < %s AND attempt_count >= max_attempts
             RETURNING id
           ), selected AS (
             SELECT id FROM outbox_jobs
             WHERE (status = 'READY' OR (status = 'LEASED' AND lease_until < %s))
               AND run_after <= %s AND attempt_count < max_attempts
             ORDER BY run_after, created_at
             FOR UPDATE SKIP LOCKED
             LIMIT %s
           )
           UPDATE outbox_jobs AS job
           SET status = 'LEASED', lease_owner = %s,
               lease_until = %s + (%s * interval '1 second'),
               attempt_count = job.attempt_count + 1,
               updated_at = %s
           FROM selected
           WHERE job.id = selected.id
           RETURNING job.id, job.event_name, job.correlation_id, job.payload,
                     job.attempt_count, job.lease_owner, job.lease_until, job.max_attempts""",
        (now.astimezone(timezone.utc), now.astimezone(timezone.utc),
         now.astimezone(timezone.utc), now.astimezone(timezone.utc), limit, worker_id.strip(),
         now.astimezone(timezone.utc), lease_seconds, now.astimezone(timezone.utc)),
    )
    return await cursor.fetchall()


async def record_job_failure(
    connection: OutboxConnection,
    *,
    job_id: UUID,
    worker_id: str,
    attempt_count: int,
    max_attempts: int,
    error_code: str,
    retryable: bool,
    base_delay_seconds: int = 5,
    max_delay_seconds: int = 3600,
) -> FailureOutcome:
    """Schedule a bounded retry or dead-letter a failed current lease.

    Only a safe, structured error code is stored; exception text is never
    persisted. The caller runs this in a fresh ``unit_of_work`` after the
    handler transaction has rolled back.
    """
    if not isinstance(job_id, UUID):
        raise OutboxValidationError("job_id must be a UUID value")
    if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 200:
        raise OutboxValidationError("worker_id must be a non-empty string of at most 200 characters")
    if (isinstance(attempt_count, bool) or not isinstance(attempt_count, int)
            or attempt_count < 1):
        raise OutboxValidationError("attempt_count must be a positive integer")
    if (isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
            or not attempt_count <= max_attempts <= 100):
        raise OutboxValidationError("max_attempts must be at least attempt_count and at most 100")
    if not isinstance(error_code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", error_code):
        raise OutboxValidationError("error_code must be a lowercase code of at most 100 characters")
    if not isinstance(retryable, bool):
        raise OutboxValidationError("retryable must be a boolean")
    if (isinstance(base_delay_seconds, bool) or not isinstance(base_delay_seconds, int)
            or not 1 <= base_delay_seconds <= 3600):
        raise OutboxValidationError("base delay must be between 1 and 3600 seconds")
    if (isinstance(max_delay_seconds, bool) or not isinstance(max_delay_seconds, int)
            or not base_delay_seconds <= max_delay_seconds <= 86400):
        raise OutboxValidationError("maximum delay must be between base delay and 86400 seconds")

    should_retry = retryable and attempt_count < max_attempts
    delay = min(base_delay_seconds * (2 ** (attempt_count - 1)), max_delay_seconds)
    status = "READY" if should_retry else "DEAD"
    cursor = await connection.execute(
        """UPDATE outbox_jobs
           SET status = %s,
               run_after = CASE WHEN %s THEN now() + (%s * interval '1 second') ELSE now() END,
               lease_owner = NULL,
               lease_until = NULL,
               error_detail = %s,
               updated_at = now()
           WHERE id = %s AND status = 'LEASED' AND lease_owner = %s
             AND lease_until > now() AND attempt_count = %s AND max_attempts = %s
           RETURNING status, attempt_count, run_after""",
        (status, should_retry, delay, error_code, job_id, worker_id.strip(), attempt_count, max_attempts),
    )
    row = await cursor.fetchone()
    if row is None:
        raise LeaseLostError("job lease is no longer owned by this worker")
    return FailureOutcome(status=row[0], attempt_count=row[1], run_after=row[2], error_code=error_code)


async def list_dead_jobs(connection: OutboxConnection, *, limit: int = 100) -> list[DeadLetter]:
    """List safe dead-letter metadata without returning job payloads."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise OutboxValidationError("dead-letter limit must be between 1 and 500")
    cursor = await connection.execute(
        """SELECT id, event_name, correlation_id, attempt_count, max_attempts,
                  error_detail, updated_at
           FROM outbox_jobs WHERE status = 'DEAD'
           ORDER BY updated_at DESC, id LIMIT %s""",
        (limit,),
    )
    return [DeadLetter(*row) for row in await cursor.fetchall()]


async def requeue_dead_job(
    connection: OutboxConnection, *, job_id: UUID, max_attempts: int = 5
) -> UUID:
    """Reset one DEAD job for an explicitly authorized operator replay."""
    if not isinstance(job_id, UUID):
        raise OutboxValidationError("job_id must be a UUID value")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 100:
        raise OutboxValidationError("max_attempts must be between 1 and 100")
    cursor = await connection.execute(
        """UPDATE outbox_jobs SET status = 'READY', attempt_count = 0,
                  max_attempts = %s, run_after = now(), error_detail = NULL,
                  lease_owner = NULL, lease_until = NULL, updated_at = now()
           WHERE id = %s AND status = 'DEAD' RETURNING id""",
        (max_attempts, job_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise JobNotDeadLetteredError("job is not available for dead-letter replay")
    return row[0]


async def complete_job(
    connection: OutboxConnection, *, job_id: UUID, worker_id: str, attempt_count: int
) -> None:
    """Complete only the current lease generation owned by this worker."""
    if not isinstance(job_id, UUID):
        raise OutboxValidationError("job_id must be a UUID value")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise OutboxValidationError("worker_id must be a non-empty string")
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 1:
        raise OutboxValidationError("attempt_count must be a positive integer")
    cursor = await connection.execute(
        """UPDATE outbox_jobs
           SET status = 'DONE', lease_owner = NULL, lease_until = NULL, updated_at = now()
           WHERE id = %s AND status = 'LEASED' AND lease_owner = %s
             AND attempt_count = %s AND lease_until > now()""",
        (job_id, worker_id.strip(), attempt_count),
    )
    if cursor.rowcount != 1:
        raise LeaseLostError("job lease is no longer owned by this worker")
