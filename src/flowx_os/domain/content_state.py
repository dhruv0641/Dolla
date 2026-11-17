"""Typed content lifecycle states and allowed transition rules."""

from __future__ import annotations

from enum import StrEnum


class ContentStatus(StrEnum):
    IDEA = "IDEA"
    RESEARCHED = "RESEARCHED"
    BRIEF_READY = "BRIEF_READY"
    SCRIPT_READY = "SCRIPT_READY"
    STORYBOARD_READY = "STORYBOARD_READY"
    GENERATING = "GENERATING"
    ASSEMBLING = "ASSEMBLING"
    QA_PENDING = "QA_PENDING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY = "READY"
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PUBLISHED = "PARTIALLY_PUBLISHED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class InvalidContentTransition(ValueError):
    """Raised when a content status transition is not allowed."""


ALLOWED_CONTENT_TRANSITIONS: dict[ContentStatus, frozenset[ContentStatus]] = {
    ContentStatus.IDEA: frozenset({ContentStatus.RESEARCHED, ContentStatus.ARCHIVED}),
    ContentStatus.RESEARCHED: frozenset({ContentStatus.BRIEF_READY, ContentStatus.ARCHIVED}),
    ContentStatus.BRIEF_READY: frozenset({ContentStatus.SCRIPT_READY, ContentStatus.ARCHIVED}),
    ContentStatus.SCRIPT_READY: frozenset({ContentStatus.STORYBOARD_READY, ContentStatus.ARCHIVED}),
    ContentStatus.STORYBOARD_READY: frozenset({ContentStatus.GENERATING, ContentStatus.ARCHIVED}),
    ContentStatus.GENERATING: frozenset({ContentStatus.ASSEMBLING, ContentStatus.FAILED}),
    ContentStatus.ASSEMBLING: frozenset({ContentStatus.QA_PENDING, ContentStatus.FAILED}),
    ContentStatus.QA_PENDING: frozenset({ContentStatus.NEEDS_REVIEW, ContentStatus.FAILED}),
    ContentStatus.NEEDS_REVIEW: frozenset({
        ContentStatus.READY, ContentStatus.SCRIPT_READY, ContentStatus.STORYBOARD_READY,
        ContentStatus.ARCHIVED,
    }),
    ContentStatus.READY: frozenset({
        ContentStatus.NEEDS_REVIEW, ContentStatus.ARCHIVED,
    }),
    # Scheduling/publication states require coordinated job workflows.
    ContentStatus.SCHEDULED: frozenset(),
    ContentStatus.PARTIALLY_PUBLISHED: frozenset(),
    ContentStatus.FAILED: frozenset({ContentStatus.ARCHIVED}),
    ContentStatus.PUBLISHED: frozenset(),
    ContentStatus.ARCHIVED: frozenset(),
}


def require_content_transition(current: ContentStatus, target: ContentStatus) -> None:
    """Raise a typed domain error unless the requested state edge is allowed."""
    if not isinstance(current, ContentStatus) or not isinstance(target, ContentStatus):
        raise InvalidContentTransition("content status is not supported")
    if target not in ALLOWED_CONTENT_TRANSITIONS[current]:
        raise InvalidContentTransition(f"transition from {current.value} to {target.value} is not allowed")
