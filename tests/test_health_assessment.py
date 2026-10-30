import unittest

from fru_diagnosis.anomaly_detection import detect_anomalies
from fru_diagnosis.health_assessment import assess_device_health


class HealthAssessmentTests(unittest.TestCase):
    def test_low_event_noise_is_minor_and_not_blocking(self):
        runtime = {"events": {"total_warning_error_count": 4}, "device_inventory": {"problem_device_count": 0}}
        health = assess_device_health(runtime, detect_anomalies(runtime))

        self.assertEqual(health["health_level"], "minor")
        self.assertTrue(any(item["impact"] == "does_not_affect_operation" for item in health["items"]))
        self.assertEqual(health["maintenance_strategy"]["cadence"], "observe_next_24_to_72_hours")

    def test_storage_smart_signal_is_urgent(self):
        runtime = {"storage": {"smart": "disk failure predicted"}}
        health = assess_device_health(runtime, detect_anomalies(runtime))

        self.assertEqual(health["health_level"], "urgent")
        self.assertIn("backup_data_and_run_storage_diagnostics", health["maintenance_strategy"]["immediate_actions"])

    def test_failed_log_collection_is_not_treated_as_clear_logs(self):
        runtime = {
            "collection_status": {
                "logs.system": {"status": "failed", "error": "access denied"},
                "logs.application": {"status": "failed", "error": "access denied"},
            },
            "events": {"total_warning_error_count": 0},
            "device_inventory": {"problem_device_count": 0},
        }
        health = assess_device_health(runtime, detect_anomalies(runtime))

        item_ids = {item["id"] for item in health["items"]}
        self.assertIn("event_log_not_collected", item_ids)
        self.assertNotIn("event_log_clear", item_ids)
        self.assertIn("recollect_event_logs_with_required_permission", health["maintenance_strategy"]["routine_actions"])


if __name__ == "__main__":
    unittest.main()
