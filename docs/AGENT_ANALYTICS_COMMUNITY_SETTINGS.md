# Agent, Analytics, Community and Settings Dashboard

## Agent activity

The AI team panel lists all 12 virtual ownership roles defined in `AGENTS.md`. It does not claim that models, workers, or independent agent processes are provisioned. Run history, assignments, prompt traces, token usage, costs, failures, and escalations remain unavailable until persisted workflow records are connected.

## Analytics

The analytics panel shows views/plays, reach, watch time/retention, engagement, follower change, and spend as unavailable when no verified snapshot exists. Keep platform-native metric names, definitions, collection windows, and missing fields distinct. Planned 24h, 72h, and 7d windows do not mean that snapshots have been collected. Recommendations must cite measured observations and distinguish facts from inference; correlation is not causal proof.

## Community

The community inbox displays no comments or theme counts without an authorized source. Response drafting and posting stay disabled. Any future reply must retain its source reference, remain a draft until human review, and follow platform policy; do not automate spam or fake engagement.

## Settings

The server reads the checked-in policy defaults from `config/prompt_registry.json` and passes them into the settings panel as read-only repository defaults: human approval is required, autonomous publishing is disabled, and scene regeneration is capped at two attempts. These are not editable runtime settings or proof that a separately deployed service loaded the same configuration.

Brand profile/timezone, account permissions, Flow MCP, local media/TTS, social APIs, analytics/community, roles, spend limits, audit/backup, and licensing readiness remain unavailable in the app because no settings API or connected persistence boundary is wired. This screen never collects passwords, tokens, cookies, or OAuth credentials. Configure secret references through approved deployment and account workflows when those integrations exist.
