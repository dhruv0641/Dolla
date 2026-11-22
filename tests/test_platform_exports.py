import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.assets.storage import ManagedAssetStore, StoredAssetFile
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata
from flowx_os.rendering import (
    EXPORT_PROFILES,
    ExportProfileId,
    ExportRequest,
    PlatformExportService,
    RenderError,
    RenderPolicy,
    build_export_manifest,
)


REQUEST_ID = UUID("fabf036e-874c-44cd-996d-c1cd94a48c76")
BRAND_ID = UUID("79312d0e-6a03-4c1d-b850-22ea214d8a2e")
CONTENT_ID = UUID("1da8cf70-3f38-40c6-9ef2-0a26c9750ef1")
SOURCE_ID = UUID("9d421854-feef-4b77-ab7f-ab8335db2134")
OUTPUT_ID = UUID("28fcb18d-3e3a-4ec3-8be1-f16957833363")
INSTAGRAM_OUTPUT_ID = UUID("700578df-64bd-4d72-aa9a-b83b43e55fa6")
FACEBOOK_OUTPUT_ID = UUID("9ff69963-9f1d-41bf-a6ea-7ee523b59d26")


def request(**updates):
    values = {
        "request_id": REQUEST_ID, "brand_id": BRAND_ID, "content_id": CONTENT_ID,
        "owner_user_id": "owner-1", "source_asset_id": SOURCE_ID,
        "output_asset_id": OUTPUT_ID, "profile_id": ExportProfileId.YOUTUBE_SHORTS_V1,
    }
    values.update(updates)
    return ExportRequest.model_validate(values)


def record(source, **media_updates):
    media = {
        "composition_version": 1, "composition_fingerprint": "c" * 64,
        "timeline_start_ms": 0, "duration_ms": 400, "subtitles_muxed": True,
    }
    media.update(media_updates)
    return AssetRecord(AssetMetadata(
        asset_id=source.asset_id, content_id=CONTENT_ID, kind=AssetKind.FINAL_VIDEO,
        storage_uri=source.storage_uri, sha256_hex=source.sha256_hex,
        mime_type=source.mime_type, size_bytes=source.size_bytes, media_metadata=media,
    ), datetime(2026, 11, 22, tzinfo=timezone.utc))


def fake_source():
    return StoredAssetFile(
        asset_id=SOURCE_ID, path=Path("unused"),
        storage_uri=f"managed://assets/{SOURCE_ID.hex}/payload",
        sha256_hex="a" * 64, mime_type="video/mp4", size_bytes=100,
    )


class RecordingIngest:
    def __init__(self):
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        self.payload = Path(kwargs["source_path"]).read_bytes()


