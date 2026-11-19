import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.domain.assets import AssetKind, AssetMetadata


ASSET_ID = UUID("f2c13904-9b62-4a5d-9459-617b87946132")
CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
SCENE_ID = UUID("1de51411-a9b3-4596-b752-eeb3cc647941")
JOB_ID = UUID("d468282b-9f29-4da4-b32c-2dc80749fe61")


def valid_metadata(**updates):
    values = {
        "asset_id": ASSET_ID,
        "content_id": CONTENT_ID,
        "scene_id": SCENE_ID,
        "source_job_id": JOB_ID,
        "kind": AssetKind.RAW_FLOW_CLIP,
        "storage_uri": f"managed://assets/{ASSET_ID.hex}/payload",
        "sha256_hex": "a" * 64,
        "mime_type": "video/mp4",
        "size_bytes": 12,
        "media_metadata": {},
    }
    values.update(updates)
    return AssetMetadata.model_validate(values)


class AssetDomainTests(unittest.TestCase):
    def test_validates_supported_kind_and_storage_identity(self):
        value = valid_metadata()
        self.assertEqual(value.asset_id, ASSET_ID)

    def test_rejects_job_without_scene_and_kind_mime_mismatch(self):
        with self.assertRaises(ValidationError):
            valid_metadata(scene_id=None)
        with self.assertRaises(ValidationError):
            valid_metadata(mime_type="image/png")

    def test_rejects_malformed_digest_and_arbitrary_storage_uri(self):
        with self.assertRaises(ValidationError):
            valid_metadata(sha256_hex="not-a-sha")
        with self.assertRaises(ValidationError):
            valid_metadata(storage_uri="C:/private/file.png")
        with self.assertRaises(ValidationError):
            valid_metadata(storage_uri="managed://assets/" + "0" * 32 + "/payload")


if __name__ == "__main__":
    unittest.main()
