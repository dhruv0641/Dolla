from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.assets.probing import MediaProbeError, MediaProbeService, MediaReport, MediaStream
from flowx_os.assets.storage import ManagedAssetStore, StoredAssetFile
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata
from flowx_os.qa.integrity import (
    IntegrityCheckError, IntegrityDecision, IntegrityExpectation, MediaIntegrityService,
)


ASSET_ID = UUID("4beec3b7-4053-4c44-8ebc-56df62d45b31")
CONTENT_ID = UUID("269d0d0d-5d79-4094-a5be-8e2b293add68")
HASH = "a" * 64
FINGERPRINT = "b" * 64


class Inspector:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def inspect(self, asset, policy=None):
        self.calls.append((asset, policy))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def expectation(**updates):
    values = {
        "asset_id": ASSET_ID, "content_id": CONTENT_ID,
        "expected_kind": AssetKind.EXPORT_VARIANT,
        "artifact_fingerprint": FINGERPRINT,
        "profile_id": "YOUTUBE_SHORTS_V1",
        "width": 1080, "height": 1920, "frame_rate": 30,
        "duration_ms": 1000,
    }
    values.update(updates)
    return IntegrityExpectation.model_validate(values)


def managed():
    stored = StoredAssetFile(
        ASSET_ID, Path("C:/managed/assets") / ASSET_ID.hex / "payload",
        f"managed://assets/{ASSET_ID.hex}/payload", HASH, "video/mp4", 100,
    )
    metadata = AssetMetadata(
        asset_id=ASSET_ID, content_id=CONTENT_ID, kind=AssetKind.EXPORT_VARIANT,
        storage_uri=stored.storage_uri, sha256_hex=HASH, mime_type="video/mp4", size_bytes=100,
        media_metadata={
            "export_fingerprint": FINGERPRINT,
            "export_profile_id": "YOUTUBE_SHORTS_V1",
            "width": 1080, "height": 1920, "frame_rate": 30,
            "duration_ms": 1000, "subtitles_muxed": True,
        },
    )
    return stored, AssetRecord(metadata, datetime(2026, 11, 22, tzinfo=timezone.utc))


def good_report():
    return MediaReport(
        HASH, 1.0,
        (
            MediaStream(
                "video", "h264", 1080, 1920, 9 / 16, 30.0,
                video_profile="High", pixel_format="yuv420p",
            ),
            MediaStream("audio", "aac", sample_rate=48_000, channels=1),
            MediaStream("subtitle", "mov_text"),
        ),
        True, (), 1.0, ("mov", "mp4", "m4a", "3gp", "3g2", "mj2"),
    )


