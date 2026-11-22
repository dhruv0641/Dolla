-- Immutable owner-visible deterministic integrity reports.

CREATE UNIQUE INDEX idx_qa_reports_asset_version
  ON qa_reports(asset_id, version)
  WHERE version = 'integrity-v1';

CREATE FUNCTION require_qa_report_asset_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE asset_content uuid;
DECLARE asset_scene uuid;
DECLARE asset_state text;
DECLARE asset_kind text;
BEGIN
  SELECT a.content_id, a.scene_id, a.retention_state, a.asset_kind
    INTO asset_content, asset_scene, asset_state, asset_kind
    FROM assets AS a WHERE a.id = NEW.asset_id FOR SHARE;
  IF asset_content IS NULL OR NEW.content_id IS NULL
     OR NEW.content_id <> asset_content OR NEW.scene_id IS NOT NULL
     OR asset_scene IS NOT NULL OR asset_state <> 'ACTIVE'
     OR asset_kind NOT IN ('FINAL_VIDEO', 'EXPORT_VARIANT') THEN
    RAISE EXCEPTION 'integrity QA report is outside active render lineage'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.version <> 'integrity-v1' OR NEW.reviewer_type <> 'AUTO'
     OR NEW.score IS NOT NULL OR NEW.decision NOT IN ('PASS', 'FAIL')
     OR jsonb_typeof(NEW.hard_blockers) <> 'array'
     OR jsonb_typeof(NEW.checks) <> 'object' THEN
    RAISE EXCEPTION 'integrity QA report contract is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER qa_reports_integrity_lineage
  BEFORE INSERT ON qa_reports
  FOR EACH ROW WHEN (NEW.version = 'integrity-v1')
  EXECUTE FUNCTION require_qa_report_asset_lineage();

CREATE FUNCTION prevent_integrity_qa_report_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.version = 'integrity-v1' THEN
    RAISE EXCEPTION 'integrity QA reports are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.version = 'integrity-v1' THEN
    RAISE EXCEPTION 'integrity QA reports are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER qa_reports_integrity_immutable
  BEFORE UPDATE OR DELETE ON qa_reports
  FOR EACH ROW EXECUTE FUNCTION prevent_integrity_qa_report_mutation();
