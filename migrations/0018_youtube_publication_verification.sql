-- Exact approved-artifact claims and verified official YouTube publication state.

ALTER TABLE publication_jobs
  ADD COLUMN request_id uuid,
  ADD COLUMN request_fingerprint char(64),
  ADD COLUMN approval_decision_id uuid REFERENCES review_decisions(id),
  ADD COLUMN channel_external_id_snapshot text,
  ADD COLUMN credentials_ref_snapshot text,
  ADD COLUMN destination_fingerprint char(64),
  ADD COLUMN asset_sha256_hex char(64),
  ADD COLUMN asset_size_bytes bigint,
  ADD COLUMN intended_privacy_status text,
  ADD COLUMN upload_session_ref text,
  ADD COLUMN uploaded_bytes bigint NOT NULL DEFAULT 0,
  ADD COLUMN verification_attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN last_verified_at timestamptz,
  ADD CONSTRAINT publication_jobs_youtube_v1_shape CHECK (
    (request_id IS NULL AND request_fingerprint IS NULL
      AND approval_decision_id IS NULL AND asset_sha256_hex IS NULL
      AND channel_external_id_snapshot IS NULL
      AND credentials_ref_snapshot IS NULL
      AND destination_fingerprint IS NULL
      AND asset_size_bytes IS NULL AND intended_privacy_status IS NULL
      AND upload_session_ref IS NULL AND uploaded_bytes = 0
      AND verification_attempt_count = 0 AND last_verified_at IS NULL)
    OR
    (request_id IS NOT NULL AND request_fingerprint ~ '^[0-9a-f]{64}$'
      AND approval_decision_id IS NOT NULL
      AND channel_external_id_snapshot ~ '^[A-Za-z0-9_-]{1,200}$'
      AND credentials_ref_snapshot ~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'
      AND destination_fingerprint ~ '^[0-9a-f]{64}$'
      AND asset_sha256_hex ~ '^[0-9a-f]{64}$'
      AND asset_size_bytes > 0
      AND intended_privacy_status IN ('private','unlisted','public')
      AND uploaded_bytes BETWEEN 0 AND asset_size_bytes
      AND verification_attempt_count BETWEEN 0 AND 1000)
  );

CREATE UNIQUE INDEX idx_publication_jobs_request_v1
  ON publication_jobs(request_id) WHERE request_id IS NOT NULL;
CREATE UNIQUE INDEX idx_publication_jobs_approval_channel_v1
  ON publication_jobs(approval_decision_id, channel_id)
  WHERE approval_decision_id IS NOT NULL;

