"""Transactional outbox enqueue, lease, and completion operations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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


async def enqueue_job(
    connection: OutboxConnection,
    *,
    idempotency_key: UUID,
    event_name: str,
    correlation_id: UUID,
    payload: Mapping[str, Any],
    max_attempts: int = 5,
) -> UUID:
    """Insert an outbox item in the caller's domain transaction, idempotently."""
    if not isinstance(idempotency_key, UUID) or not isinstance(correlation_id, UUID):
        raise OutboxValidationError("idempotency_key and correlation_id must be UUID values")
    if not isinstance(event_name, str) or not event_name.strip() or len(event_name) > 160:
        raise OutboxValidationError("event_name must be a non-empty string of at most 160 characters")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 100:
        raise OutboxValidationError("max_attempts must be between 1 and 100")
    try:
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise OutboxValidationError("payload must be JSON serializable") from exc
    if len(payload_json.encode("utf-8")) > 64 * 1024:
        raise OutboxValidationError("payload exceeds the 65536-byte limit")

    cursor = await connection.execute(
        """INSERT INTO outbox_jobs
           (idempotency_key, event_name, correlation_id, payload, max_attempts)
           VALUES (%s, %s, %s, %s::jsonb, %s)
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING id""",
        (idempotency_key, event_name.strip(), correlation_id, payload_json, max_attempts),
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
        """WITH selected AS (
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
                     job.attempt_count, job.lease_owner, job.lease_until""",
        (now.astimezone(timezone.utc), now.astimezone(timezone.utc), limit, worker_id.strip(),
         now.astimezone(timezone.utc), lease_seconds, now.astimezone(timezone.utc)),
    )
    return await cursor.fetchall()


async def complete_job(connection: OutboxConnection, *, job_id: UUID, worker_id: str) -> None:
    """Complete only a job still leased by this worker."""
    if not isinstance(job_id, UUID):
        raise OutboxValidationError("job_id must be a UUID value")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise OutboxValidationError("worker_id must be a non-empty string")
    cursor = await connection.execute(
        """UPDATE outbox_jobs
           SET status = 'DONE', lease_owner = NULL, lease_until = NULL, updated_at = now()
           WHERE id = %s AND status = 'LEASED' AND lease_owner = %s""",
        (job_id, worker_id.strip()),
    )
    if cursor.rowcount != 1:
        raise LeaseLostError("job lease is no longer owned by this worker")
