-- Exact publication approval, timezone-safe schedules and pre-provider duplicate barriers.

CREATE TABLE publication_delivery_approvals (
  id uuid PRIMARY KEY,
  request_id uuid NOT NULL UNIQUE,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL,
  approver_user_id text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
  reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
  valid_until timestamptz NOT NULL,
  publication_request_fingerprint char(64) NOT NULL,
  publication_state_version bigint NOT NULL,
  content_id uuid NOT NULL REFERENCES content_items(id),
  channel_id uuid NOT NULL REFERENCES social_channels(id),
  asset_id uuid NOT NULL REFERENCES assets(id),
  artifact_version integer NOT NULL CHECK (artifact_version > 0),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  destination_fingerprint char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, publication_id),
  CHECK (owner_user_id = approver_user_id),
  CHECK (publication_request_fingerprint ~ '^[0-9a-f]{64}$'),
  CHECK (destination_fingerprint ~ '^[0-9a-f]{64}$'),
  CHECK (valid_until > created_at)
);

CREATE FUNCTION require_publication_delivery_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text;
  current_platform text;
  current_status text;
  current_contract text;
  current_request_fingerprint text;
  current_state_version bigint;
  current_content uuid;
  current_channel uuid;
  current_asset uuid;
  current_artifact_version integer;
  current_destination_fingerprint text;
  current_enabled boolean;
  current_permissions text;
  current_remote_upload text;
  current_remote_post text;
  current_instagram_phase text;
  current_facebook_phase text;
BEGIN
  SELECT b.owner_user_id, ch.platform, p.status, p.publication_contract,
         p.request_fingerprint, p.publication_state_version, p.content_id,
         p.channel_id, p.asset_id, p.artifact_version,
         p.destination_fingerprint, ch.enabled, ch.permissions_status,
         p.remote_upload_id, p.remote_post_id,
         p.instagram_phase, p.facebook_phase
    INTO current_owner, current_platform, current_status, current_contract,
         current_request_fingerprint, current_state_version, current_content,
         current_channel, current_asset, current_artifact_version,
         current_destination_fingerprint, current_enabled, current_permissions,
         current_remote_upload, current_remote_post,
         current_instagram_phase, current_facebook_phase
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    WHERE p.id = NEW.publication_id
      AND ch.external_channel_id = p.channel_external_id_snapshot
      AND ch.credentials_ref = p.credentials_ref_snapshot
    FOR KEY SHARE OF p, ch;

  IF current_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.approver_user_id IS DISTINCT FROM current_owner
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.publication_request_fingerprint IS DISTINCT FROM current_request_fingerprint
     OR NEW.publication_state_version IS DISTINCT FROM current_state_version
     OR NEW.content_id IS DISTINCT FROM current_content
     OR NEW.channel_id IS DISTINCT FROM current_channel
     OR NEW.asset_id IS DISTINCT FROM current_asset
     OR NEW.artifact_version IS DISTINCT FROM current_artifact_version
     OR NEW.destination_fingerprint IS DISTINCT FROM current_destination_fingerprint
     OR current_status IS DISTINCT FROM 'DRAFT'
     OR current_enabled IS DISTINCT FROM true
     OR current_permissions IS DISTINCT FROM 'VALID'
     OR current_remote_upload IS NOT NULL
     OR current_remote_post IS NOT NULL
     OR (current_platform = 'YOUTUBE' AND current_contract <> 'YOUTUBE_V1')
     OR (current_platform = 'INSTAGRAM' AND (
          current_contract <> 'INSTAGRAM_REELS_V1'
          OR current_instagram_phase <> 'CLAIMED'))
     OR (current_platform = 'FACEBOOK' AND (
          current_contract <> 'FACEBOOK_REELS_V1'
          OR current_facebook_phase <> 'CLAIMED'))
     OR EXISTS (
       SELECT 1 FROM publication_reconciliations AS r
       WHERE r.publication_id = NEW.publication_id
         AND r.requires_human_review = true
     ) THEN
    RAISE EXCEPTION 'publication delivery approval evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_delivery_approvals_require_evidence
  BEFORE INSERT ON publication_delivery_approvals
  FOR EACH ROW EXECUTE FUNCTION require_publication_delivery_approval();

CREATE FUNCTION prevent_publication_delivery_approval_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'publication delivery approvals are immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER publication_delivery_approvals_prevent_update
  BEFORE UPDATE ON publication_delivery_approvals
  FOR EACH ROW EXECUTE FUNCTION prevent_publication_delivery_approval_mutation();

CREATE TRIGGER publication_delivery_approvals_prevent_delete
  BEFORE DELETE ON publication_delivery_approvals
  FOR EACH ROW EXECUTE FUNCTION prevent_publication_delivery_approval_mutation();

