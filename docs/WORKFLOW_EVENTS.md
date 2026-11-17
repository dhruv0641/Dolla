# Workflow event persistence

`WorkflowEventStore.append` writes one parameterized `workflow_events` row using an active PostgreSQL connection. Call it inside `unit_of_work(pool)` so the event commits or rolls back atomically with the domain change that caused it:

```python
async with unit_of_work(pool) as connection:
    await repository.update_content(connection, content_id, status="READY")
    await WorkflowEventStore(connection).append(...)
```

The store validates IDs and identity lengths, encodes payloads as JSON, and caps payloads at 64 KiB. It does not resolve entity ownership, redact secrets, or provide idempotency by itself. Callers must authorize and sanitize data before append. Since `entity_id` is polymorphic in the initial schema, the application must define how to handle events whose entity was later deleted. Database I/O is covered by parameter-shape unit tests; no live database connection is claimed.
