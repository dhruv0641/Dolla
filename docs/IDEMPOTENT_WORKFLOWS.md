# Idempotent workflow dispatch

`OutboxDispatcher` accepts only rows already leased by `lease_due_jobs`. Convert each returned seven-column row with `LeasedJob.from_row`, then dispatch using the worker ID that acquired the lease. The dispatcher requires an exact lease-owner match and an explicitly registered event name; otherwise it fails without opening a database transaction.

For a registered job, the handler runs inside `unit_of_work`, and `complete_job` acknowledges the same job in that same transaction only while the lease owner still matches and the lease has not expired. If the handler raises or completion detects lease loss/expiry, the transaction rolls back, including handler database writes. A job's immutable UUID is its stable idempotency key. Handlers must make their database/outbox writes unique or upsert-safe by that key and must not call external services, perform network I/O, or produce non-transactional side effects. This keeps a redelivery from duplicating committed work.

This is an at-least-once lease mechanism with transactional database effects; it does not provide exactly-once delivery to external systems. Retry delays, exhaustion/dead-letter handling and lease recovery policy are scoped to TASK-015. No live worker or PostgreSQL instance is configured, so current evidence is unit tests with fake connection/pool boundaries only.
