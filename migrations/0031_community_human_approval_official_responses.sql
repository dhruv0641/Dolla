-- Exact human approval and disabled-by-default official community responses.

CREATE TABLE community_response_approvals (
  approval_id uuid PRIMARY KEY,
  draft_request_id uuid NOT NULL UNIQUE REFERENCES community_reply_draft_records(request_id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  reviewer_user_id text NOT NULL
    CHECK (reviewer_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  reviewer_role text NOT NULL CHECK (reviewer_role IN ('admin','reviewer')),
  decision text NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
  reason text NOT NULL CHECK (
    length(reason) BETWEEN 1 AND 1000 AND reason = btrim(reason)
    AND replace(replace(replace(reason, E'\n', ''), E'\r', ''), E'\t', '')
      !~ '[[:cntrl:]]'
    AND reason !~* '(password|secret|token|credential|api[_-]?key|authorization|cookie)[[:space:]]*[:=][[:space:]]*[^[:space:]]+'
  ),
  decided_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  draft_fingerprint char(64) NOT NULL CHECK (draft_fingerprint ~ '^[0-9a-f]{64}$'),
  draft_text_fingerprint char(64) NOT NULL
    CHECK (draft_text_fingerprint ~ '^[0-9a-f]{64}$'),
  record_fingerprint char(64) NOT NULL CHECK (record_fingerprint ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (valid_until > decided_at AND valid_until <= decided_at + interval '24 hours')
);

CREATE FUNCTION require_community_response_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  draft community_reply_draft_records%ROWTYPE;
  current_comment community_comment_versions%ROWTYPE;
  expected_request text;
  expected_draft text;
  expected_text text;
  expected_record text;
BEGIN
  SELECT * INTO draft FROM community_reply_draft_records
    WHERE request_id = NEW.draft_request_id FOR KEY SHARE;
  IF draft.request_id IS NULL THEN
    RAISE EXCEPTION 'response approval draft is unavailable'
      USING ERRCODE = 'check_violation';
  END IF;
  PERFORM p.id FROM publication_jobs AS p
    WHERE p.id = draft.publication_id FOR UPDATE;
  SELECT * INTO current_comment FROM community_comments_current
    WHERE id = draft.comment_version_id;

  expected_request := encode(digest(concat_ws('|',
    NEW.approval_id::text, NEW.draft_request_id::text, NEW.owner_user_id,
    NEW.reviewer_user_id, NEW.reviewer_role, NEW.decision, NEW.reason,
    to_char(NEW.decided_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    to_char(NEW.valid_until AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');
  expected_text := encode(digest(COALESCE(draft.draft_text, ''), 'sha256'), 'hex');
  expected_draft := encode(digest(concat_ws('|',
    draft.request_id::text, draft.owner_user_id, draft.publication_id::text,
    draft.comment_version_id::text, draft.record_fingerprint,
    draft.classification_fingerprint, draft.disposition, expected_text,
    array_to_string(draft.escalation_reasons, ','),
    draft.outbound_action_authorized::text,
    current_comment.platform, current_comment.destination_id,
    current_comment.remote_object_id, current_comment.remote_comment_id,
    current_comment.state
  ), 'sha256'), 'hex');
  expected_record := encode(digest(concat_ws('|',
    expected_request, expected_draft, expected_text
  ), 'sha256'), 'hex');

  IF NEW.owner_user_id IS DISTINCT FROM draft.owner_user_id
     OR current_comment.id IS NULL
     OR NEW.decided_at < draft.created_at
     OR NEW.decided_at > clock_timestamp()
     OR NEW.valid_until <= clock_timestamp()
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request
     OR NEW.draft_text_fingerprint IS DISTINCT FROM expected_text
     OR NEW.draft_fingerprint IS DISTINCT FROM expected_draft
     OR NEW.record_fingerprint IS DISTINCT FROM expected_record
     OR (NEW.decision = 'APPROVE' AND (
       draft.disposition <> 'DRAFT_REQUIRES_HUMAN_APPROVAL'
       OR draft.draft_text IS NULL
       OR cardinality(draft.escalation_reasons) <> 0
       OR draft.outbound_action_authorized
       OR current_comment.state = 'DELETED'
     ))
     OR EXISTS (
       SELECT 1 FROM community_analysis_reports AS newer
       WHERE newer.publication_id = draft.publication_id
         AND (newer.created_at, newer.request_id::text) >
             ((SELECT created_at FROM community_analysis_reports
               WHERE request_id = draft.analysis_request_id), draft.analysis_request_id::text)
     ) THEN
    RAISE EXCEPTION 'response approval evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION lock_community_response_publication(publication_id_value uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  locked_id uuid;
BEGIN
  SELECT id INTO locked_id FROM public.publication_jobs
    WHERE id = publication_id_value FOR UPDATE;
  RETURN locked_id IS NOT NULL;
END;
$$;

REVOKE EXECUTE ON FUNCTION lock_community_response_publication(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lock_community_response_publication(uuid)
  TO flowx_community_approval_writer, flowx_community_response_runtime;

CREATE FUNCTION guard_community_response_approval_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'response approval is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER community_response_approvals_require_evidence
  BEFORE INSERT ON community_response_approvals
  FOR EACH ROW EXECUTE FUNCTION require_community_response_approval();
CREATE TRIGGER community_response_approvals_prevent_mutation
  BEFORE UPDATE OR DELETE ON community_response_approvals
  FOR EACH ROW EXECUTE FUNCTION guard_community_response_approval_immutable();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'flowx_community_approval_writer'
  ) THEN
    CREATE ROLE flowx_community_approval_writer
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'flowx_community_response_runtime'
  ) THEN
    CREATE ROLE flowx_community_response_runtime
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END;
$$;

CREATE FUNCTION record_community_response_approval(
  approval_id_value uuid,
  draft_request_id_value uuid,
  owner_user_id_value text,
  reviewer_user_id_value text,
  reviewer_role_value text,
  decision_value text,
  reason_value text,
  decided_at_value timestamptz,
  valid_until_value timestamptz,
  request_fingerprint_value char(64),
  draft_fingerprint_value char(64),
  draft_text_fingerprint_value char(64),
  record_fingerprint_value char(64)
) RETURNS SETOF community_response_approvals
LANGUAGE sql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  INSERT INTO public.community_response_approvals (
    approval_id, draft_request_id, owner_user_id, reviewer_user_id,
    reviewer_role, decision, reason, decided_at, valid_until,
    request_fingerprint, draft_fingerprint, draft_text_fingerprint,
    record_fingerprint
  ) VALUES (
    approval_id_value, draft_request_id_value, owner_user_id_value,
    reviewer_user_id_value, reviewer_role_value, decision_value, reason_value,
    decided_at_value, valid_until_value, request_fingerprint_value,
    draft_fingerprint_value, draft_text_fingerprint_value,
    record_fingerprint_value
  )
  ON CONFLICT DO NOTHING
  RETURNING *;
$$;

REVOKE ALL ON community_response_approvals FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION record_community_response_approval(
  uuid, uuid, text, text, text, text, text, timestamptz, timestamptz,
  char(64), char(64), char(64), char(64)
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION record_community_response_approval(
  uuid, uuid, text, text, text, text, text, timestamptz, timestamptz,
  char(64), char(64), char(64), char(64)
) TO flowx_community_approval_writer;

CREATE TABLE community_official_responses (
  request_id uuid PRIMARY KEY,
  approval_id uuid NOT NULL UNIQUE REFERENCES community_response_approvals(approval_id),
  owner_user_id text NOT NULL
    CHECK (owner_user_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$'),
  request_fingerprint char(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
  approval_fingerprint char(64) NOT NULL CHECK (approval_fingerprint ~ '^[0-9a-f]{64}$'),
  draft_fingerprint char(64) NOT NULL CHECK (draft_fingerprint ~ '^[0-9a-f]{64}$'),
  draft_text text NOT NULL CHECK (
    length(draft_text) BETWEEN 1 AND 500 AND draft_text = btrim(draft_text)
    AND replace(replace(replace(draft_text, E'\n', ''), E'\r', ''), E'\t', '')
      !~ '[[:cntrl:]]'
  ),
  draft_text_fingerprint char(64) NOT NULL
    CHECK (draft_text_fingerprint ~ '^[0-9a-f]{64}$'),
  publication_id uuid NOT NULL REFERENCES publication_jobs(id),
  comment_version_id uuid NOT NULL REFERENCES community_comment_versions(id),
  platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
  destination_id text NOT NULL
    CHECK (destination_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'),
  credentials_ref text NOT NULL
    CHECK (credentials_ref ~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'),
  remote_object_id text NOT NULL
    CHECK (remote_object_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'),
  remote_comment_id text NOT NULL
    CHECK (remote_comment_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'),
  state text NOT NULL DEFAULT 'DRAFT' CHECK (state IN (
    'DRAFT','MUTATION_RESERVED','VERIFY_PENDING','RESPONDED','FAILED'
  )),
  authorization_fingerprint char(64)
    CHECK (authorization_fingerprint IS NULL OR authorization_fingerprint ~ '^[0-9a-f]{64}$'),
  authorization_scopes text[] NOT NULL DEFAULT '{}',
  authorization_checked_at timestamptz,
  authorization_valid_until timestamptz,
  remote_response_id text CHECK (
    remote_response_id IS NULL OR
    remote_response_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'
  ),
  receipt_state text CHECK (receipt_state IS NULL OR receipt_state IN ('ACCEPTED','UNKNOWN')),
  receipt_fingerprint char(64)
    CHECK (receipt_fingerprint IS NULL OR receipt_fingerprint ~ '^[0-9a-f]{64}$'),
  recovery_evidence_id text CHECK (
    recovery_evidence_id IS NULL OR
    recovery_evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'
  ),
  identity_recovered_at timestamptz,
  verification_evidence_id text CHECK (
    verification_evidence_id IS NULL OR
    verification_evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'
  ),
  verification_observed_at timestamptz,
  verification_fingerprint char(64)
    CHECK (verification_fingerprint IS NULL OR verification_fingerprint ~ '^[0-9a-f]{64}$'),
  verification_platform text CHECK (
    verification_platform IS NULL OR verification_platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')
  ),
  verification_destination_id text,
  verification_remote_object_id text,
  verification_parent_comment_id text,
  verification_text_fingerprint char(64) CHECK (
    verification_text_fingerprint IS NULL OR verification_text_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  verification_visible boolean,
  error_code text CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
  requested_at timestamptz NOT NULL,
  mutation_reserved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    (authorization_fingerprint IS NULL AND cardinality(authorization_scopes) = 0
      AND authorization_checked_at IS NULL AND authorization_valid_until IS NULL) OR
    (authorization_fingerprint IS NOT NULL AND cardinality(authorization_scopes) > 0
      AND authorization_checked_at IS NOT NULL AND authorization_valid_until IS NOT NULL
      AND authorization_valid_until > authorization_checked_at)
  ),
  CHECK ((recovery_evidence_id IS NULL) = (identity_recovered_at IS NULL)),
  CHECK ((state = 'DRAFT') = (mutation_reserved_at IS NULL)),
  CHECK ((state = 'RESPONDED') =
    (remote_response_id IS NOT NULL AND verification_evidence_id IS NOT NULL
     AND verification_observed_at IS NOT NULL AND verification_fingerprint IS NOT NULL
     AND verification_platform IS NOT NULL AND verification_destination_id IS NOT NULL
     AND verification_remote_object_id IS NOT NULL
     AND verification_parent_comment_id IS NOT NULL
     AND verification_text_fingerprint IS NOT NULL
     AND verification_visible IS NOT NULL))
);

CREATE FUNCTION require_community_official_response_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  approval community_response_approvals%ROWTYPE;
  draft community_reply_draft_records%ROWTYPE;
  comment_value community_comment_versions%ROWTYPE;
  channel_value social_channels%ROWTYPE;
  publication_status text;
  current_owner text;
  expected_request text;
BEGIN
  SELECT * INTO approval FROM community_response_approvals
    WHERE approval_id = NEW.approval_id FOR KEY SHARE;
  SELECT * INTO draft FROM community_reply_draft_records
    WHERE request_id = approval.draft_request_id FOR KEY SHARE;
  PERFORM p.id FROM publication_jobs AS p
    WHERE p.id = draft.publication_id FOR UPDATE;
  SELECT * INTO comment_value FROM community_comments_current
    WHERE id = draft.comment_version_id;
  SELECT p.status, ch, b.owner_user_id
    INTO publication_status, channel_value, current_owner
    FROM publication_jobs AS p
    JOIN social_channels AS ch ON ch.id = p.channel_id
    JOIN brands AS b ON b.id = ch.brand_id
    WHERE p.id = draft.publication_id;
  expected_request := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.approval_id::text, NEW.owner_user_id,
    to_char(NEW.requested_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
  ), 'sha256'), 'hex');
  IF approval.approval_id IS NULL OR approval.decision <> 'APPROVE'
     OR approval.valid_until <= clock_timestamp()
     OR NEW.owner_user_id IS DISTINCT FROM approval.owner_user_id
     OR NEW.owner_user_id IS DISTINCT FROM current_owner
     OR NEW.request_fingerprint IS DISTINCT FROM expected_request
     OR NEW.approval_fingerprint IS DISTINCT FROM approval.record_fingerprint
     OR NEW.draft_fingerprint IS DISTINCT FROM approval.draft_fingerprint
     OR NEW.draft_text IS DISTINCT FROM draft.draft_text
     OR NEW.draft_text_fingerprint IS DISTINCT FROM approval.draft_text_fingerprint
     OR NEW.draft_text_fingerprint IS DISTINCT FROM encode(digest(NEW.draft_text, 'sha256'), 'hex')
     OR NEW.publication_id IS DISTINCT FROM draft.publication_id
     OR NEW.comment_version_id IS DISTINCT FROM draft.comment_version_id
     OR comment_value.id IS NULL OR comment_value.state = 'DELETED'
     OR NEW.platform IS DISTINCT FROM comment_value.platform
     OR NEW.destination_id IS DISTINCT FROM comment_value.destination_id
     OR NEW.remote_object_id IS DISTINCT FROM comment_value.remote_object_id
     OR NEW.remote_comment_id IS DISTINCT FROM comment_value.remote_comment_id
     OR NEW.credentials_ref IS DISTINCT FROM channel_value.credentials_ref
     OR NEW.destination_id IS DISTINCT FROM channel_value.external_channel_id
     OR channel_value.enabled IS DISTINCT FROM true
     OR channel_value.permissions_status <> 'VALID'
     OR publication_status <> 'PUBLISHED'
     OR EXISTS (
       SELECT 1 FROM community_analysis_reports AS newer
       WHERE newer.publication_id = draft.publication_id
         AND (newer.created_at, newer.request_id::text) >
             ((SELECT created_at FROM community_analysis_reports
               WHERE request_id = draft.analysis_request_id), draft.analysis_request_id::text)
     )
     OR NEW.state <> 'DRAFT'
     OR NEW.authorization_fingerprint IS NOT NULL
     OR NEW.remote_response_id IS NOT NULL
     OR NEW.receipt_state IS NOT NULL OR NEW.receipt_fingerprint IS NOT NULL
     OR NEW.recovery_evidence_id IS NOT NULL OR NEW.identity_recovered_at IS NOT NULL
     OR NEW.verification_evidence_id IS NOT NULL
     OR NEW.verification_observed_at IS NOT NULL
     OR NEW.verification_fingerprint IS NOT NULL
     OR NEW.verification_platform IS NOT NULL
     OR NEW.verification_destination_id IS NOT NULL
     OR NEW.verification_remote_object_id IS NOT NULL
     OR NEW.verification_parent_comment_id IS NOT NULL
     OR NEW.verification_text_fingerprint IS NOT NULL
     OR NEW.verification_visible IS NOT NULL OR NEW.error_code IS NOT NULL
     OR NEW.requested_at < approval.decided_at
     OR NEW.requested_at > clock_timestamp() THEN
    RAISE EXCEPTION 'official response claim evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION guard_community_official_response_update() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  network_ready boolean;
  expected_authorization text;
  expected_receipt text;
  expected_verification text;
BEGIN
  IF (NEW.request_id, NEW.approval_id, NEW.owner_user_id,
      NEW.request_fingerprint, NEW.approval_fingerprint,
      NEW.draft_fingerprint, NEW.draft_text, NEW.draft_text_fingerprint,
      NEW.publication_id, NEW.comment_version_id, NEW.platform,
      NEW.destination_id, NEW.credentials_ref, NEW.remote_object_id,
      NEW.remote_comment_id, NEW.requested_at, NEW.created_at)
     IS DISTINCT FROM
     (OLD.request_id, OLD.approval_id, OLD.owner_user_id,
      OLD.request_fingerprint, OLD.approval_fingerprint,
      OLD.draft_fingerprint, OLD.draft_text, OLD.draft_text_fingerprint,
      OLD.publication_id, OLD.comment_version_id, OLD.platform,
      OLD.destination_id, OLD.credentials_ref, OLD.remote_object_id,
      OLD.remote_comment_id, OLD.requested_at, OLD.created_at)
     OR OLD.state IN ('RESPONDED','FAILED') THEN
    RAISE EXCEPTION 'official response identity is immutable'
      USING ERRCODE = 'check_violation';
  END IF;

  IF OLD.state = 'DRAFT' AND NEW.state = 'MUTATION_RESERVED' THEN
    PERFORM p.id FROM publication_jobs AS p
      WHERE p.id = NEW.publication_id FOR UPDATE;
    SELECT true INTO network_ready
      FROM community_response_approvals AS a
      JOIN community_reply_draft_records AS d ON d.request_id = a.draft_request_id
      JOIN community_comments_current AS c ON c.id = d.comment_version_id
      JOIN publication_jobs AS p ON p.id = d.publication_id
      JOIN social_channels AS ch ON ch.id = p.channel_id
      JOIN brands AS b ON b.id = ch.brand_id
      WHERE a.approval_id = NEW.approval_id AND a.decision = 'APPROVE'
        AND a.valid_until > clock_timestamp()
        AND a.record_fingerprint = NEW.approval_fingerprint
        AND d.record_fingerprint = NEW.draft_fingerprint
        AND d.draft_text = NEW.draft_text AND c.id = NEW.comment_version_id
        AND c.state <> 'DELETED' AND c.platform = NEW.platform
        AND c.destination_id = NEW.destination_id
        AND c.remote_object_id = NEW.remote_object_id
        AND c.remote_comment_id = NEW.remote_comment_id
        AND p.id = NEW.publication_id AND p.status = 'PUBLISHED'
        AND ch.enabled AND ch.permissions_status = 'VALID'
        AND ch.external_channel_id = NEW.destination_id
        AND ch.credentials_ref = NEW.credentials_ref
        AND b.owner_user_id = NEW.owner_user_id
        AND NOT EXISTS (
          SELECT 1 FROM community_analysis_reports AS newer
          WHERE newer.publication_id = d.publication_id
            AND (newer.created_at, newer.request_id::text) >
                ((SELECT created_at FROM community_analysis_reports
                  WHERE request_id = d.analysis_request_id), d.analysis_request_id::text)
        )
      ;
    expected_authorization := encode(digest(concat_ws('|',
      NEW.platform, NEW.destination_id,
      array_to_string(NEW.authorization_scopes, ','),
      to_char(NEW.authorization_checked_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      to_char(NEW.authorization_valid_until AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    ), 'sha256'), 'hex');
    IF NEW.mutation_reserved_at IS NULL
       OR network_ready IS DISTINCT FROM true
       OR NEW.authorization_fingerprint IS NULL
       OR NEW.authorization_fingerprint IS DISTINCT FROM expected_authorization
       OR cardinality(NEW.authorization_scopes) = 0
       OR array_position(NEW.authorization_scopes, NULL) IS NOT NULL
       OR EXISTS (
         SELECT 1 FROM unnest(NEW.authorization_scopes) AS scope_value
         WHERE scope_value !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'
       )
       OR NEW.authorization_scopes IS DISTINCT FROM ARRAY(
         SELECT DISTINCT scope_value
         FROM unnest(NEW.authorization_scopes) AS scope_value
         ORDER BY scope_value COLLATE "C"
       )
       OR NEW.authorization_checked_at > NEW.mutation_reserved_at
       OR NEW.authorization_checked_at < NEW.mutation_reserved_at - interval '300 seconds'
       OR NEW.authorization_valid_until < NEW.mutation_reserved_at + interval '30 seconds'
       OR (NEW.platform = 'YOUTUBE' AND NOT
         ('https://www.googleapis.com/auth/youtube.force-ssl' = ANY(NEW.authorization_scopes)))
       OR (NEW.platform = 'INSTAGRAM' AND NOT
         ('instagram_business_manage_comments' = ANY(NEW.authorization_scopes)))
       OR (NEW.platform = 'FACEBOOK' AND NOT
         ('pages_manage_engagement' = ANY(NEW.authorization_scopes)))
       OR NEW.receipt_state IS NOT NULL OR NEW.receipt_fingerprint IS NOT NULL
       OR NEW.remote_response_id IS NOT NULL OR NEW.recovery_evidence_id IS NOT NULL
       OR NEW.identity_recovered_at IS NOT NULL
       OR NEW.verification_evidence_id IS NOT NULL
       OR NEW.verification_observed_at IS NOT NULL
       OR NEW.verification_fingerprint IS NOT NULL
       OR NEW.verification_platform IS NOT NULL
       OR NEW.verification_destination_id IS NOT NULL
       OR NEW.verification_remote_object_id IS NOT NULL
       OR NEW.verification_parent_comment_id IS NOT NULL
       OR NEW.verification_text_fingerprint IS NOT NULL
       OR NEW.verification_visible IS NOT NULL OR NEW.error_code IS NOT NULL THEN
      RAISE EXCEPTION 'official response reservation is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSIF OLD.state = 'MUTATION_RESERVED' AND NEW.state = 'MUTATION_RESERVED' THEN
    PERFORM p.id FROM publication_jobs AS p
      WHERE p.id = NEW.publication_id FOR UPDATE;
    SELECT true INTO network_ready
      FROM community_response_approvals AS a
      JOIN community_reply_draft_records AS d ON d.request_id = a.draft_request_id
      JOIN community_comments_current AS c ON c.id = d.comment_version_id
      JOIN publication_jobs AS p ON p.id = d.publication_id
      JOIN social_channels AS ch ON ch.id = p.channel_id
      JOIN brands AS b ON b.id = ch.brand_id
      WHERE a.approval_id = NEW.approval_id AND a.decision = 'APPROVE'
        AND a.valid_until > clock_timestamp()
        AND a.record_fingerprint = NEW.approval_fingerprint
        AND d.record_fingerprint = NEW.draft_fingerprint
        AND d.draft_text = NEW.draft_text AND c.id = NEW.comment_version_id
        AND c.state <> 'DELETED' AND c.platform = NEW.platform
        AND c.destination_id = NEW.destination_id
        AND c.remote_object_id = NEW.remote_object_id
        AND c.remote_comment_id = NEW.remote_comment_id
        AND p.id = NEW.publication_id AND p.status = 'PUBLISHED'
        AND ch.enabled AND ch.permissions_status = 'VALID'
        AND ch.external_channel_id = NEW.destination_id
        AND ch.credentials_ref = NEW.credentials_ref
        AND b.owner_user_id = NEW.owner_user_id
        AND NOT EXISTS (
          SELECT 1 FROM community_analysis_reports AS newer
          WHERE newer.publication_id = d.publication_id
            AND (newer.created_at, newer.request_id::text) >
                ((SELECT created_at FROM community_analysis_reports
                  WHERE request_id = d.analysis_request_id), d.analysis_request_id::text)
        );
    expected_authorization := encode(digest(concat_ws('|',
      NEW.platform, NEW.destination_id,
      array_to_string(NEW.authorization_scopes, ','),
      to_char(NEW.authorization_checked_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
      to_char(NEW.authorization_valid_until AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    ), 'sha256'), 'hex');
    IF network_ready IS DISTINCT FROM true
       OR NEW.authorization_fingerprint IS DISTINCT FROM expected_authorization
       OR cardinality(NEW.authorization_scopes) = 0
       OR array_position(NEW.authorization_scopes, NULL) IS NOT NULL
       OR EXISTS (
         SELECT 1 FROM unnest(NEW.authorization_scopes) AS scope_value
         WHERE scope_value !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'
       )
       OR NEW.authorization_scopes IS DISTINCT FROM ARRAY(
         SELECT DISTINCT scope_value
         FROM unnest(NEW.authorization_scopes) AS scope_value
         ORDER BY scope_value COLLATE "C"
       )
       OR NEW.authorization_checked_at > clock_timestamp()
       OR NEW.authorization_checked_at < clock_timestamp() - interval '300 seconds'
       OR NEW.authorization_valid_until < clock_timestamp() + interval '30 seconds'
       OR (NEW.platform = 'YOUTUBE' AND NOT
         ('https://www.googleapis.com/auth/youtube.force-ssl' = ANY(NEW.authorization_scopes)))
       OR (NEW.platform = 'INSTAGRAM' AND NOT
         ('instagram_business_manage_comments' = ANY(NEW.authorization_scopes)))
       OR (NEW.platform = 'FACEBOOK' AND NOT
         ('pages_manage_engagement' = ANY(NEW.authorization_scopes)))
       OR (NEW.mutation_reserved_at, NEW.receipt_state, NEW.receipt_fingerprint,
           NEW.remote_response_id, NEW.recovery_evidence_id, NEW.identity_recovered_at,
           NEW.verification_evidence_id, NEW.verification_observed_at,
           NEW.verification_fingerprint, NEW.verification_platform,
           NEW.verification_destination_id, NEW.verification_remote_object_id,
           NEW.verification_parent_comment_id, NEW.verification_text_fingerprint,
           NEW.verification_visible, NEW.error_code)
          IS DISTINCT FROM
          (OLD.mutation_reserved_at, OLD.receipt_state, OLD.receipt_fingerprint,
           OLD.remote_response_id, OLD.recovery_evidence_id, OLD.identity_recovered_at,
           OLD.verification_evidence_id, OLD.verification_observed_at,
           OLD.verification_fingerprint, OLD.verification_platform,
           OLD.verification_destination_id, OLD.verification_remote_object_id,
           OLD.verification_parent_comment_id, OLD.verification_text_fingerprint,
           OLD.verification_visible, OLD.error_code) THEN
      RAISE EXCEPTION 'official response authorization refresh is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSIF OLD.state = 'MUTATION_RESERVED' AND NEW.state IN ('VERIFY_PENDING','FAILED') THEN
    IF NEW.receipt_state IS NOT NULL THEN
      expected_receipt := encode(digest(concat_ws('|',
        NEW.receipt_state, NEW.platform, NEW.destination_id,
        NEW.remote_object_id, NEW.remote_comment_id,
        NEW.draft_text_fingerprint, NEW.authorization_fingerprint,
        COALESCE(NEW.remote_response_id, '')
      ), 'sha256'), 'hex');
    END IF;
    IF (NEW.authorization_fingerprint, NEW.authorization_scopes,
        NEW.authorization_checked_at, NEW.authorization_valid_until,
        NEW.mutation_reserved_at)
       IS DISTINCT FROM
       (OLD.authorization_fingerprint, OLD.authorization_scopes,
        OLD.authorization_checked_at, OLD.authorization_valid_until,
        OLD.mutation_reserved_at)
       OR NEW.recovery_evidence_id IS NOT NULL OR NEW.identity_recovered_at IS NOT NULL
       OR NEW.verification_evidence_id IS NOT NULL OR NEW.verification_observed_at IS NOT NULL
       OR NEW.verification_fingerprint IS NOT NULL
       OR NEW.verification_platform IS NOT NULL
       OR NEW.verification_destination_id IS NOT NULL
       OR NEW.verification_remote_object_id IS NOT NULL
       OR NEW.verification_parent_comment_id IS NOT NULL
       OR NEW.verification_text_fingerprint IS NOT NULL
       OR NEW.verification_visible IS NOT NULL
       OR (NEW.receipt_state IS NOT NULL
         AND NEW.receipt_fingerprint IS DISTINCT FROM expected_receipt)
       OR (NEW.receipt_state = 'ACCEPTED' AND NEW.remote_response_id IS NULL)
       OR (NEW.receipt_state IS NULL AND (
         NEW.receipt_fingerprint IS NOT NULL OR NEW.remote_response_id IS NOT NULL
       ))
       OR (NEW.state = 'FAILED' AND (
         NEW.remote_response_id IS NOT NULL OR NEW.receipt_state IS NOT NULL
         OR NEW.receipt_fingerprint IS NOT NULL OR NEW.error_code IS NULL
       ))
       OR (NEW.state = 'VERIFY_PENDING' AND NEW.error_code IS NULL AND (
         NEW.receipt_state IS NULL OR NEW.receipt_fingerprint IS NULL
       )) THEN
      RAISE EXCEPTION 'official response receipt transition is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSIF OLD.state = 'VERIFY_PENDING' AND NEW.state = 'VERIFY_PENDING' THEN
    IF OLD.remote_response_id IS NOT NULL OR NEW.remote_response_id IS NULL
       OR OLD.recovery_evidence_id IS NOT NULL
       OR NEW.recovery_evidence_id IS NULL OR NEW.identity_recovered_at IS NULL
       OR NEW.identity_recovered_at <= OLD.mutation_reserved_at
       OR NEW.identity_recovered_at > clock_timestamp()
       OR (NEW.authorization_fingerprint, NEW.authorization_scopes,
           NEW.authorization_checked_at, NEW.authorization_valid_until,
           NEW.mutation_reserved_at, NEW.receipt_state, NEW.receipt_fingerprint,
           NEW.error_code, NEW.verification_evidence_id, NEW.verification_observed_at,
           NEW.verification_fingerprint, NEW.verification_platform,
           NEW.verification_destination_id, NEW.verification_remote_object_id,
           NEW.verification_parent_comment_id, NEW.verification_text_fingerprint,
           NEW.verification_visible)
          IS DISTINCT FROM
          (OLD.authorization_fingerprint, OLD.authorization_scopes,
           OLD.authorization_checked_at, OLD.authorization_valid_until,
           OLD.mutation_reserved_at, OLD.receipt_state, OLD.receipt_fingerprint,
           OLD.error_code, OLD.verification_evidence_id, OLD.verification_observed_at,
           OLD.verification_fingerprint, OLD.verification_platform,
           OLD.verification_destination_id, OLD.verification_remote_object_id,
           OLD.verification_parent_comment_id, OLD.verification_text_fingerprint,
           OLD.verification_visible) THEN
      RAISE EXCEPTION 'official response recovery transition is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSIF OLD.state = 'VERIFY_PENDING' AND NEW.state = 'RESPONDED' THEN
    expected_verification := encode(digest(concat_ws('|',
      NEW.verification_platform, NEW.verification_destination_id,
      NEW.verification_remote_object_id, NEW.remote_response_id,
      NEW.verification_parent_comment_id, NEW.verification_text_fingerprint,
      NEW.verification_visible::text,
      to_char(NEW.verification_observed_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), NEW.verification_evidence_id
    ), 'sha256'), 'hex');
    IF (NEW.authorization_fingerprint, NEW.authorization_scopes,
        NEW.authorization_checked_at, NEW.authorization_valid_until,
        NEW.mutation_reserved_at, NEW.receipt_state, NEW.receipt_fingerprint,
        NEW.remote_response_id, NEW.recovery_evidence_id, NEW.identity_recovered_at)
       IS DISTINCT FROM
       (OLD.authorization_fingerprint, OLD.authorization_scopes,
        OLD.authorization_checked_at, OLD.authorization_valid_until,
        OLD.mutation_reserved_at, OLD.receipt_state, OLD.receipt_fingerprint,
        OLD.remote_response_id, OLD.recovery_evidence_id, OLD.identity_recovered_at)
       OR NEW.remote_response_id IS NULL
       OR (NEW.receipt_state IS NULL AND NEW.recovery_evidence_id IS NULL)
       OR NEW.verification_evidence_id IS NULL
       OR NEW.verification_observed_at IS NULL
       OR NEW.verification_observed_at <
          COALESCE(NEW.identity_recovered_at, NEW.mutation_reserved_at)
       OR NEW.verification_observed_at > clock_timestamp()
       OR NEW.verification_fingerprint IS DISTINCT FROM expected_verification
       OR NEW.verification_platform IS DISTINCT FROM NEW.platform
       OR NEW.verification_destination_id IS DISTINCT FROM NEW.destination_id
       OR NEW.verification_remote_object_id IS DISTINCT FROM NEW.remote_object_id
       OR NEW.verification_parent_comment_id IS DISTINCT FROM NEW.remote_comment_id
       OR NEW.verification_text_fingerprint IS DISTINCT FROM NEW.draft_text_fingerprint
       OR NEW.verification_visible IS DISTINCT FROM true
       OR NEW.error_code IS NOT NULL THEN
      RAISE EXCEPTION 'official response verification transition is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSIF OLD.state = 'VERIFY_PENDING' AND NEW.state = 'FAILED' THEN
    IF NEW.error_code IS NULL
       OR (NEW.authorization_fingerprint, NEW.authorization_scopes,
           NEW.authorization_checked_at, NEW.authorization_valid_until,
           NEW.mutation_reserved_at, NEW.receipt_state, NEW.receipt_fingerprint,
           NEW.remote_response_id, NEW.recovery_evidence_id, NEW.identity_recovered_at,
           NEW.verification_evidence_id, NEW.verification_observed_at,
           NEW.verification_fingerprint, NEW.verification_platform,
           NEW.verification_destination_id, NEW.verification_remote_object_id,
           NEW.verification_parent_comment_id, NEW.verification_text_fingerprint,
           NEW.verification_visible)
          IS DISTINCT FROM
          (OLD.authorization_fingerprint, OLD.authorization_scopes,
           OLD.authorization_checked_at, OLD.authorization_valid_until,
           OLD.mutation_reserved_at, OLD.receipt_state, OLD.receipt_fingerprint,
           OLD.remote_response_id, OLD.recovery_evidence_id, OLD.identity_recovered_at,
           OLD.verification_evidence_id, OLD.verification_observed_at,
           OLD.verification_fingerprint, OLD.verification_platform,
           OLD.verification_destination_id, OLD.verification_remote_object_id,
           OLD.verification_parent_comment_id, OLD.verification_text_fingerprint,
           OLD.verification_visible) THEN
      RAISE EXCEPTION 'official response failure transition is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSE
    RAISE EXCEPTION 'official response state transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END;
$$;

CREATE FUNCTION guard_community_official_response_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'official response evidence is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER community_official_responses_require_insert
  BEFORE INSERT ON community_official_responses
  FOR EACH ROW EXECUTE FUNCTION require_community_official_response_insert();
CREATE TRIGGER community_official_responses_guard_update
  BEFORE UPDATE ON community_official_responses
  FOR EACH ROW EXECUTE FUNCTION guard_community_official_response_update();
CREATE TRIGGER community_official_responses_prevent_delete
  BEFORE DELETE ON community_official_responses
  FOR EACH ROW EXECUTE FUNCTION guard_community_official_response_delete();

REVOKE ALL ON community_response_approvals FROM PUBLIC;
REVOKE ALL ON community_official_responses FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION require_community_response_approval() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guard_community_response_approval_immutable() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION require_community_official_response_insert() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guard_community_official_response_update() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION guard_community_official_response_delete() FROM PUBLIC;

GRANT USAGE ON SCHEMA public
  TO flowx_community_approval_writer, flowx_community_response_runtime;
GRANT SELECT ON community_response_approvals,
  community_reply_draft_records, community_comment_versions,
  publication_jobs, social_channels, brands, community_analysis_reports,
  community_comments_current
  TO flowx_community_approval_writer;
GRANT SELECT ON community_response_approvals, community_reply_draft_records,
  community_comment_versions, publication_jobs, social_channels, brands,
  community_analysis_reports, community_comments_current
  TO flowx_community_response_runtime;
GRANT SELECT, INSERT, UPDATE ON community_official_responses
  TO flowx_community_response_runtime;

COMMENT ON TABLE community_response_approvals IS
  'Immutable reviewer/admin decisions over one exact inert reply draft; approval alone grants no provider authority.';
COMMENT ON TABLE community_official_responses IS
  'Single-winner official response attempts that become RESPONDED only after independent remote proof.';
