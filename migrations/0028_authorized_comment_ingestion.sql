-- Authorized, read-only, replay-safe ingestion of first-party comments.

CREATE TABLE comment_ingestion_runs (
  sync_id uuid PRIMARY KEY,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  reconciliation_request_id uuid NOT NULL
    REFERENCES publication_reconciliations(request_id),
  last_page_index integer NOT NULL DEFAULT 0
    CHECK (last_page_index BETWEEN 0 AND 1000),
  next_cursor text CHECK (
    next_cursor IS NULL OR (
      length(next_cursor) BETWEEN 1 AND 2048
      AND next_cursor !~ '[[:cntrl:]]'
      AND next_cursor = btrim(next_cursor)
    )
  ),
  status text NOT NULL CHECK (status IN ('ACTIVE','COMPLETE','ABANDONED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (status = 'ACTIVE' AND (
      (last_page_index = 0 AND next_cursor IS NULL) OR
      (last_page_index > 0 AND next_cursor IS NOT NULL)
    )) OR
    (status = 'COMPLETE' AND last_page_index > 0 AND next_cursor IS NULL) OR
    (status = 'ABANDONED' AND next_cursor IS NULL)
  )
);

CREATE UNIQUE INDEX uq_comment_ingestion_active_publication
  ON comment_ingestion_runs(publication_id) WHERE status = 'ACTIVE';

CREATE FUNCTION expected_comment_ingestion_target(
  publication_value uuid,
  owner_value text,
  platform_value text,
  state_version_value bigint,
  request_fingerprint_value text,
  channel_value uuid,
  destination_value text,
  destination_fingerprint_value text,
  remote_object_value text,
  remote_url_value text,
  reconciliation_request_value uuid,
  reconciliation_target_value text,
  reconciliation_observation_value text
) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT encode(digest(concat_ws('|',
    publication_value::text, owner_value, platform_value,
    state_version_value::text, request_fingerprint_value,
    channel_value::text, destination_value, destination_fingerprint_value,
    remote_object_value, remote_url_value, reconciliation_request_value::text,
    reconciliation_target_value, reconciliation_observation_value
  ), 'sha256'), 'hex')
$$;

CREATE FUNCTION require_comment_ingestion_run() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text;
  current_platform text;
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
  reconciliation_target text;
  reconciliation_observation text;
  reconciliation_observed_at timestamptz;
  expected_target text;
BEGIN
  SELECT b.owner_user_id, ch.platform, p.publication_state_version,
         p.request_fingerprint, p.channel_id, p.channel_external_id_snapshot,
         p.destination_fingerprint,
         CASE ch.platform
           WHEN 'YOUTUBE' THEN p.remote_post_id
           WHEN 'INSTAGRAM' THEN p.remote_post_id
           WHEN 'FACEBOOK' THEN p.remote_upload_id
         END,
         p.remote_url, p.publication_contract, ch.enabled,
         ch.permissions_status, r.target_fingerprint,
         r.observation_fingerprint, r.observed_at
    INTO current_owner, current_platform, current_version,
         current_request_fingerprint, current_channel, current_destination,
         current_destination_fingerprint, current_remote_object,
         current_remote_url, current_contract, channel_enabled,
         channel_permissions, reconciliation_target,
         reconciliation_observation, reconciliation_observed_at
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    JOIN publication_reconciliations AS r
      ON r.request_id = NEW.reconciliation_request_id
     AND r.publication_id = p.id
     AND r.platform = ch.platform
     AND r.local_status = 'PUBLISHED'
     AND r.remote_state = 'PUBLISHED'
     AND r.verdict = 'IN_SYNC'
     AND r.remote_object_id = CASE ch.platform
       WHEN 'YOUTUBE' THEN p.remote_post_id
       WHEN 'INSTAGRAM' THEN p.remote_post_id
       WHEN 'FACEBOOK' THEN p.remote_upload_id
     END
     AND r.remote_url = p.remote_url
    WHERE p.id = NEW.publication_id
      AND p.status = 'PUBLISHED'
      AND ch.external_channel_id = p.channel_external_id_snapshot
      AND ch.credentials_ref = p.credentials_ref_snapshot
      AND NOT EXISTS (
        SELECT 1 FROM publication_reconciliations AS newer
        WHERE newer.publication_id = p.id
          AND newer.platform = ch.platform
          AND (
            newer.observed_at > r.observed_at OR
            (newer.observed_at = r.observed_at
             AND newer.request_id::text > r.request_id::text)
          )
      )
    FOR KEY SHARE OF p, ch;

  expected_target := expected_comment_ingestion_target(
    NEW.publication_id, current_owner, current_platform, current_version,
    current_request_fingerprint, current_channel, current_destination,
    current_destination_fingerprint, current_remote_object,
    current_remote_url, NEW.reconciliation_request_id,
    reconciliation_target, reconciliation_observation
  );

  IF current_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.target_fingerprint IS DISTINCT FROM expected_target
     OR NEW.last_page_index <> 0 OR NEW.next_cursor IS NOT NULL
     OR NEW.status <> 'ACTIVE'
     OR NEW.updated_at IS DISTINCT FROM NEW.created_at
     OR channel_enabled IS DISTINCT FROM true
     OR channel_permissions IS DISTINCT FROM 'VALID'
     OR reconciliation_observed_at < clock_timestamp() - interval '24 hours'
     OR reconciliation_observed_at > clock_timestamp() + interval '2 minutes'
     OR (current_platform = 'YOUTUBE' AND current_contract <> 'YOUTUBE_V1')
     OR (current_platform = 'INSTAGRAM' AND current_contract <> 'INSTAGRAM_REELS_V1')
     OR (current_platform = 'FACEBOOK' AND current_contract <> 'FACEBOOK_REELS_V1') THEN
    RAISE EXCEPTION 'comment ingestion run evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comment_ingestion_runs_require_evidence
  BEFORE INSERT ON comment_ingestion_runs
  FOR EACH ROW EXECUTE FUNCTION require_comment_ingestion_run();

