import unittest

from scripts.validate_diagnosis_dataset import validate_boundary_readiness


def boundary_case(case_id, boundary_type, evidence, confidence="silver"):
    return {
        "case_id": case_id,
        "evidence": evidence,
        "label": {
            "boundary_type": boundary_type,
            "confidence": confidence,
        },
        "metadata": {"split": "test"},
    }


class BoundaryDatasetValidationTests(unittest.TestCase):
    def test_boundary_profile_accepts_confirmed_class_coverage(self):
        cases = []
        for index in range(3):
            cases.extend(
                [
                    boundary_case(
                        f"software_{index}",
                        "software_side",
                        {"logs": {"message": "driver failure"}},
                    ),
                    boundary_case(
                        f"interface_{index}",
                        "interface_path",
                        {"metrics": {"pcie": "link down"}},
                    ),
                    boundary_case(
                        f"hardware_{index}",
                        "hardware_endpoint",
                        {"active_tests": {"memory": "failed"}},
                    ),
                ]
            )
        errors = []
        warnings = []

        readiness = validate_boundary_readiness(cases, {"test": cases}, errors, warnings)

        self.assertEqual(errors, [])
        self.assertTrue(readiness["ready"])

    def test_boundary_profile_rejects_software_only_dataset(self):
        cases = [
            boundary_case(
                "software_only",
                "software_side",
                {"logs": {"message": "service timeout"}},
            )
        ]
        errors = []
        warnings = []

        readiness = validate_boundary_readiness(cases, {"test": cases}, errors, warnings)

        self.assertFalse(readiness["ready"])
        self.assertTrue(any("missing required classes" in item for item in errors))


if __name__ == "__main__":
    unittest.main()

