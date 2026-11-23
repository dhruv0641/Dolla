-- Immutable authoritative creative factors and typed, non-causal cohort evidence.

CREATE FUNCTION creative_metadata_source_fingerprint(
  source_publication_id uuid, source_storyboard_version integer
) RETURNS char(64)
LANGUAGE sql STABLE AS $$
  SELECT encode(digest(concat_ws('|',
    p.id::text, b.owner_user_id, b.id::text, c.id::text,
    p.artifact_version::text, c.script_version::text,
    source_storyboard_version::text, ch.platform,
    to_char(p.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    b.niche, c.language, c.script::text, sv.timeline_json::text,
    COALESCE((
      SELECT string_agg(DISTINCT vp.id::text || ':' || vp.voice_key, ',' ORDER BY vp.id::text || ':' || vp.voice_key)
      FROM tts_synthesis_requests AS tts
      JOIN voice_profiles AS vp ON vp.id = tts.profile_id AND vp.brand_id = tts.brand_id
      WHERE tts.content_id = c.id AND tts.status = 'COMPLETED'
        AND tts.asset_id::text IN (SELECT jsonb_array_elements_text(rj.inputs_manifest->'asset_ids'))
    ), ''),
    COALESCE((
      SELECT string_agg(g.id::text || ':' || r.model_name || ':' || r.quoted_credits::text, ',' ORDER BY g.id::text)
      FROM assets AS asset
      JOIN generation_jobs AS g ON g.id = asset.source_job_id
      JOIN flow_credit_reservations AS r ON r.id = g.credit_reservation_id
      WHERE asset.content_id = c.id
        AND asset.id::text IN (SELECT jsonb_array_elements_text(rj.inputs_manifest->'asset_ids'))
    ), '')
  ), 'sha256'), 'hex')::char(64)
  FROM publication_jobs AS p
  JOIN content_items AS c ON c.id = p.content_id
  JOIN brands AS b ON b.id = c.brand_id
  JOIN social_channels AS ch ON ch.id = p.channel_id AND ch.brand_id = b.id
  JOIN storyboard_versions AS sv
    ON sv.content_id = c.id AND sv.version = source_storyboard_version
  JOIN render_jobs AS rj
    ON rj.content_id = c.id AND rj.render_version = p.artifact_version AND rj.status = 'DONE'
  JOIN render_job_artifacts AS rja
    ON rja.render_job_id = rj.id AND rja.asset_id = p.asset_id AND rja.artifact_role = 'FINAL_VIDEO'
  WHERE p.id = source_publication_id
    AND p.status = 'PUBLISHED' AND p.published_at IS NOT NULL;
$$;

CREATE TABLE creative_metadata_snapshots (
  snapshot_id uuid PRIMARY KEY,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  brand_id uuid NOT NULL REFERENCES brands(id),
  content_id uuid NOT NULL REFERENCES content_items(id),
  artifact_version integer NOT NULL CHECK (artifact_version > 0),
  script_version integer NOT NULL CHECK (script_version > 0),
  storyboard_version integer NOT NULL CHECK (storyboard_version > 0),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  published_at timestamptz NOT NULL,
  schema_version text NOT NULL CHECK (schema_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  source_fingerprint char(64) NOT NULL CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
  factors jsonb NOT NULL CHECK (
    jsonb_typeof(factors) = 'array' AND jsonb_array_length(factors) = 13
    AND pg_column_size(factors) <= 65536
  ),
  snapshot_fingerprint char(64) NOT NULL UNIQUE CHECK (snapshot_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL UNIQUE CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  UNIQUE (publication_id, schema_version)
);

CREATE FUNCTION require_creative_metadata_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text; current_brand uuid; current_content uuid;
  current_artifact integer; current_script_version integer; current_storyboard integer;
  current_platform text; current_published_at timestamptz; current_niche text;
  current_language text; current_script jsonb; current_duration_ms integer;
  current_scene_count integer; voice_count integer; current_voice text;
  model_count integer; current_model text; current_cost bigint; render_inputs jsonb;
  expected_source_fingerprint char(64); expected_snapshot_fingerprint char(64);
BEGIN
  SELECT b.owner_user_id, b.id, c.id, p.artifact_version, c.script_version,
         c.storyboard_version, ch.platform, p.published_at, b.niche, c.language,
         c.script, sv.total_duration_ms, rj.inputs_manifest,
         (SELECT count(*) FROM scenes AS s WHERE s.content_id = c.id AND s.storyboard_version = NEW.storyboard_version),
         creative_metadata_source_fingerprint(p.id, NEW.storyboard_version)
    INTO current_owner, current_brand, current_content, current_artifact,
         current_script_version, current_storyboard, current_platform,
         current_published_at, current_niche, current_language, current_script,
         current_duration_ms, render_inputs, current_scene_count, expected_source_fingerprint
    FROM publication_jobs AS p
    JOIN content_items AS c ON c.id = p.content_id
    JOIN brands AS b ON b.id = c.brand_id
    JOIN social_channels AS ch ON ch.id = p.channel_id AND ch.brand_id = b.id
    JOIN storyboard_versions AS sv ON sv.content_id = c.id AND sv.version = NEW.storyboard_version
    JOIN render_jobs AS rj
      ON rj.content_id = c.id AND rj.render_version = p.artifact_version AND rj.status = 'DONE'
    JOIN render_job_artifacts AS rja
      ON rja.render_job_id = rj.id AND rja.asset_id = p.asset_id AND rja.artifact_role = 'FINAL_VIDEO'
   WHERE p.id = NEW.publication_id AND p.status = 'PUBLISHED' AND p.published_at IS NOT NULL
   FOR SHARE OF p, c, b, ch, sv, rj, rja;

  SELECT count(DISTINCT vp.voice_key), min(vp.voice_key)
    INTO voice_count, current_voice
    FROM tts_synthesis_requests AS tts
    JOIN voice_profiles AS vp ON vp.id = tts.profile_id AND vp.brand_id = tts.brand_id
   WHERE tts.content_id = NEW.content_id AND tts.status = 'COMPLETED'
     AND tts.asset_id::text IN (SELECT jsonb_array_elements_text(render_inputs->'asset_ids'));

  SELECT count(DISTINCT r.model_name), min(r.model_name), sum(r.quoted_credits)
    INTO model_count, current_model, current_cost
    FROM assets AS asset
    JOIN generation_jobs AS g ON g.id = asset.source_job_id
    JOIN flow_credit_reservations AS r ON r.id = g.credit_reservation_id
   WHERE asset.content_id = NEW.content_id
     AND asset.id::text IN (SELECT jsonb_array_elements_text(render_inputs->'asset_ids'));

  IF current_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.brand_id IS DISTINCT FROM current_brand
     OR NEW.content_id IS DISTINCT FROM current_content
     OR NEW.artifact_version IS DISTINCT FROM current_artifact
     OR NEW.script_version IS DISTINCT FROM current_script_version
     OR NEW.storyboard_version IS DISTINCT FROM current_storyboard
     OR NEW.platform IS DISTINCT FROM current_platform
     OR NEW.published_at IS DISTINCT FROM current_published_at
     OR NEW.source_fingerprint IS DISTINCT FROM expected_source_fingerprint
     OR NEW.created_at < current_published_at
     OR (SELECT count(*) FROM jsonb_array_elements(NEW.factors)) <> 13
     OR (SELECT count(DISTINCT value->>'factor') FROM jsonb_array_elements(NEW.factors)) <> 13
     OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(NEW.factors) AS item(value)
       WHERE jsonb_typeof(value) <> 'object'
          OR (SELECT count(*) FROM jsonb_object_keys(value)) <> 5
          OR value->>'factor' NOT IN (
            'NICHE','HOOK_TYPE','SCRIPT_WORD_COUNT','CTA_TYPE','SCENE_COUNT','DURATION_SECONDS',
            'NARRATOR_VOICE','POSTING_TIME_UTC','PLATFORM','LANGUAGE','VISUAL_MOTIF','FLOW_MODEL','FLOW_COST_MICROCREDITS'
          )
          OR value->>'availability' NOT IN ('OBSERVED','UNAVAILABLE','NOT_APPLICABLE')
          OR NOT (value ? 'value' AND value ? 'evidence_ref' AND value ? 'unavailable_reason')
          OR CASE value->>'availability'
               WHEN 'OBSERVED' THEN jsonb_typeof(value->'value') <> 'string'
                 OR value->>'value' = '' OR length(value->>'value') > 200
                 OR jsonb_typeof(value->'evidence_ref') <> 'string'
                 OR value->>'evidence_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'
                 OR jsonb_typeof(value->'unavailable_reason') <> 'null'
               WHEN 'UNAVAILABLE' THEN jsonb_typeof(value->'value') <> 'null'
                 OR jsonb_typeof(value->'evidence_ref') <> 'null'
                 OR value->>'unavailable_reason' NOT IN ('NOT_CAPTURED','SOURCE_UNAVAILABLE','SOURCE_AMBIGUOUS')
               WHEN 'NOT_APPLICABLE' THEN jsonb_typeof(value->'value') <> 'null'
                 OR jsonb_typeof(value->'evidence_ref') <> 'null'
                 OR jsonb_typeof(value->'unavailable_reason') <> 'null'
               ELSE true END
     )
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','PLATFORM','availability','OBSERVED','value',current_platform,
       'evidence_ref','publication:platform:v1','unavailable_reason',NULL))
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','POSTING_TIME_UTC','availability','OBSERVED',
       'value','D' || extract(isodow FROM current_published_at AT TIME ZONE 'UTC')::integer::text ||
               '-H' || to_char(current_published_at AT TIME ZONE 'UTC','HH24') || 'Z',
       'evidence_ref','publication:published-at:utc-weekday-hour-v1','unavailable_reason',NULL))
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','LANGUAGE','availability','OBSERVED','value',current_language,
       'evidence_ref','content:language:v1','unavailable_reason',NULL))
     OR NOT NEW.factors @> jsonb_build_array(CASE WHEN coalesce(trim(current_script->>'narration'),'') <> '' THEN jsonb_build_object(
       'factor','SCRIPT_WORD_COUNT','availability','OBSERVED',
       'value',cardinality(regexp_split_to_array(trim(current_script->>'narration'), E'\\s+'))::text,
       'evidence_ref','content:script:narration:v1','unavailable_reason',NULL)
       ELSE jsonb_build_object('factor','SCRIPT_WORD_COUNT','availability','UNAVAILABLE','value',NULL,
         'evidence_ref',NULL,'unavailable_reason','NOT_CAPTURED') END)
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','SCENE_COUNT','availability','OBSERVED','value',current_scene_count::text,
       'evidence_ref','storyboard:scenes:v1','unavailable_reason',NULL))
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','DURATION_SECONDS','availability','OBSERVED',
       'value',trim(trailing '.' FROM trim(trailing '0' FROM (current_duration_ms::numeric / 1000)::text)),
       'evidence_ref','storyboard:duration:v1','unavailable_reason',NULL))
     OR NOT NEW.factors @> jsonb_build_array(CASE WHEN coalesce(current_niche,'') <> '' THEN jsonb_build_object(
         'factor','NICHE','availability','OBSERVED','value',current_niche,'evidence_ref','brand:niche:v1','unavailable_reason',NULL)
       ELSE jsonb_build_object('factor','NICHE','availability','UNAVAILABLE','value',NULL,'evidence_ref',NULL,'unavailable_reason','NOT_CAPTURED') END)
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','HOOK_TYPE','availability','UNAVAILABLE','value',NULL,
       'evidence_ref',NULL,'unavailable_reason','NOT_CAPTURED'))
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','CTA_TYPE','availability','UNAVAILABLE','value',NULL,
       'evidence_ref',NULL,'unavailable_reason','NOT_CAPTURED'))
     OR NOT NEW.factors @> jsonb_build_array(CASE WHEN voice_count = 1 THEN jsonb_build_object(
         'factor','NARRATOR_VOICE','availability','OBSERVED','value',current_voice,'evidence_ref','tts:voice-profile:v1','unavailable_reason',NULL)
       ELSE jsonb_build_object('factor','NARRATOR_VOICE','availability','UNAVAILABLE','value',NULL,'evidence_ref',NULL,
         'unavailable_reason',CASE WHEN voice_count > 1 THEN 'SOURCE_AMBIGUOUS' ELSE 'NOT_CAPTURED' END) END)
     OR NOT NEW.factors @> jsonb_build_array(jsonb_build_object(
       'factor','VISUAL_MOTIF','availability','UNAVAILABLE','value',NULL,'evidence_ref',NULL,'unavailable_reason','NOT_CAPTURED'))
     OR NOT NEW.factors @> jsonb_build_array(CASE WHEN model_count = 1 THEN jsonb_build_object(
         'factor','FLOW_MODEL','availability','OBSERVED','value',current_model,'evidence_ref','generation:selected-assets:model:v1','unavailable_reason',NULL)
       ELSE jsonb_build_object('factor','FLOW_MODEL','availability','UNAVAILABLE','value',NULL,'evidence_ref',NULL,
         'unavailable_reason',CASE WHEN model_count > 1 THEN 'SOURCE_AMBIGUOUS' ELSE 'NOT_CAPTURED' END) END)
     OR NOT NEW.factors @> jsonb_build_array(CASE WHEN current_cost IS NOT NULL THEN jsonb_build_object(
         'factor','FLOW_COST_MICROCREDITS','availability','OBSERVED','value',current_cost::text,
         'evidence_ref','generation:selected-assets:quoted-credits:v1','unavailable_reason',NULL)
       ELSE jsonb_build_object('factor','FLOW_COST_MICROCREDITS','availability','UNAVAILABLE','value',NULL,
         'evidence_ref',NULL,'unavailable_reason','NOT_CAPTURED') END) THEN
    RAISE EXCEPTION 'creative metadata snapshot evidence is invalid' USING ERRCODE = 'check_violation';
  END IF;

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.snapshot_id::text, NEW.owner_user_id, NEW.brand_id::text, NEW.content_id::text,
    NEW.publication_id::text, NEW.artifact_version::text, NEW.script_version::text,
    NEW.storyboard_version::text, NEW.platform,
    to_char(NEW.published_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    NEW.schema_version, NEW.source_fingerprint,
    to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    (SELECT string_agg(concat_ws('|', value->>'factor', value->>'availability',
       coalesce(value->>'value',''), coalesce(value->>'evidence_ref',''),
       coalesce(value->>'unavailable_reason','')), '|' ORDER BY value->>'factor')
       FROM jsonb_array_elements(NEW.factors) AS item(value))
  ], '|'), 'sha256'), 'hex') INTO expected_snapshot_fingerprint;
  IF NEW.snapshot_fingerprint IS DISTINCT FROM expected_snapshot_fingerprint THEN
    RAISE EXCEPTION 'creative metadata snapshot fingerprint is invalid' USING ERRCODE = 'check_violation';
  END IF;
  NEW.storage_fingerprint := encode(digest(NEW.snapshot_fingerprint || '|' || NEW.source_fingerprint, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER creative_metadata_snapshots_require_evidence
  BEFORE INSERT ON creative_metadata_snapshots FOR EACH ROW EXECUTE FUNCTION require_creative_metadata_evidence();

CREATE TABLE cohort_analysis_reports (
  request_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  definition_version text NOT NULL CHECK (definition_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  factor text NOT NULL CHECK (factor IN (
    'NICHE','HOOK_TYPE','SCRIPT_WORD_COUNT','CTA_TYPE','SCENE_COUNT','DURATION_SECONDS',
    'NARRATOR_VOICE','POSTING_TIME_UTC','LANGUAGE','VISUAL_MOTIF','FLOW_MODEL','FLOW_COST_MICROCREDITS'
  )),
  metric_id text NOT NULL,
  window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D')),
  registry_version text NOT NULL,
  registry_fingerprint char(64) NOT NULL,
  minimum_group_size integer NOT NULL CHECK (minimum_group_size BETWEEN 3 AND 10000),
  bands jsonb NOT NULL CHECK (jsonb_typeof(bands) = 'array' AND jsonb_array_length(bands) <= 20 AND pg_column_size(bands) <= 32768),
  report_data jsonb NOT NULL CHECK (jsonb_typeof(report_data) = 'object' AND pg_column_size(report_data) <= 1048576),
  report_fingerprint char(64) NOT NULL UNIQUE CHECK (report_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL UNIQUE CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (registry_version, registry_fingerprint) REFERENCES analytics_metric_registries(registry_version, registry_fingerprint),
  FOREIGN KEY (registry_version, metric_id) REFERENCES analytics_metric_definitions(registry_version, metric_id)
);

CREATE TABLE cohort_analysis_sources (
  request_id uuid NOT NULL REFERENCES cohort_analysis_reports(request_id) ON DELETE RESTRICT,
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  metadata_snapshot_id uuid NOT NULL REFERENCES creative_metadata_snapshots(snapshot_id),
  metadata_fingerprint char(64) NOT NULL,
  observation_request_id uuid NOT NULL REFERENCES analytics_metric_observations(request_id),
  observation_fingerprint char(64) NOT NULL,
  PRIMARY KEY (request_id, publication_id),
  UNIQUE (request_id, metadata_snapshot_id), UNIQUE (request_id, observation_request_id)
);

CREATE FUNCTION require_cohort_analysis_report() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE metric_kind text; metric_unit text; exclusion_total integer; cohort_total integer; eligible_count integer;
  expected_request_fingerprint char(64); expected_report_fingerprint char(64);
BEGIN
  SELECT d.metric_kind, d.metric_unit INTO metric_kind, metric_unit
    FROM analytics_metric_definitions AS d
   WHERE d.registry_version = NEW.registry_version AND d.metric_id = NEW.metric_id FOR SHARE;
  SELECT coalesce(sum((value->>1)::integer),0) INTO exclusion_total
    FROM jsonb_array_elements(NEW.report_data->'exclusions') AS item(value);
  SELECT coalesce(sum((value->>'sample_size')::integer),0), count(*) FILTER (WHERE (value->>'eligible')::boolean)
    INTO cohort_total, eligible_count FROM jsonb_array_elements(NEW.report_data->'cohorts') AS item(value);
  SELECT encode(digest(array_to_string(ARRAY[
    NEW.request_id::text, NEW.owner_user_id, NEW.definition_version, NEW.factor,
    NEW.metric_id, NEW.window_name, NEW.registry_version, NEW.registry_fingerprint,
    NEW.minimum_group_size::text,
    coalesce((SELECT string_agg(concat_ws('|', value->>'label', value->>'lower', value->>'upper'), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.bands) WITH ORDINALITY AS item(value, ordinal)), '')
  ], '|'), 'sha256'), 'hex') INTO expected_request_fingerprint;
  SELECT encode(digest(array_to_string(ARRAY[
    NEW.request_fingerprint, NEW.report_data->>'status', NEW.report_data->>'interpretation',
    NEW.report_data->>'candidate_count', NEW.report_data->>'included_count',
    coalesce((SELECT string_agg(concat_ws('|', value->>0, value->>1), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.report_data->'exclusions') WITH ORDINALITY AS item(value, ordinal)), ''),
    coalesce((SELECT string_agg(concat_ws('|', value->>'label', value->>'sample_size',
      value->>'eligible', coalesce(value->>'median',''), coalesce(value->>'q1',''),
      coalesce(value->>'q3','')), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.report_data->'cohorts') WITH ORDINALITY AS item(value, ordinal)), ''),
    coalesce((SELECT string_agg(concat_ws('|', value->>'publication_id',
      value->>'metadata_snapshot_id', value->>'metadata_fingerprint',
      value->>'observation_request_id', value->>'observation_fingerprint'), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.report_data->'sources') WITH ORDINALITY AS item(value, ordinal)), '')
  ], '|'), 'sha256'), 'hex') INTO expected_report_fingerprint;
  IF metric_kind IS DISTINCT FROM 'RAW' OR metric_unit NOT IN ('COUNT','SECONDS','MINUTES','MILLISECONDS')
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request_fingerprint
     OR NEW.report_fingerprint IS DISTINCT FROM expected_report_fingerprint
     OR NEW.report_data->>'request_fingerprint' IS DISTINCT FROM NEW.request_fingerprint
     OR NEW.report_data->>'interpretation' IS DISTINCT FROM 'DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL'
     OR NEW.report_data->>'status' NOT IN ('DESCRIPTIVE','INSUFFICIENT_COHORTS')
     OR jsonb_typeof(NEW.report_data->'candidate_count') <> 'number'
     OR jsonb_typeof(NEW.report_data->'included_count') <> 'number'
     OR jsonb_typeof(NEW.report_data->'sources') <> 'array'
     OR jsonb_typeof(NEW.report_data->'cohorts') <> 'array'
     OR jsonb_typeof(NEW.report_data->'exclusions') <> 'array'
     OR jsonb_array_length(NEW.report_data->'exclusions') <> 5
     OR (SELECT count(DISTINCT value->>0)
           FROM jsonb_array_elements(NEW.report_data->'exclusions') AS item(value)) <> 5
     OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(NEW.report_data->'exclusions') AS item(value)
       WHERE jsonb_typeof(value) <> 'array' OR jsonb_array_length(value) <> 2
          OR value->>0 NOT IN ('METADATA_UNAVAILABLE','SNAPSHOT_UNAVAILABLE','FACTOR_UNAVAILABLE','METRIC_UNAVAILABLE','OUTSIDE_BANDS')
          OR jsonb_typeof(value->1) <> 'number' OR (value->>1)::integer < 0
     )
     OR (NEW.report_data->>'candidate_count')::integer NOT BETWEEN 1 AND 10000
     OR (NEW.report_data->>'included_count')::integer <> cohort_total
     OR (NEW.report_data->>'candidate_count')::integer <> cohort_total + exclusion_total
     OR jsonb_array_length(NEW.report_data->'sources') <> cohort_total
     OR ((NEW.report_data->>'status' = 'DESCRIPTIVE') IS DISTINCT FROM (eligible_count >= 2))
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.report_data->'cohorts') AS item(value)
       WHERE (value->>'sample_size')::integer < 1
          OR ((value->>'eligible')::boolean IS DISTINCT FROM ((value->>'sample_size')::integer >= NEW.minimum_group_size))) THEN
    RAISE EXCEPTION 'cohort analysis report evidence is invalid' USING ERRCODE = 'check_violation';
  END IF;
  NEW.storage_fingerprint := encode(digest(NEW.request_fingerprint || '|' || NEW.report_fingerprint || '|' || NEW.report_data::text, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;
CREATE TRIGGER cohort_analysis_reports_require_evidence
  BEFORE INSERT ON cohort_analysis_reports FOR EACH ROW EXECUTE FUNCTION require_cohort_analysis_report();

CREATE FUNCTION require_cohort_analysis_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_owner text; source_platform text; metric_platform text;
BEGIN
  SELECT r.owner_user_id, o.platform, d.platform
    INTO source_owner, source_platform, metric_platform
    FROM cohort_analysis_reports AS r
    JOIN analytics_metric_observations AS o ON o.request_id = NEW.observation_request_id
    JOIN analytics_metric_definitions AS d ON d.registry_version = r.registry_version AND d.metric_id = r.metric_id
   WHERE r.request_id = NEW.request_id AND o.publication_id = NEW.publication_id
     AND o.owner_user_id = r.owner_user_id AND o.observation_fingerprint = NEW.observation_fingerprint
     AND o.window_name = r.window_name AND o.registry_version = r.registry_version
     AND o.registry_fingerprint = r.registry_fingerprint FOR SHARE OF r, o, d;
  IF source_owner IS NULL OR source_platform IS DISTINCT FROM metric_platform
     OR NOT EXISTS (SELECT 1 FROM creative_metadata_snapshots AS m
       WHERE m.snapshot_id = NEW.metadata_snapshot_id AND m.publication_id = NEW.publication_id
         AND m.owner_user_id = source_owner AND m.platform = source_platform
         AND m.snapshot_fingerprint = NEW.metadata_fingerprint) THEN
    RAISE EXCEPTION 'cohort analysis source lineage is invalid' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER cohort_analysis_sources_require_evidence
  BEFORE INSERT ON cohort_analysis_sources FOR EACH ROW EXECUTE FUNCTION require_cohort_analysis_source();

CREATE FUNCTION cohort_numeric_median(values_numeric numeric[]) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE item_count integer := cardinality(values_numeric);
BEGIN
  IF item_count < 1 THEN RETURN NULL; END IF;
  IF item_count % 2 = 1 THEN RETURN values_numeric[(item_count + 1) / 2]; END IF;
  RETURN (values_numeric[item_count / 2] + values_numeric[item_count / 2 + 1]) / 2;
END;
$$;

CREATE FUNCTION validate_complete_cohort_analysis() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE active_request uuid; expected_sources jsonb; actual_sources jsonb; invalid_summary boolean;
BEGIN
  active_request := CASE WHEN TG_OP = 'DELETE' THEN OLD.request_id ELSE NEW.request_id END;
  SELECT report_data->'sources' INTO expected_sources FROM cohort_analysis_reports WHERE request_id = active_request;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
    'publication_id', publication_id::text, 'metadata_snapshot_id', metadata_snapshot_id::text,
    'metadata_fingerprint', metadata_fingerprint, 'observation_request_id', observation_request_id::text,
    'observation_fingerprint', observation_fingerprint) ORDER BY publication_id::text), '[]'::jsonb)
    INTO actual_sources FROM cohort_analysis_sources WHERE request_id = active_request;
  IF expected_sources IS DISTINCT FROM actual_sources THEN
    RAISE EXCEPTION 'cohort analysis typed sources are incomplete' USING ERRCODE = 'check_violation';
  END IF;
  WITH samples AS (
    SELECT CASE WHEN jsonb_array_length(r.bands) = 0 THEN factor_item.value->>'value'
           ELSE (SELECT band.value->>'label' FROM jsonb_array_elements(r.bands) AS band(value)
                 WHERE (factor_item.value->>'value')::numeric >= (band.value->>'lower')::numeric
                   AND (factor_item.value->>'value')::numeric < (band.value->>'upper')::numeric
                 LIMIT 1) END AS label,
           (metric_item.value->>'value')::numeric AS metric_value
    FROM cohort_analysis_reports AS r
    JOIN cohort_analysis_sources AS source ON source.request_id = r.request_id
    JOIN creative_metadata_snapshots AS metadata ON metadata.snapshot_id = source.metadata_snapshot_id
    JOIN analytics_metric_observations AS observation ON observation.request_id = source.observation_request_id
    CROSS JOIN LATERAL jsonb_array_elements(metadata.factors) AS factor_item(value)
    CROSS JOIN LATERAL jsonb_array_elements(observation.metric_data) AS metric_item(value)
    WHERE r.request_id = active_request
      AND factor_item.value->>'factor' = r.factor
      AND factor_item.value->>'availability' = 'OBSERVED'
      AND metric_item.value->>'metric_id' = r.metric_id
      AND metric_item.value->>'availability' = 'AVAILABLE'
      AND jsonb_typeof(metric_item.value->'value') = 'number'
  ), grouped AS (
    SELECT label, count(*)::integer AS sample_size,
           array_agg(metric_value ORDER BY metric_value) AS values_numeric
    FROM samples GROUP BY label
  ), report_groups AS (
    SELECT value FROM cohort_analysis_reports AS r,
         LATERAL jsonb_array_elements(r.report_data->'cohorts') AS item(value)
    WHERE r.request_id = active_request
  )
  SELECT EXISTS (SELECT 1 FROM samples WHERE label IS NULL)
      OR (SELECT count(*) FROM grouped) <> (SELECT count(*) FROM report_groups)
      OR EXISTS (
        SELECT 1 FROM grouped AS g
        LEFT JOIN report_groups AS rg ON rg.value->>'label' = g.label
        JOIN cohort_analysis_reports AS r ON r.request_id = active_request
        WHERE rg.value IS NULL
           OR (rg.value->>'sample_size')::integer <> g.sample_size
           OR (rg.value->>'eligible')::boolean IS DISTINCT FROM (g.sample_size >= r.minimum_group_size)
           OR (g.sample_size >= r.minimum_group_size AND (
             (rg.value->>'median')::numeric IS DISTINCT FROM cohort_numeric_median(g.values_numeric)
             OR (rg.value->>'q1')::numeric IS DISTINCT FROM cohort_numeric_median(
                  g.values_numeric[1:cardinality(g.values_numeric) / 2])
             OR (rg.value->>'q3')::numeric IS DISTINCT FROM cohort_numeric_median(
                  g.values_numeric[cardinality(g.values_numeric) - cardinality(g.values_numeric) / 2 + 1:cardinality(g.values_numeric)])
           ))
           OR (g.sample_size < r.minimum_group_size AND (
             jsonb_typeof(rg.value->'median') <> 'null'
             OR jsonb_typeof(rg.value->'q1') <> 'null'
             OR jsonb_typeof(rg.value->'q3') <> 'null'
           ))
      ) INTO invalid_summary;
  IF invalid_summary THEN
    RAISE EXCEPTION 'cohort analysis summary does not match typed sources' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER cohort_analysis_reports_complete_sources
  AFTER INSERT ON cohort_analysis_reports DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION validate_complete_cohort_analysis();
CREATE CONSTRAINT TRIGGER cohort_analysis_sources_complete_report
  AFTER INSERT OR UPDATE OR DELETE ON cohort_analysis_sources DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION validate_complete_cohort_analysis();

CREATE FUNCTION guard_creative_cohort_evidence_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'creative cohort evidence is immutable' USING ERRCODE = 'check_violation';
END; $$;
CREATE TRIGGER creative_metadata_snapshots_immutable BEFORE UPDATE OR DELETE ON creative_metadata_snapshots
  FOR EACH ROW EXECUTE FUNCTION guard_creative_cohort_evidence_immutable();
CREATE TRIGGER cohort_analysis_reports_immutable BEFORE UPDATE OR DELETE ON cohort_analysis_reports
  FOR EACH ROW EXECUTE FUNCTION guard_creative_cohort_evidence_immutable();
CREATE TRIGGER cohort_analysis_sources_immutable BEFORE UPDATE OR DELETE ON cohort_analysis_sources
  FOR EACH ROW EXECUTE FUNCTION guard_creative_cohort_evidence_immutable();
