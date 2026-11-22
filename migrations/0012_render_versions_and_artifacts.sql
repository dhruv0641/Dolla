-- Durable render execution leases, version evidence and artifact references.

ALTER TABLE render_jobs
  ADD COLUMN plan_fingerprint char(64),
  ADD COLUMN attempt_count integer NOT NULL DEFAULT 0,
  ADD COLUMN lease_owner text,
  ADD COLUMN lease_expires_at timestamptz,
  ADD COLUMN started_at timestamptz,
  ADD COLUMN error_code text,
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

-- Migration 0010 refused legacy free-form render rows. Any jobs created after
-- that migration already have normalized JSON, so derive a stable legacy key.
UPDATE render_jobs
SET plan_fingerprint = encode(
  digest(inputs_manifest::text || E'\n' || command_manifest::text, 'sha256'), 'hex'
)
WHERE plan_fingerprint IS NULL;

ALTER TABLE render_jobs
  ALTER COLUMN plan_fingerprint SET NOT NULL,
  ADD CONSTRAINT render_jobs_plan_fingerprint_format
    CHECK (plan_fingerprint ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT render_jobs_attempt_count_bounds
    CHECK (attempt_count BETWEEN 0 AND 10),
  ADD CONSTRAINT render_jobs_error_code_format
    CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
  ADD CONSTRAINT render_jobs_lease_shape CHECK (
    (status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL
      AND started_at IS NOT NULL AND attempt_count > 0 AND finished_at IS NULL AND error_code IS NULL)
    OR
    (status <> 'RUNNING' AND lease_owner IS NULL AND lease_expires_at IS NULL)
  ),
  ADD CONSTRAINT render_jobs_terminal_shape CHECK (
    (status = 'PENDING' AND finished_at IS NULL AND final_asset_id IS NULL AND error_code IS NULL)
    OR (status = 'RUNNING')
    OR (status = 'DONE' AND finished_at IS NOT NULL AND final_asset_id IS NOT NULL AND error_code IS NULL)
    OR (status = 'FAILED' AND finished_at IS NOT NULL AND final_asset_id IS NULL AND error_code IS NOT NULL)
  );

CREATE UNIQUE INDEX idx_render_jobs_content_plan
  ON render_jobs(content_id, plan_fingerprint);
CREATE INDEX idx_render_jobs_claimable
  ON render_jobs(status, lease_expires_at, created_at);

CREATE TABLE render_job_artifacts (
  render_job_id uuid NOT NULL REFERENCES render_jobs(id) ON DELETE CASCADE,
  asset_id uuid NOT NULL REFERENCES assets(id),
  artifact_role text NOT NULL CHECK (artifact_role IN ('FINAL_VIDEO','EXPORT_VARIANT')),
  profile_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (render_job_id, asset_id),
  UNIQUE (render_job_id, artifact_role, profile_id),
  CHECK (
    (artifact_role = 'FINAL_VIDEO' AND profile_id IS NULL)
    OR (artifact_role = 'EXPORT_VARIANT' AND profile_id ~ '^[A-Z][A-Z0-9_]{0,63}$')
  )
);

-- A NULL profile does not collide under a normal UNIQUE constraint, so enforce
-- the singleton FINAL_VIDEO role explicitly at the database boundary.
CREATE UNIQUE INDEX idx_render_job_one_final
  ON render_job_artifacts(render_job_id)
  WHERE artifact_role = 'FINAL_VIDEO';

CREATE FUNCTION require_render_artifact_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job_content uuid;
DECLARE asset_content uuid;
DECLARE asset_state text;
DECLARE selected_kind text;
BEGIN
  SELECT content_id INTO job_content FROM render_jobs
    WHERE id = NEW.render_job_id FOR SHARE;
  SELECT a.content_id, a.retention_state, a.asset_kind
    INTO asset_content, asset_state, selected_kind
    FROM assets AS a WHERE a.id = NEW.asset_id FOR SHARE;
  IF job_content IS NULL OR asset_content IS NULL OR asset_content <> job_content
     OR asset_state <> 'ACTIVE' OR selected_kind <> NEW.artifact_role THEN
    RAISE EXCEPTION 'render artifact is outside active job lineage'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER render_job_artifact_lineage
  BEFORE INSERT OR UPDATE ON render_job_artifacts
  FOR EACH ROW EXECUTE FUNCTION require_render_artifact_lineage();

CREATE FUNCTION require_render_final_same_content() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE asset_content uuid;
DECLARE asset_state text;
DECLARE selected_kind text;
BEGIN
  IF NEW.final_asset_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT a.content_id, a.retention_state, a.asset_kind
    INTO asset_content, asset_state, selected_kind
    FROM assets AS a WHERE a.id = NEW.final_asset_id FOR SHARE;
  IF asset_content IS NULL OR asset_content <> NEW.content_id
     OR asset_state <> 'ACTIVE' OR selected_kind <> 'FINAL_VIDEO' THEN
    RAISE EXCEPTION 'render final asset is outside active job lineage'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM render_job_artifacts AS rja
    WHERE rja.render_job_id = NEW.id
      AND rja.asset_id = NEW.final_asset_id
      AND rja.artifact_role = 'FINAL_VIDEO'
  ) THEN
    RAISE EXCEPTION 'render final asset is not registered for this job'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER render_jobs_final_same_content
  BEFORE INSERT OR UPDATE OF content_id, final_asset_id ON render_jobs
  FOR EACH ROW EXECUTE FUNCTION require_render_final_same_content();
