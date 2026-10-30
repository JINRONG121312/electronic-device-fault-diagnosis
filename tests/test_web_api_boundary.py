import unittest
from http import HTTPStatus

from fru_diagnosis.datasets import DatasetCase, EvidenceBundle, Label
from fru_diagnosis.web_api import ApiRoutes, api_error, ok
from fru_web_server import (
    FRURequestHandler,
    build_api_routes,
    build_confusion_matrix,
    evaluate_experiment_cases,
    parse_imported_test_cases,
)


class WebApiBoundaryTests(unittest.TestCase):
    def test_get_route_dispatches_without_http_handler_state(self):
        routes = ApiRoutes(
            get={"/api/example": lambda query: ok({"ok": True, "id": query["id"][0]})},
            post={},
        )

        status, payload = routes.handle_get("/api/example", {"id": ["42"]})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["id"], "42")

    def test_unknown_route_returns_stable_api_error(self):
        routes = ApiRoutes(get={}, post={})

        status, payload = routes.handle_post("/api/missing", {})

        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertFalse(payload["ok"])
        self.assertIn("Unknown API endpoint", payload["error"])

    def test_api_error_helper_preserves_status_and_message(self):
        status, payload = api_error(HTTPStatus.BAD_REQUEST, "bad input")

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(payload, {"ok": False, "error": "bad input"})

    def test_server_route_table_exposes_unified_diagnose_endpoint(self):
        self.assertIn("/api/diagnose", build_api_routes(FRURequestHandler).post)

    def test_server_route_table_exposes_target_agent_endpoints(self):
        routes = build_api_routes(FRURequestHandler).post

        self.assertIn("/api/target/probe", routes)
        self.assertIn("/api/target/collect", routes)
        self.assertIn("/api/experiments/loghub-os/import-test", routes)

    def test_server_route_table_exposes_health_endpoint(self):
        status, payload = build_api_routes(FRURequestHandler).handle_get("/api/health", {})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "fault_diagnosis_web")

    def test_imported_test_cases_are_forced_to_test_split(self):
        case = DatasetCase(
            case_id="case_001",
            source_dataset="unit",
            device_type="computer",
            evidence=EvidenceBundle(logs={"raw_messages": ["driver failed"]}),
            label=Label(
                fault_origin="non_fru_fault",
                target="driver_or_os_fault",
                serviceability_type="non_fru_fault",
            ),
            metadata={"dataset_key": "old", "split": "train"},
        )
        content = case.to_dict()

        cases, warnings = parse_imported_test_cases(
            f"{__import__('json').dumps(content, ensure_ascii=False)}\n",
            filename="test.jsonl",
            imported_at="2026-06-28T00:00:00",
        )

        self.assertEqual(warnings, [])
        self.assertEqual(cases[0].metadata["dataset_key"], "imported_test")
        self.assertEqual(cases[0].metadata["split"], "test")
        self.assertTrue(cases[0].case_id.startswith("imported_test_"))

    def test_confusion_matrix_reports_macro_f1(self):
        cases = [
            {
                "label": {"target": "driver_or_os_fault"},
                "metadata": {"prediction": {"target": "driver_or_os_fault"}},
            },
            {
                "label": {"target": "os_fault"},
                "metadata": {"prediction": {"target": "driver_or_os_fault"}},
            },
        ]

        matrix = build_confusion_matrix(cases, "target")
        metrics = evaluate_experiment_cases(cases, "target")

        self.assertEqual(matrix["accuracy"], 0.5)
        self.assertEqual(metrics["macro_f1"], 0.3333)


if __name__ == "__main__":
    unittest.main()
