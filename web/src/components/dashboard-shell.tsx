"use client";

import { useState } from "react";

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
  const section = sections.find((item) => item.id === activeSection) ?? sections[0];

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
          <div className="system-status" role="status">
            <span className="system-status-dot" aria-hidden="true" />
            <span>Dashboard data not connected</span>
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
                  <p className="card-footnote">Stage counts are unavailable until backend records are connected.</p>
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
              </div>
            </>
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
