"""Graph-based diagnostic inference.

This module provides a dependency-free graph baseline that can later be
replaced by R-GCN/HGT training. It uses typed edge propagation plus direct
support/conflict aggregation, so the output remains explainable enough for the
repair workflow.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


SUPPORT_EDGE_TYPES = {"supports_candidate", "supports_fault", "maps_to_fault"}
CONFLICT_EDGE_TYPES = {"contradicts_candidate", "contradicts_fault"}
STRUCTURAL_EDGE_TYPES = {"contains", "emitted_by", "observes_component", "part_of"}


def infer_diagnostic_graph(
    graph: dict[str, Any],
    *,
    restart_prob: float = 0.35,
    iterations: int = 18,
) -> dict[str, Any]:
    """Run a typed propagation baseline over a diagnostic graph."""

    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    edges = [edge for edge in graph.get("edges", []) if edge.get("source") in nodes and edge.get("target") in nodes]
    adjacency = build_adjacency(edges)
    seed = seed_distribution(nodes)
    posterior = personalized_pagerank(nodes, adjacency, seed, restart_prob=restart_prob, iterations=iterations)
    direct = direct_evidence_scores(nodes, edges)
    candidate_scores = rank_nodes("candidate", nodes, posterior, direct)
    fault_scores = rank_nodes("fault_class", nodes, posterior, direct)
    explanations = explain_top_paths(nodes, edges, candidate_scores[:8] + fault_scores[:6])
    return {
        "method": {
            "name": "heterogeneous_graph_ppr_evidence_propagation",
            "restart_prob": restart_prob,
            "iterations": iterations,
            "description": "Evidence priors are propagated over typed diagnostic graph edges; direct support and conflict edges calibrate candidate/fault posteriors.",
        },
        "candidate_ranking": candidate_scores,
        "fault_ranking": fault_scores,
        "node_posterior": {node_id: round(score, 6) for node_id, score in posterior.items() if score > 0},
        "direct_evidence": direct,
        "explanations": explanations,
        "graph_summary": graph.get("metadata", {}),
    }


def build_adjacency(edges: list[dict[str, Any]]) -> dict[str, list[tuple[str, float, str]]]:
    adjacency: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        edge_type = str(edge.get("type", ""))
        weight = max(0.0, float(edge.get("weight", 0.0) or 0.0))
        if weight <= 0:
            continue
        if edge_type in CONFLICT_EDGE_TYPES:
            continue
        propagation_weight = weight
        if edge_type in STRUCTURAL_EDGE_TYPES:
            propagation_weight *= 0.35
        elif edge_type == "maps_to_fault":
            propagation_weight *= 0.45
        adjacency[source].append((target, propagation_weight, edge_type))
        if edge_type in STRUCTURAL_EDGE_TYPES:
            adjacency[target].append((source, propagation_weight * 0.45, edge_type))
    return adjacency


def seed_distribution(nodes: dict[str, dict[str, Any]]) -> dict[str, float]:
    seed: dict[str, float] = {}
    for node_id, node in nodes.items():
        node_type = node.get("type")
        prior = float(node.get("prior", 0.0) or 0.0)
        if node_type in {
            "log_template",
            "trace_span",
            "metric_signal",
            "active_test",
            "crash_signature",
            "inventory_signal",
            "weak_signal",
        }:
            seed[node_id] = max(0.0, prior)
    if not seed:
        seed = {node_id: 1.0 for node_id, node in nodes.items() if node.get("type") == "case"}
    return normalize(seed)


def personalized_pagerank(
    nodes: dict[str, dict[str, Any]],
    adjacency: dict[str, list[tuple[str, float, str]]],
    seed: dict[str, float],
    *,
    restart_prob: float,
    iterations: int,
) -> dict[str, float]:
    scores = dict(seed)
    for node_id in nodes:
        scores.setdefault(node_id, 0.0)
    for _ in range(iterations):
        next_scores = {node_id: restart_prob * seed.get(node_id, 0.0) for node_id in nodes}
        for source, score in scores.items():
            if score <= 0:
                continue
            outgoing = adjacency.get(source, [])
            total_weight = sum(weight for _, weight, _ in outgoing)
            if total_weight <= 0:
                next_scores[source] = next_scores.get(source, 0.0) + (1.0 - restart_prob) * score
                continue
            for target, weight, _ in outgoing:
                next_scores[target] = next_scores.get(target, 0.0) + (1.0 - restart_prob) * score * weight / total_weight
        scores = normalize(next_scores)
    return scores


def direct_evidence_scores(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"support": 0.0, "conflict": 0.0, "support_edges": [], "conflict_edges": []}
    )
    for edge in edges:
        target = str(edge.get("target", ""))
        target_node = nodes.get(target, {})
        if target_node.get("type") not in {"candidate", "fault_class"}:
            continue
        weight = max(0.0, float(edge.get("weight", 0.0) or 0.0))
        source_node = nodes.get(str(edge.get("source", "")), {})
        item = {
            "source": edge.get("source", ""),
            "source_type": source_node.get("type", ""),
            "source_label": source_node.get("label", ""),
            "edge_type": edge.get("type", ""),
            "weight": round(weight, 4),
            "reason": (edge.get("metadata") or {}).get("reason", ""),
        }
        if edge.get("type") in SUPPORT_EDGE_TYPES:
            evidence[target]["support"] += weight
            evidence[target]["support_edges"].append(item)
        elif edge.get("type") in CONFLICT_EDGE_TYPES:
            evidence[target]["conflict"] += weight
            evidence[target]["conflict_edges"].append(item)
    for item in evidence.values():
        item["support"] = round(float(item["support"]), 4)
        item["conflict"] = round(float(item["conflict"]), 4)
        item["support_edges"] = sorted(item["support_edges"], key=lambda edge: edge["weight"], reverse=True)[:6]
        item["conflict_edges"] = sorted(item["conflict_edges"], key=lambda edge: edge["weight"], reverse=True)[:6]
    return dict(evidence)


def rank_nodes(
    node_type: str,
    nodes: dict[str, dict[str, Any]],
    posterior: dict[str, float],
    direct: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked = []
    for node_id, node in nodes.items():
        if node.get("type") != node_type:
            continue
        evidence = direct.get(node_id, {"support": 0.0, "conflict": 0.0, "support_edges": [], "conflict_edges": []})
        support = float(evidence.get("support", 0.0) or 0.0)
        conflict = float(evidence.get("conflict", 0.0) or 0.0)
        propagated = float(posterior.get(node_id, 0.0) or 0.0)
        raw_score = propagated * 2.4 + support * 0.55 - conflict * 0.5
        confidence = max(0.0, min(1.0, raw_score))
        ranked.append(
            {
                "node_id": node_id,
                "id": node_id.split(":", 1)[1] if ":" in node_id else node_id,
                "label": node.get("label", ""),
                "node_type": node_type,
                "posterior": round(confidence, 4),
                "propagated_score": round(propagated, 6),
                "support": round(support, 4),
                "conflict": round(conflict, 4),
                "supporting_paths": evidence.get("support_edges", []),
                "conflicting_paths": evidence.get("conflict_edges", []),
                "metadata": node.get("metadata", {}),
            }
        )
    return sorted(ranked, key=lambda item: (item["posterior"], item["support"], -item["conflict"], item["id"]), reverse=True)


def explain_top_paths(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    ranked_targets: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_ids = {item["node_id"] for item in ranked_targets}
    for edge in edges:
        target = str(edge.get("target", ""))
        if target not in target_ids:
            continue
        if edge.get("type") not in SUPPORT_EDGE_TYPES | CONFLICT_EDGE_TYPES:
            continue
        source = str(edge.get("source", ""))
        by_target[target].append(
            {
                "source": source,
                "source_label": nodes.get(source, {}).get("label", source),
                "source_type": nodes.get(source, {}).get("type", ""),
                "edge_type": edge.get("type", ""),
                "weight": edge.get("weight", 0),
                "reason": (edge.get("metadata") or {}).get("reason", ""),
            }
        )
    return {
        target: sorted(paths, key=lambda item: item.get("weight", 0), reverse=True)[:5]
        for target, paths in by_target.items()
    }


def normalize(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in scores.values())
    if total <= 0:
        return dict(scores)
    return {key: max(0.0, value) / total for key, value in scores.items()}
