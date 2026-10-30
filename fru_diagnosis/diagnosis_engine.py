"""Explainable FRU diagnosis scoring.

The engine evaluates abnormal evidence only. Inventory presence and successful
passive collection improve readiness elsewhere, but they should not by
themselves make a FRU look faulty.
"""

from __future__ import annotations

import re
from typing import Any

from .boundary_assessment import assess_boundary, boundary_role_for_candidate
from .crash_dump_evidence import crash_dump_is_available
from .decision_layer import decide_after_classification
from .diagnostic_graph import build_diagnostic_graph
from .fault_classification import classify_fault_case
from .graph_inference import infer_diagnostic_graph
from .log_noise_reduction import (
    event_bucket_actionable_count,
    runtime_actionable_event_count,
    sample_is_actionable,
)


NEGATIVE_TEST_VALUES = {"failed", "fail", "error", "abnormal", "not_detected"}
POSITIVE_TEST_VALUES = {"passed", "pass", "ok", "normal", "not_applicable"}
MISSING_VALUES = {None, "", "not_run", "unknown"}

NON_FRU_FAULTS: list[dict[str, Any]] = [
    {
        "id": "driver_or_os_fault",
        "name": "Driver or operating-system fault",
        "category": "software_or_os",
        "repair_action": "Update, roll back, reinstall, or repair the affected driver/OS component.",
        "evidence_rules": [
            {
                "id": "driver_events_without_hardware_failure",
                "evidence_type": "non_fru_signal",
                "pattern": "driver|service|stack|ndis|security-spp|activation|appcrash|service control",
                "weight": 0.9,
                "description": "Warnings/errors are concentrated in driver, service, activation, or OS components without a matching failed hardware test.",
            }
        ],
    },
    {
        "id": "firmware_or_config_fault",
        "name": "Firmware or configuration fault",
        "category": "firmware_or_config",
        "repair_action": "Check BIOS/EC settings, firmware version, disabled devices, and power-management policy.",
        "evidence_rules": [
            {
                "id": "firmware_config_events",
                "evidence_type": "non_fru_signal",
                "pattern": "bios|firmware|ec|acpi|secure boot|disabled|policy|power plan|ucmucsi",
                "weight": 0.75,
                "description": "The evidence points to firmware, ACPI, configuration, or policy before a replaceable module.",
            }
        ],
    },
    {
        "id": "external_environment_fault",
        "name": "External environment fault",
        "category": "external_environment",
        "repair_action": "Swap the cable, outlet, charger, router, peripheral, dock, or test under a controlled environment.",
        "evidence_rules": [
            {
                "id": "external_context_events",
                "evidence_type": "non_fru_signal",
                "pattern": "networkavailable|router|gateway|ssid|outlet|dock|cable|peripheral|external|ambient",
                "weight": 0.7,
                "description": "The symptom can be explained by external power, network, peripheral, cable, dock, or ambient conditions.",
            }
        ],
    },
    {
        "id": "connector_or_interconnect_fault",
        "name": "Connector or interconnect fault",
        "category": "connector_or_interconnect",
        "repair_action": "Inspect and reseat cables/connectors before replacing endpoint modules.",
        "evidence_rules": [
            {
                "id": "intermittent_endpoint_path",
                "evidence_type": "non_fru_signal",
                "pattern": "intermittent|descriptor request failed|code 43|disconnect|reconnect|link down|not recognized|loose|connector",
                "weight": 0.8,
                "description": "Intermittent endpoint or path failures can indicate cable, connector, oxidation, or seating issues.",
            }
        ],
    },
    {
        "id": "data_or_filesystem_fault",
        "name": "Data or filesystem fault",
        "category": "data_or_filesystem",
        "repair_action": "Free disk space, repair filesystem/OS image, and validate storage before hardware replacement.",
        "evidence_rules": [
            {
                "id": "low_space_or_filesystem_context",
                "evidence_type": "non_fru_signal",
                "pattern": "ntfs|filesystem|file system|low disk|space|volume|corrupt",
                "weight": 0.9,
                "description": "Low free space or filesystem/OS image symptoms can mimic storage or system faults.",
            }
        ],
    },
    {
        "id": "maintenance_condition_fault",
        "name": "Maintenance condition",
        "category": "maintenance_condition",
        "repair_action": "Clean vents, check dust, thermal paste, battery calibration, and mechanical seating.",
        "evidence_rules": [
            {
                "id": "maintenance_context",
                "evidence_type": "non_fru_signal",
                "pattern": "thermal|overheat|throttle|dust|calibration|blocked|fan curve",
                "weight": 0.65,
                "description": "Maintenance conditions can cause symptoms before a FRU has actually failed.",
            }
        ],
    },
    {
        "id": "multi_fault_or_damage",
        "name": "Multiple faults or damage",
        "category": "multi_fault",
        "repair_action": "Inspect for liquid, drop, corrosion, overvoltage, and multiple failed paths before single-FRU replacement.",
        "evidence_rules": [
            {
                "id": "multiple_independent_paths",
                "evidence_type": "non_fru_signal",
                "pattern": "multiple|liquid|corrosion|overvoltage|drop|several|multi",
                "weight": 0.8,
                "description": "Multiple independent abnormal paths reduce confidence in a single replaceable module.",
            }
        ],
    },
]


