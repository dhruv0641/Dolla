from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.assets.probing import MediaProbeError
from flowx_os.assets.storage import ManagedAssetStore, StoredAssetFile
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata
from flowx_os.qa.av_evaluation import (
    AvDecision,
    AvEvaluationError,
    AvEvaluationPolicy,
    AvEvaluationService,
    AvMeasurements,
    LocalFfmpegAvAnalyzer,
    parse_av_analysis,
)
from flowx_os.qa.integrity import IntegrityDecision, IntegrityReport


ASSET_ID = UUID("c63f3cd8-2612-411b-b4dd-505112c36cf5")
CONTENT_ID = UUID("c78092b8-a89a-4164-a9ea-9e0dc3d32fa7")
HASH = "a" * 64
INTEGRITY_FINGERPRINT = "b" * 64


class Analyzer:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def analyze(self, asset, *, duration_ms, policy):
        self.calls.append((asset, duration_ms, policy))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def managed():
    stored = StoredAssetFile(
        ASSET_ID, Path("C:/managed/assets") / ASSET_ID.hex / "payload",
        f"managed://assets/{ASSET_ID.hex}/payload", HASH, "video/mp4", 100,
    )
    metadata = AssetMetadata(
        asset_id=ASSET_ID, content_id=CONTENT_ID, kind=AssetKind.FINAL_VIDEO,
        storage_uri=stored.storage_uri, sha256_hex=HASH,
        mime_type="video/mp4", size_bytes=100,
        media_metadata={"duration_ms": 1000},
    )
    return stored, AssetRecord(metadata, datetime(2026, 11, 22, tzinfo=timezone.utc))


def integrity(**updates):
    values = {
        "asset_id": ASSET_ID, "content_id": CONTENT_ID,
        "expected_kind": AssetKind.FINAL_VIDEO, "profile_id": None,
        "artifact_fingerprint": "c" * 64,
        "decision": IntegrityDecision.PASS, "findings": (),
        "decode_verified": True, "observed_sha256_hex": HASH,
        "evidence_fingerprint": INTEGRITY_FINGERPRINT,
    }
    values.update(updates)
    return IntegrityReport.model_validate(values)


def measurements(**updates):
    values = {
        "evaluated_duration_ms": 1000,
        "black_duration_ms": 0, "black_ratio": 0.0, "black_intervals": 0,
        "freeze_duration_ms": 0, "freeze_ratio": 0.0, "freeze_intervals": 0,
        "silence_duration_ms": 0, "silence_ratio": 0.0, "silence_intervals": 0,
        "integrated_lufs": -16.0, "true_peak_dbtp": -2.0,
    }
    values.update(updates)
    return AvMeasurements.model_validate(values)


