import unittest

from fru_diagnosis.active_diagnosis import recommend_next_tests, run_active_test_update
from fru_diagnosis.crash_diagnosis import diagnose_crash_dump
from fru_diagnosis.datasets import Label, case_from_runtime_info
from fru_diagnosis.evidence_fusion import (
    build_fusion_candidates,
    combine_beliefs_dempster_shafer,
)


class ResearchLayerTests(unittest.TestCase):
    def test_case_from_runtime_info_preserves_research_fields(self):
        runtime = {
            "generated_at": "2026-05-15T10:00:00",
            "system": {"manufacturer": "LENOVO", "model": "81YL"},
            "events": {"collection": {"fault_time": "2026-05-15T09:00:00"}},
        }
        label = Label(
            fault_origin="non_fru_fault",
            target="driver_or_os_fault",
            serviceability_type="non_fru_fault",
            final_root_cause="driver_stack_failure",
        )

        case = case_from_runtime_info(runtime, case_id="case_1", symptom=["bsod"], label=label)

        self.assertEqual(case.fault_case_id, "case_1")
        self.assertEqual(case.fault_time, "2026-05-15T09:00:00")
        self.assertIn("LENOVO", case.device_id)
        self.assertEqual(case.label.final_root_cause, "driver_stack_failure")

    def test_evidence_fusion_outputs_belief_uncertainty(self):
        report = {
            "candidates": [
                {
                    "fru_id": "driver_or_os_fault",
                    "candidate_type": "non_fru_fault",
                    "rank_score": 70,
                    "matched_evidence": [{"rule_id": "driver"}],
                    "negative_evidence": [],
                    "missing_evidence": [],
                    "next_actions": [{"key": "collect_minidump"}],
                }
            ]
        }

        fused = build_fusion_candidates(report)

        self.assertEqual(fused[0]["candidate"], "driver_or_os_fault")
        self.assertGreater(fused[0]["belief"], 0.6)
        self.assertIn("uncertainty", fused[0])

    def test_dempster_shafer_combiner(self):
        combined = combine_beliefs_dempster_shafer(
            [
                {"support": 0.7, "against": 0.1, "uncertain": 0.2},
                {"support": 0.6, "against": 0.1, "uncertain": 0.3},
            ]
        )

        self.assertGreater(combined["support"], combined["against"])

    def test_low_source_quality_increases_fusion_uncertainty(self):
        base = {
            "fru_id": "driver_or_os_fault",
            "candidate_type": "non_fru_fault",
            "rank_score": 70,
            "matched_evidence": [{"rule_id": "driver"}],
            "negative_evidence": [],
            "missing_evidence": [],
        }
        high = build_fusion_candidates({"candidates": [base]})[0]
        low_candidate = dict(base, source_quality={"logs": 0.2, "graph": 0.2})
        low = build_fusion_candidates({"candidates": [low_candidate]})[0]

        self.assertGreater(low["uncertainty"], high["uncertainty"])

    def test_active_diagnosis_recommends_minidump_for_bsod(self):
        report = {"top_candidates": [{"fru_id": "driver_or_os_fault"}]}

        tests = recommend_next_tests(report, ["bsod"])

        self.assertEqual(tests[0]["id"], "collect_minidump")

    def test_active_diagnosis_skips_completed_test(self):
        report = {"top_candidates": [{"fru_id": "wlan_module"}]}
        tests = recommend_next_tests(
            report,
            ["no_network"],
            completed_tests={"gateway_ping_and_driver_check"},
        )

        self.assertNotIn("gateway_ping_and_driver_check", {item["id"] for item in tests})

    def test_active_test_result_recomputes_boundary_posterior(self):
        runtime = {"events": {"samples": [{"message": "display driver timeout"}]}}
        classification = {
            "predicted_fault_class": "driver_fault",
            "class_ranking": [{"fault_class": "driver_fault", "score": 0.7}],
        }

        result = run_active_test_update(
            runtime,
            classification,
            [{"fru_id": "memory_subsystem", "candidate_type": "replaceable_fru", "status": "possible"}],
            ["bsod"],
            "run_memory_extended_test",
            "failed",
        )

        self.assertEqual(
            result["runtime"]["tests"]["active_diagnosis"]["run_memory_extended_test"]["status"],
            "failed",
        )
        self.assertGreater(result["transition"]["posterior_shift"], 0)

    def test_crash_diagnosis_maps_bugcheck(self):
        result = diagnose_crash_dump({"bugcheck": "MEMORY_MANAGEMENT"})

        self.assertEqual(result["status"], "mapped")
        self.assertIn("memory_subsystem", {item["candidate"] for item in result["candidates"]})

    def test_crash_diagnosis_prefers_third_party_driver(self):
        result = diagnose_crash_dump(
            {
                "bugcheck": "VIDEO_TDR_FAILURE",
                "probably_caused_by": "vendor_gpu_driver.sys",
            }
        )

        self.assertEqual(result["candidates"][0]["candidate"], "driver_or_os_fault")


if __name__ == "__main__":
    unittest.main()
