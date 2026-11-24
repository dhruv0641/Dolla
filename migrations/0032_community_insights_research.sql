-- Immutable, review-only research proposals derived from exact TASK-068 evidence.
-- This schema grants no browsing, model, provider, account, publishing, spend,
-- moderation, response, or Google Flow authority.

CREATE TABLE community_insight_records (
  request_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK (policy_version = 'community-insight-v1'),
  analysis_request_id uuid NOT NULL REFERENCES community_analysis_reports(request_id),
  analysis_report_fingerprint char(64) NOT NULL CHECK (analysis_report_fingerprint ~ '^[0-9a-f]{64}$'),
  source_snapshot_fingerprint char(64) NOT NULL CHECK (source_snapshot_fingerprint ~ '^[0-9a-f]{64}$'),
  insight_source_fingerprint char(64) NOT NULL CHECK (insight_source_fingerprint ~ '^[0-9a-f]{64}$'),
  proposal_count integer NOT NULL CHECK (proposal_count BETWEEN 0 AND 8),
  requested_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL CHECK (created_at = requested_at),
  record_fingerprint char(64) NOT NULL CHECK (record_fingerprint ~ '^[0-9a-f]{64}$'),
  external_browsing_authorized boolean NOT NULL DEFAULT false CHECK (external_browsing_authorized=false),
  model_execution_authorized boolean NOT NULL DEFAULT false CHECK (model_execution_authorized=false),
  provider_action_authorized boolean NOT NULL DEFAULT false CHECK (provider_action_authorized=false),
  account_action_authorized boolean NOT NULL DEFAULT false CHECK (account_action_authorized=false),
  publishing_authorized boolean NOT NULL DEFAULT false CHECK (publishing_authorized=false),
  spend_authorized boolean NOT NULL DEFAULT false CHECK (spend_authorized=false),
  flow_authorized boolean NOT NULL DEFAULT false CHECK (flow_authorized=false),
  UNIQUE (publication_id, analysis_request_id, policy_version, insight_source_fingerprint)
);

CREATE TABLE community_research_proposals (
  insight_request_id uuid NOT NULL REFERENCES community_insight_records(request_id),
  theme text NOT NULL CHECK (theme IN (
    'SUPPORT_REQUEST','PRICING','FEATURE_REQUEST','CONTENT_REQUEST',
    'QUESTION','PRAISE','COMPLAINT','OTHER'
  )),
  question_key text NOT NULL CHECK (question_key IN (
    'investigate_recurring_product_friction',
    'validate_pricing_clarity_and_objections',
    'assess_requested_capability_demand',
    'assess_requested_content_demand',
    'identify_recurring_knowledge_gaps',
    'identify_retention_and_advocacy_drivers',
    'investigate_recurring_dissatisfaction_causes',
    'review_uncategorized_community_patterns'
  )),
  priority text NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH')),
  member_count integer NOT NULL CHECK (member_count BETWEEN 1 AND 5000),
  review_required_count integer NOT NULL CHECK (review_required_count BETWEEN 0 AND member_count),
  source_cluster_fingerprint char(64) NOT NULL CHECK (source_cluster_fingerprint ~ '^[0-9a-f]{64}$'),
  proposal_fingerprint char(64) NOT NULL CHECK (proposal_fingerprint ~ '^[0-9a-f]{64}$'),
  requires_human_review boolean NOT NULL DEFAULT true CHECK (requires_human_review=true),
  research_execution_authorized boolean NOT NULL DEFAULT false CHECK (research_execution_authorized=false),
  PRIMARY KEY (insight_request_id, theme),
  UNIQUE (insight_request_id, source_cluster_fingerprint),
  UNIQUE (insight_request_id, proposal_fingerprint)
);

