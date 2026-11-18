# QA, Voice, Calendar and Publishing Dashboard

## Scope

The dashboard sections are an operator view for quality review, local narration, scheduling, and platform publication. They display only application-owned evidence. The current API does not expose QA reports, media assets, TTS status, calendar records, platform connections, or publication jobs, so each such value remains explicitly unavailable.

## Quality review

The QA workspace names the checks required for media integrity, caption and narration timing, content evidence and safety, and human sign-off. It does not display a score or pass/fail outcome without a persisted report tied to a verified render. `Run quality review` remains disabled until an authorized asset source and report persistence path exist. Automated checks never provide the final human approval.

## Voice studio

Narration generation and preview remain disabled until a local speech engine is configured, an approved voice profile and any required consent are available, and a script can be loaded. The dashboard does not clone or generate a voice and does not show a sample waveform as playable audio.

## Calendar

The calendar is a read-only UTC month view until a brand timezone is configured. It contains no content records; an empty month does not prove that connected platforms have no scheduled posts. Schedule creation remains disabled until approved content, a timezone-aware scheduling service, platform authorization, duplicate prevention, and remote reconciliation are available.

## Platform publication

YouTube, Instagram professional accounts, and Facebook Pages show separate authorization readiness. Account connection and publishing actions remain unavailable until official API credentials and permissions are configured. Upload state and remote publication verification must be tracked independently for each platform; a request acknowledgement alone does not prove publication. Public publishing remains off by default and requires human approval.

## Operational boundary

No API connection, OAuth grant, schedule, upload, post, QA report, narration asset, or platform result is created or implied by these panels. A dash or unavailable label means the application has no verified record; it must not be represented as zero, passed, or empty external state.
