"""Allowlisted local delivery exports; no upload or publishing behavior."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
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
    RenderInputManifest,
    RenderPolicy,
    _inspect_output,
    _snapshot,
    _validate_output_media,
    _video_filter,
)


class ExportProfileId(StrEnum):
    YOUTUBE_SHORTS_V1 = "YOUTUBE_SHORTS_V1"
    INSTAGRAM_REELS_V1 = "INSTAGRAM_REELS_V1"
    FACEBOOK_REELS_V1 = "FACEBOOK_REELS_V1"


@dataclass(frozen=True, slots=True)
class ExportProfile:
    profile_id: ExportProfileId
    platform: Literal["YOUTUBE", "INSTAGRAM", "FACEBOOK"]
    width: int
    height: int
    frame_rate: int
    fit_mode: Literal["COVER", "CONTAIN"]
    video_bitrate_bps: int
    audio_bitrate_bps: int

    def __post_init__(self) -> None:
        expected_platform = {
            ExportProfileId.YOUTUBE_SHORTS_V1: "YOUTUBE",
            ExportProfileId.INSTAGRAM_REELS_V1: "INSTAGRAM",
            ExportProfileId.FACEBOOK_REELS_V1: "FACEBOOK",
        }.get(self.profile_id)
        if expected_platform != self.platform:
            raise ValueError("export profile platform is invalid")
        RenderPolicy(
            target_width=self.width, target_height=self.height,
            frame_rate=self.frame_rate, fit_mode=self.fit_mode,
        )
        if type(self.video_bitrate_bps) is not int or not 500_000 <= self.video_bitrate_bps <= 50_000_000:
            raise ValueError("export video bitrate is invalid")
        if type(self.audio_bitrate_bps) is not int or not 64_000 <= self.audio_bitrate_bps <= 512_000:
            raise ValueError("export audio bitrate is invalid")

    def render_policy(self, base: RenderPolicy) -> RenderPolicy:
        return RenderPolicy(
            timeout_seconds=base.timeout_seconds,
            max_input_bytes=base.max_input_bytes,
            max_output_bytes=base.max_output_bytes,
            tool_output_limit=base.tool_output_limit,
            target_width=self.width,
            target_height=self.height,
            frame_rate=self.frame_rate,
            fit_mode=self.fit_mode,
        )


_EXPORT_PROFILES: dict[ExportProfileId, ExportProfile] = {
    ExportProfileId.YOUTUBE_SHORTS_V1: ExportProfile(
        ExportProfileId.YOUTUBE_SHORTS_V1, "YOUTUBE", 1080, 1920, 30, "COVER", 8_000_000, 192_000,
    ),
    ExportProfileId.INSTAGRAM_REELS_V1: ExportProfile(
        ExportProfileId.INSTAGRAM_REELS_V1, "INSTAGRAM", 1080, 1920, 30, "COVER", 6_000_000, 128_000,
    ),
    ExportProfileId.FACEBOOK_REELS_V1: ExportProfile(
        ExportProfileId.FACEBOOK_REELS_V1, "FACEBOOK", 1080, 1920, 30, "COVER", 6_000_000, 128_000,
    ),
}
EXPORT_PROFILES: Mapping[ExportProfileId, ExportProfile] = MappingProxyType(_EXPORT_PROFILES)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    request_id: UUID
    brand_id: UUID
    content_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=200)
    source_asset_id: UUID
    output_asset_id: UUID
    profile_id: ExportProfileId

    @field_validator("owner_user_id")
    @classmethod
    def owner_is_safe(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("owner identity is invalid")
        return value

    @model_validator(mode="after")
    def output_is_distinct(self) -> "ExportRequest":
        if self.output_asset_id == self.source_asset_id:
            raise ValueError("export output must use a new asset identity")
        return self


class ExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1] = 1
    operation: Literal["PLATFORM_EXPORT"] = "PLATFORM_EXPORT"
    request_id: UUID
    content_id: UUID
    source_asset_id: UUID
    source_sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_asset_id: UUID
    profile_id: ExportProfileId
    platform: Literal["YOUTUBE", "INSTAGRAM", "FACEBOOK"]
    width: int
    height: int
    frame_rate: int
    fit_mode: Literal["COVER", "CONTAIN"]
    video_codec: Literal["h264"] = "h264"
    audio_codec: Literal["aac"] = "aac"
    subtitle_codec: Literal["mov_text"] = "mov_text"
    video_bitrate_bps: int
    audio_bitrate_bps: int
    duration_ms: int = Field(ge=1, le=180_000)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    def inputs_manifest(self) -> dict[str, list[str]]:
        return {"asset_ids": [str(self.source_asset_id)]}

    def command_manifest(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_id", "source_asset_id", "output_asset_id"})


@dataclass(frozen=True, slots=True)
class ExportResult:
    request_id: UUID
    output_asset_id: UUID
    manifest: ExportManifest
    output_sha256_hex: str
    output_size_bytes: int


def build_export_manifest(
    request: ExportRequest, source: StoredAssetFile, source_record: AssetRecord,
) -> ExportManifest:
    if not isinstance(request, ExportRequest) or not isinstance(source, StoredAssetFile) or not isinstance(source_record, AssetRecord):
        raise ValueError("export request and owner-scoped source are required")
    profile = EXPORT_PROFILES[request.profile_id]
    metadata = source_record.metadata
    media = metadata.media_metadata
    if (metadata.asset_id != request.source_asset_id or source.asset_id != request.source_asset_id
            or metadata.content_id != request.content_id or metadata.scene_id is not None
            or metadata.kind != AssetKind.FINAL_VIDEO or metadata.mime_type != "video/mp4"
            or metadata.storage_uri != source.storage_uri or metadata.sha256_hex != source.sha256_hex
            or metadata.size_bytes != source.size_bytes or source.mime_type != "video/mp4"
            or media.get("composition_version") != 1
            or not isinstance(media.get("composition_fingerprint"), str)
            or re.fullmatch(r"[0-9a-f]{64}", media["composition_fingerprint"]) is None
            or media.get("timeline_start_ms") != 0
            or type(media.get("duration_ms")) is not int
            or not 1 <= media["duration_ms"] <= 180_000
            or media.get("subtitles_muxed") is not True):
        raise RenderError("SOURCE_LINEAGE_MISMATCH", "composed source does not match the authorized export lineage")
    base: dict[str, object] = {
        "schema_version": 1,
        "operation": "PLATFORM_EXPORT",
        "request_id": request.request_id,
        "content_id": request.content_id,
        "source_asset_id": request.source_asset_id,
        "source_sha256_hex": metadata.sha256_hex,
        "output_asset_id": request.output_asset_id,
        "profile_id": request.profile_id,
        "platform": profile.platform,
        "width": profile.width,
        "height": profile.height,
        "frame_rate": profile.frame_rate,
        "fit_mode": profile.fit_mode,
        "video_codec": "h264",
        "audio_codec": "aac",
        "subtitle_codec": "mov_text",
        "video_bitrate_bps": profile.video_bitrate_bps,
        "audio_bitrate_bps": profile.audio_bitrate_bps,
        "duration_ms": media["duration_ms"],
    }
    canonical = {
        **base,
        "request_id": request.request_id.hex,
        "content_id": request.content_id.hex,
        "source_asset_id": request.source_asset_id.hex,
        "output_asset_id": request.output_asset_id.hex,
        "profile_id": request.profile_id.value,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return ExportManifest.model_validate({**base, "fingerprint": hashlib.sha256(encoded).hexdigest()})


class PlatformExportService:
    """Create verified local variants; this service cannot upload or publish."""

    def __init__(
        self, *, storage_root: Path, asset_ingest: AssetIngest,
        ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", base_policy: RenderPolicy | None = None,
    ) -> None:
        self._root = Path(storage_root).expanduser().resolve()
        self._ingest = asset_ingest
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._base = base_policy or RenderPolicy()

    async def export(
        self, *, request: ExportRequest, source: StoredAssetFile, source_record: AssetRecord,
    ) -> ExportResult:
        manifest = build_export_manifest(request, source, source_record)
        profile = EXPORT_PROFILES[request.profile_id]
        policy = profile.render_policy(self._base)
        evidence = RenderInputManifest(
            position=0, asset_id=source.asset_id,
            sha256_hex=source.sha256_hex, mime_type=source.mime_type,
            size_bytes=source.size_bytes,
        )
        try:
            with tempfile.TemporaryDirectory(prefix=f"export-{request.request_id.hex}-") as directory:
                temporary = Path(directory)
                snapshot = temporary / "source"
                output = temporary / "output.mp4"
                await asyncio.to_thread(
                    _snapshot, source, evidence, storage_root=self._root,
                    destination=snapshot, max_bytes=policy.max_input_bytes,
                )
                await asyncio.to_thread(
                    _run,
                    [self._ffmpeg, "-nostdin", "-v", "error", "-xerror", "-max_alloc", "268435456", "-threads", "1",
                     "-protocol_whitelist", "file", "-format_whitelist", "mov,mp4,m4a,3gp,3g2,mj2", "-f", "mov",
                     "-i", str(snapshot), "-map", "0:v:0", "-map", "0:a:0", "-map", "0:s:0",
                     "-map_metadata", "-1", "-map_chapters", "-1", "-vf", _video_filter(policy),
                     "-c:v", "libx264", "-preset", policy.preset, "-pix_fmt", policy.pixel_format,
                     "-b:v", str(profile.video_bitrate_bps), "-maxrate", str(profile.video_bitrate_bps),
                     "-bufsize", str(profile.video_bitrate_bps * 2), "-c:a", "aac", "-b:a", str(profile.audio_bitrate_bps),
                     "-c:s", "mov_text", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
                     "-movflags", "+faststart", "-fs", str(policy.max_output_bytes), "-threads", "1", "-f", "mp4", str(output)],
                    timeout=policy.timeout_seconds, output_limit=policy.tool_output_limit,
                )
                output_hash, output_size = await asyncio.to_thread(
                    _inspect_output, output, max_bytes=policy.max_output_bytes,
                )
                await asyncio.to_thread(
                    _validate_output_media, output, ffprobe=self._ffprobe,
                    timeout=policy.timeout_seconds, output_limit=policy.tool_output_limit,
                    policy=policy, require_audio=True, require_subtitle=True,
                    expected_duration_seconds=manifest.duration_ms / 1000,
                )
                await self._ingest.ingest(
                    asset_id=request.output_asset_id, source_path=output, mime_type="video/mp4",
                    brand_id=request.brand_id, content_id=request.content_id,
                    owner_user_id=request.owner_user_id, kind=AssetKind.EXPORT_VARIANT,
                    media_metadata={
                        "export_version": 1,
                        "export_fingerprint": manifest.fingerprint,
                        "export_profile_id": manifest.profile_id.value,
                        "platform": manifest.platform,
                        "source_asset_id": str(request.source_asset_id),
                        "source_sha256": manifest.source_sha256_hex,
                        "duration_ms": manifest.duration_ms,
                        "timeline_start_ms": 0,
                        "width": manifest.width,
                        "height": manifest.height,
                        "frame_rate": manifest.frame_rate,
                        "subtitles_muxed": True,
                        "publishing_performed": False,
                    },
                )
        except RenderError:
            raise
        except MediaProbeError as exc:
            raise RenderError("EXPORT_TOOL_FAILED", "local platform export failed") from exc
        except Exception as exc:
            raise RenderError("EXPORT_FAILED", "platform export could not be completed safely") from exc
        return ExportResult(request.request_id, request.output_asset_id, manifest, output_hash, output_size)
