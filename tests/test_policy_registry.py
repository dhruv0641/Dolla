import json
import tempfile
import unittest
from pathlib import Path

from flowx_os.policies import RegistryError, load_registry


class PolicyRegistryTests(unittest.TestCase):
    def test_loads_checked_in_registry_and_enforces_safe_defaults(self):
        root = Path(__file__).resolve().parents[1]
        registry = load_registry(root / "config" / "prompt_registry.json")
        self.assertEqual(registry.version, 1)
        self.assertEqual(registry.max_scene_regenerations, 2)
        self.assertTrue(registry.human_approval_required)
        self.assertFalse(registry.autonomous_publishing_enabled)
        self.assertEqual(registry.get_prompt("scene-visual-direction", 1).version, 1)

    def test_rejects_autonomous_publishing_while_human_approval_is_required(self):
        data = {
            "version": 1,
            "policy": {
                "max_scene_regenerations": 2,
                "human_approval_required": True,
                "autonomous_publishing_enabled": True,
            },
            "prompts": [{"id": "p", "version": 1, "purpose": "test", "system": "test"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "conflicts"):
                load_registry(path)

    def test_rejects_duplicate_prompt_ids(self):
        data = {
            "version": 1,
            "policy": {
                "max_scene_regenerations": 0,
                "human_approval_required": True,
                "autonomous_publishing_enabled": False,
            },
            "prompts": [
                {"id": "p", "version": 1, "purpose": "first", "system": "first"},
                {"id": "p", "version": 2, "purpose": "second", "system": "second"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "Duplicate prompt"):
                load_registry(path)

    def test_rejects_invalid_regeneration_cap(self):
        data = {
            "version": 1,
            "policy": {
                "max_scene_regenerations": -1,
                "human_approval_required": True,
                "autonomous_publishing_enabled": False,
            },
            "prompts": [{"id": "p", "version": 1, "purpose": "test", "system": "test"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "max_scene_regenerations"):
                load_registry(path)

    def test_rejects_invalid_json_without_echoing_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text('{"private":"value",', encoding="utf-8")
            with self.assertRaises(RegistryError) as raised:
                load_registry(path)
            self.assertNotIn("private", str(raised.exception))

    def test_unknown_prompt_version_is_not_returned(self):
        root = Path(__file__).resolve().parents[1]
        registry = load_registry(root / "config" / "prompt_registry.json")
        with self.assertRaises(KeyError):
            registry.get_prompt("scene-visual-direction", 2)


if __name__ == "__main__":
    unittest.main()