CREATE TABLE publication_delivery_reservations (
  id uuid PRIMARY KEY,
  request_id uuid NOT NULL UNIQUE,
  publication_id uuid NOT NULL UNIQUE REFERENCES publication_jobs(id),
  approval_id uuid NOT NULL,
  owner_user_id text NOT NULL,
  content_id uuid NOT NULL REFERENCES content_items(id),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  channel_id uuid NOT NULL REFERENCES social_channels(id),
  asset_id uuid NOT NULL REFERENCES assets(id),
  artifact_version integer NOT NULL CHECK (artifact_version > 0),
  publication_state_version bigint NOT NULL,
  destination_fingerprint char(64) NOT NULL,
  local_scheduled_at timestamp NOT NULL,
  timezone_name text NOT NULL,
  schedule_fold smallint CHECK (schedule_fold IN (0,1)),
  utc_offset_minutes integer NOT NULL CHECK (utc_offset_minutes BETWEEN -840 AND 840),
  scheduled_at_utc timestamptz NOT NULL,
  local_day_start_utc timestamptz NOT NULL,
  local_day_end_utc timestamptz NOT NULL,
  daily_cap integer NOT NULL CHECK (daily_cap BETWEEN 1 AND 100),
  minimum_gap_seconds integer NOT NULL CHECK (minimum_gap_seconds BETWEEN 0 AND 86400),
  state text NOT NULL CHECK (state IN ('SCHEDULED','DISPATCH_RESERVED','CANCELLED')),
  outbox_job_id uuid NOT NULL UNIQUE REFERENCES outbox_jobs(id),
  dispatch_reserved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (approval_id, publication_id)
    REFERENCES publication_delivery_approvals(id, publication_id),
  UNIQUE (content_id, platform, channel_id, artifact_version),
  CHECK (destination_fingerprint ~ '^[0-9a-f]{64}$'),
  CHECK (local_day_end_utc > local_day_start_utc),
  CHECK (scheduled_at_utc >= local_day_start_utc AND scheduled_at_utc < local_day_end_utc),
  CHECK (
    (state = 'SCHEDULED' AND dispatch_reserved_at IS NULL) OR
    (state = 'DISPATCH_RESERVED' AND dispatch_reserved_at IS NOT NULL) OR
    state = 'CANCELLED'
  )
);

CREATE INDEX idx_publication_delivery_due
  ON publication_delivery_reservations(scheduled_at_utc, created_at)
  WHERE state = 'SCHEDULED';
CREATE INDEX idx_publication_delivery_channel_time
  ON publication_delivery_reservations(channel_id, scheduled_at_utc)
  WHERE state <> 'CANCELLED';

CREATE FUNCTION require_publication_delivery_schedule() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text;
  current_platform text;
  current_status text;
  current_version bigint;
  current_content uuid;
  current_channel uuid;
  current_asset uuid;
  current_artifact integer;
  current_destination text;
  current_timezone text;
  current_contract text;
  current_enabled boolean;
  current_permissions text;
  current_destination_current boolean;
  current_credentials_current boolean;
  current_remote_upload text;
  current_remote_post text;
  current_instagram_phase text;
  current_facebook_phase text;
  approval_decision text;
  approval_expiry timestamptz;
  approval_owner text;
  approval_platform text;
  approval_content uuid;
  approval_channel uuid;
  approval_asset uuid;
  approval_artifact integer;
  approval_request_fingerprint text;
  approval_version bigint;
  approval_destination text;
  active_count integer;