CREATE TABLE comment_ingestion_attempts (
  request_id uuid PRIMARY KEY,
  sync_id uuid NOT NULL REFERENCES comment_ingestion_runs(sync_id),
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  page_index integer NOT NULL CHECK (page_index BETWEEN 1 AND 1000),
  cursor_fingerprint char(64) NOT NULL CHECK (cursor_fingerprint ~ '^[0-9a-f]{64}$'),
  status text NOT NULL CHECK (status IN ('RESERVED','RECORDED','ABANDONED')),
  attempt_count integer NOT NULL CHECK (attempt_count BETWEEN 1 AND 10),
  lease_expires_at timestamptz,
  last_error_code text CHECK (
    last_error_code IS NULL OR last_error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'
  ),
  created_at timestamptz NOT NULL DEFAULT now(),
  recorded_at timestamptz,
  abandoned_at timestamptz,
  UNIQUE (sync_id, page_index),
  UNIQUE (request_id, sync_id, publication_id),
  CHECK (
    (status = 'RESERVED' AND recorded_at IS NULL AND abandoned_at IS NULL
      AND lease_expires_at IS NOT NULL) OR
    (status = 'RECORDED' AND recorded_at IS NOT NULL AND abandoned_at IS NULL
      AND lease_expires_at IS NULL) OR
    (status = 'ABANDONED' AND recorded_at IS NULL AND abandoned_at IS NOT NULL
      AND lease_expires_at IS NULL)
  )
);

