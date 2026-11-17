const areas = [
  { id: "executive", title: "Executive Command Center", description: "Production and publishing status will appear here once connected." },
  { id: "team", title: "AI Content Team", description: "Agent assignments and activity will be connected to backend records." },
  { id: "research", title: "Research & Content Strategy", description: "Evidence-backed research and approved ideas will appear here." },
  { id: "pipeline", title: "Content Production Pipeline", description: "Content and scene workflow states are not connected yet." },
  { id: "flow", title: "Google Flow Jobs & Credits", description: "Flow capabilities remain unverified; no live jobs or balances are shown." },
  { id: "assets", title: "Scene & Video Asset Library", description: "Generated and rendered assets will appear after storage is configured." },
  { id: "editing", title: "Voice & Video Editing", description: "Local voice and FFmpeg workflows are not connected yet." },
  { id: "quality", title: "Quality Review", description: "Review queues and QC results will be backed by real reports." },
  { id: "calendar", title: "Publishing Calendar", description: "No schedule is available until publishing data is connected." },
  { id: "platforms", title: "YouTube, Instagram & Facebook", description: "Account authorization and per-platform publishing are not configured." },
  { id: "analytics", title: "Growth Analytics", description: "Platform metrics will remain empty until authorized data is available." },
  { id: "community", title: "Community Engagement", description: "Comments and reviewed reply drafts are not connected yet." },
  { id: "monitoring", title: "System Monitoring", description: "Service health and job metrics will appear after backend integration." },
  { id: "settings", title: "Settings & Integrations", description: "Configuration is managed locally until settings APIs are available." },
];

export default function Home() {
  return (
    <main className="workspace">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <div className="brand-mark">FLOW</div>
          <div className="brand-name">Content OS</div>
          <div className="brand-caption">Production workspace</div>
        </div>
        <p className="nav-label">Workspace</p>
        <nav className="nav-list">
          {areas.map((area, index) => (
            <a className="nav-link" href={`#${area.id}`} key={area.id}>
              <span className="nav-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
              <span>{area.title}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-note">
          <strong>Live data only</strong>
          Sample operational metrics are intentionally not displayed.
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <span className="crumb">FLOW AI Content OS / Workspace</span>
          <span className="connection"><span className="connection-dot" aria-hidden="true" />Data integration not configured</span>
        </header>

        <div className="content">
          <section className="intro" id="overview">
            <div>
              <p className="eyebrow">Operations workspace</p>
              <h1>Content command center</h1>
              <p className="intro-copy">
                Plan, produce, review, and distribute content from one traceable workspace.
                Operational data will appear as each backend integration is verified.
              </p>
            </div>
            <p className="intro-aside">No sample counts, balances, posts, or performance metrics are presented as live data.</p>
          </section>

          <section aria-labelledby="areas-heading">
            <div className="section-heading">
              <h2 id="areas-heading">Workspace areas</h2>
              <p>14 areas · integrations are being built</p>
            </div>
            <div className="area-grid">
              {areas.map((area, index) => (
                <article className="area-card" id={area.id} key={area.id}>
                  <div className="area-top">
                    <h3>{area.title}</h3>
                    <span className="area-number">{String(index + 1).padStart(2, "0")}</span>
                  </div>
                  <span className="area-state">Awaiting verified integration</span>
                  <p>{area.description}</p>
                </article>
              ))}
            </div>
          </section>

          <footer className="footer-note">
            <strong>System state:</strong> This is the application shell. Google Flow MCP, database, social accounts, and analytics are not connected by this screen.
          </footer>
        </div>
      </div>
    </main>
  );
}
