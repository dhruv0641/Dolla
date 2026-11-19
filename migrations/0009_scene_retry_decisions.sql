-- Persist the retry decision with the failed generation attempt for idempotent closeout.
ALTER TABLE generation_jobs
  ADD COLUMN retry_scheduled boolean NOT NULL DEFAULT false,
  ADD CONSTRAINT generation_jobs_retry_scheduled_failed
    CHECK (NOT retry_scheduled OR status = 'FAILED');

CREATE INDEX idx_generation_jobs_scene_attempt_status
  ON generation_jobs(scene_id, attempt_index, status);
