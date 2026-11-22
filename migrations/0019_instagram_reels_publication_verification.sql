-- Exact approved-artifact claims and verified official Instagram Reel state.

ALTER TABLE publication_jobs
  ADD COLUMN publication_contract text,
  ADD COLUMN media_source_ref_snapshot text,
  ADD COLUMN instagram_phase text;

UPDATE publication_jobs
   SET publication_contract = 'YOUTUBE_V1'
 WHERE request_id IS NOT NULL;

ALTER TABLE publication_jobs
  DROP CONSTRAINT publication_jobs_youtube_v1_shape,
  ADD CONSTRAINT publication_jobs_v1_shape CHECK (
    (request_id IS NULL AND publication_contract IS NULL
      AND request_fingerprint IS NULL AND approval_decision_id IS NULL
      AND asset_sha256_hex IS NULL AND channel_external_id_snapshot IS NULL
      AND credentials_ref_snapshot IS NULL AND destination_fingerprint IS NULL
      AND asset_size_bytes IS NULL AND intended_privacy_status IS NULL
      AND upload_session_ref IS NULL AND uploaded_bytes = 0
      AND verification_attempt_count = 0 AND last_verified_at IS NULL
      AND media_source_ref_snapshot IS NULL AND instagram_phase IS NULL)
    OR
    (publication_contract = 'YOUTUBE_V1'
      AND request_id IS NOT NULL AND request_fingerprint ~ '^[0-9a-f]{64}$'
      AND approval_decision_id IS NOT NULL
      AND channel_external_id_snapshot ~ '^[A-Za-z0-9_-]{1,200}$'
      AND credentials_ref_snapshot ~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'
      AND destination_fingerprint ~ '^[0-9a-f]{64}$'
      AND asset_sha256_hex ~ '^[0-9a-f]{64}$' AND asset_size_bytes > 0
      AND intended_privacy_status IN ('private','unlisted','public')
      AND uploaded_bytes BETWEEN 0 AND asset_size_bytes
      AND verification_attempt_count BETWEEN 0 AND 1000
      AND media_source_ref_snapshot IS NULL AND instagram_phase IS NULL)
    OR
    (publication_contract = 'INSTAGRAM_REELS_V1'
      AND request_id IS NOT NULL AND request_fingerprint ~ '^[0-9a-f]{64}$'
      AND approval_decision_id IS NOT NULL
      AND channel_external_id_snapshot ~ '^[A-Za-z0-9_-]{1,200}$'
      AND credentials_ref_snapshot ~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'
      AND destination_fingerprint ~ '^[0-9a-f]{64}$'
      AND media_source_ref_snapshot ~ '^secretref://[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$'
      AND asset_sha256_hex ~ '^[0-9a-f]{64}$'
      AND asset_size_bytes BETWEEN 1 AND 300000000
      AND intended_privacy_status = 'public'
      AND upload_session_ref IS NULL AND uploaded_bytes = 0
      AND verification_attempt_count BETWEEN 0 AND 1000
      AND instagram_phase IN (
        'CLAIMED','CONTAINER_RESERVED','CONTAINER_CREATED','CONTAINER_PROCESSING',
        'CONTAINER_READY','PUBLISH_RESERVED','MEDIA_RECORDED','MEDIA_ID_UNKNOWN',
        'VERIFIED','FAILED','CANCELLED'))
  );

DROP TRIGGER publication_jobs_require_youtube_claim ON publication_jobs;
CREATE TRIGGER publication_jobs_require_youtube_claim
  BEFORE INSERT ON publication_jobs
  FOR EACH ROW WHEN (NEW.publication_contract = 'YOUTUBE_V1')
  EXECUTE FUNCTION require_youtube_publication_claim();

DROP TRIGGER publication_jobs_guard_youtube_transition ON publication_jobs;
CREATE TRIGGER publication_jobs_guard_youtube_transition
  BEFORE UPDATE ON publication_jobs
  FOR EACH ROW WHEN (
    OLD.publication_contract = 'YOUTUBE_V1' OR NEW.publication_contract = 'YOUTUBE_V1')
  EXECUTE FUNCTION guard_youtube_publication_transition();

