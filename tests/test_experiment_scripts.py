import tempfile
import unittest
from pathlib import Path

from experiments.evaluate_cases import evaluate
from experiments.run_baselines import (
    predict_graph_fusion,
    predict_log_template_tfidf,
    predict_rule_weighted,
    predict_reliability_gated_fusion,
    train_log_template_tfidf_models,
    train_reliability_gated_fusion_models,
)
from fru_diagnosis.datasets import DatasetCase, EvidenceBundle, Label, dump_cases_jsonl, load_cases_jsonl


class ExperimentScriptTests(unittest.TestCase):
    def test_rule_weighted_and_graph_fusion_predictions_are_evaluable(self):
        case = DatasetCase(
            case_id="case_001",
            source_dataset="unit",
            device_type="computer_system",
            symptom=("log_observation",),
            evidence=EvidenceBundle(
                logs={
                    "actionable_warning_error_count": 0,
                    "event_template_counts": {"session opened for user <*>": 3},
                    "noise_reduction": {"actionable_event_count": 0},
                }
            ),
            label=Label(
                fault_origin="no_fault_observed",
                target="none",
                serviceability_type="none",
            ),
            metadata={"dataset_key": "unit", "split": "test"},
        )

        rule_prediction = predict_rule_weighted(case)
        graph_prediction = predict_graph_fusion(case)

        self.assertEqual(rule_prediction["method"], "rule_weighted_baseline")
        self.assertEqual(graph_prediction["method"], "graph_fusion_baseline")
        self.assertIn("target_ranking", graph_prediction)

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "cases.jsonl"
            predicted = DatasetCase(
                case_id=case.case_id,
                source_dataset=case.source_dataset,
                device_type=case.device_type,
                symptom=case.symptom,
                evidence=case.evidence,
                label=case.label,
                metadata={**case.metadata, "prediction": graph_prediction},
            )
            dump_cases_jsonl([predicted], path)
            metrics = evaluate(load_cases_jsonl(path))

        self.assertEqual(metrics["predicted_count"], 1)
        self.assertEqual(metrics["target_macro_f1"], 1.0)
        self.assertEqual(metrics["boundary_accuracy"], 1.0)
        self.assertEqual(metrics["boundary_macro_f1"], 1.0)

    def test_log_template_tfidf_baseline_learns_from_training_cases(self):
        train_cases = [
            DatasetCase(
                case_id="train_os",
                source_dataset="unit",
                device_type="computer_system",
                evidence=EvidenceBundle(
                    logs={
                        "event_template_counts": {"service <*> failed while opening package": 3},
                        "event_template_sequence": ["service <*> failed while opening package"] * 3,
                    }
                ),
                label=Label(
                    fault_origin="non_fru_fault",
                    target="os_fault",
                    serviceability_type="non_fru_fault",
                ),
            ),
            DatasetCase(
                case_id="train_config",
                source_dataset="unit",
                device_type="computer_system",
                evidence=EvidenceBundle(
                    logs={
                        "event_template_counts": {"invalid configuration value <*>": 3},
                        "event_template_sequence": ["invalid configuration value <*>"] * 3,
                    }
                ),
                label=Label(
                    fault_origin="non_fru_fault",
                    target="firmware_or_config_fault",
                    serviceability_type="non_fru_fault",
                ),
            ),
        ]
        test_case = DatasetCase(
            case_id="test_config",
            source_dataset="unit",
            device_type="computer_system",
            evidence=EvidenceBundle(
                logs={
                    "event_template_counts": {"invalid configuration value <*>": 2},
                    "event_template_sequence": ["invalid configuration value <*>"] * 2,
                }
            ),
        )

        models = train_log_template_tfidf_models(train_cases)
        prediction = predict_log_template_tfidf(test_case, models)

        self.assertEqual(prediction["method"], "log_template_tfidf_centroid_baseline")
        self.assertEqual(prediction["target"], "firmware_or_config_fault")
        self.assertIn("firmware_or_config_fault", prediction["target_ranking"][:1])

    def test_graph_fusion_blocks_replacement_without_hardware_evidence(self):
        case = DatasetCase(
            case_id="case_log_only_power",
            source_dataset="unit",
            device_type="computer_system",
            symptom=("charging_failure",),
            evidence=EvidenceBundle(
                logs={
                    "actionable_warning_error_count": 2,
                    "event_template_counts": {
                        "power adapter disconnected from external outlet <*>": 2,
                    },
                    "event_template_sequence": [
                        "power adapter disconnected from external outlet <*>",
                        "power adapter disconnected from external outlet <*>",
                    ],
                }
            ),
        )

        prediction = predict_graph_fusion(case)

        self.assertEqual(prediction["target"], "external_environment_fault")
        self.assertEqual(prediction["fault_origin"], "non_fru_fault")
        self.assertFalse(prediction["replacement_recommended"])
        self.assertEqual(prediction["calibration"]["blocked_hardware_target"], "power_adapter")

    def test_graph_fusion_allows_replacement_with_active_test_evidence(self):
        case = DatasetCase(
            case_id="case_power_test_failed",
            source_dataset="unit",
            device_type="computer_system",
            symptom=("charging_failure",),
            evidence=EvidenceBundle(
                active_tests={
                    "power": {
                        "adapter_swap_result": "failed",
                    }
                }
            ),
        )

        prediction = predict_graph_fusion(case)

        self.assertEqual(prediction["target"], "power_adapter")
        self.assertEqual(prediction["fault_origin"], "replaceable_fru")
        self.assertTrue(prediction["replacement_recommended"])
        self.assertTrue(prediction["calibration"]["has_hardware_evidence"])

    def test_reliability_gated_fusion_returns_modality_weights(self):
        case = DatasetCase(
            case_id="fusion_case",
            source_dataset="unit",
            device_type="computer",
            fault_time="2026-01-01T00:00:00Z",
            evidence=EvidenceBundle(
                logs={"event_template_counts": {"driver <*> failed": 2}},
                metrics={"telemetry": {"row_count": 5, "whea": "error"}},
            ),
            label=Label(
                fault_origin="non_fru_fault",
                target="driver_or_os_fault",
                serviceability_type="non_fru_fault",
            ),
        )

        models = train_reliability_gated_fusion_models([case])
        prediction = predict_reliability_gated_fusion(case, models)

        self.assertEqual(prediction["method"], "reliability_gated_late_fusion")
        self.assertGreater(prediction["modality_weights"]["logs"], 0)
        self.assertIn("target_ranking", prediction)

    def test_evaluator_reports_active_test_utility(self):
        case = DatasetCase(
            case_id="active_eval",
            source_dataset="unit",
            device_type="computer",
            evidence=EvidenceBundle(logs={"message": "driver timeout"}),
            label=Label(
                fault_origin="non_fru_fault",
                target="driver_or_os_fault",
                serviceability_type="non_fru_fault",
            ),
            metadata={
                "expected_next_tests": ["collect_minidump"],
                "active_test_transition": {"realized_information_gain": 0.25},
                "prediction": {
                    "fault_origin": "non_fru_fault",
                    "target": "driver_or_os_fault",
                    "serviceability_type": "non_fru_fault",
                    "boundary_type": "software_side",
                    "next_tests": [
                        {
                            "id": "collect_minidump",
                            "boundary_expected_information_gain": 0.8,
                        }
                    ],
                },
            },
        )

        metrics = evaluate([case])

        self.assertEqual(metrics["active_test_hit_at_1"], 1.0)
        self.assertEqual(metrics["mean_recommended_information_gain"], 0.8)
        self.assertEqual(metrics["mean_realized_information_gain"], 0.25)


if __name__ == "__main__":
    unittest.main()
