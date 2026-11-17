-- FLOW AI CONTENT OS — reviewed PostgreSQL 15+ initial migration.
-- Based on the supplied reference logical schema; see docs/SCHEMA_REVIEW.md.
-- All timestamps UTC; local display timezone stored on brands.
-- Never store raw Gemini secrets, OAuth refresh tokens or Flow browser cookies here.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE brands (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    owner_user_id text NOT NULL,
    timezone text NOT NULL DEFAULT 'Asia/Kolkata',
    niche text NOT NULL DEFAULT '',
    audience text NOT NULL DEFAULT '',
    brand_bible jsonb NOT NULL DEFAULT '{}'::jsonb,
    autonomy_policy jsonb NOT NULL DEFAULT '{"auto_publish":false,"require_first_n_manual_approvals":20}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE flow_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alias text NOT NULL UNIQUE,
    owner_user_id text NOT NULL,
    credentials_ref text NOT NULL,
    mcp_adapter text NOT NULL,
    plan_name text,
    monthly_allowance_estimate integer CHECK (monthly_allowance_estimate >= 0),
    daily_allowance_estimate integer CHECK (daily_allowance_estimate >= 0),
    observed_monthly_available integer CHECK (observed_monthly_available >= 0),
    observed_daily_available integer CHECK (observed_daily_available >= 0),
    monthly_cycle_starts_at timestamptz,
    next_daily_reset_at timestamptz,
    last_reconciled_at timestamptz,
    session_health text NOT NULL DEFAULT 'UNVERIFIED'
      CHECK (session_health IN ('UNVERIFIED','HEALTHY','DEGRADED','EXPIRED','UNSUPPORTED')),
    paused boolean NOT NULL DEFAULT true,
    compliance_approved boolean NOT NULL DEFAULT false,
    max_inflight integer NOT NULL DEFAULT 1 CHECK (max_inflight > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE content_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id uuid NOT NULL REFERENCES brands(id),
    title text NOT NULL,
    idea_text text NOT NULL,
    topic text,
    audience_segment text,
    language text NOT NULL DEFAULT 'en-IN',
    target_duration_seconds integer NOT NULL DEFAULT 32 CHECK (target_duration_seconds BETWEEN 4 AND 180),
    status text NOT NULL DEFAULT 'IDEA' CHECK (status IN (
      'IDEA','RESEARCHED','BRIEF_READY','SCRIPT_READY','STORYBOARD_READY',
      'GENERATING','ASSEMBLING','QA_PENDING','NEEDS_REVIEW','READY','SCHEDULED',
      'PARTIALLY_PUBLISHED','PUBLISHED','FAILED','ARCHIVED')),
    priority smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    research jsonb NOT NULL DEFAULT '{}'::jsonb,
    brief jsonb NOT NULL DEFAULT '{}'::jsonb,
    script jsonb NOT NULL DEFAULT '{}'::jsonb,
    script_version integer NOT NULL DEFAULT 0 CHECK (script_version >= 0),
    storyboard_version integer NOT NULL DEFAULT 0 CHECK (storyboard_version >= 0),
    visual_bible jsonb NOT NULL DEFAULT '{}'::jsonb,
    credit_budget integer NOT NULL DEFAULT 0 CHECK (credit_budget >= 0),
    planned_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_content_brand_status ON content_items(brand_id, status, priority, created_at);

CREATE TABLE scenes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    scene_index integer NOT NULL CHECK (scene_index > 0),
    start_ms integer NOT NULL CHECK (start_ms >= 0),
    end_ms integer NOT NULL,
    beat text NOT NULL,
    narration_text text NOT NULL DEFAULT '',
    visual_prompt text NOT NULL,
    prompt_version integer NOT NULL DEFAULT 1 CHECK (prompt_version > 0),
    model_preference text,
    desired_output jsonb NOT NULL DEFAULT '{}'::jsonb,
    state text NOT NULL DEFAULT 'PENDING' CHECK (state IN (
      'PENDING','CREDIT_RESERVED','SUBMITTED','RUNNING','DOWNLOADED',
      'QA_FAILED','QA_PASSED','RETRY_WAIT','BLOCKED','FAILED')),
    approved_asset_id uuid,
    retry_count integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(content_id, scene_index),
    CHECK (end_ms > start_ms)
);
CREATE INDEX idx_scenes_content_state ON scenes(content_id, state);

CREATE TABLE assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid REFERENCES content_items(id),
    scene_id uuid REFERENCES scenes(id),
    asset_kind text NOT NULL CHECK (asset_kind IN (
      'RAW_FLOW_CLIP','NARRATION','CAPTION_SRT','THUMBNAIL','FINAL_VIDEO',
      'EXPORT_VARIANT','REFERENCE_IMAGE','MUSIC_LICENSED','OTHER')),
    storage_uri text NOT NULL,
    sha256_hex char(64) NOT NULL,
    mime_type text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_job_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(storage_uri)
);
CREATE INDEX idx_assets_content_kind ON assets(content_id, asset_kind, created_at DESC);
ALTER TABLE scenes ADD CONSTRAINT scenes_approved_asset_fk FOREIGN KEY (approved_asset_id) REFERENCES assets(id);