BEGIN
  SELECT b.owner_user_id, ch.platform, p.status, p.publication_state_version,
         p.content_id, p.channel_id, p.asset_id, p.artifact_version,
         p.destination_fingerprint, b.timezone, p.publication_contract,
         ch.enabled, ch.permissions_status,
         ch.external_channel_id = p.channel_external_id_snapshot,
         ch.credentials_ref = p.credentials_ref_snapshot,
         p.remote_upload_id, p.remote_post_id,
         p.instagram_phase, p.facebook_phase,
         a.decision, a.valid_until, a.owner_user_id, a.platform,
         a.content_id, a.channel_id, a.asset_id, a.artifact_version,
         a.publication_request_fingerprint, a.publication_state_version,
         a.destination_fingerprint
    INTO current_owner, current_platform, current_status, current_version,
         current_content, current_channel, current_asset, current_artifact,
         current_destination, current_timezone, current_contract,
         current_enabled, current_permissions, current_destination_current,
         current_credentials_current, current_remote_upload, current_remote_post,
         current_instagram_phase, current_facebook_phase,
         approval_decision, approval_expiry, approval_owner, approval_platform,
         approval_content, approval_channel, approval_asset, approval_artifact,
         approval_request_fingerprint, approval_version,
         approval_destination
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    JOIN publication_delivery_approvals AS a
      ON a.id = NEW.approval_id AND a.publication_id = p.id
    WHERE p.id = NEW.publication_id
    FOR UPDATE OF p, ch;

  SELECT count(*) INTO active_count
    FROM publication_delivery_reservations AS r
    WHERE r.channel_id = NEW.channel_id AND r.state <> 'CANCELLED'
      AND r.scheduled_at_utc >= NEW.local_day_start_utc
      AND r.scheduled_at_utc < NEW.local_day_end_utc;

  IF current_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.content_id IS DISTINCT FROM current_content
     OR NEW.channel_id IS DISTINCT FROM current_channel
     OR NEW.asset_id IS DISTINCT FROM current_asset
     OR NEW.artifact_version IS DISTINCT FROM current_artifact
     OR NEW.publication_state_version IS DISTINCT FROM current_version
     OR NEW.destination_fingerprint IS DISTINCT FROM current_destination
     OR NEW.timezone_name IS DISTINCT FROM current_timezone
     OR current_status IS DISTINCT FROM 'DRAFT'
     OR current_enabled IS DISTINCT FROM true
     OR current_permissions IS DISTINCT FROM 'VALID'
     OR current_destination_current IS DISTINCT FROM true
     OR current_credentials_current IS DISTINCT FROM true
     OR current_remote_upload IS NOT NULL
     OR current_remote_post IS NOT NULL
     OR (current_platform = 'YOUTUBE' AND current_contract <> 'YOUTUBE_V1')
     OR (current_platform = 'INSTAGRAM' AND (
          current_contract <> 'INSTAGRAM_REELS_V1'
          OR current_instagram_phase <> 'CLAIMED'))
     OR (current_platform = 'FACEBOOK' AND (
          current_contract <> 'FACEBOOK_REELS_V1'
          OR current_facebook_phase <> 'CLAIMED'))
     OR approval_decision IS DISTINCT FROM 'APPROVE'
     OR approval_expiry <= NEW.scheduled_at_utc
     OR approval_owner IS DISTINCT FROM current_owner
     OR approval_platform IS DISTINCT FROM current_platform
     OR approval_content IS DISTINCT FROM current_content
     OR approval_channel IS DISTINCT FROM current_channel
     OR approval_asset IS DISTINCT FROM current_asset
     OR approval_artifact IS DISTINCT FROM current_artifact
     OR approval_request_fingerprint IS DISTINCT FROM
        (SELECT p.request_fingerprint FROM publication_jobs AS p
         WHERE p.id = NEW.publication_id)
     OR approval_version IS DISTINCT FROM current_version
     OR approval_destination IS DISTINCT FROM current_destination
     OR NEW.local_scheduled_at IS DISTINCT FROM
        (NEW.scheduled_at_utc AT TIME ZONE NEW.timezone_name)
     OR NEW.utc_offset_minutes IS DISTINCT FROM
        (EXTRACT(EPOCH FROM (
          NEW.local_scheduled_at - (NEW.scheduled_at_utc AT TIME ZONE 'UTC')
        )) / 60)::integer
     OR NEW.local_day_start_utc IS DISTINCT FROM
        (date_trunc('day', NEW.local_scheduled_at) AT TIME ZONE NEW.timezone_name)
     OR NEW.local_day_end_utc IS DISTINCT FROM
        ((date_trunc('day', NEW.local_scheduled_at) + interval '1 day')
          AT TIME ZONE NEW.timezone_name)
     OR active_count >= NEW.daily_cap
     OR EXISTS (
       SELECT 1 FROM publication_delivery_reservations AS r
       WHERE r.channel_id = NEW.channel_id AND r.state <> 'CANCELLED'
         AND abs(EXTRACT(EPOCH FROM (r.scheduled_at_utc - NEW.scheduled_at_utc)))
             < NEW.minimum_gap_seconds
     )
     OR EXISTS (
       SELECT 1 FROM publication_reconciliations AS pr
       WHERE pr.publication_id = NEW.publication_id
         AND pr.requires_human_review = true
     ) THEN
    RAISE EXCEPTION 'publication delivery schedule evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_delivery_reservations_require_evidence
  BEFORE INSERT ON publication_delivery_reservations
  FOR EACH ROW EXECUTE FUNCTION require_publication_delivery_schedule();

