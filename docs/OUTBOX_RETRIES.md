# Outbox scheduling, retries and dead letters

`enqueue_job` accepts an optional timezone-aware `run_after` timestamp. The default is database time at enqueue. `lease_due_jobs` claims only due work and returns the configured `max_attempts` with the lease data. Expired leases can be reclaimed while attempts remain; an expired lease at the attempt limit is moved to `DEAD` during a subsequent lease sweep.

`OutboxDispatcher` runs registered handler writes and job completion in one database transaction. On handler failure, that transaction rolls back and a separate transaction records the failure, provided the original lease still belongs to the worker and has not expired. Failures retry by default. `WorkflowHandlerFailure` allows a handler to provide a lowercase safe `error_code` and set `retryable=False`; unknown event names are non-retryable. Raw exception text is never stored. Retry delay is `min(5 * 2^(attempt_count - 1), 3600)` seconds by default. After the configured attempt limit, the job becomes `DEAD`.

`list_dead_jobs` exposes metadata only and deliberately excludes payloads. `requeue_dead_job` resets a `DEAD` row to `READY`; it is a persistence helper, not an authorization boundary. Any service or operator endpoint that exposes it must require an administrator role and record the actor in the audit trail in the same unit of work. Replay reuses the existing payload and idempotency key, so handlers must remain idempotent.

The SQL operations use PostgreSQL row locks and database time for backoff and lease validation. Unit tests cover query contracts and state decisions; live PostgreSQL concurrency behavior has not been verified. No scheduler process, admin endpoint, or external side effect is introduced by this capability.
