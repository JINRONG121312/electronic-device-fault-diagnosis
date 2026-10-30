import unittest

from fru_diagnosis.remote_diagnosis import build_remote_diagnosis


class RemoteDiagnosisTests(unittest.TestCase):
    def test_customer_visible_bsod_description_creates_initial_classification(self):
        result = build_remote_diagnosis(
            {
                "manufacturer": "Lenovo",
                "model": "ThinkPad T14",
                "os_family": "windows",
                "description": "客户反馈电脑突然蓝屏死机，重启后还能进入系统。",
            },
            profile={"fru_list": []},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "remote_cross_machine_diagnosis")
        self.assertIn("bsod", result["intake"]["symptoms"])
        self.assertEqual(result["classification"]["task"], "fault_classification")
        self.assertNotEqual(result["classification"]["predicted_fault_class"], "hardware_fault")
        self.assertEqual(result["decision"]["task"], "decision_after_classification")
        self.assertEqual(result["remote_collection"]["scenario"], "diagnose_another_machine")
        plan = result["remote_collection"]["collection_plan"]
        self.assertTrue(plan["can_export_runtime"])
        self.assertIn("crash_dump", {group["id"] for group in plan["groups"]})

    def test_remote_runtime_json_is_used_as_cross_machine_evidence(self):
        result = build_remote_diagnosis(
            {
                "manufacturer": "Dell",
                "model": "Latitude",
                "os_family": "windows",
                "symptoms": ["no_network"],
                "runtime_info": '{"events":{"total_warning_error_count":1},"network":{"adapters":[{"name":"Wi-Fi"}]}}',
            },
            profile={"fru_list": []},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["intake"]["manufacturer"], "Dell")
        self.assertIn("base_actions", result["remote_collection"])
        self.assertIn("runtime_bundle", {group["id"] for group in result["remote_collection"]["collection_plan"]["groups"]})


if __name__ == "__main__":
    unittest.main()
