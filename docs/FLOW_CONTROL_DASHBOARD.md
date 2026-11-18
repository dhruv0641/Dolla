# Flow control dashboard

The Flow section is a read-only control shell until the application has an authorized MCP transport and backend job/credit APIs. It deliberately shows account, server, job-recovery, and credit readiness as unavailable or unverified when those providers are absent. Ledger values are labeled **Unavailable** rather than rendered as zero, and the job table contains no sample rows.

Generate, retry, and cancel actions are disabled. They must remain disabled until all required server capability, account-identity/health, idempotency/job-reconciliation, and spend-approval evidence is available through the application backend. Browser-only MCP session state is not an application data source. Unknown generation or credit state must stop further spend.

The UI does not expose the old connector-side `sent` job as an application job record because TASK-024 has not reconciled it. The adapter and external state limits are documented in `FLOW_MCP_ADAPTER.md` and `MCP_CAPABILITY_MATRIX.md`.
