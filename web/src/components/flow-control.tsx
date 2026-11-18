const prerequisites = [
  {
    title: "Application transport",
    state: "Not configured",
    detail: "The dashboard API has no Flow MCP transport connection.",
  },
  {
    title: "Google account identity",
    state: "Unverified",
    detail: "A logged-in browser session does not prove the configured account identity.",
  },
  {
    title: "Previous external job",
    state: "Unreconciled",
    detail: "Job reconciliation is not connected, so external job state is unavailable; retry stays disabled.",
  },
  {
    title: "Credit quote and balance",
    state: "Unavailable",
    detail: "No verified quote or account balance is exposed to the application.",
  },
] as const;

const ledgerFields = [
  "Available credits",
  "Reserved credits",
  "Consumed credits",
  "Unknown charges",
] as const;

export function FlowControl() {
  return (
    <div className="flow-workspace">
      <section className="surface-card flow-gate-card" aria-labelledby="flow-gate-title">
        <div className="card-heading">
          <div>
            <h2 id="flow-gate-title">Generation controls</h2>
            <p>Operations stay unavailable until the application has verified account, job, and spend evidence.</p>
          </div>
          <span className="status-pill status-pill--warning">Unavailable</span>
        </div>
        <div className="flow-gate-body">
          <div className="flow-gate-message" role="status">
            <strong>Video generation is not connected</strong>
            <p>No Flow operation has been submitted from this application. The browser-only connector session is not an application transport.</p>
          </div>
          <div className="flow-action-row" role="group" aria-label="Unavailable Flow actions">
            <button className="flow-action-button flow-action-button--primary" type="button" disabled aria-describedby="flow-action-reason">
              Generate video
            </button>
            <button className="flow-action-button" type="button" disabled aria-describedby="flow-action-reason">
              Retry job
            </button>
            <button className="flow-action-button" type="button" disabled aria-describedby="flow-action-reason">
              Cancel job
            </button>
          </div>
          <p id="flow-action-reason" className="card-footnote">Actions unlock only after verified backend capability, account health, job recovery, and spend authorization are available.</p>
        </div>
        <ul className="flow-prerequisite-list" aria-label="Flow readiness prerequisites">
          {prerequisites.map((item) => (
            <li key={item.title}>
              <div>
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
              </div>
              <span className="status-pill status-pill--warning">{item.state}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="surface-card" aria-labelledby="flow-ledger-title">
        <div className="card-heading">
          <div>
            <h2 id="flow-ledger-title">Credit ledger</h2>
            <p>Per-account records from the application ledger</p>
          </div>
          <span className="status-pill status-pill--warning">No verified ledger</span>
        </div>
        <div className="flow-ledger-grid">
          {ledgerFields.map((field) => (
            <article className="flow-ledger-field" key={field} aria-label={`${field}: unavailable`}>
              <span>{field}</span>
              <strong>Unavailable</strong>
              <small>No verified account ledger loaded</small>
            </article>
          ))}
        </div>
        <p className="card-footnote">Unavailable values are not zero. This view does not estimate allowances, costs, or remaining credits.</p>
      </section>

      <section className="surface-card" aria-labelledby="flow-jobs-title">
        <div className="card-heading">
          <div>
            <h2 id="flow-jobs-title">Generation jobs</h2>
            <p>Application-owned jobs and their reconciled credit records</p>
          </div>
          <span className="status-pill status-pill--warning">No verified records</span>
        </div>
        <div className="flow-jobs-table-wrap">
          <table className="flow-jobs-table">
            <thead>
              <tr>
                <th scope="col">Job ID</th>
                <th scope="col">Account</th>
                <th scope="col">Content / scene</th>
                <th scope="col">Credits</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={5}>
                  <div className="flow-jobs-empty" role="status">
                    <strong>No application job records loaded</strong>
                    <p>External connector activity is not treated as an application job until it is verified and reconciled.</p>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
