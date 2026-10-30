"""Normalize crash-dump evidence across self, target-agent, offline, and unavailable scenarios."""

from __future__ import annotations

from typing import Any


CRASH_DUMP_UNAVAILABLE_REASON = "dump_not_found_or_machine_unavailable"
CRASH_DUMP_NEXT_ACTION = "enable_dump_or_collect_offline_evidence"


def normalize_crash_dump_evidence(
    crash_dump: Any,
    *,
    source: str,
    unavailable_reason: str = CRASH_DUMP_UNAVAILABLE_REASON,
) -> dict[str, Any]:
    """Return a crash_dump object that never confuses missing evidence with healthy state."""

    if not isinstance(crash_dump, dict):
        crash_dump = {}

    dump_files = crash_dump.get("dump_files")
    if not isinstance(dump_files, list):
        dump_files = []
    dump_files.extend(normalize_dump_files(crash_dump.get("minidumps")))
    memory_dump = crash_dump.get("memory_dump")
    if isinstance(memory_dump, dict) and memory_dump:
        dump_files.append({**memory_dump, "kind": memory_dump.get("kind", "memory_dump")})

    bugcheck_code = str(
        crash_dump.get("bugcheck_code")
        or crash_dump.get("code")
        or crash_dump.get("bugcheck")
        or crash_dump.get("bugcheck_name")
        or ""
    )
    probable_modules = normalize_probable_modules(crash_dump)
    available = bool(crash_dump.get("available") is True or dump_files or bugcheck_code or probable_modules)

    normalized = {
        **crash_dump,
        "available": available,
        "source": crash_dump.get("source") or source,
        "dump_files": dump_files,
        "bugcheck_code": bugcheck_code,
        "probable_modules": probable_modules,
        "limitation": crash_dump.get("limitation", ""),
    }
    if not available:
        normalized["reason"] = crash_dump.get("reason") or unavailable_reason
        normalized["next_action"] = crash_dump.get("next_action") or CRASH_DUMP_NEXT_ACTION
    return normalized


def crash_dump_is_available(crash_dump: Any) -> bool:
    return isinstance(crash_dump, dict) and bool(crash_dump.get("available"))


def normalize_dump_files(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    files = []
    for item in value:
        if isinstance(item, dict):
            files.append({**item, "kind": item.get("kind", "minidump")})
    return files


def normalize_probable_modules(crash_dump: dict[str, Any]) -> list[str]:
    modules = []
    raw_modules = crash_dump.get("probable_modules")
    if isinstance(raw_modules, list):
        modules.extend(str(item) for item in raw_modules if str(item).strip())
    probable = str(crash_dump.get("probably_caused_by", "") or "").strip()
    if probable:
        modules.append(probable)
    stack_modules = crash_dump.get("stack_modules")
    if isinstance(stack_modules, list):
        modules.extend(str(item) for item in stack_modules if str(item).strip())
    result = []
    for module in modules:
        if module not in result:
            result.append(module)
    return result
