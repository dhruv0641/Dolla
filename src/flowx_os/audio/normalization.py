"""Bounded local narration timing and FFmpeg normalization."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
from uuid import UUID
import wave

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.assets.probing import MediaProbeError, MediaProbeService, ProbePolicy, _run
from flowx_os.assets.storage import StoredAssetFile
from flowx_os.audio.synthesis import AssetIngest
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind


class AudioNormalizationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class NarrationTiming(BaseModel):
    """Primary narration is anchored at the first video frame."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    start_ms: int = Field(ge=0, le=180_000)
    content_duration_ms: int = Field(ge=1, le=180_000)

    @model_validator(mode="after")
    def starts_at_zero(self) -> "NarrationTiming":
        if self.start_ms != 0:
            raise ValueError("primary narration must start at zero milliseconds")
        return self


class AudioNormalizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    request_id: UUID
    source_asset_id: UUID
    output_asset_id: UUID
    brand_id: UUID
    content_id: UUID
    scene_id: UUID | None = None
    owner_user_id: str = Field(min_length=1, max_length=200)
    timing: NarrationTiming

    @field_validator("owner_user_id")
    @classmethod
    def owner_is_safe(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("owner identity is invalid")
        return value

    @model_validator(mode="after")
    def distinct_assets(self) -> "AudioNormalizationRequest":
        if self.source_asset_id == self.output_asset_id:
            raise ValueError("normalization output must use a new asset identity")
        return self


@dataclass(frozen=True, slots=True)
class AudioNormalizationPolicy:
    sample_rate_hz: int = 48_000
    channels: int = 1
    integrated_lufs: float = -16.0
    true_peak_dbtp: float = -1.5
    loudness_range_lu: float = 11.0
    duration_tolerance_ms: int = 20
    timeout_seconds: float = 120.0
    max_input_bytes: int = 250_000_000
    max_output_bytes: int = 250_000_000
    tool_output_limit: int = 1_000_000

    def __post_init__(self) -> None:
        if type(self.sample_rate_hz) is not int or not 8_000 <= self.sample_rate_hz <= 96_000:
            raise ValueError("normalization sample rate is invalid")
        if type(self.channels) is not int or self.channels not in {1, 2}:
            raise ValueError("normalization channel count is invalid")
        for value in (self.integrated_lufs, self.true_peak_dbtp, self.loudness_range_lu, self.timeout_seconds):
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError("normalization numeric policy is invalid")
        if not -70 <= self.integrated_lufs <= -5 or not -9 <= self.true_peak_dbtp <= 0 or not 1 <= self.loudness_range_lu <= 50:
            raise ValueError("normalization loudness policy is invalid")
        if not 0 < self.timeout_seconds <= 600:
            raise ValueError("normalization timeout is invalid")
        if type(self.duration_tolerance_ms) is not int or not 0 <= self.duration_tolerance_ms <= 1_000:
            raise ValueError("normalization duration tolerance is invalid")
        for value in (self.max_input_bytes, self.max_output_bytes):
            if type(value) is not int or not 1_024 <= value <= 1_000_000_000:
                raise ValueError("normalization byte limit is invalid")
        if type(self.tool_output_limit) is not int or not 1_024 <= self.tool_output_limit <= 8_000_000:
            raise ValueError("normalization tool output limit is invalid")


@dataclass(frozen=True, slots=True)
class AudioNormalizationResult:
    request_id: UUID
    output_asset_id: UUID
    plan_fingerprint: str
    start_ms: int
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int


def normalization_fingerprint(request: AudioNormalizationRequest, policy: AudioNormalizationPolicy) -> str:
    payload = {
        "schema": 1,
        "request_id": request.request_id.hex,
        "source_asset_id": request.source_asset_id.hex,
        "output_asset_id": request.output_asset_id.hex,
        "brand_id": request.brand_id.hex,
        "content_id": request.content_id.hex,
        "scene_id": request.scene_id.hex if request.scene_id else None,
        "start_ms": request.timing.start_ms,
        "content_duration_ms": request.timing.content_duration_ms,
        "sample_rate_hz": policy.sample_rate_hz,
        "channels": policy.channels,
        "integrated_lufs": policy.integrated_lufs,
        "true_peak_dbtp": policy.true_peak_dbtp,
        "loudness_range_lu": policy.loudness_range_lu,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _snapshot(asset: StoredAssetFile, *, storage_root: Path, destination: Path,
              max_bytes: int) -> None:
    root = Path(storage_root).expanduser().resolve() / "assets"
    expected = root / asset.asset_id.hex / "payload"
    digest = hashlib.sha256()
    size = 0
    try:
        if (asset.path.absolute() != expected or root.is_symlink() or expected.parent.is_symlink()
                or expected.is_symlink() or not stat.S_ISREG(expected.lstat().st_mode)
                or expected.lstat().st_nlink != 1):
            raise AudioNormalizationError("SOURCE_PATH_UNSAFE", "narration source path is unsafe")
        with expected.open("rb") as incoming, destination.open("xb") as output:
            before = os.fstat(incoming.fileno())
            while block := incoming.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise AudioNormalizationError("SOURCE_SIZE_LIMIT", "narration source exceeds the byte limit")
                digest.update(block)
                output.write(block)
            after = os.fstat(incoming.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if (identity(before) != identity(after) or size != asset.size_bytes
                or digest.hexdigest() != asset.sha256_hex):
            raise AudioNormalizationError("SOURCE_INTEGRITY_MISMATCH", "narration source integrity changed")
    except AudioNormalizationError:
        raise
    except OSError as exc:
        raise AudioNormalizationError("SOURCE_UNAVAILABLE", "narration source is unavailable") from exc


def _inspect_output(path: Path, *, policy: AudioNormalizationPolicy,
                    target_duration_ms: int) -> tuple[int, int]:
    try:
        file_stat = path.lstat()
        if (path.parent.is_symlink() or path.is_symlink() or not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_nlink != 1):
            raise AudioNormalizationError("OUTPUT_PATH_UNSAFE", "normalized output path is unsafe")
        if not 44 <= file_stat.st_size <= policy.max_output_bytes:
            raise AudioNormalizationError("OUTPUT_SIZE_INVALID", "normalized output size is invalid")
        with wave.open(os.fspath(path), "rb") as stream:
            if stream.getcomptype() != "NONE":
                raise AudioNormalizationError("OUTPUT_ENCODING_INVALID", "normalized output must be PCM WAV")
            rate, channels = stream.getframerate(), stream.getnchannels()
            width, frames = stream.getsampwidth(), stream.getnframes()
        if rate != policy.sample_rate_hz or channels != policy.channels or width != 2 or frames <= 0:
            raise AudioNormalizationError("OUTPUT_FORMAT_MISMATCH", "normalized output does not match policy")
        duration_ms = round(frames * 1000 / rate)
        if abs(duration_ms - target_duration_ms) > policy.duration_tolerance_ms:
            raise AudioNormalizationError("OUTPUT_DURATION_MISMATCH", "normalized output duration does not match timeline")
        return duration_ms, width
    except AudioNormalizationError:
        raise
    except (OSError, EOFError, wave.Error) as exc:
        raise AudioNormalizationError("OUTPUT_WAV_INVALID", "normalized output is not valid WAV") from exc


class AudioNormalizationService:
    """Normalize an authorized managed narration asset and ingest the derived WAV."""

    _DEMUXERS = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg"}

    def __init__(self, *, storage_root: Path, asset_ingest: AssetIngest,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                 policy: AudioNormalizationPolicy | None = None) -> None:
        self._root = Path(storage_root).expanduser().resolve()
        self._ingest = asset_ingest
        self._ffmpeg = ffmpeg
        self._policy = policy or AudioNormalizationPolicy()
        self._probe = MediaProbeService(
            self._root, ffprobe=ffprobe, ffmpeg=ffmpeg,
            timeout_seconds=self._policy.timeout_seconds,
            max_bytes=self._policy.max_input_bytes,
            output_limit=self._policy.tool_output_limit,
        )

    async def normalize(self, *, request: AudioNormalizationRequest,
                        source: StoredAssetFile,
                        source_record: AssetRecord) -> AudioNormalizationResult:
        if (not isinstance(request, AudioNormalizationRequest)
                or not isinstance(source, StoredAssetFile)
                or not isinstance(source_record, AssetRecord)):
            raise ValueError("normalization request, source and owner-scoped record are required")
        if source.asset_id != request.source_asset_id:
            raise AudioNormalizationError("SOURCE_ID_MISMATCH", "narration source identity does not match request")
        metadata = source_record.metadata
        if (metadata.asset_id != source.asset_id or metadata.content_id != request.content_id
                or metadata.scene_id != request.scene_id or metadata.kind != AssetKind.NARRATION
                or metadata.storage_uri != source.storage_uri or metadata.sha256_hex != source.sha256_hex
                or metadata.mime_type != source.mime_type or metadata.size_bytes != source.size_bytes):
            raise AudioNormalizationError(
                "SOURCE_LINEAGE_MISMATCH", "narration source is outside the authorized content lineage",
            )
        demuxer = self._DEMUXERS.get(source.mime_type)
        if demuxer is None:
            raise AudioNormalizationError("SOURCE_TYPE_UNSUPPORTED", "narration source type is unsupported")
        target_seconds = request.timing.content_duration_ms / 1000
        try:
            report = await asyncio.to_thread(
                self._probe.inspect, source,
                ProbePolicy(require_video=False, require_audio=True),
            )
        except MediaProbeError as exc:
            raise AudioNormalizationError("SOURCE_MEDIA_INVALID", "narration source failed media validation") from exc
        if not report.passed:
            raise AudioNormalizationError("SOURCE_MEDIA_INVALID", "narration source failed media policy")
        tolerance = self._policy.duration_tolerance_ms / 1000
        if report.duration_seconds > target_seconds + tolerance:
            raise AudioNormalizationError("NARRATION_TOO_LONG", "narration exceeds the content timeline")
        fingerprint = normalization_fingerprint(request, self._policy)
        try:
            with tempfile.TemporaryDirectory(prefix=f"audio-{request.request_id.hex}-") as directory:
                temporary = Path(directory)
                snapshot = temporary / "source"
                output = temporary / "normalized.wav"
                await asyncio.to_thread(
                    _snapshot, source, storage_root=self._root,
                    destination=snapshot, max_bytes=self._policy.max_input_bytes,
                )
                loudnorm = (
                    f"loudnorm=I={self._policy.integrated_lufs}:TP={self._policy.true_peak_dbtp}:"
                    f"LRA={self._policy.loudness_range_lu},aresample={self._policy.sample_rate_hz},"
                    f"apad=whole_dur={target_seconds:.3f},atrim=duration={target_seconds:.3f},asetpts=PTS-STARTPTS"
                )
                await asyncio.to_thread(
                    _run,
                    [self._ffmpeg, "-nostdin", "-v", "error", "-xerror", "-threads", "1",
                     "-protocol_whitelist", "file", "-format_whitelist", demuxer, "-f", demuxer,
                     "-i", str(snapshot), "-map", "0:a:0", "-vn", "-af", loudnorm,
                     "-c:a", "pcm_s16le", "-ar", str(self._policy.sample_rate_hz),
                     "-ac", str(self._policy.channels), "-map_metadata", "-1", "-f", "wav", str(output)],
                    timeout=self._policy.timeout_seconds,
                    output_limit=self._policy.tool_output_limit,
                )
                duration_ms, width = await asyncio.to_thread(
                    _inspect_output, output, policy=self._policy,
                    target_duration_ms=request.timing.content_duration_ms,
                )
                await self._ingest.ingest(
                    asset_id=request.output_asset_id, source_path=output, mime_type="audio/wav",
                    brand_id=request.brand_id, content_id=request.content_id,
                    owner_user_id=request.owner_user_id, kind=AssetKind.NARRATION,
                    scene_id=request.scene_id,
                    media_metadata={
                        "normalization_version": 1,
                        "normalization_fingerprint": fingerprint,
                        "source_asset_id": source.asset_id.hex,
                        "timeline_start_ms": 0,
                        "duration_ms": duration_ms,
                        "sample_rate_hz": self._policy.sample_rate_hz,
                        "channels": self._policy.channels,
                        "sample_width_bytes": width,
                        "integrated_lufs_target": self._policy.integrated_lufs,
                        "true_peak_dbtp_target": self._policy.true_peak_dbtp,
                        "loudness_range_lu_target": self._policy.loudness_range_lu,
                        "loudness_measurement_verified": False,
                    },
                )
        except AudioNormalizationError:
            raise
        except MediaProbeError as exc:
            raise AudioNormalizationError("NORMALIZATION_TOOL_FAILED", "local audio normalization failed") from exc
        except Exception as exc:
            raise AudioNormalizationError("NORMALIZATION_FAILED", "audio normalization could not be completed safely") from exc
        return AudioNormalizationResult(
            request.request_id, request.output_asset_id, fingerprint, 0, duration_ms,
            self._policy.sample_rate_hz, self._policy.channels, width,
        )
