"""Device health scoring and maintenance policy generation."""

from __future__ import annotations

from typing import Any

from .log_noise_reduction import runtime_actionable_event_count


HEALTH_LEVELS = {
    "healthy": {
        "label": "healthy",
        "description": "No actionable abnormal evidence was found.",
    },
    "minor": {
        "label": "minor_anomalies",
        "description": "Abnormal evidence exists but does not currently block normal operation.",
    },
    "diagnose": {
        "label": "needs_further_diagnosis",
        "description": "Evidence may affect reliability and should be diagnosed further.",
    },
    "urgent": {
        "label": "needs_urgent_action",
        "description": "Evidence suggests a fault that may cause data loss, shutdown, or service interruption.",
    },
}


def assess_device_health(runtime: dict[str, Any], anomaly: dict[str, Any]) -> dict[str, Any]:
    """Classify current health and generate maintenance policy."""

    items = build_health_items(runtime, anomaly)
    score = calculate_health_score(items)
    level = classify_health_level(score, items)
    return {
        "task": "health_assessment",
        "health_score": score,
        "health_level": level,
        "description": HEALTH_LEVELS[level]["description"],
        "items": items,
        "summary": summarize_items(items),
        "maintenance_strategy": build_maintenance_strategy(level, items),
    }


def build_health_items(runtime: dict[str, Any], anomaly: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    events = runtime.get("events", {}) if isinstance(runtime.get("events"), dict) else {}
    inventory = runtime.get("device_inventory", {}) if isinstance(runtime.get("device_inventory"), dict) else {}
    collection_status = runtime.get("collection_status", {}) if isinstance(runtime.get("collection_status"), dict) else {}

    if collection_failed(collection_status, {"logs.system", "logs.application"}):
        items.append(
            health_item(
                "event_log_not_collected",
                "minor",
                "logs",
                "Event logs were not collected successfully; log silence cannot be interpreted as healthy.",
                impact="unknown",
                action="recollect_event_logs_with_required_permission",
            )
        )
    raw_warning_error_count = int(events.get("total_warning_error_count", 0) or 0)
    actionable_warning_error_count = runtime_actionable_event_count(events)
    if actionable_warning_error_count == 0 and not collection_failed(collection_status, {"logs.system", "logs.application"}):
        items.append(
            health_item(
                "event_log_noise_reduced" if raw_warning_error_count else "event_log_clear",
                "operational",
                "logs",
                (
                    f"{raw_warning_error_count} warning/error events were collected, "
                    "but template-based noise reduction found no actionable fault signal."
                    if raw_warning_error_count
                    else "No warning/error events were collected in the current window."
                ),
                impact="does_not_affect_operation",
                action="keep_baseline_monitoring",
            )
        )
    elif actionable_warning_error_count <= 5:
        items.append(
            health_item(
                "low_event_noise",
                "minor",
                "logs",
                (
                    f"{actionable_warning_error_count} actionable warning/error event(s) remain "
                    f"after reducing {raw_warning_error_count} raw event(s)."
                ),
                impact="does_not_affect_operation",
                action="observe_trend_and_review_if_repeated",
            )
        )
    else:
        items.append(
            health_item(
                "high_event_noise",
                "diagnose",
                "logs",
                (
                    f"{actionable_warning_error_count} actionable warning/error event(s) remain "
                    f"after reducing {raw_warning_error_count} raw event(s)."
                ),
                impact="may_affect_reliability",
                action="diagnose_event_buckets_and_collect_fault_window_logs",
            )
        )

    if collection_failed(collection_status, {"inventory.pnp_devices"}):
        items.append(
            health_item(
                "device_inventory_not_collected",
                "minor",
                "inventory",
                "PnP device inventory was not collected; zero problem devices cannot be assumed.",
                impact="unknown",
                action="recollect_device_inventory",
            )
        )
    problem_devices = int(inventory.get("problem_device_count", 0) or 0)
    if problem_devices == 0 and not collection_failed(collection_status, {"inventory.pnp_devices"}):
        items.append(
            health_item(
                "no_problem_devices",
                "operational",
                "inventory",
                "No PnP problem devices were found.",
                impact="does_not_affect_operation",
                action="no_immediate_action",
            )
        )
    else:
        items.append(
            health_item(
                "problem_devices_present",
                "urgent" if problem_devices >= 2 else "diagnose",
                "inventory",
                f"{problem_devices} problem device(s) were found.",
                impact="may_affect_device_function",
                action="inspect_device_manager_driver_and_hardware_path",
            )
        )

    for observation in anomaly.get("observations", []):
        obs_id = str(observation.get("id", ""))
        if obs_id in {"event_warning_error_count", "visible_symptom_reported"}:
            continue
        items.append(item_from_anomaly_observation(observation))

    if not items:
        items.append(
            health_item(
                "no_evidence",
                "minor",
                "evidence",
                "No runtime evidence is available. The device cannot be assessed confidently.",
                impact="unknown",
                action="collect_runtime_info",
            )
        )
    return items


def collection_failed(collection_status: dict[str, Any], sources: set[str]) -> bool:
    for source in sources:
        state = collection_status.get(source)
        if isinstance(state, dict) and state.get("status") == "failed":
            return True
    return False


def item_from_anomaly_observation(observation: dict[str, Any]) -> dict[str, Any]:
    severity = str(observation.get("severity", "medium"))
    if severity == "high":
        category = "urgent" if observation.get("id") in {"storage_smart_or_bad_block"} else "diagnose"
    elif severity == "medium":
        category = "minor"
    else:
        category = "operational"
    action_by_id = {
        "problem_device_count": "inspect_device_manager_driver_and_hardware_path",
        "storage_smart_or_bad_block": "backup_data_and_run_storage_diagnostics",
        "memory_or_whea_signal": "run_memory_and_platform_stress_tests",
        "crash_dump_present": "classify_crash_dump_and_review_recent_drivers",
        "active_test_failed": "repeat_active_test_and_isolate_related_module",
    }
    impact_by_category = {
        "operational": "does_not_affect_operation",
        "minor": "does_not_affect_operation",
        "diagnose": "needs_further_diagnosis",
        "urgent": "may_interrupt_operation",
    }
    return health_item(
        str(observation.get("id", "anomaly")),
        category,
        str(observation.get("layer", "evidence")),
        str(observation.get("description", "Abnormal evidence was detected.")),
        impact=impact_by_category[category],
        action=action_by_id.get(str(observation.get("id", "")), "collect_more_evidence"),
    )


def health_item(
    item_id: str,
    category: str,
    source: str,
    description: str,
    *,
    impact: str,
    action: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "category": category,
        "source": source,
        "description": description,
        "impact": impact,
        "recommended_action": action,
    }


def calculate_health_score(items: list[dict[str, Any]]) -> int:
    penalty = 0
    for item in items:
        category = item.get("category")
        penalty += {"operational": 0, "minor": 8, "diagnose": 22, "urgent": 38}.get(category, 10)
    return max(0, min(100, 100 - penalty))


def classify_health_level(score: int, items: list[dict[str, Any]]) -> str:
    categories = {str(item.get("category")) for item in items}
    if "urgent" in categories or score < 55:
        return "urgent"
    if "diagnose" in categories or score < 78:
        return "diagnose"
    if "minor" in categories or score < 95:
        return "minor"
    return "healthy"


def summarize_items(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"operational": 0, "minor": 0, "diagnose": 0, "urgent": 0}
    for item in items:
        category = str(item.get("category", "minor"))
        if category in summary:
            summary[category] += 1
    return summary


def build_maintenance_strategy(level: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    immediate = []
    follow_up = []
    routine = []
    for item in items:
        action = item.get("recommended_action")
        if item.get("category") == "urgent":
            immediate.append(action)
        elif item.get("category") == "diagnose":
            follow_up.append(action)
        else:
            routine.append(action)

    if level == "healthy":
        cadence = "normal_baseline_monitoring"
    elif level == "minor":
        cadence = "observe_next_24_to_72_hours"
    elif level == "diagnose":
        cadence = "run_targeted_diagnostics_before_repair"
    else:
        cadence = "handle_before_continued_use"

    return {
        "cadence": cadence,
        "immediate_actions": dedupe(immediate),
        "follow_up_diagnostics": dedupe(follow_up),
        "routine_actions": dedupe(routine),
    }


def dedupe(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
