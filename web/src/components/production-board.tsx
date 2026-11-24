import type { DashboardSnapshot } from "../lib/dashboard-types";
import { textField } from "../lib/dashboard-types";

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

function VerifiedList({ title, records, label }: { title: string; records: DashboardSnapshot["scenes"]; label: (record: DashboardSnapshot["scenes"][number]) => string }) {
  return <section className="surface-card lineage-panel"><div className="card-heading"><div><h2>{title}</h2><p>Owner-scoped live records</p></div><span className="status-pill status-pill--success">{records.length} verified</span></div>
    {records.length ? <ul className="record-list">{records.map((record, index) => <li key={textField(record, "id", String(index))}><strong>{label(record)}</strong><small>{textField(record, "created_at", textField(record, "updated_at"))}</small></li>)}</ul>
      : <div className="empty-panel lineage-empty"><span className="empty-icon">0</span><div><strong>No records</strong><p>The authenticated snapshot verified zero {title.toLowerCase()} records.</p></div></div>}
  </section>;
}

export function ProductionBoard({ data }: { data: DashboardSnapshot | null }) {
  if (!data) return <section className="surface-card"><div className="empty-panel"><span className="empty-icon">—</span><div><strong>Pipeline unavailable</strong><p>The authenticated dashboard snapshot could not be loaded.</p></div></div></section>;
  return <div className="production-workspace">
    <section className="surface-card board-card"><div className="card-heading"><div><h2>Content lifecycle</h2><p>Live content records grouped by backend state</p></div><span className="status-pill status-pill--success">{data.content.length} records</span></div>
      <div className="board-columns">{columns.map((column) => { const items = data.content.filter((item) => column.statuses.includes(textField(item, "status", "") as never)); return <section className="board-column" key={column.title}><div className="board-column-heading"><h3>{column.title}</h3><span>{items.length}</span></div><div className="board-statuses">{column.statuses.map((status) => <span className="board-state" key={status}>{status.replaceAll("_", " ")}</span>)}</div>{items.length ? items.map((item) => <article className="record-card" key={textField(item, "id")}><strong>{textField(item, "title", "Untitled content")}</strong><small>{textField(item, "brand_name")} · {textField(item, "status")}</small></article>) : <p className="board-empty">Verified 0 records</p>}</section>; })}</div>
      <p className="card-footnote">Counts are from the current authenticated owner snapshot generated at {data.generated_at}.</p>
    </section>
    <div className="lineage-grid"><VerifiedList title="Scene breakdown" records={data.scenes} label={(record) => `${textField(record, "content_title")} · scene ${String(record.scene_index ?? "—")} · ${textField(record, "state")}`} /><VerifiedList title="Assets and lineage" records={data.assets} label={(record) => `${textField(record, "content_title")} · ${textField(record, "asset_kind")}`} /></div>
  </div>;
}
