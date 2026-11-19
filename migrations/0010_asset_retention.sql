-- Keep lineage after a local payload is retired. No deletion is automatic.
ALTER TABLE assets
  ADD COLUMN retention_state text NOT NULL DEFAULT 'ACTIVE'
    CHECK (retention_state IN ('ACTIVE', 'TOMBSTONED', 'PURGE_PENDING', 'PURGED')),
  ADD COLUMN retention_reason text,
  ADD COLUMN retention_actor text,
  ADD COLUMN tombstoned_at timestamptz,
  ADD COLUMN purged_at timestamptz,
  ADD CONSTRAINT assets_retention_state_dates CHECK (
    (retention_state = 'ACTIVE' AND tombstoned_at IS NULL AND purged_at IS NULL)
    OR (retention_state IN ('TOMBSTONED', 'PURGE_PENDING') AND tombstoned_at IS NOT NULL AND purged_at IS NULL)
    OR (retention_state = 'PURGED' AND tombstoned_at IS NOT NULL AND purged_at IS NOT NULL)
  );

CREATE INDEX idx_assets_owner_search ON assets(content_id, created_at DESC, id DESC)
  WHERE retention_state = 'ACTIVE';
CREATE INDEX idx_assets_retention_queue ON assets(tombstoned_at, id)
  WHERE retention_state IN ('TOMBSTONED', 'PURGE_PENDING');

-- Serialize new FK references with retirement; never point at absent payloads.
CREATE FUNCTION require_active_asset_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE referenced_id uuid;
DECLARE current_state text;
BEGIN
  referenced_id := (to_jsonb(NEW) ->> TG_ARGV[0])::uuid;
  IF referenced_id IS NOT NULL THEN
    -- Lock the row even when ACTIVE so retirement cannot overtake this write.
    SELECT retention_state INTO current_state FROM assets
      WHERE id = referenced_id FOR SHARE;
    IF current_state IS NOT NULL AND current_state <> 'ACTIVE' THEN
      RAISE EXCEPTION 'asset is retired' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER scenes_approved_asset_active BEFORE INSERT OR UPDATE OF approved_asset_id ON scenes
  FOR EACH ROW EXECUTE FUNCTION require_active_asset_reference('approved_asset_id');
CREATE TRIGGER qa_reports_asset_active BEFORE INSERT OR UPDATE OF asset_id ON qa_reports
  FOR EACH ROW EXECUTE FUNCTION require_active_asset_reference('asset_id');
CREATE TRIGGER review_decisions_asset_active BEFORE INSERT OR UPDATE OF asset_id ON review_decisions
  FOR EACH ROW EXECUTE FUNCTION require_active_asset_reference('asset_id');
CREATE TRIGGER publication_jobs_asset_active BEFORE INSERT OR UPDATE OF asset_id ON publication_jobs
  FOR EACH ROW EXECUTE FUNCTION require_active_asset_reference('asset_id');
CREATE TRIGGER render_jobs_final_asset_active BEFORE INSERT OR UPDATE OF final_asset_id ON render_jobs
  FOR EACH ROW EXECUTE FUNCTION require_active_asset_reference('final_asset_id');

-- Legacy free-form render manifests cannot prove asset lineage. Fail the
-- migration until they have been audited and migrated by an operator.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM render_jobs) THEN
    RAISE EXCEPTION 'existing render manifests require migration before asset retention';
  END IF;
END $$;

-- Future render inputs are an exact, bounded list of same-content active IDs.
-- Other command parameters belong in command_manifest.
CREATE FUNCTION require_normalized_render_assets() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE candidate text;
DECLARE current_content uuid;
DECLARE current_state text;
BEGIN
  PERFORM 1 FROM content_items WHERE id = NEW.content_id FOR SHARE;
  IF jsonb_typeof(NEW.inputs_manifest) <> 'object'
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.inputs_manifest)) <> 1
     OR NOT (NEW.inputs_manifest ? 'asset_ids')
     OR jsonb_typeof(NEW.inputs_manifest->'asset_ids') <> 'array'
     OR jsonb_array_length(NEW.inputs_manifest->'asset_ids') NOT BETWEEN 1 AND 100 THEN
    RAISE EXCEPTION 'render inputs require bounded asset_ids only' USING ERRCODE = 'check_violation';
  END IF;
  FOR candidate IN SELECT jsonb_array_elements_text(NEW.inputs_manifest->'asset_ids') LOOP
    IF candidate !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
      RAISE EXCEPTION 'render asset ID is not canonical' USING ERRCODE = 'check_violation';
    END IF;
    SELECT content_id, retention_state INTO current_content, current_state
      FROM assets WHERE id = candidate::uuid FOR SHARE;
    IF current_content IS NULL OR current_content <> NEW.content_id OR current_state <> 'ACTIVE' THEN
      RAISE EXCEPTION 'render input asset is unavailable' USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER render_jobs_normalized_assets BEFORE INSERT OR UPDATE OF content_id, inputs_manifest ON render_jobs
  FOR EACH ROW EXECUTE FUNCTION require_normalized_render_assets();

CREATE FUNCTION prevent_retired_content_reactivation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'ARCHIVED' AND NEW.status <> 'ARCHIVED'
     AND EXISTS (SELECT 1 FROM assets WHERE content_id = OLD.id
                 AND retention_state <> 'ACTIVE' FOR SHARE) THEN
    RAISE EXCEPTION 'archived content has retired assets' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER content_retired_asset_reactivation BEFORE UPDATE OF status ON content_items
  FOR EACH ROW EXECUTE FUNCTION prevent_retired_content_reactivation();
