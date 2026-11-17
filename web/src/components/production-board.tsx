const columns = [
  { title: "Ideas", statuses: ["IDEA", "RESEARCHED", "BRIEF_READY"] },
  { title: "Scripts", statuses: ["SCRIPT_READY"] },
  { title: "Scenes", statuses: ["STORYBOARD_READY"] },
  { title: "Generation", statuses: ["GENERATING"] },
  { title: "Assembly", statuses: ["ASSEMBLING"] },
  { title: "Quality and review", statuses: ["QA_PENDING", "NEEDS_REVIEW", "READY"] },
  { title: "Failed", statuses: ["FAILED"] },
  { title: "Archived", statuses: ["ARCHIVED"] },
  { title: "Scheduled and published", statuses: ["SCHEDULED", "PARTIALLY_PUBLISHED", "PUBLISHED"] },
] as const;

function UnavailablePanel({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="surface-card lineage-panel" aria-labelledby={`${title.toLowerCase().replaceAll(" ", "-")}-title`}>
      <div className="card-heading">
        <div>
          <h2 id={`${title.toLowerCase().replaceAll(" ", "-")}-title`}>{title}</h2>
          <p>Verified records only</p>
        </div>
        <span className="status-pill status-pill--warning">Unavailable</span>
      </div>
      <div className="empty-panel lineage-empty">
        <span className="empty-icon" aria-hidden="true">◇</span>
        <div>
          <strong>No records loaded</strong>
          <p>{detail}</p>
        </div>
      </div>
    </section>
  );
}

export function ProductionBoard() {
  return (
    <div className="production-workspace">
      <section className="surface-card board-card" aria-labelledby="board-title">
        <div className="card-heading">
          <div>
            <h2 id="board-title">Content lifecycle</h2>
            <p>Stages mirror the backend content state machine</p>
          </div>
          <span className="status-pill status-pill--warning">Records unavailable</span>
        </div>

        <div className="board-columns" aria-label="Content lifecycle stages">
          {columns.map((column) => (
            <section className="board-column" key={column.title} aria-label={column.title}>
              <div className="board-column-heading">
                <h3>{column.title}</h3>
                <span aria-label="Count unavailable">—</span>
              </div>
              <div className="board-statuses">
                {column.statuses.map((status) => <span className="board-state" key={status}>{status.replaceAll("_", " ")}</span>)}
              </div>
              <p className="board-empty">Content records require an authenticated API session.</p>
            </section>
          ))}
        </div>
        <p className="card-footnote">A dash means unavailable, not zero. This screen does not create example cards or imply that content has been loaded.</p>
      </section>

      <div className="lineage-grid">
        <UnavailablePanel title="Scene breakdown" detail="Scene endpoints are not exposed by the backend yet. Storyboards and generation attempts cannot be listed here." />
        <UnavailablePanel title="Assets and lineage" detail="Asset endpoints and download authorization are not available. No media links or placeholder files are shown." />
      </div>
    </div>
  );
}
