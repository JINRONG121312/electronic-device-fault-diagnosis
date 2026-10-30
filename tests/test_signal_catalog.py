import json
import unittest
from pathlib import Path

from fru_diagnosis import load_device_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SignalCatalogTests(unittest.TestCase):
    def test_signal_catalog_targets_known_frus(self):
        profile = load_device_profile(PROJECT_ROOT / "configs" / "asus_tianxuan5_fx607jv.json")
        profile_fru_ids = {fru.id for fru in profile.fru_list}

        catalog = json.loads(
            (PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json").read_text(
                encoding="utf-8-sig"
            )
        )
        catalog_fru_ids = {item["fru_id"] for item in catalog["fru_signals"]}

        self.assertEqual(catalog_fru_ids, profile_fru_ids)

    def test_each_fru_has_required_or_active_test_signal(self):
        catalog = json.loads(
            (PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json").read_text(
                encoding="utf-8-sig"
            )
        )

        for item in catalog["fru_signals"]:
            has_required = bool(item.get("required"))
            has_active_test = bool(item.get("active_test"))
            self.assertTrue(
                has_required or has_active_test,
                msg=f"{item['fru_id']} has no required or active-test signals",
            )


if __name__ == "__main__":
    unittest.main()
