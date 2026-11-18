-- Durable owner-scoped record of unknown-spend conditions.
CREATE TABLE flow_credit_alarms (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_account_id uuid NOT NULL,
    request_id uuid NOT NULL,
    alarm_type text NOT NULL CHECK (alarm_type IN ('UNKNOWN_SPEND')),
    reason_code text NOT NULL CHECK (reason_code IN (
      'SUBMISSION_OUTCOME_UNKNOWN',
      'REMOTE_JOB_STATE_UNKNOWN',
      'ACTUAL_COST_UNKNOWN',
      'PROVIDER_RESPONSE_AMBIGUOUS'
    )),
    state text NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN')),
    created_by text NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT flow_credit_alarm_reservation_fk
      FOREIGN KEY (flow_account_id, request_id)
      REFERENCES flow_credit_reservations(flow_account_id, request_id),
    UNIQUE (flow_account_id, request_id, alarm_type)
);

CREATE INDEX idx_flow_credit_alarms_open
  ON flow_credit_alarms(flow_account_id, created_at DESC, id DESC)
  WHERE state = 'OPEN';
