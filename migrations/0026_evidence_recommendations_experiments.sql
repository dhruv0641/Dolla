-- Immutable descriptive recommendations and inert one-variable experiment proposals.

ALTER TABLE cohort_analysis_reports
  ADD CONSTRAINT cohort_analysis_request_report_identity
  UNIQUE (request_id, report_fingerprint);

CREATE TABLE analytics_recommendations (
  recommendation_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  report_request_id uuid NOT NULL,
  report_fingerprint char(64) NOT NULL,
  definition_version text NOT NULL CHECK (definition_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  factor text NOT NULL,
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  metric_id text NOT NULL,
  window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D')),
  registry_version text NOT NULL,
  registry_fingerprint char(64) NOT NULL CHECK (registry_fingerprint ~ '^[0-9a-f]{64}$'),
  minimum_group_size integer NOT NULL CHECK (minimum_group_size BETWEEN 3 AND 10000),
  control_label text NOT NULL CHECK (length(control_label) BETWEEN 1 AND 80),
  treatment_label text NOT NULL CHECK (length(treatment_label) BETWEEN 1 AND 80),
  recommendation_data jsonb NOT NULL CHECK (
    jsonb_typeof(recommendation_data) = 'object'
    AND pg_column_size(recommendation_data) <= 1048576
  ),
  recommendation_fingerprint char(64) NOT NULL UNIQUE CHECK (recommendation_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL UNIQUE CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  CHECK (control_label <> treatment_label),
  FOREIGN KEY (report_request_id, report_fingerprint)
    REFERENCES cohort_analysis_reports(request_id, report_fingerprint),
  FOREIGN KEY (registry_version, registry_fingerprint)
    REFERENCES analytics_metric_registries(registry_version, registry_fingerprint),
  FOREIGN KEY (registry_version, metric_id)
    REFERENCES analytics_metric_definitions(registry_version, metric_id)
);

CREATE FUNCTION require_evidence_backed_recommendation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  report_owner text; report_request_fingerprint char(64); report_status text;
  report_factor text; report_metric text; report_window text;
  report_registry_version text; report_registry_fingerprint char(64);
  report_minimum integer; report_created timestamptz; report_data jsonb;
  metric_platform text; eligible_count integer; expected_direction text;
  expected_request_fingerprint char(64); expected_recommendation_fingerprint char(64);
BEGIN
  SELECT r.owner_user_id, r.request_fingerprint, r.report_data->>'status', r.factor,
         r.metric_id, r.window_name, r.registry_version, r.registry_fingerprint,
         r.minimum_group_size, r.created_at, r.report_data, d.platform
    INTO report_owner, report_request_fingerprint, report_status, report_factor,
         report_metric, report_window, report_registry_version,
         report_registry_fingerprint, report_minimum, report_created,
         report_data, metric_platform
    FROM cohort_analysis_reports AS r
    JOIN analytics_metric_definitions AS d
      ON d.registry_version = r.registry_version AND d.metric_id = r.metric_id
   WHERE r.request_id = NEW.report_request_id
     AND r.report_fingerprint = NEW.report_fingerprint
   FOR SHARE OF r, d;

  SELECT count(*) FILTER (WHERE (value->>'eligible')::boolean)
    INTO eligible_count
    FROM jsonb_array_elements(report_data->'cohorts') AS item(value);

  SELECT CASE
    WHEN (treatment.value->>'median')::numeric > (control.value->>'median')::numeric
      THEN 'TREATMENT_MEDIAN_HIGHER'
    WHEN (treatment.value->>'median')::numeric < (control.value->>'median')::numeric
      THEN 'TREATMENT_MEDIAN_LOWER'
    ELSE 'MEDIANS_EQUAL' END
    INTO expected_direction
    FROM jsonb_array_elements(report_data->'cohorts') AS control(value),
         jsonb_array_elements(report_data->'cohorts') AS treatment(value)
   WHERE control.value->>'label' = NEW.control_label
     AND treatment.value->>'label' = NEW.treatment_label
     AND (control.value->>'eligible')::boolean
     AND (treatment.value->>'eligible')::boolean;

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.recommendation_id::text, NEW.owner_user_id, NEW.report_request_id::text,
    NEW.report_fingerprint, NEW.definition_version, NEW.control_label,
    NEW.treatment_label,
    to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_request_fingerprint;

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.recommendation_id::text, NEW.owner_user_id, NEW.request_fingerprint,
    NEW.report_request_id::text, report_request_fingerprint, NEW.report_fingerprint,
    NEW.definition_version, NEW.factor, NEW.platform, NEW.metric_id,
    NEW.window_name, NEW.registry_version, NEW.registry_fingerprint,
    NEW.minimum_group_size::text, NEW.control_label, NEW.treatment_label,
    NEW.recommendation_data->>'direction', NEW.recommendation_data->>'status',
    NEW.recommendation_data->>'interpretation',
    NEW.recommendation_data->>'candidate_count',
    NEW.recommendation_data->>'included_count',
    to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    coalesce((SELECT string_agg(concat_ws('|', value->>0, value->>1), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.recommendation_data->'exclusions') WITH ORDINALITY AS item(value, ordinal)), ''),
    coalesce((SELECT string_agg(concat_ws('|', value->>'label', value->>'sample_size',
      value->>'eligible', coalesce(value->>'median',''), coalesce(value->>'q1',''),
      coalesce(value->>'q3','')), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.recommendation_data->'disclosed_cohorts') WITH ORDINALITY AS item(value, ordinal)), ''),
    coalesce((SELECT string_agg(concat_ws('|', value->>'publication_id',
      value->>'metadata_snapshot_id', value->>'metadata_fingerprint',
      value->>'observation_request_id', value->>'observation_fingerprint'), '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.recommendation_data->'sources') WITH ORDINALITY AS item(value, ordinal)), '')
  ], '|'), 'sha256'), 'hex') INTO expected_recommendation_fingerprint;

  IF report_owner IS NULL OR report_status IS DISTINCT FROM 'DESCRIPTIVE'
     OR eligible_count < 2 OR expected_direction IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM report_owner
     OR NEW.factor IS DISTINCT FROM report_factor
     OR NEW.platform IS DISTINCT FROM metric_platform
     OR NEW.metric_id IS DISTINCT FROM report_metric
     OR NEW.window_name IS DISTINCT FROM report_window
     OR NEW.registry_version IS DISTINCT FROM report_registry_version
     OR NEW.registry_fingerprint IS DISTINCT FROM report_registry_fingerprint
     OR NEW.minimum_group_size IS DISTINCT FROM report_minimum
     OR NEW.created_at < report_created
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request_fingerprint
     OR NEW.recommendation_fingerprint IS DISTINCT FROM expected_recommendation_fingerprint
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.recommendation_data)) <> 25
     OR NEW.recommendation_data->>'recommendation_id' IS DISTINCT FROM NEW.recommendation_id::text
     OR NEW.recommendation_data->>'owner_user_id' IS DISTINCT FROM NEW.owner_user_id
     OR NEW.recommendation_data->>'request_fingerprint' IS DISTINCT FROM NEW.request_fingerprint
     OR NEW.recommendation_data->>'report_request_id' IS DISTINCT FROM NEW.report_request_id::text
     OR NEW.recommendation_data->>'report_request_fingerprint' IS DISTINCT FROM report_request_fingerprint
     OR NEW.recommendation_data->>'report_fingerprint' IS DISTINCT FROM NEW.report_fingerprint
     OR NEW.recommendation_data->>'definition_version' IS DISTINCT FROM NEW.definition_version
     OR NEW.recommendation_data->>'factor' IS DISTINCT FROM NEW.factor
     OR NEW.recommendation_data->>'platform' IS DISTINCT FROM NEW.platform
     OR NEW.recommendation_data->>'metric_id' IS DISTINCT FROM NEW.metric_id
     OR NEW.recommendation_data->>'window' IS DISTINCT FROM NEW.window_name
     OR NEW.recommendation_data->>'registry_version' IS DISTINCT FROM NEW.registry_version
     OR NEW.recommendation_data->>'registry_fingerprint' IS DISTINCT FROM NEW.registry_fingerprint
     OR (NEW.recommendation_data->>'minimum_group_size')::integer IS DISTINCT FROM NEW.minimum_group_size
     OR NEW.recommendation_data->'control' IS DISTINCT FROM (
       SELECT value FROM jsonb_array_elements(report_data->'cohorts') AS item(value)
        WHERE value->>'label' = NEW.control_label)
     OR NEW.recommendation_data->'treatment' IS DISTINCT FROM (
       SELECT value FROM jsonb_array_elements(report_data->'cohorts') AS item(value)
        WHERE value->>'label' = NEW.treatment_label)
     OR NEW.recommendation_data->'exclusions' IS DISTINCT FROM report_data->'exclusions'
     OR NEW.recommendation_data->'disclosed_cohorts' IS DISTINCT FROM report_data->'cohorts'
     OR NEW.recommendation_data->'sources' IS DISTINCT FROM report_data->'sources'
     OR NEW.recommendation_data->>'candidate_count' IS DISTINCT FROM report_data->>'candidate_count'
     OR NEW.recommendation_data->>'included_count' IS DISTINCT FROM report_data->>'included_count'
     OR NEW.recommendation_data->>'direction' IS DISTINCT FROM expected_direction
     OR NEW.recommendation_data->>'status' IS DISTINCT FROM 'HYPOTHESIS_ONLY'
     OR NEW.recommendation_data->>'interpretation' IS DISTINCT FROM
        'DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL_NO_GUARANTEED_WINNER'
     OR NEW.recommendation_data->>'created_at' IS DISTINCT FROM
        to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') THEN
    RAISE EXCEPTION 'recommendation is not exact descriptive evidence' USING ERRCODE = 'check_violation';
  END IF;
  NEW.storage_fingerprint := encode(digest(
    NEW.request_fingerprint || '|' || NEW.recommendation_fingerprint || '|' ||
    NEW.report_fingerprint || '|' || NEW.recommendation_data::text, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_recommendations_require_evidence
  BEFORE INSERT ON analytics_recommendations FOR EACH ROW
  EXECUTE FUNCTION require_evidence_backed_recommendation();

ALTER TABLE analytics_recommendations
  ADD CONSTRAINT analytics_recommendation_identity
  UNIQUE (recommendation_id, recommendation_fingerprint);

CREATE TABLE analytics_experiment_proposals (
  proposal_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  recommendation_id uuid NOT NULL,
  recommendation_fingerprint char(64) NOT NULL,
  definition_version text NOT NULL CHECK (definition_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  single_variable text NOT NULL,
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  metric_id text NOT NULL,
  window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D')),
  registry_version text NOT NULL,
  registry_fingerprint char(64) NOT NULL CHECK (registry_fingerprint ~ '^[0-9a-f]{64}$'),
  control_label text NOT NULL,
  treatment_label text NOT NULL,
  minimum_sample_per_arm integer NOT NULL CHECK (minimum_sample_per_arm BETWEEN 3 AND 10000),
  control_target_size integer NOT NULL CHECK (control_target_size BETWEEN 3 AND 10000),
  treatment_target_size integer NOT NULL CHECK (treatment_target_size BETWEEN 3 AND 10000),
  proposal_data jsonb NOT NULL CHECK (jsonb_typeof(proposal_data) = 'object' AND pg_column_size(proposal_data) <= 65536),
  proposal_fingerprint char(64) NOT NULL UNIQUE CHECK (proposal_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL UNIQUE CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  CHECK (control_label <> treatment_label),
  CHECK (control_target_size = treatment_target_size),
  CHECK (minimum_sample_per_arm <= control_target_size),
  FOREIGN KEY (recommendation_id, recommendation_fingerprint)
    REFERENCES analytics_recommendations(recommendation_id, recommendation_fingerprint),
  FOREIGN KEY (registry_version, registry_fingerprint)
    REFERENCES analytics_metric_registries(registry_version, registry_fingerprint),
  FOREIGN KEY (registry_version, metric_id)
    REFERENCES analytics_metric_definitions(registry_version, metric_id)
);

CREATE FUNCTION require_inert_experiment_proposal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  recommendation_owner text; recommendation_factor text;
  recommendation_platform text; recommendation_metric text;
  recommendation_window text; recommendation_registry_version text;
  recommendation_registry_fingerprint char(64); recommendation_control text;
  recommendation_treatment text; recommendation_created timestamptz;
  expected_request_fingerprint char(64); expected_proposal_fingerprint char(64);
BEGIN
  SELECT owner_user_id, factor, platform, metric_id, window_name,
         registry_version, registry_fingerprint, control_label, treatment_label,
         created_at
    INTO recommendation_owner, recommendation_factor, recommendation_platform,
         recommendation_metric, recommendation_window,
         recommendation_registry_version, recommendation_registry_fingerprint,
         recommendation_control, recommendation_treatment, recommendation_created
    FROM analytics_recommendations
   WHERE recommendation_id = NEW.recommendation_id
     AND recommendation_fingerprint = NEW.recommendation_fingerprint
   FOR SHARE;

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.proposal_id::text, NEW.owner_user_id, NEW.recommendation_id::text,
    NEW.recommendation_fingerprint, NEW.definition_version,
    NEW.minimum_sample_per_arm::text, NEW.control_target_size::text,
    to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_request_fingerprint;

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.proposal_id::text, NEW.owner_user_id, NEW.request_fingerprint,
    NEW.recommendation_id::text, NEW.recommendation_fingerprint,
    NEW.definition_version, NEW.single_variable, NEW.platform, NEW.metric_id,
    NEW.window_name, NEW.registry_version, NEW.registry_fingerprint,
    NEW.control_label, NEW.treatment_label, NEW.minimum_sample_per_arm::text,
    NEW.control_target_size::text, NEW.treatment_target_size::text,
    NEW.proposal_data->>'allocation', NEW.proposal_data->>'stop_rule',
    coalesce((SELECT string_agg(value #>> '{}', '|' ORDER BY ordinal)
      FROM jsonb_array_elements(NEW.proposal_data->'safety_rules') WITH ORDINALITY AS item(value, ordinal)), ''),
    NEW.proposal_data->>'status',
    to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_proposal_fingerprint;

  IF recommendation_owner IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM recommendation_owner
     OR NEW.single_variable IS DISTINCT FROM recommendation_factor
     OR NEW.platform IS DISTINCT FROM recommendation_platform
     OR NEW.metric_id IS DISTINCT FROM recommendation_metric
     OR NEW.window_name IS DISTINCT FROM recommendation_window
     OR NEW.registry_version IS DISTINCT FROM recommendation_registry_version
     OR NEW.registry_fingerprint IS DISTINCT FROM recommendation_registry_fingerprint
     OR NEW.control_label IS DISTINCT FROM recommendation_control
     OR NEW.treatment_label IS DISTINCT FROM recommendation_treatment
     OR NEW.created_at < recommendation_created
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request_fingerprint
     OR NEW.proposal_fingerprint IS DISTINCT FROM expected_proposal_fingerprint
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.proposal_data)) <> 30
     OR NEW.proposal_data->>'proposal_id' IS DISTINCT FROM NEW.proposal_id::text
     OR NEW.proposal_data->>'owner_user_id' IS DISTINCT FROM NEW.owner_user_id
     OR NEW.proposal_data->>'request_fingerprint' IS DISTINCT FROM NEW.request_fingerprint
     OR NEW.proposal_data->>'recommendation_id' IS DISTINCT FROM NEW.recommendation_id::text
     OR NEW.proposal_data->>'recommendation_fingerprint' IS DISTINCT FROM NEW.recommendation_fingerprint
     OR NEW.proposal_data->>'definition_version' IS DISTINCT FROM NEW.definition_version
     OR NEW.proposal_data->>'single_variable' IS DISTINCT FROM NEW.single_variable
     OR NEW.proposal_data->>'platform' IS DISTINCT FROM NEW.platform
     OR NEW.proposal_data->>'metric_id' IS DISTINCT FROM NEW.metric_id
     OR NEW.proposal_data->>'window' IS DISTINCT FROM NEW.window_name
     OR NEW.proposal_data->>'registry_version' IS DISTINCT FROM NEW.registry_version
     OR NEW.proposal_data->>'registry_fingerprint' IS DISTINCT FROM NEW.registry_fingerprint
     OR NEW.proposal_data->>'control_label' IS DISTINCT FROM NEW.control_label
     OR NEW.proposal_data->>'treatment_label' IS DISTINCT FROM NEW.treatment_label
     OR (NEW.proposal_data->>'minimum_sample_per_arm')::integer IS DISTINCT FROM NEW.minimum_sample_per_arm
     OR (NEW.proposal_data->>'control_target_size')::integer IS DISTINCT FROM NEW.control_target_size
     OR (NEW.proposal_data->>'treatment_target_size')::integer IS DISTINCT FROM NEW.treatment_target_size
     OR NEW.proposal_data->>'allocation' IS DISTINCT FROM 'BALANCED_FIXED_1_TO_1'
     OR NEW.proposal_data->>'stop_rule' IS DISTINCT FROM 'FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP'
     OR NEW.proposal_data->'safety_rules' IS DISTINCT FROM
        '["PAUSE_ON_POLICY_OR_SAFETY_SIGNAL","PAUSE_ON_UNKNOWN_AUTH_JOB_OR_SPEND_STATE"]'::jsonb
     OR NEW.proposal_data->>'status' IS DISTINCT FROM 'DRAFT_REQUIRES_HUMAN_APPROVAL'
     OR NEW.proposal_data->'human_approval_required' IS DISTINCT FROM 'true'::jsonb
     OR NEW.proposal_data->'execution_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->'generation_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->'spend_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->'account_connection_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->'scheduling_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->'upload_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->'publishing_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.proposal_data->>'created_at' IS DISTINCT FROM
        to_char(NEW.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') THEN
    RAISE EXCEPTION 'experiment proposal is not inert exact evidence' USING ERRCODE = 'check_violation';
  END IF;
  NEW.storage_fingerprint := encode(digest(
    NEW.request_fingerprint || '|' || NEW.proposal_fingerprint || '|' ||
    NEW.recommendation_fingerprint || '|' || NEW.proposal_data::text, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_experiment_proposals_require_evidence
  BEFORE INSERT ON analytics_experiment_proposals FOR EACH ROW
  EXECUTE FUNCTION require_inert_experiment_proposal();

CREATE FUNCTION guard_recommendation_experiment_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'recommendation and experiment evidence is immutable' USING ERRCODE = 'check_violation';
END; $$;

CREATE TRIGGER analytics_recommendations_immutable
  BEFORE UPDATE OR DELETE ON analytics_recommendations FOR EACH ROW
  EXECUTE FUNCTION guard_recommendation_experiment_immutable();
CREATE TRIGGER analytics_experiment_proposals_immutable
  BEFORE UPDATE OR DELETE ON analytics_experiment_proposals FOR EACH ROW
  EXECUTE FUNCTION guard_recommendation_experiment_immutable();

COMMENT ON TABLE content_recommendations IS
  'Legacy unverified table; do not use for TASK-065 evidence or experiment proposals.';
