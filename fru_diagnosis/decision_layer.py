"""Decision layer for post-classification actions."""

from __future__ import annotations

from typing import Any


DECISION_POLICIES: dict[str, dict[str, Any]] = {
    "driver_fault": {
        "decision": "software_repairable",
        "actions": ["collect_driver_version", "rollback_or_update_driver", "collect_crash_dump_if_missing"],
    },
    "os_fault": {
        "decision": "software_repairable",
        "actions": ["collect_system_events", "repair_system_files", "review_recent_updates"],
    },
    "firmware_fault": {
        "decision": "firmware_repairable",
        "actions": ["collect_bios_acpi_state", "restore_firmware_defaults", "consider_firmware_update"],
    },
    "configuration_fault": {
        "decision": "configuration_repairable",
        "actions": ["review_policy_and_service_state", "restore_known_good_configuration"],
    },
    "external_environment_fault": {
        "decision": "externally_reproducible",
        "actions": ["retest_with_known_good_external_environment"],
    },
    "hardware_fault": {
        "decision": "replaceable_hardware_or_service_required",
        "actions": ["run_confirmatory_hardware_test", "map_to_serviceability_object_after_confirmation"],
    },
    "data_or_filesystem_fault": {
        "decision": "software_repairable",
        "actions": ["check_free_space", "repair_filesystem_or_image", "validate_storage_health"],
    },
    "mixed_or_uncertain": {
        "decision": "need_more_evidence",
        "actions": ["run_next_best_test", "collect_missing_required_evidence"],
    },
}


def decide_after_classification(classification: dict[str, Any]) -> dict[str, Any]:
    health = classification.get("health_assessment", {}) if isinstance(classification.get("health_assessment"), dict) else {}
    health_level = str(health.get("health_level", ""))
    boundary = classification.get("boundary_assessment", {}) if isinstance(classification.get("boundary_assessment"), dict) else {}
    if health_level in {"healthy", "minor"}:
        return {
            "task": "decision_after_classification",
            "fault_class": str(classification.get("predicted_fault_class", "mixed_or_uncertain")),
            "decision": "monitor_or_routine_maintenance",
            "actions": list(health.get("maintenance_strategy", {}).get("routine_actions", []))
            or ["keep_baseline_monitoring"],
            "classification_score": (
                classification.get("class_ranking", [{}])[0].get("score")
                if classification.get("class_ranking")
                else None
            ),
            "health_level": health_level,
        }

    if boundary.get("boundary_type") == "hardware_software_boundary" and float(boundary.get("confidence", 0.0) or 0.0) < 0.75:
        return {
            "task": "decision_after_classification",
            "fault_class": str(classification.get("predicted_fault_class", "mixed_or_uncertain")),
            "decision": "need_boundary_isolation",
            "actions": [
                str(boundary.get("next_best_boundary_test") or "run_boundary_isolation_test"),
                "defer_hardware_replacement_until_boundary_is_clear",
            ],
            "classification_score": (
                classification.get("class_ranking", [{}])[0].get("score")
                if classification.get("class_ranking")
                else None
            ),
            "boundary_type": boundary.get("boundary_type"),
            "boundary_confidence": boundary.get("confidence"),
        }

    fault_class = str(classification.get("predicted_fault_class", "mixed_or_uncertain"))
    policy = DECISION_POLICIES.get(fault_class, DECISION_POLICIES["mixed_or_uncertain"])
    return {
        "task": "decision_after_classification",
        "fault_class": fault_class,
        "decision": policy["decision"],
        "actions": list(policy["actions"]),
        "classification_score": (
            classification.get("class_ranking", [{}])[0].get("score")
            if classification.get("class_ranking")
            else None
        ),
    }