CREATE FUNCTION guard_comment_ingestion_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  run_value comment_ingestion_runs%ROWTYPE;
  expected_cursor text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'comment ingestion attempts are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT * INTO run_value FROM comment_ingestion_runs
      WHERE sync_id = NEW.sync_id FOR KEY SHARE;
    expected_cursor := encode(digest(COALESCE(run_value.next_cursor, ''), 'sha256'), 'hex');
    IF run_value.sync_id IS NULL
       OR NEW.publication_id IS DISTINCT FROM run_value.publication_id
       OR NEW.owner_user_id IS DISTINCT FROM run_value.owner_user_id
       OR NEW.target_fingerprint IS DISTINCT FROM run_value.target_fingerprint
       OR NEW.page_index IS DISTINCT FROM run_value.last_page_index + 1
       OR NEW.cursor_fingerprint IS DISTINCT FROM expected_cursor
       OR run_value.status <> 'ACTIVE'
       OR NEW.status <> 'RESERVED' OR NEW.attempt_count <> 1
       OR NEW.lease_expires_at <= clock_timestamp()
       OR NEW.last_error_code IS NOT NULL
       OR NEW.recorded_at IS NOT NULL OR NEW.abandoned_at IS NOT NULL THEN
      RAISE EXCEPTION 'comment ingestion reservation is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF (NEW.request_id, NEW.sync_id, NEW.publication_id, NEW.owner_user_id,
      NEW.target_fingerprint, NEW.page_index, NEW.cursor_fingerprint,
      NEW.created_at)
     IS DISTINCT FROM
     (OLD.request_id, OLD.sync_id, OLD.publication_id, OLD.owner_user_id,
      OLD.target_fingerprint, OLD.page_index, OLD.cursor_fingerprint,
      OLD.created_at)
     OR OLD.status <> 'RESERVED' OR NOT (
       (NEW.status = 'RESERVED'
        AND NEW.recorded_at IS NULL AND NEW.abandoned_at IS NULL
        AND NEW.lease_expires_at IS NOT NULL
        AND (
          (NEW.attempt_count = OLD.attempt_count
           AND NEW.last_error_code IS NOT NULL
           AND NEW.lease_expires_at <= clock_timestamp()) OR
          (NEW.attempt_count = OLD.attempt_count + 1
           AND NEW.last_error_code IS NULL
           AND NEW.lease_expires_at > OLD.lease_expires_at)
        )) OR
       (NEW.status = 'RECORDED'
        AND NEW.attempt_count = OLD.attempt_count
        AND NEW.recorded_at IS NOT NULL AND NEW.abandoned_at IS NULL
        AND NEW.lease_expires_at IS NULL
        AND EXISTS (
          SELECT 1 FROM comment_ingestion_batches
          WHERE request_id = NEW.request_id
        )) OR
       (NEW.status = 'ABANDONED'
        AND NEW.attempt_count = OLD.attempt_count
        AND NEW.recorded_at IS NULL AND NEW.abandoned_at IS NOT NULL
        AND NEW.lease_expires_at IS NULL
        AND NEW.last_error_code = 'RETRY_LIMIT_REACHED')
     ) THEN
    RAISE EXCEPTION 'comment ingestion reservation transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comment_ingestion_attempts_guard_insert
  BEFORE INSERT ON comment_ingestion_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_attempt();

