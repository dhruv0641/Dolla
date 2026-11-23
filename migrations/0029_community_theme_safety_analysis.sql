-- Deterministic, immutable theme clustering and safety signals over TASK-067 evidence.

CREATE TABLE community_analysis_reports (
  request_id uuid PRIMARY KEY,
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  ingestion_sync_id uuid NOT NULL REFERENCES comment_ingestion_runs(sync_id),
  ingestion_target_fingerprint char(64) NOT NULL
    CHECK (ingestion_target_fingerprint ~ '^[0-9a-f]{64}$'),
  source_snapshot_fingerprint char(64) NOT NULL
    CHECK (source_snapshot_fingerprint ~ '^[0-9a-f]{64}$'),
  theme_taxonomy_version text NOT NULL
    CHECK (theme_taxonomy_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  safety_policy_version text NOT NULL
    CHECK (safety_policy_version ~ '^[a-z][a-z0-9.-]{0,63}$'),
  status text NOT NULL CHECK (status IN ('EMPTY','CLASSIFIED')),
  total_comment_count integer NOT NULL CHECK (total_comment_count BETWEEN 0 AND 5000),
  analyzed_comment_count integer NOT NULL CHECK (analyzed_comment_count BETWEEN 0 AND 5000),
  deleted_comment_count integer NOT NULL CHECK (deleted_comment_count BETWEEN 0 AND 5000),
  review_required_count integer NOT NULL CHECK (review_required_count BETWEEN 0 AND 5000),
  cluster_count integer NOT NULL CHECK (cluster_count BETWEEN 0 AND 8),
  requested_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL,
  report_fingerprint char(64) NOT NULL CHECK (report_fingerprint ~ '^[0-9a-f]{64}$'),
  outbound_action_authorized boolean NOT NULL DEFAULT false
    CHECK (outbound_action_authorized = false),
  CHECK (analyzed_comment_count + deleted_comment_count = total_comment_count),
  CHECK (review_required_count <= analyzed_comment_count),
  CHECK (created_at >= requested_at),
  CHECK (status = CASE WHEN total_comment_count = 0 THEN 'EMPTY' ELSE 'CLASSIFIED' END),
  UNIQUE (
    publication_id, ingestion_sync_id, theme_taxonomy_version,
    safety_policy_version, source_snapshot_fingerprint
  )
);

CREATE TABLE community_comment_classifications (
  report_request_id uuid NOT NULL REFERENCES community_analysis_reports(request_id),
  comment_version_id uuid NOT NULL REFERENCES community_comment_versions(id),
  remote_comment_id text NOT NULL
    CHECK (remote_comment_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'),
  comment_fingerprint char(64) NOT NULL CHECK (comment_fingerprint ~ '^[0-9a-f]{64}$'),
  theme text NOT NULL CHECK (theme IN (
    'SUPPORT_REQUEST','PRICING','FEATURE_REQUEST','CONTENT_REQUEST',
    'QUESTION','PRAISE','COMPLAINT','OTHER','CONTENT_UNAVAILABLE'
  )),
  theme_rule_id text NOT NULL CHECK (theme_rule_id ~ '^[a-z][a-z0-9._-]{0,79}$'),
  safety_category text NOT NULL CHECK (safety_category IN (
    'NO_DETECTED_SIGNAL','PROMPT_INJECTION','SPAM_OR_SCAM','HARASSMENT',
    'PERSONAL_DATA','SEXUAL_CONTENT','HATE','VIOLENCE','SELF_HARM',
    'CONTENT_UNAVAILABLE'
  )),
  safety_severity text NOT NULL CHECK (
    safety_severity IN ('NONE','LOW','MEDIUM','HIGH','CRITICAL')
  ),
  safety_rule_ids text[] NOT NULL DEFAULT '{}' CHECK (
    cardinality(safety_rule_ids) <= 8
    AND array_position(safety_rule_ids, NULL) IS NULL
  ),
  requires_human_review boolean NOT NULL,
  classification_fingerprint char(64) NOT NULL
    CHECK (classification_fingerprint ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (report_request_id, comment_version_id),
  UNIQUE (report_request_id, remote_comment_id),
  UNIQUE (report_request_id, classification_fingerprint)
);

CREATE TABLE community_theme_clusters (
  report_request_id uuid NOT NULL REFERENCES community_analysis_reports(request_id),
  theme text NOT NULL CHECK (theme IN (
    'SUPPORT_REQUEST','PRICING','FEATURE_REQUEST','CONTENT_REQUEST',
    'QUESTION','PRAISE','COMPLAINT','OTHER'
  )),
  member_count integer NOT NULL CHECK (member_count BETWEEN 1 AND 5000),
  review_required_count integer NOT NULL CHECK (
    review_required_count BETWEEN 0 AND member_count
  ),
  classification_fingerprints char(64)[] NOT NULL CHECK (
    cardinality(classification_fingerprints) = member_count
  ),
  cluster_fingerprint char(64) NOT NULL CHECK (cluster_fingerprint ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (report_request_id, theme),
  UNIQUE (report_request_id, cluster_fingerprint)
);

CREATE FUNCTION expected_community_classification(
  comment_text_value text,
  state_value text
) RETURNS TABLE (
  theme_value text,
  theme_rule_value text,
  safety_category_value text,
  safety_severity_value text,
  safety_rule_values text[],
  requires_review_value boolean
)
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  normalized text;
  matched_rules text[] := '{}';
BEGIN
  IF state_value = 'DELETED' THEN
    RETURN QUERY SELECT
      'CONTENT_UNAVAILABLE'::text, 'theme.content_unavailable'::text,
      'CONTENT_UNAVAILABLE'::text, 'NONE'::text, '{}'::text[], false;
    RETURN;
  END IF;

  normalized := ' ' || btrim(regexp_replace(translate(comment_text_value,
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),
    E'[ \\t\\r\\n]+', ' ', 'g')) || ' ';
  IF normalized LIKE ANY (ARRAY['% help%','%not working%','% issue%','% problem%','% error%']) THEN
    theme_value := 'SUPPORT_REQUEST'; theme_rule_value := 'theme.support';
  ELSIF normalized LIKE ANY (ARRAY['% price%','% pricing%','% cost%','% subscription%']) THEN
    theme_value := 'PRICING'; theme_rule_value := 'theme.pricing';
  ELSIF normalized LIKE ANY (ARRAY['% feature%','%please add%','%would love%','%can you add%']) THEN
    theme_value := 'FEATURE_REQUEST'; theme_rule_value := 'theme.feature_request';
  ELSIF normalized LIKE ANY (ARRAY['%make a video%','%cover this%','% tutorial%','%next topic%']) THEN
    theme_value := 'CONTENT_REQUEST'; theme_rule_value := 'theme.content_request';
  ELSIF normalized LIKE ANY (ARRAY['% love%','% great%','% amazing%','% thank%','% awesome%']) THEN
    theme_value := 'PRAISE'; theme_rule_value := 'theme.praise';
  ELSIF normalized LIKE ANY (ARRAY['% awful%','% disappointing%','% terrible%','% hate%']) THEN
    theme_value := 'COMPLAINT'; theme_rule_value := 'theme.complaint';
  ELSIF position('?' IN comment_text_value) > 0
     OR normalized ~ '^ (who|what|when|where|why|how|can|does|is) ' THEN
    theme_value := 'QUESTION'; theme_rule_value := 'theme.question';
  ELSE
    theme_value := 'OTHER'; theme_rule_value := 'theme.other';
  END IF;

  IF normalized LIKE ANY (ARRAY[
    '%ignore previous instructions%','%reveal system prompt%','%developer message%'
  ]) THEN matched_rules := array_append(matched_rules, 'safety.prompt_injection'); END IF;
  IF normalized LIKE ANY (ARRAY[
    '%guaranteed profit%','%crypto giveaway%','%contact me on whatsapp%',
    '%contact me on telegram%'
  ]) THEN matched_rules := array_append(matched_rules, 'safety.spam_scam'); END IF;
  IF normalized LIKE ANY (ARRAY['%you are stupid%','% idiot%','% loser%']) THEN
    matched_rules := array_append(matched_rules, 'safety.harassment');
  END IF;
  IF normalized LIKE ANY (ARRAY['%explicit sexual%','%send nudes%','% porn%']) THEN
    matched_rules := array_append(matched_rules, 'safety.sexual');
  END IF;
  IF normalized LIKE ANY (ARRAY['%hate speech%','%racial slur%']) THEN
    matched_rules := array_append(matched_rules, 'safety.hate');
  END IF;
  IF normalized LIKE ANY (ARRAY['%kill you%','%hurt you%','%shoot you%','%bomb threat%']) THEN
    matched_rules := array_append(matched_rules, 'safety.violence');
  END IF;
  IF normalized LIKE ANY (ARRAY['%kill myself%','%end my life%','%self harm%','%suicide%']) THEN
    matched_rules := array_append(matched_rules, 'safety.self_harm');
  END IF;
  IF comment_text_value ~ '\m[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\M'
     OR comment_text_value ~ '(^|[^0-9])(\+?[0-9][ .()-]?){8,15}([^0-9]|$)' THEN
    matched_rules := array_append(matched_rules, 'safety.personal_data');
  END IF;
  SELECT COALESCE(array_agg(rule_id ORDER BY rule_id COLLATE "C"), '{}') INTO matched_rules
    FROM (SELECT DISTINCT unnest(matched_rules) AS rule_id) AS rules;

  IF 'safety.violence' = ANY(matched_rules) THEN
    safety_category_value := 'VIOLENCE'; safety_severity_value := 'CRITICAL';
  ELSIF 'safety.self_harm' = ANY(matched_rules) THEN
    safety_category_value := 'SELF_HARM'; safety_severity_value := 'CRITICAL';
  ELSIF 'safety.sexual' = ANY(matched_rules) THEN
    safety_category_value := 'SEXUAL_CONTENT'; safety_severity_value := 'HIGH';
  ELSIF 'safety.personal_data' = ANY(matched_rules) THEN
    safety_category_value := 'PERSONAL_DATA'; safety_severity_value := 'HIGH';
  ELSIF 'safety.hate' = ANY(matched_rules) THEN
    safety_category_value := 'HATE'; safety_severity_value := 'HIGH';
  ELSIF 'safety.spam_scam' = ANY(matched_rules) THEN
    safety_category_value := 'SPAM_OR_SCAM'; safety_severity_value := 'MEDIUM';
  ELSIF 'safety.prompt_injection' = ANY(matched_rules) THEN
    safety_category_value := 'PROMPT_INJECTION'; safety_severity_value := 'MEDIUM';
  ELSIF 'safety.harassment' = ANY(matched_rules) THEN
    safety_category_value := 'HARASSMENT'; safety_severity_value := 'MEDIUM';
  ELSE
    safety_category_value := 'NO_DETECTED_SIGNAL'; safety_severity_value := 'NONE';
  END IF;
  safety_rule_values := matched_rules;
  requires_review_value := cardinality(matched_rules) > 0;
  RETURN NEXT;
END;
$$;

CREATE FUNCTION require_community_analysis_report() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  run_value comment_ingestion_runs%ROWTYPE;
  current_owner text;
  current_total integer;
  current_deleted integer;
  current_snapshot text;
  expected_request text;
  expected_report text;
BEGIN
  SELECT r.* INTO run_value
    FROM comment_ingestion_runs AS r
    WHERE r.publication_id = NEW.publication_id
    ORDER BY r.created_at DESC, r.sync_id DESC
    LIMIT 1 FOR KEY SHARE;
  SELECT b.owner_user_id INTO current_owner
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    WHERE p.id = NEW.publication_id
    FOR KEY SHARE OF p;
  SELECT count(*), count(*) FILTER (WHERE state = 'DELETED'),
         encode(digest(concat_ws('|', NEW.ingestion_sync_id::text,
           NEW.ingestion_target_fingerprint,
           COALESCE(string_agg(id::text || ':' || comment_fingerprint, ','
             ORDER BY remote_comment_id COLLATE "C"), '')), 'sha256'), 'hex')
    INTO current_total, current_deleted, current_snapshot
    FROM community_comments_current
    WHERE publication_id = NEW.publication_id;

  expected_request := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.owner_user_id, NEW.publication_id::text,
    NEW.theme_taxonomy_version, NEW.safety_policy_version,
    to_char(NEW.requested_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');
  expected_report := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.owner_user_id, NEW.publication_id::text,
    NEW.request_fingerprint, NEW.ingestion_sync_id::text,
    NEW.ingestion_target_fingerprint, NEW.source_snapshot_fingerprint,
    NEW.theme_taxonomy_version, NEW.safety_policy_version, NEW.status,
    NEW.total_comment_count::text, NEW.analyzed_comment_count::text,
    NEW.deleted_comment_count::text, NEW.review_required_count::text,
    NEW.cluster_count::text,
    to_char(NEW.requested_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(NEW.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    NEW.outbound_action_authorized::text
  ), 'sha256'), 'hex');

  IF run_value.sync_id IS NULL OR run_value.status <> 'COMPLETE'
     OR NEW.ingestion_sync_id IS DISTINCT FROM run_value.sync_id
     OR NEW.ingestion_target_fingerprint IS DISTINCT FROM run_value.target_fingerprint
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.owner_user_id IS DISTINCT FROM run_value.owner_user_id
     OR NEW.requested_at < run_value.updated_at
     OR NEW.theme_taxonomy_version <> 'community-theme-v1'
     OR NEW.safety_policy_version <> 'community-safety-v1'
     OR NEW.total_comment_count IS DISTINCT FROM current_total
     OR NEW.deleted_comment_count IS DISTINCT FROM current_deleted
     OR NEW.analyzed_comment_count IS DISTINCT FROM current_total - current_deleted
     OR NEW.source_snapshot_fingerprint IS DISTINCT FROM current_snapshot
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request
     OR NEW.report_fingerprint IS DISTINCT FROM expected_report
     OR NEW.outbound_action_authorized THEN
    RAISE EXCEPTION 'community analysis report evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION require_community_comment_classification() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  report_value community_analysis_reports%ROWTYPE;
  comment_value community_comment_versions%ROWTYPE;
  expected record;
  expected_fingerprint text;
BEGIN
  SELECT * INTO report_value FROM community_analysis_reports
    WHERE request_id = NEW.report_request_id FOR KEY SHARE;
  SELECT * INTO comment_value FROM community_comment_versions
    WHERE id = NEW.comment_version_id FOR KEY SHARE;
  SELECT * INTO expected FROM expected_community_classification(
    comment_value.comment_text, comment_value.state
  );
  expected_fingerprint := encode(digest(concat_ws('|',
    NEW.comment_version_id::text, NEW.comment_fingerprint,
    NEW.theme, NEW.theme_rule_id, NEW.safety_category, NEW.safety_severity,
    array_to_string(NEW.safety_rule_ids, ','), NEW.requires_human_review::text
  ), 'sha256'), 'hex');

  IF report_value.request_id IS NULL OR comment_value.id IS NULL
     OR comment_value.publication_id IS DISTINCT FROM report_value.publication_id
     OR comment_value.owner_user_id IS DISTINCT FROM report_value.owner_user_id
     OR NOT EXISTS (
       SELECT 1 FROM community_comments_current AS current
       WHERE current.id = comment_value.id
         AND current.publication_id = report_value.publication_id
     )
     OR NEW.remote_comment_id IS DISTINCT FROM comment_value.remote_comment_id
     OR NEW.comment_fingerprint IS DISTINCT FROM comment_value.comment_fingerprint
     OR NEW.theme IS DISTINCT FROM expected.theme_value
     OR NEW.theme_rule_id IS DISTINCT FROM expected.theme_rule_value
     OR NEW.safety_category IS DISTINCT FROM expected.safety_category_value
     OR NEW.safety_severity IS DISTINCT FROM expected.safety_severity_value
     OR NEW.safety_rule_ids IS DISTINCT FROM expected.safety_rule_values
     OR NEW.requires_human_review IS DISTINCT FROM expected.requires_review_value
     OR NEW.classification_fingerprint IS DISTINCT FROM expected_fingerprint THEN
    RAISE EXCEPTION 'community comment classification evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION require_community_theme_cluster() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  actual_members integer;
  actual_reviews integer;
  actual_fingerprints char(64)[];
  expected_fingerprint text;
BEGIN
  SELECT count(*), count(*) FILTER (WHERE requires_human_review),
         array_agg(classification_fingerprint ORDER BY classification_fingerprint COLLATE "C")
    INTO actual_members, actual_reviews, actual_fingerprints
    FROM community_comment_classifications
    WHERE report_request_id = NEW.report_request_id AND theme = NEW.theme;
  expected_fingerprint := encode(digest(concat_ws('|',
    NEW.report_request_id::text, NEW.theme, NEW.member_count::text,
    NEW.review_required_count::text,
    array_to_string(NEW.classification_fingerprints, ',')
  ), 'sha256'), 'hex');
  IF NEW.member_count IS DISTINCT FROM actual_members
     OR NEW.review_required_count IS DISTINCT FROM actual_reviews
     OR NEW.classification_fingerprints IS DISTINCT FROM actual_fingerprints
     OR NEW.cluster_fingerprint IS DISTINCT FROM expected_fingerprint THEN
    RAISE EXCEPTION 'community theme cluster evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION verify_community_analysis_completion() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  classification_count integer;
  deleted_count integer;
  review_count integer;
  cluster_count_value integer;
  cluster_members integer;
BEGIN
  SELECT count(*), count(*) FILTER (WHERE theme = 'CONTENT_UNAVAILABLE'),
         count(*) FILTER (WHERE requires_human_review)
    INTO classification_count, deleted_count, review_count
    FROM community_comment_classifications
    WHERE report_request_id = NEW.request_id;
  SELECT count(*), COALESCE(sum(member_count), 0)
    INTO cluster_count_value, cluster_members
    FROM community_theme_clusters WHERE report_request_id = NEW.request_id;
  IF classification_count IS DISTINCT FROM NEW.total_comment_count
     OR deleted_count IS DISTINCT FROM NEW.deleted_comment_count
     OR review_count IS DISTINCT FROM NEW.review_required_count
     OR cluster_count_value IS DISTINCT FROM NEW.cluster_count
     OR cluster_members IS DISTINCT FROM NEW.analyzed_comment_count
     OR EXISTS (
       SELECT 1 FROM community_comments_current AS current
       WHERE current.publication_id = NEW.publication_id
         AND NOT EXISTS (
           SELECT 1 FROM community_comment_classifications AS item
           WHERE item.report_request_id = NEW.request_id
             AND item.comment_version_id = current.id
         )
     ) THEN
    RAISE EXCEPTION 'community analysis evidence is incomplete at commit'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END;
$$;

CREATE FUNCTION guard_community_analysis_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'community analysis evidence is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER community_analysis_reports_require_evidence
  BEFORE INSERT ON community_analysis_reports
  FOR EACH ROW EXECUTE FUNCTION require_community_analysis_report();
CREATE TRIGGER community_comment_classifications_require_evidence
  BEFORE INSERT ON community_comment_classifications
  FOR EACH ROW EXECUTE FUNCTION require_community_comment_classification();
CREATE TRIGGER community_theme_clusters_require_evidence
  BEFORE INSERT ON community_theme_clusters
  FOR EACH ROW EXECUTE FUNCTION require_community_theme_cluster();
CREATE CONSTRAINT TRIGGER community_analysis_reports_verify_completion
  AFTER INSERT ON community_analysis_reports
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION verify_community_analysis_completion();

CREATE TRIGGER community_analysis_reports_prevent_update
  BEFORE UPDATE OR DELETE ON community_analysis_reports
  FOR EACH ROW EXECUTE FUNCTION guard_community_analysis_immutable();
CREATE TRIGGER community_comment_classifications_prevent_update
  BEFORE UPDATE OR DELETE ON community_comment_classifications
  FOR EACH ROW EXECUTE FUNCTION guard_community_analysis_immutable();
CREATE TRIGGER community_theme_clusters_prevent_update
  BEFORE UPDATE OR DELETE ON community_theme_clusters
  FOR EACH ROW EXECUTE FUNCTION guard_community_analysis_immutable();

REVOKE ALL ON community_analysis_reports FROM PUBLIC;
REVOKE ALL ON community_comment_classifications FROM PUBLIC;
REVOKE ALL ON community_theme_clusters FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION expected_community_classification(text, text) FROM PUBLIC;

COMMENT ON TABLE community_analysis_reports IS
  'Immutable local heuristic analysis; NO_DETECTED_SIGNAL is not a safety guarantee and no outbound action is authorized.';
