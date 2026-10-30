import unittest

from fru_diagnosis.anomaly_detection import detect_anomalies
from fru_diagnosis.diagnostic_workflow import (
    CROSS_MACHINE_INTERFACE,
    CROSS_MACHINE_POWER_OFF,
    CROSS_MACHINE_REMOTE,
    SELF_DETECTION,
    run_diagnostic_workflow,
)


class DiagnosticWorkflowTests(unittest.TestCase):
    def test_self_detection_runs_anomaly_classification_decision(self):
        runtime = {
            "events": {"total_warning_error_count": 2},
            "device_inventory": {"problem_device_count": 1},
        }

        result = run_diagnostic_workflow(
            SELF_DETECTION,
            {"symptoms": ["no_network"]},
            profile={"fru_list": []},
            runtime=runtime,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], SELF_DETECTION)
        self.assertEqual(result["anomaly_detection"]["task"], "anomaly_detection")
        self.assertEqual(result["anomaly_detection"]["status"], "abnormal")
        self.assertEqual(result["health_assessment"]["task"], "health_assessment")
        self.assertIn(result["health_assessment"]["health_level"], {"minor", "diagnose", "urgent"})
        self.assertIn("maintenance_strategy", result["health_assessment"])
        self.assertEqual(result["classification"]["task"], "fault_classification")
        self.assertEqual(result["boundary_assessment"]["task"], "boundary_assessment")
        self.assertEqual(result["decision"]["task"], "decision_after_classification")
        self.assertIn("diagnostic_graph", result)
        self.assertIn("graph_inference", result)
        self.assertIn("active_diagnosis", result)
        self.assertEqual(
            result["active_diagnosis"]["method"],
            "boundary_aware_information_gain_per_cost",
        )
        self.assertGreater(len(result["diagnostic_graph"].get("nodes", [])), 0)
        self.assertGreater(len(result["graph_inference"].get("candidate_ranking", [])), 0)
        self.assertEqual([step["step"] for step in result["pipeline"]], [
            "anomaly_detection",
            "fault_classification",
            "boundary_assessment",
            "fault_decision",
        ])

    def test_self_detection_can_report_healthy_state(self):
        result = run_diagnostic_workflow(
            "self",
            {},
            profile={"fru_list": []},
            runtime={"system": {"model": "healthy-machine"}},
        )

        self.assertEqual(result["system_health"]["level"], "healthy")
        self.assertEqual(result["health_assessment"]["health_level"], "healthy")
        self.assertEqual(result["anomaly_detection"]["status"], "normal")
        self.assertEqual(result["decision"]["decision"], "monitor_or_routine_maintenance")

    def test_cross_machine_remote_guidance_uses_prior_knowledge_path(self):
        result = run_diagnostic_workflow(
            CROSS_MACHINE_REMOTE,
            {"description": "blue screen after display driver update", "os_family": "windows"},
            profile={"fru_list": []},
        )

        self.assertEqual(result["scenario"]["id"], CROSS_MACHINE_REMOTE)
        self.assertEqual(result["guidance"]["primary_goal"], "remote_guidance_from_description_and_prior_knowledge")
        self.assertIn("llm_extension_point", result["guidance"])
        self.assertIn("bsod", result["intake"]["symptoms"])

    def test_cross_machine_interface_guidance_collects_evidence_via_interface(self):
        result = run_diagnostic_workflow(
            CROSS_MACHINE_INTERFACE,
            {"runtime_info": {"events": {"total_warning_error_count": 1}}},
            profile={"fru_list": []},
        )

        self.assertEqual(result["mode"], CROSS_MACHINE_INTERFACE)
        self.assertIn("boundary_assessment", result)
        self.assertIn("diagnostic_graph", result)
        self.assertIn("graph_inference", result)
        self.assertGreater(len(result["diagnostic_graph"].get("nodes", [])), 0)
        self.assertEqual(result["guidance"]["primary_goal"], "collect_evidence_from_fault_machine_via_interface")
        self.assertTrue(result["guidance"]["collection_plan"]["can_export_runtime"])
        self.assertIn("runtime_bundle", {group["id"] for group in result["guidance"]["collection_plan"]["groups"]})

    def test_cross_machine_power_off_guidance_prioritizes_field_observation(self):
        result = run_diagnostic_workflow(
            CROSS_MACHINE_POWER_OFF,
            {"description": "machine has no power and cannot boot"},
            profile={"fru_list": []},
        )

        self.assertEqual(result["mode"], CROSS_MACHINE_POWER_OFF)
        self.assertEqual(result["guidance"]["primary_goal"], "onsite_guidance_when_fault_machine_cannot_boot_or_power_on")
        self.assertIn("replacement_guidance", result["guidance"])
        self.assertFalse(result["guidance"]["collection_plan"]["can_export_runtime"])
        self.assertIn("field_observation", {group["id"] for group in result["guidance"]["collection_plan"]["groups"]})

    def test_cross_machine_offline_guidance_imports_crash_evidence(self):
        result = run_diagnostic_workflow(
            "cross_machine_offline",
            {
                "os_family": "windows",
                "symptoms": ["bsod"],
                "runtime_info": {
                    "crash_dump": {
                        "available": False,
                        "reason": "dump_not_found_or_machine_unavailable",
                    }
                },
            },
            profile={"fru_list": []},
        )

        self.assertEqual(result["mode"], "cross_machine_offline")
        self.assertEqual(result["scenario"]["id"], "cross_machine_offline")
        self.assertEqual(result["guidance"]["primary_goal"], "diagnose_from_offline_evidence_exported_from_fault_machine")
        self.assertIn("offline_crash_evidence", {group["id"] for group in result["guidance"]["collection_plan"]["groups"]})

    def test_anomaly_detection_detects_failed_active_test(self):
        result = detect_anomalies({"tests": {"display": {"external_monitor": "failed"}}})

        self.assertEqual(result["status"], "abnormal")
        self.assertIn("active_test_failed", {item["id"] for item in result["observations"]})

    def test_anomaly_detection_reports_incomplete_collection(self):
        result = detect_anomalies(
            {
                "collection_status": {
                    "logs.system": {"status": "failed", "error": "access denied"},
                }
            }
        )

        self.assertEqual(result["status"], "abnormal")
        self.assertIn("collection_incomplete", {item["id"] for item in result["observations"]})
        self.assertIn("mixed_or_uncertain", result["fault_hints"])

    def test_unavailable_crash_dump_does_not_count_as_present(self):
        result = detect_anomalies(
            {
                "crash_dump": {
                    "available": False,
                    "source": "unavailable",
                    "reason": "dump_not_found_or_machine_unavailable",
                }
            }
        )

        self.assertNotIn("crash_dump_present", {item["id"] for item in result["observations"]})


if __name__ == "__main__":
    unittest.main()
