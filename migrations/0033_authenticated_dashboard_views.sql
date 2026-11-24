-- Sanitized owner-scoped read models for the local operations dashboard.

CREATE VIEW flowx_dashboard_content WITH (security_barrier = true) AS
SELECT b.owner_user_id, b.id AS brand_id, b.name AS brand_name, b.timezone,
       c.id, c.title, c.topic, c.language, c.target_duration_seconds,
       c.status, c.priority, c.planned_at, c.created_at, c.updated_at
FROM content_items AS c
JOIN brands AS b ON b.id = c.brand_id;

CREATE VIEW flowx_dashboard_activity WITH (security_barrier = true) AS
SELECT b.owner_user_id, e.id, e.entity_type, e.entity_id, e.event_name,
       e.actor, e.created_at
FROM workflow_events AS e
JOIN content_items AS c ON e.entity_type = 'content' AND e.entity_id = c.id
JOIN brands AS b ON b.id = c.brand_id
UNION ALL
SELECT b.owner_user_id, e.id, e.entity_type, e.entity_id, e.event_name,
       e.actor, e.created_at
FROM workflow_events AS e
JOIN brands AS b ON e.entity_type = 'brand' AND e.entity_id = b.id;

CREATE VIEW flowx_dashboard_flow_accounts WITH (security_barrier = true) AS
SELECT owner_user_id, id, alias, mcp_adapter, plan_name,
       observed_monthly_available, observed_daily_available,
       monthly_cycle_starts_at, next_daily_reset_at, last_reconciled_at,
       session_health, paused, compliance_approved, max_inflight, created_at
FROM flow_accounts;

CREATE VIEW flowx_dashboard_credit_entries WITH (security_barrier = true) AS
SELECT a.owner_user_id, e.id, e.flow_account_id, a.alias AS account_alias,
       e.generation_job_id, e.wallet_type, e.action, e.credit_delta,
       e.source, e.created_at
FROM flow_credit_entries AS e
JOIN flow_accounts AS a ON a.id = e.flow_account_id;

CREATE VIEW flowx_dashboard_credit_reservations WITH (security_barrier = true) AS
SELECT a.owner_user_id, r.id, r.flow_account_id, a.alias AS account_alias,
       r.request_id, r.model_name, r.duration_seconds, r.quoted_credits,
       r.quote_source, r.quoted_at, r.quote_expires_at, r.state, r.created_at
FROM flow_credit_reservations AS r
JOIN flow_accounts AS a ON a.id = r.flow_account_id;

CREATE VIEW flowx_dashboard_generation_jobs WITH (security_barrier = true) AS
SELECT b.owner_user_id, j.id, j.scene_id, s.content_id, c.title AS content_title,
       s.scene_index, a.alias AS account_alias, j.external_job_id,
       j.quoted_credits, j.actual_credits, j.status, j.error_code,
       j.submitted_at, j.completed_at, j.created_at
FROM generation_jobs AS j
JOIN scenes AS s ON s.id = j.scene_id
JOIN content_items AS c ON c.id = s.content_id
JOIN brands AS b ON b.id = c.brand_id
JOIN flow_accounts AS a ON a.id = j.flow_account_id;

CREATE VIEW flowx_dashboard_scenes WITH (security_barrier = true) AS
SELECT b.owner_user_id, s.id, s.content_id, c.title AS content_title,
       s.scene_index, s.start_ms, s.end_ms, s.beat, s.state,
       s.approved_asset_id, s.retry_count, s.storyboard_version,
       s.created_at, s.updated_at
FROM scenes AS s
JOIN content_items AS c ON c.id = s.content_id
JOIN brands AS b ON b.id = c.brand_id;

CREATE VIEW flowx_dashboard_assets WITH (security_barrier = true) AS
SELECT b.owner_user_id, a.id, a.content_id, c.title AS content_title,
       a.scene_id, a.asset_kind, a.mime_type, a.size_bytes,
       a.source_job_id, a.retention_state, a.created_at
FROM assets AS a
JOIN content_items AS c ON c.id = a.content_id
JOIN brands AS b ON b.id = c.brand_id;

CREATE VIEW flowx_dashboard_qa WITH (security_barrier = true) AS
SELECT b.owner_user_id, q.id, q.content_id, c.title AS content_title,
       q.scene_id, q.asset_id, q.version, q.score, q.decision,
       q.reviewer_type, q.created_at
