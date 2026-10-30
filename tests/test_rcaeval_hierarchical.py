import unittest

from experiments.run_rcaeval_formal_experiment import (
    evaluate_predictions,
    operation_target_service,
    predict_tracerca_reproduction,
    quantile,
    smoothed_compatibility,
)
from fru_diagnosis.datasets import DatasetCase, EvidenceBundle, Label


class HierarchicalRcaMetricTests(unittest.TestCase):
    def test_factorization_and_unseen_metrics_are_reported(self):
        case = DatasetCase(
            case_id="case-1",
            source_dataset="unit",
            device_type="microservice",
            evidence=EvidenceBundle(),
            label=Label(
                fault_origin="software_fault",
                target="checkoutservice:cpu",
                serviceability_type="software_fault",
                final_root_cause="checkoutservice:cpu",
            ),
            metadata={
                "prediction": {
                    "root_cause": "checkoutservice:cpu",
                    "root_cause_service_ranking": ["checkoutservice"],
                    "fault_type_ranking": ["cpu"],
                    "root_cause_ranking": ["checkoutservice:cpu"],
                    "root_cause_service": "checkoutservice",
                    "fault_type": "cpu",
                }
            },
        )

        metrics = evaluate_predictions([case], reference_roots={"frontend:delay"})

        self.assertEqual(metrics["factor_both_correct_rate"], 1.0)
        self.assertEqual(metrics["factor_service_only_correct_rate"], 0.0)
        self.assertEqual(metrics["unseen_root_top3_accuracy"], 1.0)
        self.assertEqual(metrics["root_top3_gain"], 0.0)

    def test_compatibility_is_smoothed_for_unseen_pairs(self):
        compatibility = {
            "pair_counts": {"frontend:delay": 3},
            "service_counts": {"frontend": 3},
            "fault_types": ["cpu", "delay", "mem"],
        }

        self.assertGreater(smoothed_compatibility("frontend", "cpu", compatibility), 0.0)
        self.assertGreater(smoothed_compatibility("frontend", "delay", compatibility), smoothed_compatibility("frontend", "cpu", compatibility))

    def test_literature_baseline_helpers_preserve_service_label_space(self):
        services = ["checkoutservice", "currencyservice", "recommendationservice"]

        target = operation_target_service(
            "hipstershop.CheckoutService/PlaceOrder",
            services,
        )

        self.assertEqual(target, "checkoutservice")
        self.assertEqual(quantile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)

    def test_tracerca_reproduction_ranks_failed_operation_target(self):
        case = DatasetCase(
            case_id="trace-case",
            source_dataset="unit",
            device_type="microservice",
            evidence=EvidenceBundle(
                traces={
                    "failed_span_count": 4,
                    "spans": [
                        {
                            "service_name": "frontendservice",
                            "operation": "hipstershop.CheckoutService/PlaceOrder",
                            "status_code": "14.0",
                            "count": 4,
                        }
                    ],
                }
            ),
        )

        prediction = predict_tracerca_reproduction(case, ["checkoutservice", "frontend"])

        self.assertEqual(prediction["root_cause_service"], "checkoutservice")
        self.assertEqual(prediction["fault_type"], "loss")


if __name__ == "__main__":
    unittest.main()
