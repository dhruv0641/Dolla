import { lstat, readFile, realpath } from "node:fs/promises";
import { posix } from "node:path";
import { NextResponse } from "next/server";
import type { DashboardSnapshot, ReadinessPayload } from "../../../lib/dashboard-types";

export const dynamic = "force-dynamic";

function isReadinessPayload(value: unknown): value is ReadinessPayload {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (candidate.status === "ready" || candidate.status === "not_ready")
    && !!candidate.checks && typeof candidate.checks === "object" && !Array.isArray(candidate.checks);
}

function isDashboardSnapshot(value: unknown): value is DashboardSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  const arrays = ["content", "activity", "flow_accounts", "credit_entries", "credit_reservations", "generation_jobs", "scenes", "assets", "qa_reports", "review_decisions", "voice_profiles", "tts_requests", "publication_channels", "publication_jobs", "agent_runs", "analytics_observations", "community_comments", "community_reply_drafts", "brands"];
  return typeof candidate.generated_at === "string" && typeof candidate.owner_user_id === "string"
    && !!candidate.overview && typeof candidate.overview === "object"
    && !!candidate.pipeline_counts && typeof candidate.pipeline_counts === "object"
    && arrays.every((name) => Array.isArray(candidate[name]));
}

async function readDashboardToken(reference: string | undefined) {
  const prefix = "secretref://file";
  if (!reference?.startsWith(`${prefix}/`)) throw new Error("dashboard_secret_not_configured");
  const normalized = posix.normalize(reference.slice(prefix.length));
  if (!normalized.startsWith("/run/secrets/dashboard_service/") || normalized.includes("..")) throw new Error("dashboard_secret_invalid");
  const metadata = await lstat(normalized);
  if (!metadata.isFile() || metadata.isSymbolicLink()) throw new Error("dashboard_secret_invalid");
  const resolved = await realpath(normalized);
  if (!resolved.startsWith("/run/secrets/dashboard_service/")) throw new Error("dashboard_secret_invalid");
  const token = (await readFile(resolved, "utf8")).trim();
  if (token.length < 32 || token.length > 512 || /[\r\n\0]/u.test(token)) throw new Error("dashboard_secret_invalid");
  return token;
}

async function timedFetch(url: URL, init: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try { return await fetch(url, { ...init, cache: "no-store", signal: controller.signal }); }
  finally { clearTimeout(timeout); }
}

export async function GET() {
  const baseUrl = process.env.FLOWX_API_BASE_URL;
  if (!baseUrl) return NextResponse.json({ state: "unavailable", reason: "api_not_configured" }, { status: 503 });
  let healthUrl: URL; let readinessUrl: URL; let dashboardUrl: URL;
  try {
    healthUrl = new URL("/healthz", baseUrl); readinessUrl = new URL("/readyz", baseUrl); dashboardUrl = new URL("/api/v1/dashboard", baseUrl);
    if (!["http:", "https:"].includes(healthUrl.protocol)) throw new Error("invalid protocol");
  } catch { return NextResponse.json({ state: "unavailable", reason: "api_configuration_invalid" }, { status: 503 }); }

  try {
    const response = await timedFetch(healthUrl);
    const health: unknown = response.ok ? await response.json() : null;
    if (!health || typeof health !== "object" || (health as Record<string, unknown>).status !== "alive" || (health as Record<string, unknown>).scope !== "process-only") throw new Error("health_invalid");
  } catch (error) {
    return NextResponse.json({ state: "unavailable", reason: error instanceof Error && error.name === "AbortError" ? "api_timeout" : "api_unavailable" }, { status: 503 });
  }

  let readiness: ReadinessPayload | null = null;
  try {
    const response = await timedFetch(readinessUrl);
    const value: unknown = await response.json();
    if ((response.ok || response.status === 503) && isReadinessPayload(value)) readiness = value;
  } catch { readiness = null; }

  let dashboard: DashboardSnapshot | null = null;
  let dashboardReason: string | null = null;
  try {
    const token = await readDashboardToken(process.env.FLOWX_DASHBOARD_SERVICE_CREDENTIALS_REF);
    const response = await timedFetch(dashboardUrl, { headers: { "X-FlowX-Dashboard-Token": token } });
    const value: unknown = await response.json();
    if (!response.ok || !isDashboardSnapshot(value)) throw new Error(response.ok ? "dashboard_response_invalid" : `dashboard_http_${response.status}`);
    dashboard = value;
  } catch (error) { dashboardReason = error instanceof Error ? error.message : "dashboard_unavailable"; }

  return NextResponse.json({ state: "connected", checkedAt: new Date().toISOString(), readiness, dashboard, dashboardReason });
}
