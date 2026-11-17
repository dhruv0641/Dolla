# FLOW AI Content OS Dashboard

This Next.js App Router shell is the frontend for FLOW AI Content OS. It intentionally shows empty states until backend data and authorized integrations exist.

## Local development

From this directory, run:

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. Run `npm run typecheck` and `npm run build` before opening a pull request.

This shell does not imply that Flow, PostgreSQL, social publishing, or analytics are connected.

## Dashboard status connection

The executive dashboard reads only the backend's unauthenticated `/healthz` and `/readyz` endpoints through a same-origin Next.js route. Configure the server-side `FLOWX_API_BASE_URL` variable with the backend origin (for example, `http://127.0.0.1:8000`). The UI polls every 60 seconds and supports an on-demand refresh. If the variable is missing, endpoints time out, or the response shape is invalid, service status is shown as unavailable. Health confirms only that the API process responds; readiness reports configured dependency checks. This connection does not provide authenticated brand/content data, Flow MCP status, publishing state, or analytics, so those operational metrics remain unavailable.
