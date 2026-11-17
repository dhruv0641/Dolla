# API observability

## Current instrumentation

The FastAPI application emits one JSON log record per request to the configured Python logger `flowx.api.request`. Fields are UTC timestamp, event name, generated request ID, allowlisted HTTP method, route template, status code, handler duration in milliseconds, and (for unhandled failures) exception class only. The same UUID is returned in `X-Request-ID`. The middleware intentionally does not log request/response bodies, headers, query strings, raw paths with identifiers, exception messages, client IPs, or credentials. Unhandled exceptions return a generic 500 body with the request ID.

`GET /api/v1/admin/metrics` returns process-lifetime counters and cumulative latency buckets by allowlisted method, registered route template and status class. It requires the `admin` role and fails closed if token verification is not configured. Route labels are templates (for example `/api/v1/brands/{brand_id}/content`); unmatched requests are grouped under `unmatched`. The measurement is application handler time through response object creation; it is not a full streaming-body duration.

These counters are in-memory and process-local. They reset on restart, are not aggregated across workers, and are not a Prometheus/OpenTelemetry exporter. Do not use them as a durable audit log or financial source of truth. The request ID is local correlation only: it is not propagated to database spans, outbox handlers, providers, or a distributed trace backend.

## Alert policy proposal (not configured)

There is no alert delivery integration in the repository. Once a collector and on-call route are selected, start with these reviewable thresholds and tune them from measured baselines:

- Readiness stays HTTP 503 for more than five minutes: inspect configured dependency wiring and the dependency runbook; do not infer which integration is ready from liveness.
- API 5xx rate exceeds 1% over five minutes or any 5xx burst persists: inspect sanitized request IDs and service logs; avoid logging request payloads during incident response.
- Handler latency p95 exceeds one second for five minutes: inspect route-level counters, database pool and worker saturation; the current metrics only retain process-local cumulative buckets.
- Any dead-letter job exists: inspect safe dead-letter metadata, correlate its event ID, and require an explicit authorized operator decision before requeueing. Never blindly replay external side effects.
- Repeated authentication failures or access denials: review identity-provider, key lifecycle and route authorization without recording bearer-token values.

These are proposed operational thresholds, not active monitors or guarantees. The current process-lifetime snapshot cannot produce a rolling five-minute p95 by itself; a collector must sample and aggregate bucket deltas over the alert window. Alert ownership, delivery, deduplication, maintenance windows, retention and incident escalation remain to be configured under deployment/operations work.

## Operator setup and limitations

Logs go to the application logger; the deployment must configure a structured stdout collector, retention and access controls. Metrics are available only to a verified admin principal; expose the endpoint only through a trusted internal path and avoid placing its bearer token in a browser or dashboard URL. The metrics endpoint is intentionally not public.

This instrumentation does not configure tracing, dashboards, metrics scraping, alert delivery, log storage, or SLOs. Request IDs are not accepted from inbound headers, preventing an external caller from choosing/colliding with a service correlation identifier. Database-backed workflow events remain separate and require explicit sanitized writes by their caller.
