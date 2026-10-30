"""Next-best-test planning for active diagnosis."""

from __future__ import annotations

import copy
import math
from typing import Any

from .boundary_assessment import assess_boundary


TEST_LIBRARY: list[dict[str, Any]] = [
    {
        "id": "collect_minidump",
        "name": "Collect Windows minidump and bugcheck metadata",
        "symptoms": ["bsod"],
        "targets": ["driver_or_os_fault", "memory_subsystem", "storage_fru", "motherboard"],
        "expected_information_gain": 0.9,
        "cost": 0.2,
        "risk": 0.0,
        "boundary_roles": ["software_side", "interface_path", "hardware_endpoint"],
    },
    {
        "id": "run_memory_extended_test",
        "name": "Run extended memory diagnostic",
        "symptoms": ["bsod", "random_reboot"],
        "targets": ["memory_subsystem", "motherboard"],
        "expected_information_gain": 0.75,
        "cost": 0.7,
        "risk": 0.1,
        "boundary_roles": ["hardware_endpoint", "interface_path"],
    },
    {
        "id": "collect_power_acpi_ucsi",
        "name": "Collect battery, ACPI, UCSI, and charging evidence",
        "symptoms": ["charging_failure", "no_power"],
        "targets": ["battery_pack", "power_adapter", "firmware_or_config_fault", "motherboard"],
        "expected_information_gain": 0.78,
        "cost": 0.3,
        "risk": 0.0,
        "boundary_roles": ["firmware_control", "interface_path", "hardware_endpoint"],
    },
    {
        "id": "adapter_swap_test",
        "name": "Retest with known-good power adapter/cable",
        "symptoms": ["charging_failure", "no_power"],
        "targets": ["power_adapter", "external_environment_fault"],
        "expected_information_gain": 0.7,
        "cost": 0.25,
        "risk": 0.0,
        "boundary_roles": ["external_environment", "interface_path", "hardware_endpoint"],
    },
    {
        "id": "gateway_ping_and_driver_check",
        "name": "Run gateway ping, packet loss, and network driver check",
        "symptoms": ["no_network", "wifi_disconnect"],
        "targets": ["wlan_module", "driver_or_os_fault", "external_environment_fault"],
        "expected_information_gain": 0.72,
        "cost": 0.25,
        "risk": 0.0,
        "boundary_roles": ["software_side", "external_environment", "interface_path", "hardware_endpoint"],
    },
    {
        "id": "external_display_test",
        "name": "Compare internal and external display output",
        "symptoms": ["black_screen", "display_fault"],
        "targets": ["display_panel_module", "driver_or_os_fault", "motherboard"],
        "expected_information_gain": 0.82,
        "cost": 0.35,
        "risk": 0.0,
        "boundary_roles": ["software_side", "interface_path", "hardware_endpoint"],
    },
    {
        "id": "storage_health_and_short_test",
        "name": "Collect SMART/NVMe health and run short storage self-test",
        "symptoms": ["boot_failure", "slow_io", "bsod"],
        "targets": ["storage_fru", "data_or_filesystem_fault"],
        "expected_information_gain": 0.76,
        "cost": 0.45,
        "risk": 0.05,
        "boundary_roles": ["software_side", "interface_path", "hardware_endpoint"],
    }
]


