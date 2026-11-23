-- Immutable owner-scoped platform metric evidence. Provider reads remain disabled by default.

CREATE TABLE analytics_metric_collection_attempts (
  request_id uuid PRIMARY KEY,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D')),
  metric_ids jsonb NOT NULL CHECK (
    jsonb_typeof(metric_ids) = 'array'
    AND jsonb_array_length(metric_ids) BETWEEN 1 AND 100
  ),
  registry_version text NOT NULL CHECK (
    registry_version ~ '^[a-z][a-z0-9.-]{0,63}$'
  ),
  registry_fingerprint char(64) NOT NULL
    CHECK (registry_fingerprint ~ '^[0-9a-f]{64}$'),
  status text NOT NULL CHECK (status IN ('RESERVED','RECORDED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  recorded_at timestamptz,
  UNIQUE (request_id, publication_id),
  CHECK (
    (status = 'RESERVED' AND recorded_at IS NULL) OR
    (status = 'RECORDED' AND recorded_at IS NOT NULL)
  )
);

CREATE FUNCTION guard_analytics_metric_collection_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'analytics metric collection attempts are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.request_id, NEW.publication_id, NEW.owner_user_id,
      NEW.request_fingerprint, NEW.target_fingerprint, NEW.window_name,
      NEW.metric_ids, NEW.registry_version, NEW.registry_fingerprint, NEW.created_at)
     IS DISTINCT FROM
     (OLD.request_id, OLD.publication_id, OLD.owner_user_id,
      OLD.request_fingerprint, OLD.target_fingerprint, OLD.window_name,
      OLD.metric_ids, OLD.registry_version, OLD.registry_fingerprint, OLD.created_at)
     OR OLD.status <> 'RESERVED' OR NEW.status <> 'RECORDED'
     OR OLD.recorded_at IS NOT NULL OR NEW.recorded_at IS NULL THEN
    RAISE EXCEPTION 'analytics metric collection attempt transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_metric_collection_attempts_guard_update
  BEFORE UPDATE ON analytics_metric_collection_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_analytics_metric_collection_attempt();

CREATE TRIGGER analytics_metric_collection_attempts_prevent_delete
  BEFORE DELETE ON analytics_metric_collection_attempts
  FOR EACH ROW EXECUTE FUNCTION guard_analytics_metric_collection_attempt();

CREATE TABLE analytics_metric_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL UNIQUE,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  publication_state_version bigint NOT NULL CHECK (publication_state_version >= 0),
  publication_request_fingerprint char(64) NOT NULL
    CHECK (publication_request_fingerprint ~ '^[0-9a-f]{64}$'),
  channel_id uuid NOT NULL REFERENCES social_channels(id),
  destination_id text NOT NULL CHECK (destination_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  destination_fingerprint char(64) NOT NULL
    CHECK (destination_fingerprint ~ '^[0-9a-f]{64}$'),
  remote_object_id text NOT NULL CHECK (remote_object_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  published_at timestamptz NOT NULL,
  window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D')),
  window_started_at timestamptz NOT NULL,
  window_ended_at timestamptz NOT NULL,
  source text NOT NULL CHECK (source IN (
    'YOUTUBE_ANALYTICS','INSTAGRAM_GRAPH','FACEBOOK_VIDEO_INSIGHTS'
  )),
  registry_version text NOT NULL CHECK (
    registry_version ~ '^[a-z][a-z0-9.-]{0,63}$'
  ),
  registry_fingerprint char(64) NOT NULL
    CHECK (registry_fingerprint ~ '^[0-9a-f]{64}$'),
  metric_data jsonb NOT NULL CHECK (
    jsonb_typeof(metric_data) = 'array'
    AND jsonb_array_length(metric_data) BETWEEN 1 AND 100
    AND pg_column_size(metric_data) <= 65536
  ),
  collection_status text NOT NULL CHECK (collection_status IN ('OK','PARTIAL')),
  provider_evidence_id text NOT NULL
    CHECK (provider_evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  observed_at timestamptz NOT NULL,
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  observation_fingerprint char(64) NOT NULL
    CHECK (observation_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (request_id, publication_id)
    REFERENCES analytics_metric_collection_attempts(request_id, publication_id),
  CHECK (window_started_at = published_at),
  CHECK (window_ended_at = window_started_at + CASE window_name
    WHEN '1H' THEN interval '1 hour'
    WHEN '24H' THEN interval '24 hours'
    WHEN '72H' THEN interval '72 hours'
    WHEN '7D' THEN interval '7 days'
    WHEN '28D' THEN interval '28 days'
  END),
  CHECK (observed_at >= window_ended_at)
);

CREATE INDEX idx_metric_observations_publication_window
  ON analytics_metric_observations(publication_id, window_name, observed_at DESC);

CREATE FUNCTION require_analytics_metric_observation_evidence() RETURNS trigger
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
  current_published_at timestamptz;
  current_contract text;
  current_source text;
  channel_enabled boolean;
  channel_permissions text;
  channel_credentials_match boolean;
  attempt_owner text;
  attempt_request text;
  attempt_target text;
  attempt_window text;
  attempt_registry text;
  attempt_registry_fingerprint text;
  attempt_metric_ids jsonb;
  attempt_status text;
  expected_target text;
  expected_status text;
  expected_metric_ids jsonb;
BEGIN
  SELECT b.owner_user_id, ch.platform, p.status, p.publication_state_version,
         p.request_fingerprint, p.channel_id, p.channel_external_id_snapshot,
         p.destination_fingerprint,
         CASE ch.platform
           WHEN 'YOUTUBE' THEN p.remote_post_id
           WHEN 'INSTAGRAM' THEN p.remote_post_id
           WHEN 'FACEBOOK' THEN p.remote_upload_id
         END,
         p.published_at, p.publication_contract,
         CASE ch.platform
           WHEN 'YOUTUBE' THEN 'YOUTUBE_ANALYTICS'
           WHEN 'INSTAGRAM' THEN 'INSTAGRAM_GRAPH'
           WHEN 'FACEBOOK' THEN 'FACEBOOK_VIDEO_INSIGHTS'
         END,
         ch.enabled, ch.permissions_status,
         ch.credentials_ref = p.credentials_ref_snapshot,
         a.owner_user_id, a.request_fingerprint, a.target_fingerprint,
         a.window_name, a.registry_version, a.registry_fingerprint,
         a.metric_ids, a.status
    INTO current_owner, current_platform, current_status, current_version,
         current_request_fingerprint, current_channel, current_destination,
         current_destination_fingerprint, current_remote_object,
         current_published_at, current_contract, current_source,
         channel_enabled, channel_permissions, channel_credentials_match,
         attempt_owner, attempt_request, attempt_target, attempt_window,
         attempt_registry, attempt_registry_fingerprint, attempt_metric_ids,
         attempt_status
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    JOIN analytics_metric_collection_attempts AS a
      ON a.request_id = NEW.request_id AND a.publication_id = p.id
    WHERE p.id = NEW.publication_id
      AND ch.external_channel_id = p.channel_external_id_snapshot
    FOR KEY SHARE OF p, ch;

  expected_metric_ids := (
    SELECT jsonb_agg(value ORDER BY value)
    FROM jsonb_array_elements(attempt_metric_ids) AS item(value)
  );
  expected_target := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.publication_id::text, current_owner,
    current_platform, current_version::text, current_request_fingerprint,
    current_channel::text, current_destination, current_destination_fingerprint,
    current_remote_object,
    to_char(current_published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    NEW.window_name,
    to_char(NEW.window_started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(NEW.window_ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    current_source, NEW.registry_version, NEW.registry_fingerprint,
    (SELECT string_agg(value #>> '{}', '|' ORDER BY value #>> '{}')
       FROM jsonb_array_elements(attempt_metric_ids) AS item(value))
  ), 'sha256'), 'hex');
  expected_status := CASE
    WHEN EXISTS (
      SELECT 1 FROM jsonb_array_elements(NEW.metric_data) AS datum
      WHERE datum->>'availability' <> 'AVAILABLE'
    ) THEN 'PARTIAL' ELSE 'OK' END;

  IF current_owner IS NULL
     OR current_status IS DISTINCT FROM 'PUBLISHED'
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.publication_state_version IS DISTINCT FROM current_version
     OR NEW.publication_request_fingerprint IS DISTINCT FROM current_request_fingerprint
     OR NEW.channel_id IS DISTINCT FROM current_channel
     OR NEW.destination_id IS DISTINCT FROM current_destination
     OR NEW.destination_fingerprint IS DISTINCT FROM current_destination_fingerprint
     OR NEW.remote_object_id IS DISTINCT FROM current_remote_object
     OR NEW.published_at IS DISTINCT FROM current_published_at
     OR NEW.source IS DISTINCT FROM current_source
     OR NEW.target_fingerprint IS DISTINCT FROM expected_target
     OR attempt_owner IS DISTINCT FROM current_owner
     OR attempt_request IS DISTINCT FROM encode(digest(concat_ws('|',
          NEW.request_id::text, NEW.publication_id::text, current_owner,
          NEW.window_name,
          (SELECT string_agg(value #>> '{}', '|' ORDER BY value #>> '{}')
             FROM jsonb_array_elements(attempt_metric_ids) AS item(value))
        ), 'sha256'), 'hex')
     OR attempt_target IS DISTINCT FROM expected_target
     OR attempt_window IS DISTINCT FROM NEW.window_name
     OR attempt_registry IS DISTINCT FROM NEW.registry_version
     OR attempt_registry_fingerprint IS DISTINCT FROM NEW.registry_fingerprint
     OR expected_metric_ids IS DISTINCT FROM attempt_metric_ids
     OR jsonb_array_length(NEW.metric_data) <> jsonb_array_length(attempt_metric_ids)
     OR EXISTS (
       SELECT 1
       FROM jsonb_array_elements(NEW.metric_data) WITH ORDINALITY AS datum(value, n)
       JOIN jsonb_array_elements(attempt_metric_ids) WITH ORDINALITY AS metric(value, n)
         USING (n)
       WHERE CASE
         WHEN jsonb_typeof(datum.value) IS DISTINCT FROM 'object' THEN true
         ELSE
           NOT (datum.value ?& ARRAY[
             'metric_id','availability','value','unavailable_reason'
           ])
           OR (SELECT count(*) FROM jsonb_object_keys(datum.value)) <> 4
           OR datum.value->>'metric_id' IS DISTINCT FROM metric.value #>> '{}'
           OR datum.value->>'availability' NOT IN ('AVAILABLE','UNAVAILABLE')
           OR (datum.value->>'availability' = 'AVAILABLE' AND (
                 jsonb_typeof(datum.value->'value') NOT IN ('number','object')
                 OR datum.value->'unavailable_reason' <> 'null'::jsonb))
           OR (datum.value->>'availability' = 'UNAVAILABLE' AND (
                 datum.value->'value' <> 'null'::jsonb
                 OR datum.value->>'unavailable_reason' NOT IN (
                   'FIELD_NOT_RETURNED','PERMISSION_DENIED','NOT_SUPPORTED','PROVIDER_REDACTED'
                 )))
       END
     )
     OR NEW.collection_status IS DISTINCT FROM expected_status
     OR attempt_status IS DISTINCT FROM 'RESERVED'
     OR channel_enabled IS DISTINCT FROM true
     OR channel_permissions IS DISTINCT FROM 'VALID'
     OR channel_credentials_match IS DISTINCT FROM true
     OR (current_platform = 'YOUTUBE' AND current_contract <> 'YOUTUBE_V1')
     OR (current_platform = 'INSTAGRAM' AND current_contract <> 'INSTAGRAM_REELS_V1')
     OR (current_platform = 'FACEBOOK' AND current_contract <> 'FACEBOOK_REELS_V1') THEN
    RAISE EXCEPTION 'analytics metric observation evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_metric_observations_require_evidence
  BEFORE INSERT ON analytics_metric_observations
  FOR EACH ROW EXECUTE FUNCTION require_analytics_metric_observation_evidence();

CREATE FUNCTION guard_analytics_metric_observation_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'analytics metric observations are immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER analytics_metric_observations_prevent_update
  BEFORE UPDATE ON analytics_metric_observations
  FOR EACH ROW EXECUTE FUNCTION guard_analytics_metric_observation_immutable();

CREATE TRIGGER analytics_metric_observations_prevent_delete
  BEFORE DELETE ON analytics_metric_observations
  FOR EACH ROW EXECUTE FUNCTION guard_analytics_metric_observation_immutable();

