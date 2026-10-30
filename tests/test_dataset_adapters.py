import tempfile
import unittest
from pathlib import Path

from fru_diagnosis.datasets import DatasetCase, EvidenceBundle, Label, dump_cases_jsonl, enrich_case, load_cases_jsonl
from fru_diagnosis.datasets.adapters import (
    iter_backblaze_cases,
    iter_gaia_cases,
    iter_loghub_cases,
    iter_openrepair_cases,
    iter_rcaeval_cases,
)


class DatasetAdapterTests(unittest.TestCase):
    def test_backblaze_adapter_maps_failure_to_storage_fru(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "backblaze.csv"
            path.write_text(
                "date,serial_number,model,capacity_bytes,failure,smart_5_raw\n"
                "2026-01-01,S1,Drive A,1000,1,12\n",
                encoding="utf-8",
            )

            case = list(iter_backblaze_cases(path))[0]

            self.assertEqual(case.label.fault_origin, "replaceable_fru")
            self.assertEqual(case.label.target, "storage_fru")
            self.assertEqual(case.evidence.metrics["storage_smart"]["smart_5_raw"], 12)

    def test_loghub_adapter_maps_error_to_non_fru_fault(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "logs.csv"
            path.write_text(
                "Content,Label\n"
                "driver failed to initialize,Anomaly\n",
                encoding="utf-8",
            )

            case = list(iter_loghub_cases(path, dataset_name="sample_loghub"))[0]

            self.assertEqual(case.label.fault_origin, "non_fru_fault")
            self.assertEqual(case.label.target, "driver_or_os_fault")

    def test_openrepair_adapter_maps_battery_repair(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "repair.csv"
            path.write_text(
                "product,problem,repair,outcome\n"
                "Laptop,battery will not charge,replaced battery,fixed\n",
                encoding="utf-8",
            )

            case = list(iter_openrepair_cases(path))[0]

            self.assertEqual(case.device_type, "computer")
            self.assertEqual(case.label.target, "battery_pack")
            self.assertTrue(case.label.fixed)

    def test_rcaeval_adapter_preserves_metrics_logs_and_traces(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            case_dir = root / "re2_checkout_cpu_1"
            case_dir.mkdir()
            (case_dir / "metrics.json").write_text('{"cpu": [1, 2]}', encoding="utf-8")
            (case_dir / "inject_time.txt").write_text("1700000000", encoding="utf-8")
            (case_dir / "logs.csv").write_text("time,message\n1,service error\n", encoding="utf-8")
            (case_dir / "traces.csv").write_text("timestamp,status_code,message\n1,500,request failed\n", encoding="utf-8")

            case = list(iter_rcaeval_cases(root, preserve_raw_records=True))[0]

            self.assertEqual(case.label.target, "service_runtime_fault")
            self.assertEqual(case.label.final_root_cause, "checkout:cpu")
            self.assertEqual(case.evidence.metrics["telemetry"]["cpu"], [1, 2])
            self.assertEqual(case.evidence.logs["records"][0]["message"], "service error")
            self.assertEqual(case.evidence.traces["spans"][0]["status_code"], "500")

    def test_rcaeval_adapter_handles_service_fault_suffix_and_bounded_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            case_dir = root / "RE3-TT" / "ts-route-service_f3_1" / "1"
            case_dir.mkdir(parents=True)
            (case_dir / "metrics.csv").write_text(
                "time,m_a,m_b\n1,1,2\n",
                encoding="utf-8",
            )
            (case_dir / "logs.csv").write_text(
                "message\nerror 100\nerror 101\n",
                encoding="utf-8",
            )
            (case_dir / "traces.csv").write_text(
                "status_code,service_name,operation_name\n500,route,GetRoute\n500,route,GetRoute\n",
                encoding="utf-8",
            )

            case = list(iter_rcaeval_cases(root))[0]

            self.assertEqual(case.metadata["benchmark"], "re3-tt")
            self.assertEqual(case.label.final_root_cause, "ts-route-service:f3")
            self.assertEqual(case.metadata["instance"], "1_1")
            self.assertEqual(case.metadata["split_group"], "re3-tt|ts-route-service|f3")
            self.assertEqual(case.metadata["split_stratum"], "re3-tt|f3")
            self.assertEqual(case.evidence.logs["event_template_count"], 1)
            self.assertEqual(case.evidence.traces["failed_span_count"], 2)
            self.assertEqual(case.evidence.traces["spans"][0]["count"], 2)

    def test_rcaeval_adapter_skips_re2_auxiliary_multi_source_data(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            valid_dir = root / "RE2-OB" / "checkoutservice_cpu" / "1"
            auxiliary_dir = root / "RE2-OB" / "checkoutservice_cpu" / "multi-source-data"
            for case_dir in (valid_dir, auxiliary_dir):
                case_dir.mkdir(parents=True)
                (case_dir / "metrics.csv").write_text("time,cpu\n1,2\n", encoding="utf-8")
                (case_dir / "logs.csv").write_text("message\nok\n", encoding="utf-8")
                (case_dir / "traces.csv").write_text(
                    "status_code,service_name\n0,checkoutservice\n",
                    encoding="utf-8",
                )

            cases = list(iter_rcaeval_cases(root))

            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].metadata["benchmark"], "re2-ob")
            self.assertEqual(cases[0].metadata["instance"], "1")

    def test_gaia_adapter_maps_injection_record_to_case(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            run_dir = root / "MicroSS" / "run"
            run_dir.mkdir(parents=True)
            (root / "MicroSS" / "metric").mkdir()
            (root / "MicroSS" / "trace").mkdir()
            run_file = run_dir / "injections.csv"
            run_file.write_text(
                "datetime,service,message\n"
                "2021-07-01 10:00:00,dbservice1,[memory_anomalies] trigger a high memory program, start at 2021-07-01 10:00:00\n",
                encoding="utf-8",
            )

            case = list(iter_gaia_cases(root))[0]

            self.assertEqual(case.label.target, "service_runtime_fault")
            self.assertEqual(case.label.final_root_cause, "dbservice1:memory_anomalies")
            self.assertTrue(case.evidence.metrics["source_available"])
            self.assertTrue(case.evidence.traces["source_available"])

    def test_jsonl_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "logs.txt"
            target = Path(tmp_dir) / "cases.jsonl"
            source.write_text("normal startup\nfatal driver error\n", encoding="utf-8")
            cases = list(iter_loghub_cases(source, limit=2))

            dump_cases_jsonl(cases, target)
            loaded = load_cases_jsonl(target)

            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[1].label.target, "driver_or_os_fault")

    def test_enrich_case_derives_modalities_quality_and_boundary_roles(self):
        case = DatasetCase(
            case_id="boundary_case",
            source_dataset="unit",
            device_type="computer",
            fault_time="2026-01-01T00:00:00Z",
            evidence=EvidenceBundle(
                logs={"time_range": {"start": "2025-12-31T23:59:50Z", "end": "2026-01-01T00:00:01Z"}, "message": "driver reset on PCIe"},
                metrics={"telemetry": {"row_count": 10, "whea": "error"}},
            ),
        )

        enriched = enrich_case(case)

        self.assertIn("logs", enriched.metadata["modalities"])
        self.assertIn("metrics", enriched.metadata["modalities"])
        self.assertIn("software_side", enriched.metadata["boundary_roles"])
        self.assertIn("interface_path", enriched.metadata["boundary_roles"])
        self.assertTrue(enriched.evidence.alignment["has_fault_time"])
        self.assertGreater(enriched.evidence.quality["logs"], 0)

    def test_enrich_case_maps_service_label_to_software_boundary(self):
        case = DatasetCase(
            case_id="service_case",
            source_dataset="unit",
            device_type="service",
            evidence=EvidenceBundle(logs={"message": "timeout"}),
            label=Label(
                fault_origin="non_fru_fault",
                target="service_runtime_fault",
                serviceability_type="non_fru_fault",
            ),
        )

        enriched = enrich_case(case)

        self.assertEqual(enriched.label.boundary_type, "software_side")


if __name__ == "__main__":
    unittest.main()
