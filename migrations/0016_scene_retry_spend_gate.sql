-- Bind every new definitive generation failure to one immutable retry/spend decision.

ALTER TABLE generation_jobs
  ADD COLUMN retry_gate_decision text
    CHECK (retry_gate_decision IN ('ALLOW','DENY')),
  ADD COLUMN retry_gate_reason text
    CHECK (retry_gate_reason IN (
      'ELIGIBLE', 'FAILURE_NOT_RETRYABLE', 'ATTEMPT_LIMIT_EXHAUSTED',
      'RESERVATION_UNAVAILABLE', 'APPROVAL_REQUIRED', 'APPROVAL_REJECTED',
      'APPROVAL_UNAVAILABLE', 'SPEND_STATE_INVALID'
    )),
  ADD COLUMN retry_credit_reservation_id uuid
    REFERENCES flow_credit_reservations(id),
  ADD COLUMN retry_approval_fingerprint char(64),
  ADD COLUMN retry_max_attempts integer
    CHECK (retry_max_attempts BETWEEN 1 AND 11),
  ADD COLUMN retry_decided_at timestamptz,
  ADD CONSTRAINT generation_jobs_retry_gate_shape CHECK (
    (retry_gate_decision IS NULL
      AND retry_gate_reason IS NULL
      AND retry_credit_reservation_id IS NULL
      AND retry_approval_fingerprint IS NULL
      AND retry_max_attempts IS NULL
      AND retry_decided_at IS NULL) OR
    (retry_gate_decision = 'ALLOW'
      AND retry_scheduled = true
      AND retry_gate_reason = 'ELIGIBLE'
      AND retry_credit_reservation_id IS NOT NULL
      AND retry_approval_fingerprint ~ '^[0-9a-f]{64}$'
      AND retry_max_attempts IS NOT NULL
      AND attempt_index < retry_max_attempts
      AND retry_decided_at IS NOT NULL) OR
    (retry_gate_decision = 'DENY'
      AND retry_scheduled = false
      AND retry_gate_reason IS NOT NULL
      AND retry_gate_reason <> 'ELIGIBLE'
      AND retry_credit_reservation_id IS NULL
      AND retry_approval_fingerprint IS NULL
      AND retry_max_attempts IS NOT NULL
      AND retry_decided_at IS NOT NULL)
  );

CREATE UNIQUE INDEX idx_generation_jobs_retry_reservation
  ON generation_jobs(retry_credit_reservation_id)
  WHERE retry_credit_reservation_id IS NOT NULL;

CREATE FUNCTION require_scene_retry_spend_gate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE reservation_state text;
DECLARE reservation_owner text;
DECLARE scene_owner text;
DECLARE reservation_expiry timestamptz;
BEGIN
  IF NEW.status <> 'FAILED' THEN RETURN NEW; END IF;
  IF TG_OP = 'UPDATE' AND OLD.status = 'FAILED'
     AND (OLD.retry_gate_decision IS NOT NULL
          OR NEW.retry_gate_decision IS NULL) THEN RETURN NEW; END IF;
  IF NEW.retry_gate_decision IS NULL OR NEW.retry_gate_reason IS NULL
     OR NEW.retry_decided_at IS NULL THEN
    RAISE EXCEPTION 'definitive generation failure lacks retry gate evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.retry_gate_decision = 'ALLOW' THEN
    SELECT r.state, a.owner_user_id, r.quote_expires_at
      INTO reservation_state, reservation_owner, reservation_expiry
      FROM flow_credit_reservations AS r
      JOIN flow_accounts AS a ON a.id = r.flow_account_id
      WHERE r.id = NEW.retry_credit_reservation_id FOR SHARE OF r, a;
    SELECT b.owner_user_id INTO scene_owner
      FROM scenes AS s
      JOIN content_items AS c ON c.id = s.content_id
      JOIN brands AS b ON b.id = c.brand_id
      WHERE s.id = NEW.scene_id FOR SHARE OF s, c, b;
    IF reservation_state IS DISTINCT FROM 'RESERVED'
       OR reservation_owner IS NULL OR reservation_owner IS DISTINCT FROM scene_owner
       OR reservation_expiry IS NULL OR reservation_expiry <= NEW.retry_decided_at
       OR NEW.retry_credit_reservation_id = NEW.credit_reservation_id
       OR EXISTS (
         SELECT 1 FROM generation_jobs AS used
         WHERE used.id <> NEW.id
           AND used.credit_reservation_id = NEW.retry_credit_reservation_id
       ) THEN
      RAISE EXCEPTION 'retry gate reservation is not eligible'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF NEW.retry_gate_reason = 'ATTEMPT_LIMIT_EXHAUSTED'
     AND NEW.attempt_index < NEW.retry_max_attempts THEN
    RAISE EXCEPTION 'retry gate attempt-limit reason is inconsistent'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER generation_jobs_retry_spend_gate
  BEFORE INSERT OR UPDATE ON generation_jobs
  FOR EACH ROW EXECUTE FUNCTION require_scene_retry_spend_gate();

CREATE FUNCTION require_scene_retry_claim_gate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_status text;
DECLARE prior_scheduled boolean;
DECLARE prior_decision text;
DECLARE prior_reservation uuid;
DECLARE prior_max_attempts integer;
DECLARE claimed_account uuid;
DECLARE reservation_account uuid;
BEGIN
  IF NEW.attempt_index = 1 THEN RETURN NEW; END IF;
  SELECT id INTO claimed_account
    FROM flow_accounts
    WHERE id = NEW.flow_account_id FOR SHARE;
  SELECT flow_account_id INTO reservation_account
    FROM flow_credit_reservations
    WHERE id = NEW.credit_reservation_id FOR SHARE;
  SELECT status, retry_scheduled, retry_gate_decision,
         retry_credit_reservation_id, retry_max_attempts
    INTO prior_status, prior_scheduled, prior_decision,
         prior_reservation, prior_max_attempts
    FROM generation_jobs
    WHERE scene_id = NEW.scene_id AND attempt_index = NEW.attempt_index - 1
    FOR SHARE;
  IF prior_status IS DISTINCT FROM 'FAILED'
     OR prior_scheduled IS DISTINCT FROM true
     OR prior_decision IS DISTINCT FROM 'ALLOW'
     OR prior_reservation IS DISTINCT FROM NEW.credit_reservation_id
     OR claimed_account IS NULL
     OR reservation_account IS DISTINCT FROM claimed_account
     OR prior_max_attempts IS NULL
     OR NEW.attempt_index > prior_max_attempts THEN
    RAISE EXCEPTION 'scene retry claim lacks an exact eligible retry gate'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER generation_jobs_retry_claim_gate
  BEFORE INSERT ON generation_jobs
  FOR EACH ROW EXECUTE FUNCTION require_scene_retry_claim_gate();

CREATE FUNCTION prevent_scene_retry_gate_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND OLD.retry_gate_decision IS NOT NULL THEN
    RAISE EXCEPTION 'scene retry gate decisions are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.retry_gate_decision IS NOT NULL THEN
    RAISE EXCEPTION 'scene retry gate decisions are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER generation_jobs_retry_gate_immutable
  BEFORE UPDATE OR DELETE ON generation_jobs
  FOR EACH ROW EXECUTE FUNCTION prevent_scene_retry_gate_mutation();
