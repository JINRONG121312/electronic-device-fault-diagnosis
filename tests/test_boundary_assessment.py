import unittest

from fru_diagnosis.boundary_assessment import assess_boundary, boundary_role_for_candidate


class BoundaryAssessmentTests(unittest.TestCase):
    def test_driver_logs_without_hardware_evidence_are_software_side(self):
        result = assess_boundary(
            {
                "events": {
                    "total_warning_error_count": 2,
                    "samples": [{"provider": "Service Control Manager", "message": "display driver service failed"}],
                }
            },
            {
                "predicted_fault_class": "driver_fault",
                "class_ranking": [{"fault_class": "driver_fault", "score": 0.7}],
            },
            [],
            ["bsod"],
        )

        self.assertEqual(result["boundary_type"], "software_side")

    def test_smart_whea_and_failed_active_test_are_hardware_side(self):
        result = assess_boundary(
            {
                "events": {"total_warning_error_count": 1, "samples": [{"message": "WHEA corrected hardware error"}]},
                "storage": {"smart": {"predicted_failure": True}},
                "tests": {"storage": {"short_test": "failed"}},
            },
            {
                "predicted_fault_class": "hardware_fault",
                "class_ranking": [{"fault_class": "hardware_fault", "score": 0.75}],
            },
            [{"fru_id": "storage_fru", "candidate_type": "replaceable_fru", "status": "suspect"}],
            ["slow_io"],
        )

        self.assertEqual(result["boundary_type"], "hardware_side")

    def test_driver_and_whea_context_is_boundary(self):
        result = assess_boundary(
            {
                "events": {
                    "total_warning_error_count": 3,
                    "samples": [{"message": "GPU driver timeout followed by WHEA PCIe error"}],
                },
                "device_inventory": {"problem_device_count": 1},
                "crash_dump": {"bugcheck": "VIDEO_TDR_FAILURE"},
            },
            {
                "predicted_fault_class": "driver_fault",
                "class_ranking": [
                    {"fault_class": "driver_fault", "score": 0.55},
                    {"fault_class": "hardware_fault", "score": 0.4},
                ],
            },
            [{"fru_id": "display_panel_module", "candidate_type": "replaceable_fru", "status": "possible"}],
            ["bsod"],
        )

        self.assertEqual(result["boundary_type"], "hardware_software_boundary")
        self.assertIn("boundary", result["scores"])

    def test_only_symptom_is_uncertain(self):
        result = assess_boundary({}, {"predicted_fault_class": "mixed_or_uncertain", "class_ranking": []}, [], ["bsod"])

        self.assertEqual(result["boundary_type"], "mixed_or_uncertain")
        self.assertLess(result["confidence"], 0.5)

    def test_candidate_boundary_roles_are_stable(self):
        self.assertEqual(
            boundary_role_for_candidate({"candidate_type": "non_fru_fault", "fru_id": "driver_or_os_fault"})[0],
            "software_side",
        )
        self.assertEqual(
            boundary_role_for_candidate({"candidate_type": "replaceable_fru", "fru_id": "storage_fru"})[0],
            "hardware_endpoint",
        )

    def test_explicit_boundary_roles_and_quality_are_exposed(self):
        result = assess_boundary(
            {
                "logs": {"message": "driver timeout"},
                "metrics": {"pcie": "link down"},
                "quality": {"logs": 0.25, "metrics": 0.9},
                "boundary": {"scores": {"interface_path": 0.9}},
            },
            {"predicted_fault_class": "driver_fault", "class_ranking": []},
            [],
            ["black_screen"],
        )

        self.assertIn("posterior", result)
        self.assertEqual(result["source_quality"]["metrics"], 0.9)
        self.assertGreater(result["posterior"]["interface_path"], 0)


if __name__ == "__main__":
    unittest.main()
