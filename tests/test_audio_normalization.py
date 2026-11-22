import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from uuid import UUID
import wave
from datetime import datetime, timezone

from pydantic import ValidationError

from flowx_os.assets.storage import ManagedAssetStore
from flowx_os.audio.normalization import (
    AudioNormalizationError,
    AudioNormalizationPolicy,
    AudioNormalizationRequest,
    AudioNormalizationService,
    NarrationTiming,
    normalization_fingerprint,
)
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata


REQUEST_ID = UUID("123dcbd8-dc02-4a60-9a3e-303828e11a74")
SOURCE_ID = UUID("93b68f29-4b28-4a78-bb27-0c9db24fb62a")
OUTPUT_ID = UUID("9d421854-feef-4b77-ab7f-ab8335db2134")
BRAND_ID = UUID("79312d0e-6a03-4c1d-b850-22ea214d8a2e")
CONTENT_ID = UUID("1da8cf70-3f38-40c6-9ef2-0a26c9750ef1")


def request(**updates):
    values = {
        "request_id": REQUEST_ID, "source_asset_id": SOURCE_ID,
        "output_asset_id": OUTPUT_ID, "brand_id": BRAND_ID,
        "content_id": CONTENT_ID, "owner_user_id": "owner-1",
        "timing": NarrationTiming(start_ms=0, content_duration_ms=250),
    }
    values.update(updates)
    return AudioNormalizationRequest.model_validate(values)


def write_wav(path: Path, *, duration_ms=100, rate=16_000):
    frames = round(rate * duration_ms / 1000)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = [int(4000 * math.sin(2 * math.pi * 440 * index / rate)) for index in range(frames)]
        output.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


class RecordingIngest:
    def __init__(self):
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        self.bytes = Path(kwargs["source_path"]).read_bytes()


def record(source):
    return AssetRecord(
        AssetMetadata(
            asset_id=source.asset_id, content_id=CONTENT_ID, kind=AssetKind.NARRATION,
            storage_uri=source.storage_uri, sha256_hex=source.sha256_hex,
            mime_type=source.mime_type, size_bytes=source.size_bytes,
        ),
        datetime(2026, 11, 22, tzinfo=timezone.utc),
    )


class AudioNormalizationTests(unittest.IsolatedAsyncioTestCase):
    def test_timeline_requires_exact_zero_and_fingerprint_is_stable(self):
        with self.assertRaises(ValidationError):
            NarrationTiming(start_ms=1, content_duration_ms=1000)
        first = normalization_fingerprint(request(), AudioNormalizationPolicy())
        second = normalization_fingerprint(request(), AudioNormalizationPolicy())
        changed = normalization_fingerprint(
            request(timing=NarrationTiming(start_ms=0, content_duration_ms=300)),
            AudioNormalizationPolicy(),
        )
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        with self.assertRaises(ValidationError):
            request(output_asset_id=SOURCE_ID)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    async def test_real_normalization_starts_at_zero_pads_and_registers_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.wav"
            write_wav(source_path)
            source = ManagedAssetStore(root).store(
                asset_id=SOURCE_ID, source_path=source_path, mime_type="audio/wav",
            )
            ingest = RecordingIngest()
            result = await AudioNormalizationService(
                storage_root=root, asset_ingest=ingest,
            ).normalize(request=request(), source=source, source_record=record(source))

        self.assertEqual(result.start_ms, 0)
        self.assertEqual(result.duration_ms, 250)
        self.assertEqual((result.sample_rate_hz, result.channels, result.sample_width_bytes), (48_000, 1, 2))
        self.assertTrue(ingest.bytes.startswith(b"RIFF"))
        metadata = ingest.calls[0]["media_metadata"]
        self.assertEqual(metadata["timeline_start_ms"], 0)
        self.assertEqual(metadata["source_asset_id"], SOURCE_ID.hex)
        self.assertFalse(metadata["loudness_measurement_verified"])
        self.assertEqual(ingest.calls[0]["output_asset_id"] if "output_asset_id" in ingest.calls[0] else ingest.calls[0]["asset_id"], OUTPUT_ID)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    async def test_long_narration_and_identity_mismatch_fail_before_ingest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.wav"
            write_wav(source_path, duration_ms=400)
            source = ManagedAssetStore(root).store(
                asset_id=SOURCE_ID, source_path=source_path, mime_type="audio/wav",
            )
            ingest = RecordingIngest()
            service = AudioNormalizationService(storage_root=root, asset_ingest=ingest)
            with self.assertRaises(AudioNormalizationError) as caught:
                await service.normalize(request=request(), source=source, source_record=record(source))
            self.assertEqual(caught.exception.code, "NARRATION_TOO_LONG")
            self.assertEqual(ingest.calls, [])

            with self.assertRaises(AudioNormalizationError) as caught:
                await service.normalize(
                    request=request(source_asset_id=UUID("07e851a6-01e4-4b39-89b9-0cbb969c711a")),
                    source=source, source_record=record(source),
                )
            self.assertEqual(caught.exception.code, "SOURCE_ID_MISMATCH")

            wrong = record(source)
            wrong = AssetRecord(
                wrong.metadata.model_copy(update={"content_id": UUID("9abf05a8-73b0-441d-bf70-45f2fd58aaab")}),
                wrong.created_at,
            )
            with self.assertRaises(AudioNormalizationError) as caught:
                await service.normalize(request=request(), source=source, source_record=wrong)
            self.assertEqual(caught.exception.code, "SOURCE_LINEAGE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
