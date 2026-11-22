-- Immutable policy/factuality/copyright signals bound to passing AV evidence.

CREATE UNIQUE INDEX idx_qa_reports_asset_signals_version
  ON qa_reports(asset_id, version)
  WHERE version = 'signals-v1';

CREATE FUNCTION require_policy_signal_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE asset_content uuid;
DECLARE asset_scene uuid;
DECLARE asset_state text;
DECLARE asset_kind text;
DECLARE expected_blockers jsonb;
DECLARE blocker_present boolean;
DECLARE finding_count integer;
BEGIN
  SELECT a.content_id, a.scene_id, a.retention_state, a.asset_kind
    INTO asset_content, asset_scene, asset_state, asset_kind
    FROM assets AS a WHERE a.id = NEW.asset_id FOR SHARE;
  IF asset_content IS NULL OR NEW.content_id IS NULL
     OR NEW.content_id <> asset_content OR NEW.scene_id IS NOT NULL
     OR asset_scene IS NOT NULL OR asset_state <> 'ACTIVE'
     OR asset_kind NOT IN ('FINAL_VIDEO', 'EXPORT_VARIANT') THEN
    RAISE EXCEPTION 'policy signal QA report is outside active render lineage'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.version <> 'signals-v1' OR NEW.reviewer_type <> 'AUTO'
     OR NEW.score IS NOT NULL
     OR NEW.decision NOT IN ('PASS', 'FAIL', 'NEEDS_HUMAN')
     OR jsonb_typeof(NEW.hard_blockers) IS DISTINCT FROM 'array'
     OR jsonb_typeof(NEW.checks) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'policy signal QA report contract is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.checks->>'asset_id' IS DISTINCT FROM NEW.asset_id::text
     OR NEW.checks->>'content_id' IS DISTINCT FROM NEW.content_id::text
     OR NEW.checks->>'decision' IS DISTINCT FROM NEW.decision
     OR NEW.checks->'human_approval_required' IS DISTINCT FROM 'true'::jsonb
     OR NEW.checks->'content_approved' IS DISTINCT FROM 'false'::jsonb
     OR jsonb_typeof(NEW.checks->'review') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.checks->'prompt_id') IS DISTINCT FROM 'string'
     OR length(NEW.checks->>'prompt_id') NOT BETWEEN 1 AND 100
     OR jsonb_typeof(NEW.checks->'prompt_version') IS DISTINCT FROM 'number'
     OR jsonb_typeof(NEW.checks->'policy_version') IS DISTINCT FROM 'number'
     OR NEW.checks->>'evidence_fingerprint' IS NULL
     OR NEW.checks->>'evidence_fingerprint' !~ '^[0-9a-f]{64}$'
     OR NEW.checks->>'av_evidence_fingerprint' IS NULL
     OR NEW.checks->>'av_evidence_fingerprint' !~ '^[0-9a-f]{64}$'
     OR NEW.checks->>'review_context_fingerprint' IS NULL
     OR NEW.checks->>'review_context_fingerprint' !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(NEW.checks->'signals') IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.checks->'signals') <> 3
     OR NEW.checks->'signals'->0->>'domain' IS DISTINCT FROM 'POLICY'
     OR NEW.checks->'signals'->1->>'domain' IS DISTINCT FROM 'FACTUALITY'
     OR NEW.checks->'signals'->2->>'domain' IS DISTINCT FROM 'COPYRIGHT'
     OR jsonb_typeof(NEW.checks->'findings') IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.checks->'findings') > 9 THEN
    RAISE EXCEPTION 'policy signal QA evidence envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.checks->'signals') AS entry(signal)
    WHERE jsonb_typeof(signal) IS DISTINCT FROM 'object'
       OR jsonb_object_length(signal) <> 4
       OR signal->>'state' IS NULL
       OR signal->>'state' NOT IN ('NO_AUTOMATED_FLAG', 'FLAGGED', 'UNAVAILABLE')
       OR jsonb_typeof(signal->'evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_typeof(signal->'authority_refs') IS DISTINCT FROM 'array'
       OR jsonb_array_length(signal->'evidence_ids') > 20
       OR jsonb_array_length(signal->'authority_refs') > 20
  ) THEN
    RAISE EXCEPTION 'policy signal QA signal envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF jsonb_array_length(NEW.checks->'signals'->0->'authority_refs') < 1
     OR NEW.checks->'signals'->0->>'state' = 'UNAVAILABLE'
     OR NEW.checks->'signals'->1->>'state' = 'UNAVAILABLE'
     OR (NEW.checks->'signals'->2->>'state' = 'UNAVAILABLE'
         AND jsonb_array_length(NEW.checks->'signals'->2->'authority_refs') <> 0)
     OR (NEW.checks->'signals'->2->>'state' = 'NO_AUTOMATED_FLAG'
         AND jsonb_array_length(NEW.checks->'signals'->2->'authority_refs') = 0) THEN
    RAISE EXCEPTION 'policy signal QA authority envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.checks->'findings') AS entry(finding)
    WHERE jsonb_typeof(finding) IS DISTINCT FROM 'object'
       OR jsonb_object_length(finding) <> 2
       OR finding->>'code' IS NULL
       OR finding->>'code' NOT IN (
         'POLICY_CRITICAL', 'POLICY_REVIEW_REQUIRED',
         'FACTUALITY_CRITICAL', 'FACTUALITY_REVIEW_REQUIRED',
         'COPYRIGHT_CRITICAL', 'COPYRIGHT_REVIEW_REQUIRED',
         'COPYRIGHT_AUTHORITY_UNAVAILABLE', 'AUTOMATED_REVIEW_BLOCKED',
         'AUTOMATED_REVIEW_NEEDS_REVISION'
       )
       OR finding->>'severity' IS NULL
       OR finding->>'severity' NOT IN ('BLOCKER', 'REVIEW')
  ) THEN
    RAISE EXCEPTION 'policy signal QA finding envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT COALESCE(jsonb_agg(finding->>'code' ORDER BY ordinal)
                    FILTER (WHERE finding->>'severity' = 'BLOCKER'), '[]'::jsonb),
         COALESCE(bool_or(finding->>'severity' = 'BLOCKER'), false), count(*)
    INTO expected_blockers, blocker_present, finding_count
    FROM jsonb_array_elements(NEW.checks->'findings')
      WITH ORDINALITY AS entry(finding, ordinal);
  IF NEW.hard_blockers <> expected_blockers THEN
    RAISE EXCEPTION 'policy signal QA blocker envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (blocker_present AND NEW.decision <> 'FAIL')
     OR (NOT blocker_present AND finding_count > 0 AND NEW.decision <> 'NEEDS_HUMAN')
     OR (finding_count = 0 AND NEW.decision <> 'PASS') THEN
    RAISE EXCEPTION 'policy signal QA decision does not match findings'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM qa_reports AS av
    WHERE av.asset_id = NEW.asset_id AND av.version = 'av-v1'
      AND av.decision = 'PASS'
      AND av.checks->>'evidence_fingerprint' = NEW.checks->>'av_evidence_fingerprint'
    FOR SHARE
  ) THEN
    RAISE EXCEPTION 'policy signal QA report lacks passing AV evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER qa_reports_policy_signal_lineage
  BEFORE INSERT ON qa_reports
  FOR EACH ROW WHEN (NEW.version = 'signals-v1')
  EXECUTE FUNCTION require_policy_signal_lineage();

CREATE FUNCTION prevent_policy_signal_report_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.version = 'signals-v1' THEN
    RAISE EXCEPTION 'policy signal QA reports are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.version = 'signals-v1' THEN
    RAISE EXCEPTION 'policy signal QA reports are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER qa_reports_policy_signal_immutable
  BEFORE UPDATE OR DELETE ON qa_reports
  FOR EACH ROW EXECUTE FUNCTION prevent_policy_signal_report_mutation();
