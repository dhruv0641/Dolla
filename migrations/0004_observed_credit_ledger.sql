-- Give every credit entry a stable, account-scoped replay key.
-- Legacy rows receive unique keys derived from their immutable primary key.
ALTER TABLE flow_credit_entries
  ADD COLUMN idempotency_key text;

UPDATE flow_credit_entries
   SET idempotency_key = 'legacy:' || id::text
 WHERE idempotency_key IS NULL;

ALTER TABLE flow_credit_entries
  ALTER COLUMN idempotency_key SET NOT NULL,
  ADD CONSTRAINT flow_credit_entries_idempotency_key_check
    CHECK (length(idempotency_key) BETWEEN 1 AND 200);

CREATE UNIQUE INDEX idx_credit_entry_account_idempotency
  ON flow_credit_entries(flow_account_id, idempotency_key);

-- Reconciliation history is read in reverse chronological order per account.
CREATE INDEX idx_credit_entry_account_time_id
  ON flow_credit_entries(flow_account_id, created_at DESC, id DESC);
