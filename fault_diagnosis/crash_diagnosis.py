"""Compatibility API for parsing crash-dump evidence.

Crash dumps are evidence for fault classification, not a standalone diagnosis
branch in the research-facing workflow.
"""

from fru_diagnosis.crash_diagnosis import diagnose_crash_dump

__all__ = ["diagnose_crash_dump"]