DROP TRIGGER publication_jobs_prevent_youtube_delete ON publication_jobs;
CREATE TRIGGER publication_jobs_prevent_youtube_delete
  BEFORE DELETE ON publication_jobs
  FOR EACH ROW WHEN (OLD.publication_contract = 'YOUTUBE_V1')
  EXECUTE FUNCTION prevent_youtube_publication_delete();

CREATE FUNCTION require_instagram_publication_claim() RETURNS trigger LANGUAGE plpgsql AS $$
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
  IF NEW.status <> 'DRAFT' OR NEW.instagram_phase <> 'CLAIMED'
     OR NEW.remote_upload_id IS NOT NULL OR NEW.remote_post_id IS NOT NULL
     OR NEW.remote_url IS NOT NULL OR NEW.last_remote_status <> '{}'::jsonb
     OR NEW.verification_attempt_count <> 0 OR NEW.last_verified_at IS NOT NULL
     OR NEW.published_at IS NOT NULL OR NEW.last_error_code IS NOT NULL
     OR NEW.last_error_message IS NOT NULL THEN
    RAISE EXCEPTION 'initial Instagram publication state is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  expected_destination_fingerprint := encode(digest(
    NEW.channel_external_id_snapshot || '|' || NEW.credentials_ref_snapshot,
    'sha256'
  ), 'hex');
  IF NEW.destination_fingerprint IS DISTINCT FROM expected_destination_fingerprint THEN
    RAISE EXCEPTION 'Instagram destination fingerprint is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF jsonb_typeof(NEW.platform_metadata) IS DISTINCT FROM 'object'
     OR NEW.platform_metadata->>'api_login' IS DISTINCT FROM 'INSTAGRAM_LOGIN'
     OR NEW.platform_metadata->>'media_type' IS DISTINCT FROM 'REELS'
     OR length(NEW.platform_metadata->>'caption') > 2200
     OR NEW.platform_metadata->>'caption' IS DISTINCT FROM btrim(NEW.platform_metadata->>'caption')
     OR (NEW.platform_metadata->>'caption') ~ '[[:cntrl:]]'
     OR jsonb_typeof(NEW.platform_metadata->'share_to_feed') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(NEW.platform_metadata->'is_ai_generated') IS DISTINCT FROM 'boolean' THEN
    RAISE EXCEPTION 'Instagram publication metadata is invalid'
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
    JOIN social_channels AS ch ON ch.id = NEW.channel_id AND ch.brand_id = b.id
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
     OR channel_platform IS DISTINCT FROM 'INSTAGRAM'
     OR NEW.channel_external_id_snapshot IS DISTINCT FROM channel_external_id
     OR NEW.credentials_ref_snapshot IS DISTINCT FROM channel_credentials_ref
     OR channel_permissions IS DISTINCT FROM 'VALID' OR channel_enabled IS DISTINCT FROM true
     OR asset_kind_value IS DISTINCT FROM 'EXPORT_VARIANT'
     OR asset_retention IS DISTINCT FROM 'ACTIVE'
     OR asset_storage IS DISTINCT FROM 'managed://assets/' || replace(NEW.asset_id::text, '-', '') || '/payload'
     OR asset_sha IS DISTINCT FROM NEW.asset_sha256_hex
     OR asset_size IS DISTINCT FROM NEW.asset_size_bytes
     OR asset_mime IS DISTINCT FROM 'video/mp4'
     OR asset_media->>'export_profile_id' IS DISTINCT FROM 'INSTAGRAM_REELS_V1'
     OR asset_media->>'platform' IS DISTINCT FROM 'INSTAGRAM'
     OR asset_media->'publishing_performed' IS DISTINCT FROM 'false'::jsonb
     OR render_profile IS DISTINCT FROM 'INSTAGRAM_REELS_V1'
     OR render_version_value IS DISTINCT FROM NEW.artifact_version
     OR render_status IS DISTINCT FROM 'DONE'
     OR review_decision IS DISTINCT FROM 'APPROVE' THEN
    RAISE EXCEPTION 'Instagram publication evidence is not eligible'
      USING ERRCODE = 'check_violation';
  END IF;

  expected_fingerprint := encode(digest(concat_ws('|',
    NEW.request_id::text, NEW.id::text, brand_id_value::text,
    NEW.content_id::text, NEW.channel_id::text, NEW.asset_id::text,
    owner_value, NEW.artifact_version::text, NEW.media_source_ref_snapshot,
    NEW.platform_metadata->>'caption',
    CASE WHEN (NEW.platform_metadata->>'share_to_feed')::boolean THEN 'true' ELSE 'false' END,
    CASE WHEN (NEW.platform_metadata->>'is_ai_generated')::boolean THEN 'true' ELSE 'false' END,
    'INSTAGRAM_LOGIN_V1'
  ), 'sha256'), 'hex');
  IF NEW.request_fingerprint IS DISTINCT FROM expected_fingerprint THEN
    RAISE EXCEPTION 'Instagram publication fingerprint is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_jobs_require_instagram_claim
  BEFORE INSERT ON publication_jobs
  FOR EACH ROW WHEN (NEW.publication_contract = 'INSTAGRAM_REELS_V1')
  EXECUTE FUNCTION require_instagram_publication_claim();

