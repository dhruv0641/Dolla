-- Preserve immutable storyboard snapshots and version each scene projection.
ALTER TABLE scenes
  ADD COLUMN storyboard_version integer NOT NULL DEFAULT 0
  CHECK (storyboard_version >= 0);

ALTER TABLE scenes
  DROP CONSTRAINT scenes_content_id_scene_index_key;

ALTER TABLE scenes
  ADD CONSTRAINT scenes_content_version_scene_index_key
  UNIQUE (content_id, storyboard_version, scene_index);

CREATE TABLE storyboard_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    version integer NOT NULL CHECK (version > 0),
    title text NOT NULL,
    total_duration_ms integer NOT NULL CHECK (total_duration_ms > 0),
    timeline_json jsonb NOT NULL CHECK (jsonb_typeof(timeline_json) = 'object'),
    created_by_user_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (content_id, version)
);
CREATE INDEX idx_storyboard_versions_content ON storyboard_versions(content_id, version DESC);