class PlatformExportTests(unittest.IsolatedAsyncioTestCase):
    def test_profiles_are_allowlisted_and_requests_reject_rebinding(self):
        self.assertEqual(set(EXPORT_PROFILES), set(ExportProfileId))
        self.assertEqual({profile.platform for profile in EXPORT_PROFILES.values()}, {"YOUTUBE", "INSTAGRAM", "FACEBOOK"})
        self.assertTrue(all((profile.width, profile.height, profile.frame_rate) == (1080, 1920, 30)
                            for profile in EXPORT_PROFILES.values()))
        with self.assertRaises(TypeError):
            EXPORT_PROFILES[ExportProfileId.YOUTUBE_SHORTS_V1] = EXPORT_PROFILES[ExportProfileId.YOUTUBE_SHORTS_V1]  # type: ignore[index]
        with self.assertRaises(ValidationError):
            request(profile_id="TIKTOK")
        with self.assertRaises(ValidationError):
            request(output_asset_id=SOURCE_ID)

    def test_manifest_is_stable_path_free_and_profile_specific(self):
        source = fake_source()
        youtube = build_export_manifest(request(), source, record(source))
        instagram = build_export_manifest(
            request(profile_id=ExportProfileId.INSTAGRAM_REELS_V1), source, record(source),
        )
        self.assertEqual(youtube, build_export_manifest(request(), source, record(source)))
        self.assertNotEqual(youtube.fingerprint, instagram.fingerprint)
        self.assertEqual(youtube.inputs_manifest(), {"asset_ids": [str(SOURCE_ID)]})
        self.assertNotIn("path", str(youtube.command_manifest()).lower())
        self.assertEqual(youtube.command_manifest()["source_sha256_hex"], "a" * 64)
        self.assertEqual(youtube.platform, "YOUTUBE")
        self.assertGreater(youtube.video_bitrate_bps, instagram.video_bitrate_bps)

    def test_manifest_rejects_uncomposed_or_unverified_source(self):
        source = fake_source()
        for updates in (
            {"composition_version": 0},
            {"composition_fingerprint": "bad"},
            {"timeline_start_ms": 1},
            {"subtitles_muxed": False},
        ):
            with self.subTest(updates=updates):
                with self.assertRaises(RenderError) as caught:
                    build_export_manifest(request(), source, record(source, **updates))
                self.assertEqual(caught.exception.code, "SOURCE_LINEAGE_MISMATCH")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    async def test_all_real_platform_variants_are_verified_and_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captions = root / "captions.srt"
            captions.write_text("1\n00:00:00,000 --> 00:00:00,400\nExample\n\n", encoding="utf-8")
            raw = root / "composed.mp4"
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error",
                "-f", "lavfi", "-i", "color=c=green:s=180x320:r=10",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-f", "srt", "-i", str(captions), "-t", "0.4",
                "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "mov_text", str(raw),
            ], check=True, timeout=30)
            source = ManagedAssetStore(root).store(asset_id=SOURCE_ID, source_path=raw, mime_type="video/mp4")
            verified = []
            variants = (
                (ExportProfileId.YOUTUBE_SHORTS_V1, OUTPUT_ID),
                (ExportProfileId.INSTAGRAM_REELS_V1, INSTAGRAM_OUTPUT_ID),
                (ExportProfileId.FACEBOOK_REELS_V1, FACEBOOK_OUTPUT_ID),
            )
            for profile_id, output_id in variants:
                ingest = RecordingIngest()
                result = await PlatformExportService(
                    storage_root=root, asset_ingest=ingest,
                    base_policy=RenderPolicy(timeout_seconds=60, max_output_bytes=50_000_000),
                ).export(
                    request=request(profile_id=profile_id, output_asset_id=output_id),
                    source=source, source_record=record(source),
                )
                output = root / f"{profile_id.value}.mp4"
                output.write_bytes(ingest.payload)
                probe = json.loads(subprocess.run([
                    "ffprobe", "-v", "error", "-show_entries",
                    "stream=codec_type,codec_name,width,height,avg_frame_rate", "-of", "json", str(output),
                ], check=True, capture_output=True, timeout=20).stdout)
                kinds = {item["codec_type"]: item for item in probe["streams"]}
                self.assertEqual((kinds["video"]["codec_name"], kinds["video"]["width"], kinds["video"]["height"]),
                                 ("h264", 1080, 1920))
                self.assertEqual(kinds["video"]["avg_frame_rate"], "30/1")
                self.assertEqual(kinds["audio"]["codec_name"], "aac")
                self.assertEqual(kinds["subtitle"]["codec_name"], "mov_text")
                self.assertEqual(ingest.calls[0]["kind"], AssetKind.EXPORT_VARIANT)
                self.assertFalse(ingest.calls[0]["media_metadata"]["publishing_performed"])
                self.assertEqual(result.manifest.profile_id, profile_id)
                verified.append(result.manifest.platform)
            Path(source.path).write_bytes(Path(source.path).read_bytes() + b"tamper")
            rejected = RecordingIngest()
            with self.assertRaises(RenderError) as caught:
                await PlatformExportService(
                    storage_root=root, asset_ingest=rejected,
                    base_policy=RenderPolicy(timeout_seconds=60, max_output_bytes=50_000_000),
                ).export(request=request(), source=source, source_record=record(source))

        self.assertEqual(verified, ["YOUTUBE", "INSTAGRAM", "FACEBOOK"])
        self.assertEqual(caught.exception.code, "INPUT_INTEGRITY_MISMATCH")
        self.assertEqual(rejected.calls, [])


if __name__ == "__main__":
    unittest.main()
