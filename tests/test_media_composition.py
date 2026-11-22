import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.assets.storage import ManagedAssetStore
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata
from flowx_os.rendering import (
    CompositionRequest,
    MediaCompositionService,
    RenderError,
    RenderPolicy,
    SceneCompositionInput,
    build_composition_manifest,
)


REQUEST_ID = UUID("fabf036e-874c-44cd-996d-c1cd94a48c76")
BRAND_ID = UUID("79312d0e-6a03-4c1d-b850-22ea214d8a2e")
CONTENT_ID = UUID("1da8cf70-3f38-40c6-9ef2-0a26c9750ef1")
SCENE_1 = UUID("591cb283-7d84-4534-b117-c9f0a4e07bb2")
SCENE_2 = UUID("6aa46cbd-e9cc-403b-b9e2-c5315c4e22f2")
VIDEO_1 = UUID("93b68f29-4b28-4a78-bb27-0c9db24fb62a")
VIDEO_2 = UUID("1b34d767-a92f-4072-9b98-f6cd88221528")
AUDIO_ID = UUID("969090ee-2c06-434b-aa44-80e53ca7edfb")
SUBTITLE_ID = UUID("30a3b8d8-47bb-4df6-9ac4-afb389eaf015")
OUTPUT_ID = UUID("9d421854-feef-4b77-ab7f-ab8335db2134")
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def request(**updates):
    values = {
        "request_id": REQUEST_ID, "brand_id": BRAND_ID, "content_id": CONTENT_ID,
        "owner_user_id": "owner-1", "render_version": 1, "storyboard_version": 3,
        "scenes": (
            SceneCompositionInput(scene_number=1, scene_id=SCENE_1, asset_id=VIDEO_1, start_ms=0, end_ms=200),
            SceneCompositionInput(scene_number=2, scene_id=SCENE_2, asset_id=VIDEO_2, start_ms=200, end_ms=400),
        ),
        "narration_asset_id": AUDIO_ID, "subtitle_asset_id": SUBTITLE_ID,
        "output_asset_id": OUTPUT_ID,
    }
    values.update(updates)
    return CompositionRequest.model_validate(values)


def record(source, kind, *, scene_id=None, media=None, content_id=CONTENT_ID):
    return AssetRecord(AssetMetadata(
        asset_id=source.asset_id, content_id=content_id, scene_id=scene_id, kind=kind,
        storage_uri=source.storage_uri, sha256_hex=source.sha256_hex,
        mime_type=source.mime_type, size_bytes=source.size_bytes,
        media_metadata=media or {},
    ), NOW)


def metadata(sources):
    records = {
        VIDEO_1: record(sources[VIDEO_1], AssetKind.RAW_FLOW_CLIP, scene_id=SCENE_1),
        VIDEO_2: record(sources[VIDEO_2], AssetKind.RAW_FLOW_CLIP, scene_id=SCENE_2),
        AUDIO_ID: record(sources[AUDIO_ID], AssetKind.NARRATION, media={
            "normalization_version": 1, "normalization_fingerprint": "a" * 64,
            "timeline_start_ms": 0, "duration_ms": 400,
        }),
        SUBTITLE_ID: record(sources[SUBTITLE_ID], AssetKind.CAPTION_SRT, media={
            "caption_version": 1, "caption_fingerprint": "b" * 64,
            "storyboard_version": 3, "normalized_audio_asset_id": AUDIO_ID.hex,
            "timeline_start_ms": 0, "timeline_end_ms": 400,
        }),
    }
    return records


