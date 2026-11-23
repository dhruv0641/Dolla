-- Immutable creative-factor lineage and descriptive, non-causal cohort evidence.

CREATE TABLE creative_metadata_snapshots (
  snapshot_id uuid PRIMARY KEY,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  brand_id uuid NOT NULL REFERENCES brands(id),
  content_id uuid NOT NULL REFERENCES content_items(id),
  artifact_version integer NOT NULL CHECK (artifact_version > 0),
  storyboard_version integer NOT NULL CHECK (storyboard_version > 0),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  published_at timestamptz NOT NULL,
  schema_version text NOT NULL
    CHECK (schema_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  source_fingerprint char(64) NOT NULL
    CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
  factors jsonb NOT NULL CHECK (
    jsonb_typeof(factors) = 'array'
    AND jsonb_array_length(factors) = 13
    AND pg_column_size(factors) <= 65536
  ),
  snapshot_fingerprint char(64) NOT NULL UNIQUE
    CHECK (snapshot_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL
    CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  UNIQUE (publication_id, schema_version)
);

CREATE FUNCTION require_creative_metadata_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text;
  current_brand uuid;
  current_content uuid;
  current_artifact integer;
  current_storyboard integer;
  current_platform text;
  current_published_at timestamptz;
  factor_count integer;
  distinct_factor_count integer;
BEGIN
  SELECT b.owner_user_id, b.id, c.id, p.artifact_version,
         c.storyboard_version, ch.platform, p.published_at
    INTO current_owner, current_brand, current_content, current_artifact,
         current_storyboard, current_platform, current_published_at
    FROM publication_jobs AS p
    JOIN content_items AS c ON c.id = p.content_id
    JOIN brands AS b ON b.id = c.brand_id
    JOIN social_channels AS ch
      ON ch.id = p.channel_id AND ch.brand_id = b.id
    JOIN storyboard_versions AS sv
      ON sv.content_id = c.id AND sv.version = NEW.storyboard_version
   WHERE p.id = NEW.publication_id
     AND p.status = 'PUBLISHED' AND p.published_at IS NOT NULL
   FOR SHARE OF p, c, b, ch, sv;

  SELECT count(*), count(DISTINCT value->>'factor')
    INTO factor_count, distinct_factor_count
    FROM jsonb_array_elements(NEW.factors) AS item(value);

  IF current_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.brand_id IS DISTINCT FROM current_brand
     OR NEW.content_id IS DISTINCT FROM current_content
     OR NEW.artifact_version IS DISTINCT FROM current_artifact
     OR NEW.storyboard_version IS DISTINCT FROM current_storyboard
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.published_at IS DISTINCT FROM current_published_at
     OR NEW.created_at < current_published_at
     OR factor_count <> 13 OR distinct_factor_count <> 13
     OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(NEW.factors) AS item(value)
       WHERE jsonb_typeof(value) <> 'object'
          OR (SELECT count(*) FROM jsonb_object_keys(value)) <> 5
          OR value->>'factor' NOT IN (
            'NICHE','HOOK_TYPE','SCRIPT_WORD_COUNT','CTA_TYPE','SCENE_COUNT',
            'DURATION_SECONDS','NARRATOR_VOICE','POSTING_TIME_UTC','PLATFORM',
            'LANGUAGE','VISUAL_MOTIF','FLOW_MODEL','FLOW_COST_MICROCREDITS'
          )
          OR value->>'availability' NOT IN ('OBSERVED','UNAVAILABLE','NOT_APPLICABLE')
          OR NOT (value ? 'value' AND value ? 'evidence_ref' AND value ? 'unavailable_reason')
          OR CASE value->>'availability'
               WHEN 'OBSERVED' THEN
                 jsonb_typeof(value->'value') <> 'string'
                 OR value->>'value' = '' OR length(value->>'value') > 200
                 OR jsonb_typeof(value->'evidence_ref') <> 'string'
                 OR value->>'evidence_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'
                 OR jsonb_typeof(value->'unavailable_reason') <> 'null'
               WHEN 'UNAVAILABLE' THEN
                 jsonb_typeof(value->'value') <> 'null'
                 OR jsonb_typeof(value->'evidence_ref') <> 'null'
                 OR value->>'unavailable_reason' NOT IN (
                   'NOT_CAPTURED','SOURCE_UNAVAILABLE','SOURCE_AMBIGUOUS'
                 )
               WHEN 'NOT_APPLICABLE' THEN
                 jsonb_typeof(value->'value') <> 'null'
                 OR jsonb_typeof(value->'evidence_ref') <> 'null'
                 OR jsonb_typeof(value->'unavailable_reason') <> 'null'
               ELSE true
             END
     )
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','PLATFORM','availability','OBSERVED','value',NEW.platform
     ))
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','POSTING_TIME_UTC','availability','OBSERVED',
       'value',to_char(NEW.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
     )) THEN
    RAISE EXCEPTION 'creative metadata snapshot evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;

  NEW.storage_fingerprint := encode(digest(concat_ws('|',
    NEW.snapshot_id::text, NEW.publication_id::text, NEW.owner_user_id,
    NEW.brand_id::text, NEW.content_id::text, NEW.artifact_version::text,
    NEW.storyboard_version::text, NEW.platform,
    to_char(NEW.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    NEW.schema_version, NEW.source_fingerprint, NEW.factors::text,
    NEW.snapshot_fingerprint,
    to_char(NEW.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER creative_metadata_snapshots_require_evidence
  BEFORE INSERT ON creative_metadata_snapshots
  FOR EACH ROW EXECUTE FUNCTION require_creative_metadata_evidence();

CREATE TABLE cohort_analysis_reports (
  request_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL UNIQUE
    CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  definition_version text NOT NULL
    CHECK (definition_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  factor text NOT NULL CHECK (factor IN (
    'NICHE','HOOK_TYPE','SCRIPT_WORD_COUNT','CTA_TYPE','SCENE_COUNT',
    'DURATION_SECONDS','NARRATOR_VOICE','POSTING_TIME_UTC','LANGUAGE',
    'VISUAL_MOTIF','FLOW_MODEL','FLOW_COST_MICROCREDITS'
  )),
  metric_id text NOT NULL,
  window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D')),
  registry_version text NOT NULL,
  registry_fingerprint char(64) NOT NULL,
  minimum_group_size integer NOT NULL CHECK (minimum_group_size BETWEEN 3 AND 10000),
  bands jsonb NOT NULL CHECK (
    jsonb_typeof(bands) = 'array' AND jsonb_array_length(bands) <= 20
    AND pg_column_size(bands) <= 32768
  ),
  report_data jsonb NOT NULL CHECK (
    jsonb_typeof(report_data) = 'object' AND pg_column_size(report_data) <= 1048576
  ),
  report_fingerprint char(64) NOT NULL UNIQUE
    CHECK (report_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL
    CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (registry_version, registry_fingerprint)
    REFERENCES analytics_metric_registries(registry_version, registry_fingerprint),
  FOREIGN KEY (registry_version, metric_id)
    REFERENCES analytics_metric_definitions(registry_version, metric_id)
);

CREATE FUNCTION require_cohort_analysis_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  metric_platform text;
  metric_kind text;
  metric_unit text;
  source_count integer;
BEGIN
  SELECT platform, metric_kind, metric_unit
    INTO metric_platform, metric_kind, metric_unit
    FROM analytics_metric_definitions
   WHERE registry_version = NEW.registry_version AND metric_id = NEW.metric_id
   FOR SHARE;

  IF metric_kind IS DISTINCT FROM 'RAW'
     OR metric_unit NOT IN ('COUNT','SECONDS','MINUTES','MILLISECONDS')
     OR NEW.report_data->>'request_fingerprint' IS DISTINCT FROM NEW.request_fingerprint
     OR NEW.report_data->>'interpretation' IS DISTINCT FROM 'DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL'
     OR NEW.report_data->>'status' NOT IN ('DESCRIPTIVE','INSUFFICIENT_COHORTS')
     OR jsonb_typeof(NEW.report_data->'candidate_count') <> 'number'
     OR jsonb_typeof(NEW.report_data->'included_count') <> 'number'
     OR (NEW.report_data->>'candidate_count')::integer NOT BETWEEN 1 AND 10000
     OR (NEW.report_data->>'included_count')::integer NOT BETWEEN 0 AND
        (NEW.report_data->>'candidate_count')::integer
     OR jsonb_typeof(NEW.report_data->'source_fingerprints') <> 'array'
     OR jsonb_typeof(NEW.report_data->'cohorts') <> 'array'
     OR jsonb_typeof(NEW.report_data->'exclusions') <> 'array' THEN
    RAISE EXCEPTION 'cohort analysis report evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT count(*) INTO source_count
    FROM jsonb_array_elements_text(NEW.report_data->'source_fingerprints');

  IF source_count <> (
       SELECT count(DISTINCT value)
       FROM jsonb_array_elements_text(NEW.report_data->'source_fingerprints') AS source(value)
     )
     OR source_count <> 2 * (NEW.report_data->>'included_count')::integer
     OR EXISTS (
       SELECT 1
       FROM jsonb_array_elements_text(NEW.report_data->'source_fingerprints') AS source(value)
       WHERE value !~ '^[0-9a-f]{64}$'
          OR NOT EXISTS (
            SELECT 1 FROM creative_metadata_snapshots AS metadata
             WHERE metadata.snapshot_fingerprint = value
               AND metadata.owner_user_id = NEW.owner_user_id
            UNION ALL
            SELECT 1 FROM analytics_metric_observations AS observation
             WHERE observation.observation_fingerprint = value
               AND observation.owner_user_id = NEW.owner_user_id
               AND observation.platform = metric_platform
               AND observation.window_name = NEW.window_name
               AND observation.registry_version = NEW.registry_version
               AND observation.registry_fingerprint = NEW.registry_fingerprint
          )
     ) THEN
    RAISE EXCEPTION 'cohort analysis source lineage is invalid'
      USING ERRCODE = 'check_violation';
  END IF;

  NEW.storage_fingerprint := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.owner_user_id, NEW.request_fingerprint,
    NEW.definition_version, NEW.factor, NEW.metric_id, NEW.window_name,
    NEW.registry_version, NEW.registry_fingerprint,
    NEW.minimum_group_size::text, NEW.bands::text, NEW.report_data::text,
    NEW.report_fingerprint
  ), 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER cohort_analysis_reports_require_evidence
  BEFORE INSERT ON cohort_analysis_reports
  FOR EACH ROW EXECUTE FUNCTION require_cohort_analysis_evidence();

CREATE FUNCTION guard_creative_cohort_evidence_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'creative cohort evidence is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER creative_metadata_snapshots_immutable
  BEFORE UPDATE OR DELETE ON creative_metadata_snapshots
  FOR EACH ROW EXECUTE FUNCTION guard_creative_cohort_evidence_immutable();

CREATE TRIGGER cohort_analysis_reports_immutable
  BEFORE UPDATE OR DELETE ON cohort_analysis_reports
  FOR EACH ROW EXECUTE FUNCTION guard_creative_cohort_evidence_immutable();
