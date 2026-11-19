"""Fail-closed Flow generation job identity, polling, and recovery helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol
from uuid import UUID

from flowx_os.flow_mcp.adapter import FlowAdapter
from flowx_os.flow_mcp.capabilities import FlowAccountAuthorization, FlowOperation, SpendAuthorization
from flowx_os.domain.scene_jobs import SceneRetryPolicy


class FlowJobState(StrEnum):
    UNKNOWN = "UNKNOWN"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class FlowJobObservation:
    external_job_id: str | None
    state: FlowJobState
    output_path: str | None = None


@dataclass(frozen=True, slots=True)
class PersistedJobResumeContext:
    external_job_id: str
    project_url: str
    prompt: str
    output_dir: str


@dataclass(frozen=True, slots=True)
class JobSubmissionRequest:
    """Stable local identity and inputs for one already-reserved generation."""

    scene_id: UUID
    request_id: UUID
    owner_user_id: str
    attempt_index: int
    model: str
    prompt: str
    duration_seconds: int
    quoted_credits: int
    arguments: Mapping[str, object]
    settings: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class JobSubmissionClaim:
    """Atomic store result; only a newly inserted RESERVED row may be sent."""

    job_id: UUID
    status: str
    external_job_id: str | None
    created: bool


class FlowGenerationJobStore(Protocol):
    async def claim_or_get(self, *, account_ref: str, request: JobSubmissionRequest,
                           fingerprint: str) -> JobSubmissionClaim:
        """Atomically consume an existing matching credit reservation and insert/get the job."""

    async def mark_submitted(self, *, job_id: UUID, external_job_id: str) -> None: ...

    async def mark_remote_submission_unknown(self, *, job_id: UUID) -> None: ...

    async def get_resume_context(self, *, job_id: UUID, account_ref: str,
                                 owner_user_id: str) -> PersistedJobResumeContext | None: ...


def generation_fingerprint(
    *, account_ref: str, scene_id: str, attempt_index: int,
    model: str, prompt: str, settings: Mapping[str, Any],
) -> str:
    """Return a deterministic, non-reversible request identity for deduplication."""
    if (
        not isinstance(account_ref, str) or not account_ref.strip()
        or not isinstance(scene_id, str) or not scene_id.strip()
        or isinstance(attempt_index, bool) or not isinstance(attempt_index, int) or attempt_index < 1
        or not isinstance(model, str) or not model.strip()
        or not isinstance(prompt, str) or not prompt.strip()
        or not isinstance(settings, Mapping)
    ):
        raise ValueError("generation request identity is invalid")
    body = {
        "account_ref": account_ref.strip(),
        "scene_id": scene_id.strip(),
        "attempt_index": attempt_index,
        "model": model.strip(),
        "prompt": prompt,
        "settings": settings,
    }
    try:
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("generation request settings are not canonical JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def observe_in_flight_job(payload: object, *, expected_job_id: str) -> FlowJobObservation:
    """Match an exact Flow status entry; absence or malformed data stays unknown."""
    if not isinstance(expected_job_id, str) or not expected_job_id.strip():
        raise ValueError("expected_job_id is required")
    if not isinstance(payload, Mapping):
        return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)
    jobs = payload.get("jobs_in_flight")
    if not isinstance(jobs, (list, tuple)):
        return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)
    matching = [item for item in jobs if isinstance(item, Mapping) and item.get("job_id") == expected_job_id]
    if len(matching) != 1:
        return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)
    phase = matching[0].get("phase")
    if isinstance(phase, str) and phase.strip().casefold() in {"sent", "queued", "running", "processing"}:
        return FlowJobObservation(expected_job_id, FlowJobState.RUNNING)
    return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)


def observe_resume_result(payload: object, *, expected_job_id: str) -> FlowJobObservation:
    """Trust only a matching ID and explicit terminal state from a resume result."""
    if not isinstance(expected_job_id, str) or not expected_job_id.strip():
        raise ValueError("expected_job_id is required")
    if not isinstance(payload, Mapping) or payload.get("job_id") != expected_job_id:
        return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)
    status = payload.get("status")
    if not isinstance(status, str):
        return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)
    normalized = status.strip().casefold()
    if normalized in {"sent", "queued", "running", "processing", "in_progress"}:
        return FlowJobObservation(expected_job_id, FlowJobState.RUNNING)
    if normalized in {"failed", "error"}:
        return FlowJobObservation(expected_job_id, FlowJobState.FAILED)
    if normalized in {"completed", "complete", "succeeded", "downloaded"}:
        path = payload.get("output_path")
        files = payload.get("files")
        if not (isinstance(path, str) and path.strip()) and isinstance(files, (list, tuple)):
            path = files[0] if len(files) == 1 else None
        if isinstance(path, str) and path.strip():
            return FlowJobObservation(expected_job_id, FlowJobState.SUCCEEDED, path.strip())
    return FlowJobObservation(expected_job_id, FlowJobState.UNKNOWN)


class FlowJobSubmissionService:
    """Persist an idempotent reservation before send; ambiguous sends never retry."""

    def __init__(self, adapter: FlowAdapter, store: FlowGenerationJobStore, *,
                 retry_policy: SceneRetryPolicy | None = None) -> None:
        self._adapter = adapter
        self._store = store
        self._retry_policy = retry_policy or SceneRetryPolicy()

    async def submit(self, *, account: FlowAccountAuthorization, request: JobSubmissionRequest,
                     spend: SpendAuthorization) -> JobSubmissionClaim:
        if (
            not isinstance(request, JobSubmissionRequest)
            or not isinstance(spend, SpendAuthorization)
            or spend.operation != FlowOperation.VIDEO_GENERATE
            or spend.account_ref != account.account_ref
            or not isinstance(request.arguments, Mapping)
            or request.arguments.get("auto_confirm") is not True
            or request.arguments.get("prompt") != request.prompt
            or request.arguments.get("model") != request.model
            or request.arguments.get("duration") != request.duration_seconds
            or request.arguments.get("resume") is True
            or request.arguments.get("job_id") is not None
            or isinstance(request.quoted_credits, bool)
            or not isinstance(request.quoted_credits, int)
            or request.quoted_credits <= 0
            or spend.max_allowed_credits < request.quoted_credits
        ):
            raise ValueError("generation submission requires a matching reserved request and explicit spend approval")
        self._retry_policy.require_index(request.attempt_index)
        fingerprint = generation_fingerprint(
            account_ref=account.account_ref, scene_id=str(request.scene_id),
            attempt_index=request.attempt_index, model=request.model,
            prompt=request.prompt,
            settings={"duration_seconds": request.duration_seconds,
                      "settings": request.settings, "arguments": request.arguments,
                      "request_id": str(request.request_id)},
        )
        claim = await self._store.claim_or_get(
            account_ref=account.account_ref, request=request, fingerprint=fingerprint,
        )
        if not isinstance(claim, JobSubmissionClaim):
            raise RuntimeError("generation job store returned an invalid claim")
        if not claim.created or claim.status != "RESERVED":
            return claim
        try:
            result = await self._adapter.invoke(
                FlowOperation.VIDEO_GENERATE, request.arguments,
                account=account, spend=spend,
            )
        except Exception:
            await self._store.mark_remote_submission_unknown(job_id=claim.job_id)
            raise
        external_job_id = result.get("job_id") if isinstance(result, Mapping) else None
        if not isinstance(external_job_id, str) or not external_job_id.strip():
            await self._store.mark_remote_submission_unknown(job_id=claim.job_id)
            return JobSubmissionClaim(claim.job_id, "REMOTE_SUBMISSION_UNKNOWN", None, True)
        await self._store.mark_submitted(
            job_id=claim.job_id, external_job_id=external_job_id.strip(),
        )
        return JobSubmissionClaim(claim.job_id, "SUBMITTED", external_job_id.strip(), True)


class FlowJobResumeService:
    """Resume/poll an existing Flow job through an explicitly discovered binding."""

    def __init__(self, adapter: FlowAdapter, store: FlowGenerationJobStore, *,
                 account: FlowAccountAuthorization, owner_user_id: str,
                 result_observer: Callable[..., FlowJobObservation] = observe_resume_result) -> None:
        self._adapter = adapter
        self._store = store
        self._account = account
        self._owner_user_id = owner_user_id
        self._result_observer = result_observer

    async def poll(self, *, job_id: UUID) -> FlowJobObservation:
        if not isinstance(job_id, UUID):
            raise ValueError("job_id must be a UUID")
        context = await self._store.get_resume_context(
            job_id=job_id, account_ref=self._account.account_ref,
            owner_user_id=self._owner_user_id,
        )
        if not isinstance(context, PersistedJobResumeContext):
            return FlowJobObservation(None, FlowJobState.UNKNOWN)
        arguments: dict[str, object] = {
            "job_id": context.external_job_id,
            "resume": True,
            "auto_confirm": False,
            "project_url": context.project_url,
            "prompt": context.prompt,
            "output_dir": context.output_dir,
        }
        result = await self._adapter.invoke(
            FlowOperation.JOB_RESUME, arguments, account=self._account,
        )
        return self._result_observer(result, expected_job_id=context.external_job_id)
