import unittest

from fru_diagnosis.crash_dump_evidence import normalize_crash_dump_evidence


class CrashDumpEvidenceTests(unittest.TestCase):
    def test_missing_dump_is_explicitly_unavailable(self):
        evidence = normalize_crash_dump_evidence({}, source="unavailable")

        self.assertFalse(evidence["available"])
        self.assertEqual(evidence["source"], "unavailable")
        self.assertEqual(evidence["reason"], "dump_not_found_or_machine_unavailable")
        self.assertEqual(evidence["next_action"], "enable_dump_or_collect_offline_evidence")

    def test_minidump_metadata_makes_evidence_available(self):
        evidence = normalize_crash_dump_evidence(
            {"minidumps": [{"path": "C:/Windows/Minidump/001.dmp", "size_bytes": 1234}]},
            source="self_after_reboot",
        )

        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["source"], "self_after_reboot")
        self.assertEqual(evidence["dump_files"][0]["kind"], "minidump")


if __name__ == "__main__":
    unittest.main()
