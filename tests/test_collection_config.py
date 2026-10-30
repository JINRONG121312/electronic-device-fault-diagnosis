import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fru_diagnosis.collection_config import (
    archive_runtime_snapshot,
    cleanup_history,
    list_history_snapshots,
    load_collection_settings,
    normalize_collection_settings,
    save_collection_settings,
)


class CollectionConfigTests(unittest.TestCase):
    def test_load_missing_settings_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = load_collection_settings(Path(tmp_dir) / "missing.json")

        self.assertEqual(settings["storage"]["active_runtime_path"], "data/runtime_info.json")
        self.assertTrue(settings["storage"]["save_history"])
        self.assertEqual(settings["background"]["interval_minutes"], 30)

    def test_save_and_load_settings_merges_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "settings.json"

            saved = save_collection_settings(
                {
                    "storage": {"active_runtime_path": "data/custom.json"},
                    "background": {"enabled": True, "interval_minutes": 2},
                },
                settings_path,
            )
            loaded = load_collection_settings(settings_path)

        self.assertEqual(saved, loaded)
        self.assertEqual(loaded["storage"]["active_runtime_path"], "data/custom.json")
        self.assertEqual(loaded["storage"]["history_dir"], "data/history")
        self.assertTrue(loaded["background"]["enabled"])
        self.assertEqual(loaded["background"]["interval_minutes"], 2)

    def test_normalize_rejects_unsafe_filename_template(self):
        settings = normalize_collection_settings(
            {"storage": {"filename_template": "../runtime_{timestamp}.json"}}
        )

        self.assertEqual(settings["storage"]["filename_template"], "runtime_{timestamp}.json")

    def test_archive_runtime_snapshot_and_cleanup_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "runtime.json"
            source.write_text(json.dumps({"generated_at": "now"}), encoding="utf-8")
            settings = normalize_collection_settings(
                {
                    "storage": {
                        "history_dir": str(root / "history"),
                        "filename_template": "runtime_{timestamp}.json",
                        "retention_count": 2,
                    }
                }
            )

            archive_runtime_snapshot(
                settings,
                source,
                datetime(2026, 5, 14, 10, 0, 0),
            )
            archive_runtime_snapshot(
                settings,
                source,
                datetime(2026, 5, 14, 10, 1, 0),
            )
            archive_runtime_snapshot(
                settings,
                source,
                datetime(2026, 5, 14, 10, 2, 0),
            )
            snapshots = list_history_snapshots(settings, limit=10)

        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0]["filename"], "runtime_20260514_100200.json")
        self.assertEqual(snapshots[1]["filename"], "runtime_20260514_100100.json")

    def test_cleanup_history_only_removes_managed_json_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            history = root / "history"
            history.mkdir()
            settings = normalize_collection_settings(
                {
                    "storage": {
                        "history_dir": str(history),
                        "filename_template": "runtime_{timestamp}.json",
                        "retention_count": 1,
                    }
                }
            )
            old_snapshot = history / "runtime_20260514_100000.json"
            new_snapshot = history / "runtime_20260514_100100.json"
            unrelated = history / "notes.json"
            old_snapshot.write_text("{}", encoding="utf-8")
            new_snapshot.write_text("{}", encoding="utf-8")
            unrelated.write_text("{}", encoding="utf-8")
            old_time = datetime.now() - timedelta(minutes=2)
            new_time = datetime.now() - timedelta(minutes=1)
            os.utime(old_snapshot, (old_time.timestamp(), old_time.timestamp()))
            os.utime(new_snapshot, (new_time.timestamp(), new_time.timestamp()))

            removed = cleanup_history(settings)

            self.assertEqual(removed, [str(old_snapshot)])
            self.assertFalse(old_snapshot.exists())
            self.assertTrue(new_snapshot.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
