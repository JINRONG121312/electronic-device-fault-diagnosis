"""Anomaly detection for device evidence bundles.

This layer answers whether collected evidence is currently abnormal. It does
not decide repair actions; classification and decision layers consume its
observations afterward.
"""

from __future__ import annotations

from typing import Any

from .crash_dump_evidence import crash_dump_is_available
from .log_noise_reduction import event_bucket_actionable_count, runtime_actionable_event_count


ANOMALY_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "event_warning_error_count",
        "layer": "logs",
        "severity": "medium",
        "fault_hint": "os_fault",
        "description": "Runtime evidence contains warning or error events.",
    },
    {
        "id": "problem_device_count",
        "layer": "inventory",
        "severity": "high",
        "fault_hint": "driver_fault",
        "description": "Device inventory reports problem devices.",
    },
    {
        "id": "storage_smart_or_bad_block",
        "layer": "metrics",
        "severity": "high",
        "fault_hint": "hardware_fault",
        "description": "Storage evidence contains SMART, bad block, or disk failure signals.",
    },
    {
        "id": "memory_or_whea_signal",
        "layer": "logs",
        "severity": "high",
        "fault_hint": "hardware_fault",
        "description": "Evidence contains memory, WHEA, or machine-check signals.",
    },
    {
        "id": "crash_dump_present",
        "layer": "crash_dump",
        "severity": "high",
        "fault_hint": "driver_fault",
        "description": "Crash dump evidence is present and should be classified.",
    },
    {
        "id": "active_test_failed",
        "layer": "active_tests",
        "severity": "high",
        "fault_hint": "hardware_fault",
        "description": "At least one active test failed.",
    },
)


def detect_anomalies(runtime: dict[str, Any], symptoms: list[str] | None = None) -> dict[str, Any]:
    symptoms = symptoms or []
    observations: list[dict[str, Any]] = []
    collection_status = runtime.get("collection_status", {}) if isinstance(runtime.get("collection_status"), dict) else {}
    events = runtime.get("events", {}) if isinstance(runtime.get("events"), dict) else {}
    device_inventory = (
        runtime.get("device_inventory", {}) if isinstance(runtime.get("device_inventory"), dict) else {}
    )
    crash_dump = runtime.get("crash_dump", {}) if isinstance(runtime.get("crash_dump"), dict) else {}
    tests = runtime.get("tests", {}) if isinstance(runtime.get("tests"), dict) else {}

    actionable_event_count = runtime_actionable_event_count(events)
    if actionable_event_count > 0:
        observation = build_observation("event_warning_error_count", actionable_event_count)
        observation["raw_value"] = int(events.get("total_warning_error_count", actionable_event_count) or 0)
        observation["description"] = "Runtime evidence contains actionable warning/error events after log-noise reduction."
        observations.append(observation)
    if int(device_inventory.get("problem_device_count", 0) or 0) > 0:
        observations.append(build_observation("problem_device_count", device_inventory.get("problem_device_count")))
    if event_bucket_actionable_count("storage", events.get("storage", {})) > 0 or contains_abnormal_metric(
        runtime.get("storage", {}),
        ["smart", "smart_failed", "smart_failure", "predicted_failure", "bad_block", "media_error"],
    ):
        observations.append(build_observation("storage_smart_or_bad_block"))
    if event_bucket_actionable_count("memory", events.get("memory", {})) > 0 or contains_abnormal_metric(
        runtime.get("memory", {}),
        ["memory_error", "whea_error", "machine_check", "ecc_error"],
    ):
        observations.append(build_observation("memory_or_whea_signal"))
    if crash_dump_is_available(crash_dump):
        observations.append(build_observation("crash_dump_present", crash_dump.get("bugcheck") or crash_dump.get("code")))
    if has_failed_active_test(tests):
        observations.append(build_observation("active_test_failed"))

    if symptoms and symptoms != ["unknown_symptom"]:
        observations.append(
            {
                "id": "visible_symptom_reported",
                "layer": "symptom",
                "severity": "medium",
                "fault_hint": "mixed_or_uncertain",
                "description": "A user-visible symptom was reported.",
                "value": list(symptoms),
            }
        )

    failed_sources = failed_collection_sources(collection_status)
    if failed_sources:
        observations.append(
            {
                "id": "collection_incomplete",
                "layer": "evidence",
                "severity": "low",
                "fault_hint": "mixed_or_uncertain",
                "description": "Some evidence sources failed to collect; absence of data must not be treated as normal evidence.",
                "value": failed_sources,
            }
        )

    score = round(min(1.0, sum(severity_weight(item["severity"]) for item in observations)), 4)
    status = "abnormal" if observations else "normal"
    return {
        "task": "anomaly_detection",
        "status": status,
        "anomaly_score": score,
        "observations": observations,
        "fault_hints": sorted({item["fault_hint"] for item in observations if item.get("fault_hint")}),
    }


def build_observation(rule_id: str, value: Any = None) -> dict[str, Any]:
    rule = next(item for item in ANOMALY_RULES if item["id"] == rule_id)
    observation = dict(rule)
    if value is not None:
        observation["value"] = value
    return observation


def severity_weight(severity: str) -> float:
    return {"high": 0.45, "medium": 0.25, "low": 0.1}.get(severity, 0.1)


def has_failed_active_test(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_failed_active_test(item) for item in value.values())
    if isinstance(value, list):
        return any(has_failed_active_test(item) for item in value)
    return str(value).casefold() in {"failed", "fail", "error", "abnormal", "not_detected"}


def bucket_total(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    return int(value.get("total_count", 0) or 0)


def contains_abnormal_metric(value: Any, keys: list[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if any(target in normalized_key for target in keys) and is_abnormal_value(item):
                return True
            if contains_abnormal_metric(item, keys):
                return True
        return False
    if isinstance(value, list):
        return any(contains_abnormal_metric(item, keys) for item in value)
    return False


def is_abnormal_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    text = str(value).casefold()
    return text in {"failed", "failure", "true", "bad", "error", "abnormal", "predicted_failure"} or any(
        token in text for token in ["fail", "failure", "predicted", "bad block", "media error", "smart error"]
    )


def failed_collection_sources(collection_status: dict[str, Any]) -> list[str]:
    failed = []
    for source, state in collection_status.items():
        if isinstance(state, dict) and state.get("status") == "failed":
            failed.append(str(source))
    return sorted(failed)
