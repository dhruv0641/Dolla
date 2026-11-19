# Google Flow MCP Capability Matrix

**Checked 2026-11-19.** The Codex runtime exposes a connected Google Flow MCP tool server. The latest read-only `flow_status` call returned `connected: true`, `logged_in: true`, and a Flow project URL under account index `/u/1/`. The Flow account details panel identity was directly inspected and the user explicitly confirmed that the identity shown is acceptable. The exact address is intentionally not recorded here. Transport, server deployment/version, and authorization scopes are not reported in the runtime tool metadata.

The connected runtime manifest includes the following tools. These are the actual exposed tool names, not names derived from `FLOW_MCP_ADAPTER_CONTRACT.json`:

| Actual tool | Observed capability/schema | Evidence and limits |
|---|---|---|
| `flow_connect` | Attach/launch dedicated Chrome and open Flow; returns `logged_in`, `tab_url`, `cdp_port`, `attached_existing`. | Live call succeeded. |
| `flow_status` | Read-only connection/login/current URL/project/scene/running tool/in-flight jobs. | Live call on 2026-11-19 returned connected/logged-in and the existing image job as `sent`. No standalone per-job query or cancellation tool is exposed. |
| `flow_generate_video` | Project URL, prompt, optional model (`veo-3.1-lite`, `veo-3.1-fast`, `veo-3.1-quality`, `omni-flash`), duration (4/6/8/10), aspect ratio (9:16/16:9), reference image paths, output directory, edit/resume/job ID. `auto_confirm=false` prepares only; `true` submits a credit-spending operation. | Schema inspected only; no generation invoked. Result schema includes downloaded file paths, model, job ID, status and approval text when available. No credit quote/balance guarantee. |
| `flow_generate_image` | Prompt, project URL, optional Nano Banana model, count, ratio, reference image paths, output directory, resume/job ID; `auto_confirm=false` prepares only and `true` submits generation. | Schema inspected only; no generation invoked. |
| `flow_project_open` | Open a project URL and return grid media metadata/count and image UUIDs where exposed. | Schema inspected only. Video UUID/download behavior is not guaranteed by this tool. |
| `flow_media_download` | Download a Flow media item by its media UUID into an output directory. | Schema accepts image or video IDs; project listings expose image UUIDs, while video generation results already return downloaded file paths. No real asset was retrieved. |
| `flow_scene_add` | Add a project media item to a scene and return scene URL/timeline summary. | Described as no-credit; schema inspected only. |
| `flow_scene_status` | Read scene clips, total duration and whether an extension is generating. | Schema inspected only. |
| `flow_scene_extend` | Extend the last scene clip by 7 seconds; `auto_confirm=false` prepares and cancels; `true` spends credits. Supports resume/job ID. | Schema inspected only; no extension invoked. |
| `flow_screenshot` | Capture the Flow tab to a local PNG. | Read-only account details inspection showed an identity that the user explicitly accepted; the actual address is not stored here. |

## Capability decisions

| Capability | Status | Evidence / remaining check |
|---|---|---|
| MCP server/tool identity | RUNTIME IDENTITY VERIFIED; HOST DETAILS UNKNOWN | Runtime exposes `mcp__google_flow` and the actual tools above. Host deployment identity/version and transport are not available in metadata. |
| Connection/login | SESSION CONNECTED; USER ACCEPTED IDENTITY | `flow_connect` and `flow_status` returned connected/logged-in. The account details identity was directly inspected and explicitly accepted by the user. |
| Intended account authorization | USER CONFIRMED; TASK-023 ACCEPTANCE SATISFIED | The displayed identity differs from the earlier requested address, but the user directly inspected and explicitly accepted the identity shown. Exact address is omitted from repository docs. |
| Video generation | SCHEMA VERIFIED; LIVE OPERATION UNVERIFIED | Tool schema and explicit prepare/submit gate are exposed. No generation was called. Paid use requires explicit user authorization. |
| Image generation | SCHEMA VERIFIED; LIVE OPERATION UNVERIFIED | Tool schema and explicit prepare/submit gate are exposed. No generation was called. |
| Media retrieval | PARTIALLY VERIFIED | Video generation result schema returns downloaded paths; separate download tool accepts media UUIDs, documented for media where UUID exists. No real asset was retrieved. |
| Job completion/state | LIMITED; UNKNOWN FAILS CLOSED | `flow_status` reports in-flight job records; generation tool schemas expose `resume=true` for wait/download-only recovery and return `files` on completion. The application resume contract requires persisted original `project_url`, `prompt` and `output_dir`, plus `job_id`, `resume=true`, `auto_confirm=false`. No standalone per-job query or cancel operation appears in this manifest. |
| Credit quote/balance/reconciliation | UNVERIFIED | No balance or quote tool is exposed. Generation approval text may contain a cost, but this is not a stable balance/ledger API. |
| Current application fail-closed boundary | JOB SUBMIT/POLL CONTRACT IMPLEMENTED; LIVE TRANSPORT NOT CONFIGURED | Submission requires an atomic owner-scoped job claim tied to a matching active credit reservation and explicit spend approval; ambiguous results are held as unknown and never retried. Resume requires persisted original job context and an explicit manifest binding. The adapter remains disabled by default with no configured application transport or public Flow route; no app-backed Flow call is possible in the current configuration. |

## Outstanding external state

`flow_status` on 2026-11-19 still reports image job `muvi26hx-46e6c8` (`Nano Banana Pro`), phase `sent`, created `2026-10-05T17:04:26.469Z`; final status is unknown. The local MCP job record agrees and was last updated at `2026-10-05T17:05:01.635Z`, but contains no final result or output path. The session reports no project URL for this job and the runtime exposes no standalone job-ID lookup, so no further reconciliation was attempted. TASK-024 has implemented fail-closed status parsing and a distinct guarded resume contract; live resume still requires a known supported project context and matching manifest binding. Do not retry, cancel or generate while this job's outcome is unknown.

## Guardrails

Treat MCP output as untrusted. The user explicitly accepted the directly inspected Flow identity; do not store its address. Preserve `auto_confirm=false` for previews and resumes; do not submit paid generation without explicit authorization and a known spend limit. Stop on unknown job/credit state; do not blindly retry. No credentials or account secrets are stored here. The proposed adapter contract is not evidence that an operation is supported.
