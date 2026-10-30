import tempfile
import unittest
from pathlib import Path

from fru_diagnosis.datasets import load_cases_jsonl
from scripts.prepare_loghub_os_dataset import prepare_dataset, write_prompt_templates


class LoghubOsPreparationTests(unittest.TestCase):
    def test_prepare_dataset_windows_and_labels_windows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            structured = root / "Windows_2k.log_structured.csv"
            templates = root / "Windows_2k.log_templates.csv"
            structured.write_text(
                "LineId,Date,Time,Level,Component,Content,EventId,EventTemplate\n"
                "1,2026-01-01,00:00:00,Info,CBS,Startup complete,E1,Startup complete\n"
                "2,2026-01-01,00:00:01,Error,CBS,Failed to open package,E2,Failed to open package\n"
                "3,2026-01-01,00:00:02,Info,CBS,Idle thread terminated,E3,Idle thread terminated\n",
                encoding="utf-8",
            )
            templates.write_text(
                "EventId,EventTemplate\n"
                "E1,Startup complete\n"
                "E2,Failed to open package\n"
                "E3,Idle thread terminated\n",
                encoding="utf-8",
            )

            cases, stats = prepare_dataset(
                dataset_key="windows",
                structured_csv=structured,
                template_csv=templates,
                window_size=2,
                limit_rows=None,
            )

            self.assertEqual(len(cases), 2)
            self.assertEqual(stats["template_count"], 3)
            self.assertEqual(cases[0].label.fault_origin, "non_fru_fault")
            self.assertEqual(cases[0].label.confidence, "weak")
            self.assertIn("raw_messages", cases[0].evidence.logs)
            self.assertEqual(cases[1].label.fault_origin, "no_fault_observed")

    def test_generated_cases_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_dir = root / "prompts"
            write_prompt_templates(prompt_dir)
            self.assertTrue((prompt_dir / "log_window_labeling_prompt.md").exists())

            structured = root / "Linux_2k.log_structured.csv"
            templates = root / "Linux_2k.log_templates.csv"
            out = root / "cases.jsonl"
            structured.write_text(
                "LineId,Month,Date,Time,Level,Component,PID,Content,EventId,EventTemplate\n"
                "1,Jan,1,00:00:00,info,kernel,1,kernel panic detected,E1,kernel panic detected\n",
                encoding="utf-8",
            )
            templates.write_text("EventId,EventTemplate\nE1,kernel panic detected\n", encoding="utf-8")

            cases, _ = prepare_dataset(
                dataset_key="linux",
                structured_csv=structured,
                template_csv=templates,
                window_size=50,
                limit_rows=None,
            )
            from fru_diagnosis.datasets import dump_cases_jsonl

            dump_cases_jsonl(cases, out)
            loaded = load_cases_jsonl(out)

            self.assertEqual(loaded[0].label.target, "driver_or_os_fault")
            self.assertEqual(loaded[0].metadata["official_label_available"], False)


if __name__ == "__main__":
    unittest.main()