FROM qa_reports AS q
JOIN content_items AS c ON c.id = q.content_id
JOIN brands AS b ON b.id = c.brand_id;

CREATE VIEW flowx_dashboard_reviews WITH (security_barrier = true) AS
SELECT b.owner_user_id, r.id, r.content_id, c.title AS content_title,
       r.asset_id, r.reviewer_user_id, r.decision, r.approval_scope,
       r.created_at
FROM review_decisions AS r
JOIN content_items AS c ON c.id = r.content_id
JOIN brands AS b ON b.id = c.brand_id;

CREATE VIEW flowx_dashboard_agent_runs WITH (security_barrier = true) AS
SELECT b.owner_user_id, a.id, a.brand_id, a.content_id, c.title AS content_title,
       a.agent_role, a.backend_model, a.model_version, a.prompt_version,
       a.token_usage, a.requires_human, a.status, a.created_at, a.completed_at
FROM agent_runs AS a
JOIN brands AS b ON b.id = a.brand_id
LEFT JOIN content_items AS c ON c.id = a.content_id;

CREATE VIEW flowx_dashboard_channels WITH (security_barrier = true) AS
SELECT b.owner_user_id, ch.id, ch.brand_id, b.name AS brand_name,
       ch.platform, ch.external_channel_id, ch.display_name,
       ch.permissions_status, ch.enabled, ch.created_at
FROM social_channels AS ch
JOIN brands AS b ON b.id = ch.brand_id;

CREATE VIEW flowx_dashboard_publications WITH (security_barrier = true) AS
SELECT b.owner_user_id, p.id, p.content_id, c.title AS content_title,
       ch.platform, ch.display_name AS channel_name, p.schedule_at_utc,
       p.status, p.remote_post_id, p.last_remote_status, p.published_at,
       p.created_at, p.last_verified_at
FROM publication_jobs AS p
JOIN content_items AS c ON c.id = p.content_id
JOIN brands AS b ON b.id = c.brand_id
JOIN social_channels AS ch ON ch.id = p.channel_id;

CREATE VIEW flowx_dashboard_analytics WITH (security_barrier = true) AS
SELECT owner_user_id, id, publication_id, platform, remote_object_id,
       window_name, window_started_at, window_ended_at, source,
       registry_version, metric_data, collection_status, observed_at, created_at
FROM analytics_metric_observations;

CREATE VIEW flowx_dashboard_comments WITH (security_barrier = true) AS
SELECT owner_user_id, id, publication_id, platform, remote_comment_id,
       parent_remote_comment_id, comment_text, state, published_at,
       provider_updated_at, created_at
FROM community_comments_current;

CREATE VIEW flowx_dashboard_reply_drafts WITH (security_barrier = true) AS
SELECT owner_user_id, request_id, publication_id, comment_version_id,
       disposition, escalation_priority, escalation_reasons, draft_text,
       human_approval_required, outbound_action_authorized, created_at
FROM community_reply_draft_records;

CREATE VIEW flowx_dashboard_voice_profiles WITH (security_barrier = true) AS
SELECT b.owner_user_id, v.id, v.brand_id, b.name AS brand_name, v.name,
       v.engine_name, v.engine_version, v.language, v.sample_rate_hz,
       v.channels, v.source, v.license_status, v.consent_status,
       v.active, v.created_at
FROM voice_profiles AS v
JOIN brands AS b ON b.id = v.brand_id;

CREATE VIEW flowx_dashboard_tts WITH (security_barrier = true) AS
SELECT b.owner_user_id, t.id, t.brand_id, t.content_id, c.title AS content_title,
       t.scene_id, t.profile_id, t.status, t.completed_asset_id,
       t.duration_ms, t.sample_rate_hz, t.channels, t.error_code,
       t.created_at, t.completed_at
FROM tts_synthesis_requests AS t
JOIN brands AS b ON b.id = t.brand_id
JOIN content_items AS c ON c.id = t.content_id;

COMMENT ON VIEW flowx_dashboard_flow_accounts IS
  'Dashboard-safe Flow account state; credential references are intentionally excluded.';
COMMENT ON VIEW flowx_dashboard_channels IS
  'Dashboard-safe social channel state; credential references and provider config are excluded.';
