import { DashboardShell } from "../components/dashboard-shell";

export default function Home() {
  const now = new Date();
  const initialMonth = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
  return <DashboardShell initialMonth={initialMonth} />;
}