CREATE TABLE comment_ingestion_batches (
  request_id uuid PRIMARY KEY,
  sync_id uuid NOT NULL,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  destination_id text NOT NULL CHECK (destination_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  remote_object_id text NOT NULL CHECK (remote_object_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  page_index integer NOT NULL CHECK (page_index BETWEEN 1 AND 1000),
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  cursor_fingerprint char(64) NOT NULL CHECK (cursor_fingerprint ~ '^[0-9a-f]{64}$'),
  next_cursor_fingerprint char(64) NOT NULL
    CHECK (next_cursor_fingerprint ~ '^[0-9a-f]{64}$'),
  comment_count integer NOT NULL CHECK (comment_count BETWEEN 0 AND 500),
  comment_remote_ids text[] NOT NULL,
  comment_fingerprints text[] NOT NULL,
  has_more boolean NOT NULL,
  provider_evidence_id text NOT NULL
    CHECK (provider_evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  observed_at timestamptz NOT NULL,
  batch_fingerprint char(64) NOT NULL CHECK (batch_fingerprint ~ '^[0-9a-f]{64}$'),
  authorization_fingerprint char(64) NOT NULL
    CHECK (authorization_fingerprint ~ '^[0-9a-f]{64}$'),
  authorization_scopes text[] NOT NULL,
  authorization_checked_at timestamptz NOT NULL,
  authorization_valid_until timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (request_id, sync_id, publication_id)
    REFERENCES comment_ingestion_attempts(request_id, sync_id, publication_id),
  UNIQUE (sync_id, page_index),
  CHECK (
    cardinality(comment_remote_ids) = comment_count
    AND cardinality(comment_fingerprints) = comment_count
  ),
  CHECK (authorization_valid_until > authorization_checked_at)
);

CREATE FUNCTION require_comment_ingestion_batch() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  run_value comment_ingestion_runs%ROWTYPE;
  attempt_value comment_ingestion_attempts%ROWTYPE;
  reconciliation_target text;
  reconciliation_observation text;
  expected_target text;
  expected_batch text;
  fingerprint_value text;
  remote_id_value text;
  expected_authorization text;
BEGIN
  SELECT * INTO run_value FROM comment_ingestion_runs
    WHERE sync_id = NEW.sync_id FOR KEY SHARE;
  SELECT * INTO attempt_value FROM comment_ingestion_attempts
    WHERE request_id = NEW.request_id FOR KEY SHARE;
  SELECT target_fingerprint, observation_fingerprint
    INTO reconciliation_target, reconciliation_observation
    FROM publication_reconciliations
    WHERE request_id = run_value.reconciliation_request_id
      AND publication_id = NEW.publication_id
      AND platform = NEW.platform
      AND local_status = 'PUBLISHED'
      AND remote_state = 'PUBLISHED'
      AND verdict = 'IN_SYNC'
      AND requires_human_review = false
      AND remote_object_id = NEW.remote_object_id;
  IF EXISTS (
    SELECT 1 FROM publication_reconciliations AS newer
    WHERE newer.publication_id = NEW.publication_id
      AND newer.platform = NEW.platform
      AND (
        newer.observed_at > (
          SELECT observed_at FROM publication_reconciliations
          WHERE request_id = run_value.reconciliation_request_id
        ) OR
        (newer.observed_at = (
          SELECT observed_at FROM publication_reconciliations
          WHERE request_id = run_value.reconciliation_request_id
        ) AND newer.request_id::text > run_value.reconciliation_request_id::text)
      )
  ) THEN
    RAISE EXCEPTION 'comment ingestion authorization is no longer current'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT expected_comment_ingestion_target(
    p.id, b.owner_user_id, ch.platform, p.publication_state_version,
    p.request_fingerprint, p.channel_id, p.channel_external_id_snapshot,
    p.destination_fingerprint,
    CASE ch.platform
      WHEN 'YOUTUBE' THEN p.remote_post_id
      WHEN 'INSTAGRAM' THEN p.remote_post_id
      WHEN 'FACEBOOK' THEN p.remote_upload_id
    END,
    p.remote_url, run_value.reconciliation_request_id,
    reconciliation_target, reconciliation_observation
  ) INTO expected_target
  FROM publication_jobs AS p
  JOIN social_channels AS ch ON ch.id = p.channel_id
  JOIN brands AS b ON b.id = ch.brand_id
  WHERE p.id = NEW.publication_id
    AND p.status = 'PUBLISHED'
    AND ch.enabled = true AND ch.permissions_status = 'VALID'
    AND ch.external_channel_id = p.channel_external_id_snapshot
    AND ch.credentials_ref = p.credentials_ref_snapshot
    AND b.owner_user_id = NEW.owner_user_id
    AND ch.platform = NEW.platform
    AND p.channel_external_id_snapshot = NEW.destination_id
    AND CASE ch.platform
      WHEN 'YOUTUBE' THEN p.remote_post_id
      WHEN 'INSTAGRAM' THEN p.remote_post_id
      WHEN 'FACEBOOK' THEN p.remote_upload_id
    END = NEW.remote_object_id
    AND (
      (ch.platform = 'YOUTUBE' AND p.publication_contract = 'YOUTUBE_V1') OR
      (ch.platform = 'INSTAGRAM' AND p.publication_contract = 'INSTAGRAM_REELS_V1') OR
      (ch.platform = 'FACEBOOK' AND p.publication_contract = 'FACEBOOK_REELS_V1')
    );

  FOREACH fingerprint_value IN ARRAY NEW.comment_fingerprints LOOP
    IF fingerprint_value !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'comment ingestion batch fingerprint list is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;
  FOREACH remote_id_value IN ARRAY NEW.comment_remote_ids LOOP
    IF remote_id_value !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$' THEN
      RAISE EXCEPTION 'comment ingestion batch remote identity list is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;
  IF cardinality(NEW.comment_fingerprints) <> cardinality(
       ARRAY(SELECT DISTINCT value FROM unnest(NEW.comment_fingerprints) AS value)
     ) OR cardinality(NEW.comment_remote_ids) <> cardinality(
       ARRAY(SELECT DISTINCT value FROM unnest(NEW.comment_remote_ids) AS value)
     ) THEN
    RAISE EXCEPTION 'comment ingestion batch has duplicate comments'
      USING ERRCODE = 'check_violation';
  END IF;

  expected_batch := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.sync_id::text, NEW.publication_id::text,
    NEW.platform, NEW.destination_id, NEW.remote_object_id,
    NEW.page_index::text, NEW.cursor_fingerprint,
    array_to_string(NEW.comment_fingerprints, ','), NEW.has_more::text,
    NEW.next_cursor_fingerprint,
    to_char(NEW.observed_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    NEW.provider_evidence_id, NEW.authorization_fingerprint
  ), 'sha256'), 'hex');
  expected_authorization := encode(digest(concat_ws('|',
    NEW.platform, NEW.destination_id,
    array_to_string(NEW.authorization_scopes, ','),
    to_char(NEW.authorization_checked_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(NEW.authorization_valid_until AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');

  IF run_value.sync_id IS NULL OR attempt_value.request_id IS NULL
     OR NEW.publication_id IS DISTINCT FROM run_value.publication_id
     OR NEW.owner_user_id IS DISTINCT FROM run_value.owner_user_id
     OR NEW.platform IS DISTINCT FROM run_value.platform
     OR NEW.target_fingerprint IS DISTINCT FROM run_value.target_fingerprint
     OR NEW.target_fingerprint IS DISTINCT FROM expected_target
     OR NEW.sync_id IS DISTINCT FROM attempt_value.sync_id
     OR NEW.publication_id IS DISTINCT FROM attempt_value.publication_id
     OR NEW.owner_user_id IS DISTINCT FROM attempt_value.owner_user_id
     OR NEW.target_fingerprint IS DISTINCT FROM attempt_value.target_fingerprint
     OR NEW.page_index IS DISTINCT FROM attempt_value.page_index
     OR NEW.cursor_fingerprint IS DISTINCT FROM attempt_value.cursor_fingerprint
     OR attempt_value.status <> 'RESERVED'
     OR run_value.status <> 'ACTIVE'
     OR NEW.page_index IS DISTINCT FROM run_value.last_page_index + 1
     OR NEW.cursor_fingerprint IS DISTINCT FROM
       encode(digest(COALESCE(run_value.next_cursor, ''), 'sha256'), 'hex')
     OR NEW.has_more IS DISTINCT FROM
       (NEW.next_cursor_fingerprint <> encode(digest('', 'sha256'), 'hex'))
     OR NEW.batch_fingerprint IS DISTINCT FROM expected_batch
     OR NEW.authorization_fingerprint IS DISTINCT FROM expected_authorization
     OR NEW.authorization_scopes IS DISTINCT FROM ARRAY(
       SELECT DISTINCT scope_value
       FROM unnest(NEW.authorization_scopes) AS scope_value
       ORDER BY scope_value
     )
     OR cardinality(NEW.authorization_scopes) = 0
     OR EXISTS (
       SELECT 1 FROM unnest(NEW.authorization_scopes) AS scope_value
       WHERE scope_value !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'
     )
     OR (NEW.platform = 'YOUTUBE' AND NOT (
       'https://www.googleapis.com/auth/youtube.readonly' = ANY(NEW.authorization_scopes)
     ))
     OR (NEW.platform = 'INSTAGRAM' AND NOT (
       'instagram_business_basic' = ANY(NEW.authorization_scopes)
       AND 'instagram_business_manage_comments' = ANY(NEW.authorization_scopes)
     ))
     OR (NEW.platform = 'FACEBOOK' AND NOT (
       'pages_show_list' = ANY(NEW.authorization_scopes)
       AND 'pages_read_engagement' = ANY(NEW.authorization_scopes)
     ))
     OR NEW.authorization_checked_at < clock_timestamp() - interval '1 hour'
     OR NEW.authorization_checked_at > clock_timestamp() + interval '2 minutes'
     OR NEW.authorization_valid_until <= clock_timestamp()
     OR NEW.observed_at < clock_timestamp() - interval '1 hour'
     OR NEW.observed_at > clock_timestamp() + interval '2 minutes' THEN
    RAISE EXCEPTION 'comment ingestion batch evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comment_ingestion_batches_require_evidence
  BEFORE INSERT ON comment_ingestion_batches
  FOR EACH ROW EXECUTE FUNCTION require_comment_ingestion_batch();

CREATE FUNCTION guard_comment_ingestion_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'comment ingestion evidence is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER comment_ingestion_batches_prevent_update
  BEFORE UPDATE ON comment_ingestion_batches
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_immutable();

CREATE TRIGGER comment_ingestion_batches_prevent_delete
  BEFORE DELETE ON comment_ingestion_batches
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_immutable();

CREATE TABLE community_comment_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  destination_id text NOT NULL CHECK (destination_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  remote_object_id text NOT NULL CHECK (remote_object_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  remote_comment_id text NOT NULL
    CHECK (remote_comment_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'),
  parent_remote_comment_id text CHECK (
    parent_remote_comment_id IS NULL OR
    parent_remote_comment_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'
  ),
  author_external_id_hash char(64)
    CHECK (author_external_id_hash IS NULL OR author_external_id_hash ~ '^[0-9a-f]{64}$'),
  comment_text text CHECK (
    comment_text IS NULL OR (
      length(comment_text) BETWEEN 1 AND 10000
      AND replace(replace(replace(comment_text, E'\n', ''), E'\r', ''), E'\t', '')
        !~ '[[:cntrl:]]'
    )
  ),
  state text NOT NULL CHECK (state IN ('ACTIVE','EDITED','DELETED')),
  published_at timestamptz NOT NULL,
  provider_updated_at timestamptz NOT NULL,
  comment_fingerprint char(64) NOT NULL CHECK (comment_fingerprint ~ '^[0-9a-f]{64}$'),
  first_batch_request_id uuid NOT NULL REFERENCES comment_ingestion_batches(request_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (publication_id, remote_comment_id, comment_fingerprint),
  UNIQUE (publication_id, remote_comment_id, provider_updated_at),
  CHECK (parent_remote_comment_id IS DISTINCT FROM remote_comment_id),
  CHECK (provider_updated_at >= published_at),
  CHECK (
    (state = 'DELETED' AND author_external_id_hash IS NULL AND comment_text IS NULL) OR
    (state IN ('ACTIVE','EDITED')
      AND author_external_id_hash IS NOT NULL AND comment_text IS NOT NULL
      AND comment_text = btrim(comment_text))
  )
);

CREATE INDEX idx_community_comment_versions_current
  ON community_comment_versions(
    publication_id, remote_comment_id, provider_updated_at DESC, created_at DESC
  );

CREATE FUNCTION require_community_comment_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  batch_value comment_ingestion_batches%ROWTYPE;
  prior_value community_comment_versions%ROWTYPE;
  expected_fingerprint text;
  expected_ordinal integer;
BEGIN
  SELECT * INTO batch_value FROM comment_ingestion_batches
    WHERE request_id = NEW.first_batch_request_id FOR KEY SHARE;
  SELECT * INTO prior_value FROM community_comment_versions
    WHERE publication_id = NEW.publication_id
      AND remote_comment_id = NEW.remote_comment_id
    ORDER BY provider_updated_at DESC, created_at DESC
    LIMIT 1 FOR KEY SHARE;

  expected_fingerprint := encode(digest(concat_ws('|',
    NEW.remote_comment_id, COALESCE(NEW.parent_remote_comment_id, ''),
    COALESCE(NEW.author_external_id_hash, ''), COALESCE(NEW.comment_text, ''),
    NEW.state,
    to_char(NEW.published_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(NEW.provider_updated_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');
  expected_ordinal := array_position(
    batch_value.comment_fingerprints, NEW.comment_fingerprint
  );

  IF batch_value.request_id IS NULL
     OR NEW.publication_id IS DISTINCT FROM batch_value.publication_id
     OR NEW.owner_user_id IS DISTINCT FROM batch_value.owner_user_id
     OR NEW.platform IS DISTINCT FROM batch_value.platform
     OR NEW.destination_id IS DISTINCT FROM batch_value.destination_id
     OR NEW.remote_object_id IS DISTINCT FROM batch_value.remote_object_id
     OR NEW.provider_updated_at > batch_value.observed_at
     OR NEW.comment_fingerprint IS DISTINCT FROM expected_fingerprint
     OR expected_ordinal IS NULL
     OR NEW.remote_comment_id IS DISTINCT FROM
       batch_value.comment_remote_ids[expected_ordinal]
     OR (prior_value.id IS NOT NULL AND (
       NEW.published_at IS DISTINCT FROM prior_value.published_at
       OR NEW.parent_remote_comment_id IS DISTINCT FROM prior_value.parent_remote_comment_id
       OR NEW.provider_updated_at < prior_value.provider_updated_at
       OR (NEW.provider_updated_at = prior_value.provider_updated_at
           AND NEW.comment_fingerprint IS DISTINCT FROM prior_value.comment_fingerprint)
       OR (prior_value.state = 'DELETED'
           AND NEW.comment_fingerprint IS DISTINCT FROM prior_value.comment_fingerprint)
     )) THEN
    RAISE EXCEPTION 'community comment version evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER community_comment_versions_require_evidence
  BEFORE INSERT ON community_comment_versions
  FOR EACH ROW EXECUTE FUNCTION require_community_comment_version();

CREATE TRIGGER community_comment_versions_prevent_update
  BEFORE UPDATE ON community_comment_versions
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_immutable();

CREATE TRIGGER community_comment_versions_prevent_delete
  BEFORE DELETE ON community_comment_versions
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_immutable();

CREATE TABLE comment_ingestion_batch_items (
  batch_request_id uuid NOT NULL REFERENCES comment_ingestion_batches(request_id),
  ordinal integer NOT NULL CHECK (ordinal BETWEEN 1 AND 500),
  comment_version_id uuid NOT NULL REFERENCES community_comment_versions(id),
  PRIMARY KEY (batch_request_id, ordinal),
  UNIQUE (batch_request_id, comment_version_id)
);

CREATE FUNCTION require_comment_ingestion_batch_item() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  batch_value comment_ingestion_batches%ROWTYPE;
  version_value community_comment_versions%ROWTYPE;
BEGIN
  SELECT * INTO batch_value FROM comment_ingestion_batches
    WHERE request_id = NEW.batch_request_id FOR KEY SHARE;
  SELECT * INTO version_value FROM community_comment_versions
    WHERE id = NEW.comment_version_id FOR KEY SHARE;
  IF batch_value.request_id IS NULL OR version_value.id IS NULL
     OR NEW.ordinal > batch_value.comment_count
     OR version_value.publication_id IS DISTINCT FROM batch_value.publication_id
     OR version_value.owner_user_id IS DISTINCT FROM batch_value.owner_user_id
     OR version_value.platform IS DISTINCT FROM batch_value.platform
     OR version_value.destination_id IS DISTINCT FROM batch_value.destination_id
     OR version_value.remote_object_id IS DISTINCT FROM batch_value.remote_object_id
     OR version_value.comment_fingerprint IS DISTINCT FROM
       batch_value.comment_fingerprints[NEW.ordinal]
     OR version_value.remote_comment_id IS DISTINCT FROM
       batch_value.comment_remote_ids[NEW.ordinal] THEN
    RAISE EXCEPTION 'comment ingestion batch item evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comment_ingestion_batch_items_require_evidence
  BEFORE INSERT ON comment_ingestion_batch_items
  FOR EACH ROW EXECUTE FUNCTION require_comment_ingestion_batch_item();

CREATE TRIGGER comment_ingestion_batch_items_prevent_update
  BEFORE UPDATE ON comment_ingestion_batch_items
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_immutable();

CREATE TRIGGER comment_ingestion_batch_items_prevent_delete
  BEFORE DELETE ON comment_ingestion_batch_items
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_immutable();

CREATE FUNCTION verify_comment_ingestion_batch_completion() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  attempt_status text;
  run_value comment_ingestion_runs%ROWTYPE;
  item_count integer;
BEGIN
  SELECT status INTO attempt_status FROM comment_ingestion_attempts
    WHERE request_id = NEW.request_id;
  SELECT * INTO run_value FROM comment_ingestion_runs
    WHERE sync_id = NEW.sync_id;
  SELECT count(*) INTO item_count FROM comment_ingestion_batch_items
    WHERE batch_request_id = NEW.request_id;
  IF attempt_status IS DISTINCT FROM 'RECORDED'
     OR run_value.sync_id IS NULL
     OR run_value.last_page_index < NEW.page_index
     OR item_count IS DISTINCT FROM NEW.comment_count
     OR EXISTS (
       SELECT 1 FROM generate_series(1, NEW.comment_count) AS required(required_ordinal)
       WHERE NOT EXISTS (
         SELECT 1 FROM comment_ingestion_batch_items AS item
         WHERE item.batch_request_id = NEW.request_id
           AND item.ordinal = required_ordinal
       )
     ) THEN
    RAISE EXCEPTION 'comment ingestion batch is incomplete at commit'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER comment_ingestion_batches_verify_completion
  AFTER INSERT ON comment_ingestion_batches
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION verify_comment_ingestion_batch_completion();

CREATE FUNCTION advance_comment_ingestion_run() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  batch_value comment_ingestion_batches%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'comment ingestion runs are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status = 'ABANDONED' THEN
    IF (NEW.sync_id, NEW.publication_id, NEW.owner_user_id, NEW.platform,
        NEW.target_fingerprint, NEW.reconciliation_request_id,
        NEW.last_page_index, NEW.created_at)
       IS DISTINCT FROM
       (OLD.sync_id, OLD.publication_id, OLD.owner_user_id, OLD.platform,
        OLD.target_fingerprint, OLD.reconciliation_request_id,
        OLD.last_page_index, OLD.created_at)
       OR OLD.status <> 'ACTIVE' OR NEW.next_cursor IS NOT NULL
       OR NEW.updated_at <= OLD.updated_at
       OR NOT EXISTS (
         SELECT 1 FROM comment_ingestion_attempts
         WHERE sync_id = NEW.sync_id AND status = 'ABANDONED'
       ) THEN
      RAISE EXCEPTION 'comment ingestion run abandonment is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO batch_value FROM comment_ingestion_batches
    WHERE sync_id = NEW.sync_id AND page_index = NEW.last_page_index
    FOR KEY SHARE;
  IF (NEW.sync_id, NEW.publication_id, NEW.owner_user_id, NEW.platform,
      NEW.target_fingerprint, NEW.reconciliation_request_id, NEW.created_at)
     IS DISTINCT FROM
     (OLD.sync_id, OLD.publication_id, OLD.owner_user_id, OLD.platform,
      OLD.target_fingerprint, OLD.reconciliation_request_id, OLD.created_at)
     OR OLD.status <> 'ACTIVE'
     OR NEW.last_page_index <> OLD.last_page_index + 1
     OR NEW.updated_at <= OLD.updated_at
     OR batch_value.request_id IS NULL
     OR NEW.last_page_index IS DISTINCT FROM batch_value.page_index
     OR encode(digest(COALESCE(NEW.next_cursor, ''), 'sha256'), 'hex')
       IS DISTINCT FROM batch_value.next_cursor_fingerprint
     OR NEW.status IS DISTINCT FROM
       (CASE WHEN batch_value.has_more THEN 'ACTIVE' ELSE 'COMPLETE' END) THEN
    RAISE EXCEPTION 'comment ingestion run transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER comment_ingestion_runs_guard_update
  BEFORE UPDATE ON comment_ingestion_runs
  FOR EACH ROW EXECUTE FUNCTION advance_comment_ingestion_run();

CREATE TRIGGER comment_ingestion_runs_prevent_delete
  BEFORE DELETE ON comment_ingestion_runs
  FOR EACH ROW EXECUTE FUNCTION advance_comment_ingestion_run();

CREATE TRIGGER comment_ingestion_attempts_guard_update
  BEFORE UPDATE ON comment_ingestion_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_attempt();

CREATE TRIGGER comment_ingestion_attempts_prevent_delete
  BEFORE DELETE ON comment_ingestion_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_comment_ingestion_attempt();

CREATE VIEW community_comments_current AS
SELECT DISTINCT ON (publication_id, remote_comment_id)
  id, publication_id, owner_user_id, platform, destination_id,
  remote_object_id, remote_comment_id, parent_remote_comment_id,
  author_external_id_hash, comment_text, state, published_at,
  provider_updated_at, comment_fingerprint, first_batch_request_id, created_at
FROM community_comment_versions
ORDER BY publication_id, remote_comment_id,
         provider_updated_at DESC, created_at DESC;

REVOKE ALL ON comment_ingestion_runs FROM PUBLIC;
REVOKE ALL ON comment_ingestion_attempts FROM PUBLIC;
REVOKE ALL ON comment_ingestion_batches FROM PUBLIC;
REVOKE ALL ON community_comment_versions FROM PUBLIC;
REVOKE ALL ON comment_ingestion_batch_items FROM PUBLIC;
REVOKE ALL ON community_comments_current FROM PUBLIC;

COMMENT ON VIEW community_comments_current IS
  'Latest immutable first-party comment evidence; text remains untrusted and grants no reply or moderation authority.';
