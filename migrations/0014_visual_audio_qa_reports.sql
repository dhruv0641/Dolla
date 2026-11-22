-- Immutable objective visual/audio reports bound to passing integrity evidence.

CREATE UNIQUE INDEX idx_qa_reports_asset_av_version
  ON qa_reports(asset_id, version)
  WHERE version = 'av-v1';

CREATE FUNCTION require_av_report_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
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
    RAISE EXCEPTION 'visual/audio QA report is outside active render lineage'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.version <> 'av-v1' OR NEW.reviewer_type <> 'AUTO'
     OR NEW.score IS NOT NULL
     OR NEW.decision NOT IN ('PASS', 'FAIL', 'NEEDS_HUMAN')
     OR jsonb_typeof(NEW.hard_blockers) <> 'array'
     OR jsonb_typeof(NEW.checks) <> 'object' THEN
    RAISE EXCEPTION 'visual/audio QA report contract is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF jsonb_typeof(NEW.checks->'findings') IS DISTINCT FROM 'array'
     OR jsonb_array_length(NEW.checks->'findings') > 7
     OR jsonb_typeof(NEW.checks->'policy') IS DISTINCT FROM 'object'
     OR NEW.checks->'subjective_signals_not_evaluated' IS DISTINCT FROM
          '["SEMANTIC_VISUAL_QUALITY","SPEECH_INTELLIGIBILITY","MIX_PREFERENCE"]'::jsonb
     OR NEW.checks->>'asset_id' IS DISTINCT FROM NEW.asset_id::text
     OR NEW.checks->>'content_id' IS DISTINCT FROM NEW.content_id::text
     OR NEW.checks->>'decision' IS DISTINCT FROM NEW.decision
     OR NEW.checks->>'evidence_fingerprint' IS NULL
     OR NEW.checks->>'evidence_fingerprint' !~ '^[0-9a-f]{64}$'
     OR NEW.checks->>'integrity_evidence_fingerprint' IS NULL
     OR NEW.checks->>'integrity_evidence_fingerprint' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'visual/audio QA evidence envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.checks->'findings') AS entry(finding)
    WHERE jsonb_typeof(finding) IS DISTINCT FROM 'object'
       OR finding->>'code' IS NULL
       OR finding->>'code' NOT IN (
         'ASSET_REVALIDATION_FAILED', 'ANALYSIS_UNAVAILABLE',
         'BLACK_DURATION_EXCEEDED', 'FREEZE_DURATION_EXCEEDED',
         'SILENCE_DURATION_EXCEEDED', 'LOUDNESS_OUT_OF_RANGE',
         'TRUE_PEAK_EXCEEDED'
       )
       OR finding->>'severity' IS NULL
       OR finding->>'severity' NOT IN ('BLOCKER', 'REVIEW')
  ) THEN
    RAISE EXCEPTION 'visual/audio QA finding envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT COALESCE(jsonb_agg(finding->>'code' ORDER BY ordinal)
                    FILTER (WHERE finding->>'severity' = 'BLOCKER'), '[]'::jsonb),
         COALESCE(bool_or(finding->>'severity' = 'BLOCKER'), false),
         count(*)
    INTO expected_blockers, blocker_present, finding_count
    FROM jsonb_array_elements(NEW.checks->'findings')
      WITH ORDINALITY AS entry(finding, ordinal);
  IF NEW.hard_blockers <> expected_blockers THEN
    RAISE EXCEPTION 'visual/audio QA blocker envelope is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (blocker_present AND NEW.decision <> 'FAIL')
     OR (NOT blocker_present AND finding_count > 0 AND NEW.decision <> 'NEEDS_HUMAN')
     OR (finding_count = 0 AND NEW.decision <> 'PASS') THEN
    RAISE EXCEPTION 'visual/audio QA decision does not match findings'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM qa_reports AS integrity
    WHERE integrity.asset_id = NEW.asset_id
      AND integrity.version = 'integrity-v1'
      AND integrity.decision = 'PASS'
      AND integrity.checks->>'evidence_fingerprint'
          = NEW.checks->>'integrity_evidence_fingerprint'
    FOR SHARE
  ) THEN
    RAISE EXCEPTION 'visual/audio QA report lacks passing integrity evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER qa_reports_av_lineage
  BEFORE INSERT ON qa_reports
  FOR EACH ROW WHEN (NEW.version = 'av-v1')
  EXECUTE FUNCTION require_av_report_lineage();

CREATE FUNCTION prevent_av_report_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.version = 'av-v1' THEN
    RAISE EXCEPTION 'visual/audio QA reports are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.version = 'av-v1' THEN
    RAISE EXCEPTION 'visual/audio QA reports are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER qa_reports_av_immutable
  BEFORE UPDATE OR DELETE ON qa_reports
  FOR EACH ROW EXECUTE FUNCTION prevent_av_report_mutation();
