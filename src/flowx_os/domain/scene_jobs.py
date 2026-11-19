"""Scene generation attempt state and conservative retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class SceneJobState(StrEnum):
    PENDING = "PENDING"
    CREDIT_RESERVED = "CREDIT_RESERVED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    DOWNLOADED = "DOWNLOADED"
    QA_FAILED = "QA_FAILED"
    QA_PASSED = "QA_PASSED"
    RETRY_WAIT = "RETRY_WAIT"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class SceneAttemptLimitExceeded(ValueError):
    """The requested generation attempt exceeds the configured retry bound."""


class SceneAttemptStateConflict(ValueError):
    """Scene state does not permit the requested generation attempt."""


@dataclass(frozen=True, slots=True)
class SceneRetryPolicy:
    """Bound retries after the initial generation attempt.

    ``retry_count`` records retry attempts already scheduled, excluding the
    initial generation. A limit of two permits attempt indexes 1, 2 and 3.
    """

    max_scene_regenerations: int = 2

    def __post_init__(self) -> None:
        if (isinstance(self.max_scene_regenerations, bool)
                or not isinstance(self.max_scene_regenerations, int)
                or not 0 <= self.max_scene_regenerations <= 10):
            raise ValueError("max_scene_regenerations must be between 0 and 10")

    @property
    def max_attempts(self) -> int:
        return 1 + self.max_scene_regenerations

    def require_index(self, attempt_index: int) -> None:
        if isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or attempt_index < 1:
            raise ValueError("scene attempt index is invalid")
        if attempt_index > self.max_attempts:
            raise SceneAttemptLimitExceeded("scene regeneration limit is exhausted")

    def require_attempt(self, *, attempt_index: int, state: str | SceneJobState,
                        retry_count: int) -> None:
        self.require_index(attempt_index)
        if isinstance(retry_count, bool) or not isinstance(retry_count, int) or retry_count < 0:
            raise ValueError("scene attempt identity is invalid")
        try:
            scene_state = SceneJobState(state)
        except (ValueError, TypeError) as exc:
            raise SceneAttemptStateConflict("scene has an unsupported generation state") from exc
        expected_initial = attempt_index == 1 and scene_state == SceneJobState.PENDING and retry_count == 0
        expected_retry = (
            attempt_index > 1 and scene_state == SceneJobState.RETRY_WAIT
            and retry_count == attempt_index - 1
        )
        if not (expected_initial or expected_retry):
            raise SceneAttemptStateConflict("scene state does not permit the requested attempt")

    def should_schedule_retry(self, *, attempt_index: int, retryable: bool) -> bool:
        if isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or attempt_index < 1:
            raise ValueError("scene attempt index is invalid")
        if not isinstance(retryable, bool):
            raise ValueError("retryable must be a boolean")
        return retryable and attempt_index <= self.max_scene_regenerations


@dataclass(frozen=True, slots=True)
class SceneRetryDecision:
    scene_id: UUID
    job_id: UUID
    attempt_index: int
    retry_count: int
    scene_state: SceneJobState
    retry_scheduled: bool
