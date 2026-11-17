"""Typed, provider-neutral contracts for AI workflow agents."""

from flowx_os.agents.schemas import (
    AgentRequest,
    AgentRole,
    AgentSchemaError,
    EvidenceReference,
    ResearchResult,
    ScriptDraft,
    StrategyCandidate,
    StoryboardDraft,
    validate_agent_request,
    validate_agent_output,
)
from flowx_os.agents.research import (
    EvidenceBackedResearch,
    EvidenceBackedResearchWorkflow,
    ResearchEvidenceError,
    ResearchErrorCode,
    ResearchSourceProvider,
    ResearchSummarizer,
    RetrievedSource,
)

__all__ = [
    "AgentRequest", "AgentRole", "AgentSchemaError", "EvidenceReference",
    "ResearchResult", "ScriptDraft", "StrategyCandidate", "StoryboardDraft",
    "validate_agent_request", "validate_agent_output", "EvidenceBackedResearch",
    "EvidenceBackedResearchWorkflow", "ResearchEvidenceError", "ResearchErrorCode",
    "ResearchSourceProvider", "ResearchSummarizer", "RetrievedSource",
]
