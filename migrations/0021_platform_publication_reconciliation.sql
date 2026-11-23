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

CREATE TABLE publication_reconciliation_attempts (
  request_id uuid PRIMARY KEY,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  attempt_index integer NOT NULL CHECK (attempt_index BETWEEN 1 AND 1000),
  status text NOT NULL CHECK (status IN ('RESERVED','RECORDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  recorded_at timestamptz,
  UNIQUE (request_id, publication_id),
  UNIQUE (publication_id, attempt_index),
  CHECK (
    (status = 'RESERVED' AND recorded_at IS NULL) OR
    (status = 'RECORDED' AND recorded_at IS NOT NULL)
  )
);

CREATE FUNCTION guard_publication_reconciliation_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'publication reconciliation attempts are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.request_id, NEW.publication_id, NEW.owner_user_id,
      NEW.target_fingerprint, NEW.attempt_index, NEW.created_at)
     IS DISTINCT FROM
     (OLD.request_id, OLD.publication_id, OLD.owner_user_id,
      OLD.target_fingerprint, OLD.attempt_index, OLD.created_at)
     OR OLD.status <> 'RESERVED' OR NEW.status <> 'RECORDED'
     OR OLD.recorded_at IS NOT NULL OR NEW.recorded_at IS NULL THEN
    RAISE EXCEPTION 'publication reconciliation attempt transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_reconciliation_attempts_guard_update
  BEFORE UPDATE ON publication_reconciliation_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_publication_reconciliation_attempt();

CREATE TRIGGER publication_reconciliation_attempts_prevent_delete
  BEFORE DELETE ON publication_reconciliation_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_publication_reconciliation_attempt();

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
  FOREIGN KEY (request_id, publication_id)
    REFERENCES publication_reconciliation_attempts(request_id, publication_id),
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

CREATE FUNCTION expected_publication_reconciliation_verdict(
  local_value text, remote_value text
) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT CASE
    WHEN remote_value = 'UNKNOWN' THEN 'UNKNOWN'
    WHEN local_value = 'PUBLISHED' AND remote_value = 'PUBLISHED' THEN 'IN_SYNC'
    WHEN local_value = 'PUBLISHED' AND remote_value = 'PROCESSING' THEN 'LOCAL_AHEAD'
    WHEN local_value = 'PUBLISHED' THEN 'CONFLICT'
    WHEN local_value = 'CANCELLED' AND remote_value IN ('ABSENT','DELETED') THEN 'IN_SYNC'
    WHEN local_value = 'CANCELLED' THEN 'CONFLICT'
    WHEN local_value = 'FAILED' AND remote_value = 'FAILED' THEN 'IN_SYNC'
    WHEN local_value = 'FAILED' THEN 'CONFLICT'
    WHEN remote_value = 'PUBLISHED' THEN 'REMOTE_AHEAD'
    WHEN remote_value = 'PROCESSING' THEN 'IN_SYNC'
    WHEN remote_value = 'ABSENT' AND local_value = 'DRAFT' THEN 'IN_SYNC'
    WHEN remote_value = 'ABSENT' THEN 'LOCAL_AHEAD'
    ELSE 'CONFLICT'
  END
$$;

CREATE FUNCTION require_publication_reconciliation_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text;
  current_platform text;
  current_status text;
  current_version bigint;
  current_request_fingerprint text;
  current_channel uuid;
  current_destination text;
  current_destination_fingerprint text;
  current_remote_object text;
  current_remote_url text;
  current_contract text;
  channel_enabled boolean;
  channel_permissions text;
  attempt_owner text;
  attempt_target text;
  attempt_status text;
  expected_target text;
  expected_verdict text;
BEGIN
  SELECT b.owner_user_id, ch.platform, p.status,
         p.publication_state_version, p.request_fingerprint, p.channel_id,
         p.channel_external_id_snapshot, p.destination_fingerprint,
         CASE ch.platform
           WHEN 'YOUTUBE' THEN p.remote_post_id
           WHEN 'INSTAGRAM' THEN p.remote_post_id
           WHEN 'FACEBOOK' THEN p.remote_upload_id
         END,
         p.remote_url, p.publication_contract, ch.enabled,
         ch.permissions_status, a.owner_user_id, a.target_fingerprint, a.status
    INTO current_owner, current_platform, current_status,
         current_version, current_request_fingerprint, current_channel,
         current_destination, current_destination_fingerprint,
         current_remote_object, current_remote_url, current_contract,
         channel_enabled, channel_permissions, attempt_owner,
         attempt_target, attempt_status
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    JOIN publication_reconciliation_attempts AS a
      ON a.request_id = NEW.request_id AND a.publication_id = p.id
    WHERE p.id = NEW.publication_id
      AND ch.external_channel_id = p.channel_external_id_snapshot
      AND ch.credentials_ref = p.credentials_ref_snapshot
    FOR KEY SHARE OF p, ch;

  expected_target := encode(digest(concat_ws('|',
    NEW.publication_id::text, current_owner, current_platform, current_status,
    current_version::text, current_request_fingerprint, current_channel::text,
    current_destination, current_destination_fingerprint,
    COALESCE(current_remote_object, ''), COALESCE(current_remote_url, '')
  ), 'sha256'), 'hex');
  expected_verdict := expected_publication_reconciliation_verdict(
    NEW.local_status, NEW.remote_state
  );

  IF current_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.local_status IS DISTINCT FROM current_status
     OR NEW.publication_state_version IS DISTINCT FROM current_version
     OR NEW.request_fingerprint IS DISTINCT FROM current_request_fingerprint
     OR NEW.channel_id IS DISTINCT FROM current_channel
     OR NEW.destination_id IS DISTINCT FROM current_destination
     OR NEW.destination_fingerprint IS DISTINCT FROM current_destination_fingerprint
     OR NEW.remote_object_id IS DISTINCT FROM current_remote_object
     OR NEW.target_fingerprint IS DISTINCT FROM expected_target
     OR attempt_owner IS DISTINCT FROM current_owner
     OR attempt_target IS DISTINCT FROM expected_target
     OR attempt_status IS DISTINCT FROM 'RESERVED'
     OR channel_enabled IS DISTINCT FROM true
     OR channel_permissions IS DISTINCT FROM 'VALID'
     OR (current_platform = 'YOUTUBE' AND current_contract <> 'YOUTUBE_V1')
     OR (current_platform = 'INSTAGRAM' AND current_contract <> 'INSTAGRAM_REELS_V1')
     OR (current_platform = 'FACEBOOK' AND current_contract <> 'FACEBOOK_REELS_V1')
     OR NEW.verdict IS DISTINCT FROM expected_verdict
     OR NEW.requires_human_review IS DISTINCT FROM (expected_verdict <> 'IN_SYNC')
     OR (current_remote_url IS NOT NULL AND NEW.remote_url IS NOT NULL
         AND NEW.remote_url IS DISTINCT FROM current_remote_url) THEN
    RAISE EXCEPTION 'publication reconciliation evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_reconciliations_require_evidence
  BEFORE INSERT ON publication_reconciliations
  FOR EACH ROW EXECUTE FUNCTION require_publication_reconciliation_evidence();

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
