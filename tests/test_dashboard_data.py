import json
import tempfile
import unittest
from pathlib import Path

from fru_diagnosis.dashboard_data import (
    build_dashboard_payload,
    build_profile_signal_coverage,
    build_signal_coverage,
    summarize_event_buckets,
    set_runtime_test_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DashboardDataTests(unittest.TestCase):
    def test_build_dashboard_payload_includes_fru_summary(self):
        payload = build_dashboard_payload(
            profile_path=PROJECT_ROOT / "configs" / "active_device.json",
            runtime_path=PROJECT_ROOT / "data" / "runtime_info.json",
            catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
            setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
        )

        self.assertGreater(payload["summary"]["target_fru_count"], 0)
        self.assertGreater(len(payload["target_frus"]), 0)
        self.assertIn("signal_coverage", payload["summary"])
        self.assertIn("platform", payload)
        self.assertIn("evidence_layers", payload)
        self.assertIn("anomaly_detection", payload)
        self.assertIn("health_assessment", payload)
        self.assertIn("system_health", payload)
        self.assertIn("diagnosis", payload)
        self.assertIn("collection_plan", payload)
        self.assertIn("collection_readiness", payload)
        self.assertIn("average_score", payload["summary"]["signal_coverage"])
        self.assertIn("top_candidates", payload["diagnosis"])
        self.assertIn("status", payload["diagnosis"]["summary"])
        self.assertIn("classification", payload["diagnosis"]["summary"])
        self.assertIn("decision", payload["diagnosis"]["summary"])
        self.assertIn("health", payload["summary"])
        self.assertIn("score", payload["summary"]["health"])
        self.assertIn("maintenance_cadence", payload["summary"]["health"])
        self.assertEqual(
            payload["diagnosis"]["summary"]["classification"]["task"],
            "fault_classification",
        )
        self.assertEqual(
            payload["diagnosis"]["summary"]["decision"]["task"],
            "decision_after_classification",
        )
        self.assertIn("serviceability", payload["target_frus"][0])

    def test_dashboard_payload_describes_generalized_evidence_layers(self):
        payload = build_dashboard_payload(
            profile_path=PROJECT_ROOT / "configs" / "active_device.json",
            runtime_path=PROJECT_ROOT / "data" / "runtime_info.json",
            catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
            setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
        )

        self.assertIn(payload["platform"]["os_family"], {"windows", "linux", "other", "unknown"})
        self.assertEqual(
            {layer["id"] for layer in payload["evidence_layers"]},
            {"inventory", "metrics", "logs", "active_tests"},
        )

    def test_evidence_layer_marks_failed_collection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "collection_status": {
                            "logs.system": {"status": "failed", "error": "access denied"},
                        },
                        "events": {"total_warning_error_count": 0},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dashboard_payload(
                profile_path=PROJECT_ROOT / "configs" / "active_device.json",
                runtime_path=runtime_path,
                catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
                setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
            )

            layers = {layer["id"]: layer for layer in payload["evidence_layers"]}
            self.assertEqual(layers["logs"]["status"], "failed")

    def test_target_frus_have_chinese_explanations(self):
        payload = build_dashboard_payload(
            profile_path=PROJECT_ROOT / "configs" / "active_device.json",
            runtime_path=PROJECT_ROOT / "data" / "runtime_info.json",
            catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
            setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
        )

        missing = [
            fru["id"]
            for fru in payload["target_frus"]
            if not fru.get("zh_explanation", {}).get("brief")
        ]

        self.assertEqual(missing, [])

    def test_signal_coverage_marks_not_run_active_tests_as_missing(self):
        runtime = {
            "battery": {"present": True},
            "tests": {"power": {"adapter_detected": "not_run"}},
        }
        catalog = {
            "fru_signals": [
                {
                    "fru_id": "power_adapter",
                    "required": [{"key": "battery.present"}],
                    "enhancing": [],
                    "active_test": [{"key": "tests.power.adapter_detected"}],
                }
            ]
        }

        coverage = build_signal_coverage(runtime, catalog)

        self.assertEqual(coverage["power_adapter"]["required_present"], 1)
        self.assertEqual(coverage["power_adapter"]["active_test_present"], 0)
        self.assertEqual(coverage["power_adapter"]["missing_active_test"][0]["key"], "tests.power.adapter_detected")
        self.assertIn("score", coverage["power_adapter"])

    def test_profile_signal_coverage_falls_back_by_fru_category(self):
        runtime = {
            "storage": {"drives": [{"present": True, "status": "OK"}]},
            "events": {"storage": {"error_count": 0}},
            "tests": {"storage": {"short_self_test": "not_run"}},
        }
        catalog = {
            "fru_signals": [
                {
                    "fru_id": "m2_ssd_module",
                    "required": [
                        {"key": "storage.drives[].present"},
                        {"key": "events.storage.error_count"},
                    ],
                    "enhancing": [],
                    "active_test": [{"key": "tests.storage.short_self_test"}],
                }
            ]
        }
        target_frus = [
            {
                "id": "vendor_specific_drive",
                "name": "Vendor SSD",
                "category": "StorageFRU",
                "replaceable": True,
                "diagnosis_role": "target_fru",
                "aliases": ["ssd"],
            }
        ]

        coverage = build_profile_signal_coverage(runtime, catalog, target_frus)

        self.assertEqual(coverage["vendor_specific_drive"]["catalog_match"], "fallback")
        self.assertEqual(coverage["vendor_specific_drive"]["catalog_fru_id"], "m2_ssd_module")
        self.assertEqual(coverage["vendor_specific_drive"]["required_present"], 2)

    def test_diagnosis_ranks_failed_active_test(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "events": {"total_warning_error_count": 0},
                        "device_inventory": {"problem_device_count": 0, "problem_devices": []},
                        "tests": {"audio": {"left_right_speaker_result": "speaker_failed"}},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dashboard_payload(
                profile_path=PROJECT_ROOT / "configs" / "active_device.json",
                runtime_path=runtime_path,
                catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
                setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
            )

            top = payload["diagnosis"]["top_candidates"][0]
            self.assertEqual(top["fru_id"], "speaker_module")
            self.assertEqual(top["status"], "suspect")

    def test_diagnosis_does_not_map_usb_problem_to_speaker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "events": {"total_warning_error_count": 0},
                        "device_inventory": {
                            "problem_device_count": 1,
                            "problem_devices": [
                                {
                                    "name": "Unknown USB Device",
                                    "status": "Error",
                                    "pnp_class": "USB",
                                    "problem_code": 43,
                                }
                            ],
                        },
                        "tests": {},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dashboard_payload(
                profile_path=PROJECT_ROOT / "configs" / "active_device.json",
                runtime_path=runtime_path,
                catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
                setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
            )
            by_id = {item["fru_id"]: item for item in payload["diagnosis"]["candidates"]}

            self.assertGreater(by_id["io_board"]["matched_rule_count"], 0)
            self.assertEqual(by_id["speaker_module"]["matched_rule_count"], 0)

    def test_diagnosis_surfaces_non_fru_fault_origin(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "events": {
                            "total_warning_error_count": 2,
                            "network": {
                                "error_count": 1,
                                "warning_count": 1,
                                "samples": [
                                    {
                                        "provider": "Microsoft-Windows-NDIS",
                                        "message_excerpt": "driver stack service failed during NetworkAvailable trigger",
                                    }
                                ],
                            },
                        },
                        "device_inventory": {"problem_device_count": 0, "problem_devices": []},
                        "tests": {},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dashboard_payload(
                profile_path=PROJECT_ROOT / "configs" / "active_device.json",
                runtime_path=runtime_path,
                catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
                setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
            )

            summary = payload["diagnosis"]["summary"]
            self.assertEqual(summary["fault_origin"], "non_fru_fault")
            self.assertEqual(summary["replacement_recommendation"], "not_recommended")
            self.assertEqual(payload["diagnosis"]["top_candidates"][0]["candidate_type"], "non_fru_fault")

    def test_failed_active_test_still_prefers_replaceable_fru(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text(
                json.dumps(
                    {
                        "events": {
                            "total_warning_error_count": 1,
                            "network": {
                                "error_count": 1,
                                "warning_count": 0,
                                "samples": [{"message_excerpt": "driver stack failed"}],
                            },
                        },
                        "device_inventory": {"problem_device_count": 0, "problem_devices": []},
                        "tests": {"audio": {"left_right_speaker_result": "speaker_failed"}},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dashboard_payload(
                profile_path=PROJECT_ROOT / "configs" / "active_device.json",
                runtime_path=runtime_path,
                catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
                setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
            )

            summary = payload["diagnosis"]["summary"]
            self.assertEqual(payload["diagnosis"]["top_candidates"][0]["fru_id"], "speaker_module")
            self.assertEqual(summary["fault_origin"], "replaceable_fru")
            self.assertIn(summary["replacement_recommendation"], {"recommended", "recommended_after_confirmation"})

    def test_diagnosis_candidate_includes_serviceability(self):
        payload = build_dashboard_payload(
            profile_path=PROJECT_ROOT / "configs" / "active_device.json",
            runtime_path=PROJECT_ROOT / "data" / "runtime_info.json",
            catalog_path=PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json",
            setup_report_path=PROJECT_ROOT / "reports" / "fru_profile_setup_report.json",
        )
        by_id = {item["fru_id"]: item for item in payload["diagnosis"]["candidates"]}

        self.assertEqual(by_id["power_adapter"]["candidate_type"], "external_part")
        self.assertEqual(by_id["motherboard"]["candidate_type"], "serviceable_assembly")
        self.assertIn("serviceability", by_id["motherboard"])

    def test_summarize_event_buckets_preserves_rules_and_skips_metadata(self):
        events = {
            "total_warning_error_count": 2,
            "collection": {"mode": "fault_window"},
            "storage": {
                "error_count": 1,
                "warning_count": 0,
                "total_count": 1,
                "samples": [{"provider": "Disk"}],
                "rules": {"provider_patterns": ["Disk"]},
            },
        }

        buckets = summarize_event_buckets(events)

        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0]["name"], "storage")
        self.assertEqual(buckets[0]["rules"]["provider_patterns"], ["Disk"])

    def test_set_runtime_test_result_updates_nested_key(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text(
                json.dumps({"tests": {"power": {"adapter_detected": "not_run"}}}),
                encoding="utf-8",
            )

            runtime = set_runtime_test_result(
                "tests.power.adapter_detected", "passed", runtime_path
            )

            self.assertEqual(runtime["tests"]["power"]["adapter_detected"], "passed")

    def test_set_runtime_test_result_rejects_non_test_key(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime_path = Path(tmp_dir) / "runtime.json"
            runtime_path.write_text("{}", encoding="utf-8")

            with self.assertRaises(ValueError):
                set_runtime_test_result("battery.status", "passed", runtime_path)


if __name__ == "__main__":
    unittest.main()