CREATE FUNCTION guard_instagram_publication_transition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE container_id text;
DECLARE container_state text;
DECLARE media_id text;
DECLARE owner_id text;
DECLARE media_type_value text;
DECLARE permalink_value text;
BEGIN
  IF NEW.publication_contract IS DISTINCT FROM OLD.publication_contract
     OR (NEW.id, NEW.request_id, NEW.request_fingerprint, NEW.content_id,
         NEW.channel_id, NEW.asset_id, NEW.approval_decision_id,
         NEW.artifact_version, NEW.channel_external_id_snapshot,
         NEW.credentials_ref_snapshot, NEW.destination_fingerprint,
         NEW.media_source_ref_snapshot, NEW.asset_sha256_hex, NEW.asset_size_bytes,
         NEW.intended_privacy_status, NEW.platform_metadata, NEW.created_at)
        IS DISTINCT FROM
        (OLD.id, OLD.request_id, OLD.request_fingerprint, OLD.content_id,
         OLD.channel_id, OLD.asset_id, OLD.approval_decision_id,
         OLD.artifact_version, OLD.channel_external_id_snapshot,
         OLD.credentials_ref_snapshot, OLD.destination_fingerprint,
         OLD.media_source_ref_snapshot, OLD.asset_sha256_hex, OLD.asset_size_bytes,
         OLD.intended_privacy_status, OLD.platform_metadata, OLD.created_at) THEN
    RAISE EXCEPTION 'Instagram publication claim evidence is immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status IN ('PUBLISHED','FAILED','CANCELLED') THEN
    RAISE EXCEPTION 'terminal Instagram publication state is immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (OLD.remote_upload_id IS NOT NULL AND NEW.remote_upload_id IS DISTINCT FROM OLD.remote_upload_id)
     OR (OLD.remote_post_id IS NOT NULL AND NEW.remote_post_id IS DISTINCT FROM OLD.remote_post_id) THEN
    RAISE EXCEPTION 'Instagram remote identities are immutable once observed'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT (
    (OLD.status = 'DRAFT' AND OLD.instagram_phase = 'CLAIMED'
      AND NEW.status = 'UPLOAD_STARTED' AND NEW.instagram_phase = 'CONTAINER_RESERVED') OR
    (OLD.status = 'UPLOAD_STARTED' AND OLD.instagram_phase = 'CONTAINER_RESERVED'
      AND NEW.status = 'PROCESSING' AND NEW.instagram_phase = 'CONTAINER_CREATED') OR
    (OLD.status = 'UPLOAD_STARTED' AND OLD.instagram_phase = 'CONTAINER_RESERVED'
      AND NEW.status = 'CANCELLED' AND NEW.instagram_phase = 'CANCELLED') OR
    (OLD.status = 'PROCESSING' AND OLD.instagram_phase IN
      ('CONTAINER_CREATED','CONTAINER_PROCESSING','CONTAINER_READY')
      AND NEW.status = 'PROCESSING' AND NEW.instagram_phase IN
      ('CONTAINER_PROCESSING','CONTAINER_READY')) OR
    (OLD.status = 'PROCESSING' AND OLD.instagram_phase IN
      ('CONTAINER_CREATED','CONTAINER_PROCESSING','CONTAINER_READY')
      AND NEW.status = 'FAILED' AND NEW.instagram_phase = 'FAILED') OR
    (OLD.status = 'PROCESSING' AND OLD.instagram_phase IN
      ('CONTAINER_CREATED','CONTAINER_PROCESSING','CONTAINER_READY')
      AND NEW.status = 'VERIFY_PENDING' AND NEW.instagram_phase = 'MEDIA_ID_UNKNOWN') OR
    (OLD.status = 'PROCESSING' AND OLD.instagram_phase = 'CONTAINER_READY'
      AND NEW.status = 'PUBLISH_REQUESTED' AND NEW.instagram_phase = 'PUBLISH_RESERVED') OR
    (OLD.status = 'PUBLISH_REQUESTED' AND OLD.instagram_phase = 'PUBLISH_RESERVED'
      AND NEW.status = 'VERIFY_PENDING' AND NEW.instagram_phase = 'MEDIA_RECORDED') OR
    (OLD.status = 'PUBLISH_REQUESTED' AND OLD.instagram_phase = 'PUBLISH_RESERVED'
      AND NEW.status = 'CANCELLED' AND NEW.instagram_phase = 'CANCELLED') OR
    (OLD.status = 'VERIFY_PENDING' AND OLD.instagram_phase = 'MEDIA_ID_UNKNOWN'
      AND NEW.status = 'VERIFY_PENDING' AND NEW.instagram_phase = 'MEDIA_RECORDED') OR
    (OLD.status = 'VERIFY_PENDING' AND OLD.instagram_phase = 'MEDIA_ID_UNKNOWN'
      AND NEW.status = 'CANCELLED' AND NEW.instagram_phase = 'CANCELLED') OR
    (OLD.status = 'VERIFY_PENDING' AND OLD.instagram_phase = 'MEDIA_RECORDED'
      AND NEW.status = 'VERIFY_PENDING' AND NEW.instagram_phase = 'MEDIA_RECORDED') OR
    (OLD.status = 'VERIFY_PENDING' AND OLD.instagram_phase = 'MEDIA_RECORDED'
      AND NEW.status = 'PUBLISHED' AND NEW.instagram_phase = 'VERIFIED') OR
    (OLD.status = NEW.status AND OLD.instagram_phase = NEW.instagram_phase
      AND OLD.instagram_phase IN ('CONTAINER_RESERVED','PUBLISH_RESERVED','MEDIA_ID_UNKNOWN'))
  ) THEN
    RAISE EXCEPTION 'Instagram publication transition is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase = 'CONTAINER_RESERVED' AND (
       NEW.remote_upload_id IS NOT NULL OR NEW.remote_post_id IS NOT NULL
       OR NEW.remote_url IS NOT NULL OR NEW.last_remote_status <> '{}'::jsonb
       OR NEW.verification_attempt_count <> 0 OR NEW.last_verified_at IS NOT NULL
       OR NEW.published_at IS NOT NULL) THEN
    RAISE EXCEPTION 'Instagram container reservation must be pristine'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase IN ('CONTAINER_CREATED','CONTAINER_PROCESSING','CONTAINER_READY',
                              'PUBLISH_RESERVED','MEDIA_RECORDED','MEDIA_ID_UNKNOWN','VERIFIED')
     AND NEW.remote_upload_id IS NULL THEN
    RAISE EXCEPTION 'Instagram container identity is missing'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase IN ('MEDIA_RECORDED','VERIFIED') AND NEW.remote_post_id IS NULL THEN
    RAISE EXCEPTION 'Instagram media identity is missing'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase = 'CONTAINER_PROCESSING' AND (
       jsonb_typeof(NEW.last_remote_status) IS DISTINCT FROM 'object'
       OR NEW.last_remote_status->>'container_id' IS DISTINCT FROM NEW.remote_upload_id
       OR NEW.last_remote_status->>'container_status' IS DISTINCT FROM 'IN_PROGRESS'
     ) THEN
    RAISE EXCEPTION 'Instagram processing evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase IN ('CONTAINER_READY','PUBLISH_RESERVED') AND (
       jsonb_typeof(NEW.last_remote_status) IS DISTINCT FROM 'object'
       OR NEW.last_remote_status->>'container_id' IS DISTINCT FROM NEW.remote_upload_id
       OR NEW.last_remote_status->>'container_status' IS DISTINCT FROM 'FINISHED'
     ) THEN
    RAISE EXCEPTION 'Instagram publishable container evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase = 'MEDIA_ID_UNKNOWN' AND (
       jsonb_typeof(NEW.last_remote_status) IS DISTINCT FROM 'object'
       OR NEW.last_remote_status->>'container_id' IS DISTINCT FROM NEW.remote_upload_id
       OR NEW.last_remote_status->>'container_status' IS DISTINCT FROM 'PUBLISHED'
     ) THEN
    RAISE EXCEPTION 'Instagram unknown media evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.instagram_phase = 'MEDIA_RECORDED' AND (
       jsonb_typeof(NEW.last_remote_status) IS DISTINCT FROM 'object'
       OR NEW.last_remote_status->>'container_id' IS DISTINCT FROM NEW.remote_upload_id
       OR NEW.last_remote_status->>'container_status' NOT IN ('FINISHED','PUBLISHED')
     ) THEN
    RAISE EXCEPTION 'Instagram recorded media evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF (OLD.remote_upload_id IS NULL AND NEW.remote_upload_id IS NOT NULL
      AND NEW.instagram_phase <> 'CONTAINER_CREATED')
     OR (OLD.remote_post_id IS NULL AND NEW.remote_post_id IS NOT NULL
      AND NEW.instagram_phase <> 'MEDIA_RECORDED') THEN
    RAISE EXCEPTION 'Instagram remote identity introduction is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.verification_attempt_count < OLD.verification_attempt_count
     OR NEW.uploaded_bytes <> 0 OR NEW.upload_session_ref IS NOT NULL
     OR (NEW.last_error_code IS NOT NULL AND NEW.last_error_code !~ '^[A-Z][A-Z0-9_]{0,63}$')
     OR (NEW.last_error_message IS NOT NULL AND (
       length(NEW.last_error_message) > 500 OR NEW.last_error_message ~ '[[:cntrl:]]'
       OR NEW.last_error_message ~* '(token|secret|credential|authorization|cookie)[[:space:]]*[:=]')) THEN
    RAISE EXCEPTION 'Instagram progress/error evidence is invalid'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status = 'FAILED' AND NEW.last_error_code IS NULL THEN
    RAISE EXCEPTION 'failed Instagram publication requires an error code'
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.status = 'PUBLISHED' THEN
    container_id := NEW.last_remote_status->>'container_id';
    container_state := NEW.last_remote_status->>'container_status';
    media_id := NEW.last_remote_status->>'media_id';
    owner_id := NEW.last_remote_status->>'owner_id';
    media_type_value := NEW.last_remote_status->>'media_type';
    permalink_value := NEW.last_remote_status->>'permalink';
    IF jsonb_typeof(NEW.last_remote_status) IS DISTINCT FROM 'object'
       OR container_id IS DISTINCT FROM NEW.remote_upload_id
       OR container_state IS DISTINCT FROM 'PUBLISHED'
       OR media_id IS DISTINCT FROM NEW.remote_post_id
       OR owner_id IS DISTINCT FROM NEW.channel_external_id_snapshot
       OR media_type_value IS DISTINCT FROM 'VIDEO'
       OR permalink_value !~ '^https://www[.]instagram[.]com/reel/[A-Za-z0-9_-]+/?$'
       OR NEW.remote_url IS DISTINCT FROM permalink_value
       OR NEW.last_verified_at IS NULL OR NEW.published_at IS NULL
       OR NEW.last_error_code IS NOT NULL OR NEW.last_error_message IS NOT NULL THEN
      RAISE EXCEPTION 'verified Instagram publication evidence is invalid'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSEIF NEW.published_at IS NOT NULL OR NEW.remote_url IS NOT NULL THEN
    RAISE EXCEPTION 'unverified Instagram publication cannot have publication evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER publication_jobs_guard_instagram_transition
  BEFORE UPDATE ON publication_jobs
  FOR EACH ROW WHEN (
    OLD.publication_contract = 'INSTAGRAM_REELS_V1'
    OR NEW.publication_contract = 'INSTAGRAM_REELS_V1')
  EXECUTE FUNCTION guard_instagram_publication_transition();

CREATE FUNCTION prevent_instagram_publication_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Instagram publication evidence is immutable'
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER publication_jobs_prevent_instagram_delete
  BEFORE DELETE ON publication_jobs
  FOR EACH ROW WHEN (OLD.publication_contract = 'INSTAGRAM_REELS_V1')
  EXECUTE FUNCTION prevent_instagram_publication_delete();
