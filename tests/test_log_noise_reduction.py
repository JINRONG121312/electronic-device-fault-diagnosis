import re
import unittest

from fru_diagnosis.anomaly_detection import detect_anomalies
from fru_diagnosis.health_assessment import assess_device_health
from fru_diagnosis.log_noise_reduction import (
    build_log_noise_profile,
    event_bucket_actionable_count,
    runtime_actionable_event_count,
)


class LogNoiseReductionTests(unittest.TestCase):
    def test_recoverable_error_is_suppressed_as_anti_event(self):
        profile = build_log_noise_profile(
            [
                {"message": "Update retry succeeded after transient error; ignoring"},
                {"message": "Update retry succeeded after transient error; ignoring"},
            ]
        )

        self.assertEqual(profile["actionable_event_count"], 0)
        self.assertEqual(profile["anti_event_count"], 2)

    def test_repeated_rule_relevant_warning_is_compressed(self):
        samples = [
            {
                "provider": "Microsoft-Windows-Kernel-Processor-Power",
                "event_id": 37,
                "level": "Warning",
                "message_excerpt": f"Processor {index} speed is limited by system firmware.",
            }
            for index in range(8)
        ]
        bucket = {
            "warning_count": 8,
            "total_count": 8,
            "samples": samples,
            "rules": {
                "provider_patterns": ["Kernel-Processor-Power"],
                "message_patterns": ["firmware", "thermal"],
            },
        }

        self.assertEqual(event_bucket_actionable_count("thermal", bucket), 1)
        self.assertEqual(runtime_actionable_event_count({"thermal": bucket}), 1)

    def test_severe_log_term_is_retained(self):
        profile = build_log_noise_profile([{"message": "kernel panic: uncorrectable machine check"}])

        self.assertEqual(profile["actionable_event_count"], 1)
        self.assertEqual(profile["retained_templates"][0]["event_type"], "key_event")

    def test_anomaly_and_health_use_actionable_count(self):
        runtime = {
            "events": {
                "total_warning_error_count": 8,
                "thermal": {
                    "warning_count": 8,
                    "total_count": 8,
                    "samples": [
                        {
                            "provider": "Microsoft-Windows-Kernel-Processor-Power",
                            "event_id": 37,
                            "level": "Warning",
                            "message_excerpt": f"Processor {index} speed is limited by system firmware.",
                        }
                        for index in range(8)
                    ],
                    "rules": {
                        "provider_patterns": ["Kernel-Processor-Power"],
                        "message_patterns": ["firmware"],
                    },
                },
            }
        }

        anomaly = detect_anomalies(runtime)
        health = assess_device_health(runtime, anomaly)

        self.assertEqual(anomaly["observations"][0]["value"], 1)
        self.assertEqual(anomaly["observations"][0]["raw_value"], 8)
        self.assertIn("low_event_noise", {item["id"] for item in health["items"]})

    def test_non_matching_duplicate_warning_does_not_become_actionable(self):
        profile = build_log_noise_profile(
            [{"message": "connection from 10.0.0.1 at 00:00:00", "level": "Warning"} for _ in range(10)],
            rule_patterns=[re.compile("disk", re.IGNORECASE)],
        )

        self.assertEqual(profile["actionable_event_count"], 0)
        self.assertGreaterEqual(profile["ordinary_event_count"], 10)


if __name__ == "__main__":
    unittest.main()
