import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type ReadinessPayload = {
  status: "ready" | "not_ready";
  checks: Record<string, { status: string }>;
};

function isReadinessPayload(value: unknown): value is ReadinessPayload {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.status !== "ready" && candidate.status !== "not_ready") return false;
  if (!candidate.checks || typeof candidate.checks !== "object" || Array.isArray(candidate.checks)) return false;
  return Object.values(candidate.checks).every(
    (check) => !!check && typeof check === "object" && typeof (check as Record<string, unknown>).status === "string",
  );
}

export async function GET() {
  const baseUrl = process.env.FLOWX_API_BASE_URL;
  if (!baseUrl) {
    return NextResponse.json({ state: "unavailable", reason: "api_not_configured" }, { status: 503 });
  }

  let healthUrl: URL;
  let readinessUrl: URL;
  try {
    healthUrl = new URL("/healthz", baseUrl);
    readinessUrl = new URL("/readyz", baseUrl);
    if (healthUrl.protocol !== "http:" && healthUrl.protocol !== "https:") throw new Error("invalid protocol");
  } catch {
    return NextResponse.json({ state: "unavailable", reason: "api_configuration_invalid" }, { status: 503 });
  }

  const healthController = new AbortController();
  const healthTimeout = setTimeout(() => healthController.abort(), 4000);
  let healthResponse: Response;
  try {
    healthResponse = await fetch(healthUrl, { cache: "no-store", signal: healthController.signal });
    if (!healthResponse.ok) throw new Error("health_unavailable");
    const health: unknown = await healthResponse.json();
    if (!health || typeof health !== "object" || (health as Record<string, unknown>).status !== "alive" || (health as Record<string, unknown>).scope !== "process-only") {
      throw new Error("health_response_invalid");
    }
  } catch (error) {
    const reason = error instanceof Error && error.name === "AbortError" ? "api_timeout" : "api_unavailable";
    return NextResponse.json({ state: "unavailable", reason }, { status: 503 });
  } finally {
    clearTimeout(healthTimeout);
  }

  let readiness: ReadinessPayload | null = null;
  const readinessController = new AbortController();
  const readinessTimeout = setTimeout(() => readinessController.abort(), 4000);
  try {
    const readinessResponse = await fetch(readinessUrl, { cache: "no-store", signal: readinessController.signal });
    if (readinessResponse.ok || readinessResponse.status === 503) {
      const value: unknown = await readinessResponse.json();
      if (isReadinessPayload(value)) {
        const statusMatchesBody = value.status === "ready"
          ? readinessResponse.ok
          : readinessResponse.status === 503;
        if (statusMatchesBody) readiness = value;
      }
    }
  } catch {
    readiness = null;
  } finally {
    clearTimeout(readinessTimeout);
  }

  return NextResponse.json({ state: "connected", checkedAt: new Date().toISOString(), readiness });
}
