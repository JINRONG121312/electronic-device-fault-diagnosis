import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Loghub2MigrationTests(unittest.TestCase):
    def test_migrated_manifest_matches_dataset_directories(self):
        manifest_path = PROJECT_ROOT / "experiments" / "log_parsing_benchmark" / "loghub2_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dataset_root = PROJECT_ROOT / manifest["dataset_path"]

        datasets = sorted(path.name for path in dataset_root.iterdir() if path.is_dir())

        self.assertEqual(sorted(manifest["datasets"]), datasets)
        self.assertEqual(manifest["dataset_count"], len(datasets))

    def test_native_runner_is_present(self):
        runner = PROJECT_ROOT / "experiments" / "log_parsing_benchmark" / "run_imported_parser.py"
        benchmark_root = PROJECT_ROOT / "experiments" / "log_parsing_benchmark"

        self.assertTrue(runner.exists())
        self.assertTrue((benchmark_root / "evaluation").is_dir())
        self.assertTrue((benchmark_root / "logparser").is_dir())
        self.assertTrue((benchmark_root / "old_benchmark").is_dir())


if __name__ == "__main__":
    unittest.main()
