# Transactional outbox and worker leases

Use `enqueue_job` inside `unit_of_work` with the domain write that creates the work item. Its caller-supplied UUID idempotency key is unique in the database; replays return the existing job ID. The key must remain stable for the same logical operation.

Run `lease_due_jobs` inside a short unit of work. It uses `FOR UPDATE SKIP LOCKED`, accepts due ready rows or expired leases, applies bounded lease duration and batch limits, increments attempts, and returns lease ownership. Workers should commit the lease before doing remote or long-running work. `complete_job` only succeeds for the current lease owner and clears lease fields.

Migration `0002_outbox_idempotency.sql` adds the key and indexes. Apply migrations in order. This code does not yet dead-letter exhausted attempts, release a lease for retry, or heartbeat; until those operations exist, do not deploy worker execution. A lost lease must be reconciled before repeating external side effects.