CREATE FUNCTION require_youtube_publication_claim() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE brand_id_value uuid;
DECLARE owner_value text;
DECLARE content_status_value text;
DECLARE channel_platform text;
DECLARE channel_external_id text;
DECLARE channel_credentials_ref text;
DECLARE channel_permissions text;
DECLARE channel_enabled boolean;
DECLARE asset_kind_value text;
DECLARE asset_retention text;
DECLARE asset_storage text;
DECLARE asset_sha text;
DECLARE asset_size bigint;
DECLARE asset_mime text;
DECLARE asset_media jsonb;
DECLARE render_profile text;
DECLARE render_version_value integer;
DECLARE render_status text;
DECLARE review_decision text;
DECLARE expected_fingerprint text;
DECLARE expected_destination_fingerprint text;
BEGIN
  IF NEW.request_id IS NULL THEN
    RAISE EXCEPTION 'new publication jobs require v1 evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status <> 'DRAFT' OR NEW.upload_session_ref IS NOT NULL
     OR NEW.remote_upload_id IS NOT NULL OR NEW.remote_post_id IS NOT NULL
     OR NEW.remote_url IS NOT NULL OR NEW.uploaded_bytes <> 0
     OR NEW.verification_attempt_count <> 0 OR NEW.last_verified_at IS NOT NULL
     OR NEW.published_at IS NOT NULL OR NEW.last_error_code IS NOT NULL
     OR NEW.last_error_message IS NOT NULL THEN
    RAISE EXCEPTION 'initial YouTube publication state is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  expected_destination_fingerprint := encode(digest(
    NEW.channel_external_id_snapshot || '|' || NEW.credentials_ref_snapshot,
    'sha256'
  ), 'hex');
  IF NEW.destination_fingerprint IS DISTINCT FROM expected_destination_fingerprint THEN
    RAISE EXCEPTION 'YouTube destination fingerprint is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF jsonb_typeof(NEW.platform_metadata) IS DISTINCT FROM 'object'
     OR length(btrim(NEW.platform_metadata->>'title')) NOT BETWEEN 1 AND 100
     OR length(NEW.platform_metadata->>'description') > 5000
     OR NEW.platform_metadata->>'title' IS DISTINCT FROM btrim(NEW.platform_metadata->>'title')
     OR NEW.platform_metadata->>'description' IS DISTINCT FROM btrim(NEW.platform_metadata->>'description')
     OR NEW.platform_metadata->>'privacy_status' IS DISTINCT FROM NEW.intended_privacy_status
     OR jsonb_typeof(NEW.platform_metadata->'contains_synthetic_media') IS DISTINCT FROM 'boolean'
     OR NEW.platform_metadata->'notify_subscribers' IS DISTINCT FROM 'false'::jsonb
     OR (NEW.platform_metadata->>'title') ~ '[[:cntrl:]]'
     OR (NEW.platform_metadata->>'description') ~ '[[:cntrl:]]' THEN
    RAISE EXCEPTION 'YouTube publication metadata is invalid'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT b.id, b.owner_user_id, c.status,
         ch.platform, ch.external_channel_id, ch.credentials_ref,
         ch.permissions_status, ch.enabled,
         a.asset_kind, a.retention_state, a.storage_uri, a.sha256_hex,
         a.size_bytes, a.mime_type, a.media_metadata,
         rja.profile_id, rj.render_version, rj.status, rd.decision
    INTO brand_id_value, owner_value, content_status_value,
         channel_platform, channel_external_id, channel_credentials_ref,
         channel_permissions, channel_enabled,
         asset_kind_value, asset_retention, asset_storage, asset_sha,
         asset_size, asset_mime, asset_media,
         render_profile, render_version_value, render_status, review_decision
    FROM content_items AS c
    JOIN brands AS b ON b.id = c.brand_id
    JOIN social_channels AS ch
      ON ch.id = NEW.channel_id AND ch.brand_id = b.id
    JOIN assets AS a
      ON a.id = NEW.asset_id AND a.content_id = c.id AND a.scene_id IS NULL
    JOIN render_job_artifacts AS rja
      ON rja.asset_id = a.id AND rja.artifact_role = 'EXPORT_VARIANT'
    JOIN render_jobs AS rj
      ON rj.id = rja.render_job_id AND rj.content_id = c.id
     AND rj.render_version = NEW.artifact_version
    JOIN review_decisions AS rd
      ON rd.id = NEW.approval_decision_id AND rd.content_id = c.id
     AND rd.asset_id = a.id AND rd.request_id IS NOT NULL
    WHERE c.id = NEW.content_id
    FOR KEY SHARE OF c, b, ch, a, rja, rj, rd;

  IF content_status_value IS DISTINCT FROM 'READY'
     OR channel_platform IS DISTINCT FROM 'YOUTUBE'
     OR channel_external_id !~ '^[A-Za-z0-9_-]{1,200}$'
     OR channel_credentials_ref !~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'
     OR NEW.channel_external_id_snapshot IS DISTINCT FROM channel_external_id
     OR NEW.credentials_ref_snapshot IS DISTINCT FROM channel_credentials_ref
     OR channel_permissions IS DISTINCT FROM 'VALID' OR channel_enabled IS DISTINCT FROM true
     OR asset_kind_value IS DISTINCT FROM 'EXPORT_VARIANT'
     OR asset_retention IS DISTINCT FROM 'ACTIVE'
     OR asset_storage IS DISTINCT FROM 'managed://assets/' || replace(NEW.asset_id::text, '-', '') || '/payload'
     OR asset_sha IS DISTINCT FROM NEW.asset_sha256_hex
     OR asset_size IS DISTINCT FROM NEW.asset_size_bytes
     OR asset_mime IS DISTINCT FROM 'video/mp4'
     OR asset_media->>'export_profile_id' IS DISTINCT FROM 'YOUTUBE_SHORTS_V1'
     OR asset_media->>'platform' IS DISTINCT FROM 'YOUTUBE'
     OR asset_media->'publishing_performed' IS DISTINCT FROM 'false'::jsonb
     OR render_profile IS DISTINCT FROM 'YOUTUBE_SHORTS_V1'
     OR render_version_value IS DISTINCT FROM NEW.artifact_version
     OR render_status IS DISTINCT FROM 'DONE'
     OR review_decision IS DISTINCT FROM 'APPROVE' THEN
    RAISE EXCEPTION 'YouTube publication evidence is not eligible'
      USING ERRCODE = 'check_violation';
  END IF;

  expected_fingerprint := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.id::text, brand_id_value::text,
    NEW.content_id::text, NEW.channel_id::text, NEW.asset_id::text,
    owner_value, NEW.artifact_version::text,
    btrim(NEW.platform_metadata->>'title'),
    btrim(NEW.platform_metadata->>'description'),
    NEW.intended_privacy_status,
    CASE WHEN (NEW.platform_metadata->>'contains_synthetic_media')::boolean THEN 'true' ELSE 'false' END,
    'false'
  ), 'sha256'), 'hex');
  IF NEW.request_fingerprint IS DISTINCT FROM expected_fingerprint THEN
    RAISE EXCEPTION 'YouTube publication fingerprint is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_jobs_require_youtube_claim
  BEFORE INSERT ON publication_jobs
  FOR EACH ROW EXECUTE FUNCTION require_youtube_publication_claim();

