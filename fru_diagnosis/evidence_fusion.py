"""Research-oriented evidence fusion for repair diagnosis candidates."""

from __future__ import annotations

import math
from typing import Any


def build_fusion_candidates(
    diagnosis_report: dict[str, Any],
    *,
    next_tests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert diagnosis candidates into multi-source belief outputs."""

    tests_by_target = {}
    for test in next_tests or []:
        for target in test.get("targets", []):
            tests_by_target.setdefault(target, []).append(test)

    graph_by_candidate = {
        str(item.get("id", "")): item
        for item in diagnosis_report.get("graph_inference", {}).get("candidate_ranking", [])
    }
    fused = []
    for candidate in diagnosis_report.get("candidates", []):
        support = list(candidate.get("matched_evidence", []))
        conflict = list(candidate.get("negative_evidence", []))
        missing = list(candidate.get("missing_evidence", []))
        candidate_id = str(candidate.get("fru_id", ""))
        graph_item = graph_by_candidate.get(candidate_id, {})
        source_masses = build_source_masses(candidate, graph_item, support, conflict, missing)
        combined = combine_beliefs_dempster_shafer(source_masses)
        belief = combined["support"]
        uncertainty = combined["uncertain"]
        fused.append(
            {
                "candidate": candidate_id,
                "type": candidate.get("candidate_type", "replaceable_fru"),
                "belief": belief,
                "uncertainty": uncertainty,
                "against": combined["against"],
                "source_masses": source_masses,
                "source_reliability": source_reliability(candidate, graph_item),
                "supporting_evidence": support,
                "conflicting_evidence": conflict,
                "graph_supporting_paths": candidate.get("graph_supporting_paths", []),
                "graph_conflicting_paths": candidate.get("graph_conflicting_paths", []),
                "next_best_test": select_next_best_test(
                    candidate,
                    tests_by_target.get(candidate.get("fru_id", ""), []),
                ),
            }
        )
    return sorted(fused, key=lambda item: (item["belief"], -item["uncertainty"]), reverse=True)


def score_to_belief(score: Any, support: list[Any], conflict: list[Any]) -> float:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        numeric = 0.0
    support_bonus = min(0.12, len(support) * 0.04)
    conflict_penalty = min(0.2, len(conflict) * 0.05)
    return round(max(0.0, min(1.0, numeric / 100.0 + support_bonus - conflict_penalty)), 4)


def build_source_masses(
    candidate: dict[str, Any],
    graph_item: dict[str, Any],
    support: list[Any],
    conflict: list[Any],
    missing: list[Any],
) -> list[dict[str, float]]:
    """Build evidence masses from legacy rules, graph inference, tests, and uncertainty."""

    legacy_belief = score_to_belief(candidate.get("evidence_score", candidate.get("rank_score", 0)), support, conflict)
    legacy_against = min(0.45, len(conflict) * 0.08)
    reliability = source_reliability(candidate, graph_item)
    masses = [
        normalize_mass(
            {
                "support": legacy_belief * 0.75 * reliability["legacy"],
                "against": legacy_against * reliability["legacy"],
                "uncertain": 1.0 - reliability["legacy"]
                + estimate_uncertainty(support, conflict, missing, candidate) * reliability["legacy"],
            }
        )
    ]
    graph_support = float(candidate.get("graph_support", graph_item.get("support", 0.0)) or 0.0)
    graph_conflict = float(candidate.get("graph_conflict", graph_item.get("conflict", 0.0)) or 0.0)
    graph_posterior = float(candidate.get("graph_posterior", graph_item.get("posterior", 0.0)) or 0.0)
    if graph_support or graph_conflict or graph_posterior:
        masses.append(
            normalize_mass(
                {
                    "support": min(0.92, graph_posterior + graph_support * 0.12) * reliability["graph"],
                    "against": min(0.75, graph_conflict * 0.16) * reliability["graph"],
                    "uncertain": 1.0 - reliability["graph"]
                    + max(0.08, 0.55 - graph_support * 0.05) * reliability["graph"],
                }
            )
        )
    if any(item.get("type") == "active_test" for item in support):
        masses.append({"support": 0.82, "against": 0.04, "uncertain": 0.14})
    if any(item.get("type") == "active_test" for item in conflict):
        masses.append({"support": 0.05, "against": 0.7, "uncertain": 0.25})
    return [{key: round(value, 4) for key, value in normalize_mass(mass).items()} for mass in masses]


def source_reliability(
    candidate: dict[str, Any],
    graph_item: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Bound source confidence so missing or low-quality modalities add uncertainty."""

    graph_item = graph_item or {}
    supplied = candidate.get("source_quality", graph_item.get("source_quality", {}))
    if not isinstance(supplied, dict):
        supplied = {}
    values = {
        "legacy": supplied.get("logs", supplied.get("legacy", 1.0)),
        "graph": supplied.get("graph", supplied.get("metrics", 1.0)),
    }
    result: dict[str, float] = {}
    for name, value in values.items():
        try:
            result[name] = round(max(0.0, min(1.0, float(value))), 4)
        except (TypeError, ValueError):
            result[name] = 0.0
    return result


def estimate_uncertainty(
    support: list[Any],
    conflict: list[Any],
    missing: list[Any],
    candidate: dict[str, Any],
) -> float:
    evidence_count = len(support) + len(conflict)
    missing_count = len(missing)
    base = 0.35 if evidence_count else 0.75
    missing_penalty = min(0.35, missing_count * 0.08)
    readiness = candidate.get("readiness")
    readiness_penalty = 0.15 if readiness in {"missing", "partial"} else 0.0
    return round(max(0.0, min(1.0, base + missing_penalty + readiness_penalty)), 4)


def select_next_best_test(
    candidate: dict[str, Any],
    tests: list[dict[str, Any]],
) -> str:
    if tests:
        ranked = sorted(
            tests,
            key=lambda item: information_gain_per_cost(item),
            reverse=True,
        )
        return str(ranked[0].get("id", ""))
    actions = candidate.get("next_actions", [])
    return str(actions[0].get("key", "")) if actions else ""


def information_gain_per_cost(test: dict[str, Any]) -> float:
    gain = float(test.get("expected_information_gain", 0.1) or 0.1)
    cost = float(test.get("cost", 1.0) or 1.0)
    risk = float(test.get("risk", 0.0) or 0.0)
    return gain / max(0.1, cost + risk)


def combine_beliefs_dempster_shafer(masses: list[dict[str, float]]) -> dict[str, float]:
    """Small Dempster-Shafer combiner for experimental baselines."""

    combined = {"support": 0.0, "against": 0.0, "uncertain": 1.0}
    for mass in masses:
        combined = combine_two_masses(combined, normalize_mass(mass))
    return {key: round(value, 4) for key, value in combined.items()}


def normalize_mass(mass: dict[str, float]) -> dict[str, float]:
    support = float(mass.get("support", 0.0) or 0.0)
    against = float(mass.get("against", 0.0) or 0.0)
    uncertain = float(mass.get("uncertain", 1.0 - support - against) or 0.0)
    total = support + against + uncertain
    if total <= 0:
        return {"support": 0.0, "against": 0.0, "uncertain": 1.0}
    return {
        "support": support / total,
        "against": against / total,
        "uncertain": uncertain / total,
    }


def combine_two_masses(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    conflict = left["support"] * right["against"] + left["against"] * right["support"]
    denominator = 1.0 - conflict
    if math.isclose(denominator, 0.0):
        return {"support": 0.0, "against": 0.0, "uncertain": 1.0}
    return {
        "support": (
            left["support"] * right["support"]
            + left["support"] * right["uncertain"]
            + left["uncertain"] * right["support"]
        )
        / denominator,
        "against": (
            left["against"] * right["against"]
            + left["against"] * right["uncertain"]
            + left["uncertain"] * right["against"]
        )
        / denominator,
        "uncertain": (left["uncertain"] * right["uncertain"]) / denominator,
    }
