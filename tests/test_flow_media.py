from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from flowx_os.flow_mcp.capabilities import FlowAccountAuthorization, FlowOperation, _issue_flow_account_authorization
from flowx_os.flow_mcp.media import FlowMediaError, FlowMediaItem, FlowMediaService


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
MEDIA_ID = "61b3b89d-9b48-4c63-a101-0a80d38940b0"


class FakeFlowAdapter:
    def __init__(self, *, project=None, download=None):
        self.project = project or {"project_id": "project-1", "media": [
            {"uuid": MEDIA_ID, "kind": "image", "title": "still"},
            {"uuid": "../../escape", "kind": "image", "title": "bad"},
            {"uuid": MEDIA_ID, "kind": "video", "title": "duplicate"},
            {"kind": "video", "title": "video without ID"},
        ]}
        self.download = download
        self.calls = []

    async def invoke(self, operation, arguments, *, account, spend=None):
        self.calls.append((operation, arguments, account))
        if operation == FlowOperation.PROJECT_OPEN:
            return self.project
        if self.download:
            return self.download(arguments)
        path = Path(arguments["output_dir"]) / "asset.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        return {"path": str(path), "content_type": "image/png", "bytes": path.stat().st_size}


class FlowMediaServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.account = _issue_flow_account_authorization(
            "acct-test", checked_at=NOW, valid_until=NOW + timedelta(minutes=5)
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    async def test_project_listing_keeps_only_valid_unique_media_uuids(self):
        adapter = FakeFlowAdapter()
        service = FlowMediaService(adapter, account=self.account, media_root=Path(self.tmp.name))
        result = await service.list_project(project_url="https://flow.google.com/project/project-1")
        self.assertEqual(result.project_id, "project-1")
        self.assertEqual(result.items, (FlowMediaItem(MEDIA_ID, "image", "still"),))
        self.assertEqual(adapter.calls[0][0], FlowOperation.PROJECT_OPEN)

    async def test_retrieval_verifies_bytes_records_hash_and_is_idempotent(self):
        adapter = FakeFlowAdapter()
        service = FlowMediaService(adapter, account=self.account, media_root=Path(self.tmp.name))
        item = FlowMediaItem(MEDIA_ID, "image", "still")
        first = await service.retrieve(item=item)
        second = await service.retrieve(item=item)
        self.assertEqual(first, second)
        self.assertEqual(first.mime_type, "image/png")
        self.assertEqual(first.size_bytes, first.storage_path.stat().st_size)
        self.assertEqual(len(first.sha256_hex), 64)
        self.assertEqual(len(adapter.calls), 2)
        self.assertFalse(any(path.name.startswith(".flow-download-") for path in Path(self.tmp.name).iterdir()))

    async def test_project_url_must_be_https_flow_project(self):
        service = FlowMediaService(FakeFlowAdapter(), account=self.account, media_root=Path(self.tmp.name))
        with self.assertRaises(ValueError):
            await service.list_project(project_url="https://evil.example/project/1")

    async def test_external_download_path_is_rejected(self):
        outside = Path(self.tmp.name) / "outside.png"
        outside.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        adapter = FakeFlowAdapter(download=lambda _: {"path": str(outside), "content_type": "image/png"})
        service = FlowMediaService(adapter, account=self.account, media_root=Path(self.tmp.name) / "managed")
        with self.assertRaises(FlowMediaError):
            await service.retrieve(item=FlowMediaItem(MEDIA_ID, "image", "still"))

    async def test_mime_signature_conflict_and_size_limit_fail_closed(self):
        def wrong_mime(args):
            path = Path(args["output_dir"]) / "fake.jpg"
            path.write_bytes(b"not a jpeg" * 4)
            return {"path": str(path), "content_type": "image/jpeg"}
        service = FlowMediaService(FakeFlowAdapter(download=wrong_mime), account=self.account,
                                   media_root=Path(self.tmp.name) / "wrong")
        with self.assertRaises(FlowMediaError):
            await service.retrieve(item=FlowMediaItem(MEDIA_ID, "image", "still"))

        service = FlowMediaService(FakeFlowAdapter(), account=self.account,
                                   media_root=Path(self.tmp.name) / "small", max_bytes=8)
        with self.assertRaises(FlowMediaError):
            await service.retrieve(item=FlowMediaItem(MEDIA_ID, "image", "still"))

    async def test_unknown_or_invalid_media_items_are_rejected_before_tool_call(self):
        adapter = FakeFlowAdapter()
        service = FlowMediaService(adapter, account=self.account, media_root=Path(self.tmp.name))
        with self.assertRaises(ValueError):
            await service.retrieve(item=FlowMediaItem("../x", "image", "bad"))
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
