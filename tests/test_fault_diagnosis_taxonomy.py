import unittest

from fault_diagnosis import (
    FAULT_ORIGIN_TYPES,
    SERVICEABILITY_TYPES,
    build_fusion_candidates,
    classify_fault_case,
    classify_fault_origin,
    decide_after_classification,
    recommend_next_tests,
)


class FaultDiagnosisTaxonomyTests(unittest.TestCase):
    def test_taxonomy_contains_software_layer_faults(self):
        origin_ids = {item.id for item in FAULT_ORIGIN_TYPES}

        self.assertIn("driver_fault", origin_ids)
        self.assertIn("os_fault", origin_ids)
        self.assertIn("firmware_fault", origin_ids)
        self.assertIn("hardware_fault", origin_ids)

    def test_serviceability_keeps_replacement_as_output_not_main_origin(self):
        outcomes = {item.id: item for item in SERVICEABILITY_TYPES}

        self.assertFalse(outcomes["software_repairable"].replacement_oriented)
        self.assertTrue(outcomes["replaceable_hardware"].replacement_oriented)

    def test_legacy_candidate_types_map_to_fault_origin(self):
        self.assertEqual(classify_fault_origin("non_fru_fault", "driver_or_os"), "driver_fault")
        self.assertEqual(classify_fault_origin("replaceable_fru", "storage"), "hardware_fault")
        self.assertEqual(classify_fault_origin("non_fru_fault", "firmware_or_config"), "firmware_fault")

    def test_research_api_reexports_core_diagnosis_capabilities(self):
        report = {"top_candidates": [{"fru_id": "driver_or_os_fault"}]}

        self.assertEqual(recommend_next_tests(report, ["bsod"])[0]["id"], "collect_minidump")
        self.assertEqual(
            build_fusion_candidates(
                {
                    "candidates": [
                        {
                            "fru_id": "driver_or_os_fault",
                            "rank_score": 70,
                            "matched_evidence": [],
                            "negative_evidence": [],
                            "missing_evidence": [],
                        }
                    ]
                }
            )[0]["candidate"],
            "driver_or_os_fault",
        )

    def test_bsod_is_symptom_for_fault_classification_not_standalone_decision(self):
        classification = classify_fault_case(
            {
                "symptom": ["bsod"],
                "evidence": {
                    "crash_dump": {
                        "bugcheck": "VIDEO_TDR_FAILURE",
                        "probably_caused_by": "vendor_gpu_driver.sys",
                    }
                },
            }
        )
        decision = decide_after_classification(classification)

        self.assertEqual(classification["task"], "fault_classification")
        self.assertEqual(classification["predicted_fault_class"], "driver_fault")
        self.assertTrue(classification["decision_deferred"])
        self.assertEqual(decision["task"], "decision_after_classification")
        self.assertEqual(decision["fault_class"], "driver_fault")


if __name__ == "__main__":
    unittest.main()
