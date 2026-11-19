"""Typed asset metadata shared by storage and persistence boundaries."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetKind(StrEnum):
    RAW_FLOW_CLIP = "RAW_FLOW_CLIP"
    NARRATION = "NARRATION"
    CAPTION_SRT = "CAPTION_SRT"
    THUMBNAIL = "THUMBNAIL"
    FINAL_VIDEO = "FINAL_VIDEO"
    EXPORT_VARIANT = "EXPORT_VARIANT"
    REFERENCE_IMAGE = "REFERENCE_IMAGE"
    MUSIC_LICENSED = "MUSIC_LICENSED"
    OTHER = "OTHER"


class AssetMetadata(BaseModel):
    """Verified metadata for a single immutable managed object."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    asset_id: UUID
    content_id: UUID
    kind: AssetKind
    storage_uri: str = Field(pattern=r"^managed://assets/[0-9a-f]{32}/payload$")
    sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(gt=0, le=4_000_000_000)
    media_metadata: dict[str, object] = Field(default_factory=dict)
    scene_id: UUID | None = None
    source_job_id: UUID | None = None

    @model_validator(mode="after")
    def source_job_requires_scene(self) -> "AssetMetadata":
        if self.storage_uri != f"managed://assets/{self.asset_id.hex}/payload":
            raise ValueError("managed storage URI must match the asset UUID")
        if self.source_job_id is not None and self.scene_id is None:
            raise ValueError("source generation job requires a scene")
        required_prefix = {
            AssetKind.RAW_FLOW_CLIP: "video/",
            AssetKind.NARRATION: "audio/",
            AssetKind.CAPTION_SRT: "text/",
            AssetKind.THUMBNAIL: "image/",
            AssetKind.FINAL_VIDEO: "video/",
            AssetKind.REFERENCE_IMAGE: "image/",
            AssetKind.MUSIC_LICENSED: "audio/",
        }.get(self.kind)
        if required_prefix is not None and not self.mime_type.startswith(required_prefix):
            raise ValueError("asset kind and MIME type do not match")
        return self
