export type DashboardRecord = Record<string, unknown>;

export type DashboardSnapshot = {
  generated_at: string;
  owner_user_id: string;
  overview: Record<string, number>;
  pipeline_counts: Record<string, number>;
  content: DashboardRecord[];
  activity: DashboardRecord[];
  flow_accounts: DashboardRecord[];
  credit_entries: DashboardRecord[];
  credit_reservations: DashboardRecord[];
  generation_jobs: DashboardRecord[];
  scenes: DashboardRecord[];
  assets: DashboardRecord[];
  qa_reports: DashboardRecord[];
  review_decisions: DashboardRecord[];
  voice_profiles: DashboardRecord[];
  tts_requests: DashboardRecord[];
  publication_channels: DashboardRecord[];
  publication_jobs: DashboardRecord[];
  agent_runs: DashboardRecord[];
  analytics_observations: DashboardRecord[];
  community_comments: DashboardRecord[];
  community_reply_drafts: DashboardRecord[];
  brands: DashboardRecord[];
};

export type ReadinessPayload = {
  status: "ready" | "not_ready";
  checks: Record<string, { status: string }>;
};

export type DashboardStatus =
  | { state: "connected"; checkedAt: string; readiness: ReadinessPayload | null; dashboard: DashboardSnapshot | null; dashboardReason: string | null }
  | { state: "unavailable"; reason: string };

export function textField(record: DashboardRecord, field: string, fallback = "—") {
  const value = record[field];
  return typeof value === "string" && value.trim() ? value : fallback;
}

export function numberField(record: DashboardRecord, field: string) {
  const value = record[field];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
