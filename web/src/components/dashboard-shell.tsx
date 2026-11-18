"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ProductionBoard } from "./production-board";
import { FlowControl } from "./flow-control";

type DashboardStatus =
  | { state: "connected"; checkedAt: string; readiness: { status: "ready" | "not_ready"; checks: Record<string, { status: string }> } | null }
  | { state: "unavailable"; reason: string };

const sections = [
  {
    id: "overview",
    icon: "◈",
    title: "Executive overview",
    description: "One view of the content operation. Live metrics appear when verified dashboard data is available.",
  },
  {
    id: "pipeline",
    icon: "▦",
    title: "Production pipeline",
    description: "Ideas, scripts, scenes, renders, and approvals will be shown from the content lifecycle records.",
  },
  {
    id: "flow",
    icon: "◉",
    title: "Flow & credits",
    description: "Flow MCP capabilities and account balances are unverified. This workspace does not estimate live credits.",
  },
  {
    id: "quality",
    icon: "◇",
    title: "Video and voice QA",
    description: "Quality reports will appear after media checks and human review are connected.",
  },
  {
    id: "publishing",
    icon: "↗",
    title: "Publishing control",
    description: "Platform accounts, schedules, and remote verification are not connected to this screen.",
  },
  {
    id: "agents",
    icon: "♜",
    title: "AI content team",
    description: "Agent assignments and activity will be backed by workflow records, not illustrative sample data.",
  },
  {
    id: "analytics",
    icon: "⌁",
    title: "Growth analytics",
    description: "Native platform metrics and their definitions will appear when verified data is available.",
  },
  {
    id: "community",
    icon: "☏",
    title: "Community inbox",
    description: "Comments and response drafts will appear only after an authorized source is connected.",
  },
] as const;

type SectionId = (typeof sections)[number]["id"];

function UnavailableMetric({ label }: { label: string }) {
  return (
    <article className="metric-card" aria-label={`${label}: unavailable`}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value" aria-hidden="true">—</strong>
      <span className="metric-footnote">Unavailable · no verified data loaded</span>
    </article>
  );
}

function EmptyPanel({
  title,
  message,
  icon = "◇",
}: {
  title: string;
  message: string;
  icon?: string;
}) {
  return (
    <div className="empty-panel">
      <span className="empty-icon" aria-hidden="true">{icon}</span>
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
    </div>
  );
}