CREATE TABLE generation_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_id uuid NOT NULL REFERENCES scenes(id),
    flow_account_id uuid NOT NULL REFERENCES flow_accounts(id),
    attempt_index integer NOT NULL CHECK (attempt_index >= 1),
    idempotency_fingerprint char(64) NOT NULL UNIQUE,
    external_job_id text,
    request_json jsonb NOT NULL,
    response_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quoted_credits integer NOT NULL DEFAULT 0 CHECK (quoted_credits >= 0),
    actual_credits integer CHECK (actual_credits >= 0),
    status text NOT NULL DEFAULT 'CREATED' CHECK (status IN (
      'CREATED','RESERVED','SUBMITTED','REMOTE_SUBMISSION_UNKNOWN',
      'RUNNING','DOWNLOADED','QA_PASSED','QA_FAILED',
      'COST_RECONCILE_PENDING','FAILED','CANCELLED')),
    error_code text,
    error_message text,
    submitted_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(scene_id, attempt_index)
);
CREATE INDEX idx_generation_account_status ON generation_jobs(flow_account_id, status);
CREATE UNIQUE INDEX idx_generation_external_job ON generation_jobs(flow_account_id, external_job_id)
  WHERE external_job_id IS NOT NULL;

-- Preserve the generation lineage for assets while allowing their storage
-- metadata to remain after a generation job is archived/deleted only if the
-- deletion policy is explicitly changed in a future reviewed migration.
ALTER TABLE assets ADD CONSTRAINT assets_source_job_fk
  FOREIGN KEY (source_job_id) REFERENCES generation_jobs(id);

CREATE TABLE flow_credit_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_account_id uuid NOT NULL REFERENCES flow_accounts(id),
    generation_job_id uuid REFERENCES generation_jobs(id),
    wallet_type text NOT NULL CHECK (wallet_type IN ('DAILY','MONTHLY','PURCHASED','UNKNOWN')),
    action text NOT NULL CHECK (action IN ('RESERVE','CONSUME','RELEASE','ADJUST','RESET','RECONCILE')),
    credit_delta integer NOT NULL,
    source text NOT NULL CHECK (source IN ('FLOW_OBSERVED','MODEL_QUOTE','SYSTEM_ESTIMATE','HUMAN_ADJUSTMENT')),
    external_receipt text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_credit_account_time ON flow_credit_entries(flow_account_id, created_at DESC);

CREATE TABLE qa_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid REFERENCES content_items(id),
    scene_id uuid REFERENCES scenes(id),
    asset_id uuid NOT NULL REFERENCES assets(id),
    version text NOT NULL DEFAULT 'v1',
    score numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    hard_blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
    checks jsonb NOT NULL DEFAULT '{}'::jsonb,
    decision text NOT NULL CHECK (decision IN ('PASS','FAIL','NEEDS_HUMAN')),
    reviewer_type text NOT NULL CHECK (reviewer_type IN ('AUTO','HUMAN')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (content_id IS NOT NULL OR scene_id IS NOT NULL)
);
CREATE INDEX idx_qa_asset_time ON qa_reports(asset_id, created_at DESC);

CREATE TABLE render_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid NOT NULL REFERENCES content_items(id),
    render_version integer NOT NULL CHECK (render_version > 0),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','RUNNING','DONE','FAILED')),
    inputs_manifest jsonb NOT NULL,
    command_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
    final_asset_id uuid REFERENCES assets(id),
    error_log text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE(content_id, render_version)
);