class AvEvaluationTests(unittest.TestCase):
    def test_policy_rejects_nonfinite_or_unsafe_bounds(self):
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises((ValidationError, TypeError)):
                AvEvaluationPolicy(target_lufs=value)
        with self.assertRaises(ValidationError):
            AvEvaluationPolicy(output_limit_bytes=10)
        with self.assertRaises(ValidationError):
            measurements(black_duration_ms=100, black_ratio=0.2)

    def test_parser_accepts_only_complete_bounded_numeric_summary(self):
        payload = b"""
        black_duration:0.1
        freeze_duration: 0.2
        silence_duration: 0.3
        Integrated loudness:\n I: -17.2 LUFS
        True peak:\n Peak: -1.5 dBFS
        """
        result = parse_av_analysis(payload, duration_ms=1000)
        self.assertEqual(
            (result.black_duration_ms, result.freeze_duration_ms, result.silence_duration_ms),
            (100, 200, 300),
        )
        self.assertEqual((result.integrated_lufs, result.true_peak_dbtp), (-17.2, -1.5))
        with self.assertRaisesRegex(MediaProbeError, "ANALYSIS_INVALID"):
            parse_av_analysis(b"C:/secret/path", duration_ms=1000)

    def test_clean_objective_metrics_pass_and_subjective_signals_remain_explicit(self):
        stored, record = managed()
        analyzer = Analyzer(measurements())
        service = AvEvaluationService(analyzer)
        first = service.evaluate(integrity(), stored, record, duration_ms=1000)
        second = service.evaluate(integrity(), stored, record, duration_ms=1000)
        self.assertEqual(first.decision, AvDecision.PASS)
        self.assertEqual(first.findings, ())
        self.assertEqual(len(first.subjective_signals_not_evaluated), 3)
        self.assertEqual(first.evidence_fingerprint, second.evidence_fingerprint)
        self.assertEqual(analyzer.calls[0][1], 1000)
        payload = first.model_dump()
        payload["decision"] = AvDecision.FAIL
        with self.assertRaises(ValidationError):
            type(first).model_validate(payload)
        payload = first.model_dump()
        payload["evidence_fingerprint"] = "f" * 64
        with self.assertRaises(ValidationError):
            type(first).model_validate(payload)

    def test_failures_are_stably_ordered_and_not_scored(self):
        stored, record = managed()
        result = AvEvaluationService(Analyzer(measurements(
            black_ratio=0.1, black_duration_ms=100,
            freeze_ratio=0.2, freeze_duration_ms=200,
            silence_ratio=0.3, silence_duration_ms=300,
            integrated_lufs=-25.0, true_peak_dbtp=-0.1,
        ))).evaluate(integrity(), stored, record, duration_ms=1000)
        self.assertEqual(result.decision, AvDecision.FAIL)
        self.assertEqual(
            [item.code.value for item in result.findings],
            [
                "BLACK_DURATION_EXCEEDED", "FREEZE_DURATION_EXCEEDED",
                "SILENCE_DURATION_EXCEEDED", "LOUDNESS_OUT_OF_RANGE",
                "TRUE_PEAK_EXCEEDED",
            ],
        )
        self.assertNotIn("score", result.model_dump())

    def test_unavailable_analysis_requires_human_and_redacts_tool_text(self):
        stored, record = managed()
        result = AvEvaluationService(Analyzer(MediaProbeError("C:/secret/path"))).evaluate(
            integrity(), stored, record, duration_ms=1000,
        )
        self.assertEqual(result.decision, AvDecision.NEEDS_HUMAN)
        self.assertEqual(result.findings[0].observed, "MEDIA_ANALYSIS_FAILED")
        self.assertIsNone(result.measurements)

    def test_asset_change_is_blocking_and_bad_integrity_never_invokes_analyzer(self):
        stored, record = managed()
        changed = AvEvaluationService(Analyzer(MediaProbeError("MEDIA_INTEGRITY_MISMATCH"))).evaluate(
            integrity(), stored, record, duration_ms=1000,
        )
        self.assertEqual(changed.decision, AvDecision.FAIL)
        self.assertEqual(changed.findings[0].code.value, "ASSET_REVALIDATION_FAILED")

        analyzer = Analyzer(measurements())
        with self.assertRaisesRegex(AvEvaluationError, "INTEGRITY_PREREQUISITE_FAILED"):
            AvEvaluationService(analyzer).evaluate(
                integrity(decision=IntegrityDecision.FAIL), stored, record,
                duration_ms=1000,
            )
        self.assertEqual(analyzer.calls, [])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_real_local_moving_video_and_audio_produce_bounded_measurements(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "fixture.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "2", str(source),
                ],
                check=True, timeout=20,
            )
            stored = ManagedAssetStore(root).store(
                asset_id=ASSET_ID, source_path=source, mime_type="video/mp4",
            )
            result = LocalFfmpegAvAnalyzer(root).analyze(
                stored, duration_ms=2000,
                policy=AvEvaluationPolicy(
                    target_lufs=-20.0, loudness_tolerance_lu=30.0,
                    max_true_peak_dbtp=0.0,
                ),
            )
            self.assertEqual(result.black_duration_ms, 0)
            self.assertEqual(result.freeze_duration_ms, 0)
            self.assertEqual(result.silence_duration_ms, 0)
            self.assertTrue(-100 < result.integrated_lufs < 10)
            self.assertTrue(-100 < result.true_peak_dbtp <= 0)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_real_black_frozen_and_silent_sections_are_measured(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "failure.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10:d=1.2",
                    "-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=0.8",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                    "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]",
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "2", str(source),
                ],
                check=True, timeout=20,
            )
            stored = ManagedAssetStore(root).store(
                asset_id=ASSET_ID, source_path=source, mime_type="video/mp4",
            )
            result = LocalFfmpegAvAnalyzer(root).analyze(
                stored, duration_ms=2000, policy=AvEvaluationPolicy(),
            )
            self.assertGreater(result.black_ratio, 0.5)
            self.assertGreater(result.freeze_ratio, 0.4)
            self.assertGreater(result.silence_ratio, 0.4)


if __name__ == "__main__":
    unittest.main()
