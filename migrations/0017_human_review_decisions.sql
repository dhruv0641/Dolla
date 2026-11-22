-- Bind every new human decision to exact QA evidence and a lifecycle transition.

ALTER TABLE review_decisions
  ADD COLUMN request_id uuid,
  ADD COLUMN request_fingerprint char(64),
  ADD COLUMN qa_report_id uuid REFERENCES qa_reports(id),
  ADD COLUMN revision_target text
    CHECK (revision_target IN ('SCRIPT_READY','STORYBOARD_READY')),
  ADD CONSTRAINT review_decisions_v1_shape CHECK (
    (request_id IS NULL
      AND request_fingerprint IS NULL
      AND qa_report_id IS NULL
      AND revision_target IS NULL) OR
    (request_id IS NOT NULL
      AND request_fingerprint ~ '^[0-9a-f]{64}$'
      AND qa_report_id IS NOT NULL
      AND asset_id IS NOT NULL
      AND approval_scope = 'FINAL_VIDEO'
      AND reason IS NOT NULL
      AND length(btrim(reason)) BETWEEN 1 AND 2000
      AND (
        (decision IN ('APPROVE','REJECT') AND revision_target IS NULL) OR
        (decision = 'CHANGES_REQUIRED' AND revision_target IS NOT NULL)
      ))
  );

CREATE UNIQUE INDEX idx_review_decisions_request_v1
  ON review_decisions(request_id) WHERE request_id IS NOT NULL;
CREATE UNIQUE INDEX idx_review_decisions_qa_report_v1
  ON review_decisions(qa_report_id) WHERE qa_report_id IS NOT NULL;

CREATE FUNCTION require_human_review_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE content_status text;
DECLARE content_owner text;
DECLARE asset_kind_value text;
DECLARE asset_retention text;
DECLARE qa_version text;
DECLARE qa_decision text;
DECLARE qa_reviewer_type text;
DECLARE qa_blockers jsonb;
DECLARE qa_checks jsonb;
DECLARE expected_fingerprint text;
DECLARE next_status text;
BEGIN
  IF NEW.request_id IS NULL THEN
    RAISE EXCEPTION 'new human review decisions require v1 evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.reviewer_user_id !~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'
     OR NEW.reason IS DISTINCT FROM btrim(NEW.reason)
     OR NEW.reason ~ '[[:cntrl:]]'
     OR NEW.reason ~* '(password|secret|token|credential|api[_-]?key|authorization|cookie)[[:space:]]*[:=][[:space:]]*[^[:space:]]+' THEN
    RAISE EXCEPTION 'human review identity or reason is invalid'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT c.status, b.owner_user_id, a.asset_kind, a.retention_state,
         q.version, q.decision, q.reviewer_type, q.hard_blockers, q.checks
    INTO content_status, content_owner, asset_kind_value, asset_retention,
         qa_version, qa_decision, qa_reviewer_type, qa_blockers, qa_checks
    FROM content_items AS c
    JOIN brands AS b ON b.id = c.brand_id
    JOIN assets AS a
      ON a.id = NEW.asset_id AND a.content_id = c.id AND a.scene_id IS NULL
    JOIN qa_reports AS q
      ON q.id = NEW.qa_report_id AND q.asset_id = a.id AND q.content_id = c.id
    WHERE c.id = NEW.content_id
    FOR UPDATE OF c;

  IF content_status IS DISTINCT FROM 'NEEDS_REVIEW'
     OR content_owner IS DISTINCT FROM NEW.reviewer_user_id
     OR asset_kind_value NOT IN ('FINAL_VIDEO','EXPORT_VARIANT')
     OR asset_retention IS DISTINCT FROM 'ACTIVE'
     OR qa_version IS DISTINCT FROM 'signals-v1'
     OR qa_reviewer_type IS DISTINCT FROM 'AUTO'
     OR qa_decision NOT IN ('PASS','NEEDS_HUMAN','FAIL')
     OR jsonb_typeof(qa_blockers) IS DISTINCT FROM 'array'
     OR qa_checks->'human_approval_required' IS DISTINCT FROM 'true'::jsonb
     OR qa_checks->'content_approved' IS DISTINCT FROM 'false'::jsonb THEN
    RAISE EXCEPTION 'human review evidence is not eligible'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.decision = 'APPROVE'
     AND (qa_decision = 'FAIL' OR jsonb_array_length(qa_blockers) > 0) THEN
    RAISE EXCEPTION 'blocked automated QA cannot be approved'
      USING ERRCODE = 'check_violation';
  END IF;

  expected_fingerprint := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.content_id::text, NEW.asset_id::text,
    NEW.qa_report_id::text, NEW.reviewer_user_id, NEW.decision,
    NEW.approval_scope, COALESCE(NEW.revision_target, ''), NEW.reason
  ), 'sha256'), 'hex');
  IF NEW.request_fingerprint IS DISTINCT FROM expected_fingerprint THEN
    RAISE EXCEPTION 'human review fingerprint is invalid'
      USING ERRCODE = 'check_violation';
  END IF;

  next_status := CASE NEW.decision
    WHEN 'APPROVE' THEN 'READY'
    WHEN 'REJECT' THEN 'ARCHIVED'
    ELSE NEW.revision_target
  END;
  UPDATE content_items SET status = next_status, updated_at = now()
    WHERE id = NEW.content_id AND status = 'NEEDS_REVIEW';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'content changed while human review was recorded'
      USING ERRCODE = 'serialization_failure';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER review_decisions_require_evidence
  BEFORE INSERT ON review_decisions
  FOR EACH ROW EXECUTE FUNCTION require_human_review_evidence();

CREATE FUNCTION prevent_human_review_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'human review decisions are immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER review_decisions_immutable_v1
  BEFORE UPDATE OR DELETE ON review_decisions
  FOR EACH ROW EXECUTE FUNCTION prevent_human_review_mutation();