class RecordingIngest:
    def __init__(self):
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        self.payload = Path(kwargs["source_path"]).read_bytes()


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    def test_request_rejects_gaps_reordering_and_reused_assets(self):
        with self.assertRaises(ValidationError):
            request(scenes=(
                SceneCompositionInput(scene_number=1, scene_id=SCENE_1, asset_id=VIDEO_1, start_ms=0, end_ms=150),
                SceneCompositionInput(scene_number=2, scene_id=SCENE_2, asset_id=VIDEO_2, start_ms=200, end_ms=400),
            ))
        with self.assertRaises(ValidationError):
            request(scenes=(
                SceneCompositionInput(scene_number=2, scene_id=SCENE_1, asset_id=VIDEO_1, start_ms=0, end_ms=200),
            ))
        with self.assertRaises(ValidationError):
            request(narration_asset_id=VIDEO_1)

    def test_manifest_is_ordered_path_free_and_binds_all_lineage(self):
        sources = {}
        for asset_id, mime in ((VIDEO_1, "video/mp4"), (VIDEO_2, "video/mp4"), (AUDIO_ID, "audio/wav"), (SUBTITLE_ID, "text/plain")):
            sources[asset_id] = type("Source", (), {
                "asset_id": asset_id, "path": Path("unused"),
                "storage_uri": f"managed://assets/{asset_id.hex}/payload",
                "sha256_hex": asset_id.hex * 2, "mime_type": mime, "size_bytes": 120,
            })()
        policy = RenderPolicy(target_width=160, target_height=90, frame_rate=10)
        first = build_composition_manifest(request(), metadata(sources), sources, policy)
        second = build_composition_manifest(request(), metadata(sources), sources, policy)
        self.assertEqual(first, second)
        self.assertEqual(first.inputs_manifest()["asset_ids"], [str(item) for item in request().input_asset_ids])
        self.assertEqual([item.role for item in first.inputs], ["SCENE", "SCENE", "NARRATION", "SUBTITLE"])
        command = first.command_manifest()
        self.assertEqual(command["input_roles"], ["SCENE", "SCENE", "NARRATION", "SUBTITLE"])
        self.assertEqual(command["scene_timeline"][1]["start_ms"], 200)
        self.assertEqual((command["narration_input_position"], command["subtitle_input_position"]), (2, 3))
        self.assertNotIn("path", str(command).lower())

    def test_manifest_rejects_scene_audio_and_subtitle_lineage_mismatch(self):
        sources = {}
        for asset_id, mime in ((VIDEO_1, "video/mp4"), (VIDEO_2, "video/mp4"), (AUDIO_ID, "audio/wav"), (SUBTITLE_ID, "text/plain")):
            sources[asset_id] = type("Source", (), {
                "asset_id": asset_id, "path": Path("unused"),
                "storage_uri": f"managed://assets/{asset_id.hex}/payload",
                "sha256_hex": asset_id.hex * 2, "mime_type": mime, "size_bytes": 120,
            })()
        policy = RenderPolicy(target_width=160, target_height=90, frame_rate=10)
        records = metadata(sources)
        records[VIDEO_1] = record(sources[VIDEO_1], AssetKind.RAW_FLOW_CLIP, scene_id=SCENE_2)
        with self.assertRaises(RenderError) as caught:
            build_composition_manifest(request(), records, sources, policy)
        self.assertEqual(caught.exception.code, "SCENE_LINEAGE_MISMATCH")
        records = metadata(sources)
        records[AUDIO_ID] = record(sources[AUDIO_ID], AssetKind.NARRATION, media={
            "normalization_version": 1, "normalization_fingerprint": "a" * 64,
            "timeline_start_ms": 1, "duration_ms": 400,
        })
        with self.assertRaises(RenderError) as caught:
            build_composition_manifest(request(), records, sources, policy)
        self.assertEqual(caught.exception.code, "NARRATION_LINEAGE_MISMATCH")
        records = metadata(sources)
        wrong = records[SUBTITLE_ID].metadata.media_metadata | {"storyboard_version": 2}
        records[SUBTITLE_ID] = record(sources[SUBTITLE_ID], AssetKind.CAPTION_SRT, media=wrong)
        with self.assertRaises(RenderError) as caught:
            build_composition_manifest(request(), records, sources, policy)
        self.assertEqual(caught.exception.code, "SUBTITLE_LINEAGE_MISMATCH")
        records = metadata(sources)
        wrong = records[SUBTITLE_ID].metadata.media_metadata | {"caption_fingerprint": "not-a-digest"}
        records[SUBTITLE_ID] = record(sources[SUBTITLE_ID], AssetKind.CAPTION_SRT, media=wrong)
        with self.assertRaises(RenderError) as caught:
            build_composition_manifest(request(), records, sources, policy)
        self.assertEqual(caught.exception.code, "SUBTITLE_LINEAGE_MISMATCH")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    async def test_real_composition_preserves_scene_order_audio_zero_and_subtitle_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ManagedAssetStore(root)
            sources = {}
            for asset_id, color in ((VIDEO_1, "red"), (VIDEO_2, "blue")):
                path = root / f"{asset_id.hex}.mp4"
                subprocess.run([
                    "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=160x90:r=10", "-t", "0.2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-an", str(path),
                ], check=True, timeout=20)
                sources[asset_id] = store.store(asset_id=asset_id, source_path=path, mime_type="video/mp4")
            audio = root / "audio.wav"
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000", "-t", "0.4", "-c:a", "pcm_s16le", str(audio),
            ], check=True, timeout=20)
            sources[AUDIO_ID] = store.store(asset_id=AUDIO_ID, source_path=audio, mime_type="audio/wav")
            captions = root / "captions.srt"
            captions.write_text(
                "1\n00:00:00,000 --> 00:00:00,200\nRed\n\n"
                "2\n00:00:00,200 --> 00:00:00,400\nBlue\n\n", encoding="utf-8",
            )
            sources[SUBTITLE_ID] = store.store(asset_id=SUBTITLE_ID, source_path=captions, mime_type="text/plain")
            ingest = RecordingIngest()
            policy = RenderPolicy(target_width=160, target_height=90, frame_rate=10)
            result = await MediaCompositionService(
                storage_root=root, asset_ingest=ingest, policy=policy,
            ).compose(request=request(), sources=sources, records=metadata(sources))

            output = root / "composed.mp4"
            output.write_bytes(ingest.payload)
            streams = json.loads(subprocess.run([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,start_time",
                "-of", "json", str(output),
            ], check=True, capture_output=True, timeout=20).stdout)
            first = subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-ss", "0.05", "-i", str(output),
                "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ], check=True, capture_output=True, timeout=20).stdout
            second = subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-ss", "0.25", "-i", str(output),
                "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ], check=True, capture_output=True, timeout=20).stdout
            Path(sources[SUBTITLE_ID].path).write_bytes(Path(sources[SUBTITLE_ID].path).read_bytes() + b"tamper")
            rejected = RecordingIngest()
            with self.assertRaises(RenderError) as caught:
                await MediaCompositionService(
                    storage_root=root, asset_ingest=rejected, policy=policy,
                ).compose(request=request(), sources=sources, records=metadata(sources))

        kinds = {item["codec_type"]: item for item in streams["streams"]}
        self.assertEqual(kinds["video"]["codec_name"], "h264")
        self.assertEqual((kinds["video"]["width"], kinds["video"]["height"]), (160, 90))
        self.assertEqual(kinds["video"]["avg_frame_rate"], "10/1")
        self.assertEqual(kinds["audio"]["codec_name"], "aac")
        self.assertAlmostEqual(float(kinds["audio"]["start_time"]), 0, delta=0.05)
        self.assertEqual(kinds["subtitle"]["codec_name"], "mov_text")
        self.assertAlmostEqual(float(streams["format"]["duration"]), 0.4, delta=0.25)
        self.assertGreater(first[0], first[2])
        self.assertGreater(second[2], second[0])
        self.assertEqual(ingest.calls[0]["media_metadata"]["timeline_start_ms"], 0)
        self.assertEqual(result.manifest.inputs_manifest()["asset_ids"], [str(item) for item in request().input_asset_ids])
        self.assertEqual(caught.exception.code, "INPUT_INTEGRITY_MISMATCH")
        self.assertEqual(rejected.calls, [])


if __name__ == "__main__":
    unittest.main()
