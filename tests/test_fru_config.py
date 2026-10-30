import tempfile
import unittest
from pathlib import Path

from fru_diagnosis import FRUConfigError, load_device_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FRUConfigTests(unittest.TestCase):
    def test_load_laptop_profile(self):
        profile = load_device_profile(PROJECT_ROOT / "configs" / "laptop.json")

        self.assertEqual(profile.device_type, "laptop")
        self.assertGreaterEqual(len(profile.fru_list), 8)
        self.assertEqual(profile.get_fru("ssd").category, "StorageFRU")
        self.assertTrue(profile.get_fru("battery_pack").replaceable)
        self.assertEqual(profile.get_fru("battery_pack").serviceability.type, "replaceable_fru")

    def test_load_server_profile(self):
        profile = load_device_profile(PROJECT_ROOT / "configs" / "server.json")

        self.assertEqual(profile.device_type, "server")
        self.assertEqual(profile.get_fru("nic_1").category, "CommunicationFRU")
        self.assertIn("StorageFRU", profile.to_summary()["categories"])

    def test_load_lenovo_ideapad_pre_fru_profile(self):
        profile = load_device_profile(
            PROJECT_ROOT / "configs" / "lenovo_ideapad_5_15iil05_81yl.json"
        )

        self.assertEqual(profile.device_type, "laptop")
        self.assertIn("Lenovo", profile.display_name)
        self.assertEqual(profile.get_fru("m2_ssd_module").category, "StorageFRU")
        self.assertEqual(profile.get_fru("motherboard").category, "MainboardFRU")
        self.assertFalse(profile.get_fru("ram_module").replaceable)
        self.assertEqual(profile.get_fru("ram_module").diagnosis_role, "subsystem")
        self.assertEqual(profile.get_fru("ram_module").serviceability.type, "non_replaceable_subsystem")
        self.assertEqual(profile.get_fru("ram_module").serviceability.parent_assembly, "motherboard")
        self.assertNotIn("ram_module", {fru.id for fru in profile.replaceable_frus()})

    def test_explicit_serviceability_is_validated(self):
        profile = load_device_profile(PROJECT_ROOT / "configs" / "active_device.json")

        adapter = profile.get_fru("power_adapter")
        motherboard = profile.get_fru("motherboard")

        self.assertEqual(adapter.serviceability.type, "external_part")
        self.assertEqual(adapter.serviceability.level, "external")
        self.assertFalse(adapter.serviceability.requires_disassembly)
        self.assertEqual(motherboard.serviceability.type, "serviceable_assembly")

    def test_reject_duplicate_fru_ids(self):
        profile_json = """{
          "device_type": "bad_device",
          "display_name": "Bad Device",
          "version": "1.0",
          "fru_list": [
            {"id": "same", "name": "A", "category": "PowerFRU"},
            {"id": "same", "name": "B", "category": "StorageFRU"}
          ]
        }"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "bad.json"
            path.write_text(profile_json, encoding="utf-8")

            with self.assertRaises(FRUConfigError):
                load_device_profile(path)

    def test_reject_unknown_category(self):
        profile_json = """{
          "device_type": "bad_device",
          "display_name": "Bad Device",
          "version": "1.0",
          "fru_list": [
            {"id": "x", "name": "X", "category": "UnknownFRU"}
          ]
        }"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "bad.json"
            path.write_text(profile_json, encoding="utf-8")

            with self.assertRaises(FRUConfigError):
                load_device_profile(path)


if __name__ == "__main__":
    unittest.main()
