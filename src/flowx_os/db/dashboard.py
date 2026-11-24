"""Bounded, sanitized owner-scoped dashboard snapshot queries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flowx_os.db.transaction import ConnectionPool, unit_of_work


class DashboardUnavailable(RuntimeError):
    """Raised when the verified dashboard snapshot cannot be loaded."""


class DashboardRepository:
    """Read the dashboard contract from sanitized PostgreSQL views only."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    async def snapshot(self, *, owner_user_id: str) -> dict[str, Any]:
        if not isinstance(owner_user_id, str) or not owner_user_id.strip() or len(owner_user_id) > 200:
            raise ValueError("owner_user_id must be a non-empty string of at most 200 characters")
        owner = owner_user_id.strip()
        query = """
        WITH requested AS (SELECT %s::text AS owner_user_id),
        content_rows AS (
          SELECT * FROM flowx_dashboard_content
          WHERE owner_user_id = (SELECT owner_user_id FROM requested)
          ORDER BY updated_at DESC, id LIMIT 200
        ), publication_rows AS (
          SELECT * FROM flowx_dashboard_publications
          WHERE owner_user_id = (SELECT owner_user_id FROM requested)
          ORDER BY created_at DESC, id LIMIT 200
        )
        SELECT jsonb_build_object(
          'generated_at', now(),
          'owner_user_id', (SELECT owner_user_id FROM requested),
          'overview', jsonb_build_object(
            'content_in_pipeline', (SELECT count(*) FROM content_rows WHERE status NOT IN ('ARCHIVED', 'PUBLISHED')),
            'ready_for_review', (SELECT count(*) FROM content_rows WHERE status IN ('QA_PENDING', 'NEEDS_REVIEW', 'READY')),
            'scheduled_this_week', (SELECT count(*) FROM publication_rows WHERE schedule_at_utc >= now() AND schedule_at_utc < now() + interval '7 days'),
            'published_videos', (SELECT count(DISTINCT content_id) FROM publication_rows WHERE status = 'PUBLISHED')
          ),
          'pipeline_counts', COALESCE((SELECT jsonb_object_agg(status, count_value) FROM (SELECT status, count(*) AS count_value FROM content_rows GROUP BY status) AS counts), '{}'::jsonb),
          'content', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM content_rows AS row_value), '[]'::jsonb),
          'activity', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_activity WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 50) AS row_value), '[]'::jsonb),
          'flow_accounts', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_flow_accounts WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at, id LIMIT 20) AS row_value), '[]'::jsonb),
          'credit_entries', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_credit_entries WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'credit_reservations', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_credit_reservations WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'generation_jobs', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_generation_jobs WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'scenes', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_scenes WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY updated_at DESC, id LIMIT 300) AS row_value), '[]'::jsonb),
          'assets', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_assets WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 300) AS row_value), '[]'::jsonb),
          'qa_reports', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_qa WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'review_decisions', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_reviews WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'voice_profiles', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_voice_profiles WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 100) AS row_value), '[]'::jsonb),
          'tts_requests', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_tts WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'publication_channels', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_channels WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at, id LIMIT 100) AS row_value), '[]'::jsonb),
          'publication_jobs', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM publication_rows AS row_value), '[]'::jsonb),
          'agent_runs', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_agent_runs WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'analytics_observations', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_analytics WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY observed_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'community_comments', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_comments WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY provider_updated_at DESC, id LIMIT 200) AS row_value), '[]'::jsonb),
          'community_reply_drafts', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_reply_drafts WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY created_at DESC, request_id LIMIT 200) AS row_value), '[]'::jsonb),
          'brands', COALESCE((SELECT jsonb_agg(to_jsonb(row_value)) FROM (SELECT * FROM flowx_dashboard_brands WHERE owner_user_id = (SELECT owner_user_id FROM requested) ORDER BY updated_at DESC, id LIMIT 100) AS row_value), '[]'::jsonb)
        )
        """
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(query, (owner,))
                row = await cursor.fetchone()
        except Exception as exc:
            raise DashboardUnavailable("dashboard snapshot is unavailable") from exc
        if row is None or not isinstance(row[0], dict):
            raise DashboardUnavailable("dashboard snapshot returned no document")
        result: dict[str, Any] = row[0]
        generated = result.get("generated_at")
        if isinstance(generated, datetime):
            result["generated_at"] = generated.astimezone(timezone.utc).isoformat()
        return result
