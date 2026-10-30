"""Crash-dump evidence mapping helpers.

The mapped candidates feed fault classification. BSOD itself is a symptom, not
an independent diagnosis category.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BSOD_RULES_PATH = PROJECT_ROOT / "knowledge" / "rules" / "bsod_rules.json"


def diagnose_crash_dump(
    crash_dump: dict[str, Any],
    rules_path: str | Path = DEFAULT_BSOD_RULES_PATH,
) -> dict[str, Any]:
    """Map bugcheck metadata into repair-oriented candidates."""

    rules = load_rules(rules_path)
    bugcheck = normalize_bugcheck(crash_dump.get("bugcheck") or crash_dump.get("bugcheck_name"))
    code = normalize_code(crash_dump.get("bugcheck_code") or crash_dump.get("code"))
    matched_rule = None
    for rule in rules.get("rules", []):
        if normalize_bugcheck(rule.get("bugcheck")) == bugcheck or normalize_code(rule.get("code")) == code:
            matched_rule = rule
            break

    third_party_driver = detect_third_party_driver(crash_dump)
    if matched_rule is None and third_party_driver:
        matched_rule = {
            "bugcheck": bugcheck or "UNKNOWN",
            "code": code,
            "supports": ["driver_or_os_fault"],
            "next_best_test": "collect_driver_version_and_rollback_candidate",
        }

    if matched_rule is None:
        return {
            "status": "insufficient_crash_evidence",
            "bugcheck": bugcheck or "",
            "code": code or "",
            "candidates": [],
            "next_best_test": "collect_minidump",
        }

    candidates = [
        {
            "candidate": candidate,
            "type": "non_fru" if candidate.endswith("_fault") else "fru_or_subsystem",
            "belief": 0.75 if index == 0 else 0.55,
            "uncertainty": 0.25 if third_party_driver else 0.35,
            "supporting_evidence": [
                {
                    "rule_id": f"bugcheck_{matched_rule.get('bugcheck', 'unknown')}",
                    "description": f"BugCheck {bugcheck or code} supports {candidate}.",
                }
            ],
            "conflicting_evidence": [],
            "next_best_test": matched_rule.get("next_best_test", "collect_minidump"),
        }
        for index, candidate in enumerate(matched_rule.get("supports", []))
    ]
    if third_party_driver:
        candidates.insert(
            0,
            {
                "candidate": "driver_or_os_fault",
                "type": "non_fru",
                "belief": 0.85,
                "uncertainty": 0.2,
                "supporting_evidence": [
                    {
                        "rule_id": "third_party_driver_in_stack",
                        "description": f"Crash stack references third-party driver {third_party_driver}.",
                    }
                ],
                "conflicting_evidence": [],
                "next_best_test": "update_or_rollback_driver",
            },
        )
    return {
        "status": "mapped",
        "bugcheck": bugcheck or matched_rule.get("bugcheck", ""),
        "code": code or matched_rule.get("code", ""),
        "candidates": candidates,
        "next_best_test": candidates[0]["next_best_test"] if candidates else "collect_minidump",
    }


def load_rules(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def normalize_bugcheck(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.startswith("0x"):
        return "0x" + text[2:].zfill(8).upper()
    try:
        return f"0x{int(text):08X}"
    except ValueError:
        return text.upper()


def detect_third_party_driver(crash_dump: dict[str, Any]) -> str:
    stack = " ".join(str(item) for item in crash_dump.get("stack_modules", []))
    probable = str(crash_dump.get("probably_caused_by", "") or "")
    text = f"{stack} {probable}".casefold()
    if not text:
        return ""
    microsoft_prefixes = ("ntoskrnl", "hal.dll", "win32k", "ndis.sys", "tcpip.sys")
    for token in text.replace(",", " ").split():
        if token.endswith((".sys", ".dll")) and not token.startswith(microsoft_prefixes):
            return token
    return ""
