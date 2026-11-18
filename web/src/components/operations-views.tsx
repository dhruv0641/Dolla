const roleCatalog = [
  { role: "Project Director", scope: "Own user goals, approved scope, and completion claims." },
  { role: "Solution Architect", scope: "Own service boundaries, engineering standards, and architecture decisions." },
  { role: "Task Planning Agent", scope: "Maintain task dependencies and select eligible work." },
  { role: "Backend Engineer", scope: "Own FastAPI services, persistence, migrations, and backend security." },
  { role: "Flow MCP Integration Engineer", scope: "Discover supported capabilities; never invent Flow tools." },
  { role: "AI Workflow Engineer", scope: "Own research, prompts, Gemini/local routing, and output schemas." },
  { role: "Media Pipeline Engineer", scope: "Own local TTS, assets, FFmpeg, and quality-control plumbing." },
  { role: "Frontend Engineer", scope: "Own dashboard screens and user workflows." },
  { role: "Publishing Integration Engineer", scope: "Own official platform interfaces and publication reconciliation." },
  { role: "QA and Security Engineer", scope: "Own checks, threat review, and failure cases." },
  { role: "DevOps Engineer", scope: "Own containers, workers, backup, observability, and deployment." },
  { role: "Technical Reviewer", scope: "Independently check implementation and acceptance evidence." },
] as const;

const analyticMetrics = [
  "Platform views / plays",
  "Reach and impressions",
  "Watch time and retention",
  "Engagement by platform",
  "Follower change",
  "Spend per approved video",
] as const;

const metricRules = [
  { title: "Keep native definitions", detail: "YouTube views, Instagram plays, and Facebook views are not interchangeable." },
  { title: "Show observation windows", detail: "24h, 72h, and 7d snapshots are planned; no verified snapshots are loaded." },
  { title: "Separate fact from inference", detail: "A pattern is not evidence of causation; recommendations need source observations." },
] as const;

const integrations = [
  { name: "Brand profile and timezone", detail: "Brand-specific identity and timezone are not loaded." },
  { name: "Database and identity", detail: "The settings service has no connected authenticated persistence boundary." },
  { name: "Google Flow MCP", detail: "The application transport and account identity are not verified." },
  { name: "Local voice and media", detail: "No speech engine, voice profile, or media store is configured." },
  { name: "Social platform APIs", detail: "No YouTube, Instagram, or Facebook authorization is connected." },
  { name: "Analytics and community", detail: "No platform metrics or comment source is connected." },
  { name: "Roles and spending limits", detail: "No authenticated settings API or persisted operator limits are loaded." },
  { name: "Audit, backup, and licensing", detail: "No runtime settings or verification evidence is available in this workspace." },
] as const;

export type PolicyDefaults = {
  max_scene_regenerations: number;
  human_approval_required: boolean;
  autonomous_publishing_enabled: boolean;
};

function EmptyOperationsPanel({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="ops-empty-panel" role="status">
      <span className="empty-icon" aria-hidden="true">◇</span>
      <div><strong>{title}</strong><p>{detail}</p></div>
    </div>
  );
}

function UnavailableMetric({ label }: { label: string }) {
  return (
    <article className="metric-card" aria-label={`${label}: unavailable`}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value" aria-hidden="true">—</strong>
      <span className="metric-footnote">Unavailable · no verified snapshot</span>
    </article>
  );
}

export function AgentWorkspace() {
  return (
    <div className="ops-workspace">
      <section className="surface-card" aria-labelledby="agent-run-title">
        <div className="card-heading">
          <div><h2 id="agent-run-title">Agent activity</h2><p>Persisted runs, source evidence, and escalations</p></div>
          <span className="status-pill status-pill--warning">No run records</span>
        </div>
        <EmptyOperationsPanel title="No agent runs loaded" detail="These are virtual ownership roles. No model provider, agent runtime, assignment, token use, or run state is connected here." />
      </section>
      <section className="surface-card" aria-labelledby="agent-roles-title">
        <div className="card-heading">
          <div><h2 id="agent-roles-title">AI team role catalog</h2><p>Responsibility map from the project architecture</p></div>
          <span className="status-pill status-pill--neutral">Design roles</span>
        </div>
        <div className="agent-role-grid">
          {roleCatalog.map((item) => (
            <article className="agent-role-card" key={item.role}>
              <span className="agent-role-mark" aria-hidden="true">♜</span>
              <div><strong>{item.role}</strong><p>{item.scope}</p></div>
              <span className="status-pill status-pill--neutral">Virtual role</span>
            </article>
          ))}
        </div>
        <p className="card-footnote">The catalog documents task ownership; it does not mean that independent agent processes are provisioned or running.</p>
      </section>
    </div>
  );
}

