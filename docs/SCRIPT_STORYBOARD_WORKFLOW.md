# Script and storyboard workflow

`flowx_os.agents.script_storyboard.ScriptStoryboardWorkflow` provides an asynchronous boundary around an injected `ScriptStoryboardGenerator`. It does not load an SDK, call a model, fetch URLs, persist results, or authorize media generation. Provider implementations are responsible for their own credentials, spend limits, timeouts, and retries.

Inputs are strictly validated and bounded to at most 20 source snapshots and 1 MiB total source text. Each strategy citation must match the supplied source URL/title and its excerpt must occur in that snapshot. Provider output is treated as untrusted data and revalidated with payload-free schema errors. Script citations and scene citations are checked against the same source snapshots by citation ID, URL, title, and excerpt.

The workflow requires a nonempty script evidence list, the requested number of sequential scenes, scene durations between 1 and 60 seconds that sum exactly to the requested duration, matching script/storyboard titles, and scene narration that partitions the script narration in order (whitespace and Unicode normalization are ignored for comparison). Impossible scene-count/duration combinations are rejected before the generator runs. These checks make structure and provenance inspectable; they do not establish factual accuracy, copyright clearance, brand suitability, platform policy compliance, or user approval. Human review remains required before production or publishing.

Unit tests use fake generators only. No live provider, Flow MCP server, paid generation, external account, or publication is configured or claimed.
