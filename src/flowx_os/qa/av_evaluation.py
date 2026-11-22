"""Bounded objective visual/audio measurements for integrity-passed renders."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flowx_os.assets.probing import (
    MediaProbeError,
    _run_streams,
    verified_media_snapshot,
)
from flowx_os.assets.storage import StoredAssetFile
from flowx_os.db.assets import AssetRecord
from flowx_os.qa.integrity import IntegrityDecision, IntegrityReport


_SAFE_MEDIA_CODE = re.compile(r"^MEDIA_[A-Z0-9_]{1,63}$")
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


class AvEvaluationError(RuntimeError):
    """Safe prerequisite or lineage failure."""


class AvDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class FindingSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    REVIEW = "REVIEW"


class AvFindingCode(StrEnum):
    ASSET_REVALIDATION_FAILED = "ASSET_REVALIDATION_FAILED"
    ANALYSIS_UNAVAILABLE = "ANALYSIS_UNAVAILABLE"
    BLACK_DURATION_EXCEEDED = "BLACK_DURATION_EXCEEDED"
    FREEZE_DURATION_EXCEEDED = "FREEZE_DURATION_EXCEEDED"
    SILENCE_DURATION_EXCEEDED = "SILENCE_DURATION_EXCEEDED"
    LOUDNESS_OUT_OF_RANGE = "LOUDNESS_OUT_OF_RANGE"
    TRUE_PEAK_EXCEEDED = "TRUE_PEAK_EXCEEDED"


class SubjectiveSignal(StrEnum):
    SEMANTIC_VISUAL_QUALITY = "SEMANTIC_VISUAL_QUALITY"
    SPEECH_INTELLIGIBILITY = "SPEECH_INTELLIGIBILITY"
    MIX_PREFERENCE = "MIX_PREFERENCE"


class AvEvaluationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    max_input_bytes: int = Field(default=2_000_000_000, ge=1, le=4_000_000_000)
    output_limit_bytes: int = Field(default=1_000_000, ge=16_384, le=8_000_000)
    black_min_duration_ms: int = Field(default=200, ge=100, le=10_000)
    black_pixel_threshold: float = Field(default=0.10, ge=0, le=1)
    max_black_ratio: float = Field(default=0.02, ge=0, le=1)
    freeze_min_duration_ms: int = Field(default=1000, ge=100, le=30_000)
    freeze_noise_db: float = Field(default=-50.0, ge=-100, le=0)
    max_freeze_ratio: float = Field(default=0.15, ge=0, le=1)
    silence_min_duration_ms: int = Field(default=500, ge=100, le=30_000)
    silence_threshold_db: float = Field(default=-50.0, ge=-100, le=0)
    max_silence_ratio: float = Field(default=0.25, ge=0, le=1)
    target_lufs: float = Field(default=-16.0, ge=-70, le=0)
    loudness_tolerance_lu: float = Field(default=3.0, ge=0, le=30)
    max_true_peak_dbtp: float = Field(default=-1.0, ge=-20, le=0)

    @model_validator(mode="after")
    def finite_values(self) -> "AvEvaluationPolicy":
        for value in (
            self.timeout_seconds, self.black_pixel_threshold,
            self.max_black_ratio, self.freeze_noise_db, self.max_freeze_ratio,
            self.silence_threshold_db, self.max_silence_ratio,
            self.target_lufs, self.loudness_tolerance_lu,
            self.max_true_peak_dbtp,
        ):
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError("visual/audio policy values must be finite")
        return self


class AvMeasurements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    evaluated_duration_ms: int = Field(ge=1, le=180_000)
    black_duration_ms: int = Field(ge=0, le=180_000)
    black_ratio: float = Field(ge=0, le=1)
    black_intervals: int = Field(ge=0, le=10_000)
    freeze_duration_ms: int = Field(ge=0, le=180_000)
    freeze_ratio: float = Field(ge=0, le=1)
    freeze_intervals: int = Field(ge=0, le=10_000)
    silence_duration_ms: int = Field(ge=0, le=180_000)
    silence_ratio: float = Field(ge=0, le=1)
    silence_intervals: int = Field(ge=0, le=10_000)
    integrated_lufs: float = Field(ge=-100, le=10)
    true_peak_dbtp: float = Field(ge=-100, le=10)

    @model_validator(mode="after")
    def ratios_match_durations(self) -> "AvMeasurements":
        for duration, ratio in (
            (self.black_duration_ms, self.black_ratio),
            (self.freeze_duration_ms, self.freeze_ratio),
            (self.silence_duration_ms, self.silence_ratio),
        ):
            if duration > self.evaluated_duration_ms:
                raise ValueError("measured interval exceeds evaluated duration")
            expected = duration / self.evaluated_duration_ms
            if abs(ratio - expected) > 0.00000001:
                raise ValueError("measured ratio does not match its duration")
        return self


class AvFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    code: AvFindingCode
    severity: FindingSeverity
    expected: str = Field(min_length=1, max_length=100)
    observed: str = Field(min_length=1, max_length=100)


def av_evidence_fingerprint(
    *, asset_id: UUID, content_id: UUID, integrity_evidence_fingerprint: str,
    policy: AvEvaluationPolicy, findings: tuple[AvFinding, ...],
    measurements: AvMeasurements | None,
) -> str:
    payload = {
        "asset_id": str(asset_id),
        "content_id": str(content_id),
        "integrity_evidence_fingerprint": integrity_evidence_fingerprint,
        "policy": policy.model_dump(mode="json"),
        "findings": [item.model_dump(mode="json") for item in findings],
        "measurements": None if measurements is None else measurements.model_dump(mode="json"),
        "subjective_signals_not_evaluated": [item.value for item in SubjectiveSignal],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class AvEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    asset_id: UUID
    content_id: UUID
    integrity_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: AvEvaluationPolicy
    decision: AvDecision
    findings: tuple[AvFinding, ...]
    measurements: AvMeasurements | None
    subjective_signals_not_evaluated: tuple[SubjectiveSignal, ...]
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def envelope_is_canonical(self) -> "AvEvaluationReport":
        if self.subjective_signals_not_evaluated != tuple(SubjectiveSignal):
            raise ValueError("subjective signal boundary is incomplete")
        if any(item.severity == FindingSeverity.BLOCKER for item in self.findings):
            expected_decision = AvDecision.FAIL
        elif self.findings:
            expected_decision = AvDecision.NEEDS_HUMAN
        else:
            expected_decision = AvDecision.PASS
        if self.decision != expected_decision:
            raise ValueError("visual/audio decision does not match findings")
        if self.measurements is None and not self.findings:
            raise ValueError("visual/audio report lacks measurements or findings")
        expected_fingerprint = av_evidence_fingerprint(
            asset_id=self.asset_id, content_id=self.content_id,
            integrity_evidence_fingerprint=self.integrity_evidence_fingerprint,
            policy=self.policy, findings=self.findings,
            measurements=self.measurements,
        )
        if self.evidence_fingerprint != expected_fingerprint:
            raise ValueError("visual/audio evidence fingerprint is invalid")
        return self


class AvAnalyzer(Protocol):
    def analyze(
        self, asset: StoredAssetFile, *, duration_ms: int,
        policy: AvEvaluationPolicy,
    ) -> AvMeasurements: ...


def _format_filter(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("filter value must be finite")
    return format(value, ".8g")


def _duration_metrics(text: str, marker: str, duration_ms: int) -> tuple[int, float, int]:
    values = [float(value) for value in re.findall(rf"{re.escape(marker)}\s*:?\s*({_NUMBER})", text)]
    if len(values) > 10_000 or any(not math.isfinite(value) or value < 0 for value in values):
        raise MediaProbeError("MEDIA_ANALYSIS_INVALID")
    total_ms = round(sum(values) * 1000)
    if total_ms > duration_ms + 500:
        raise MediaProbeError("MEDIA_ANALYSIS_INVALID")
    total_ms = min(total_ms, duration_ms)
    return total_ms, round(total_ms / duration_ms, 8), len(values)


def parse_av_analysis(payload: bytes, *, duration_ms: int) -> AvMeasurements:
    """Parse only allowlisted numeric FFmpeg findings; discard all other text."""
    if type(duration_ms) is not int or not 1 <= duration_ms <= 180_000:
        raise ValueError("analysis duration is invalid")
    text = payload.decode("ascii", errors="replace")
    try:
        black_ms, black_ratio, black_count = _duration_metrics(text, "black_duration", duration_ms)
        freeze_ms, freeze_ratio, freeze_count = _duration_metrics(text, "freeze_duration", duration_ms)
        silence_ms, silence_ratio, silence_count = _duration_metrics(text, "silence_duration", duration_ms)
        loudness = re.findall(rf"Integrated loudness:\s*I:\s*({_NUMBER})\s*LUFS", text)
        peaks = re.findall(rf"True peak:\s*Peak:\s*({_NUMBER})\s*dBFS", text)
        if not loudness or not peaks:
            raise ValueError("summary missing")
        integrated_lufs, true_peak = float(loudness[-1]), float(peaks[-1])
        if not math.isfinite(integrated_lufs) or not math.isfinite(true_peak):
            raise ValueError("summary invalid")
        return AvMeasurements(
            evaluated_duration_ms=duration_ms,
            black_duration_ms=black_ms, black_ratio=black_ratio,
            black_intervals=black_count, freeze_duration_ms=freeze_ms,
            freeze_ratio=freeze_ratio, freeze_intervals=freeze_count,
            silence_duration_ms=silence_ms, silence_ratio=silence_ratio,
            silence_intervals=silence_count, integrated_lufs=integrated_lufs,
            true_peak_dbtp=true_peak,
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise MediaProbeError("MEDIA_ANALYSIS_INVALID") from exc


class LocalFfmpegAvAnalyzer:
    """Measure a verified private snapshot with fixed local FFmpeg filters."""

    def __init__(self, storage_root: Path, *, ffmpeg: str = "ffmpeg") -> None:
        self._root = Path(storage_root).expanduser().resolve()
        self._ffmpeg = ffmpeg

    def analyze(
        self, asset: StoredAssetFile, *, duration_ms: int,
        policy: AvEvaluationPolicy,
    ) -> AvMeasurements:
        if (not isinstance(asset, StoredAssetFile) or not isinstance(policy, AvEvaluationPolicy)
                or type(duration_ms) is not int or not 1 <= duration_ms <= 180_000):
            raise ValueError("visual/audio analysis request is invalid")
        video_filter = (
            f"blackdetect=d={policy.black_min_duration_ms / 1000}:"
            f"pix_th={_format_filter(policy.black_pixel_threshold)},"
            f"freezedetect=n={_format_filter(policy.freeze_noise_db)}dB:"
            f"d={policy.freeze_min_duration_ms / 1000}"
        )
        audio_filter = (
            f"silencedetect=n={_format_filter(policy.silence_threshold_db)}dB:"
            f"d={policy.silence_min_duration_ms / 1000},"
            "ebur128=peak=true:framelog=verbose"
        )
        with verified_media_snapshot(
            asset, storage_root=self._root, max_bytes=policy.max_input_bytes,
        ) as (snapshot, options):
            _, diagnostic = _run_streams(
                [
                    self._ffmpeg, "-nostdin", "-hide_banner", "-v", "info",
                    "-max_alloc", "268435456", *options, "-i", str(snapshot),
                    "-filter_complex_threads", "1", "-filter_complex",
                    f"[0:v:0]{video_filter}[v];[0:a:0]{audio_filter}[a]",
                    "-map", "[v]", "-map", "[a]", "-threads", "1",
                    "-f", "null", "-",
                ],
                timeout=policy.timeout_seconds,
                output_limit=policy.output_limit_bytes,
            )
        return parse_av_analysis(diagnostic, duration_ms=duration_ms)


def _finding(
    code: AvFindingCode, severity: FindingSeverity,
    expected: object, observed: object,
) -> AvFinding:
    return AvFinding(
        code=code, severity=severity,
        expected=str(expected)[:100], observed=str(observed)[:100],
    )


class AvEvaluationService:
    """Evaluate objective signals only; subjective review remains explicit."""

    def __init__(self, analyzer: AvAnalyzer) -> None:
        if not hasattr(analyzer, "analyze"):
            raise ValueError("visual/audio analyzer is required")
        self._analyzer = analyzer

    def evaluate(
        self, integrity: IntegrityReport, asset: StoredAssetFile,
        record: AssetRecord, *, duration_ms: int,
        policy: AvEvaluationPolicy | None = None,
    ) -> AvEvaluationReport:
        policy = policy or AvEvaluationPolicy()
        if (not isinstance(integrity, IntegrityReport)
                or not isinstance(asset, StoredAssetFile)
                or not isinstance(record, AssetRecord)
                or not isinstance(policy, AvEvaluationPolicy)
                or type(duration_ms) is not int or not 1 <= duration_ms <= 180_000):
            raise ValueError("visual/audio evaluation inputs are invalid")
        metadata = record.metadata
        if (integrity.decision != IntegrityDecision.PASS or not integrity.decode_verified
                or integrity.findings or integrity.observed_sha256_hex != asset.sha256_hex):
            raise AvEvaluationError("INTEGRITY_PREREQUISITE_FAILED")
        if (integrity.asset_id != asset.asset_id or metadata.asset_id != asset.asset_id
                or integrity.content_id != metadata.content_id
                or metadata.storage_uri != asset.storage_uri
                or metadata.sha256_hex != asset.sha256_hex
                or metadata.size_bytes != asset.size_bytes
                or metadata.mime_type != "video/mp4" or asset.mime_type != "video/mp4"
                or metadata.scene_id is not None
                or metadata.media_metadata.get("duration_ms") != duration_ms):
            raise AvEvaluationError("ASSET_LINEAGE_MISMATCH")

        findings: list[AvFinding] = []
        measurements: AvMeasurements | None = None
        try:
            measurements = self._analyzer.analyze(
                asset, duration_ms=duration_ms, policy=policy,
            )
        except MediaProbeError as exc:
            safe = str(exc) if _SAFE_MEDIA_CODE.fullmatch(str(exc)) else "MEDIA_ANALYSIS_FAILED"
            if safe in {
                "MEDIA_INTEGRITY_MISMATCH", "MEDIA_PATH_UNSAFE",
                "MEDIA_FILE_UNAVAILABLE", "MEDIA_SIZE_LIMIT",
            }:
                findings.append(_finding(
                    AvFindingCode.ASSET_REVALIDATION_FAILED,
                    FindingSeverity.BLOCKER, "unchanged managed bytes", safe,
                ))
            else:
                findings.append(_finding(
                    AvFindingCode.ANALYSIS_UNAVAILABLE,
                    FindingSeverity.REVIEW, "complete objective measurements", safe,
                ))
        else:
            if measurements.black_ratio > policy.max_black_ratio:
                findings.append(_finding(
                    AvFindingCode.BLACK_DURATION_EXCEEDED, FindingSeverity.BLOCKER,
                    f"<= {policy.max_black_ratio:.6f}", f"{measurements.black_ratio:.6f}",
                ))
            if measurements.freeze_ratio > policy.max_freeze_ratio:
                findings.append(_finding(
                    AvFindingCode.FREEZE_DURATION_EXCEEDED, FindingSeverity.BLOCKER,
                    f"<= {policy.max_freeze_ratio:.6f}", f"{measurements.freeze_ratio:.6f}",
                ))
            if measurements.silence_ratio > policy.max_silence_ratio:
                findings.append(_finding(
                    AvFindingCode.SILENCE_DURATION_EXCEEDED, FindingSeverity.BLOCKER,
                    f"<= {policy.max_silence_ratio:.6f}", f"{measurements.silence_ratio:.6f}",
                ))
            if abs(measurements.integrated_lufs - policy.target_lufs) > policy.loudness_tolerance_lu:
                findings.append(_finding(
                    AvFindingCode.LOUDNESS_OUT_OF_RANGE, FindingSeverity.BLOCKER,
                    f"{policy.target_lufs:.2f} +/- {policy.loudness_tolerance_lu:.2f} LU",
                    f"{measurements.integrated_lufs:.2f} LUFS",
                ))
            if measurements.true_peak_dbtp > policy.max_true_peak_dbtp:
                findings.append(_finding(
                    AvFindingCode.TRUE_PEAK_EXCEEDED, FindingSeverity.BLOCKER,
                    f"<= {policy.max_true_peak_dbtp:.2f} dBTP",
                    f"{measurements.true_peak_dbtp:.2f} dBTP",
                ))

        ordered = tuple(findings)
        if any(item.severity == FindingSeverity.BLOCKER for item in ordered):
            decision = AvDecision.FAIL
        elif ordered:
            decision = AvDecision.NEEDS_HUMAN
        else:
            decision = AvDecision.PASS
        return AvEvaluationReport(
            asset_id=asset.asset_id, content_id=metadata.content_id,
            integrity_evidence_fingerprint=integrity.evidence_fingerprint,
            policy=policy, decision=decision, findings=ordered,
            measurements=measurements,
            subjective_signals_not_evaluated=tuple(SubjectiveSignal),
            evidence_fingerprint=av_evidence_fingerprint(
                asset_id=asset.asset_id, content_id=metadata.content_id,
                integrity_evidence_fingerprint=integrity.evidence_fingerprint,
                policy=policy, findings=ordered, measurements=measurements,
            ),
        )
