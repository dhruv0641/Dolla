-- Persist one account-scoped, idempotent reservation per request.
-- Unknown/expired spend remains held until a later reviewed reconciliation resolves it.
CREATE TABLE flow_credit_reservations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_account_id uuid NOT NULL REFERENCES flow_accounts(id),
    request_id uuid NOT NULL,
    model_name text NOT NULL CHECK (length(trim(model_name)) BETWEEN 1 AND 100),
    duration_seconds integer NOT NULL CHECK (duration_seconds BETWEEN 4 AND 180),
    quote_ref text NOT NULL CHECK (length(trim(quote_ref)) BETWEEN 1 AND 256),
    quoted_credits integer NOT NULL CHECK (quoted_credits > 0),
    quote_source text NOT NULL CHECK (quote_source IN ('FLOW_QUOTE','APPROVED_RATE_CARD')),
    quoted_at timestamptz NOT NULL,
    quote_expires_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'RESERVED'
      CHECK (state IN ('RESERVED','RECONCILE_PENDING','RELEASED','SETTLED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (quote_expires_at > quoted_at),
    UNIQUE (flow_account_id, request_id)
);

CREATE INDEX idx_flow_credit_reservations_active
  ON flow_credit_reservations(flow_account_id, state, created_at)
  WHERE state IN ('RESERVED','RECONCILE_PENDING');
