import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DashboardShell } from "../components/dashboard-shell";
import type { PolicyDefaults } from "../components/operations-views";

export default function Home() {
  const now = new Date();
  const initialMonth = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
  const policyRegistry = JSON.parse(readFileSync(resolve(process.cwd(), "../config/prompt_registry.json"), "utf8")) as { policy: PolicyDefaults };
  return <DashboardShell initialMonth={initialMonth} policyDefaults={policyRegistry.policy} />;
}