export function DashboardShell() {
  const [activeSection, setActiveSection] = useState<SectionId>("overview");
  const [dashboardStatus, setDashboardStatus] = useState<DashboardStatus>({ state: "unavailable", reason: "not_checked" });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const refreshInFlight = useRef(false);
  const section = sections.find((item) => item.id === activeSection) ?? sections[0];

  const refreshStatus = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setIsRefreshing(true);
    try {
      const response = await fetch("/api/dashboard-status", { cache: "no-store" });
      const value = await response.json() as DashboardStatus;
      setDashboardStatus(value);
    } catch {
      setDashboardStatus({ state: "unavailable", reason: "request_failed" });
    } finally {
      refreshInFlight.current = false;
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const timer = window.setInterval(() => void refreshStatus(), 60_000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  const statusLabel = dashboardStatus.state === "connected"
    ? dashboardStatus.readiness === null ? "API healthy · readiness unknown" : dashboardStatus.readiness.status === "ready" ? "API ready" : "API dependencies unavailable"
    : dashboardStatus.reason === "not_checked" ? "Checking API status" : "API unavailable";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="FLOW workspace navigation">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">F</span>
          <div>
            <div className="brand-name"><span>FLOW</span> Content OS</div>
            <p className="brand-caption">Production workspace</p>
          </div>
        </div>

        <p className="nav-heading">Workspace</p>
        <nav className="nav-list" aria-label="Workspace sections">
          {sections.map((item) => (
            <button
              className={`nav-item${activeSection === item.id ? " is-active" : ""}`}
              type="button"
              key={item.id}
              aria-current={activeSection === item.id ? "page" : undefined}
              aria-controls="workspace-view"
              onClick={() => setActiveSection(item.id)}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.title}</span>
              {item.id === "flow" && <span className="nav-indicator" aria-label="Unverified">!</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-status" role="note">
          <div className="sidebar-status-heading"><span className="status-dot" aria-hidden="true" />Live records only</div>
          <p>No sample counts, balances, posts, or performance metrics are displayed.</p>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb"><span>FLOW AI Content OS</span><span aria-hidden="true">/</span><strong>{section.title}</strong></div>
          <div className="system-status-group">
            <div className={`system-status${dashboardStatus.state === "connected" && dashboardStatus.readiness?.status === "ready" ? " system-status--ready" : ""}`} role="status" aria-live="polite">
              <span className="system-status-dot" aria-hidden="true" />
              <span>{statusLabel}</span>
            </div>
            <button className="refresh-button" type="button" onClick={() => void refreshStatus()} disabled={isRefreshing}>
              {isRefreshing ? "Checking…" : "Refresh"}
            </button>
          </div>
        </header>

        <main id="workspace-view" className="main-content" aria-live="polite">
          <section className="page-intro" aria-labelledby="page-title">
            <div>
              <p className="eyebrow">Operations workspace</p>
              <h1 id="page-title">{section.title}</h1>
              <p className="page-description">{section.description}</p>
            </div>
            <div className="environment-tag"><span className="environment-tag-dot" aria-hidden="true" />Application shell</div>
          </section>

          {activeSection === "overview" ? (
            <>
              <section className="metrics-grid" aria-label="Operational metrics">
                <UnavailableMetric label="Content in pipeline" />
                <UnavailableMetric label="Ready for review" />
                <UnavailableMetric label="Scheduled this week" />
                <UnavailableMetric label="Published videos" />
              </section>

              <div className="overview-grid">
                <section className="surface-card pipeline-card" aria-labelledby="pipeline-title">
                  <div className="card-heading">
                    <div>
                      <h2 id="pipeline-title">Production pipeline</h2>
                      <p>Current lifecycle stages</p>
                    </div>
                    <span className="subtle-tag">Live records only</span>
                  </div>
                  <div className="pipeline-stages">
                    {["Ideas", "Scripts", "Scenes", "Review", "Published"].map((stage) => (
                      <div className="pipeline-stage" key={stage}>
                        <span className="stage-indicator" aria-hidden="true" />
                        <span>{stage}</span>
                        <strong>—</strong>
                      </div>
                    ))}
                  </div>
                  <p className="card-footnote">Stage counts require an authenticated dashboard summary API; unavailable until that contract is connected.</p>
                </section>

                <section className="surface-card activity-card" aria-labelledby="activity-title">
                  <div className="card-heading">
                    <div>
                      <h2 id="activity-title">Recent activity</h2>
                      <p>Workflow events</p>
                    </div>
                    <span className="subtle-tag">No feed</span>
                  </div>
                  <EmptyPanel
                    icon="◷"
                    title="No events loaded"
                    message="Activity will appear here after a verified event feed is connected."
                  />
                </section>

                <section className="surface-card flow-card" aria-labelledby="flow-status-title">
                  <div className="card-heading">
                    <div>
                      <h2 id="flow-status-title">Google Flow MCP</h2>
                      <p>Video generation readiness</p>
                    </div>
                    <span className="status-pill status-pill--warning">Unverified</span>
                  </div>
                  <p className="flow-status-copy">No authorized Flow MCP server or manifest is available in this session. Generation, job status, and credit balance remain unavailable.</p>
                </section>

                <section className="surface-card approval-card" aria-labelledby="approval-title">
                  <div className="card-heading">
                    <div>
                      <h2 id="approval-title">Human approval</h2>
                      <p>Production and publishing controls</p>
                    </div>
                    <span className="status-pill status-pill--neutral">Required</span>
                  </div>
                  <p className="flow-status-copy">Automated assessments do not approve, schedule, generate, or publish content. A connected workflow will show its pending items here.</p>
                </section>

                <section className="surface-card service-card" aria-labelledby="service-health-title">
                  <div className="card-heading">
                    <div>
                      <h2 id="service-health-title">Backend service health</h2>
                      <p>Live health and dependency readiness</p>
                    </div>
                    <span className={`status-pill ${dashboardStatus.state === "connected" && dashboardStatus.readiness?.status === "ready" ? "status-pill--success" : "status-pill--warning"}`}>
                      {dashboardStatus.state === "connected" ? dashboardStatus.readiness?.status.replace("_", " ") ?? "health only" : "Unavailable"}
                    </span>
                  </div>
                  {dashboardStatus.state === "connected" ? (
                    <>
                      <p className="flow-status-copy">Health endpoint responded. {dashboardStatus.readiness ? `Overall readiness: ${dashboardStatus.readiness.status.replace("_", " ")}.` : "Readiness could not be verified."}</p>
                      {dashboardStatus.readiness && Object.keys(dashboardStatus.readiness.checks).length > 0 && (
                        <ul className="readiness-list">
                          {Object.entries(dashboardStatus.readiness.checks).map(([name, check]) => (
                            <li key={name}><span>{name}</span><strong>{check.status.replaceAll("_", " ")}</strong></li>
                          ))}
                        </ul>
                      )}
                    </>
                  ) : (
                    <p className="flow-status-copy">{dashboardStatus.reason === "api_not_configured" ? "Set FLOWX_API_BASE_URL on the Next.js server to connect the health endpoints." : "The API did not return a verified health response. Operational counts remain unavailable."}</p>
                  )}
                </section>
              </div>
            </>
          ) : activeSection === "pipeline" ? (
            <ProductionBoard />
          ) : activeSection === "flow" ? (
            <FlowControl />
          ) : (
            <section className="surface-card section-placeholder" aria-labelledby={`${activeSection}-heading`}>
              <div className="section-placeholder-mark" aria-hidden="true">{section.icon}</div>
              <h2 id={`${activeSection}-heading`}>{section.title}</h2>
              <p>{section.description}</p>
              <EmptyPanel
                title="No verified records loaded"
                message="This section is ready to display backend data when its integration is available."
              />
            </section>
          )}

          <footer className="page-footer">
            <span>FLOW AI CONTENT OS</span>
            <span>This shell never substitutes illustrative sample data for live operational records.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