CREATE FUNCTION guard_publication_delivery_reservation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'publication delivery reservations cannot be deleted'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.id, NEW.request_id, NEW.publication_id, NEW.approval_id,
      NEW.owner_user_id, NEW.content_id, NEW.platform, NEW.channel_id,
      NEW.asset_id, NEW.artifact_version, NEW.publication_state_version,
      NEW.destination_fingerprint, NEW.local_scheduled_at, NEW.timezone_name,
      NEW.schedule_fold, NEW.utc_offset_minutes, NEW.scheduled_at_utc,
      NEW.local_day_start_utc, NEW.local_day_end_utc, NEW.daily_cap,
      NEW.minimum_gap_seconds, NEW.outbox_job_id, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.request_id, OLD.publication_id, OLD.approval_id,
      OLD.owner_user_id, OLD.content_id, OLD.platform, OLD.channel_id,
      OLD.asset_id, OLD.artifact_version, OLD.publication_state_version,
      OLD.destination_fingerprint, OLD.local_scheduled_at, OLD.timezone_name,
      OLD.schedule_fold, OLD.utc_offset_minutes, OLD.scheduled_at_utc,
      OLD.local_day_start_utc, OLD.local_day_end_utc, OLD.daily_cap,
      OLD.minimum_gap_seconds, OLD.outbox_job_id, OLD.created_at)
     OR OLD.state <> 'SCHEDULED'
     OR NEW.state NOT IN ('DISPATCH_RESERVED','CANCELLED')
     OR (NEW.state = 'DISPATCH_RESERVED' AND NEW.dispatch_reserved_at IS NULL)
     OR (NEW.state = 'CANCELLED' AND NEW.dispatch_reserved_at IS NOT NULL) THEN
    RAISE EXCEPTION 'publication delivery reservation transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_delivery_reservations_guard_update
  BEFORE UPDATE ON publication_delivery_reservations
  FOR EACH ROW EXECUTE FUNCTION guard_publication_delivery_reservation();

CREATE TRIGGER publication_delivery_reservations_prevent_delete
  BEFORE DELETE ON publication_delivery_reservations
  FOR EACH ROW EXECUTE FUNCTION guard_publication_delivery_reservation();

CREATE FUNCTION reserve_due_publication_delivery() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  reservation_id uuid;
BEGIN
  IF NOT (
    (OLD.publication_contract = 'YOUTUBE_V1' AND OLD.status = 'DRAFT'
      AND NEW.status = 'PUBLISH_REQUESTED') OR
    (OLD.publication_contract = 'INSTAGRAM_REELS_V1' AND OLD.status = 'DRAFT'
      AND OLD.instagram_phase = 'CLAIMED' AND NEW.status = 'UPLOAD_STARTED'
      AND NEW.instagram_phase = 'CONTAINER_RESERVED') OR
    (OLD.publication_contract = 'FACEBOOK_REELS_V1' AND OLD.status = 'DRAFT'
      AND OLD.facebook_phase = 'CLAIMED' AND NEW.status = 'UPLOAD_STARTED'
      AND NEW.facebook_phase = 'START_RESERVED')
  ) THEN
    RETURN NEW;
  END IF;

  SELECT r.id INTO reservation_id
    FROM publication_delivery_reservations AS r
    JOIN publication_delivery_approvals AS a ON a.id = r.approval_id
    JOIN social_channels AS ch ON ch.id = r.channel_id
    WHERE r.publication_id = OLD.id
      AND r.owner_user_id = (SELECT b.owner_user_id FROM brands AS b WHERE b.id = ch.brand_id)
      AND r.content_id = OLD.content_id AND r.channel_id = OLD.channel_id
      AND r.asset_id = OLD.asset_id AND r.artifact_version = OLD.artifact_version
      AND r.publication_state_version = OLD.publication_state_version
      AND r.destination_fingerprint = OLD.destination_fingerprint
      AND r.state = 'SCHEDULED' AND r.scheduled_at_utc <= now()
      AND a.decision = 'APPROVE' AND a.valid_until > now()
      AND ch.enabled = true AND ch.permissions_status = 'VALID'
      AND ch.external_channel_id = OLD.channel_external_id_snapshot
      AND ch.credentials_ref = OLD.credentials_ref_snapshot
      AND NOT EXISTS (
        SELECT 1 FROM publication_reconciliations AS pr
        WHERE pr.publication_id = OLD.id AND pr.requires_human_review = true
      )
    FOR UPDATE OF r;

  IF reservation_id IS NULL THEN
    RAISE EXCEPTION 'due approved publication delivery reservation is required'
      USING ERRCODE = 'check_violation';
  END IF;
  UPDATE publication_delivery_reservations
     SET state = 'DISPATCH_RESERVED', dispatch_reserved_at = now()
   WHERE id = reservation_id AND state = 'SCHEDULED';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'publication delivery reservation is already claimed'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_jobs_require_due_delivery
  BEFORE UPDATE ON publication_jobs
  FOR EACH ROW EXECUTE FUNCTION reserve_due_publication_delivery();
