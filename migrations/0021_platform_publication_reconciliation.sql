-- Immutable, read-only platform observations kept separate from local workflow state.

ALTER TABLE publication_jobs
  ADD COLUMN publication_state_version bigint NOT NULL DEFAULT 0
    CHECK (publication_state_version >= 0);

CREATE FUNCTION advance_publication_state_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.publication_state_version := OLD.publication_state_version + 1;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_jobs_advance_state_version
  BEFORE UPDATE ON publication_jobs
  FOR EACH ROW EXECUTE FUNCTION advance_publication_state_version();

CREATE TABLE publication_reconciliations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL UNIQUE,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  local_status text NOT NULL CHECK (local_status IN (
    'DRAFT','PUBLISH_REQUESTED','UPLOAD_STARTED','PROCESSING',
    'VERIFY_PENDING','PUBLISHED','FAILED','CANCELLED'
  )),
  publication_state_version bigint NOT NULL CHECK (publication_state_version >= 0),
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  channel_id uuid NOT NULL REFERENCES social_channels(id),
  destination_id text NOT NULL CHECK (destination_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  destination_fingerprint char(64) NOT NULL
    CHECK (destination_fingerprint ~ '^[0-9a-f]{64}$'),
  remote_object_id text NOT NULL CHECK (remote_object_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  remote_state text NOT NULL CHECK (remote_state IN (
    'ABSENT','PROCESSING','PUBLISHED','FAILED','DELETED','RESTRICTED','UNKNOWN'
  )),
  remote_url text,
  provider_evidence_id text NOT NULL
    CHECK (provider_evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  observed_at timestamptz NOT NULL,
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  observation_fingerprint char(64) NOT NULL
    CHECK (observation_fingerprint ~ '^[0-9a-f]{64}$'),
  verdict text NOT NULL CHECK (verdict IN (
    'IN_SYNC','REMOTE_AHEAD','LOCAL_AHEAD','CONFLICT','UNKNOWN'
  )),
  requires_human_review boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (requires_human_review = (verdict <> 'IN_SYNC')),
  CHECK (
    remote_url IS NULL OR
    (platform = 'YOUTUBE' AND remote_url =
      'https://www.youtube.com/watch?v=' || remote_object_id) OR
    (platform = 'FACEBOOK' AND remote_url =
      'https://www.facebook.com/reel/' || remote_object_id) OR
    (platform = 'INSTAGRAM' AND remote_url ~
      '^https://www[.]instagram[.]com/reel/[A-Za-z0-9_-]+/?$')
  ),
  CHECK (remote_state <> 'PUBLISHED' OR remote_url IS NOT NULL)
);

CREATE INDEX idx_publication_reconciliations_publication_observed
  ON publication_reconciliations(publication_id, observed_at DESC);

CREATE FUNCTION guard_publication_reconciliation_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'publication reconciliation history is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER publication_reconciliations_prevent_update
  BEFORE UPDATE ON publication_reconciliations
  FOR EACH ROW EXECUTE FUNCTION guard_publication_reconciliation_immutable();

CREATE TRIGGER publication_reconciliations_prevent_delete
  BEFORE DELETE ON publication_reconciliations
  FOR EACH ROW EXECUTE FUNCTION guard_publication_reconciliation_immutable();