CREATE FUNCTION guard_youtube_publication_transition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE remote_video_id text;
DECLARE remote_channel_id text;
DECLARE remote_upload_status text;
DECLARE remote_processing_status text;
DECLARE remote_privacy_status text;
BEGIN
  IF OLD.request_id IS NULL THEN
    RAISE EXCEPTION 'legacy publication jobs cannot enter the v1 workflow'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.id, NEW.request_id, NEW.request_fingerprint, NEW.content_id,
      NEW.channel_id, NEW.asset_id, NEW.approval_decision_id,
      NEW.artifact_version, NEW.channel_external_id_snapshot,
      NEW.credentials_ref_snapshot, NEW.destination_fingerprint,
      NEW.asset_sha256_hex, NEW.asset_size_bytes,
      NEW.intended_privacy_status, NEW.platform_metadata, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.request_id, OLD.request_fingerprint, OLD.content_id,
      OLD.channel_id, OLD.asset_id, OLD.approval_decision_id,
      OLD.artifact_version, OLD.channel_external_id_snapshot,
      OLD.credentials_ref_snapshot, OLD.destination_fingerprint,
      OLD.asset_sha256_hex, OLD.asset_size_bytes,
      OLD.intended_privacy_status, OLD.platform_metadata, OLD.created_at) THEN
    RAISE EXCEPTION 'YouTube publication claim evidence is immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status IN ('PUBLISHED','FAILED','CANCELLED') THEN
    RAISE EXCEPTION 'terminal YouTube publication state is immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.upload_session_ref IS NOT NULL
     AND NEW.upload_session_ref IS DISTINCT FROM OLD.upload_session_ref
     OR OLD.remote_upload_id IS NOT NULL
     AND NEW.remote_upload_id IS DISTINCT FROM OLD.remote_upload_id
     OR OLD.remote_post_id IS NOT NULL
     AND NEW.remote_post_id IS DISTINCT FROM OLD.remote_post_id THEN
    RAISE EXCEPTION 'YouTube remote identities are immutable once observed'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT (
    (OLD.status = 'DRAFT' AND NEW.status = 'PUBLISH_REQUESTED') OR
    (OLD.status = 'PUBLISH_REQUESTED' AND NEW.status IN ('UPLOAD_STARTED','VERIFY_PENDING','FAILED','CANCELLED')) OR
    (OLD.status = 'UPLOAD_STARTED' AND NEW.status IN ('UPLOAD_STARTED','PROCESSING','VERIFY_PENDING','FAILED')) OR
    (OLD.status = 'VERIFY_PENDING' AND NEW.status IN ('UPLOAD_STARTED','PROCESSING','VERIFY_PENDING','FAILED','CANCELLED')) OR
    (OLD.status = 'PROCESSING' AND NEW.status IN ('PROCESSING','VERIFY_PENDING','PUBLISHED','FAILED'))
  ) THEN
    RAISE EXCEPTION 'YouTube publication transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.upload_session_ref IS NOT NULL
     AND NEW.upload_session_ref !~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$' THEN
    RAISE EXCEPTION 'YouTube upload session reference is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.remote_upload_id IS NOT NULL AND NEW.remote_upload_id !~ '^[A-Za-z0-9_-]{1,200}$')
     OR (NEW.remote_post_id IS NOT NULL AND NEW.remote_post_id !~ '^[A-Za-z0-9_-]{1,200}$')
     OR (NEW.last_error_code IS NOT NULL AND NEW.last_error_code !~ '^[A-Z][A-Z0-9_]{0,63}$')
     OR (NEW.last_error_message IS NOT NULL AND (
       length(NEW.last_error_message) > 500 OR NEW.last_error_message ~ '[[:cntrl:]]'
       OR NEW.last_error_message ~* '(token|secret|credential|authorization|cookie)[[:space:]]*[:=]')) THEN
    RAISE EXCEPTION 'YouTube remote/error evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IN ('UPLOAD_STARTED','PROCESSING','PUBLISHED')
     AND (NEW.upload_session_ref IS NULL OR NEW.remote_upload_id IS NULL) THEN
    RAISE EXCEPTION 'YouTube resumable session evidence is missing'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IN ('PROCESSING','PUBLISHED')
     AND (NEW.remote_post_id IS NULL OR NEW.uploaded_bytes <> NEW.asset_size_bytes) THEN
    RAISE EXCEPTION 'YouTube completed upload evidence is missing'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.verification_attempt_count < OLD.verification_attempt_count
     OR NEW.uploaded_bytes < OLD.uploaded_bytes THEN
    RAISE EXCEPTION 'YouTube progress evidence cannot move backwards'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status = 'FAILED' AND NEW.last_error_code IS NULL THEN
    RAISE EXCEPTION 'failed YouTube publication requires an error code'
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.status = 'PUBLISHED' THEN
    remote_video_id := NEW.last_remote_status->>'video_id';
    remote_channel_id := NEW.last_remote_status->>'channel_id';
    remote_upload_status := NEW.last_remote_status->>'upload_status';
    remote_processing_status := NEW.last_remote_status->>'processing_status';
    remote_privacy_status := NEW.last_remote_status->>'privacy_status';
    IF jsonb_typeof(NEW.last_remote_status) IS DISTINCT FROM 'object'
       OR remote_video_id IS DISTINCT FROM NEW.remote_post_id
       OR remote_upload_status IS DISTINCT FROM 'processed'
       OR remote_processing_status IS DISTINCT FROM 'succeeded'
       OR remote_privacy_status IS DISTINCT FROM NEW.intended_privacy_status
       OR NOT EXISTS (
         SELECT 1 FROM social_channels AS ch
         WHERE ch.id = NEW.channel_id AND ch.external_channel_id = remote_channel_id
       )
       OR NEW.remote_url IS DISTINCT FROM 'https://www.youtube.com/watch?v=' || NEW.remote_post_id
       OR NEW.last_verified_at IS NULL OR NEW.published_at IS NULL
       OR NEW.last_error_code IS NOT NULL OR NEW.last_error_message IS NOT NULL THEN
      RAISE EXCEPTION 'verified YouTube publication evidence is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSEIF NEW.published_at IS NOT NULL THEN
    RAISE EXCEPTION 'unverified YouTube publication cannot have a publication time'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_jobs_guard_youtube_transition
  BEFORE UPDATE ON publication_jobs
  FOR EACH ROW WHEN (OLD.request_id IS NOT NULL OR NEW.request_id IS NOT NULL)
  EXECUTE FUNCTION guard_youtube_publication_transition();

CREATE FUNCTION prevent_youtube_publication_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.request_id IS NOT NULL THEN
    RAISE EXCEPTION 'YouTube publication evidence is immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN OLD;
END;
$$;

CREATE TRIGGER publication_jobs_prevent_youtube_delete
  BEFORE DELETE ON publication_jobs
  FOR EACH ROW EXECUTE FUNCTION prevent_youtube_publication_delete();
