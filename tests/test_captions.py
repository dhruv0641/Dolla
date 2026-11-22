from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.audio.captions import (
    CaptionAlignmentError,
    CaptionAlignmentService,
    CaptionPolicy,
    CaptionRequest,
    build_caption_cues,
    render_srt,
)
from flowx_os.db.assets import AssetRecord
from flowx_os.db.storyboards import StoryboardVersionRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata
from flowx_os.domain.storyboard import StoryboardTimeline


REQUEST_ID = UUID("8e20df55-a3e1-44d4-8c14-6bb084c9b6b6")
OUTPUT_ID = UUID("eff3f944-86d9-4c70-a028-12cf1d02e4a2")
AUDIO_ID = UUID("3bf4e583-9e90-42ea-8d3c-48351e6bef61")
CONTENT_ID = UUID("a002ec6e-8862-4c3a-a35e-b837a0af3e46")
BRAND_ID = UUID("05a4ec02-6728-48af-bc2d-4e70ab3dbc58")
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def timeline():
    return StoryboardTimeline.model_validate({
        "title": "Caption test",
        "scenes": [
            {"scene_number": 1, "start_ms": 0, "end_ms": 3000, "beat": "Open",
             "narration_text": "Hello & welcome to the garden.", "visual_prompt": "Garden"},
            {"scene_number": 2, "start_ms": 3000, "end_ms": 7000, "beat": "Explain",
             "narration_text": "Fresh herbs grow in small spaces.", "visual_prompt": "Herbs"},
        ],
    })


def storyboard_record(**updates):
    values = {
        "content_id": CONTENT_ID, "version": 3, "title": "Caption test",
        "total_duration_ms": 7000, "storyboard": timeline(), "created_at": NOW,
    }
    values.update(updates)
    return StoryboardVersionRecord(**values)


def audio_record(**metadata_updates):
    media = {
        "timeline_start_ms": 0, "duration_ms": 7000,
        "normalization_version": 1,
        "normalization_fingerprint": "a" * 64,
    }
    media.update(metadata_updates)
    metadata = AssetMetadata(
        asset_id=AUDIO_ID, content_id=CONTENT_ID, kind=AssetKind.NARRATION,
        storage_uri=f"managed://assets/{AUDIO_ID.hex}/payload",
        sha256_hex="b" * 64, mime_type="audio/wav", size_bytes=1000,
        media_metadata=media,
    )
    return AssetRecord(metadata, NOW)


def request(**updates):
    values = {
        "request_id": REQUEST_ID, "output_asset_id": OUTPUT_ID,
        "normalized_audio_asset_id": AUDIO_ID, "brand_id": BRAND_ID,
        "content_id": CONTENT_ID, "owner_user_id": "owner-1", "storyboard_version": 3,
    }
    values.update(updates)
    return CaptionRequest.model_validate(values)


class RecordingIngest:
    def __init__(self):
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        self.payload = Path(kwargs["source_path"]).read_bytes()


class CaptionTests(unittest.IsolatedAsyncioTestCase):
    def test_cues_preserve_narration_scene_windows_and_plain_srt(self):
        cues = build_caption_cues(timeline(), CaptionPolicy(max_characters_per_line=18))
        self.assertEqual(cues[0].start_ms, 0)
        self.assertEqual(cues[-1].end_ms, 7000)
        self.assertTrue(all(cue.end_ms <= (3000 if cue.scene_number == 1 else 7000) for cue in cues))
        self.assertEqual(
            " ".join(cue.source_text for cue in cues),
            "Hello & welcome to the garden. Fresh herbs grow in small spaces.",
        )
        payload = render_srt(cues).decode("utf-8")
        self.assertIn("00:00:00,000 -->", payload)
        self.assertIn("Hello &amp; welcome", payload)
        self.assertNotIn("<script", payload)

    def test_density_long_tokens_and_identity_rebinding_fail_closed(self):
        dense = StoryboardTimeline.model_validate({
            "title": "Dense", "scenes": [{
                "scene_number": 1, "start_ms": 0, "end_ms": 500,
                "beat": "Fast", "narration_text": "too many caption words here",
                "visual_prompt": "Words",
            }],
        })
        with self.assertRaises(CaptionAlignmentError) as caught:
            build_caption_cues(dense, CaptionPolicy(max_characters_per_line=12, max_lines_per_cue=1))
        self.assertEqual(caught.exception.code, "CAPTION_DENSITY_EXCEEDED")

        long_token = StoryboardTimeline.model_validate({
            "title": "Token", "scenes": [{
                "scene_number": 1, "start_ms": 0, "end_ms": 2000,
                "beat": "Token", "narration_text": "x" * 43, "visual_prompt": "Token",
            }],
        })
        with self.assertRaises(CaptionAlignmentError) as caught:
            build_caption_cues(long_token)
        self.assertEqual(caught.exception.code, "CAPTION_TOKEN_TOO_LONG")

        with self.assertRaises(ValidationError):
            request(output_asset_id=AUDIO_ID)

    async def test_service_binds_storyboard_and_normalized_audio_then_ingests_srt(self):
        ingest = RecordingIngest()
        result = await CaptionAlignmentService(asset_ingest=ingest).create(
            request=request(), storyboard_record=storyboard_record(),
            normalized_audio_record=audio_record(),
        )
        self.assertEqual((result.start_ms, result.end_ms), (0, 7000))
        self.assertTrue(result.estimated_alignment)
        self.assertTrue(ingest.payload.startswith(b"1\n00:00:00,000 -->"))
        self.assertEqual(ingest.calls[0]["kind"], AssetKind.CAPTION_SRT)
        evidence = ingest.calls[0]["media_metadata"]
        self.assertEqual(evidence["alignment_method"], "STORYBOARD_SCENE_ESTIMATE")
        self.assertFalse(evidence["word_level_alignment_verified"])
        self.assertEqual(evidence["storyboard_version"], 3)

    async def test_storyboard_and_audio_lineage_mismatches_do_not_write(self):
        ingest = RecordingIngest()
        service = CaptionAlignmentService(asset_ingest=ingest)
        wrong_storyboard = storyboard_record(content_id=UUID("165ff60f-fcbd-4923-b6de-fc6c9f7ca91b"))
        with self.assertRaises(CaptionAlignmentError) as caught:
            await service.create(
                request=request(), storyboard_record=wrong_storyboard,
                normalized_audio_record=audio_record(),
            )
        self.assertEqual(caught.exception.code, "STORYBOARD_LINEAGE_MISMATCH")

        with self.assertRaises(CaptionAlignmentError) as caught:
            await service.create(
                request=request(), storyboard_record=storyboard_record(),
                normalized_audio_record=audio_record(duration_ms=6999),
            )
        self.assertEqual(caught.exception.code, "AUDIO_LINEAGE_MISMATCH")
        self.assertEqual(ingest.calls, [])


if __name__ == "__main__":
    unittest.main()
