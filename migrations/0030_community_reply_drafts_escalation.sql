-- Inert, deterministic reply drafts and mandatory safety escalation.

CREATE TABLE community_reply_draft_records (
  request_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  analysis_request_id uuid NOT NULL REFERENCES community_analysis_reports(request_id),
  comment_version_id uuid NOT NULL REFERENCES community_comment_versions(id),
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  target_fingerprint char(64) NOT NULL CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
  analysis_report_fingerprint char(64) NOT NULL
    CHECK (analysis_report_fingerprint ~ '^[0-9a-f]{64}$'),
  classification_fingerprint char(64) NOT NULL
    CHECK (classification_fingerprint ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK (policy_version = 'community-reply-v1'),
  disposition text NOT NULL CHECK (disposition IN (
    'DRAFT_REQUIRES_HUMAN_APPROVAL','ESCALATED_NO_DRAFT',
    'CONTENT_UNAVAILABLE_NO_DRAFT'
  )),
  escalation_priority text NOT NULL CHECK (
    escalation_priority IN ('NONE','HUMAN_REVIEW','URGENT')
  ),
  escalation_reasons text[] NOT NULL DEFAULT '{}' CHECK (
    cardinality(escalation_reasons) <= 10
    AND array_position(escalation_reasons, NULL) IS NULL
  ),
  draft_text text CHECK (
    draft_text IS NULL OR (
      length(draft_text) BETWEEN 1 AND 500
      AND draft_text = btrim(draft_text)
      AND replace(replace(replace(draft_text, E'\n', ''), E'\r', ''), E'\t', '')
        !~ '[[:cntrl:]]'
    )
  ),
  human_approval_required boolean NOT NULL CHECK (human_approval_required = true),
  outbound_action_authorized boolean NOT NULL DEFAULT false
    CHECK (outbound_action_authorized = false),
  created_at timestamptz NOT NULL,
  record_fingerprint char(64) NOT NULL CHECK (record_fingerprint ~ '^[0-9a-f]{64}$'),
  UNIQUE (
    analysis_request_id, comment_version_id, policy_version,
    classification_fingerprint
  ),
  CHECK (
    (disposition = 'DRAFT_REQUIRES_HUMAN_APPROVAL'
      AND draft_text IS NOT NULL AND escalation_priority = 'NONE'
      AND cardinality(escalation_reasons) = 0) OR
    (disposition IN ('ESCALATED_NO_DRAFT','CONTENT_UNAVAILABLE_NO_DRAFT')
      AND draft_text IS NULL AND escalation_priority <> 'NONE'
      AND cardinality(escalation_reasons) > 0)
  )
);

CREATE FUNCTION expected_community_reply_draft(
  theme_value text,
  comment_state_value text,
  safety_category_value text,
  safety_severity_value text,
  safety_rule_values text[],
  requires_review_value boolean
) RETURNS TABLE (
  disposition_value text,
  escalation_priority_value text,
  escalation_reason_values text[],
  draft_text_value text
)
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  reasons text[];
BEGIN
  IF comment_state_value = 'DELETED' OR theme_value = 'CONTENT_UNAVAILABLE' THEN
    RETURN QUERY SELECT 'CONTENT_UNAVAILABLE_NO_DRAFT'::text,
      'HUMAN_REVIEW'::text, ARRAY['content-unavailable']::text[], NULL::text;
    RETURN;
  END IF;
  IF requires_review_value OR safety_category_value <> 'NO_DETECTED_SIGNAL' THEN
    SELECT array_agg(reason ORDER BY reason COLLATE "C") INTO reasons FROM (
      SELECT DISTINCT unnest(array_append(
        safety_rule_values,
        'safety-' || replace(lower(safety_category_value), '_', '-')
      )) AS reason
    ) AS values;
    RETURN QUERY SELECT 'ESCALATED_NO_DRAFT'::text,
      CASE WHEN safety_severity_value = 'CRITICAL' THEN 'URGENT'
           ELSE 'HUMAN_REVIEW' END::text,
      reasons, NULL::text;
    RETURN;
  END IF;
  RETURN QUERY SELECT 'DRAFT_REQUIRES_HUMAN_APPROVAL'::text, 'NONE'::text,
    '{}'::text[], CASE theme_value
      WHEN 'SUPPORT_REQUEST' THEN
        'Thanks for letting us know. A team member will review the issue before responding with next steps.'
      WHEN 'PRICING' THEN
        'Thanks for asking. A team member will verify the current pricing details before responding.'
      WHEN 'FEATURE_REQUEST' THEN
        'Thanks for the suggestion. We have recorded it for human review and consideration.'
      WHEN 'CONTENT_REQUEST' THEN
        'Thanks for the content suggestion. A team member will review it for a future plan.'
      WHEN 'QUESTION' THEN
        'Thanks for your question. A team member will review it and provide an accurate response.'
      WHEN 'PRAISE' THEN
        'Thank you for the kind feedback. We appreciate you taking the time to share it.'
      WHEN 'COMPLAINT' THEN
        'Thanks for sharing this feedback. A team member will review the concern before responding.'
      WHEN 'OTHER' THEN
        'Thanks for your comment. A team member will review it before any response is posted.'
    END;
END;
$$;

CREATE FUNCTION require_community_reply_draft_record() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  current_owner text;
  report_value community_analysis_reports%ROWTYPE;
  classification_value community_comment_classifications%ROWTYPE;
  comment_value community_comment_versions%ROWTYPE;
  expected record;
  expected_request text;
  expected_target text;
  expected_record text;
BEGIN
  SELECT b.owner_user_id INTO current_owner
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    WHERE p.id = NEW.publication_id
    FOR UPDATE OF p;
  SELECT * INTO report_value FROM community_analysis_reports
    WHERE request_id = NEW.analysis_request_id FOR KEY SHARE;
  SELECT * INTO classification_value FROM community_comment_classifications
    WHERE report_request_id = NEW.analysis_request_id
      AND comment_version_id = NEW.comment_version_id
    FOR KEY SHARE;
  SELECT * INTO comment_value FROM community_comment_versions
    WHERE id = NEW.comment_version_id FOR KEY SHARE;
  SELECT * INTO expected FROM expected_community_reply_draft(
    classification_value.theme, comment_value.state,
    classification_value.safety_category, classification_value.safety_severity,
    classification_value.safety_rule_ids,
    classification_value.requires_human_review
  );

  expected_request := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.owner_user_id, NEW.publication_id::text,
    NEW.analysis_request_id::text, NEW.comment_version_id::text,
    NEW.classification_fingerprint, NEW.policy_version,
    to_char(NEW.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');
  expected_target := encode(digest(concat_ws('|',
    NEW.owner_user_id, NEW.publication_id::text, NEW.analysis_request_id::text,
    report_value.report_fingerprint, NEW.comment_version_id::text,
    classification_value.remote_comment_id, comment_value.comment_fingerprint,
    comment_value.state, classification_value.theme, classification_value.theme_rule_id,
    classification_value.safety_category, classification_value.safety_severity,
    array_to_string(classification_value.safety_rule_ids, ','),
    classification_value.requires_human_review::text,
    classification_value.classification_fingerprint
  ), 'sha256'), 'hex');
  expected_record := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.owner_user_id, NEW.publication_id::text,
    NEW.analysis_request_id::text, NEW.comment_version_id::text,
    NEW.request_fingerprint, NEW.target_fingerprint,
    NEW.analysis_report_fingerprint, NEW.classification_fingerprint,
    NEW.policy_version, NEW.disposition, NEW.escalation_priority,
    array_to_string(NEW.escalation_reasons, ','), COALESCE(NEW.draft_text, ''),
    NEW.human_approval_required::text, NEW.outbound_action_authorized::text,
    to_char(NEW.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');

  IF current_owner IS NULL OR report_value.request_id IS NULL
     OR classification_value.report_request_id IS NULL OR comment_value.id IS NULL
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.owner_user_id IS DISTINCT FROM report_value.owner_user_id
     OR NEW.publication_id IS DISTINCT FROM report_value.publication_id
     OR NEW.comment_version_id IS DISTINCT FROM classification_value.comment_version_id
     OR NEW.classification_fingerprint IS DISTINCT FROM
       classification_value.classification_fingerprint
     OR NEW.analysis_report_fingerprint IS DISTINCT FROM report_value.report_fingerprint
     OR NEW.created_at < report_value.created_at
     OR NEW.created_at > clock_timestamp()
     OR NOT EXISTS (
       SELECT 1 FROM community_comments_current AS current
       WHERE current.id = NEW.comment_version_id
         AND current.publication_id = NEW.publication_id
     )
     OR EXISTS (
       SELECT 1 FROM community_analysis_reports AS newer
       WHERE newer.publication_id = NEW.publication_id
         AND (newer.created_at, newer.request_id::text) >
             (report_value.created_at, report_value.request_id::text)
     )
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request
     OR NEW.target_fingerprint IS DISTINCT FROM expected_target
     OR NEW.disposition IS DISTINCT FROM expected.disposition_value
     OR NEW.escalation_priority IS DISTINCT FROM expected.escalation_priority_value
     OR NEW.escalation_reasons IS DISTINCT FROM expected.escalation_reason_values
     OR NEW.draft_text IS DISTINCT FROM expected.draft_text_value
     OR NEW.human_approval_required IS DISTINCT FROM true
     OR NEW.outbound_action_authorized IS DISTINCT FROM false
     OR NEW.record_fingerprint IS DISTINCT FROM expected_record THEN
    RAISE EXCEPTION 'community reply draft evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION guard_community_reply_draft_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'community reply draft evidence is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER community_reply_draft_records_require_evidence
  BEFORE INSERT ON community_reply_draft_records
  FOR EACH ROW EXECUTE FUNCTION require_community_reply_draft_record();
CREATE TRIGGER community_reply_draft_records_prevent_update
  BEFORE UPDATE OR DELETE ON community_reply_draft_records
  FOR EACH ROW EXECUTE FUNCTION guard_community_reply_draft_immutable();

REVOKE ALL ON community_reply_draft_records FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION expected_community_reply_draft(
  text, text, text, text, text[], boolean
) FROM PUBLIC;

COMMENT ON TABLE community_reply_draft_records IS
  'Inert deterministic drafts or escalations requiring human approval; never authority to reply, moderate or publish.';
