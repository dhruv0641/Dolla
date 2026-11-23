-- Exact-proposal approval/spend gates and immutable descriptive feedback outcomes.

ALTER TABLE flow_credit_reservations
  ADD CONSTRAINT flow_credit_reservation_exact_identity
  UNIQUE (id, flow_account_id, request_id);

CREATE TABLE analytics_feedback_approval_attestations (
  attestation_id uuid PRIMARY KEY,
  approval_kind text NOT NULL CHECK (approval_kind IN ('HUMAN_EXPERIMENT','SPEND')),
  approval_ref text NOT NULL CHECK (approval_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  proposal_id uuid NOT NULL,
  proposal_fingerprint char(64) NOT NULL,
  account_id uuid REFERENCES flow_accounts(id),
  maximum_credits integer CHECK (maximum_credits BETWEEN 1 AND 1000000000),
  operation text CHECK (operation IN ('video_generate')),
  verifier_ref text NOT NULL CHECK (verifier_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  verifier_version text NOT NULL CHECK (verifier_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  evidence_fingerprint char(64) NOT NULL UNIQUE CHECK (evidence_fingerprint ~ '^[0-9a-f]{64}$'),
  attestation_fingerprint char(64) NOT NULL UNIQUE CHECK (attestation_fingerprint ~ '^[0-9a-f]{64}$'),
  verified_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  CHECK (expires_at > verified_at),
  CHECK ((approval_kind = 'HUMAN_EXPERIMENT' AND account_id IS NULL AND maximum_credits IS NULL AND operation IS NULL)
      OR (approval_kind = 'SPEND' AND account_id IS NOT NULL AND maximum_credits IS NOT NULL AND operation = 'video_generate')),
  FOREIGN KEY (proposal_id, proposal_fingerprint)
    REFERENCES analytics_experiment_proposals(proposal_id, proposal_fingerprint),
  UNIQUE (attestation_id, attestation_fingerprint)
);

CREATE TABLE analytics_feedback_approval_revocations (
  attestation_id uuid PRIMARY KEY REFERENCES analytics_feedback_approval_attestations(attestation_id),
  revoked_at timestamptz NOT NULL,
  reason_code text NOT NULL CHECK (reason_code IN ('REVOKED','SUPERSEDED','SECURITY_HOLD')),
  actor_ref text NOT NULL CHECK (actor_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$')
);

CREATE FUNCTION persist_feedback_approval_revocation(
  source_attestation_id uuid, source_revoked_at timestamptz,
  source_reason_code text, source_actor_ref text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
  IF source_revoked_at > clock_timestamp() THEN
    RAISE EXCEPTION 'approval revocation time is invalid' USING ERRCODE = 'check_violation';
  END IF;
  INSERT INTO public.analytics_feedback_approval_revocations
    (attestation_id, revoked_at, reason_code, actor_ref)
  VALUES (source_attestation_id, source_revoked_at, source_reason_code, source_actor_ref)
  ON CONFLICT DO NOTHING;
  IF NOT EXISTS (SELECT 1 FROM public.analytics_feedback_approval_revocations
    WHERE attestation_id = source_attestation_id
      AND revoked_at = source_revoked_at AND reason_code = source_reason_code
      AND actor_ref = source_actor_ref) THEN
    RAISE EXCEPTION 'approval revocation identity conflicts' USING ERRCODE = 'check_violation';
  END IF;
END;
$$;

CREATE FUNCTION require_feedback_approval_attestation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_fingerprint char(64); decision_now timestamptz;
BEGIN
  PERFORM 1 FROM analytics_experiment_proposals
   WHERE proposal_id = NEW.proposal_id
     AND proposal_fingerprint = NEW.proposal_fingerprint FOR SHARE;
  decision_now := clock_timestamp();
  SELECT encode(digest(array_to_string(ARRAY[
    NEW.attestation_id::text, NEW.approval_kind, NEW.approval_ref,
    NEW.owner_user_id, NEW.proposal_id::text, NEW.proposal_fingerprint,
    coalesce(NEW.account_id::text,''), coalesce(NEW.maximum_credits::text,''),
    coalesce(NEW.operation,''),
    NEW.verifier_ref, NEW.verifier_version, NEW.evidence_fingerprint,
    to_char(NEW.verified_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(NEW.expires_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_fingerprint;
  IF NEW.attestation_fingerprint IS DISTINCT FROM expected_fingerprint
     OR NEW.verified_at > decision_now
     OR NEW.expires_at <= decision_now THEN
    RAISE EXCEPTION 'feedback approval attestation is invalid or stale' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER analytics_feedback_approval_attestations_require_evidence
  BEFORE INSERT ON analytics_feedback_approval_attestations FOR EACH ROW
  EXECUTE FUNCTION require_feedback_approval_attestation();

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowx_feedback_attestation_writer') THEN
    CREATE ROLE flowx_feedback_attestation_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flowx_feedback_gate_runtime') THEN
    CREATE ROLE flowx_feedback_gate_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;

CREATE FUNCTION persist_feedback_approval_attestation(
  source_attestation_id uuid, source_approval_kind text, source_approval_ref text,
  source_owner_user_id text, source_proposal_id uuid,
  source_proposal_fingerprint char(64), source_account_id uuid,
  source_maximum_credits integer, source_operation text,
  source_verifier_ref text, source_verifier_version text,
  source_evidence_fingerprint char(64), source_attestation_fingerprint char(64),
  source_verified_at timestamptz, source_expires_at timestamptz
) RETURNS char(64)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE stored_fingerprint char(64);
BEGIN
  INSERT INTO public.analytics_feedback_approval_attestations
    (attestation_id, approval_kind, approval_ref, owner_user_id,
     proposal_id, proposal_fingerprint, account_id, maximum_credits, operation,
     verifier_ref, verifier_version, evidence_fingerprint,
     attestation_fingerprint, verified_at, expires_at)
  VALUES (source_attestation_id, source_approval_kind, source_approval_ref,
    source_owner_user_id, source_proposal_id, source_proposal_fingerprint,
    source_account_id, source_maximum_credits, source_operation,
    source_verifier_ref, source_verifier_version, source_evidence_fingerprint,
    source_attestation_fingerprint, source_verified_at, source_expires_at)
  ON CONFLICT DO NOTHING RETURNING attestation_fingerprint INTO stored_fingerprint;
  IF stored_fingerprint IS NULL THEN
    SELECT attestation_fingerprint INTO stored_fingerprint
      FROM public.analytics_feedback_approval_attestations
     WHERE attestation_id = source_attestation_id;
  END IF;
  IF stored_fingerprint IS DISTINCT FROM source_attestation_fingerprint THEN
    RAISE EXCEPTION 'approval attestation identity conflicts' USING ERRCODE = 'check_violation';
  END IF;
  RETURN stored_fingerprint;
END;
$$;
REVOKE ALL ON FUNCTION persist_feedback_approval_attestation(
  uuid,text,text,text,uuid,char(64),uuid,integer,text,text,text,char(64),char(64),timestamptz,timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION persist_feedback_approval_attestation(
  uuid,text,text,text,uuid,char(64),uuid,integer,text,text,text,char(64),char(64),timestamptz,timestamptz
) TO flowx_feedback_attestation_writer;
REVOKE ALL ON FUNCTION persist_feedback_approval_revocation(uuid,timestamptz,text,text)
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION persist_feedback_approval_revocation(uuid,timestamptz,text,text)
  TO flowx_feedback_attestation_writer;

CREATE TABLE analytics_feedback_gates (
  gate_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  proposal_id uuid NOT NULL,
  proposal_fingerprint char(64) NOT NULL,
  account_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  reservation_request_id uuid NOT NULL,
  maximum_credits integer NOT NULL CHECK (maximum_credits BETWEEN 1 AND 1000000000),
  quoted_credits integer NOT NULL CHECK (quoted_credits BETWEEN 1 AND maximum_credits),
  quote_expires_at timestamptz NOT NULL,
  human_approval_ref text NOT NULL CHECK (human_approval_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  spend_approval_ref text NOT NULL CHECK (spend_approval_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$'),
  human_attestation_id uuid NOT NULL,
  human_approval_fingerprint char(64) NOT NULL CHECK (human_approval_fingerprint ~ '^[0-9a-f]{64}$'),
  spend_attestation_id uuid NOT NULL,
  spend_approval_fingerprint char(64) NOT NULL CHECK (spend_approval_fingerprint ~ '^[0-9a-f]{64}$'),
  definition_version text NOT NULL CHECK (definition_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  gate_data jsonb NOT NULL CHECK (jsonb_typeof(gate_data) = 'object' AND pg_column_size(gate_data) <= 65536),
  gate_fingerprint char(64) NOT NULL UNIQUE CHECK (gate_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL UNIQUE CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  approved_at timestamptz NOT NULL,
  FOREIGN KEY (proposal_id, proposal_fingerprint)
    REFERENCES analytics_experiment_proposals(proposal_id, proposal_fingerprint),
  FOREIGN KEY (reservation_id, account_id, reservation_request_id)
    REFERENCES flow_credit_reservations(id, flow_account_id, request_id),
  FOREIGN KEY (human_attestation_id, human_approval_fingerprint)
    REFERENCES analytics_feedback_approval_attestations(attestation_id, attestation_fingerprint),
  FOREIGN KEY (spend_attestation_id, spend_approval_fingerprint)
    REFERENCES analytics_feedback_approval_attestations(attestation_id, attestation_fingerprint)
);

ALTER TABLE analytics_feedback_gates
  ADD CONSTRAINT analytics_feedback_gate_exact_identity
  UNIQUE (gate_id, gate_fingerprint);

CREATE FUNCTION require_spend_aware_feedback_gate() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  proposal_owner text; proposal_created timestamptz;
  account_owner text; account_health text; account_paused boolean; account_compliance boolean;
  observed_daily bigint; observed_monthly bigint; reconciled_at timestamptz;
  daily_reset timestamptz; cycle_start timestamptz; account_max_inflight integer;
  reservation_state text; reservation_credits integer; reservation_expiry timestamptz;
  reservation_quoted_at timestamptz; active_count bigint; active_credits bigint;
  human_kind text; human_ref text; human_owner text; human_proposal uuid;
  human_proposal_fingerprint char(64); human_verified timestamptz; human_expires timestamptz;
  spend_kind text; spend_ref text; spend_owner text; spend_proposal uuid;
  spend_proposal_fingerprint char(64); spend_account uuid; spend_max integer;
  spend_verified timestamptz; spend_expires timestamptz;
  decision_now timestamptz;
  expected_request char(64);
  expected_gate char(64);
BEGIN
  SELECT owner_user_id, created_at INTO proposal_owner, proposal_created
    FROM analytics_experiment_proposals
   WHERE proposal_id = NEW.proposal_id
     AND proposal_fingerprint = NEW.proposal_fingerprint FOR SHARE;
  SELECT owner_user_id, session_health, paused, compliance_approved,
         observed_daily_available, observed_monthly_available,
         last_reconciled_at, next_daily_reset_at, monthly_cycle_starts_at,
         max_inflight
    INTO account_owner, account_health, account_paused, account_compliance,
         observed_daily, observed_monthly, reconciled_at, daily_reset,
         cycle_start, account_max_inflight
    FROM flow_accounts WHERE id = NEW.account_id FOR UPDATE;
  SELECT state, quoted_credits, quote_expires_at, quoted_at
    INTO reservation_state, reservation_credits, reservation_expiry,
         reservation_quoted_at
    FROM flow_credit_reservations
   WHERE id = NEW.reservation_id AND flow_account_id = NEW.account_id
     AND request_id = NEW.reservation_request_id FOR UPDATE;
  SELECT count(*), coalesce(sum(quoted_credits),0)
    INTO active_count, active_credits FROM flow_credit_reservations
   WHERE flow_account_id = NEW.account_id
     AND state IN ('RESERVED','RECONCILE_PENDING');
  SELECT approval_kind, approval_ref, owner_user_id, proposal_id,
         proposal_fingerprint, verified_at, expires_at
    INTO human_kind, human_ref, human_owner, human_proposal,
         human_proposal_fingerprint, human_verified, human_expires
    FROM analytics_feedback_approval_attestations
   WHERE attestation_id = NEW.human_attestation_id
     AND attestation_fingerprint = NEW.human_approval_fingerprint FOR UPDATE;
  SELECT approval_kind, approval_ref, owner_user_id, proposal_id,
         proposal_fingerprint, account_id, maximum_credits, verified_at, expires_at
    INTO spend_kind, spend_ref, spend_owner, spend_proposal,
         spend_proposal_fingerprint, spend_account, spend_max,
         spend_verified, spend_expires
    FROM analytics_feedback_approval_attestations
   WHERE attestation_id = NEW.spend_attestation_id
     AND attestation_fingerprint = NEW.spend_approval_fingerprint FOR UPDATE;
  decision_now := clock_timestamp();

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.gate_id::text, NEW.owner_user_id, NEW.proposal_id::text,
    NEW.proposal_fingerprint, NEW.account_id::text, NEW.reservation_id::text,
    NEW.reservation_request_id::text, NEW.maximum_credits::text,
    NEW.human_approval_ref, NEW.spend_approval_ref, NEW.definition_version,
    to_char((NEW.gate_data->>'requested_at')::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_request;
  SELECT encode(digest(array_to_string(ARRAY[
    NEW.gate_id::text, NEW.owner_user_id, NEW.request_fingerprint,
    NEW.proposal_id::text, NEW.proposal_fingerprint, NEW.account_id::text,
    NEW.reservation_id::text, NEW.reservation_request_id::text,
    NEW.maximum_credits::text, NEW.quoted_credits::text,
    to_char(NEW.quote_expires_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    NEW.human_attestation_id::text, NEW.human_approval_fingerprint,
    NEW.spend_attestation_id::text, NEW.spend_approval_fingerprint,
    NEW.definition_version, NEW.gate_data->>'status',
    to_char(NEW.approved_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_gate;

  IF proposal_owner IS NULL OR account_owner IS NULL OR reservation_state IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM proposal_owner
     OR NEW.owner_user_id IS DISTINCT FROM account_owner
     OR account_health IS DISTINCT FROM 'HEALTHY' OR account_paused
     OR NOT account_compliance
     OR observed_daily IS NULL OR observed_monthly IS NULL
     OR reconciled_at IS NULL OR reconciled_at > decision_now
     OR reconciled_at < decision_now - interval '15 minutes'
     OR daily_reset IS NULL OR decision_now >= daily_reset
     OR cycle_start IS NULL OR reconciled_at < cycle_start
     OR account_max_inflight IS NULL OR active_count > account_max_inflight
     OR active_credits > observed_daily OR active_credits > observed_monthly
     OR reservation_state IS DISTINCT FROM 'RESERVED'
     OR NEW.quoted_credits IS DISTINCT FROM reservation_credits
     OR NEW.quote_expires_at IS DISTINCT FROM reservation_expiry
     OR NEW.quoted_credits > NEW.maximum_credits
     OR reservation_expiry <= decision_now
     OR reservation_quoted_at > decision_now
     OR reservation_quoted_at < decision_now - interval '5 minutes'
     OR NEW.approved_at < proposal_created OR NEW.approved_at > decision_now
     OR NEW.approved_at < human_verified OR NEW.approved_at < spend_verified
     OR (NEW.gate_data->>'requested_at')::timestamptz > NEW.approved_at
     OR EXISTS (SELECT 1 FROM flow_credit_alarms
       WHERE flow_account_id = NEW.account_id AND state = 'OPEN')
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request
     OR human_kind IS DISTINCT FROM 'HUMAN_EXPERIMENT'
     OR human_ref IS DISTINCT FROM NEW.human_approval_ref
     OR human_owner IS DISTINCT FROM NEW.owner_user_id
     OR human_proposal IS DISTINCT FROM NEW.proposal_id
     OR human_proposal_fingerprint IS DISTINCT FROM NEW.proposal_fingerprint
     OR human_verified > decision_now OR human_expires <= decision_now
     OR spend_kind IS DISTINCT FROM 'SPEND'
     OR spend_ref IS DISTINCT FROM NEW.spend_approval_ref
     OR spend_owner IS DISTINCT FROM NEW.owner_user_id
     OR spend_proposal IS DISTINCT FROM NEW.proposal_id
     OR spend_proposal_fingerprint IS DISTINCT FROM NEW.proposal_fingerprint
     OR spend_account IS DISTINCT FROM NEW.account_id
     OR spend_max IS DISTINCT FROM NEW.quoted_credits
     OR spend_verified > decision_now OR spend_expires <= decision_now
     OR EXISTS (SELECT 1 FROM analytics_feedback_approval_revocations
       WHERE attestation_id IN (NEW.human_attestation_id, NEW.spend_attestation_id))
     OR NEW.gate_fingerprint IS DISTINCT FROM expected_gate
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.gate_data)) <> 26
     OR NEW.gate_data->>'gate_id' IS DISTINCT FROM NEW.gate_id::text
     OR NEW.gate_data->>'owner_user_id' IS DISTINCT FROM NEW.owner_user_id
     OR NEW.gate_data->>'request_fingerprint' IS DISTINCT FROM NEW.request_fingerprint
     OR NEW.gate_data->>'proposal_id' IS DISTINCT FROM NEW.proposal_id::text
     OR NEW.gate_data->>'proposal_fingerprint' IS DISTINCT FROM NEW.proposal_fingerprint
     OR NEW.gate_data->>'account_id' IS DISTINCT FROM NEW.account_id::text
     OR NEW.gate_data->>'reservation_id' IS DISTINCT FROM NEW.reservation_id::text
     OR NEW.gate_data->>'reservation_request_id' IS DISTINCT FROM NEW.reservation_request_id::text
     OR (NEW.gate_data->>'maximum_credits')::integer IS DISTINCT FROM NEW.maximum_credits
     OR (NEW.gate_data->>'quoted_credits')::integer IS DISTINCT FROM NEW.quoted_credits
     OR (NEW.gate_data->>'quote_expires_at')::timestamptz IS DISTINCT FROM NEW.quote_expires_at
     OR NEW.gate_data->>'human_attestation_id' IS DISTINCT FROM NEW.human_attestation_id::text
     OR NEW.gate_data->>'human_approval_fingerprint' IS DISTINCT FROM NEW.human_approval_fingerprint
     OR NEW.gate_data->>'spend_attestation_id' IS DISTINCT FROM NEW.spend_attestation_id::text
     OR NEW.gate_data->>'spend_approval_fingerprint' IS DISTINCT FROM NEW.spend_approval_fingerprint
     OR NEW.gate_data->>'definition_version' IS DISTINCT FROM NEW.definition_version
     OR NEW.gate_data->>'status' IS DISTINCT FROM 'APPROVED_PENDING_FRESH_EXECUTOR_REVALIDATION'
     OR NEW.gate_data->'separate_executor_must_revalidate_exact_reservation' IS DISTINCT FROM 'true'::jsonb
     OR NEW.gate_data->'execution_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.gate_data->'automatic_execution' IS DISTINCT FROM 'false'::jsonb
     OR NEW.gate_data->'account_connection_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.gate_data->'scheduling_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.gate_data->'upload_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.gate_data->'publishing_authorized' IS DISTINCT FROM 'false'::jsonb
     OR (NEW.gate_data->>'approved_at')::timestamptz IS DISTINCT FROM NEW.approved_at THEN
    RAISE EXCEPTION 'feedback gate evidence is invalid or unsafe' USING ERRCODE = 'check_violation';
  END IF;
  NEW.storage_fingerprint := encode(digest(
    NEW.request_fingerprint || '|' || NEW.gate_fingerprint || '|' ||
    NEW.proposal_fingerprint || '|' || NEW.reservation_id::text || '|' ||
    NEW.gate_data::text, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_feedback_gates_require_evidence
  BEFORE INSERT ON analytics_feedback_gates FOR EACH ROW
  EXECUTE FUNCTION require_spend_aware_feedback_gate();

CREATE TABLE analytics_feedback_outcomes (
  outcome_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  gate_id uuid NOT NULL,
  gate_fingerprint char(64) NOT NULL,
  proposal_id uuid NOT NULL,
  proposal_fingerprint char(64) NOT NULL,
  report_request_id uuid NOT NULL,
  report_request_fingerprint char(64) NOT NULL,
  report_fingerprint char(64) NOT NULL,
  definition_version text NOT NULL CHECK (definition_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  source_count integer NOT NULL CHECK (source_count BETWEEN 1 AND 10000),
  outcome_data jsonb NOT NULL CHECK (jsonb_typeof(outcome_data) = 'object' AND pg_column_size(outcome_data) <= 65536),
  outcome_fingerprint char(64) NOT NULL UNIQUE CHECK (outcome_fingerprint ~ '^[0-9a-f]{64}$'),
  storage_fingerprint char(64) NOT NULL UNIQUE CHECK (storage_fingerprint ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz NOT NULL,
  FOREIGN KEY (gate_id, gate_fingerprint)
    REFERENCES analytics_feedback_gates(gate_id, gate_fingerprint),
  FOREIGN KEY (proposal_id, proposal_fingerprint)
    REFERENCES analytics_experiment_proposals(proposal_id, proposal_fingerprint),
  FOREIGN KEY (report_request_id, report_fingerprint)
    REFERENCES cohort_analysis_reports(request_id, report_fingerprint)
);

CREATE FUNCTION require_descriptive_feedback_outcome() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  gate_owner text; gate_proposal uuid; gate_proposal_fingerprint char(64); gate_approved timestamptz;
  proposal_factor text; proposal_metric text; proposal_window text;
  proposal_registry_version text; proposal_registry_fingerprint char(64);
  proposal_control text; proposal_treatment text; control_target integer; treatment_target integer;
  report_owner text; report_request_fingerprint char(64); report_factor text;
  report_metric text; report_window text; report_registry_version text;
  report_registry_fingerprint char(64); report_created timestamptz; report_data jsonb;
  expected_request char(64); expected_outcome char(64);
BEGIN
  SELECT owner_user_id, proposal_id, proposal_fingerprint, approved_at
    INTO gate_owner, gate_proposal, gate_proposal_fingerprint, gate_approved
    FROM analytics_feedback_gates
   WHERE gate_id = NEW.gate_id AND gate_fingerprint = NEW.gate_fingerprint FOR SHARE;
  SELECT single_variable, metric_id, window_name, registry_version,
         registry_fingerprint, control_label, treatment_label,
         control_target_size, treatment_target_size
    INTO proposal_factor, proposal_metric, proposal_window,
         proposal_registry_version, proposal_registry_fingerprint,
         proposal_control, proposal_treatment, control_target, treatment_target
    FROM analytics_experiment_proposals
   WHERE proposal_id = NEW.proposal_id
     AND proposal_fingerprint = NEW.proposal_fingerprint FOR SHARE;
  SELECT owner_user_id, request_fingerprint, factor, metric_id, window_name,
         registry_version, registry_fingerprint, created_at, report_data
    INTO report_owner, report_request_fingerprint, report_factor, report_metric,
         report_window, report_registry_version, report_registry_fingerprint,
         report_created, report_data
    FROM cohort_analysis_reports
   WHERE request_id = NEW.report_request_id
     AND report_fingerprint = NEW.report_fingerprint FOR SHARE;

  SELECT encode(digest(array_to_string(ARRAY[
    NEW.outcome_id::text, NEW.owner_user_id, NEW.gate_id::text,
    NEW.gate_fingerprint, NEW.report_request_id::text, NEW.report_fingerprint,
    NEW.definition_version,
    to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_request;
  SELECT encode(digest(array_to_string(ARRAY[
    NEW.outcome_id::text, NEW.owner_user_id, NEW.request_fingerprint,
    NEW.gate_id::text, NEW.gate_fingerprint, NEW.proposal_id::text,
    NEW.proposal_fingerprint, NEW.report_request_id::text,
    NEW.report_request_fingerprint, NEW.report_fingerprint,
    NEW.definition_version, NEW.source_count::text,
    NEW.outcome_data->>'status',
    to_char(NEW.recorded_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ], '|'), 'sha256'), 'hex') INTO expected_outcome;

  IF gate_owner IS NULL OR report_owner IS NULL OR proposal_factor IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM gate_owner
     OR NEW.owner_user_id IS DISTINCT FROM report_owner
     OR NEW.proposal_id IS DISTINCT FROM gate_proposal
     OR NEW.proposal_fingerprint IS DISTINCT FROM gate_proposal_fingerprint
     OR report_factor IS DISTINCT FROM proposal_factor
     OR report_metric IS DISTINCT FROM proposal_metric
     OR report_window IS DISTINCT FROM proposal_window
     OR report_registry_version IS DISTINCT FROM proposal_registry_version
     OR report_registry_fingerprint IS DISTINCT FROM proposal_registry_fingerprint
     OR NEW.report_request_fingerprint IS DISTINCT FROM report_request_fingerprint
     OR report_data->>'status' IS DISTINCT FROM 'DESCRIPTIVE'
     OR report_created < gate_approved OR NEW.recorded_at < report_created
     OR NEW.source_count IS DISTINCT FROM jsonb_array_length(report_data->'sources')
     OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(report_data->'cohorts') AS item(value)
       WHERE value->>'label' = proposal_control AND (value->>'eligible')::boolean
         AND (value->>'sample_size')::integer >= control_target)
     OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(report_data->'cohorts') AS item(value)
       WHERE value->>'label' = proposal_treatment AND (value->>'eligible')::boolean
         AND (value->>'sample_size')::integer >= treatment_target)
     OR EXISTS (SELECT 1 FROM cohort_analysis_sources AS source
       JOIN creative_metadata_snapshots AS metadata ON metadata.snapshot_id = source.metadata_snapshot_id
       JOIN analytics_metric_observations AS observation
         ON observation.request_id = source.observation_request_id
        AND observation.publication_id = source.publication_id
       WHERE source.request_id = NEW.report_request_id
         AND (metadata.created_at < gate_approved
           OR metadata.published_at <= gate_approved
           OR observation.published_at <= gate_approved
           OR observation.window_started_at <= gate_approved
           OR observation.window_ended_at <= gate_approved
           OR observation.observed_at <= gate_approved))
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request
     OR NEW.outcome_fingerprint IS DISTINCT FROM expected_outcome
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.outcome_data)) <> 17
     OR NEW.outcome_data->>'outcome_id' IS DISTINCT FROM NEW.outcome_id::text
     OR NEW.outcome_data->>'owner_user_id' IS DISTINCT FROM NEW.owner_user_id
     OR NEW.outcome_data->>'request_fingerprint' IS DISTINCT FROM NEW.request_fingerprint
     OR NEW.outcome_data->>'gate_id' IS DISTINCT FROM NEW.gate_id::text
     OR NEW.outcome_data->>'gate_fingerprint' IS DISTINCT FROM NEW.gate_fingerprint
     OR NEW.outcome_data->>'proposal_id' IS DISTINCT FROM NEW.proposal_id::text
     OR NEW.outcome_data->>'proposal_fingerprint' IS DISTINCT FROM NEW.proposal_fingerprint
     OR NEW.outcome_data->>'report_request_id' IS DISTINCT FROM NEW.report_request_id::text
     OR NEW.outcome_data->>'report_request_fingerprint' IS DISTINCT FROM NEW.report_request_fingerprint
     OR NEW.outcome_data->>'report_fingerprint' IS DISTINCT FROM NEW.report_fingerprint
     OR NEW.outcome_data->>'definition_version' IS DISTINCT FROM NEW.definition_version
     OR (NEW.outcome_data->>'source_count')::integer IS DISTINCT FROM NEW.source_count
     OR NEW.outcome_data->>'status' IS DISTINCT FROM 'DESCRIPTIVE_FEEDBACK_ONLY_NOT_CAUSAL'
     OR NEW.outcome_data->'new_recommendation_requires_separate_human_review' IS DISTINCT FROM 'true'::jsonb
     OR NEW.outcome_data->'causal_claim_authorized' IS DISTINCT FROM 'false'::jsonb
     OR NEW.outcome_data->'automatic_execution' IS DISTINCT FROM 'false'::jsonb
     OR (NEW.outcome_data->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at THEN
    RAISE EXCEPTION 'feedback outcome is not exact post-gate descriptive evidence' USING ERRCODE = 'check_violation';
  END IF;
  NEW.storage_fingerprint := encode(digest(
    NEW.request_fingerprint || '|' || NEW.outcome_fingerprint || '|' ||
    NEW.gate_fingerprint || '|' || NEW.report_fingerprint || '|' ||
    NEW.outcome_data::text, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER analytics_feedback_outcomes_require_evidence
  BEFORE INSERT ON analytics_feedback_outcomes FOR EACH ROW
  EXECUTE FUNCTION require_descriptive_feedback_outcome();

CREATE FUNCTION guard_feedback_evidence_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'feedback gate and outcome evidence is immutable' USING ERRCODE = 'check_violation';
END; $$;
CREATE TRIGGER analytics_feedback_gates_immutable
  BEFORE UPDATE OR DELETE ON analytics_feedback_gates FOR EACH ROW
  EXECUTE FUNCTION guard_feedback_evidence_immutable();
CREATE TRIGGER analytics_feedback_outcomes_immutable
  BEFORE UPDATE OR DELETE ON analytics_feedback_outcomes FOR EACH ROW
  EXECUTE FUNCTION guard_feedback_evidence_immutable();
CREATE TRIGGER analytics_feedback_approval_attestations_immutable
  BEFORE UPDATE OR DELETE ON analytics_feedback_approval_attestations FOR EACH ROW
  EXECUTE FUNCTION guard_feedback_evidence_immutable();
CREATE TRIGGER analytics_feedback_approval_revocations_immutable
  BEFORE UPDATE OR DELETE ON analytics_feedback_approval_revocations FOR EACH ROW
  EXECUTE FUNCTION guard_feedback_evidence_immutable();

REVOKE INSERT, UPDATE, DELETE ON analytics_feedback_approval_attestations FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON analytics_feedback_approval_revocations FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON analytics_feedback_gates FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON analytics_feedback_outcomes FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO flowx_feedback_attestation_writer, flowx_feedback_gate_runtime;
GRANT SELECT ON analytics_feedback_approval_attestations,
  analytics_feedback_approval_revocations, analytics_experiment_proposals,
  analytics_feedback_gates, analytics_feedback_outcomes,
  flow_accounts, flow_credit_reservations, flow_credit_alarms,
  cohort_analysis_reports, cohort_analysis_sources,
  creative_metadata_snapshots, analytics_metric_observations
  TO flowx_feedback_gate_runtime;
GRANT INSERT ON analytics_feedback_gates, analytics_feedback_outcomes
  TO flowx_feedback_gate_runtime;

COMMENT ON ROLE flowx_feedback_attestation_writer IS
  'NOLOGIN capability role granted only to the trusted approval-attestation adapter connection';
COMMENT ON ROLE flowx_feedback_gate_runtime IS
  'NOLOGIN capability role for ordinary TASK-066 gate/outcome persistence; cannot create attestations';
