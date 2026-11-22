"""Ordered scene, zero-start narration and subtitle composition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.assets.probing import MediaProbeError, _run
from flowx_os.assets.storage import StoredAssetFile
from flowx_os.audio.synthesis import AssetIngest
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind
from flowx_os.rendering.worker import (
    RenderError,
    RenderPolicy,
    _inspect_output,
    _validate_output_media,
    _video_filter,
)


class SceneCompositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    scene_number: int = Field(ge=1, le=30)
    scene_id: UUID
    asset_id: UUID
    start_ms: int = Field(ge=0, le=180_000)
    end_ms: int = Field(ge=1, le=180_000)

    @model_validator(mode="after")
    def duration_is_positive(self) -> "SceneCompositionInput":
        if self.end_ms <= self.start_ms:
            raise ValueError("scene duration must be positive")
        return self


class CompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    request_id: UUID
    brand_id: UUID
    content_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=200)
    render_version: int = Field(ge=1, le=1_000_000)
    storyboard_version: int = Field(ge=1, le=100_000)
    scenes: tuple[SceneCompositionInput, ...] = Field(min_length=1, max_length=30)
    narration_asset_id: UUID
    subtitle_asset_id: UUID
    output_asset_id: UUID

    @field_validator("owner_user_id")
    @classmethod
    def owner_is_safe(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("owner identity is invalid")
        return value

    @model_validator(mode="after")
    def timeline_and_assets_are_unambiguous(self) -> "CompositionRequest":
        if [item.scene_number for item in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("composition scenes must be sequential")
        if self.scenes[0].start_ms != 0:
            raise ValueError("composition timeline must start at zero")
        for previous, current in zip(self.scenes, self.scenes[1:]):
            if current.start_ms != previous.end_ms:
                raise ValueError("composition timeline must be contiguous")
        asset_ids = [item.asset_id for item in self.scenes] + [self.narration_asset_id, self.subtitle_asset_id]
        if len(set(asset_ids)) != len(asset_ids) or self.output_asset_id in asset_ids:
            raise ValueError("composition asset identities must be distinct")
        return self

    @property
    def duration_ms(self) -> int:
        return self.scenes[-1].end_ms

    @property
    def input_asset_ids(self) -> tuple[UUID, ...]:
        return tuple(item.asset_id for item in self.scenes) + (self.narration_asset_id, self.subtitle_asset_id)


class CompositionInputEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    position: int = Field(ge=0, le=99)
    role: Literal["SCENE", "NARRATION", "SUBTITLE"]
    asset_id: UUID
    sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: str
    size_bytes: int = Field(gt=0, le=4_000_000_000)
    scene_number: int | None = Field(default=None, ge=1, le=30)
    scene_id: UUID | None = None
    start_ms: int | None = Field(default=None, ge=0, le=180_000)
    end_ms: int | None = Field(default=None, ge=1, le=180_000)


class CompositionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1] = 1
    operation: Literal["COMPOSE_SCENES_AUDIO_SUBTITLES"] = "COMPOSE_SCENES_AUDIO_SUBTITLES"
    request_id: UUID
    content_id: UUID
    render_version: int
    storyboard_version: int
    duration_ms: int = Field(ge=1, le=180_000)
    output_asset_id: UUID
    inputs: tuple[CompositionInputEvidence, ...] = Field(min_length=3, max_length=32)
    target_width: int = Field(ge=16, le=7680, multiple_of=2)
    target_height: int = Field(ge=16, le=7680, multiple_of=2)
    frame_rate: int = Field(ge=1, le=60)
    fit_mode: Literal["COVER", "CONTAIN"]
    output_mime_type: Literal["video/mp4"] = "video/mp4"
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    def inputs_manifest(self) -> dict[str, list[str]]:
        return {"asset_ids": [str(item.asset_id) for item in self.inputs]}

    def command_manifest(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude={"inputs", "content_id", "output_asset_id"})
        payload["input_roles"] = [item.role for item in self.inputs]
        payload["scene_timeline"] = [
            {
                "input_position": item.position,
                "scene_number": item.scene_number,
                "scene_id": str(item.scene_id),
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
            }
            for item in self.inputs if item.role == "SCENE"
        ]
        payload["narration_input_position"] = next(
            item.position for item in self.inputs if item.role == "NARRATION"
        )
        payload["subtitle_input_position"] = next(
            item.position for item in self.inputs if item.role == "SUBTITLE"
        )
        return payload


@dataclass(frozen=True, slots=True)
class CompositionResult:
    request_id: UUID
    output_asset_id: UUID
    manifest: CompositionManifest
    output_sha256_hex: str
    output_size_bytes: int


def _matches(record: AssetRecord, source: StoredAssetFile, *, content_id: UUID) -> bool:
    metadata = record.metadata
    return (
        metadata.asset_id == source.asset_id
        and metadata.content_id == content_id
        and metadata.storage_uri == source.storage_uri
        and metadata.sha256_hex == source.sha256_hex
        and metadata.mime_type == source.mime_type
        and metadata.size_bytes == source.size_bytes
    )


def build_composition_manifest(
    request: CompositionRequest,
    records: Mapping[UUID, AssetRecord],
    sources: Mapping[UUID, StoredAssetFile],
    policy: RenderPolicy,
) -> CompositionManifest:
    if not isinstance(request, CompositionRequest) or not isinstance(policy, RenderPolicy):
        raise ValueError("composition request and policy are required")
    expected = set(request.input_asset_ids)
    if set(records) != expected or set(sources) != expected:
        raise RenderError("INPUT_SET_MISMATCH", "composition inputs do not match the request")
    evidence: list[CompositionInputEvidence] = []
    for position, scene in enumerate(request.scenes):
        source, record = sources[scene.asset_id], records[scene.asset_id]
        metadata = record.metadata
        if (not _matches(record, source, content_id=request.content_id)
                or metadata.scene_id != scene.scene_id
                or metadata.kind != AssetKind.RAW_FLOW_CLIP
                or metadata.mime_type not in {"video/mp4", "video/webm"}):
            raise RenderError("SCENE_LINEAGE_MISMATCH", "scene media is outside the authorized timeline lineage")
        evidence.append(CompositionInputEvidence(
            position=position, role="SCENE", asset_id=scene.asset_id,
            sha256_hex=metadata.sha256_hex, mime_type=metadata.mime_type,
            size_bytes=metadata.size_bytes, scene_number=scene.scene_number,
            scene_id=scene.scene_id, start_ms=scene.start_ms, end_ms=scene.end_ms,
        ))
    narration = records[request.narration_asset_id]
    narration_source = sources[request.narration_asset_id]
    narration_media = narration.metadata.media_metadata
    if (not _matches(narration, narration_source, content_id=request.content_id)
            or narration.metadata.kind != AssetKind.NARRATION
            or narration.metadata.scene_id is not None
            or narration.metadata.mime_type != "audio/wav"
            or narration_media.get("normalization_version") != 1
            or not isinstance(narration_media.get("normalization_fingerprint"), str)
            or re.fullmatch(r"[0-9a-f]{64}", narration_media["normalization_fingerprint"]) is None
            or narration_media.get("timeline_start_ms") != 0
            or narration_media.get("duration_ms") != request.duration_ms):
        raise RenderError("NARRATION_LINEAGE_MISMATCH", "normalized narration does not match the composition timeline")
    evidence.append(CompositionInputEvidence(
        position=len(evidence), role="NARRATION", asset_id=request.narration_asset_id,
        sha256_hex=narration.metadata.sha256_hex, mime_type=narration.metadata.mime_type,
        size_bytes=narration.metadata.size_bytes,
    ))
    subtitle = records[request.subtitle_asset_id]
    subtitle_source = sources[request.subtitle_asset_id]
    subtitle_media = subtitle.metadata.media_metadata
    if (not _matches(subtitle, subtitle_source, content_id=request.content_id)
            or subtitle.metadata.kind != AssetKind.CAPTION_SRT
            or subtitle.metadata.scene_id is not None
            or subtitle.metadata.mime_type != "text/plain"
            or subtitle_media.get("caption_version") != 1
            or not isinstance(subtitle_media.get("caption_fingerprint"), str)
            or re.fullmatch(r"[0-9a-f]{64}", subtitle_media["caption_fingerprint"]) is None
            or subtitle_media.get("storyboard_version") != request.storyboard_version
            or subtitle_media.get("normalized_audio_asset_id") != request.narration_asset_id.hex
            or subtitle_media.get("timeline_start_ms") != 0
            or subtitle_media.get("timeline_end_ms") != request.duration_ms):
        raise RenderError("SUBTITLE_LINEAGE_MISMATCH", "subtitle asset does not match the composition timeline")
    evidence.append(CompositionInputEvidence(
        position=len(evidence), role="SUBTITLE", asset_id=request.subtitle_asset_id,
        sha256_hex=subtitle.metadata.sha256_hex, mime_type=subtitle.metadata.mime_type,
        size_bytes=subtitle.metadata.size_bytes,
    ))
    base: dict[str, object] = {
        "schema_version": 1,
        "operation": "COMPOSE_SCENES_AUDIO_SUBTITLES",
        "request_id": request.request_id,
        "content_id": request.content_id,
        "render_version": request.render_version,
        "storyboard_version": request.storyboard_version,
        "duration_ms": request.duration_ms,
        "output_asset_id": request.output_asset_id,
        "inputs": tuple(evidence),
        "target_width": policy.target_width,
        "target_height": policy.target_height,
        "frame_rate": policy.frame_rate,
        "fit_mode": policy.fit_mode,
        "output_mime_type": "video/mp4",
    }
    canonical = {
        **base,
        "request_id": request.request_id.hex,
        "content_id": request.content_id.hex,
        "output_asset_id": request.output_asset_id.hex,
        "inputs": [item.model_dump(mode="json") for item in evidence],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return CompositionManifest.model_validate({**base, "fingerprint": hashlib.sha256(encoded).hexdigest()})


def _snapshot_asset(
    source: StoredAssetFile, evidence: CompositionInputEvidence, *, storage_root: Path,
    destination: Path, max_bytes: int,
) -> None:
    root = storage_root.resolve() / "assets"
    expected = root / source.asset_id.hex / "payload"
    digest = hashlib.sha256()
    size = 0
    try:
        if (source.asset_id != evidence.asset_id or source.path.absolute() != expected
                or source.storage_uri != f"managed://assets/{source.asset_id.hex}/payload"
                or source.sha256_hex != evidence.sha256_hex or source.size_bytes != evidence.size_bytes
                or source.mime_type != evidence.mime_type or root.is_symlink() or expected.parent.is_symlink()
                or expected.is_symlink() or not stat.S_ISREG(expected.lstat().st_mode)
                or expected.lstat().st_nlink != 1):
            raise RenderError("INPUT_PATH_UNSAFE", "composition input path or metadata is unsafe")
        with expected.open("rb") as incoming, destination.open("xb") as output:
            before = os.fstat(incoming.fileno())
            while block := incoming.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise RenderError("INPUT_SIZE_LIMIT", "composition input exceeds the byte limit")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(incoming.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if identity(before) != identity(after) or size != evidence.size_bytes or digest.hexdigest() != evidence.sha256_hex:
            raise RenderError("INPUT_INTEGRITY_MISMATCH", "composition input integrity changed")
    except RenderError:
        raise
    except OSError as exc:
        raise RenderError("INPUT_UNAVAILABLE", "composition input is unavailable") from exc


def _filter_graph(request: CompositionRequest, policy: RenderPolicy) -> str:
    parts: list[str] = []
    labels: list[str] = []
    for index, scene in enumerate(request.scenes):
        duration = (scene.end_ms - scene.start_ms) / 1000
        label = f"v{index}"
        parts.append(
            f"[{index}:v:0]{_video_filter(policy)},"
            f"tpad=stop_mode=clone:stop_duration={duration:.3f},trim=duration={duration:.3f},"
            f"setpts=PTS-STARTPTS[{label}]"
        )
        labels.append(f"[{label}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[vout]")
    audio_index = len(request.scenes)
    duration = request.duration_ms / 1000
    parts.append(
        f"[{audio_index}:a:0]apad=whole_dur={duration:.3f},"
        f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[aout]"
    )
    return ";".join(parts)


class MediaCompositionService:
    """Compose exact authorized inputs using a fixed, generated FFmpeg graph."""

    _VIDEO_DEMUXERS = {
        "video/mp4": ("mov", "mov,mp4,m4a,3gp,3g2,mj2"),
        "video/webm": ("matroska", "matroska,webm"),
    }

    def __init__(
        self, *, storage_root: Path, asset_ingest: AssetIngest,
        ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", policy: RenderPolicy | None = None,
    ) -> None:
        self._root = Path(storage_root).expanduser().resolve()
        self._ingest = asset_ingest
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._policy = policy or RenderPolicy()

    async def compose(
        self, *, request: CompositionRequest,
        sources: Mapping[UUID, StoredAssetFile], records: Mapping[UUID, AssetRecord],
    ) -> CompositionResult:
        manifest = build_composition_manifest(request, records, sources, self._policy)
        evidence = {item.asset_id: item for item in manifest.inputs}
        try:
            with tempfile.TemporaryDirectory(prefix=f"compose-{request.request_id.hex}-") as directory:
                temporary = Path(directory)
                snapshots: dict[UUID, Path] = {}
                total_bytes = 0
                for position, asset_id in enumerate(request.input_asset_ids):
                    source = sources[asset_id]
                    total_bytes += source.size_bytes
                    if total_bytes > self._policy.max_input_bytes:
                        raise RenderError("INPUT_SIZE_LIMIT", "composition inputs exceed the aggregate byte limit")
                    snapshot = temporary / f"input-{position}"
                    await asyncio.to_thread(
                        _snapshot_asset, source, evidence[asset_id], storage_root=self._root,
                        destination=snapshot, max_bytes=self._policy.max_input_bytes,
                    )
                    snapshots[asset_id] = snapshot
                output = temporary / "output.mp4"
                args = [self._ffmpeg, "-nostdin", "-v", "error", "-xerror", "-max_alloc", "268435456", "-threads", "1"]
                for scene in request.scenes:
                    demuxer, formats = self._VIDEO_DEMUXERS[sources[scene.asset_id].mime_type]
                    args += ["-protocol_whitelist", "file", "-format_whitelist", formats, "-f", demuxer, "-i", str(snapshots[scene.asset_id])]
                args += ["-protocol_whitelist", "file", "-format_whitelist", "wav", "-f", "wav", "-i", str(snapshots[request.narration_asset_id])]
                args += ["-protocol_whitelist", "file", "-format_whitelist", "srt", "-f", "srt", "-i", str(snapshots[request.subtitle_asset_id])]
                subtitle_index = len(request.scenes) + 1
                args += [
                    "-filter_complex", _filter_graph(request, self._policy),
                    "-map", "[vout]", "-map", "[aout]", "-map", f"{subtitle_index}:s:0",
                    "-map_metadata", "-1", "-map_chapters", "-1",
                    "-c:v", self._policy.video_codec, "-preset", self._policy.preset,
                    "-pix_fmt", self._policy.pixel_format, "-c:a", self._policy.audio_codec,
                    "-c:s", "mov_text", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                    "-flags:a", "+bitexact", "-movflags", "+faststart",
                    "-fs", str(self._policy.max_output_bytes), "-threads", "1", "-f", "mp4", str(output),
                ]
                await asyncio.to_thread(
                    _run, args, timeout=self._policy.timeout_seconds,
                    output_limit=self._policy.tool_output_limit,
                )
                output_hash, output_size = await asyncio.to_thread(
                    _inspect_output, output, max_bytes=self._policy.max_output_bytes,
                )
                await asyncio.to_thread(
                    _validate_output_media, output, ffprobe=self._ffprobe,
                    timeout=self._policy.timeout_seconds, output_limit=self._policy.tool_output_limit,
                    policy=self._policy, require_audio=True, require_subtitle=True,
                    expected_duration_seconds=request.duration_ms / 1000,
                )
                await self._ingest.ingest(
                    asset_id=request.output_asset_id, source_path=output, mime_type="video/mp4",
                    brand_id=request.brand_id, content_id=request.content_id,
                    owner_user_id=request.owner_user_id, kind=AssetKind.FINAL_VIDEO,
                    media_metadata={
                        "composition_version": 1,
                        "composition_fingerprint": manifest.fingerprint,
                        "render_version": request.render_version,
                        "storyboard_version": request.storyboard_version,
                        "duration_ms": request.duration_ms,
                        "timeline_start_ms": 0,
                        "scene_asset_ids": [str(item.asset_id) for item in request.scenes],
                        "narration_asset_id": str(request.narration_asset_id),
                        "subtitle_asset_id": str(request.subtitle_asset_id),
                        "subtitles_muxed": True,
                        "target_width": self._policy.target_width,
                        "target_height": self._policy.target_height,
                        "frame_rate": self._policy.frame_rate,
                        "fit_mode": self._policy.fit_mode,
                    },
                )
        except RenderError:
            raise
        except MediaProbeError as exc:
            raise RenderError("FFMPEG_FAILED", "local media composition failed") from exc
        except Exception as exc:
            raise RenderError("COMPOSITION_FAILED", "media composition could not be completed safely") from exc
        return CompositionResult(request.request_id, request.output_asset_id, manifest, output_hash, output_size)
