"""Fault classification layer shared by the dashboard and research API."""

from __future__ import annotations

from typing import Any

from .crash_diagnosis import diagnose_crash_dump
from .crash_dump_evidence import crash_dump_is_available
from .log_noise_reduction import runtime_actionable_event_count


FAULT_CLASSES = (
    "driver_fault",
    "os_fault",
    "firmware_fault",
    "configuration_fault",
    "external_environment_fault",
    "hardware_fault",
    "data_or_filesystem_fault",
    "mixed_or_uncertain",
)


def classify_fault_case(case: dict[str, Any]) -> dict[str, Any]:
    symptoms = [str(item).casefold() for item in case.get("symptom", [])]
    evidence = case.get("evidence", {}) if isinstance(case.get("evidence"), dict) else {}
    crash_dump = evidence.get("crash_dump", {}) if isinstance(evidence, dict) else {}
    anomaly_detection = case.get("anomaly_detection", {}) if isinstance(case.get("anomaly_detection"), dict) else {}
    scores: dict[str, float] = {fault_class: 0.0 for fault_class in FAULT_CLASSES}
    observations: list[dict[str, Any]] = []

    for hint in anomaly_detection.get("fault_hints", []):
        fault_class = str(hint)
        if fault_class in scores:
            scores[fault_class] += 0.3
            observations.append({"type": "anomaly_hint", "name": fault_class})

    has_crash_dump = crash_dump_is_available(crash_dump)
    if "bsod" in symptoms or has_crash_dump:
        scores["driver_fault"] += 0.2
        scores["os_fault"] += 0.15
        observations.append(
            {
                "type": "symptom",
                "name": "bsod",
                "description": "BSOD is treated as a symptom, not as a separate diagnosis branch.",
            }
        )
        merge_crash_dump_evidence(scores, observations, crash_dump if has_crash_dump else {})

    logs_text = stringify_evidence(evidence.get("logs", {}))
    metrics_text = stringify_evidence(evidence.get("metrics", {}))
    active_text = stringify_evidence(evidence.get("active_tests", {}))
    inventory_text = stringify_evidence(evidence.get("inventory", {}))
    combined_text = " ".join([logs_text, metrics_text, active_text, inventory_text]).casefold()
    meaningful_text = combined_text if has_meaningful_abnormal_evidence(evidence, crash_dump) else ""

    if any(token in meaningful_text for token in ["driver", "service control", "kernel", "stack", "ndis"]):
        scores["driver_fault"] += 0.45
        observations.append({"type": "evidence", "name": "driver_or_kernel_context"})
    if any(token in meaningful_text for token in ["ntfs", "filesystem", "file system", "boot device", "low disk"]):
        scores["data_or_filesystem_fault"] += 0.45
        observations.append({"type": "evidence", "name": "data_or_filesystem_context"})
    if any(token in meaningful_text for token in ["bios", "firmware", "acpi", "ucsi"]):
        scores["firmware_fault"] += 0.4
        observations.append({"type": "evidence", "name": "firmware_context"})
    if any(token in meaningful_text for token in ["disabled", "policy", "configuration", "power plan"]):
        scores["configuration_fault"] += 0.35
        observations.append({"type": "evidence", "name": "configuration_context"})
    if any(token in meaningful_text for token in ["gateway", "router", "cable", "dock", "adapter", "external"]):
        scores["external_environment_fault"] += 0.35
        observations.append({"type": "evidence", "name": "external_environment_context"})
    if any(token in meaningful_text for token in ["smart", "whea", "memory", "nvme", "disk failure", "bad block"]):
        scores["hardware_fault"] += 0.45
        observations.append({"type": "evidence", "name": "hardware_context"})

    ranked = sorted(
        [
            {"fault_class": fault_class, "score": round(min(score, 1.0), 4)}
            for fault_class, score in scores.items()
            if score > 0
        ],
        key=lambda item: item["score"],
        reverse=True,
    )
    if not ranked:
        ranked = [{"fault_class": "mixed_or_uncertain", "score": 0.2}]

    return {
        "task": "fault_classification",
        "predicted_fault_class": ranked[0]["fault_class"],
        "class_ranking": ranked,
        "observations": observations,
        "decision_deferred": True,
    }


