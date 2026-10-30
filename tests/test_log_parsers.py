import unittest

from fru_diagnosis.datasets import DatasetCase, EvidenceBundle
from fru_diagnosis.diagnostic_graph import build_diagnostic_graph_from_case
from fru_diagnosis.log_parsers import available_log_parsers, enrich_log_evidence, parse_logs
from scripts.prepare_loghub2k_diagnosis_dataset import window_to_case


class LogParserIntegrationTests(unittest.TestCase):
    def test_registry_exposes_source_and_drain(self):
        self.assertIn("source", available_log_parsers())
        self.assertIn("drain", available_log_parsers())

    def test_drain_groups_numeric_variants_into_one_template(self):
        result = parse_logs(
            [
                "disk 0 failed on port 1",
                "disk 1 failed on port 2",
                "network link is up",
            ],
            parser_name="drain",
        )

        self.assertEqual(result.method, "drain")
        self.assertEqual(result.event_template_counts["disk <*> failed on port <*>"], 2)
        self.assertEqual(result.event_template_counts["network link is up"], 1)
        self.assertEqual(len(result.event_id_sequence), 3)

    def test_enrich_log_evidence_parses_raw_messages(self):
        enriched = enrich_log_evidence(
            {
                "raw_messages": [
                    "driver module 123 failed",
                    "driver module 456 failed",
                ],
                "actionable_warning_error_count": 2,
            },
            parser_name="drain",
        )

        self.assertEqual(enriched["log_parser"]["method"], "drain")
        self.assertEqual(enriched["event_template_counts"]["driver module <*> failed"], 2)
        self.assertEqual(len(enriched["parsed_events"]), 2)

    def test_graph_uses_drain_when_only_raw_messages_are_available(self):
        case = DatasetCase(
            case_id="raw-log-case",
            source_dataset="unit",
            device_type="computer",
            evidence=EvidenceBundle(
                logs={
                    "raw_messages": ["driver module 123 failed"],
                    "actionable_warning_error_count": 1,
                }
            ),
        )

        graph = build_diagnostic_graph_from_case(case)
        log_nodes = [node for node in graph["nodes"] if node["type"] == "log_template"]

        self.assertTrue(any("driver module" in node["label"] for node in log_nodes))
        self.assertTrue(any(edge["type"] == "supports_candidate" for edge in graph["edges"]))

    def test_loghub2_window_can_use_drain_parser(self):
        case = window_to_case(
            "Apache",
            0,
            [
                {
                    "LineId": "1",
                    "Content": "client 10.0.0.1 request failed with code 500",
                    "EventId": "source1",
                    "EventTemplate": "source template one",
                    "Level": "error",
                },
                {
                    "LineId": "2",
                    "Content": "client 10.0.0.2 request failed with code 503",
                    "EventId": "source2",
                    "EventTemplate": "source template two",
                    "Level": "error",
                },
            ],
            log_parser="drain",
        )

        logs = case.evidence.logs
        self.assertEqual(logs["log_parser"]["method"], "drain")
        self.assertIn("client <*> request failed with code <*>", logs["event_template_counts"])
        self.assertEqual(case.metadata["log_parser"], "drain")


if __name__ == "__main__":
    unittest.main()