export function AnalyticsWorkspace() {
  return (
    <div className="ops-workspace">
      <section className="metrics-grid analytics-metrics" aria-label="Unavailable analytics metrics">
        {analyticMetrics.map((metric) => <UnavailableMetric key={metric} label={metric} />)}
      </section>
      <section className="surface-card" aria-labelledby="analytics-source-title">
        <div className="card-heading">
          <div><h2 id="analytics-source-title">Measurement and interpretation</h2><p>Platform-native definitions and evidence windows</p></div>
          <span className="status-pill status-pill--warning">No snapshots</span>
        </div>
        <div className="analytics-rules-grid">
          {metricRules.map((rule) => (
            <article className="analytics-rule-card" key={rule.title}><strong>{rule.title}</strong><p>{rule.detail}</p></article>
          ))}
        </div>
        <EmptyOperationsPanel title="No performance observations loaded" detail="Insights and experiments will appear only when verified, platform-specific snapshots and their collection windows are available." />
      </section>
    </div>
  );
}

export function CommunityWorkspace() {
  return (
    <div className="ops-workspace">
      <section className="surface-card community-gate-card" aria-labelledby="community-gate-title">
        <div className="card-heading">
          <div><h2 id="community-gate-title">Community inbox</h2><p>Comments, themes, and reviewable response drafts</p></div>
          <span className="status-pill status-pill--warning">Source unavailable</span>
        </div>
        <div className="ops-gate-message" role="status">
          <strong>No authorized comment source is connected</strong>
          <p>No comments, authors, counts, or response drafts are loaded. The inbox does not imply that external platforms have no new conversations.</p>
        </div>
        <div className="community-action-row" role="group" aria-label="Unavailable community actions">
          <button className="flow-action-button flow-action-button--primary" type="button" disabled aria-describedby="community-action-reason">Prepare response drafts</button>
          <button className="flow-action-button" type="button" disabled aria-describedby="community-action-reason">Post response</button>
        </div>
        <p id="community-action-reason" className="card-footnote">Posting requires official authorization and explicit human review. No reply is sent by this screen.</p>
      </section>
      <section className="surface-card" aria-labelledby="community-safety-title">
        <div className="card-heading">
          <div><h2 id="community-safety-title">Response safeguards</h2><p>Community work remains reviewable and traceable</p></div>
          <span className="status-pill status-pill--neutral">Human review required</span>
        </div>
        <ul className="ops-safeguard-list">
          <li>Keep source comment references and platform context with each draft.</li>
          <li>Escalate sensitive or uncertain topics to an authorized reviewer.</li>
          <li>Do not automate spam, fake engagement, likes, or unsolicited replies.</li>
        </ul>
      </section>
    </div>
  );
}

export function SettingsWorkspace({ policyDefaults }: { policyDefaults: PolicyDefaults }) {
  return (
    <div className="ops-workspace">
      <section className="surface-card" aria-labelledby="settings-defaults-title">
        <div className="card-heading">
          <div><h2 id="settings-defaults-title">Versioned policy defaults</h2><p>Repository configuration, not editable runtime settings</p></div>
          <span className="status-pill status-pill--neutral">Read-only defaults</span>
        </div>
        <div className="settings-default-grid">
          <article className="settings-default-card"><span>Human approval</span><strong>{policyDefaults.human_approval_required ? "Required" : "Not required"}</strong><small>Automated review cannot approve content.</small></article>
          <article className="settings-default-card"><span>Autonomous publishing</span><strong>{policyDefaults.autonomous_publishing_enabled ? "Enabled" : "Disabled"}</strong><small>Public publishing policy default.</small></article>
          <article className="settings-default-card"><span>Scene regeneration cap</span><strong>{policyDefaults.max_scene_regenerations} attempts</strong><small>Configured project policy limit.</small></article>
        </div>
        <p className="card-footnote">These values describe the checked-in policy defaults; the web client cannot read or modify live runtime settings.</p>
      </section>
      <section className="surface-card" aria-labelledby="settings-connection-title">
        <div className="card-heading">
          <div><h2 id="settings-connection-title">Configuration readiness</h2><p>Connections and operating context available to the application</p></div>
          <span className="status-pill status-pill--warning">Settings service unavailable</span>
        </div>
        <ul className="ops-connection-list">
          {integrations.map((item) => (
            <li key={item.name}><div><strong>{item.name}</strong><p>{item.detail}</p></div><span className="status-pill status-pill--warning">Not loaded</span></li>
          ))}
        </ul>
      </section>
      <section className="surface-card settings-security-card" aria-labelledby="settings-security-title">
        <div className="card-heading">
          <div><h2 id="settings-security-title">Credential boundary</h2><p>Secrets and persistent permissions stay outside this UI</p></div>
          <span className="status-pill status-pill--neutral">Not editable here</span>
        </div>
        <p className="flow-status-copy">This dashboard does not collect tokens, passwords, cookies, or OAuth credentials. Configure secret references through the approved deployment and account workflows when those integrations are implemented.</p>
      </section>
    </div>
  );
}