class IntegrityCheckTests(unittest.TestCase):
    def test_expectation_rejects_wrong_role_profile_contract(self):
        with self.assertRaises(ValidationError):
            expectation(expected_kind=AssetKind.FINAL_VIDEO)
        with self.assertRaises(ValidationError):
            expectation(expected_kind=AssetKind.RAW_FLOW_CLIP, profile_id=None)

    def test_matching_artifact_passes_with_reproducible_evidence(self):
        stored, record = managed()
        inspector = Inspector(good_report())
        service = MediaIntegrityService(inspector)
        first = service.evaluate(expectation(), stored, record)
        second = service.evaluate(expectation(), stored, record)
        self.assertEqual(first.decision, IntegrityDecision.PASS)
        self.assertEqual(first.findings, ())
        self.assertTrue(first.decode_verified)
        self.assertEqual(first.evidence_fingerprint, second.evidence_fingerprint)
        self.assertFalse(inspector.calls[0][1].require_audio)

    def test_lineage_mismatch_fails_before_probe(self):
        stored, record = managed()
        inspector = Inspector(good_report())
        with self.assertRaisesRegex(IntegrityCheckError, "ASSET_LINEAGE_MISMATCH"):
            MediaIntegrityService(inspector).evaluate(
                expectation(content_id=UUID("3110e0ed-009b-47e4-bbee-3f70a9892857")), stored, record,
            )
        self.assertEqual(inspector.calls, [])

    def test_mismatches_have_stable_machine_readable_order(self):
        stored, record = managed()
        report = MediaReport(
            "c" * 64, 2.0,
            (
                MediaStream(
                    "video", "vp9", 720, 1280, 9 / 16, 24.0,
                    video_profile="Profile 0", pixel_format="yuv444p",
                ),
                MediaStream("audio", "opus", sample_rate=48_000, channels=2),
                MediaStream("audio", "aac", sample_rate=48_000, channels=2),
            ),
            False, ("VIDEO_CODEC_UNSUPPORTED",), None, ("matroska",),
        )
        result = MediaIntegrityService(Inspector(report)).evaluate(expectation(), stored, record)
        self.assertEqual(result.decision, IntegrityDecision.FAIL)
        self.assertEqual(
            [item.code for item in result.findings],
            [
                "HASH_MISMATCH", "DECODE_UNVERIFIED", "CONTAINER_MISMATCH",
                "VIDEO_CODEC_MISMATCH", "VIDEO_PROFILE_MISMATCH", "PIXEL_FORMAT_MISMATCH",
                "DIMENSIONS_MISMATCH", "FRAME_RATE_MISMATCH",
                "AUDIO_STREAM_COUNT", "SUBTITLE_STREAM_COUNT", "DURATION_MISMATCH",
            ],
        )

    def test_declared_metadata_and_safe_probe_failure_fail_closed(self):
        stored, record = managed()
        altered = record.metadata.model_copy(update={"media_metadata": {**record.metadata.media_metadata, "width": 1}})
        result = MediaIntegrityService(Inspector(MediaProbeError("MEDIA_TOOL_TIMEOUT"))).evaluate(
            expectation(), stored, AssetRecord(altered, record.created_at),
        )
        self.assertEqual(result.decision, IntegrityDecision.FAIL)
        self.assertEqual(
            [item.code for item in result.findings],
            ["DECLARED_METADATA_MISMATCH", "ASSET_INTEGRITY_UNVERIFIED"],
        )
        self.assertEqual(result.findings[-1].observed, "MEDIA_TOOL_TIMEOUT")
        self.assertIsNone(result.observed_sha256_hex)

    def test_untrusted_probe_error_text_is_redacted(self):
        stored, record = managed()
        result = MediaIntegrityService(Inspector(MediaProbeError("C:/secret/path"))).evaluate(
            expectation(), stored, record,
        )
        self.assertEqual(result.findings[0].observed, "MEDIA_PROBE_FAILED")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    def test_real_muxed_artifact_passes_exact_container_stream_and_rate_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            caption = root / "caption.srt"
            caption.write_text("1\n00:00:00,000 --> 00:00:00,900\nIntegrity check\n", encoding="utf-8")
            source = root / "fixture.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-f", "srt", "-i", str(caption),
                    "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-c:s", "mov_text", "-t", "1", str(source),
                ],
                check=True, timeout=20,
            )
            stored = ManagedAssetStore(root).store(
                asset_id=ASSET_ID, source_path=source, mime_type="video/mp4",
            )
            metadata = AssetMetadata(
                asset_id=ASSET_ID, content_id=CONTENT_ID, kind=AssetKind.FINAL_VIDEO,
                storage_uri=stored.storage_uri, sha256_hex=stored.sha256_hex,
                mime_type="video/mp4", size_bytes=stored.size_bytes,
                media_metadata={
                    "composition_fingerprint": FINGERPRINT,
                    "target_width": 160, "target_height": 90, "frame_rate": 10,
                    "duration_ms": 1000, "subtitles_muxed": True,
                },
            )
            report = MediaIntegrityService(MediaProbeService(root)).evaluate(
                expectation(
                    expected_kind=AssetKind.FINAL_VIDEO, profile_id=None,
                    width=160, height=90, frame_rate=10,
                ),
                stored, AssetRecord(metadata, datetime.now(timezone.utc)),
            )
            self.assertEqual(report.decision, IntegrityDecision.PASS, report)


if __name__ == "__main__":
    unittest.main()
