import unittest

from fru_diagnosis.remote_agent_client import evidence_package_to_runtime_info


class RemoteAgentClientTests(unittest.TestCase):
    def test_evidence_package_maps_to_runtime_info_contract(self):
        package = {
            "timestamp": "2026-05-18T10:00:00",
            "fault_case_id": "case-1",
            "symptom": ["bsod"],
            "evidence": {
                "inventory": {
                    "system": {"model": "ThinkPad"},
                    "device_inventory": {"problem_device_count": 1},
                },
                "logs": {"total_warning_error_count": 2},
                "metrics": {
                    "storage": {"smart_warning": True},
                    "battery": {"charge": 80},
                    "network": {"adapters": []},
                },
                "active_tests": {"display": {"external_monitor": "passed"}},
                "crash_dump": {"bugcheck": "WHEA_UNCORRECTABLE_ERROR"},
            },
        }

        runtime = evidence_package_to_runtime_info(package)

        self.assertEqual(runtime["system"]["model"], "ThinkPad")
        self.assertEqual(runtime["device_inventory"]["problem_device_count"], 1)
        self.assertEqual(runtime["events"]["total_warning_error_count"], 2)
        self.assertTrue(runtime["storage"]["smart_warning"])
        self.assertEqual(runtime["tests"]["display"]["external_monitor"], "passed")
        self.assertEqual(runtime["crash_dump"]["bugcheck"], "WHEA_UNCORRECTABLE_ERROR")
        self.assertTrue(runtime["crash_dump"]["available"])
        self.assertEqual(runtime["crash_dump"]["source"], "target_agent")

    def test_runtime_info_passthrough_is_preserved(self):
        package = {"runtime_info": {"system": {"hostname": "target"}}}

        runtime = evidence_package_to_runtime_info(package)

        self.assertEqual(runtime["system"], {"hostname": "target"})
        self.assertEqual(runtime["crash_dump"]["available"], False)

    def test_runtime_info_passthrough_normalizes_missing_crash_dump(self):
        package = {"runtime_info": {"system": {"hostname": "target"}, "crash_dump": {"available": False}}}

        runtime = evidence_package_to_runtime_info(package)

        self.assertEqual(runtime["crash_dump"]["available"], False)
        self.assertEqual(runtime["crash_dump"]["source"], "target_agent")
        self.assertEqual(runtime["crash_dump"]["next_action"], "enable_dump_or_collect_offline_evidence")


if __name__ == "__main__":
    unittest.main()
