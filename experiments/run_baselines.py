"""Run experiment baselines over normalized dataset cases."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fru_diagnosis.datasets import (
    DatasetCase,
    dump_cases_jsonl,
    enrich_case,
    infer_boundary_type,
    load_cases_jsonl,
)
from fru_diagnosis.diagnostic_graph import build_diagnostic_graph_from_case
from fru_diagnosis.graph_inference import infer_diagnostic_graph


LABEL_KEYS = ("fault_origin", "target", "serviceability_type", "boundary_type")

REPLACEABLE_HARDWARE_TARGETS = {
    "battery_pack",
    "camera_module",
    "connector_or_interconnect_fault",
    "display_panel_module",
    "fan_module",
    "heat_sink",
    "io_board",
    "m2_ssd_module",
    "memory_subsystem",
    "motherboard",
    "power_adapter",
    "ram_module",
    "speaker_module",
    "storage_fru",
    "wlan_module",
}

NON_FRU_TARGETS = {
    "configuration_fault",
    "data_or_filesystem_fault",
    "driver_or_os_fault",
    "external_environment_fault",
    "firmware_or_config_fault",
    "none",
    "os_fault",
}

HARDWARE_EVIDENCE_SOURCE_TYPES = {
    "active_test",
    "crash_signature",
    "inventory_signal",
    "metric_signal",
}


def predict_rule_weighted(case: DatasetCase) -> dict[str, object]:
    text = json.dumps(case.evidence.__dict__, ensure_ascii=False).casefold()
    if any(token in text for token in ["smart", "disk", "nvme", "storage", "hard drive"]):
        target = "storage_fru"
        origin = "replaceable_fru"
        serviceability = "replaceable_fru"
        replacement = True
    elif any(token in text for token in ["driver", "service", "exception", "fatal", "bugcheck"]):
        target = "driver_or_os_fault"
        origin = "non_fru_fault"
        serviceability = "non_fru_fault"
        replacement = False
    elif any(token in text for token in ["battery", "charge", "adapter"]):
        target = "battery_pack"
        origin = "replaceable_fru"
        serviceability = "replaceable_fru"
        replacement = True
    else:
        target = "unknown"
        origin = "mixed_or_uncertain"
        serviceability = "mixed_or_uncertain"
        replacement = False
    return {
        "method": "rule_weighted_baseline",
        "fault_origin": origin,
        "target": target,
        "target_ranking": [target],
        "serviceability_type": serviceability,
        "boundary_type": infer_boundary_type(target, origin),
        "boundary_type_ranking": [infer_boundary_type(target, origin)],
        "replacement_recommended": replacement,
        "next_tests": [],
    }


def predict_graph_fusion(case: DatasetCase) -> dict[str, object]:
    graph = build_diagnostic_graph_from_case(case)
    inference = infer_diagnostic_graph(graph)
    fault_ranking = inference.get("fault_ranking", [])
    candidate_ranking = inference.get("candidate_ranking", [])
    selection = select_calibrated_graph_target(case, candidate_ranking, fault_ranking)
    target = selection["target"]
    fault_origin = map_calibrated_fault_origin(target)
    serviceability = map_serviceability_type(fault_origin)
    return {
        "method": "graph_fusion_baseline",
        "fault_origin": fault_origin,
        "target": target,
        "target_ranking": build_calibrated_target_ranking(
            selection["target"],
            candidate_ranking,
            fault_ranking,
            allow_hardware_targets=selection["has_hardware_evidence"],
        ),
        "serviceability_type": serviceability,
        "boundary_type": infer_boundary_type(target, fault_origin),
        "boundary_type_ranking": [infer_boundary_type(target, fault_origin)],
        "replacement_recommended": fault_origin == "replaceable_fru",
        "next_tests": [],
        "calibration": selection["calibration"],
        "graph_fault_ranking": compact_ranking(fault_ranking),
        "graph_candidate_ranking": compact_ranking(candidate_ranking),
    }


class TfidfCentroidModel:
    """Small dependency-free TF-IDF nearest-centroid classifier."""

    def __init__(
        self,
        label_key: str,
        *,
        include_temporal: bool = False,
        feature_group: str = "all",
    ) -> None:
        self.label_key = label_key
        self.include_temporal = include_temporal
        self.feature_group = feature_group
        self.idf: dict[str, float] = {}
        self.centroids: dict[str, dict[str, float]] = {}
        self.class_counts: Counter[str] = Counter()
        self.majority_label = "unknown"

    def fit(self, cases: list[DatasetCase]) -> None:
        documents: list[tuple[str, Counter[str]]] = []
        document_frequency: Counter[str] = Counter()
        for case in cases:
            if case.label is None:
                continue
            label = str(getattr(case.label, self.label_key))
            features = case_feature_counts(
                case,
                include_temporal=self.include_temporal,
                feature_group=self.feature_group,
            )
            if not features:
                continue
            documents.append((label, features))
            self.class_counts[label] += 1
            document_frequency.update(features.keys())

        if not documents:
            return

        self.majority_label = self.class_counts.most_common(1)[0][0]
        document_count = len(documents)
        self.idf = {
            term: math.log((1 + document_count) / (1 + df)) + 1.0
            for term, df in document_frequency.items()
        }
        by_class: dict[str, list[dict[str, float]]] = defaultdict(list)
        for label, features in documents:
            by_class[label].append(normalize_vector(tfidf_vector(features, self.idf)))

        self.centroids = {
            label: normalize_vector(mean_vector(vectors))
            for label, vectors in by_class.items()
            if vectors
        }

    def predict_ranking(self, case: DatasetCase) -> list[tuple[str, float]]:
        if not self.centroids:
            return [(self.majority_label, 1.0)]
        vector = normalize_vector(
            tfidf_vector(
                case_feature_counts(
                    case,
                    include_temporal=self.include_temporal,
                    feature_group=self.feature_group,
                ),
                self.idf,
            )
        )
        scores = [
            (label, cosine_similarity(vector, centroid))
            for label, centroid in self.centroids.items()
        ]
        ranked = sorted(scores, key=lambda item: (item[1], self.class_counts[item[0]], item[0]), reverse=True)
        if ranked and ranked[0][1] > 0:
            return ranked
        return [(self.majority_label, 1.0)] + [
            item for item in ranked if item[0] != self.majority_label
        ]


def predict_log_template_tfidf(case: DatasetCase, models: dict[str, TfidfCentroidModel]) -> dict[str, object]:
    case = enrich_case(case)
    rankings = {key: models[key].predict_ranking(case) for key in LABEL_KEYS}
    target_ranking = [label for label, _ in rankings["target"][:8]]
    target = target_ranking[0] if target_ranking else "unknown"
    fault_origin = rankings["fault_origin"][0][0] if rankings["fault_origin"] else "mixed_or_uncertain"
    serviceability = rankings["serviceability_type"][0][0] if rankings["serviceability_type"] else map_serviceability_type(fault_origin)
    boundary_ranking = [label for label, _ in rankings["boundary_type"][:8]]
    boundary_type = boundary_ranking[0] if boundary_ranking else infer_boundary_type(target, fault_origin)
    return {
        "method": "log_template_tfidf_centroid_baseline",
        "fault_origin": fault_origin,
        "target": target,
        "target_ranking": target_ranking,
        "serviceability_type": serviceability,
        "boundary_type": boundary_type,
        "boundary_type_ranking": boundary_ranking,
        "boundary_confidence": ranking_confidence(rankings["boundary_type"]),
        "replacement_recommended": serviceability == "replaceable_fru",
        "next_tests": [],
        "model_summary": {
            key: {
                "class_count": len(models[key].centroids),
                "majority_label": models[key].majority_label,
            }
            for key in LABEL_KEYS
        },
        "target_scores": [
            {"label": label, "score": round(score, 6)}
            for label, score in rankings["target"][:8]
        ],
    }


def predict_temporal_fusion_tfidf(
    case: DatasetCase,
    models: dict[str, TfidfCentroidModel],
) -> dict[str, object]:
    """Predict with log features plus temporal, quality and boundary features."""

    return {
        **predict_log_template_tfidf(enrich_case(case), models),
        "method": "temporal_fusion_tfidf_centroid_baseline",
        "feature_groups": ["logs", "temporal", "modality_quality", "boundary_roles"],
    }


def predict_reliability_gated_fusion(
    case: DatasetCase,
    models: dict[str, Any],
) -> dict[str, object]:
    """Fuse independently trained modality models using source quality gates."""

    case = enrich_case(case)
    quality = case.metadata.get("modality_quality", {}) or {}
    group_quality = {
        "logs": float(quality.get("logs", 0.0) or 0.0),
        "metrics": float(quality.get("metrics", 0.0) or 0.0),
        "boundary": max((case.metadata.get("boundary_role_scores", {}) or {}).values() or [0.0]),
        "temporal": 1.0 if (case.metadata.get("temporal_features", {}) or {}).get("fault_time_available") else 0.25,
    }
    global_weights = models.get("_global_weights", {}) or {}
    rankings: dict[str, list[tuple[str, float]]] = {}
    for label_key in LABEL_KEYS:
        scores: dict[str, float] = defaultdict(float)
        total_weight = 0.0
        for group in ("logs", "metrics", "boundary", "temporal"):
            group_models = models.get(group, {})
            weight = max(0.0, group_quality.get(group, 0.0)) * float(global_weights.get(group, 1.0))
            if weight <= 0 or label_key not in group_models:
                continue
            total_weight += weight
            for label, score in group_models[label_key].predict_ranking(case):
                scores[label] += weight * max(0.0, float(score))
        if total_weight <= 0:
            rankings[label_key] = [("unknown", 1.0)]
        else:
            rankings[label_key] = sorted(
                ((label, score / total_weight) for label, score in scores.items()),
                key=lambda item: item[1],
                reverse=True,
            )
    target_ranking = [label for label, _ in rankings["target"][:8]]
    target = target_ranking[0] if target_ranking else "unknown"
    origin = rankings["fault_origin"][0][0] if rankings["fault_origin"] else "mixed_or_uncertain"
    serviceability = rankings["serviceability_type"][0][0] if rankings["serviceability_type"] else map_serviceability_type(origin)
    boundary_ranking = [label for label, _ in rankings["boundary_type"][:8]]
    boundary_type = boundary_ranking[0] if boundary_ranking else infer_boundary_type(target, origin)
    return {
        "method": "reliability_gated_late_fusion",
        "fault_origin": origin,
        "target": target,
        "target_ranking": target_ranking,
        "serviceability_type": serviceability,
        "boundary_type": boundary_type,
        "boundary_type_ranking": boundary_ranking,
        "boundary_confidence": ranking_confidence(
            rankings["boundary_type"],
            power=float(models.get("_boundary_power", 1.0) or 1.0),
        ),
        "replacement_recommended": serviceability == "replaceable_fru",
        "modality_weights": {key: round(value, 4) for key, value in group_quality.items()},
        "learned_global_weights": global_weights,
        "target_scores": [
            {"label": label, "score": round(score, 6)}
            for label, score in rankings["target"][:8]
        ],
        "next_tests": [],
    }


def train_log_template_tfidf_models(train_cases: list[DatasetCase]) -> dict[str, TfidfCentroidModel]:
    models = {key: TfidfCentroidModel(key) for key in LABEL_KEYS}
    train_cases = [enrich_case(case) for case in train_cases]
    for model in models.values():
        model.fit(train_cases)
    return models


def train_temporal_fusion_tfidf_models(
    train_cases: list[DatasetCase],
) -> dict[str, TfidfCentroidModel]:
    models = {key: TfidfCentroidModel(key, include_temporal=True) for key in LABEL_KEYS}
    for model in models.values():
        model.fit([enrich_case(case) for case in train_cases])
    return models


def train_reliability_gated_fusion_models(
    train_cases: list[DatasetCase],
    dev_cases: list[DatasetCase] | None = None,
) -> dict[str, Any]:
    groups = {"logs": False, "metrics": False, "boundary": True, "temporal": True}
    enriched = [enrich_case(case) for case in train_cases]
    models: dict[str, dict[str, TfidfCentroidModel]] = {}
    for group, include_temporal in groups.items():
        group_models = {
            key: TfidfCentroidModel(
                key,
                include_temporal=include_temporal,
                feature_group=group,
            )
            for key in LABEL_KEYS
        }
        models[group] = fit_group_models(group_models, enriched)
    models["_global_weights"] = tune_reliability_weights(models, dev_cases or [])
    models["_boundary_power"] = tune_boundary_confidence_power(models, dev_cases or [])
    return models


def tune_reliability_weights(models: dict[str, Any], dev_cases: list[DatasetCase]) -> dict[str, float]:
    default = {"logs": 1.0, "metrics": 1.0, "boundary": 1.0, "temporal": 1.0}
    if not dev_cases:
        return default
    best_weights = default
    best_score = (-1.0, -1.0)
    for values in product((0.0, 0.5, 1.0, 2.0), repeat=3):
        weights = {
            "logs": 1.0,
            "metrics": values[0],
            "boundary": values[1],
            "temporal": values[2],
        }
        models["_global_weights"] = weights
        predictions = [predict_reliability_gated_fusion(case, models) for case in dev_cases]
        score = boundary_prediction_score(dev_cases, predictions)
        if score > best_score:
            best_score = score
            best_weights = weights
    return best_weights


def tune_boundary_confidence_power(models: dict[str, Any], dev_cases: list[DatasetCase]) -> float:
    if not dev_cases:
        return 1.0
    best_power = 1.0
    best_error = float("inf")
    for power in (0.5, 1.0, 2.0, 4.0, 8.0):
        models["_boundary_power"] = power
        predictions = [predict_reliability_gated_fusion(case, models) for case in dev_cases]
        error = mean_boundary_calibration_error(dev_cases, predictions)
        if error < best_error:
            best_error = error
            best_power = power
    return best_power


def boundary_prediction_score(
    cases: list[DatasetCase],
    predictions: list[dict[str, object]],
) -> tuple[float, float]:
    expected = [enrich_case(case).label.boundary_type for case in cases if case.label is not None]
    predicted = [str(item.get("boundary_type", "")) for item in predictions]
    classes = sorted(set(expected))
    recalls = []
    for label in classes:
        indices = [index for index, value in enumerate(expected) if value == label]
        recalls.append(sum(predicted[index] == label for index in indices) / len(indices))
    accuracy_value = sum(left == right for left, right in zip(expected, predicted)) / len(expected)
    return (sum(recalls) / len(recalls), accuracy_value)


def mean_boundary_calibration_error(
    cases: list[DatasetCase],
    predictions: list[dict[str, object]],
) -> float:
    errors = []
    for case, prediction in zip(cases, predictions):
        if case.label is None:
            continue
        expected = enrich_case(case).label.boundary_type
        correct = 1.0 if prediction.get("boundary_type") == expected else 0.0
        errors.append(abs(correct - float(prediction.get("boundary_confidence", 0.0) or 0.0)))
    return sum(errors) / len(errors) if errors else float("inf")


def fit_group_models(
    models: dict[str, TfidfCentroidModel],
    cases: list[DatasetCase],
) -> dict[str, TfidfCentroidModel]:
    for model in models.values():
        model.fit(cases)
    return models


def case_feature_counts(
    case: DatasetCase,
    *,
    include_temporal: bool = False,
    feature_group: str = "all",
) -> Counter[str]:
    if feature_group == "logs":
        return case_log_feature_counts(case)
    if feature_group == "metrics":
        features: Counter[str] = Counter()
        for key, value in iter_nested_values(case.evidence.metrics):
            features[f"metric_key:{normalize_feature_text(key)}"] += 1.0
            for token in tokenize_text(str(value)):
                features[f"metric_value:{token}"] += 1.0
        return +features
    features = case_log_feature_counts(case) if feature_group == "all" else Counter()
    if not include_temporal:
        return features
    metadata = case.metadata if isinstance(case.metadata, dict) else {}
    for modality in metadata.get("modalities", []) or []:
        if feature_group not in {"all", "boundary", "temporal"}:
            continue
        features[f"modality:{normalize_feature_text(modality)}"] += 1.0
    for role in metadata.get("boundary_roles", []) or []:
        if feature_group not in {"all", "boundary"}:
            continue
        features[f"boundary_role:{normalize_feature_text(role)}"] += 1.0
    for name, score in (metadata.get("modality_quality", {}) or {}).items():
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        if feature_group in {"all", "boundary", "temporal"}:
            features[f"quality:{normalize_feature_text(name)}:{quality_bucket(value)}"] += 1.0
    temporal = metadata.get("temporal_features", {}) or {}
    if temporal.get("fault_time_available") and feature_group in {"all", "temporal"}:
        features["temporal:fault_time_available"] += 1.0
    if feature_group in {"all", "temporal"}:
        features[f"temporal:source_count:{int(temporal.get('source_count', 0) or 0)}"] += 1.0
    metric_rows = int(temporal.get("metric_row_count", 0) or 0)
    if feature_group in {"all", "temporal"}:
        features[f"temporal:metric_rows:{quality_bucket(min(1.0, metric_rows / 100.0))}"] += 1.0
    for name, distance in (temporal.get("distances_seconds", {}) or {}).items():
        try:
            if feature_group in {"all", "temporal"}:
                features[f"temporal:{normalize_feature_text(name)}:{distance_bucket(float(distance))}"] += 1.0
        except (TypeError, ValueError):
            continue
    return +features


def quality_bucket(value: float) -> str:
    if value <= 0:
        return "missing"
    if value < 0.45:
        return "low"
    if value < 0.75:
        return "medium"
    return "high"


def distance_bucket(value: float) -> str:
    absolute = abs(value)
    if absolute < 1:
        return "near"
    if absolute < 60:
        return "minute"
    if absolute < 3600:
        return "hour"
    return "far"


def ranking_confidence(ranking: list[tuple[str, float]], *, power: float = 1.0) -> float:
    if not ranking:
        return 0.0
    positive = [max(0.0, float(score)) ** power for _, score in ranking]
    total = sum(positive)
    if total <= 0:
        return round(1.0 / len(ranking), 4)
    return round(positive[0] / total, 4)


def case_log_feature_counts(case: DatasetCase) -> Counter[str]:
    logs = case.evidence.logs if isinstance(case.evidence.logs, dict) else {}
    features: Counter[str] = Counter()

    template_counts = logs.get("event_template_counts", {})
    if isinstance(template_counts, dict):
        for template, count in template_counts.items():
            add_weighted_feature(features, f"template:{normalize_feature_text(template)}", count)

    event_id_counts = logs.get("event_id_counts", {})
    if isinstance(event_id_counts, dict):
        for event_id, count in event_id_counts.items():
            add_weighted_feature(features, f"event_id:{event_id}", count)

    template_sequence = logs.get("event_template_sequence", [])
    if isinstance(template_sequence, list):
        normalized_sequence = [normalize_feature_text(item) for item in template_sequence if item]
        for template in normalized_sequence:
            features[f"seq_template:{template}"] += 1.0
        for left, right in zip(normalized_sequence, normalized_sequence[1:]):
            features[f"seq_bigram:{left}->{right}"] += 1.0

    event_id_sequence = logs.get("event_id_sequence", [])
    if isinstance(event_id_sequence, list):
        ids = [str(item) for item in event_id_sequence if item]
        for left, right in zip(ids, ids[1:]):
            features[f"event_bigram:{left}->{right}"] += 1.0

    for field_name in ("level_counts", "component_counts"):
        counts = logs.get(field_name, {})
        if not isinstance(counts, dict):
            continue
        for value, count in counts.items():
            add_weighted_feature(features, f"{field_name}:{normalize_feature_text(value)}", count)

    for field_name in ("evidence_messages", "raw_messages"):
        values = logs.get(field_name, [])
        if not isinstance(values, list):
            continue
        for value in values[:80]:
            for token in tokenize_text(str(value)):
                features[f"text:{token}"] += 1.0

    return +features


def add_weighted_feature(features: Counter[str], name: str, value: Any) -> None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 1.0
    if name and amount > 0:
        features[name] += amount


def normalize_feature_text(value: Any) -> str:
    text = str(value or "").casefold().strip()
    return " ".join(text.split())


def tokenize_text(text: str) -> list[str]:
    normalized = normalize_feature_text(text)
    tokens: list[str] = []
    current = []
    for char in normalized:
        if char.isalnum() or char in {"_", "-", "."}:
            current.append(char)
        elif current:
            token = "".join(current)
            if len(token) >= 2:
                tokens.append(token)
            current = []
    if current:
        token = "".join(current)
        if len(token) >= 2:
            tokens.append(token)
    return tokens[:80]


def tfidf_vector(features: Counter[str], idf: dict[str, float]) -> dict[str, float]:
    return {
        term: math.log1p(float(count)) * idf.get(term, 1.0)
        for term, count in features.items()
        if count > 0
    }


def normalize_vector(vector: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm <= 0:
        return dict(vector)
    return {key: value / norm for key, value in vector.items()}


def mean_vector(vectors: list[dict[str, float]]) -> dict[str, float]:
    summed: dict[str, float] = defaultdict(float)
    for vector in vectors:
        for key, value in vector.items():
            summed[key] += value
    return {key: value / len(vectors) for key, value in summed.items()}


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def first_supported_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if float(item.get("support", 0.0) or 0.0) > float(item.get("conflict", 0.0) or 0.0):
            return item
    return items[0] if items else None


def select_calibrated_graph_target(
    case: DatasetCase,
    candidate_ranking: list[dict[str, Any]],
    fault_ranking: list[dict[str, Any]],
) -> dict[str, Any]:
    """Choose the graph target after evidence-gating unsafe hardware decisions."""

    has_hardware_evidence = case_has_hardware_evidence(case) or ranking_has_hardware_evidence(candidate_ranking)
    top_fault = first_supported_item(fault_ranking)
    top_candidate = first_supported_item(candidate_ranking)
    raw_candidate_target = map_candidate_target(top_candidate, top_fault)
    raw_fault_target = map_fault_to_target(top_fault)
    blocked_hardware_target = (
        raw_candidate_target if is_replaceable_hardware_target(raw_candidate_target) and not has_hardware_evidence else ""
    )

    if raw_fault_target == "none":
        target = "none"
        reason = "top fault class is no_fault_observed"
    elif blocked_hardware_target:
        target = first_non_hardware_fault_target(fault_ranking)
        if target == "unknown":
            target = first_non_hardware_candidate_target(candidate_ranking)
        reason = "replaceable hardware candidate blocked because no validating hardware evidence is present"
    elif raw_candidate_target and raw_candidate_target != "unknown":
        target = raw_candidate_target
        reason = "top supported candidate selected"
    else:
        target = raw_fault_target
        reason = "top supported fault class selected"

    return {
        "target": target or "unknown",
        "has_hardware_evidence": has_hardware_evidence,
        "calibration": {
            "reason": reason,
            "raw_candidate_target": raw_candidate_target,
            "raw_fault_target": raw_fault_target,
            "blocked_hardware_target": blocked_hardware_target,
            "has_hardware_evidence": has_hardware_evidence,
        },
    }


def case_has_hardware_evidence(case: DatasetCase) -> bool:
    evidence = case.evidence
    if has_problem_inventory(evidence.inventory):
        return True
    if has_non_empty_mapping(evidence.metrics):
        return True
    if has_non_empty_mapping(evidence.active_tests):
        return True
    if has_non_empty_mapping(evidence.crash_dump):
        return True
    return False


def has_problem_inventory(inventory: dict[str, Any]) -> bool:
    device_inventory = inventory.get("device_inventory", inventory) if isinstance(inventory, dict) else {}
    if not isinstance(device_inventory, dict):
        return False
    problem_devices = device_inventory.get("problem_devices", [])
    return isinstance(problem_devices, list) and bool(problem_devices)


def has_non_empty_mapping(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for _, leaf in iter_nested_values(value):
        if leaf in {None, "", "unknown", "not_run", "not_available"}:
            continue
        if isinstance(leaf, (dict, list)) and not leaf:
            continue
        return True
    return False


def iter_nested_values(value: Any) -> list[tuple[str, Any]]:
    values: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(nested, (dict, list)):
                values.extend(iter_nested_values(nested))
            else:
                values.append((str(key), nested))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            if isinstance(nested, (dict, list)):
                values.extend(iter_nested_values(nested))
            else:
                values.append((str(index), nested))
    return values


def ranking_has_hardware_evidence(candidate_ranking: list[dict[str, Any]]) -> bool:
    for item in candidate_ranking:
        for path in item.get("supporting_paths", []) or []:
            if path.get("source_type") in HARDWARE_EVIDENCE_SOURCE_TYPES:
                return True
    return False


def is_replaceable_hardware_target(target: str) -> bool:
    return target in REPLACEABLE_HARDWARE_TARGETS


def first_non_hardware_fault_target(fault_ranking: list[dict[str, Any]]) -> str:
    for item in fault_ranking:
        if float(item.get("support", 0.0) or 0.0) <= float(item.get("conflict", 0.0) or 0.0):
            continue
        target = map_fault_to_target(item)
        if target in NON_FRU_TARGETS:
            return target
    return "unknown"


def first_non_hardware_candidate_target(candidate_ranking: list[dict[str, Any]]) -> str:
    for item in candidate_ranking:
        if float(item.get("support", 0.0) or 0.0) <= float(item.get("conflict", 0.0) or 0.0):
            continue
        target = map_candidate_target(item, None)
        if target in NON_FRU_TARGETS:
            return target
    return "unknown"


def map_candidate_target(candidate: dict[str, Any] | None, fault: dict[str, Any] | None) -> str:
    if not candidate:
        return map_fault_to_target(fault)
    candidate_id = str(candidate.get("id", "") or "")
    if candidate_id in {
        "driver_or_os_fault",
        "firmware_or_config_fault",
        "configuration_fault",
        "external_environment_fault",
        "data_or_filesystem_fault",
    }:
        return candidate_id
    if candidate_id in {"m2_ssd_module", "storage_fru"}:
        return "storage_fru"
    if candidate_id in {"battery_pack", "power_adapter"}:
        return candidate_id
    if candidate_id and candidate_id != "mixed_or_uncertain":
        return candidate_id
    return map_fault_to_target(fault)


def map_fault_to_target(fault: dict[str, Any] | None) -> str:
    fault_id = str((fault or {}).get("id", "") or "")
    return {
        "no_fault_observed": "none",
        "driver_fault": "driver_or_os_fault",
        "os_fault": "os_fault",
        "configuration_fault": "configuration_fault",
        "firmware_fault": "firmware_or_config_fault",
        "external_environment_fault": "external_environment_fault",
        "data_or_filesystem_fault": "data_or_filesystem_fault",
        "hardware_fault": "hardware_fault",
    }.get(fault_id, "unknown")


def map_fault_origin(fault: dict[str, Any] | None, target: str) -> str:
    fault_id = str((fault or {}).get("id", "") or "")
    if target == "none" or fault_id == "no_fault_observed":
        return "no_fault_observed"
    if fault_id == "hardware_fault" or target in {"storage_fru", "battery_pack", "power_adapter"}:
        return "replaceable_fru"
    if fault_id:
        return "non_fru_fault"
    return "mixed_or_uncertain"


def map_calibrated_fault_origin(target: str) -> str:
    if target == "none":
        return "no_fault_observed"
    if is_replaceable_hardware_target(target) or target == "hardware_fault":
        return "replaceable_fru"
    if target and target != "unknown":
        return "non_fru_fault"
    return "mixed_or_uncertain"


def map_serviceability_type(fault_origin: str) -> str:
    if fault_origin == "no_fault_observed":
        return "none"
    if fault_origin == "replaceable_fru":
        return "replaceable_fru"
    if fault_origin == "non_fru_fault":
        return "non_fru_fault"
    return "mixed_or_uncertain"


def build_target_ranking(
    candidate_ranking: list[dict[str, Any]],
    fault_ranking: list[dict[str, Any]],
) -> list[str]:
    ranked: list[str] = []
    for item in fault_ranking:
        target = map_fault_to_target(item)
        if target == "none" and target not in ranked:
            ranked.append(target)
    for item in candidate_ranking:
        target = map_candidate_target(item, None)
        if target not in ranked:
            ranked.append(target)
    for item in fault_ranking:
        target = map_fault_to_target(item)
        if target not in ranked:
            ranked.append(target)
    return ranked[:8]


def build_calibrated_target_ranking(
    selected_target: str,
    candidate_ranking: list[dict[str, Any]],
    fault_ranking: list[dict[str, Any]],
    *,
    allow_hardware_targets: bool,
) -> list[str]:
    raw = build_target_ranking(candidate_ranking, fault_ranking)
    non_hardware = [target for target in raw if allow_hardware_targets or not is_replaceable_hardware_target(target)]
    hardware = [target for target in raw if not allow_hardware_targets and is_replaceable_hardware_target(target)]
    ranked = [selected_target] if selected_target else []
    for target in non_hardware + hardware:
        if target and target not in ranked:
            ranked.append(target)
    return ranked[:8]


def compact_ranking(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, object]]:
    return [
        {
            "id": item.get("id", ""),
            "posterior": item.get("posterior", 0),
            "support": item.get("support", 0),
            "conflict": item.get("conflict", 0),
        }
        for item in items[:limit]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline predictions over normalized cases.")
    parser.add_argument("input_jsonl")
    parser.add_argument("output_jsonl")
    parser.add_argument(
        "--method",
        choices=[
            "rule_weighted",
            "graph_fusion",
            "log_template_tfidf",
            "temporal_fusion_tfidf",
            "reliability_gated_fusion",
        ],
        default="rule_weighted",
    )
    parser.add_argument(
        "--train-jsonl",
        default="",
        help="Training cases for supervised baselines such as log_template_tfidf.",
    )
    parser.add_argument(
        "--dev-jsonl",
        default="",
        help="Optional development split for fusion-weight and confidence calibration.",
    )
    args = parser.parse_args()

    models: dict[str, Any] | None = None
    if args.method == "log_template_tfidf":
        if not args.train_jsonl:
            parser.error("--train-jsonl is required for --method log_template_tfidf")
        models = train_log_template_tfidf_models(load_cases_jsonl(args.train_jsonl))
    elif args.method == "temporal_fusion_tfidf":
        if not args.train_jsonl:
            parser.error("--train-jsonl is required for --method temporal_fusion_tfidf")
        models = train_temporal_fusion_tfidf_models(load_cases_jsonl(args.train_jsonl))
    elif args.method == "reliability_gated_fusion":
        if not args.train_jsonl:
            parser.error("--train-jsonl is required for --method reliability_gated_fusion")
        models = train_reliability_gated_fusion_models(
            load_cases_jsonl(args.train_jsonl),
            load_cases_jsonl(args.dev_jsonl) if args.dev_jsonl else None,
        )

    cases = []
    for case in load_cases_jsonl(args.input_jsonl):
        if args.method == "graph_fusion":
            prediction = predict_graph_fusion(case)
        elif args.method == "log_template_tfidf":
            assert models is not None
            prediction = predict_log_template_tfidf(case, models)
        elif args.method == "temporal_fusion_tfidf":
            assert models is not None
            prediction = predict_temporal_fusion_tfidf(case, models)
        elif args.method == "reliability_gated_fusion":
            assert models is not None
            prediction = predict_reliability_gated_fusion(case, models)
        else:
            prediction = predict_rule_weighted(case)
        metadata = dict(case.metadata)
        metadata["prediction"] = prediction
        cases.append(
            DatasetCase(
                case_id=case.case_id,
                source_dataset=case.source_dataset,
                device_type=case.device_type,
                device_id=case.device_id,
                fault_case_id=case.fault_case_id,
                timestamp=case.timestamp,
                fault_time=case.fault_time,
                symptom=case.symptom,
                evidence=case.evidence,
                label=case.label,
                metadata=metadata,
            )
        )
    dump_cases_jsonl(cases, args.output_jsonl)
    print(f"Wrote baseline predictions to {args.output_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
