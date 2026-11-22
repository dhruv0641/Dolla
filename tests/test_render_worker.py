import hashlib
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
    FfmpegRenderWorker, RenderError, RenderPolicy, RenderRequest, build_render_manifest,
)


REQUEST_ID = UUID("bd949446-563c-41f5-8cbf-1db3b8eb188a")
BRAND_ID = UUID("79312d0e-6a03-4c1d-b850-22ea214d8a2e")
CONTENT_ID = UUID("1da8cf70-3f38-40c6-9ef2-0a26c9750ef1")
SOURCE_ID = UUID("93b68f29-4b28-4a78-bb27-0c9db24fb62a")
OUTPUT_ID = UUID("9d421854-feef-4b77-ab7f-ab8335db2134")


def request(**updates):
    values = {
        "request_id": REQUEST_ID, "brand_id": BRAND_ID, "content_id": CONTENT_ID,
        "owner_user_id": "owner-1", "render_version": 1,
        "input_asset_ids": (SOURCE_ID,), "output_asset_id": OUTPUT_ID,
    }
    values.update(updates)
    return RenderRequest.model_validate(values)


def record(source, **updates):
    values = dict(
        asset_id=source.asset_id, content_id=CONTENT_ID, kind=AssetKind.RAW_FLOW_CLIP,
        storage_uri=source.storage_uri, sha256_hex=source.sha256_hex,
        mime_type=source.mime_type, size_bytes=source.size_bytes,
    )
    values.update(updates)
    return AssetRecord(AssetMetadata(**values), datetime(2026, 11, 22, tzinfo=timezone.utc))


class RecordingIngest:
    def __init__(self):
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        self.payload = Path(kwargs["source_path"]).read_bytes()


class RenderWorkerTests(unittest.IsolatedAsyncioTestCase):
    def test_request_and_policy_reject_unsafe_or_ambiguous_values(self):
        with self.assertRaises(ValidationError):
            request(input_asset_ids=(SOURCE_ID, SOURCE_ID))
        with self.assertRaises(ValidationError):
            request(output_asset_id=SOURCE_ID)
        with self.assertRaises(ValueError):
            RenderPolicy(timeout_seconds=float("nan"))
        with self.assertRaises(ValueError):
            RenderPolicy(video_codec="copy")  # type: ignore[arg-type]

    def test_manifest_is_stable_path_free_and_database_normalized(self):
        source = type("Source", (), {
            "asset_id": SOURCE_ID, "storage_uri": f"managed://assets/{SOURCE_ID.hex}/payload",
            "sha256_hex": "a" * 64, "mime_type": "video/mp4", "size_bytes": 120,
        })()
        first = build_render_manifest(request(), [record(source)], RenderPolicy())
        second = build_render_manifest(request(), [record(source)], RenderPolicy())
        self.assertEqual(first, second)
        self.assertRegex(first.fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(first.inputs_manifest(), {"asset_ids": [str(SOURCE_ID)]})
        command = first.command_manifest()
        self.assertNotIn("inputs", command)
        self.assertNotIn("path", str(command).lower())
        self.assertNotIn("ffmpeg", str(command).lower())

    def test_manifest_rejects_lineage_kind_type_and_unsupported_composition(self):
        source = type("Source", (), {
            "asset_id": SOURCE_ID, "storage_uri": f"managed://assets/{SOURCE_ID.hex}/payload",
            "sha256_hex": "b" * 64, "mime_type": "video/mp4", "size_bytes": 120,
        })()
        with self.assertRaises(RenderError) as caught:
            build_render_manifest(request(), [record(source, content_id=UUID(int=1))], RenderPolicy())
        self.assertEqual(caught.exception.code, "INPUT_LINEAGE_MISMATCH")
        with self.assertRaises(RenderError) as caught:
            build_render_manifest(request(), [record(source, kind=AssetKind.THUMBNAIL, mime_type="image/png")], RenderPolicy())
        self.assertEqual(caught.exception.code, "INPUT_KIND_UNSUPPORTED")
        other_id = UUID("1b34d767-a92f-4072-9b98-f6cd88221528")
        other = type("Source", (), {
            "asset_id": other_id, "storage_uri": f"managed://assets/{other_id.hex}/payload",
            "sha256_hex": "c" * 64, "mime_type": "video/mp4", "size_bytes": 120,
        })()
        with self.assertRaises(RenderError) as caught:
            build_render_manifest(
                request(input_asset_ids=(SOURCE_ID, other_id)), [record(source), record(other)], RenderPolicy(),
            )
        self.assertEqual(caught.exception.code, "OPERATION_UNSUPPORTED")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    async def test_real_render_verifies_managed_input_and_ingests_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "source.mp4"
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=blue:s=160x90:r=10", "-t", "0.25", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-an", str(raw)],
                check=True, timeout=20,
            )
            source = ManagedAssetStore(root).store(asset_id=SOURCE_ID, source_path=raw, mime_type="video/mp4")
            ingest = RecordingIngest()
            result = await FfmpegRenderWorker(storage_root=root, asset_ingest=ingest).render(
                request=request(), sources=[source], source_records=[record(source)],
            )

            rejected = RecordingIngest()
            with self.assertRaises(RenderError) as caught:
                await FfmpegRenderWorker(
                    storage_root=root, asset_ingest=rejected, ffprobe="missing-flowx-ffprobe",
                ).render(request=request(), sources=[source], source_records=[record(source)])

        self.assertEqual(result.output_asset_id, OUTPUT_ID)
        self.assertEqual(result.output_size_bytes, len(ingest.payload))
        self.assertEqual(result.output_sha256_hex, hashlib.sha256(ingest.payload).hexdigest())
        self.assertEqual(ingest.payload[4:8], b"ftyp")
        self.assertEqual(ingest.calls[0]["kind"], AssetKind.FINAL_VIDEO)
        self.assertEqual(ingest.calls[0]["media_metadata"]["render_fingerprint"], result.manifest.fingerprint)
        self.assertEqual(caught.exception.code, "OUTPUT_MEDIA_INVALID")
        self.assertEqual(rejected.calls, [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    async def test_tampered_or_wrong_source_fails_before_ingest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "source.mp4"
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=red:s=80x80:r=5", "-t", "0.2", "-c:v", "libx264", "-an", str(raw)],
                check=True, timeout=20,
            )
            source = ManagedAssetStore(root).store(asset_id=SOURCE_ID, source_path=raw, mime_type="video/mp4")
            Path(source.path).write_bytes(Path(source.path).read_bytes() + b"tamper")
            ingest = RecordingIngest()
            with self.assertRaises(RenderError) as caught:
                await FfmpegRenderWorker(storage_root=root, asset_ingest=ingest).render(
                    request=request(), sources=[source], source_records=[record(source)],
                )
        self.assertEqual(caught.exception.code, "INPUT_INTEGRITY_MISMATCH")
        self.assertEqual(ingest.calls, [])


if __name__ == "__main__":
    unittest.main()