def merge_crash_dump_evidence(
    scores: dict[str, float],
    observations: list[dict[str, Any]],
    crash_dump: dict[str, Any],
) -> None:
    if not crash_dump:
        observations.append({"type": "missing_evidence", "name": "crash_dump"})
        return

    mapped = diagnose_crash_dump(crash_dump)
    observations.append(
        {
            "type": "crash_dump",
            "name": mapped.get("bugcheck") or mapped.get("code") or "unknown_bugcheck",
            "status": mapped.get("status"),
        }
    )
    for candidate in mapped.get("candidates", []):
        fault_class = map_candidate_to_fault_class(str(candidate.get("candidate", "")))
        scores[fault_class] = scores.get(fault_class, 0.0) + float(candidate.get("belief", 0.0)) * 0.55


def map_candidate_to_fault_class(candidate: str) -> str:
    text = candidate.casefold()
    if "driver" in text:
        return "driver_fault"
    if "filesystem" in text or "data" in text:
        return "data_or_filesystem_fault"
    if "firmware" in text or "config" in text:
        return "firmware_fault"
    if any(token in text for token in ["memory", "storage", "motherboard", "fru", "subsystem"]):
        return "hardware_fault"
    return "mixed_or_uncertain"


def stringify_evidence(value: Any) -> str:
    if isinstance(value, dict):
        if is_empty_event_bucket(value):
            return ""
        pieces = []
        for key, item in value.items():
            if str(key) in {"rules", "provider_patterns", "message_patterns"}:
                continue
            text = stringify_evidence(item)
            if text:
                pieces.append(f"{key} {text}")
        return " ".join(pieces)
    if isinstance(value, list):
        return " ".join(text for item in value if (text := stringify_evidence(item)))
    if value in {None, ""}:
        return ""
    return str(value)


def is_empty_event_bucket(value: dict[str, Any]) -> bool:
    bucket_keys = {"error_count", "warning_count", "total_count", "samples", "rules"}
    if not bucket_keys.intersection(value.keys()):
        return False
    try:
        total = int(value.get("total_count", 0) or 0)
        errors = int(value.get("error_count", 0) or 0)
        warnings = int(value.get("warning_count", 0) or 0)
    except (TypeError, ValueError):
        return False
    return total == 0 and errors == 0 and warnings == 0


def has_meaningful_abnormal_evidence(evidence: dict[str, Any], crash_dump: dict[str, Any]) -> bool:
    if crash_dump_is_available(crash_dump):
        return True
    logs = evidence.get("logs", {}) if isinstance(evidence, dict) else {}
    active_tests = evidence.get("active_tests", {}) if isinstance(evidence, dict) else {}
    metrics = evidence.get("metrics", {}) if isinstance(evidence, dict) else {}
    if log_has_actionable_evidence(logs):
        return True
    return (
        has_failed_value(active_tests)
        or has_failed_value(metrics)
    )


def log_has_actionable_evidence(logs: dict[str, Any]) -> bool:
    events = logs.get("events") if isinstance(logs, dict) else None
    if isinstance(events, dict):
        return runtime_actionable_event_count(events) > 0
    explicit = logs.get("actionable_warning_error_count") if isinstance(logs, dict) else None
    if explicit is not None:
        try:
            return int(explicit or 0) > 0
        except (TypeError, ValueError):
            return False
    noise_reduction = logs.get("noise_reduction") if isinstance(logs, dict) else None
    if isinstance(noise_reduction, dict):
        try:
            return int(noise_reduction.get("actionable_event_count", 0) or 0) > 0
        except (TypeError, ValueError):
            return False
    return has_positive_count(logs, {"error_count", "warning_count", "total_warning_error_count", "total_count"})


def has_positive_count(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in keys:
                try:
                    if int(item or 0) > 0:
                        return True
                except (TypeError, ValueError):
                    pass
            if has_positive_count(item, keys):
                return True
    if isinstance(value, list):
        return any(has_positive_count(item, keys) for item in value)
    return False


def has_failed_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_failed_value(item) for item in value.values())
    if isinstance(value, list):
        return any(has_failed_value(item) for item in value)
    text = str(value).casefold()
    return text in {"failed", "fail", "error", "abnormal", "not_detected", "predicted_failure"}
