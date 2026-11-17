"""Parameterized append-only workflow event writes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from flowx_os.db.transaction import TransactionConnection


class EventValidationError(ValueError):
    """Raised when an event contains invalid or oversized data."""


class WorkflowEventStore:
    """Persist audit-shaped workflow events within a caller-owned transaction.

    Event payloads are capped and JSON encoded before SQL execution. The caller
    must redact credentials and unnecessary personal data before append.
    """

    MAX_PAYLOAD_BYTES = 64 * 1024

    def __init__(self, connection: TransactionConnection):
        self._connection = connection

    async def append(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        event_name: str,
        correlation_id: UUID,
        actor: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        values = {
            "entity_type": entity_type,
            "event_name": event_name,
            "actor": actor,
        }
        if any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise EventValidationError("entity_type, event_name, and actor must be non-empty strings")
        if len(entity_type) > 100 or len(event_name) > 160 or len(actor) > 200:
            raise EventValidationError("event identity fields exceed their storage limits")
        if not isinstance(entity_id, UUID) or not isinstance(correlation_id, UUID):
            raise EventValidationError("entity_id and correlation_id must be UUID values")
        try:
            payload_json = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise EventValidationError("payload must be JSON serializable") from exc
        if len(payload_json.encode("utf-8")) > self.MAX_PAYLOAD_BYTES:
            raise EventValidationError("payload exceeds the 65536-byte limit")

        await self._connection.execute(
            """INSERT INTO workflow_events
               (entity_type, entity_id, event_name, correlation_id, actor, payload)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            (entity_type.strip(), entity_id, event_name.strip(), correlation_id, actor.strip(), payload_json),
        )
