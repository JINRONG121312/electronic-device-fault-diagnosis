import unittest

from fru_diagnosis.diagnosis_engine import build_diagnosis_report
from fru_diagnosis.diagnostic_graph import build_diagnostic_graph
from fru_diagnosis.datasets import DatasetCase, EvidenceBundle
from fru_diagnosis.diagnostic_graph import build_diagnostic_graph_from_case
from fru_diagnosis.graph_inference import infer_diagnostic_graph


class GraphDiagnosisTests(unittest.TestCase):
    def test_log_event_propagates_to_non_fru_candidate_and_fault_class(self):
        graph = build_diagnostic_graph(
            {"fru_list": []},
            {
                "events": {
                    "network": {
                        "error_count": 1,
                        "warning_count": 0,
                        "total_count": 1,
                        "samples": [
                            {
                                "provider": "Microsoft-Windows-NDIS",
                                "message_excerpt": "driver stack service failed during NetworkAvailable trigger",
                            }
                        ],
                    }
                }
            },
        )

        result = infer_diagnostic_graph(graph)
        candidates = {item["id"]: item for item in result["candidate_ranking"]}
        faults = {item["id"]: item for item in result["fault_ranking"]}

        self.assertIn("driver_or_os_fault", candidates)
        self.assertGreater(candidates["driver_or_os_fault"]["support"], 0)
        self.assertIn("driver_fault", faults)

    def test_failed_active_test_supports_specific_fru(self):
        graph = build_diagnostic_graph(
            {
                "fru_list": [
                    {
                        "id": "speaker_module",
                        "name": "Speaker",
                        "category": "AudioFRU",
                        "replaceable": True,
                        "diagnosis_role": "target_fru",
                    }
                ]
            },
            {"tests": {"audio": {"left_right_speaker_result": "speaker_failed"}}},
        )

        result = infer_diagnostic_graph(graph)
        candidates = {item["id"]: item for item in result["candidate_ranking"]}

        self.assertIn("speaker_module", candidates)
        self.assertGreaterEqual(candidates["speaker_module"]["support"], 0.9)

    def test_diagnosis_report_exposes_graph_outputs(self):
        report = build_diagnosis_report(
            {
                "fru_list": [
                    {
                        "id": "speaker_module",
                        "name": "Speaker",
                        "category": "AudioFRU",
                        "replaceable": True,
                        "diagnosis_role": "target_fru",
                        "evidence_rules": [
                            {
                                "id": "speaker_test",
                                "evidence_type": "active_test",
                                "source": "audio",
                                "pattern": "speaker_failed",
                                "weight": 1.0,
                            }
                        ],
                    }
                ]
            },
            {"tests": {"audio": {"left_right_speaker_result": "speaker_failed"}}},
        )

        self.assertEqual(report["method"]["name"], "heterogeneous_graph_fused_fault_diagnosis")
        self.assertIn("diagnostic_graph", report)
        self.assertIn("graph_inference", report)
        self.assertEqual(report["top_candidates"][0]["fru_id"], "speaker_module")
        self.assertGreater(report["top_candidates"][0]["graph_score"], 0)

    def test_failed_trace_span_is_available_to_graph_inference(self):
        case = DatasetCase(
            case_id="trace_case",
            source_dataset="unit",
            device_type="microservice_system",
            evidence=EvidenceBundle(
                traces={
                    "spans": [
                        {
                            "service_name": "checkout",
                            "status_code": "500",
                            "message": "request failed due to socket timeout",
                        }
                    ]
                }
            ),
        )

        graph = build_diagnostic_graph_from_case(case)
        result = infer_diagnostic_graph(graph)

        self.assertTrue(any(node["type"] == "trace_span" for node in graph["nodes"]))
        faults = {item["id"]: item for item in result["fault_ranking"]}
        self.assertGreater(faults["os_fault"]["support"], 0)


if __name__ == "__main__":
    unittest.main()
