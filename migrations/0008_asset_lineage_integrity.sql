-- Enforce that stored asset relationships form one content/scene/job lineage.
ALTER TABLE scenes
  ADD CONSTRAINT scenes_id_content_unique UNIQUE (id, content_id);

ALTER TABLE generation_jobs
  ADD CONSTRAINT generation_jobs_id_scene_unique UNIQUE (id, scene_id);

ALTER TABLE assets
  ADD CONSTRAINT assets_scene_requires_content
    CHECK (scene_id IS NULL OR content_id IS NOT NULL),
  ADD CONSTRAINT assets_job_requires_scene
    CHECK (source_job_id IS NULL OR scene_id IS NOT NULL),
  ADD CONSTRAINT assets_sha256_hex_format
    CHECK (sha256_hex ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT assets_scene_content_fk
    FOREIGN KEY (scene_id, content_id) REFERENCES scenes(id, content_id),
  ADD CONSTRAINT assets_job_scene_fk
    FOREIGN KEY (source_job_id, scene_id) REFERENCES generation_jobs(id, scene_id);

CREATE INDEX idx_assets_scene_created ON assets(scene_id, created_at DESC)
  WHERE scene_id IS NOT NULL;
CREATE INDEX idx_assets_source_job ON assets(source_job_id)
  WHERE source_job_id IS NOT NULL;
