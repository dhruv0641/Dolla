"""Deterministic scene-bounded caption cues and SRT asset generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.audio.synthesis import AssetIngest
from flowx_os.db.assets import AssetRecord
from flowx_os.db.storyboards import StoryboardVersionRecord
from flowx_os.domain.assets import AssetKind
from flowx_os.domain.storyboard import StoryboardTimeline


class CaptionAlignmentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CaptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: UUID
    output_asset_id: UUID
    normalized_audio_asset_id: UUID
    brand_id: UUID
    content_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=200)
    storyboard_version: int = Field(ge=1, le=100_000)

    @field_validator("owner_user_id")
    @classmethod
    def owner_is_safe(cls, value: str) -> str:
        value = value.strip()
        if not value or any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("owner identity is invalid")
        return value

    @model_validator(mode="after")
    def asset_ids_are_distinct(self) -> "CaptionRequest":
        if self.output_asset_id == self.normalized_audio_asset_id:
            raise ValueError("caption output must use a distinct asset identity")
        return self


@dataclass(frozen=True, slots=True)
class CaptionPolicy:
    max_characters_per_line: int = 42
    max_lines_per_cue: int = 2
    minimum_cue_ms: int = 800
    maximum_cues: int = 500
    maximum_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if type(self.max_characters_per_line) is not int or not 12 <= self.max_characters_per_line <= 120:
            raise ValueError("caption line limit is invalid")
        if type(self.max_lines_per_cue) is not int or not 1 <= self.max_lines_per_cue <= 3:
            raise ValueError("caption line count is invalid")
        if type(self.minimum_cue_ms) is not int or not 100 <= self.minimum_cue_ms <= 10_000:
            raise ValueError("caption minimum duration is invalid")
        if type(self.maximum_cues) is not int or not 1 <= self.maximum_cues <= 5_000:
            raise ValueError("caption cue limit is invalid")
        if type(self.maximum_output_bytes) is not int or not 1_024 <= self.maximum_output_bytes <= 10_000_000:
            raise ValueError("caption output limit is invalid")


@dataclass(frozen=True, slots=True)
class CaptionCue:
    index: int
    scene_number: int
    start_ms: int
    end_ms: int
    source_text: str
    display_lines: tuple[str, ...]

    def __post_init__(self) -> None:
        if (type(self.index) is not int or self.index < 1
                or type(self.scene_number) is not int or self.scene_number < 1
                or type(self.start_ms) is not int or type(self.end_ms) is not int
                or not 0 <= self.start_ms < self.end_ms
                or not self.source_text or not self.display_lines):
            raise ValueError("caption cue is invalid")
        if " ".join(self.source_text.split()) != " ".join(" ".join(self.display_lines).split()):
            raise ValueError("caption display text must preserve source text")


@dataclass(frozen=True, slots=True)
class CaptionResult:
    request_id: UUID
    output_asset_id: UUID
    caption_fingerprint: str
    cue_count: int
    start_ms: int
    end_ms: int
    estimated_alignment: bool = True


def _normalized_text(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    bidi_controls = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}
    if any(unicodedata.category(character) == "Cc" or unicodedata.bidirectional(character) in bidi_controls
           for character in normalized):
        raise CaptionAlignmentError("NARRATION_TEXT_INVALID", "storyboard narration contains control characters")
    return normalized


def _wrap_words(text: str, policy: CaptionPolicy) -> list[tuple[str, tuple[str, ...]]]:
    words = text.split(" ")
    if any(len(word) > policy.max_characters_per_line for word in words):
        raise CaptionAlignmentError("CAPTION_TOKEN_TOO_LONG", "narration contains a word longer than the caption line limit")
    blocks: list[tuple[str, tuple[str, ...]]] = []
    lines: list[str] = []
    current_words: list[str] = []
    block_words: list[str] = []
    for word in words:
        candidate = " ".join([*current_words, word])
        if len(candidate) <= policy.max_characters_per_line:
            current_words.append(word)
            block_words.append(word)
            continue
        lines.append(" ".join(current_words))
        if len(lines) == policy.max_lines_per_cue:
            blocks.append((" ".join(block_words), tuple(lines)))
            lines, block_words = [], []
        current_words = [word]
        block_words.append(word)
    if current_words:
        lines.append(" ".join(current_words))
    if block_words:
        blocks.append((" ".join(block_words), tuple(lines)))
    return blocks


def _allocate(scene_start: int, scene_end: int, blocks: list[tuple[str, tuple[str, ...]]],
              policy: CaptionPolicy, first_index: int, scene_number: int) -> list[CaptionCue]:
    duration = scene_end - scene_start
    count = len(blocks)
    if count == 0:
        return []
    required = count * policy.minimum_cue_ms
    if required > duration:
        raise CaptionAlignmentError("CAPTION_DENSITY_EXCEEDED", "scene narration cannot fit the available caption window")
    weights = [max(1, len(source.replace(" ", ""))) for source, _ in blocks]
    weight_total = sum(weights)
    extra = duration - required
    durations = [policy.minimum_cue_ms + extra * weight // weight_total for weight in weights]
    durations[-1] += duration - sum(durations)
    cues: list[CaptionCue] = []
    cursor = scene_start
    for offset, ((source, lines), cue_duration) in enumerate(zip(blocks, durations)):
        end = cursor + cue_duration
        cues.append(CaptionCue(first_index + offset, scene_number, cursor, end, source, lines))
        cursor = end
    if cursor != scene_end:
        raise CaptionAlignmentError("CAPTION_TIMELINE_INVALID", "caption allocation does not cover its scene")
    return cues


def build_caption_cues(timeline: StoryboardTimeline, policy: CaptionPolicy | None = None) -> tuple[CaptionCue, ...]:
    if not isinstance(timeline, StoryboardTimeline):
        raise ValueError("storyboard timeline is required")
    selected = policy or CaptionPolicy()
    cues: list[CaptionCue] = []
    expected_parts: list[str] = []
    for scene in timeline.scenes:
        text = _normalized_text(scene.narration_text)
        if not text:
            continue
        expected_parts.append(text)
        blocks = _wrap_words(text, selected)
        cues.extend(_allocate(
            scene.start_ms, scene.end_ms, blocks, selected,
            len(cues) + 1, scene.scene_number,
        ))
        if len(cues) > selected.maximum_cues:
            raise CaptionAlignmentError("CAPTION_CUE_LIMIT", "caption cue count exceeds the configured limit")
    if not cues:
        raise CaptionAlignmentError("NARRATION_EMPTY", "storyboard contains no narration to caption")
    if _normalized_text(" ".join(cue.source_text for cue in cues)) != _normalized_text(" ".join(expected_parts)):
        raise CaptionAlignmentError("CAPTION_TEXT_MISMATCH", "caption text does not preserve storyboard narration")
    return tuple(cues)


def _timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(cues: tuple[CaptionCue, ...], *, maximum_bytes: int = 1_000_000) -> bytes:
    if (not isinstance(cues, tuple) or not cues
            or type(maximum_bytes) is not int or not 1_024 <= maximum_bytes <= 10_000_000):
        raise ValueError("caption cues and output limit are required")
    blocks: list[str] = []
    previous_end = -1
    for expected_index, cue in enumerate(cues, 1):
        if not isinstance(cue, CaptionCue) or cue.index != expected_index or cue.start_ms < previous_end:
            raise CaptionAlignmentError("CAPTION_ORDER_INVALID", "caption cues are not ordered")
        escaped = [html.escape(line, quote=False) for line in cue.display_lines]
        display = "\n".join(escaped)
        blocks.append(
            f"{cue.index}\n{_timestamp(cue.start_ms)} --> {_timestamp(cue.end_ms)}\n"
            f"{display}\n"
        )
        previous_end = cue.end_ms
    payload = ("\n".join(blocks) + "\n").encode("utf-8")
    if len(payload) > maximum_bytes or b"\x00" in payload:
        raise CaptionAlignmentError("CAPTION_OUTPUT_LIMIT", "caption output exceeds the configured limit")
    return payload


def caption_fingerprint(request: CaptionRequest, storyboard_record: StoryboardVersionRecord,
                        audio_record: AssetRecord,
                        policy: CaptionPolicy) -> str:
    payload = {
        "schema": 1,
        "request_id": request.request_id.hex,
        "output_asset_id": request.output_asset_id.hex,
        "audio_asset_id": request.normalized_audio_asset_id.hex,
        "audio_sha256": audio_record.metadata.sha256_hex,
        "brand_id": request.brand_id.hex,
        "content_id": request.content_id.hex,
        "storyboard_version": request.storyboard_version,
        "timeline": storyboard_record.storyboard.model_dump(mode="json"),
        "policy": {
            "max_characters_per_line": policy.max_characters_per_line,
            "max_lines_per_cue": policy.max_lines_per_cue,
            "minimum_cue_ms": policy.minimum_cue_ms,
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CaptionAlignmentService:
    """Create one deterministic SRT asset from approved storyboard narration."""

    def __init__(self, *, asset_ingest: AssetIngest,
                 policy: CaptionPolicy | None = None) -> None:
        self._ingest = asset_ingest
        self._policy = policy or CaptionPolicy()

    async def create(self, *, request: CaptionRequest,
                     storyboard_record: StoryboardVersionRecord,
                     normalized_audio_record: AssetRecord) -> CaptionResult:
        if (not isinstance(request, CaptionRequest)
                or not isinstance(storyboard_record, StoryboardVersionRecord)
                or not isinstance(normalized_audio_record, AssetRecord)):
            raise ValueError("caption request and owner-scoped storyboard/audio records are required")
        if (storyboard_record.content_id != request.content_id
                or storyboard_record.version != request.storyboard_version
                or storyboard_record.total_duration_ms != storyboard_record.storyboard.total_duration_ms):
            raise CaptionAlignmentError(
                "STORYBOARD_LINEAGE_MISMATCH", "storyboard version does not match the caption request",
            )
        timeline = storyboard_record.storyboard
        metadata = normalized_audio_record.metadata
        media = metadata.media_metadata
        if (metadata.asset_id != request.normalized_audio_asset_id
                or metadata.content_id != request.content_id
                or metadata.scene_id is not None
                or metadata.kind != AssetKind.NARRATION
                or not metadata.mime_type.startswith("audio/")
                or type(media.get("timeline_start_ms")) is not int
                or media.get("timeline_start_ms") != 0
                or type(media.get("duration_ms")) is not int
                or media.get("duration_ms") != timeline.total_duration_ms
                or media.get("normalization_version") != 1
                or not isinstance(media.get("normalization_fingerprint"), str)
                or re.fullmatch(r"[0-9a-f]{64}", media["normalization_fingerprint"]) is None):
            raise CaptionAlignmentError(
                "AUDIO_LINEAGE_MISMATCH",
                "normalized narration does not match the caption timeline",
            )
        cues = build_caption_cues(timeline, self._policy)
        payload = render_srt(cues, maximum_bytes=self._policy.maximum_output_bytes)
        fingerprint = caption_fingerprint(request, storyboard_record, normalized_audio_record, self._policy)
        try:
            with tempfile.TemporaryDirectory(prefix=f"captions-{request.request_id.hex}-") as directory:
                output = Path(directory) / "captions.srt"
                with output.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                await self._ingest.ingest(
                    asset_id=request.output_asset_id, source_path=output, mime_type="text/plain",
                    brand_id=request.brand_id, content_id=request.content_id,
                    owner_user_id=request.owner_user_id, kind=AssetKind.CAPTION_SRT,
                    media_metadata={
                        "caption_version": 1,
                        "caption_fingerprint": fingerprint,
                        "storyboard_version": request.storyboard_version,
                        "normalized_audio_asset_id": metadata.asset_id.hex,
                        "timeline_start_ms": 0,
                        "timeline_end_ms": timeline.total_duration_ms,
                        "cue_count": len(cues),
                        "alignment_method": "STORYBOARD_SCENE_ESTIMATE",
                        "word_level_alignment_verified": False,
                    },
                )
        except CaptionAlignmentError:
            raise
        except Exception as exc:
            raise CaptionAlignmentError("CAPTION_INGEST_FAILED", "caption asset could not be stored safely") from exc
        return CaptionResult(
            request.request_id, request.output_asset_id, fingerprint, len(cues),
            cues[0].start_ms, cues[-1].end_ms,
        )
