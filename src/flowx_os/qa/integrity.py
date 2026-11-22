"""Deterministic final/export media integrity checks with safe findings."""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flowx_os.assets.probing import MediaProbeError, MediaReport, ProbePolicy
from flowx_os.assets.storage import StoredAssetFile
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind


_SAFE_PROBE_CODE = re.compile(r"^MEDIA_[A-Z0-9_]{1,63}$")
_MP4_CONTAINERS = frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})


class IntegrityCheckError(RuntimeError):
    """Safe structural error at the owner-scoped QA boundary."""


class IntegrityDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class IntegrityFindingCode(StrEnum):
    DECLARED_PROFILE_MISMATCH = "DECLARED_PROFILE_MISMATCH"
    DECLARED_METADATA_MISMATCH = "DECLARED_METADATA_MISMATCH"
    ASSET_INTEGRITY_UNVERIFIED = "ASSET_INTEGRITY_UNVERIFIED"
    HASH_MISMATCH = "HASH_MISMATCH"
    DECODE_UNVERIFIED = "DECODE_UNVERIFIED"
    CONTAINER_MISMATCH = "CONTAINER_MISMATCH"
    VIDEO_STREAM_COUNT = "VIDEO_STREAM_COUNT"
    VIDEO_CODEC_MISMATCH = "VIDEO_CODEC_MISMATCH"
    VIDEO_PROFILE_MISMATCH = "VIDEO_PROFILE_MISMATCH"
    PIXEL_FORMAT_MISMATCH = "PIXEL_FORMAT_MISMATCH"
    DIMENSIONS_MISMATCH = "DIMENSIONS_MISMATCH"
    FRAME_RATE_MISMATCH = "FRAME_RATE_MISMATCH"
    AUDIO_STREAM_COUNT = "AUDIO_STREAM_COUNT"
    AUDIO_CODEC_MISMATCH = "AUDIO_CODEC_MISMATCH"
    SUBTITLE_STREAM_COUNT = "SUBTITLE_STREAM_COUNT"
    SUBTITLE_CODEC_MISMATCH = "SUBTITLE_CODEC_MISMATCH"
    DURATION_MISMATCH = "DURATION_MISMATCH"