CREATE TABLE review_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid NOT NULL REFERENCES content_items(id),
    asset_id uuid REFERENCES assets(id),
    reviewer_user_id text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('APPROVE','REJECT','CHANGES_REQUIRED')),
    reason text,
    approval_scope text NOT NULL DEFAULT 'FINAL_VIDEO',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE social_channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id uuid NOT NULL REFERENCES brands(id),
    platform text NOT NULL CHECK (platform IN ('YOUTUBE','INSTAGRAM','FACEBOOK')),
    external_channel_id text NOT NULL,
    display_name text NOT NULL,
    credentials_ref text NOT NULL,
    permissions_status text NOT NULL DEFAULT 'UNVERIFIED'
      CHECK (permissions_status IN ('UNVERIFIED','VALID','EXPIRED','REVOKED','INSUFFICIENT')),
    enabled boolean NOT NULL DEFAULT false,
    default_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(platform, external_channel_id)
);

CREATE TABLE publication_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_id uuid NOT NULL REFERENCES content_items(id),
    channel_id uuid NOT NULL REFERENCES social_channels(id),
    asset_id uuid NOT NULL REFERENCES assets(id),
    artifact_version integer NOT NULL CHECK (artifact_version > 0),
    schedule_at_utc timestamptz,
    platform_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
      'DRAFT','SCHEDULED','UPLOAD_STARTED','PROCESSING','PUBLISH_REQUESTED',
      'PUBLISHED','VERIFY_PENDING','FAILED','CANCELLED')),
    remote_upload_id text,
    remote_post_id text,
    remote_url text,
    last_remote_status jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error_code text,
    last_error_message text,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(content_id, channel_id, artifact_version)
);
CREATE INDEX idx_publications_due ON publication_jobs(status, schedule_at_utc);
CREATE UNIQUE INDEX idx_publication_remote_id ON publication_jobs(channel_id, remote_post_id)
 WHERE remote_post_id IS NOT NULL;

CREATE TABLE analytics_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_job_id uuid NOT NULL REFERENCES publication_jobs(id),
    observed_at timestamptz NOT NULL,
    window_name text NOT NULL CHECK (window_name IN ('1H','24H','72H','7D','28D','CUSTOM')),
    metric_data jsonb NOT NULL,
    metric_definitions_version text NOT NULL,
    collection_status text NOT NULL DEFAULT 'OK'
      CHECK (collection_status IN ('OK','PARTIAL','ERROR')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(publication_job_id, observed_at, window_name)
);
CREATE INDEX idx_analytics_post_observed ON analytics_snapshots(publication_job_id, observed_at DESC);

CREATE TABLE agent_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id uuid REFERENCES brands(id),
    content_id uuid REFERENCES content_items(id),
    agent_role text NOT NULL,
    backend_model text NOT NULL,
    model_version text,
    prompt_version text NOT NULL,
    input_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    output_data jsonb,
    output_schema_version text,
    token_usage jsonb,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    requires_human boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK (status IN ('RUNNING','DONE','FAILED','BLOCKED')),
    error_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX idx_agent_runs_content_time ON agent_runs(content_id, created_at DESC);

CREATE TABLE workflow_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    event_name text NOT NULL,
    correlation_id uuid NOT NULL,
    actor text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_workflow_events_entity ON workflow_events(entity_type, entity_id, created_at DESC);

CREATE TABLE outbox_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_name text NOT NULL,
    correlation_id uuid NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'READY' CHECK (status IN ('READY','LEASED','DONE','DEAD','CANCELLED')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
    run_after timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_until timestamptz,
    error_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_outbox_due ON outbox_jobs(status, run_after)
 WHERE status IN ('READY','LEASED');

-- Optional dedup tracking for audience/idea research.
CREATE TABLE content_recommendations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id uuid NOT NULL REFERENCES brands(id),
    source_period_start date NOT NULL,
    source_period_end date NOT NULL,
    recommendation_json jsonb NOT NULL,
    supporting_publication_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
    status text NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED','ACCEPTED','REJECTED','COMPLETED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_period_end >= source_period_start)
);

-- Example safe work leasing (execute in a transaction, after reclaiming expired leases):
-- WITH selected AS (
--   SELECT id FROM outbox_jobs
--   WHERE (status = 'READY' OR (status='LEASED' AND lease_until < now()))
--     AND run_after <= now()
--   ORDER BY run_after, created_at
--   FOR UPDATE SKIP LOCKED LIMIT 10
-- )
-- UPDATE outbox_jobs j
-- SET status='LEASED', lease_owner=$1, lease_until=now()+interval '2 minutes',
--     attempt_count=j.attempt_count+1, updated_at=now()
-- FROM selected WHERE j.id=selected.id RETURNING j.*;
