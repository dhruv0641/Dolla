"""Fail-closed local FFmpeg worker and deterministic persistence manifests."""

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
from typing import Literal, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.assets.probing import MediaProbeError, _run
from flowx_os.assets.storage import StoredAssetFile
from flowx_os.audio.synthesis import AssetIngest
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind


class RenderError(RuntimeError):
    """Stable, safe-to-display render failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class RenderRequest(BaseModel):
    """Authorized identity and immutable inputs for one baseline render."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: UUID
    brand_id: UUID
    content_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=200)
    render_version: int = Field(ge=1, le=1_000_000)
    input_asset_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    output_asset_id: UUID

    @field_validator("owner_user_id")
    @classmethod
    def owner_is_safe(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("owner identity is invalid")
        return value

    @model_validator(mode="after")
    def identities_are_distinct(self) -> "RenderRequest":
        if len(set(self.input_asset_ids)) != len(self.input_asset_ids):
            raise ValueError("render input identities must be unique")
        if self.output_asset_id in self.input_asset_ids:
            raise ValueError("render output must use a new asset identity")
        return self


@dataclass(frozen=True, slots=True)
class RenderPolicy:
    """Operator-controlled limits; arbitrary caller-supplied FFmpeg flags are forbidden."""

    timeout_seconds: float = 300.0
    max_input_bytes: int = 2_000_000_000
    max_output_bytes: int = 2_000_000_000
    tool_output_limit: int = 1_000_000
    video_codec: Literal["libx264"] = "libx264"
    audio_codec: Literal["aac"] = "aac"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    preset: Literal["medium"] = "medium"

    def __post_init__(self) -> None:
        if (isinstance(self.timeout_seconds, bool) or not math.isfinite(self.timeout_seconds)
                or not 1 <= self.timeout_seconds <= 3_600):
            raise ValueError("render timeout is invalid")
        for value in (self.max_input_bytes, self.max_output_bytes):
            if type(value) is not int or not 1_024 <= value <= 4_000_000_000:
                raise ValueError("render byte limit is invalid")
        if type(self.tool_output_limit) is not int or not 1_024 <= self.tool_output_limit <= 8_000_000:
            raise ValueError("render tool output limit is invalid")
        if (self.video_codec, self.audio_codec, self.pixel_format, self.preset) != (
            "libx264", "aac", "yuv420p", "medium",
        ):
            raise ValueError("render codec policy is unsupported")


class RenderInputManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    position: int = Field(ge=0, le=99)
    asset_id: UUID
    sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: str = Field(pattern=r"^video/(mp4|webm)$")
    size_bytes: int = Field(gt=0, le=4_000_000_000)


class RenderManifest(BaseModel):
    """Path-free manifest safe for durable render_jobs JSON columns."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1] = 1
    operation: Literal["BASELINE_SINGLE_VIDEO"] = "BASELINE_SINGLE_VIDEO"
    request_id: UUID
    content_id: UUID
    render_version: int = Field(ge=1, le=1_000_000)
    output_asset_id: UUID
    inputs: tuple[RenderInputManifest, ...] = Field(min_length=1, max_length=100)
    output_mime_type: Literal["video/mp4"] = "video/mp4"
    video_codec: Literal["libx264"] = "libx264"
    audio_codec: Literal["aac"] = "aac"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    preset: Literal["medium"] = "medium"
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    def inputs_manifest(self) -> dict[str, list[str]]:
        """Normalized shape enforced by migration 0010."""
        return {"asset_ids": [str(item.asset_id) for item in self.inputs]}

    def command_manifest(self) -> dict[str, object]:
        """Declarative execution evidence without local paths or raw arguments."""
        return self.model_dump(
            mode="json", exclude={"inputs", "content_id", "output_asset_id"},
        )


@dataclass(frozen=True, slots=True)
class RenderResult:
    request_id: UUID
    output_asset_id: UUID
    manifest: RenderManifest
    output_size_bytes: int
    output_sha256_hex: str


def _manifest_payload(
    request: RenderRequest, inputs: Sequence[RenderInputManifest], policy: RenderPolicy,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "BASELINE_SINGLE_VIDEO",
        "request_id": request.request_id,
        "content_id": request.content_id,
        "render_version": request.render_version,
        "output_asset_id": request.output_asset_id,
        "inputs": tuple(inputs),
        "output_mime_type": "video/mp4",
        "video_codec": policy.video_codec,
        "audio_codec": policy.audio_codec,
        "pixel_format": policy.pixel_format,
        "preset": policy.preset,
    }


def build_render_manifest(
    request: RenderRequest, records: Sequence[AssetRecord], policy: RenderPolicy,
) -> RenderManifest:
    if not isinstance(request, RenderRequest) or not isinstance(policy, RenderPolicy):
        raise ValueError("render request and policy are required")
    if len(records) != len(request.input_asset_ids):
        raise RenderError("INPUT_SET_MISMATCH", "render inputs do not match the request")
    inputs: list[RenderInputManifest] = []
    for position, (asset_id, record) in enumerate(zip(request.input_asset_ids, records, strict=True)):
        if not isinstance(record, AssetRecord):
            raise ValueError("owner-scoped asset records are required")
        metadata = record.metadata
        if metadata.asset_id != asset_id or metadata.content_id != request.content_id:
            raise RenderError("INPUT_LINEAGE_MISMATCH", "render input is outside the authorized content lineage")
        if metadata.kind not in {AssetKind.RAW_FLOW_CLIP, AssetKind.FINAL_VIDEO, AssetKind.EXPORT_VARIANT}:
            raise RenderError("INPUT_KIND_UNSUPPORTED", "render input kind is unsupported")
        if metadata.mime_type not in {"video/mp4", "video/webm"}:
            raise RenderError("INPUT_TYPE_UNSUPPORTED", "render input type is unsupported")
        inputs.append(RenderInputManifest(
            position=position, asset_id=asset_id, sha256_hex=metadata.sha256_hex,
            mime_type=metadata.mime_type, size_bytes=metadata.size_bytes,
        ))
    # Composition is deliberately introduced by TASK-043; the base worker handles one video safely.
    if len(inputs) != 1:
        raise RenderError("OPERATION_UNSUPPORTED", "baseline render requires exactly one video input")
    payload = _manifest_payload(request, inputs, policy)
    canonical = {
        **payload,
        "request_id": request.request_id.hex,
        "content_id": request.content_id.hex,
        "output_asset_id": request.output_asset_id.hex,
        "inputs": [item.model_dump(mode="json") for item in inputs],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return RenderManifest.model_validate({**payload, "fingerprint": hashlib.sha256(encoded).hexdigest()})


def _snapshot(
    source: StoredAssetFile, evidence: RenderInputManifest, *, storage_root: Path,
    destination: Path, max_bytes: int,
) -> None:
    root = Path(storage_root).expanduser().resolve() / "assets"
    expected = root / source.asset_id.hex / "payload"
    digest = hashlib.sha256()
    size = 0
    try:
        if (source.asset_id != evidence.asset_id or source.storage_uri != f"managed://assets/{source.asset_id.hex}/payload"
                or source.mime_type != evidence.mime_type or source.sha256_hex != evidence.sha256_hex
                or source.size_bytes != evidence.size_bytes or source.path.absolute() != expected
                or root.is_symlink() or expected.parent.is_symlink() or expected.is_symlink()
                or not stat.S_ISREG(expected.lstat().st_mode) or expected.lstat().st_nlink != 1):
            raise RenderError("INPUT_PATH_UNSAFE", "render input path or metadata is unsafe")
        with expected.open("rb") as incoming, destination.open("xb") as output:
            before = os.fstat(incoming.fileno())
            while block := incoming.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise RenderError("INPUT_SIZE_LIMIT", "render input exceeds the byte limit")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(incoming.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if (identity(before) != identity(after) or size != evidence.size_bytes
                or digest.hexdigest() != evidence.sha256_hex):
            raise RenderError("INPUT_INTEGRITY_MISMATCH", "render input integrity changed")
    except RenderError:
        raise
    except OSError as exc:
        raise RenderError("INPUT_UNAVAILABLE", "render input is unavailable") from exc


def _inspect_output(path: Path, *, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        file_stat = path.lstat()
        if path.parent.is_symlink() or path.is_symlink() or not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise RenderError("OUTPUT_PATH_UNSAFE", "render output path is unsafe")
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise RenderError("OUTPUT_SIZE_LIMIT", "render output exceeds the byte limit")
                digest.update(block)
        with path.open("rb") as stream:
            prefix = stream.read(12)
        if size < 12 or prefix[4:8] != b"ftyp":
            raise RenderError("OUTPUT_FORMAT_INVALID", "render output is not an MP4 file")
        return digest.hexdigest(), size
    except RenderError:
        raise
    except OSError as exc:
        raise RenderError("OUTPUT_UNAVAILABLE", "render output is unavailable") from exc


def _validate_output_media(path: Path, *, ffprobe: str, timeout: float, output_limit: int) -> None:
    try:
        raw = _run(
            [ffprobe, "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", "mov,mp4,m4a,3gp,3g2,mj2",
             "-f", "mov", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
            timeout=timeout, output_limit=output_limit,
        )
        payload = json.loads(raw)
        duration = float(payload["format"]["duration"])
        streams = payload["streams"]
        if (not math.isfinite(duration) or duration <= 0 or not isinstance(streams, list)
                or not any(item.get("codec_type") == "video" for item in streams if isinstance(item, dict))):
            raise ValueError("video stream or duration missing")
    except (MediaProbeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RenderError("OUTPUT_MEDIA_INVALID", "render output failed media validation") from exc


class FfmpegRenderWorker:
    """Execute a fixed baseline transcode against verified managed bytes."""

    _DEMUXERS = {"video/mp4": ("mov", "mov,mp4,m4a,3gp,3g2,mj2"), "video/webm": ("matroska", "matroska,webm")}

    def __init__(
        self, *, storage_root: Path, asset_ingest: AssetIngest, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
        policy: RenderPolicy | None = None,
    ) -> None:
        self._root = Path(storage_root).expanduser().resolve()
        self._ingest = asset_ingest
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._policy = policy or RenderPolicy()

    async def render(
        self, *, request: RenderRequest, sources: Sequence[StoredAssetFile],
        source_records: Sequence[AssetRecord],
    ) -> RenderResult:
        manifest = build_render_manifest(request, source_records, self._policy)
        if len(sources) != len(manifest.inputs):
            raise RenderError("INPUT_SET_MISMATCH", "render inputs do not match the request")
        source = sources[0]
        evidence = manifest.inputs[0]
        demuxer = self._DEMUXERS[evidence.mime_type]
        try:
            with tempfile.TemporaryDirectory(prefix=f"render-{request.request_id.hex}-") as directory:
                temporary = Path(directory)
                snapshot = temporary / "input"
                output = temporary / "output.mp4"
                await asyncio.to_thread(
                    _snapshot, source, evidence, storage_root=self._root,
                    destination=snapshot, max_bytes=self._policy.max_input_bytes,
                )
                await asyncio.to_thread(
                    _run,
                    [self._ffmpeg, "-nostdin", "-v", "error", "-xerror", "-threads", "1",
                     "-protocol_whitelist", "file", "-format_whitelist", demuxer[1], "-f", demuxer[0],
                     "-i", str(snapshot), "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "-1",
                     "-map_chapters", "-1", "-c:v", self._policy.video_codec, "-preset", self._policy.preset,
                     "-pix_fmt", self._policy.pixel_format, "-c:a", self._policy.audio_codec,
                     "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                     "-movflags", "+faststart", "-fs", str(self._policy.max_output_bytes),
                     "-threads", "1", "-f", "mp4", str(output)],
                    timeout=self._policy.timeout_seconds, output_limit=self._policy.tool_output_limit,
                )
                output_hash, output_size = await asyncio.to_thread(
                    _inspect_output, output, max_bytes=self._policy.max_output_bytes,
                )
                await asyncio.to_thread(
                    _validate_output_media, output, ffprobe=self._ffprobe,
                    timeout=self._policy.timeout_seconds, output_limit=self._policy.tool_output_limit,
                )
                await self._ingest.ingest(
                    asset_id=request.output_asset_id, source_path=output, mime_type="video/mp4",
                    brand_id=request.brand_id, content_id=request.content_id,
                    owner_user_id=request.owner_user_id, kind=AssetKind.FINAL_VIDEO,
                    media_metadata={
                        "render_manifest_schema": manifest.schema_version,
                        "render_operation": manifest.operation,
                        "render_version": manifest.render_version,
                        "render_fingerprint": manifest.fingerprint,
                        "input_asset_ids": [str(item.asset_id) for item in manifest.inputs],
                        "input_sha256": [item.sha256_hex for item in manifest.inputs],
                        "output_sha256_pre_ingest": output_hash,
                        "deterministic_command": True,
                    },
                )
        except RenderError:
            raise
        except MediaProbeError as exc:
            raise RenderError("FFMPEG_FAILED", "local render execution failed") from exc
        except Exception as exc:
            raise RenderError("RENDER_FAILED", "render could not be completed safely") from exc
        return RenderResult(request.request_id, request.output_asset_id, manifest, output_size, output_hash)