def build_diagnosis_report(
    profile: dict[str, Any],
    runtime: dict[str, Any],
    coverage: dict[str, dict[str, Any]] | None = None,
    collection_plan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return ranked FRU diagnosis candidates and supporting context."""

    coverage = coverage or {}
    plan_by_fru = {
        str(plan.get("fru_id", "")): plan
        for plan in (collection_plan or [])
    }
    candidates = [
        score_fru(fru, runtime, coverage.get(str(fru.get("id", "")), {}), plan_by_fru)
        for fru in profile.get("fru_list", [])
        if fru.get("diagnosis_role") in {"target_fru", "subsystem"}
    ]
    candidates.extend(score_non_fru_fault(fault, runtime, candidates) for fault in NON_FRU_FAULTS)
    diagnostic_graph = build_diagnostic_graph(profile, runtime, candidates=candidates)
    graph_inference = infer_diagnostic_graph(diagnostic_graph)
    candidates = apply_graph_inference_to_candidates(candidates, graph_inference)
    candidates.sort(
        key=lambda item: (
            item["rank_score"],
            item["evidence_score"],
            item["collection_score"],
            item["fru_id"],
        ),
        reverse=True,
    )

    leading = candidates[0] if candidates else None
    actionable = [item for item in candidates if item["status"] in {"suspect", "possible"}]
    summary = summarize_diagnosis(candidates, runtime, leading, actionable)

    return {
        "summary": summary,
        "top_candidates": candidates[:5],
        "candidates": candidates,
        "non_fru_risks": build_non_fru_risks(runtime, candidates),
        "classification": summary.get("classification", {}),
        "boundary_assessment": summary.get("boundary_assessment", {}),
        "decision": summary.get("decision", {}),
        "diagnostic_graph": compact_graph_for_report(diagnostic_graph),
        "graph_inference": compact_graph_inference_for_report(graph_inference),
        "method": {
            "name": "heterogeneous_graph_fused_fault_diagnosis",
            "description": "Rule evidence is converted into candidates and then fused with a heterogeneous diagnostic graph over logs, components, FRUs, metrics, active tests, crash dumps, and fault classes.",
            "score_formula": "legacy evidence score plus graph posterior, with support/conflict and source uncertainty retained for explanation",
        },
    }


def score_fru(
    fru: dict[str, Any],
    runtime: dict[str, Any],
    coverage: dict[str, Any],
    plan_by_fru: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fru_id = str(fru.get("id", ""))
    serviceability = normalize_serviceability(fru)
    service_type = str(serviceability.get("type", "replaceable_fru"))
    matches = []
    negatives = []
    missing_rules = []
    total_weight = 0.0
    matched_weight = 0.0
    negative_weight = 0.0

    for rule in fru.get("evidence_rules", []):
        weight = safe_float(rule.get("weight"), 1.0)
        total_weight += weight
        result = evaluate_rule(rule, runtime, fru)
        item = {
            "rule_id": str(rule.get("id", "")),
            "type": str(rule.get("evidence_type", "")),
            "weight": weight,
            "description": str(rule.get("description", "")),
            "source": str(rule.get("source", "")),
            "details": result.get("details", []),
        }
        if result["state"] == "match":
            matched_weight += weight
            matches.append(item)
        elif result["state"] == "negative":
            negative_weight += weight
            negatives.append(item)
        else:
            missing_rules.append(item)

    implicit_device = evaluate_implicit_device_state(fru, runtime)
    if implicit_device["state"] == "match":
        weight = 0.6
        total_weight += weight
        matched_weight += weight
        matches.append(
            {
                "rule_id": "implicit_problem_device_match",
                "type": "device_state",
                "weight": weight,
                "description": "Problem device inventory matches this FRU aliases or repair path.",
                "source": "device_inventory",
                "details": implicit_device.get("details", []),
            }
        )

    if not total_weight:
        total_weight = 1.0

    evidence_score = max(0, round((matched_weight - negative_weight * 0.45) / total_weight * 100))
    collection_score = int(coverage.get("score", 0) or 0)
    rank_score = min(100, round(evidence_score * 0.88 + collection_score * 0.12))
    status = classify_candidate(evidence_score, matches, negatives, coverage)
    confidence = classify_confidence(rank_score, coverage, matches, missing_rules)
    plan = plan_by_fru.get(fru_id, {})
    boundary_role, boundary_reason = boundary_role_for_candidate(
        {
            "fru_id": fru_id,
            "category": fru.get("category", ""),
            "candidate_type": service_type,
        }
    )

    return {
        "fru_id": fru_id,
        "fru_name": fru.get("name", ""),
        "category": fru.get("category", ""),
        "candidate_type": service_type,
        "fault_origin": service_type,
        "boundary_role": boundary_role,
        "boundary_reason": boundary_reason,
        "serviceability": serviceability,
        "replacement_required": service_type in {"replaceable_fru", "serviceable_assembly", "external_part"},
        "replacement_recommendation": replacement_recommendation_for_candidate(status, serviceability),
        "repair_action": serviceability.get("action", ""),
        "replaceable": bool(fru.get("replaceable", False)),
        "diagnosis_role": fru.get("diagnosis_role", "target_fru"),
        "status": status,
        "confidence": confidence,
        "rank_score": rank_score,
        "evidence_score": evidence_score,
        "collection_score": collection_score,
        "readiness": coverage.get("readiness", "missing"),
        "matched_rule_count": len(matches),
        "negative_rule_count": len(negatives),
        "missing_rule_count": len(missing_rules),
        "matched_evidence": matches,
        "negative_evidence": negatives,
        "missing_evidence": missing_rules,
        "next_actions": build_candidate_next_actions(missing_rules, plan),
        "explanation": explain_candidate(fru, status, evidence_score, matches, negatives),
    }


def score_non_fru_fault(
    fault: dict[str, Any],
    runtime: dict[str, Any],
    fru_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    matches = []
    negatives = []
    missing_rules = []
    matched_strength = 0

    for rule in fault.get("evidence_rules", []):
        weight = safe_float(rule.get("weight"), 1.0)
        result = evaluate_non_fru_signal(rule, runtime, fru_candidates)
        strength = int(result.get("strength", 0) or 0)
        item = {
            "rule_id": str(rule.get("id", "")),
            "type": str(rule.get("evidence_type", "non_fru_signal")),
            "weight": weight,
            "strength": strength,
            "description": str(rule.get("description", "")),
            "source": "diagnosis_context",
            "details": result.get("details", []),
        }
        if result["state"] == "match":
            matched_strength = max(matched_strength, strength)
            matches.append(item)
        elif result["state"] == "negative":
            negatives.append(item)
        else:
            missing_rules.append(item)

    hardware_blockers = hardware_replacement_blockers(fru_candidates)
    if hardware_blockers:
        matched_strength = max(0, matched_strength - 25)
        negatives.append(
            {
                "rule_id": "hardware_failure_exclusion",
                "type": "exclusion_rule",
                "weight": 0.8,
                "description": "A stronger hardware/FRU failure signal exists, so non-FRU explanation is reduced.",
                "source": "fru_candidates",
                "details": hardware_blockers[:3],
            }
        )

    evidence_score = max(0, min(100, matched_strength))
    rank_score = min(100, evidence_score)
    status = classify_non_fru_candidate(evidence_score, matches, negatives)
    confidence = classify_non_fru_confidence(rank_score, matches, negatives)
    fault_id = str(fault.get("id", ""))
    boundary_role, boundary_reason = boundary_role_for_candidate(
        {
            "fru_id": fault_id,
            "category": fault.get("category", "non_fru_fault"),
            "candidate_type": "non_fru_fault",
        }
    )

    return {
        "fru_id": fault_id,
        "fru_name": fault.get("name", ""),
        "category": fault.get("category", "non_fru_fault"),
        "candidate_type": "non_fru_fault",
        "fault_origin": "non_fru_fault",
        "boundary_role": boundary_role,
        "boundary_reason": boundary_reason,
        "replacement_required": False,
        "replacement_recommendation": "not_recommended",
        "repair_action": fault.get("repair_action", ""),
        "replaceable": False,
        "diagnosis_role": "non_fru_fault",
        "status": status,
        "confidence": confidence,
        "rank_score": rank_score,
        "evidence_score": evidence_score,
        "collection_score": 0,
        "readiness": "contextual",
        "matched_rule_count": len(matches),
        "negative_rule_count": len(negatives),
        "missing_rule_count": len(missing_rules),
        "matched_evidence": matches,
        "negative_evidence": negatives,
        "missing_evidence": missing_rules,
        "next_actions": build_non_fru_next_actions(fault_id, fault),
        "explanation": explain_non_fru_candidate(fault, status, evidence_score, matches),
    }


def apply_graph_inference_to_candidates(
    candidates: list[dict[str, Any]],
    graph_inference: dict[str, Any],
) -> list[dict[str, Any]]:
    """Blend graph posterior into legacy candidates while preserving compatibility."""

    by_candidate = {
        str(item.get("id", "")): item
        for item in graph_inference.get("candidate_ranking", [])
    }
    adjusted: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("fru_id", ""))
        graph_item = by_candidate.get(candidate_id)
        if not graph_item:
            adjusted.append(candidate)
            continue
        graph_score = int(round(float(graph_item.get("posterior", 0.0) or 0.0) * 100))
        support = float(graph_item.get("support", 0.0) or 0.0)
        conflict = float(graph_item.get("conflict", 0.0) or 0.0)
        legacy_score = int(candidate.get("rank_score", 0) or 0)
        active_test_bonus = 12 if any(
            item.get("type") == "active_test"
            for item in candidate.get("matched_evidence", [])
        ) else 0
        blended_score = max(
            legacy_score,
            min(100, round(legacy_score * 0.68 + graph_score * 0.32 + active_test_bonus)),
        )
        candidate = {
            **candidate,
            "rank_score": blended_score,
            "graph_score": graph_score,
            "graph_posterior": graph_item.get("posterior", 0.0),
            "graph_support": round(support, 4),
            "graph_conflict": round(conflict, 4),
            "graph_supporting_paths": graph_item.get("supporting_paths", [])[:4],
            "graph_conflicting_paths": graph_item.get("conflicting_paths", [])[:4],
        }
        if graph_score >= 65 and support > conflict and candidate.get("status") in {"possible", "needs_data", "no_evidence"}:
            candidate["status"] = "possible"
        if graph_score >= 78 and support >= conflict + 0.4 and candidate.get("status") != "suspect":
            candidate["status"] = "suspect"
        candidate["confidence"] = classify_graph_adjusted_confidence(candidate)
        candidate["explanation"] = append_graph_explanation(candidate)
        adjusted.append(candidate)
    return adjusted


def classify_graph_adjusted_confidence(candidate: dict[str, Any]) -> str:
    graph_score = int(candidate.get("graph_score", 0) or 0)
    rank_score = int(candidate.get("rank_score", 0) or 0)
    support = float(candidate.get("graph_support", 0.0) or 0.0)
    conflict = float(candidate.get("graph_conflict", 0.0) or 0.0)
    if rank_score >= 78 and graph_score >= 55 and support >= conflict:
        return "high"
    if rank_score >= 45 or graph_score >= 35:
        return "medium"
    if support or conflict or candidate.get("matched_rule_count", 0):
        return "low"
    return str(candidate.get("confidence", "none"))


def append_graph_explanation(candidate: dict[str, Any]) -> str:
    base = str(candidate.get("explanation", ""))
    graph_score = int(candidate.get("graph_score", 0) or 0)
    if graph_score <= 0:
        return base
    support = float(candidate.get("graph_support", 0.0) or 0.0)
    conflict = float(candidate.get("graph_conflict", 0.0) or 0.0)
    suffix = f" Graph inference posterior={graph_score}/100, support={support:.2f}, conflict={conflict:.2f}."
    return (base + suffix).strip()


def compact_graph_for_report(graph: dict[str, Any], *, node_limit: int = 80, edge_limit: int = 120) -> dict[str, Any]:
    nodes = sorted(
        graph.get("nodes", []),
        key=lambda item: (
            item.get("type") not in {"candidate", "fault_class", "active_test", "crash_signature"},
            -float(item.get("prior", 0.0) or 0.0),
            item.get("id", ""),
        ),
    )
    edges = sorted(
        graph.get("edges", []),
        key=lambda item: (
            item.get("type") not in {"supports_candidate", "supports_fault", "contradicts_candidate"},
            -float(item.get("weight", 0.0) or 0.0),
        ),
    )
    return {
        "metadata": graph.get("metadata", {}),
        "nodes": nodes[:node_limit],
        "edges": edges[:edge_limit],
        "truncated": len(nodes) > node_limit or len(edges) > edge_limit,
    }


def compact_graph_inference_for_report(graph_inference: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": graph_inference.get("method", {}),
        "candidate_ranking": graph_inference.get("candidate_ranking", [])[:10],
        "fault_ranking": graph_inference.get("fault_ranking", [])[:8],
        "explanations": graph_inference.get("explanations", {}),
        "graph_summary": graph_inference.get("graph_summary", {}),
    }


def evaluate_rule(
    rule: dict[str, Any],
    runtime: dict[str, Any],
    fru: dict[str, Any],
) -> dict[str, Any]:
    evidence_type = str(rule.get("evidence_type", ""))
    if evidence_type == "log_pattern":
        return evaluate_log_pattern(rule, runtime)
    if evidence_type == "metric_threshold":
        return evaluate_metric_threshold(rule, runtime)
    if evidence_type == "health_warning":
        return evaluate_health_warning(rule, runtime, fru)
    if evidence_type == "device_state":
        return evaluate_device_state(rule, runtime, fru)
    if evidence_type == "active_test":
        return evaluate_active_test(rule, runtime)
    if evidence_type == "symptom":
        return {"state": "missing", "details": ["No symptom intake is configured yet."]}
    return {"state": "missing", "details": [f"Unsupported evidence type: {evidence_type}"]}


def evaluate_non_fru_signal(
    rule: dict[str, Any],
    runtime: dict[str, Any],
    fru_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    context = build_non_fru_context(runtime, fru_candidates)
    if not context.strip():
        return {"state": "missing", "details": ["No runtime context has been collected."]}

    extra = evaluate_non_fru_heuristic(str(rule.get("id", "")), runtime, fru_candidates)
    if extra:
        return {
            "state": "match",
            "details": extra.get("details", [])[:5],
            "strength": extra.get("strength", 25),
        }
    return {"state": "negative", "details": ["No matching non-FRU context."]}


def build_non_fru_context(
    runtime: dict[str, Any],
    fru_candidates: list[dict[str, Any]],
) -> str:
    pieces = []
    pieces.extend(flatten_text(runtime.get("events", {})))
    pieces.extend(flatten_text(runtime.get("device_inventory", {})))
    pieces.extend(flatten_text(runtime.get("storage", {})))
    pieces.extend(flatten_text(runtime.get("power", {})))
    pieces.extend(flatten_text(runtime.get("network", {})))
    pieces.extend(
        flatten_text(
            {
                "fru_status": [
                    {
                        "id": item.get("fru_id"),
                        "status": item.get("status"),
                        "matched": item.get("matched_rule_count"),
                    }
                    for item in fru_candidates
                ]
            }
        )
    )
    return " ".join(pieces).casefold()


def evaluate_non_fru_heuristic(
    rule_id: str,
    runtime: dict[str, Any],
    fru_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    result = {"details": [], "strength": 0}
    if rule_id == "driver_events_without_hardware_failure":
        driver_events = matching_event_samples(
            runtime,
            ["driver", "service", "ndis", "security-spp", "activation", "stack"],
        )
        if driver_events and not has_strong_fru_candidate(fru_candidates):
            result["details"].append(f"{len(driver_events)} driver/OS-like event samples without strong FRU evidence")
            result["strength"] = min(80, 30 + len(driver_events) * 8)
    elif rule_id == "firmware_config_events":
        events = matching_event_samples(runtime, ["bios", "firmware", "acpi", "ucmucsi", "policy"])
        if events:
            result["details"].append(f"{len(events)} firmware/config-like event samples")
            result["strength"] = min(70, 25 + len(events) * 10)
    elif rule_id == "external_context_events":
        events = matching_event_samples(runtime, ["networkavailable", "gateway", "router", "dock", "cable", "external"])
        if events:
            result["details"].append(f"{len(events)} external-environment-like event samples")
            result["strength"] = min(60, 25 + len(events) * 8)
    elif rule_id == "intermittent_endpoint_path":
        problem_devices = runtime.get("device_inventory", {}).get("problem_devices", [])
        endpoint = [
            device
            for device in problem_devices
            if any(
                token in " ".join(flatten_text(device)).casefold()
                for token in ["code 43", "descriptor", "usb", "not recognized", "disconnect"]
            )
        ]
        if endpoint:
            result["details"].append(f"{len(endpoint)} intermittent endpoint/problem-device records")
            result["strength"] = min(65, 35 + len(endpoint) * 10)
    elif rule_id == "low_space_or_filesystem_context":
        low_space = [
            volume
            for volume in runtime.get("storage", {}).get("volumes", [])
            if safe_float(volume.get("free_percent"), 100) < 12
        ]
        if low_space:
            result["details"].append(f"{len(low_space)} volume(s) below 12% free space")
            result["strength"] = min(60, 35 + len(low_space) * 8)
    elif rule_id == "maintenance_context":
        events = matching_event_samples(runtime, ["thermal", "overheat", "throttle", "fan"])
        if events:
            result["details"].append(f"{len(events)} maintenance/thermal-like event samples")
            result["strength"] = min(65, 30 + len(events) * 8)
    elif rule_id == "multiple_independent_paths":
        categories = {
            candidate.get("category")
            for candidate in fru_candidates
            if candidate.get("status") == "suspect"
        }
        if len(categories) >= 3:
            result["details"].append(f"strong abnormal evidence spans {len(categories)} FRU categories")
            result["strength"] = min(85, 45 + len(categories) * 10)
    return result


def evaluate_log_pattern(rule: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    patterns = split_patterns(rule.get("pattern"))
    buckets = event_buckets(runtime)
    matched_details = []

    for name, bucket in buckets.items():
        samples = bucket.get("samples", [])
        actionable_count = event_bucket_actionable_count(name, bucket, patterns)
        raw_count = int(bucket.get("total_count", 0) or 0) or int(bucket.get("error_count", 0) or 0) + int(
            bucket.get("warning_count", 0) or 0
        )
        sample_text = " ".join(sample_to_text(sample) for sample in samples)
        bucket_name_match = any(pattern.search(name) for pattern in patterns)
        sample_match = any(pattern.search(sample_text) for pattern in patterns)
        if actionable_count > 0 and (bucket_name_match or sample_match):
            matched_details.append(
                f"{name}: {actionable_count} actionable event(s) after reducing {raw_count} warning/error event(s)"
            )

    if matched_details:
        return {"state": "match", "details": matched_details[:4]}
    if buckets:
        return {"state": "negative", "details": ["No matching actionable warning/error events after noise reduction."]}
    return {"state": "missing", "details": ["Event logs have not been collected."]}


def evaluate_metric_threshold(rule: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    metric = str(rule.get("metric", "") or "")
    values = get_metric_values(runtime, metric)
    values = [value for value in values if value not in MISSING_VALUES]
    if not values:
        return {"state": "missing", "details": [f"Metric missing: {metric or '-'}"]}

    operator = str(rule.get("operator", "") or "")
    threshold = rule.get("threshold")
    matches = [
        value
        for value in values
        if compare_threshold(value, operator, threshold)
    ]
    if matches:
        return {
            "state": "match",
            "details": [f"{metric} {operator} {threshold}: {format_detail_value(matches[0])}"],
        }
    return {
        "state": "negative",
        "details": [f"{metric} values within threshold."],
    }


def evaluate_health_warning(
    rule: dict[str, Any],
    runtime: dict[str, Any],
    fru: dict[str, Any],
) -> dict[str, Any]:
    patterns = split_patterns(rule.get("pattern"))
    texts = []
    for section_name in infer_sections_for_fru(fru):
        section = runtime.get(section_name, {})
        texts.extend(flatten_text(section))
    text = " ".join(texts)
    if not text.strip():
        return {"state": "missing", "details": ["Health section is missing."]}

    warning_tokens = [
        "warning",
        "error",
        "critical",
        "unhealthy",
        "degraded",
        "predictive failure",
        "bad block",
        "failed",
    ]
    if any(pattern.search(text) for pattern in patterns) or any(token in text.casefold() for token in warning_tokens):
        return {"state": "match", "details": ["Health data contains warning terms."]}
    return {"state": "negative", "details": ["Health data has no warning terms."]}


def evaluate_device_state(
    rule: dict[str, Any],
    runtime: dict[str, Any],
    fru: dict[str, Any],
) -> dict[str, Any]:
    problem_devices = runtime.get("device_inventory", {}).get("problem_devices", [])
    relevant = [
        device
        for device in problem_devices
        if device_relevant_to_fru(device, fru, rule)
    ]
    if relevant:
        return {
            "state": "match",
            "details": [
                f"{device.get('name', 'device')} problem_code={device.get('problem_code', '-')}"
                for device in relevant[:4]
            ],
        }

    if problem_devices:
        return {"state": "negative", "details": ["Problem devices exist but do not match this FRU."]}
    if "device_inventory" in runtime:
        return {"state": "negative", "details": ["No matching PnP problem devices."]}
    return {"state": "missing", "details": ["Device inventory has not been collected."]}


def evaluate_implicit_device_state(
    fru: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    problem_devices = runtime.get("device_inventory", {}).get("problem_devices", [])
    relevant = [
        device
        for device in problem_devices
        if device_relevant_to_fru(device, fru, {"pattern": ""})
    ]
    if not relevant:
        return {"state": "negative", "details": []}
    return {
        "state": "match",
        "details": [
            f"{device.get('name', 'device')} problem_code={device.get('problem_code', '-')}"
            for device in relevant[:4]
        ],
    }


def evaluate_active_test(rule: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    test_values = collect_test_values(rule, runtime)
    if not test_values:
        return {"state": "missing", "details": ["Active test result is not recorded."]}

    pattern_text = str(rule.get("pattern", "") or "")
    patterns = split_patterns(pattern_text)
    matched = []
    passed = []
    for key, value in test_values:
        text = str(value).casefold()
        if value in MISSING_VALUES:
            continue
        if patterns and any(pattern.search(text) for pattern in patterns):
            matched.append((key, value))
        elif any(token in text for token in NEGATIVE_TEST_VALUES):
            matched.append((key, value))
        elif any(token in text for token in POSITIVE_TEST_VALUES):
            passed.append((key, value))

    if matched:
        return {
            "state": "match",
            "details": [f"{key}={value}" for key, value in matched[:4]],
        }
    if passed:
        return {
            "state": "negative",
            "details": [f"{key}={value}" for key, value in passed[:4]],
        }
    return {"state": "missing", "details": ["Active test is present but inconclusive."]}


def collect_test_values(rule: dict[str, Any], runtime: dict[str, Any]) -> list[tuple[str, Any]]:
    tests = runtime.get("tests", {})
    source = str(rule.get("source", "") or "")
    candidate_sections = active_test_sections(source, str(rule.get("id", "")))
    values = []
    for section in candidate_sections:
        value = tests.get(section)
        if isinstance(value, dict):
            for key, nested_value in value.items():
                values.append((f"tests.{section}.{key}", nested_value))
    if values or candidate_sections:
        return values

    for section, value in tests.items():
        if not isinstance(value, dict):
            continue
        for key, nested_value in value.items():
            values.append((f"tests.{section}.{key}", nested_value))
    return values


def active_test_sections(source: str, rule_id: str) -> list[str]:
    text = f"{source} {rule_id}".casefold()
    mapping = [
        ("power", ["power"]),
        ("storage", ["storage"]),
        ("memory", ["memory"]),
        ("network", ["network"]),
        ("bluetooth", ["network"]),
        ("thermal", ["thermal"]),
        ("fan", ["thermal"]),
        ("display", ["display"]),
        ("camera", ["camera"]),
        ("keyboard", ["input"]),
        ("touchpad", ["input"]),
        ("input", ["input"]),
        ("audio", ["audio", "io"]),
        ("speaker", ["audio"]),
        ("led", ["led"]),
        ("port", ["io"]),
        ("usb", ["io"]),
        ("mainboard", ["mainboard"]),
    ]
    sections = []
    for token, names in mapping:
        if token in text:
            sections.extend(names)
    return list(dict.fromkeys(sections))


def build_candidate_next_actions(
    missing_rules: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, str]]:
    actions = []
    for rule in missing_rules[:3]:
        actions.append(
            {
                "priority": "diagnosis_rule",
                "key": rule.get("rule_id", ""),
                "source": rule.get("source", ""),
                "description": rule.get("description", ""),
            }
        )
    for action in plan.get("next_actions", [])[:3]:
        actions.append(
            {
                "priority": str(action.get("priority", "")),
                "key": str(action.get("key", "")),
                "source": str(action.get("source", "")),
                "description": str(action.get("description", "")),
            }
        )
    deduped = []
    seen = set()
    for action in actions:
        marker = (action["priority"], action["key"], action["description"])
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(action)
    return deduped[:5]


def summarize_diagnosis(
    candidates: list[dict[str, Any]],
    runtime: dict[str, Any],
    leading: dict[str, Any] | None,
    actionable: list[dict[str, Any]],
) -> dict[str, Any]:
    fault_origin = "unknown"
    replacement_recommendation = "collect_more_evidence"
    replacement_required = False
    why_not_replace: list[str] = []

    if not candidates:
        status = "missing_profile"
        headline = "No FRU profile is loaded."
    elif leading and leading.get("candidate_type") == "non_fru_fault" and leading["status"] in {"suspect", "possible"}:
        fault_origin = "non_fru_fault"
        replacement_recommendation = "not_recommended"
        headline = f"Current evidence points first to {leading['fru_name'] or leading['fru_id']}, not a replaceable module."
        status = "non_fru_found" if leading["status"] == "suspect" else "non_fru_possible"
        why_not_replace = build_why_not_replace(candidates)
    elif leading and leading["status"] == "suspect":
        status = "suspect_found"
        fault_origin = leading.get("fault_origin") or leading.get("candidate_type", "replaceable_fru")
        replacement_recommendation = leading.get("replacement_recommendation", "recommended_after_confirmation")
        replacement_required = bool(leading.get("replacement_required", False))
        headline = f"{leading['fru_name'] or leading['fru_id']} is the leading suspect."
    elif actionable:
        status = "possible_found"
        fault_origin = "mixed_or_uncertain"
        replacement_recommendation = "not_yet_recommended"
        why_not_replace = build_why_not_replace(candidates)
        headline = f"{actionable[0]['fru_name'] or actionable[0]['fru_id']} has weak or partial evidence."
    else:
        status = "insufficient_evidence"
        fault_origin = "mixed_or_uncertain"
        replacement_recommendation = "collect_more_evidence"
        why_not_replace = build_why_not_replace(candidates)
        headline = "No strong abnormal FRU evidence is available yet."

    classification = classify_runtime_fault(runtime, leading)
    boundary = assess_boundary(runtime, classification, candidates[:5], [])
    classification["boundary_assessment"] = boundary
    decision = decide_after_classification(classification)

    return {
        "status": status,
        "headline": headline,
        "fault_origin": fault_origin,
        "fault_class": classification.get("predicted_fault_class", fault_origin),
        "boundary_assessment": boundary,
        "replacement_recommendation": replacement_recommendation,
        "replacement_required": replacement_required,
        "why_not_replace": why_not_replace,
        "classification": classification,
        "decision": decision,
        "candidate_count": len(candidates),
        "actionable_count": len(actionable),
        "top_fru_id": leading.get("fru_id") if leading else "",
        "top_candidate_type": leading.get("candidate_type", "replaceable_fru") if leading else "",
        "top_score": leading.get("rank_score", 0) if leading else 0,
        "top_confidence": leading.get("confidence", "none") if leading else "none",
        "event_count": runtime_actionable_event_count(runtime.get("events", {})),
        "raw_event_count": int(runtime.get("events", {}).get("total_warning_error_count", 0) or 0),
        "problem_device_count": int(runtime.get("device_inventory", {}).get("problem_device_count", 0) or 0),
    }


def classify_runtime_fault(runtime: dict[str, Any], leading: dict[str, Any] | None) -> dict[str, Any]:
    symptoms = []
    if crash_dump_is_available(runtime.get("crash_dump")):
        symptoms.append("bsod")
    if leading:
        symptoms.append(str(leading.get("fru_id", "")))
        symptoms.append(str(leading.get("category", "")))
    classification = classify_fault_case(
        {
            "symptom": symptoms,
            "evidence": {
                "inventory": {
                    "device_inventory": runtime.get("device_inventory", {}),
                    "system": runtime.get("system", {}),
                },
                "logs": {"events": runtime.get("events", {})},
                "metrics": {
                    "power": runtime.get("power", {}),
                    "battery": runtime.get("battery", {}),
                    "storage": runtime.get("storage", {}),
                    "memory": runtime.get("memory", {}),
                    "network": runtime.get("network", {}),
                    "thermal": runtime.get("thermal", {}),
                },
                "active_tests": runtime.get("tests", {}),
                "crash_dump": runtime.get("crash_dump", {}),
            },
        }
    )
    if leading and leading.get("candidate_type") != "non_fru_fault" and leading.get("status") == "suspect":
        classification = {
            **classification,
            "predicted_fault_class": "hardware_fault",
            "class_ranking": merge_class_ranking(classification.get("class_ranking", []), "hardware_fault", 0.72),
        }
    return classification


def merge_class_ranking(ranking: list[dict[str, Any]], fault_class: str, score: float) -> list[dict[str, Any]]:
    merged = [dict(item) for item in ranking]
    for item in merged:
        if item.get("fault_class") == fault_class:
            item["score"] = max(float(item.get("score", 0.0) or 0.0), score)
            break
    else:
        merged.append({"fault_class": fault_class, "score": score})
    return sorted(merged, key=lambda item: item.get("score", 0), reverse=True)


def build_non_fru_risks(
    runtime: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    risks = []
    candidates = candidates or []
    for candidate in candidates:
        if (
            candidate.get("candidate_type") == "non_fru_fault"
            and candidate.get("status") in {"suspect", "possible"}
        ):
            risks.append(
                {
                    "category": str(candidate.get("category", "non_fru_fault")),
                    "risk": str(candidate.get("explanation", "")),
                }
            )
    events = runtime.get("events", {})
    if int(events.get("total_warning_error_count", 0) or 0) == 0:
        risks.append(
            {
                "category": "采集窗口",
                "risk": "当前日志窗口没有异常事件，建议围绕故障发生时间重新采集。",
            }
        )
    if runtime.get("storage", {}).get("volumes"):
        low_space = [
            volume
            for volume in runtime["storage"]["volumes"]
            if safe_float(volume.get("free_percent"), 100) < 12
        ]
        if low_space:
            risks.append(
                {
                    "category": "非硬件因素",
                    "risk": "存在低剩余空间卷，可能造成卡顿、更新失败或应用异常。",
                }
            )
    return risks


def build_why_not_replace(candidates: list[dict[str, Any]]) -> list[str]:
    reasons = []
    non_fru = [
        item
        for item in candidates
        if item.get("candidate_type") == "non_fru_fault"
        and item.get("status") in {"suspect", "possible"}
    ]
    strong_fru = [
        item
        for item in candidates
        if item.get("candidate_type") != "non_fru_fault"
        and item.get("status") == "suspect"
    ]
    if non_fru:
        reasons.append("Non-FRU explanations have equal or stronger evidence than replaceable modules.")
    if not strong_fru:
        reasons.append("No replaceable FRU has strong abnormal evidence yet.")
    if any(item.get("missing_rule_count", 0) > 0 for item in candidates[:5]):
        reasons.append("Important active tests or diagnosis rules are still missing.")
    return reasons[:4]


def normalize_serviceability(fru: dict[str, Any]) -> dict[str, Any]:
    raw = fru.get("serviceability")
    if isinstance(raw, dict):
        service_type = raw.get("type") or default_serviceability_type_for_fru(fru)
        return {
            "type": service_type,
            "level": raw.get("level") or default_serviceability_level(service_type),
            "replacement_target": raw.get("replacement_target") or (
                fru.get("id") if service_type in {"replaceable_fru", "serviceable_assembly"} else None
            ),
            "parent_assembly": raw.get("parent_assembly"),
            "requires_disassembly": bool(raw.get("requires_disassembly", True)),
            "cost_level": raw.get("cost_level", "unknown"),
            "confidence_required": raw.get("confidence_required", "high"),
            "action": raw.get("action") or default_service_action(service_type, str(fru.get("id", ""))),
            "notes": raw.get("notes", []),
        }

    service_type = default_serviceability_type_for_fru(fru)
    return {
        "type": service_type,
        "level": default_serviceability_level(service_type),
        "replacement_target": fru.get("id") if service_type in {"replaceable_fru", "serviceable_assembly"} else None,
        "parent_assembly": None if fru.get("replaceable") else "motherboard",
        "requires_disassembly": service_type not in {"external_part", "non_fru_fault", "maintenance_condition"},
        "cost_level": "unknown",
        "confidence_required": "high",
        "action": default_service_action(service_type, str(fru.get("id", ""))),
        "notes": [],
    }


def default_serviceability_type_for_fru(fru: dict[str, Any]) -> str:
    if fru.get("diagnosis_role") == "subsystem":
        return "non_replaceable_subsystem"
    if fru.get("replaceable", True):
        return "replaceable_fru"
    return "non_replaceable_subsystem"


def default_serviceability_level(service_type: str) -> str:
    return {
        "replaceable_fru": "field_replaceable",
        "serviceable_assembly": "assembly_replaceable",
        "non_replaceable_subsystem": "not_individually_replaceable",
        "non_fru_fault": "not_replaceable",
        "external_part": "external",
        "maintenance_condition": "not_replaceable",
    }.get(service_type, "field_replaceable")


def default_service_action(service_type: str, fru_id: str) -> str:
    if service_type == "replaceable_fru":
        return f"Replace or reseat {fru_id} after sufficient evidence."
    if service_type == "serviceable_assembly":
        return f"Repair or replace the parent assembly for {fru_id}."
    if service_type == "non_replaceable_subsystem":
        return f"Use {fru_id} as evidence for its parent assembly; do not replace it directly."
    if service_type == "external_part":
        return f"Swap or validate external part {fru_id}."
    return "Do not replace a hardware module before excluding this condition."


def replacement_recommendation_for_candidate(status: str, serviceability: dict[str, Any]) -> str:
    service_type = str(serviceability.get("type", ""))
    if service_type in {"non_replaceable_subsystem", "non_fru_fault", "maintenance_condition"}:
        return "not_recommended"
    if status == "suspect":
        required = str(serviceability.get("confidence_required", "high"))
        return "recommended_after_confirmation" if required == "high" else "recommended"
    if status == "possible":
        return "not_yet_recommended"
    return "collect_more_evidence"


def classify_candidate(
    evidence_score: int,
    matches: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> str:
    has_failed_active_test = any(match.get("type") == "active_test" for match in matches)
    if has_failed_active_test and evidence_score >= 45:
        return "suspect"
    if evidence_score >= 55 and matches:
        return "suspect"
    if evidence_score >= 25 and matches:
        return "possible"
    if negatives and not matches:
        return "unlikely"
    if matches:
        return "needs_data"
    if coverage.get("readiness") in {"missing", "partial"}:
        return "needs_data"
    return "no_evidence"


def classify_non_fru_candidate(
    evidence_score: int,
    matches: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> str:
    if evidence_score >= 60 and matches:
        return "suspect"
    if evidence_score >= 25 and matches:
        return "possible"
    if negatives and not matches:
        return "unlikely"
    if matches:
        return "needs_data"
    return "no_evidence"


def classify_confidence(
    rank_score: int,
    coverage: dict[str, Any],
    matches: list[dict[str, Any]],
    missing_rules: list[dict[str, Any]],
) -> str:
    readiness = coverage.get("readiness", "")
    if rank_score >= 75 and readiness in {"ready", "passive_ready"}:
        return "high"
    if rank_score >= 45 and matches:
        return "medium"
    if matches or missing_rules:
        return "low"
    return "none"


def classify_non_fru_confidence(
    rank_score: int,
    matches: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> str:
    if rank_score >= 75 and matches:
        return "high"
    if rank_score >= 45 and matches:
        return "medium"
    if matches or negatives:
        return "low"
    return "none"


def explain_candidate(
    fru: dict[str, Any],
    status: str,
    evidence_score: int,
    matches: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
) -> str:
    name = fru.get("name") or fru.get("id") or "FRU"
    if status == "suspect":
        return f"{name} has abnormal evidence with score {evidence_score}."
    if status == "possible":
        return f"{name} has partial abnormal evidence; collect more evidence before replacement."
    if status == "unlikely" and negatives:
        return f"{name} has collected evidence that does not currently show this failure mode."
    if matches:
        return f"{name} has weak evidence but confidence is limited."
    return f"{name} has no abnormal evidence yet."


def explain_non_fru_candidate(
    fault: dict[str, Any],
    status: str,
    evidence_score: int,
    matches: list[dict[str, Any]],
) -> str:
    name = fault.get("name") or fault.get("id") or "Non-FRU fault"
    if status == "suspect":
        return f"{name} is a stronger explanation than replacing a module."
    if status == "possible":
        return f"{name} is plausible; exclude it before hardware replacement."
    if matches:
        return f"{name} has weak contextual evidence."
    return f"{name} has no supporting context yet."


def build_non_fru_next_actions(fault_id: str, fault: dict[str, Any]) -> list[dict[str, str]]:
    common = {
        "driver_or_os_fault": [
            ("driver_check", "Update or roll back the driver related to the failing subsystem."),
            ("system_repair", "Run OS repair checks and review service/application errors."),
        ],
        "firmware_or_config_fault": [
            ("firmware_check", "Check BIOS/EC version and device enablement settings."),
            ("policy_check", "Review power, thermal, security, and device policies."),
        ],
        "external_environment_fault": [
            ("swap_external", "Retest with known-good cable, charger, router, dock, or peripheral."),
            ("controlled_environment", "Repeat the symptom in a controlled environment."),
        ],
        "connector_or_interconnect_fault": [
            ("reseat_path", "Inspect and reseat the suspected cable/connector path."),
            ("movement_test", "Run a gentle movement/intermittency test before replacing the endpoint module."),
        ],
        "data_or_filesystem_fault": [
            ("free_space", "Free disk space and rerun the workload."),
            ("filesystem_repair", "Run filesystem and OS image repair before replacing storage."),
        ],
        "maintenance_condition_fault": [
            ("clean_vents", "Check vents, dust, fan path, and thermal paste condition."),
            ("calibration", "Run battery or thermal calibration when applicable."),
        ],
        "multi_fault_or_damage": [
            ("inspect_damage", "Inspect for liquid, corrosion, drop, or overvoltage damage."),
            ("multi_path_test", "Test multiple independent paths before single-FRU replacement."),
        ],
    }
    actions = common.get(fault_id, [("non_fru_check", str(fault.get("repair_action", "")))])
    return [
        {
            "priority": "non_fru_check",
            "key": key,
            "source": "repair_workflow",
            "description": description,
        }
        for key, description in actions
    ]


def has_strong_fru_candidate(candidates: list[dict[str, Any]]) -> bool:
    return any(
        item.get("candidate_type") != "non_fru_fault"
        and item.get("status") == "suspect"
        for item in candidates
    )


def hardware_replacement_blockers(candidates: list[dict[str, Any]]) -> list[str]:
    return [
        f"{item.get('fru_name') or item.get('fru_id')} has strong FRU evidence"
        for item in candidates
        if item.get("candidate_type") != "non_fru_fault"
        and item.get("status") == "suspect"
    ]


def matching_event_samples(runtime: dict[str, Any], tokens: list[str]) -> list[str]:
    matches = []
    lowered_tokens = [token.casefold() for token in tokens]
    token_patterns = [re.compile(re.escape(token), re.IGNORECASE) for token in tokens if token]
    for bucket in event_buckets(runtime).values():
        for sample in bucket.get("samples", []):
            text = sample_to_text(sample).casefold()
            if any(token in text for token in lowered_tokens) and sample_is_actionable(
                sample,
                rule_patterns=token_patterns,
            ):
                matches.append(text[:180])
    return matches


def event_buckets(runtime: dict[str, Any]) -> dict[str, dict[str, Any]]:
    events = runtime.get("events", {})
    return {
        key: value
        for key, value in events.items()
        if isinstance(value, dict) and key not in {"collection"}
    }


def sample_to_text(sample: Any) -> str:
    if isinstance(sample, dict):
        return " ".join(str(value) for value in sample.values() if value is not None)
    return str(sample)


def get_metric_values(runtime: dict[str, Any], metric: str) -> list[Any]:
    candidates = [metric]
    aliases = {
        "full_charge_capacity_ratio": "battery.full_charge_capacity_ratio",
        "thermal_throttle_ratio": "thermal.thermal_throttle_ratio",
        "fan_response_error": "thermal.fan_response_error",
    }
    if metric in aliases:
        candidates.append(aliases[metric])

    values = []
    for candidate in candidates:
        values.extend(get_nested_values(runtime, candidate.split(".")))
    return values


def get_nested_values(current: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return [current]
    part = parts[0]
    rest = parts[1:]
    is_array = part.endswith("[]")
    clean_part = part[:-2] if is_array else part
    if not isinstance(current, dict) or clean_part not in current:
        return []
    next_value = current[clean_part]
    if is_array:
        if not isinstance(next_value, list):
            return []
        values: list[Any] = []
        for item in next_value:
            values.extend(get_nested_values(item, rest))
        return values
    return get_nested_values(next_value, rest)


def compare_threshold(value: Any, operator: str, threshold: Any) -> bool:
    left = safe_float(value, None)
    right = safe_float(threshold, None)
    if left is None or right is None:
        return False
    return {
        ">": left > right,
        ">=": left >= right,
        "<": left < right,
        "<=": left <= right,
        "==": left == right,
        "=": left == right,
        "!=": left != right,
    }.get(operator, False)


def device_relevant_to_fru(
    device: dict[str, Any],
    fru: dict[str, Any],
    rule: dict[str, Any],
) -> bool:
    text = " ".join(flatten_text(device)).casefold()
    aliases = [str(alias).casefold() for alias in fru.get("aliases", [])]
    category = str(fru.get("category", "")).casefold()
    fru_id = str(fru.get("id", "")).casefold()
    if "mainboard" in category:
        return is_platform_level_problem_device(text)

    pattern_match = any(pattern.search(text) for pattern in split_patterns(rule.get("pattern")))
    alias_match = any(alias and alias in text for alias in aliases)
    source_text = f"{rule.get('id', '')} {rule.get('pattern', '')}".casefold()
    semantic_match = (
        ("usb" in text and any(token in source_text for token in ["usb", "port", "io_board"]))
        or ("audio" in text and any(token in source_text for token in ["audio", "speaker"]))
        or ("battery" in text and "battery" in source_text)
        or ("display" in text and "display" in source_text)
        or ("keyboard" in text and "keyboard" in source_text)
        or ("touchpad" in text and "touchpad" in source_text)
        or ("network" in text and any(token in source_text for token in ["network", "wlan", "bluetooth"]))
        or ("bluetooth" in text and any(token in source_text for token in ["network", "wlan", "bluetooth"]))
    )
    category_match = (
        ("usb" in text and fru_id in {"io_board", "usb_board"})
        or ("battery" in text and "power" in category)
        or ("display" in text and "display" in category)
        or ("keyboard" in text and "input" in category)
        or ("touchpad" in text and "input" in category)
        or ("network" in text and "communication" in category)
        or ("bluetooth" in text and "communication" in category)
    )
    return pattern_match or alias_match or semantic_match or category_match


def infer_sections_for_fru(fru: dict[str, Any]) -> list[str]:
    category = str(fru.get("category", ""))
    return {
        "PowerFRU": ["power", "battery"],
        "StorageFRU": ["storage"],
        "ComputeFRU": ["memory", "performance"],
        "CommunicationFRU": ["network"],
        "ThermalFRU": ["thermal", "performance"],
        "DisplayFRU": ["display"],
        "InputFRU": ["input"],
        "InterfaceFRU": ["usb", "audio", "network"],
        "SensorFRU": ["camera"],
        "MainboardFRU": ["mainboard", "device_inventory", "bios"],
    }.get(category, ["device_inventory"])


def is_platform_level_problem_device(text: str) -> bool:
    platform_tokens = [
        "whea",
        "pci",
        "pcie",
        "acpi",
        "firmware",
        "processor",
        "system",
        "baseboard",
        "memory",
        "controller",
    ]
    endpoint_tokens = [
        "usb device",
        "audio",
        "speaker",
        "keyboard",
        "touchpad",
        "camera",
        "bluetooth",
        "wireless",
        "monitor",
        "disk",
    ]
    return any(token in text for token in platform_tokens) and not any(
        token in text for token in endpoint_tokens
    )


def split_patterns(pattern: Any) -> list[re.Pattern[str]]:
    text = str(pattern or "").strip()
    if not text:
        return []
    return [
        re.compile(part.strip(), re.IGNORECASE)
        for part in text.split("|")
        if part.strip()
    ]


def flatten_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        result = []
        for key, nested in value.items():
            result.append(str(key))
            result.extend(flatten_text(nested))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(flatten_text(item))
        return result
    if value is None:
        return []
    return [str(value)]


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_detail_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