class IntegrityExpectation(BaseModel):
    """Versioned expected evidence for one render artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    asset_id: UUID
    content_id: UUID
    expected_kind: AssetKind
    artifact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    width: int = Field(ge=16, le=7680)
    height: int = Field(ge=16, le=7680)
    frame_rate: int = Field(ge=1, le=60)
    video_profile: str = Field(default="High", pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._:+-]{0,63}$")
    pixel_format: str = Field(default="yuv420p", pattern=r"^[a-z0-9_]{1,64}$")
    duration_ms: int = Field(ge=1, le=180_000)
    duration_tolerance_ms: int = Field(default=250, ge=0, le=2_000)
    require_audio: bool = True
    require_subtitle: bool = True

    @model_validator(mode="after")
    def role_contract(self) -> "IntegrityExpectation":
        if self.expected_kind not in {AssetKind.FINAL_VIDEO, AssetKind.EXPORT_VARIANT}:
            raise ValueError("integrity checks require a render artifact")
        if self.expected_kind == AssetKind.FINAL_VIDEO and self.profile_id is not None:
            raise ValueError("final video cannot have an export profile")
        if self.expected_kind == AssetKind.EXPORT_VARIANT and self.profile_id is None:
            raise ValueError("export variant requires a profile")
        return self


class IntegrityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    code: IntegrityFindingCode
    expected: str = Field(min_length=1, max_length=100)
    observed: str = Field(min_length=1, max_length=100)


class IntegrityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    asset_id: UUID
    content_id: UUID
    expected_kind: AssetKind
    profile_id: str | None
    artifact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: IntegrityDecision
    findings: tuple[IntegrityFinding, ...]
    decode_verified: bool
    observed_sha256_hex: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class MediaInspector(Protocol):
    def inspect(self, asset: StoredAssetFile, policy: ProbePolicy | None = None) -> MediaReport: ...


def _finding(code: IntegrityFindingCode, expected: object, observed: object) -> IntegrityFinding:
    return IntegrityFinding(code=code, expected=str(expected)[:100], observed=str(observed)[:100])


def _fingerprint(expectation: IntegrityExpectation, findings: tuple[IntegrityFinding, ...],
                 report: MediaReport | None) -> str:
    payload = {
        "expectation": expectation.model_dump(mode="json"),
        "findings": [item.model_dump(mode="json") for item in findings],
        "probe": None if report is None else {
            "sha256_hex": report.sha256_hex,
            "duration_seconds": report.duration_seconds,
            "decoded_duration_seconds": report.decoded_duration_seconds,
            "decode_verified": report.decode_verified,
            "container_names": list(report.container_names),
            "streams": [
                {
                    "kind": stream.kind, "codec": stream.codec,
                    "width": stream.width, "height": stream.height,
                    "frame_rate": stream.frame_rate,
                    "video_profile": stream.video_profile,
                    "pixel_format": stream.pixel_format,
                }
                for stream in report.streams
            ],
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class MediaIntegrityService:
    """Evaluate immutable owner-scoped render bytes; never publish or approve."""

    def __init__(self, inspector: MediaInspector) -> None:
        if not hasattr(inspector, "inspect"):
            raise ValueError("media inspector is required")
        self._inspector = inspector

    def evaluate(
        self, expectation: IntegrityExpectation, asset: StoredAssetFile,
        record: AssetRecord,
    ) -> IntegrityReport:
        if (not isinstance(expectation, IntegrityExpectation)
                or not isinstance(asset, StoredAssetFile)
                or not isinstance(record, AssetRecord)):
            raise ValueError("integrity expectation and owner-scoped asset are required")
        metadata = record.metadata
        if (asset.asset_id != expectation.asset_id or metadata.asset_id != expectation.asset_id
                or metadata.content_id != expectation.content_id
                or metadata.kind != expectation.expected_kind or metadata.scene_id is not None
                or metadata.mime_type != "video/mp4" or asset.mime_type != "video/mp4"
                or metadata.storage_uri != asset.storage_uri
                or metadata.sha256_hex != asset.sha256_hex
                or metadata.size_bytes != asset.size_bytes):
            raise IntegrityCheckError("ASSET_LINEAGE_MISMATCH")

        findings: list[IntegrityFinding] = []
        declared = metadata.media_metadata
        if expectation.expected_kind == AssetKind.FINAL_VIDEO:
            declared_fingerprint = declared.get("composition_fingerprint")
            declared_width, declared_height = declared.get("target_width"), declared.get("target_height")
        else:
            declared_fingerprint = declared.get("export_fingerprint")
            declared_width, declared_height = declared.get("width"), declared.get("height")
            if declared.get("export_profile_id") != expectation.profile_id:
                findings.append(_finding(IntegrityFindingCode.DECLARED_PROFILE_MISMATCH, expectation.profile_id, declared.get("export_profile_id")))
        declared_tuple = (
            declared_fingerprint, declared_width, declared_height,
            declared.get("frame_rate"), declared.get("duration_ms"),
            declared.get("subtitles_muxed"),
        )
        expected_tuple = (
            expectation.artifact_fingerprint, expectation.width, expectation.height,
            expectation.frame_rate, expectation.duration_ms, expectation.require_subtitle,
        )
        if declared_tuple != expected_tuple:
            findings.append(_finding(IntegrityFindingCode.DECLARED_METADATA_MISMATCH, "expected render contract", "stored metadata differs"))

        probe: MediaReport | None = None
        try:
            probe = self._inspector.inspect(asset, ProbePolicy(require_audio=False))
        except MediaProbeError as exc:
            safe = str(exc) if _SAFE_PROBE_CODE.fullmatch(str(exc)) else "MEDIA_PROBE_FAILED"
            findings.append(_finding(IntegrityFindingCode.ASSET_INTEGRITY_UNVERIFIED, "verified managed bytes", safe))
        else:
            videos = [item for item in probe.streams if item.kind == "video"]
            audios = [item for item in probe.streams if item.kind == "audio"]
            subtitles = [item for item in probe.streams if item.kind == "subtitle"]
            if probe.sha256_hex != metadata.sha256_hex:
                findings.append(_finding(IntegrityFindingCode.HASH_MISMATCH, metadata.sha256_hex, probe.sha256_hex))
            if not probe.decode_verified or probe.violations:
                findings.append(_finding(IntegrityFindingCode.DECODE_UNVERIFIED, "full decode without violations", "not verified"))
            if "mp4" not in probe.container_names or not set(probe.container_names) <= _MP4_CONTAINERS:
                findings.append(_finding(IntegrityFindingCode.CONTAINER_MISMATCH, "mp4", ",".join(probe.container_names) or "unknown"))
            if len(videos) != 1:
                findings.append(_finding(IntegrityFindingCode.VIDEO_STREAM_COUNT, 1, len(videos)))
            else:
                video = videos[0]
                if video.codec != "h264":
                    findings.append(_finding(IntegrityFindingCode.VIDEO_CODEC_MISMATCH, "h264", video.codec))
                if video.video_profile != expectation.video_profile:
                    findings.append(_finding(IntegrityFindingCode.VIDEO_PROFILE_MISMATCH, expectation.video_profile, video.video_profile or "unknown"))
                if video.pixel_format != expectation.pixel_format:
                    findings.append(_finding(IntegrityFindingCode.PIXEL_FORMAT_MISMATCH, expectation.pixel_format, video.pixel_format or "unknown"))
                if (video.width, video.height) != (expectation.width, expectation.height):
                    findings.append(_finding(IntegrityFindingCode.DIMENSIONS_MISMATCH, f"{expectation.width}x{expectation.height}", f"{video.width}x{video.height}"))
                if (video.frame_rate is None or not math.isfinite(video.frame_rate)
                        or abs(video.frame_rate - expectation.frame_rate) > 0.001):
                    findings.append(_finding(IntegrityFindingCode.FRAME_RATE_MISMATCH, expectation.frame_rate, video.frame_rate or "unknown"))
            required_audio = 1 if expectation.require_audio else 0
            if (expectation.require_audio and len(audios) != 1) or (not expectation.require_audio and len(audios) > 1):
                findings.append(_finding(IntegrityFindingCode.AUDIO_STREAM_COUNT, required_audio, len(audios)))
            elif audios and audios[0].codec != "aac":
                findings.append(_finding(IntegrityFindingCode.AUDIO_CODEC_MISMATCH, "aac", audios[0].codec))
            required_subtitle = 1 if expectation.require_subtitle else 0
            if (expectation.require_subtitle and len(subtitles) != 1) or (not expectation.require_subtitle and subtitles):
                findings.append(_finding(IntegrityFindingCode.SUBTITLE_STREAM_COUNT, required_subtitle, len(subtitles)))
            elif subtitles and subtitles[0].codec != "mov_text":
                findings.append(_finding(IntegrityFindingCode.SUBTITLE_CODEC_MISMATCH, "mov_text", subtitles[0].codec))
            observed_ms = round(probe.duration_seconds * 1000)
            if abs(observed_ms - expectation.duration_ms) > expectation.duration_tolerance_ms:
                findings.append(_finding(IntegrityFindingCode.DURATION_MISMATCH, expectation.duration_ms, observed_ms))

        ordered = tuple(findings)
        decision = IntegrityDecision.PASS if not ordered else IntegrityDecision.FAIL
        return IntegrityReport(
            asset_id=expectation.asset_id, content_id=expectation.content_id,
            expected_kind=expectation.expected_kind, profile_id=expectation.profile_id,
            artifact_fingerprint=expectation.artifact_fingerprint,
            decision=decision, findings=ordered,
            decode_verified=bool(probe and probe.decode_verified),
            observed_sha256_hex=None if probe is None else probe.sha256_hex,
            evidence_fingerprint=_fingerprint(expectation, ordered, probe),
        )