CREATE FUNCTION expected_community_research_question(theme_value text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE theme_value
    WHEN 'SUPPORT_REQUEST' THEN 'investigate_recurring_product_friction'
    WHEN 'PRICING' THEN 'validate_pricing_clarity_and_objections'
    WHEN 'FEATURE_REQUEST' THEN 'assess_requested_capability_demand'
    WHEN 'CONTENT_REQUEST' THEN 'assess_requested_content_demand'
    WHEN 'QUESTION' THEN 'identify_recurring_knowledge_gaps'
    WHEN 'PRAISE' THEN 'identify_retention_and_advocacy_drivers'
    WHEN 'COMPLAINT' THEN 'investigate_recurring_dissatisfaction_causes'
    WHEN 'OTHER' THEN 'review_uncategorized_community_patterns'
  END
$$;

CREATE FUNCTION validate_community_insight_record() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  source community_analysis_reports%ROWTYPE;
  latest_id uuid;
  expected_request text;
  expected_source text;
BEGIN
  PERFORM p.id FROM publication_jobs p
    JOIN social_channels ch ON ch.id=p.channel_id
    JOIN brands b ON b.id=ch.brand_id
    WHERE p.id=NEW.publication_id AND b.owner_user_id=NEW.owner_user_id
    FOR UPDATE OF p;
  IF NOT FOUND THEN RAISE EXCEPTION 'owned publication not found'; END IF;

  SELECT r.request_id INTO latest_id FROM community_analysis_reports r
    WHERE r.publication_id=NEW.publication_id
      AND r.owner_user_id=NEW.owner_user_id
      AND r.outbound_action_authorized=false
    ORDER BY r.created_at DESC,r.request_id DESC LIMIT 1;
  IF latest_id IS NULL OR latest_id <> NEW.analysis_request_id THEN
    RAISE EXCEPTION 'community insight must bind latest analysis';
  END IF;
  SELECT * INTO source FROM community_analysis_reports
    WHERE request_id=NEW.analysis_request_id FOR SHARE;
  IF source.owner_user_id <> NEW.owner_user_id
     OR source.publication_id <> NEW.publication_id
     OR source.report_fingerprint <> NEW.analysis_report_fingerprint
     OR source.source_snapshot_fingerprint <> NEW.source_snapshot_fingerprint
     OR source.created_at > NEW.requested_at
     OR NEW.requested_at > clock_timestamp()
     OR source.outbound_action_authorized THEN
    RAISE EXCEPTION 'community insight analysis evidence mismatch';
  END IF;
  expected_request := encode(digest(concat_ws('|', NEW.request_id::text,
    NEW.owner_user_id, NEW.publication_id::text, NEW.policy_version,
    to_char(timezone('UTC',NEW.requested_at),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')),
    'sha256'),'hex');
  SELECT encode(digest(concat_ws('|', source.request_id::text,
    source.report_fingerprint, source.source_snapshot_fingerprint,
    COALESCE(string_agg(c.cluster_fingerprint,',' ORDER BY c.theme COLLATE "C"),'')),
    'sha256'),'hex') INTO expected_source
    FROM community_theme_clusters c WHERE c.report_request_id=source.request_id;
  IF NEW.request_fingerprint <> expected_request
     OR NEW.insight_source_fingerprint <> expected_source
     OR NEW.proposal_count <> source.cluster_count THEN
    RAISE EXCEPTION 'community insight fingerprint or count mismatch';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER community_insight_record_guard
BEFORE INSERT ON community_insight_records
FOR EACH ROW EXECUTE FUNCTION validate_community_insight_record();

CREATE FUNCTION validate_community_research_proposal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  record community_insight_records%ROWTYPE;
  cluster community_theme_clusters%ROWTYPE;
  expected_key text;
  expected_priority text;
  expected_fingerprint text;
BEGIN
  SELECT * INTO record FROM community_insight_records
    WHERE request_id=NEW.insight_request_id FOR SHARE;
  SELECT * INTO cluster FROM community_theme_clusters
    WHERE report_request_id=record.analysis_request_id AND theme=NEW.theme;
  IF NOT FOUND THEN RAISE EXCEPTION 'community theme cluster not found'; END IF;
  expected_key := expected_community_research_question(NEW.theme);
  expected_priority := CASE WHEN cluster.review_required_count > 0 THEN 'HIGH'
    WHEN cluster.member_count >= 3 THEN 'MEDIUM' ELSE 'LOW' END;
  expected_fingerprint := encode(digest(concat_ws('|', NEW.theme, expected_key,
    expected_priority, cluster.member_count::text, cluster.review_required_count::text,
    cluster.cluster_fingerprint, 'true', 'false'),'sha256'),'hex');
  IF NEW.question_key <> expected_key OR NEW.priority <> expected_priority
     OR NEW.member_count <> cluster.member_count
     OR NEW.review_required_count <> cluster.review_required_count
     OR NEW.source_cluster_fingerprint <> cluster.cluster_fingerprint
     OR NEW.proposal_fingerprint <> expected_fingerprint
     OR NOT NEW.requires_human_review OR NEW.research_execution_authorized THEN
    RAISE EXCEPTION 'community research proposal evidence mismatch';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER community_research_proposal_guard
BEFORE INSERT ON community_research_proposals
FOR EACH ROW EXECUTE FUNCTION validate_community_research_proposal();

CREATE FUNCTION validate_complete_community_insight() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  record community_insight_records%ROWTYPE;
  target_id uuid;
  actual_count integer;
  fingerprints text;
  expected_record text;
BEGIN
  IF TG_TABLE_NAME = 'community_research_proposals' THEN
    target_id := NEW.insight_request_id;
  ELSE
    target_id := NEW.request_id;
  END IF;
  SELECT * INTO record FROM community_insight_records
    WHERE request_id=target_id;
  SELECT count(*),COALESCE(string_agg(p.proposal_fingerprint,',' ORDER BY p.theme COLLATE "C"),'')
    INTO actual_count,fingerprints FROM community_research_proposals p
    WHERE p.insight_request_id=record.request_id;
  expected_record := encode(digest(concat_ws('|', record.request_id::text,
    record.owner_user_id, record.publication_id::text, record.request_fingerprint,
    record.policy_version, record.analysis_request_id::text,
    record.analysis_report_fingerprint, record.source_snapshot_fingerprint,
    record.insight_source_fingerprint, fingerprints,
    to_char(timezone('UTC',record.requested_at),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(timezone('UTC',record.created_at),'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'false','false','false','false','false','false','false'),'sha256'),'hex');
  IF actual_count <> record.proposal_count OR expected_record <> record.record_fingerprint THEN
    RAISE EXCEPTION 'community insight is incomplete or fingerprint differs';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER community_insight_complete_from_record
AFTER INSERT ON community_insight_records DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_complete_community_insight();
CREATE CONSTRAINT TRIGGER community_insight_complete_from_proposal
AFTER INSERT ON community_research_proposals DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_complete_community_insight();

CREATE FUNCTION reject_community_insight_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'community insight evidence is immutable';
END $$;
CREATE TRIGGER community_insight_records_immutable
BEFORE UPDATE OR DELETE ON community_insight_records
FOR EACH ROW EXECUTE FUNCTION reject_community_insight_mutation();
CREATE TRIGGER community_research_proposals_immutable
BEFORE UPDATE OR DELETE ON community_research_proposals
FOR EACH ROW EXECUTE FUNCTION reject_community_insight_mutation();

REVOKE ALL ON community_insight_records FROM PUBLIC;
REVOKE ALL ON community_research_proposals FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION expected_community_research_question(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION validate_community_insight_record() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION validate_community_research_proposal() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION validate_complete_community_insight() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION reject_community_insight_mutation() FROM PUBLIC;
