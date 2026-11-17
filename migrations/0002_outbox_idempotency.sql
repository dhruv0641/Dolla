-- Give transactional outbox inserts a durable caller-supplied deduplication key.
ALTER TABLE outbox_jobs ADD COLUMN idempotency_key uuid;
UPDATE outbox_jobs SET idempotency_key = gen_random_uuid() WHERE idempotency_key IS NULL;
ALTER TABLE outbox_jobs ALTER COLUMN idempotency_key SET NOT NULL;
CREATE UNIQUE INDEX idx_outbox_idempotency_key ON outbox_jobs(idempotency_key);
CREATE INDEX idx_outbox_ready_due ON outbox_jobs(run_after, created_at) WHERE status = 'READY';
CREATE INDEX idx_outbox_expired_lease ON outbox_jobs(lease_until) WHERE status = 'LEASED';