def recommend_next_tests(
    diagnosis_report: dict[str, Any],
    symptoms: list[str] | tuple[str, ...],
    *,
    limit: int = 5,
    boundary_assessment: dict[str, Any] | None = None,
    completed_tests: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Rank tests by boundary-aware expected information gain over cost."""

    candidates = diagnosis_report.get("top_candidates") or diagnosis_report.get("candidates", [])
    candidate_ids = {str(item.get("fru_id", "")) for item in candidates[:8]}
    symptom_set = {str(symptom) for symptom in symptoms}
    boundary_assessment = boundary_assessment or diagnosis_report.get("boundary_assessment", {}) or {}
    posterior = boundary_assessment.get("posterior", {}) if isinstance(boundary_assessment, dict) else {}
    posterior = posterior if isinstance(posterior, dict) else {}
    conflict = float(boundary_assessment.get("conflict_score", 0.0) or 0.0)
    uncertainty = posterior_uncertainty(posterior)
    completed = {str(item) for item in completed_tests or []}
    scored = []
    for test in TEST_LIBRARY:
        if str(test.get("id", "")) in completed:
            continue
        symptom_overlap = len(symptom_set.intersection(test.get("symptoms", [])))
        target_overlap = len(candidate_ids.intersection(test.get("targets", [])))
        if symptom_overlap == 0 and target_overlap == 0:
            continue
        role_coverage = sum(float(posterior.get(role, 0.0) or 0.0) for role in test.get("boundary_roles", []))
        if not posterior:
            role_coverage = 0.5
        base_gain = float(test.get("expected_information_gain", 0.1))
        context_factor = 1.0 if symptom_overlap or not symptom_set else 0.25
        raw_expected_gain = base_gain * (
            0.5
            + role_coverage
            + uncertainty * 0.5
            + conflict * 0.4
            + symptom_overlap * 0.4
            + target_overlap * 0.25
        ) * context_factor
        expected_gain = min(1.0, raw_expected_gain)
        denominator = max(
            0.1,
            float(test.get("cost", 1.0)) + float(test.get("risk", 0.0)) + 0.1,
        )
        score = expected_gain / denominator
        scored.append(
            {
                **test,
                "score": round(score, 4),
                "boundary_expected_information_gain": round(expected_gain, 4),
                "posterior_coverage": round(role_coverage, 4),
                "uncertainty_factor": round(uncertainty, 4),
                "conflict_factor": round(conflict, 4),
                "symptom_context_factor": context_factor,
                "matched_symptoms": sorted(symptom_set.intersection(test.get("symptoms", []))),
                "matched_targets": sorted(candidate_ids.intersection(test.get("targets", []))),
            }
        )
    return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]


def apply_active_test_result(
    runtime: dict[str, Any],
    test_id: str,
    result: Any,
) -> dict[str, Any]:
    """Return a runtime copy with a normalized active-test observation."""

    updated = copy.deepcopy(runtime)
    tests = updated.setdefault("tests", {})
    active = tests.setdefault("active_diagnosis", {})
    active[str(test_id)] = normalize_test_result(result)
    return updated


def completed_test_ids(runtime: dict[str, Any]) -> set[str]:
    tests = runtime.get("tests", {}) if isinstance(runtime.get("tests"), dict) else {}
    active = tests.get("active_diagnosis", {}) if isinstance(tests.get("active_diagnosis"), dict) else {}
    return {str(test_id) for test_id in active}


def evaluate_active_test_transition(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Measure how much one test changed the boundary belief state."""

    before_posterior = before.get("posterior", {}) or {}
    after_posterior = after.get("posterior", {}) or {}
    before_entropy = posterior_entropy(before_posterior)
    after_entropy = posterior_entropy(after_posterior)
    return {
        "before_boundary_type": before.get("boundary_type", "mixed_or_uncertain"),
        "after_boundary_type": after.get("boundary_type", "mixed_or_uncertain"),
        "before_confidence": float(before.get("confidence", 0.0) or 0.0),
        "after_confidence": float(after.get("confidence", 0.0) or 0.0),
        "before_entropy": round(before_entropy, 4),
        "after_entropy": round(after_entropy, 4),
        "realized_information_gain": round(before_entropy - after_entropy, 4),
        "posterior_shift": round(posterior_distance(before_posterior, after_posterior), 4),
        "conflict_delta": round(
            float(after.get("conflict_score", 0.0) or 0.0)
            - float(before.get("conflict_score", 0.0) or 0.0),
            4,
        ),
        "evidence_coverage_delta": round(
            float(after.get("evidence_coverage", 0.0) or 0.0)
            - float(before.get("evidence_coverage", 0.0) or 0.0),
            4,
        ),
        "boundary_changed": before.get("boundary_type") != after.get("boundary_type"),
    }


def run_active_test_update(
    runtime: dict[str, Any],
    classification: dict[str, Any],
    top_candidates: list[dict[str, Any]],
    symptoms: list[str],
    test_id: str,
    result: Any,
) -> dict[str, Any]:
    """Apply one test result and recompute boundary attribution."""

    before = assess_boundary(runtime, classification, top_candidates, symptoms)
    updated_runtime = apply_active_test_result(runtime, test_id, result)
    after = assess_boundary(updated_runtime, classification, top_candidates, symptoms)
    return {
        "test_id": test_id,
        "result": normalize_test_result(result),
        "runtime": updated_runtime,
        "before": before,
        "after": after,
        "transition": evaluate_active_test_transition(before, after),
    }


def normalize_test_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        normalized = dict(result)
        normalized.setdefault("status", str(result.get("result", "unknown")))
        return normalized
    return {"status": str(result or "unknown")}


def posterior_uncertainty(posterior: dict[str, Any]) -> float:
    values = [max(0.0, float(value or 0.0)) for value in posterior.values()]
    return round(1.0 - max(values), 4) if values else 1.0


def posterior_entropy(posterior: dict[str, Any]) -> float:
    values = [max(0.0, float(value or 0.0)) for value in posterior.values()]
    total = sum(values)
    if total <= 0:
        return 0.0
    probabilities = [value / total for value in values if value > 0]
    if len(probabilities) <= 1:
        return 0.0
    return -sum(value * math.log(value, 2) for value in probabilities) / math.log(len(probabilities), 2)


def posterior_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    keys = set(left).union(right)
    return 0.5 * sum(
        abs(float(left.get(key, 0.0) or 0.0) - float(right.get(key, 0.0) or 0.0))
        for key in keys
    )
