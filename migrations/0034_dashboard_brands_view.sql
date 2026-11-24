-- Complete the dashboard read boundary with a sanitized brand projection.

CREATE VIEW flowx_dashboard_brands WITH (security_barrier = true) AS
SELECT owner_user_id, id, name, timezone, niche, audience, created_at, updated_at
FROM brands;

COMMENT ON VIEW flowx_dashboard_brands IS
  'Dashboard-safe brand identity and operating context.';
