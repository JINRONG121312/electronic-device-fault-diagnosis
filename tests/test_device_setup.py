import json
import tempfile
import unittest
from pathlib import Path

from fru_diagnosis.device_setup import (
    SetupInputs,
    setup_detected_device_profile,
    setup_device_profile,
)


def build_scan_profile() -> dict:
    return {
        "device_type": "laptop",
        "display_name": "LENOVO 81YL",
        "version": "1.0",
        "description": "Auto-detected FRU profile.",
        "metadata": {
            "manufacturer": "LENOVO",
            "model": "81YL",
        },
        "fru_list": [
            {
                "id": "battery_pack",
                "name": "Battery Pack",
                "category": "PowerFRU",
                "replaceable": True,
                "description": "Detected battery.",
                "aliases": ["battery"],
                "evidence_rules": [
                    {
                        "id": "battery_low",
                        "evidence_type": "metric_threshold",
                        "source": "battery_status",
                        "weight": 0.3,
                        "description": "Battery charge is low.",
                        "metric": "estimated_charge_remaining",
                        "operator": "<",
                        "threshold": 10,
                    }
                ],
            }
        ],
    }


class DeviceSetupTests(unittest.TestCase):
    def test_detected_lenovo_laptop_uses_pre_fru_profile(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scan_path = root / "detected_device.json"
            active_path = root / "active_device.json"
            report_path = root / "report.json"
            scan_path.write_text(
                json.dumps(build_scan_profile(), ensure_ascii=False),
                encoding="utf-8",
            )

            report = setup_detected_device_profile(
                scan_path=scan_path,
                output_path=active_path,
                report_path=report_path,
            )

            self.assertEqual(report["mode"], "known_model_profile")
            self.assertEqual(
                report["model_match"]["registry_id"],
                "lenovo_ideapad_5_15iil05_81yl",
            )
            self.assertIn("Lenovo", report["selected_profile"]["display_name"])
            self.assertTrue(active_path.exists())
            active_profile = json.loads(active_path.read_text(encoding="utf-8"))
            self.assertEqual(
                active_profile["display_name"], "Lenovo IdeaPad 5 15IIL05 / 81YL"
            )
            self.assertEqual(
                active_profile["metadata"]["setup_mode"], "known_model_profile"
            )
            self.assertEqual(
                active_profile["metadata"]["selected_registry_id"],
                "lenovo_ideapad_5_15iil05_81yl",
            )
            target_fru_ids = {
                fru["id"]
                for fru in active_profile["fru_list"]
                if fru.get("replaceable") and fru.get("diagnosis_role") == "target_fru"
            }
            self.assertIn("m2_ssd_module", target_fru_ids)
            self.assertIn("motherboard", target_fru_ids)
            self.assertNotIn("ram_module", target_fru_ids)

    def test_custom_setup_keeps_active_path_current(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scan_path = root / "detected_device.json"
            active_path = root / "active_device.json"
            report_path = root / "report.json"
            scan_path.write_text(
                json.dumps(build_scan_profile(), ensure_ascii=False),
                encoding="utf-8",
            )

            setup_device_profile(
                SetupInputs(
                    declared_device_type="laptop",
                    scan_path=scan_path,
                    output_path=active_path,
                    report_path=report_path,
                    run_detection=False,
                    allow_mismatch=True,
                )
            )

            active_profile = json.loads(active_path.read_text(encoding="utf-8"))
            self.assertEqual(
                active_profile["display_name"], "Lenovo IdeaPad 5 15IIL05 / 81YL"
            )


if __name__ == "__main__":
    unittest.main()
