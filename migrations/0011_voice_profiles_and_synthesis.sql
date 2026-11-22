-- Immutable local voice profiles and replay-safe narration synthesis records.
-- Narration text is not persisted here; only its request fingerprint is stored.
CREATE TABLE voice_profiles (
    id uuid PRIMARY KEY,
    brand_id uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name text NOT NULL,
    engine_name text NOT NULL,
    engine_version text NOT NULL,
    voice_key text NOT NULL,
    language text NOT NULL,
    sample_rate_hz integer NOT NULL CHECK (sample_rate_hz BETWEEN 8000 AND 96000),
    channels smallint NOT NULL CHECK (channels BETWEEN 1 AND 2),
    source text NOT NULL CHECK (source = 'LOCAL_BUILTIN'),
    license_status text NOT NULL CHECK (license_status IN ('VERIFIED','UNVERIFIED','REJECTED')),
    license_reference text,
    consent_status text NOT NULL CHECK (consent_status IN ('NOT_REQUIRED','VERIFIED','MISSING','REVOKED')),
    consent_reference text,
    active boolean NOT NULL DEFAULT true,
    config_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (license_status <> 'VERIFIED' OR license_reference IS NOT NULL),
    CHECK (consent_status <> 'VERIFIED' OR consent_reference IS NOT NULL),
    UNIQUE (brand_id, name),
    UNIQUE (id, brand_id)
);

CREATE TABLE tts_synthesis_requests (
    id uuid PRIMARY KEY,
    asset_id uuid NOT NULL UNIQUE,
    profile_id uuid NOT NULL,
    brand_id uuid NOT NULL,
    content_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    scene_id uuid,
    request_fingerprint char(64) NOT NULL UNIQUE CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    profile_snapshot jsonb NOT NULL,
    status text NOT NULL DEFAULT 'CLAIMED' CHECK (status IN ('CLAIMED','COMPLETED','FAILED')),
    completed_asset_id uuid REFERENCES assets(id),
    duration_ms integer CHECK (duration_ms > 0),
    sample_rate_hz integer CHECK (sample_rate_hz BETWEEN 8000 AND 96000),
    channels smallint CHECK (channels BETWEEN 1 AND 2),
    sample_width_bytes smallint CHECK (sample_width_bytes BETWEEN 1 AND 4),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    FOREIGN KEY (profile_id, brand_id) REFERENCES voice_profiles(id, brand_id),
    FOREIGN KEY (scene_id, content_id) REFERENCES scenes(id, content_id),
    CHECK (scene_id IS NULL OR content_id IS NOT NULL),
    CHECK (
      (status = 'COMPLETED' AND completed_asset_id = asset_id AND duration_ms IS NOT NULL
       AND sample_rate_hz IS NOT NULL AND channels IS NOT NULL
       AND sample_width_bytes IS NOT NULL AND completed_at IS NOT NULL AND error_code IS NULL)
      OR (status = 'CLAIMED' AND completed_asset_id IS NULL AND duration_ms IS NULL
          AND sample_rate_hz IS NULL AND channels IS NULL AND sample_width_bytes IS NULL
          AND completed_at IS NULL AND error_code IS NULL)
      OR (status = 'FAILED' AND completed_asset_id IS NULL AND duration_ms IS NULL
          AND sample_rate_hz IS NULL AND channels IS NULL AND sample_width_bytes IS NULL
          AND completed_at IS NOT NULL AND error_code IS NOT NULL)
    )
);

CREATE INDEX idx_voice_profiles_brand_active ON voice_profiles(brand_id, active, name);
CREATE INDEX idx_tts_synthesis_content ON tts_synthesis_requests(content_id, created_at DESC);

CREATE FUNCTION enforce_voice_profile_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'active') IS DISTINCT FROM (to_jsonb(OLD) - 'active')
     OR (OLD.active = false AND NEW.active = true) THEN
    RAISE EXCEPTION 'voice profile configuration is immutable' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER voice_profile_immutable BEFORE UPDATE ON voice_profiles
  FOR EACH ROW EXECUTE FUNCTION enforce_voice_profile_immutable();
