"""Formal RCAEval experiments for heterogeneous-evidence diagnosis.

The generic experiment runner evaluates only the normalized service target
(`service_runtime_fault`), which is not enough for RCAEval. This script
evaluates the actual injected root cause at three levels:

- root-cause service
- injected fault type
- composed final root cause: service:fault_type

Feature extraction intentionally uses only evidence fields. It does not use
case IDs, source paths, split groups, or label metadata as model features.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fru_diagnosis.datasets import DatasetCase, dump_cases_jsonl, load_cases_jsonl


METHOD_LABELS = {
    "majority_prior": "多数类先验",
    "keyword_heuristic": "无监督关键词启发式",
    "joint_root_tfidf": "联合根因 TF-IDF",
    "logs_tfidf": "日志模板 TF-IDF",
    "metrics_tfidf": "指标 TF-IDF",
    "traces_tfidf": "链路 TF-IDF",
    "early_fusion_tfidf": "早期特征融合 TF-IDF",
    "late_fusion_tfidf": "异构证据后期融合",
    "temporal_signal_fusion": "时序指标证据融合",
    "temporal_fusion_tfidf": "时序异构证据融合 TF-IDF",
}

METHOD_LABELS["hierarchical_temporal_fusion"] = "hierarchical temporal fusion"
METHOD_LABELS["baro_reproduction"] = "BARO reproduction (metric-only)"
METHOD_LABELS["multi_source_baro_reproduction"] = "Multi-source BARO reproduction"
METHOD_LABELS["cloudranger_reproduction"] = "CloudRanger reproduction"
METHOD_LABELS["tracerca_reproduction"] = "TraceRCA reproduction"

METHOD_ORDER = [
    "majority_prior",
    "keyword_heuristic",
    "joint_root_tfidf",
    "logs_tfidf",
    "metrics_tfidf",
    "traces_tfidf",
    "early_fusion_tfidf",
    "late_fusion_tfidf",
    "temporal_signal_fusion",
    "temporal_fusion_tfidf",
    "hierarchical_temporal_fusion",
    "baro_reproduction",
    "multi_source_baro_reproduction",
    "cloudranger_reproduction",
    "tracerca_reproduction",
]

FAULT_KEYWORDS = {
    "cpu": ("cpu", "processor", "quota", "usage", "seconds-total"),
    "mem": ("mem", "memory", "rss", "working-set", "cache", "swap"),
    "disk": ("disk", "fs-", "blkio", "read", "write", "written"),
    "delay": ("delay", "latency", "duration", "timeout", "slow"),
    "loss": ("loss", "drop", "dropped", "error", "failed", "unavailable", "refused", "status"),
    "socket": ("socket", "sockets", "connection", "network", "tcp"),
    "f1": ("f1",),
    "f2": ("f2",),
    "f3": ("f3",),
    "f4": ("f4",),
    "f5": ("f5",),
}

RAW_METRIC_WINDOW = 120
RAW_METRIC_TOP_N = 96


@dataclass
class LabelParts:
    service: str
    fault_type: str
    root: str


class CentroidClassifier:
    """Dependency-free TF-IDF nearest-centroid classifier."""

    def __init__(self, label_getter: Callable[[DatasetCase], str], feature_getter: Callable[[DatasetCase], Counter[str]]) -> None:
        self.label_getter = label_getter
        self.feature_getter = feature_getter
        self.idf: dict[str, float] = {}
        self.centroids: dict[str, dict[str, float]] = {}
        self.class_counts: Counter[str] = Counter()
        self.majority_label = "unknown"

    def fit(self, cases: list[DatasetCase]) -> None:
        documents: list[tuple[str, Counter[str]]] = []
        document_frequency: Counter[str] = Counter()
        for case in cases:
            label = self.label_getter(case)
            if not label:
                continue
            features = self.feature_getter(case)
            if not features:
                continue
            documents.append((label, features))
            self.class_counts[label] += 1
            document_frequency.update(features.keys())

        if not documents:
            return

        self.majority_label = self.class_counts.most_common(1)[0][0]
        doc_count = len(documents)
        self.idf = {
            term: math.log((1 + doc_count) / (1 + df)) + 1.0
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

    def scores(self, case: DatasetCase) -> dict[str, float]:
        if not self.centroids:
            return {self.majority_label: 1.0}
        vector = normalize_vector(tfidf_vector(self.feature_getter(case), self.idf))
        raw = {label: cosine_similarity(vector, centroid) for label, centroid in self.centroids.items()}
        if any(value > 0 for value in raw.values()):
            return raw
        return {self.majority_label: 1.0, **raw}

    def ranking(self, case: DatasetCase) -> list[tuple[str, float]]:
        scores = self.scores(case)
        return sorted(
            scores.items(),
            key=lambda item: (item[1], self.class_counts[item[0]], item[0]),
            reverse=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run formal RCAEval root-cause experiments.")
    parser.add_argument("--dataset-dir", default="datasets/processed/diagnosis_v7_rcaeval_re2")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--include-dev-eval", action="store_true")
    args = parser.parse_args()

    dataset_dir = resolve_project_path(args.dataset_dir)
    output_dir = resolve_project_path(args.output_dir) if args.output_dir else (
        PROJECT_ROOT / "reports" / "experiments" / f"{dataset_dir.name}_formal_rcaeval"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    train_cases = load_cases_jsonl(dataset_dir / "train.jsonl")
    dev_cases = load_cases_jsonl(dataset_dir / "dev.jsonl")
    test_cases = load_cases_jsonl(dataset_dir / "test.jsonl")

    models = train_models(train_cases, dev_cases)
    split_cases = {"test": test_cases}
    if args.include_dev_eval:
        split_cases["dev"] = dev_cases

    summary: dict[str, Any] = {
        "dataset_dir": str(dataset_dir.relative_to(PROJECT_ROOT)),
        "output_dir": str(output_dir.relative_to(PROJECT_ROOT)),
        "train_count": len(train_cases),
        "dev_count": len(dev_cases),
        "test_count": len(test_cases),
        "split_label_overlap": split_label_overlap(train_cases, dev_cases, test_cases),
        "methods": {},
        "selected_late_fusion_weights": models["late_fusion_weights"],
        "selected_hierarchical_fusion_weights": models["hierarchical_fusion_weights"],
    }
    per_source: dict[str, Any] = {}
    per_fault: dict[str, Any] = {}

    for split, cases in split_cases.items():
        for method in METHOD_ORDER:
            predicted = [attach_prediction(case, predict_case(case, method, models)) for case in cases]
            prediction_path = output_dir / f"{split}_{method}.jsonl"
            dump_cases_jsonl(predicted, prediction_path)
            metrics = evaluate_predictions(
                predicted,
                reference_roots={label_parts(item).root for item in train_cases},
            )
            key = f"{split}_{method}"
            summary["methods"][key] = compact_metrics(metrics)
            write_json(metrics, output_dir / f"{key}_metrics.json")
            per_source[key] = evaluate_grouped(predicted, lambda case: case.source_dataset)
            per_fault[key] = evaluate_grouped(predicted, lambda case: label_parts(case).fault_type)

    write_json(summary, output_dir / "metrics_summary.json")
    write_json(per_source, output_dir / "per_source_metrics.json")
    write_json(per_fault, output_dir / "per_fault_metrics.json")
    report = build_markdown_report(dataset_dir, output_dir, summary, per_source, per_fault)
    (output_dir / "formal_experiment_report.md").write_text(report, encoding="utf-8")
    print(f"Wrote formal RCAEval experiment to {output_dir}")
    return 0


def train_models(train_cases: list[DatasetCase], dev_cases: list[DatasetCase]) -> dict[str, Any]:
    feature_sets = {
        "logs": log_features,
        "metrics": metric_features,
        "traces": trace_features,
        "all": all_features,
        "temporal": temporal_all_features,
    }
    models: dict[str, Any] = {
        "majority": {
            "service": majority_label(train_cases, lambda case: label_parts(case).service),
            "fault_type": majority_label(train_cases, lambda case: label_parts(case).fault_type),
            "root": majority_label(train_cases, lambda case: label_parts(case).root),
        }
    }
    for feature_name, getter in feature_sets.items():
        models[feature_name] = {
            "service": fit_centroid(train_cases, lambda case: label_parts(case).service, getter),
            "fault_type": fit_centroid(train_cases, lambda case: label_parts(case).fault_type, getter),
            "root": fit_centroid(train_cases, lambda case: label_parts(case).root, getter),
        }
    models["late_fusion_weights"] = tune_late_fusion_weights(train_cases, dev_cases, models)
    models["root_compatibility"] = build_root_compatibility(train_cases)
    models["dependency_graph"] = build_dependency_graph(train_cases)
    models["service_vocabulary"] = sorted(
        {label_parts(case).service for case in train_cases if label_parts(case).service}
    )
    models["hierarchical_fusion_weights"] = tune_hierarchical_fusion_weights(dev_cases, models)
    return models


def fit_centroid(
    cases: list[DatasetCase],
    label_getter: Callable[[DatasetCase], str],
    feature_getter: Callable[[DatasetCase], Counter[str]],
) -> CentroidClassifier:
    model = CentroidClassifier(label_getter, feature_getter)
    model.fit(cases)
    return model


def majority_label(cases: list[DatasetCase], label_getter: Callable[[DatasetCase], str]) -> str:
    counts = Counter(label_getter(case) for case in cases if label_getter(case))
    return counts.most_common(1)[0][0] if counts else "unknown"


def build_root_compatibility(cases: list[DatasetCase]) -> dict[str, Any]:
    pair_counts: Counter[str] = Counter()
    service_counts: Counter[str] = Counter()
    fault_types = sorted({label_parts(case).fault_type for case in cases if label_parts(case).fault_type})
    for case in cases:
        parts = label_parts(case)
        if parts.service and parts.fault_type:
            pair_counts[parts.root] += 1
            service_counts[parts.service] += 1
    return {
        "pair_counts": dict(pair_counts),
        "service_counts": dict(service_counts),
        "fault_types": fault_types,
    }


def build_dependency_graph(cases: list[DatasetCase]) -> dict[str, dict[str, float]]:
    known_services = sorted({label_parts(case).service for case in cases if label_parts(case).service})
    edges: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        traces = case.evidence.traces if isinstance(case.evidence.traces, dict) else {}
        for span in traces.get("spans") or []:
            if not isinstance(span, dict):
                continue
            source = normalize_service(str(span.get("service_name", "")))
            target = operation_target_service(str(span.get("operation", "")), known_services)
            if source and target and source != target:
                edges[source][target] += max(1.0, safe_float(span.get("count", 1.0)))
    return {
        source: normalize_score_dict(dict(targets))
        for source, targets in edges.items()
        if targets
    }


def operation_target_service(operation: str, known_services: list[str]) -> str:
    text = normalize_feature_text(operation)
    compact = "".join(character for character in text if character.isalnum())
    matches: list[tuple[int, str]] = []
    for service in known_services:
        normalized = normalize_service(service)
        token = "".join(character for character in normalized if character.isalnum())
        aliases = {token}
        if token.endswith("service"):
            aliases.add(token[: -len("service")])
        best = max((len(alias) for alias in aliases if alias and alias in compact), default=0)
        if best:
            matches.append((best, normalized))
    return max(matches)[1] if matches else ""


def tune_hierarchical_fusion_weights(
    dev_cases: list[DatasetCase],
    models: dict[str, Any],
) -> dict[str, float]:
    default = {
        "service_weight": 1.0,
        "fault_weight": 1.0,
        "model_fault_mix": 0.5,
        "temporal_pair_weight": 0.5,
        "compatibility_weight": 0.0,
    }
    if not dev_cases:
        return default

    best_weights = default
    best_score = (-1.0, -1.0, -1.0, -1.0)
    for model_fault_mix, temporal_pair_weight, compatibility_weight in product(
        (0.0, 0.5, 1.0),
        (0.5, 1.0, 2.0),
        (0.0, 0.1),
    ):
        weights = {
            "service_weight": 1.0,
            "fault_weight": 1.0,
            "model_fault_mix": model_fault_mix,
            "temporal_pair_weight": temporal_pair_weight,
            "compatibility_weight": compatibility_weight,
        }
        predicted = [
            attach_prediction(case, predict_hierarchical_temporal_fusion(case, models, weights))
            for case in dev_cases
        ]
        metrics = evaluate_predictions(predicted)
        score = (
            float(metrics.get("root_top3_accuracy") or 0.0),
            float(metrics.get("root_mrr") or 0.0),
            float(metrics.get("root_accuracy") or 0.0),
            float(metrics.get("fault_type_macro_f1") or 0.0),
        )
        if score > best_score:
            best_score = score
            best_weights = weights
    return best_weights


def tune_late_fusion_weights(
    train_cases: list[DatasetCase],
    dev_cases: list[DatasetCase],
    models: dict[str, Any],
) -> dict[str, float]:
    if not dev_cases:
        return {"logs": 1.0, "metrics": 1.0, "traces": 1.0}
    candidates = [0.5, 1.0, 2.0, 3.0]
    best_weights = {"logs": 1.0, "metrics": 1.0, "traces": 1.0}
    best_score = (-1.0, -1.0, -1.0)
    for logs_w, metrics_w, traces_w in product(candidates, repeat=3):
        weights = {"logs": logs_w, "metrics": metrics_w, "traces": traces_w}
        predicted = [
            attach_prediction(case, predict_late_fusion(case, models, weights))
            for case in dev_cases
        ]
        metrics = evaluate_predictions(predicted)
        score = (
            float(metrics.get("root_accuracy") or 0.0),
            float(metrics.get("root_top3_accuracy") or 0.0),
            float(metrics.get("fault_type_macro_f1") or 0.0),
        )
        if score > best_score:
            best_score = score
            best_weights = weights
    return best_weights


def predict_case(case: DatasetCase, method: str, models: dict[str, Any]) -> dict[str, Any]:
    if method == "majority_prior":
        service = models["majority"]["service"]
        fault = models["majority"]["fault_type"]
        return build_prediction(method, [(service, 1.0)], [(fault, 1.0)], root_ranking=[(models["majority"]["root"], 1.0)])
    if method == "keyword_heuristic":
        return predict_keyword_heuristic(case)
    if method == "joint_root_tfidf":
        root_ranking = models["all"]["root"].ranking(case)
        top_root = root_ranking[0][0] if root_ranking else "unknown:unknown"
        service, fault = split_root(top_root)
        return build_prediction(method, [(service, root_ranking[0][1] if root_ranking else 1.0)], [(fault, root_ranking[0][1] if root_ranking else 1.0)], root_ranking=root_ranking)
    if method == "logs_tfidf":
        return predict_from_models(method, case, models["logs"])
    if method == "metrics_tfidf":
        return predict_from_models(method, case, models["metrics"])
    if method == "traces_tfidf":
        return predict_from_models(method, case, models["traces"])
    if method == "early_fusion_tfidf":
        return predict_from_models(method, case, models["all"])
    if method == "late_fusion_tfidf":
        return predict_late_fusion(case, models, models["late_fusion_weights"])
    if method == "temporal_signal_fusion":
        return predict_temporal_signal_fusion(case)
    if method == "temporal_fusion_tfidf":
        return predict_from_models(method, case, models["temporal"])
    if method == "hierarchical_temporal_fusion":
        return predict_hierarchical_temporal_fusion(case, models, models["hierarchical_fusion_weights"])
    if method == "baro_reproduction":
        return predict_baro_reproduction(case, models["service_vocabulary"])
    if method == "multi_source_baro_reproduction":
        return predict_multi_source_baro_reproduction(case, models["service_vocabulary"])
    if method == "cloudranger_reproduction":
        return predict_cloudranger_reproduction(
            case,
            models["dependency_graph"],
            models["service_vocabulary"],
        )
    if method == "tracerca_reproduction":
        return predict_tracerca_reproduction(case, models["service_vocabulary"])
    raise ValueError(f"Unknown method: {method}")


def predict_from_models(method: str, case: DatasetCase, model_set: dict[str, CentroidClassifier]) -> dict[str, Any]:
    service_ranking = model_set["service"].ranking(case)
    fault_ranking = model_set["fault_type"].ranking(case)
    root_ranking = compose_root_ranking(service_ranking, fault_ranking)
    return build_prediction(method, service_ranking, fault_ranking, root_ranking=root_ranking)


def predict_late_fusion(case: DatasetCase, models: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    service_scores: dict[str, float] = defaultdict(float)
    fault_scores: dict[str, float] = defaultdict(float)
    modality_scores: dict[str, dict[str, Any]] = {}
    for name in ("logs", "metrics", "traces"):
        weight = float(weights.get(name, 1.0))
        if weight <= 0:
            continue
        service_raw = models[name]["service"].scores(case)
        fault_raw = models[name]["fault_type"].scores(case)
        modality_scores[name] = {
            "service_top": top_items(service_raw),
            "fault_type_top": top_items(fault_raw),
            "weight": weight,
        }
        for label, score in normalize_score_dict(service_raw).items():
            service_scores[label] += weight * score
        for label, score in normalize_score_dict(fault_raw).items():
            fault_scores[label] += weight * score
    service_ranking = sorted(service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = sorted(fault_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    prediction = build_prediction(
        "late_fusion_tfidf",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )
    prediction["fusion_weights"] = weights
    prediction["modality_scores"] = modality_scores
    return prediction


def predict_keyword_heuristic(case: DatasetCase) -> dict[str, Any]:
    service_scores: Counter[str] = Counter()
    fault_scores: Counter[str] = Counter()
    evidence = case.evidence

    logs = evidence.logs if isinstance(evidence.logs, dict) else {}
    for service, count in (logs.get("component_counts") or {}).items():
        service_scores[normalize_service(str(service))] += safe_float(count)
    for template, count in (logs.get("event_template_counts") or {}).items():
        add_fault_keyword_scores(fault_scores, str(template), safe_float(count))

    metrics = evidence.metrics if isinstance(evidence.metrics, dict) else {}
    last_values = (metrics.get("telemetry_summary") or {}).get("last_values") or {}
    for metric_name, value in last_values.items():
        service = service_from_metric_name(str(metric_name))
        if service:
            service_scores[service] += math.log1p(abs(safe_float(value)))
        add_fault_keyword_scores(fault_scores, str(metric_name), max(1.0, math.log1p(abs(safe_float(value)))))

    traces = evidence.traces if isinstance(evidence.traces, dict) else {}
    for service, count in (traces.get("service_counts") or {}).items():
        service_scores[normalize_service(str(service))] += 0.25 * safe_float(count)
    for span in traces.get("spans") or []:
        if not isinstance(span, dict):
            continue
        service = normalize_service(str(span.get("service_name", "")))
        count = safe_float(span.get("count", 1))
        if service:
            service_scores[service] += 3.0 * count
        add_fault_keyword_scores(fault_scores, json.dumps(span, ensure_ascii=False), 3.0 * count)

    if not service_scores:
        service_scores["unknown"] = 1.0
    if not fault_scores:
        fault_scores["unknown"] = 1.0
    service_ranking = sorted(service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = sorted(fault_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return build_prediction(
        "keyword_heuristic",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )


def predict_baro_reproduction(case: DatasetCase, service_vocabulary: list[str]) -> dict[str, Any]:
    """Adapt BARO's robust change-point ranking to the normalized RCAEval case.

    The published BARO implementation ranks metric columns using a robust
    scaler between pre-injection and post-injection windows. The normalized
    cases retain aggregate CSV paths, so we reproduce that scoring and map
    metric columns to service/fault labels for the common evaluator.
    """
    metric_scores = baro_metric_scores(case)
    service_scores: Counter[str] = Counter()
    fault_scores: Counter[str] = Counter()
    for metric, score in metric_scores:
        service = normalize_service(service_from_metric_name(metric))
        fault = infer_fault_family_from_metric(metric)
        if service in service_vocabulary:
            service_scores[service] += score
        if fault != "unknown":
            fault_scores[fault] += score
    if not service_scores:
        service_scores["unknown"] = 1.0
    if not fault_scores:
        fault_scores["unknown"] = 1.0
    service_ranking = sorted(service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = sorted(fault_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    prediction = build_prediction(
        "baro_reproduction",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )
    prediction["metric_ranking"] = [metric for metric, _ in metric_scores[:20]]
    return prediction


def predict_multi_source_baro_reproduction(case: DatasetCase, service_vocabulary: list[str]) -> dict[str, Any]:
    """Reproduce Multi-source BARO with equal modality fusion.

    The official implementation consumes metric, log time-series and trace
    time-series tables. Here logs/traces are already aggregated, so their
    modality scores are computed from error counts and failed-span counts;
    this approximation is explicitly recorded in the experiment report.
    """
    modality_service: dict[str, Counter[str]] = {
        "metrics": Counter(),
        "logs": Counter(),
        "traces": Counter(),
    }
    modality_fault: dict[str, Counter[str]] = {
        "metrics": Counter(),
        "logs": Counter(),
        "traces": Counter(),
    }
    for metric, score in baro_metric_scores(case):
        service = service_from_metric_name(metric)
        fault = infer_fault_family_from_metric(metric)
        if service in service_vocabulary:
            modality_service["metrics"][service] += score
        if fault != "unknown":
            modality_fault["metrics"][fault] += score

    logs = case.evidence.logs if isinstance(case.evidence.logs, dict) else {}
    log_error = max(1.0, safe_float(logs.get("actionable_warning_error_count", 0.0)))
    for service, count in (logs.get("component_counts") or {}).items():
        normalized_service = normalize_service(str(service))
        if normalized_service in service_vocabulary:
            modality_service["logs"][normalized_service] += log_error * math.log1p(safe_float(count))
    for template, count in (logs.get("event_template_counts") or {}).items():
        add_fault_keyword_scores(modality_fault["logs"], str(template), math.log1p(safe_float(count)))

    traces = case.evidence.traces if isinstance(case.evidence.traces, dict) else {}
    for span in traces.get("spans") or []:
        if not isinstance(span, dict):
            continue
        status = str(span.get("status_code", "0.0"))
        if status in {"0", "0.0", "ok", "OK"}:
            continue
        service = normalize_service(str(span.get("service_name", "")))
        amount = max(1.0, safe_float(span.get("count", 1.0)))
        if service in service_vocabulary:
            modality_service["traces"][service] += amount
        modality_fault["traces"]["loss"] += amount

    service_scores: Counter[str] = Counter()
    fault_scores: Counter[str] = Counter()
    modality_scores: dict[str, dict[str, Any]] = {}
    for modality in ("metrics", "logs", "traces"):
        service_distribution = normalize_score_dict(dict(modality_service[modality]))
        fault_distribution = normalize_score_dict(dict(modality_fault[modality]))
        modality_scores[modality] = {
            "service_top": top_items(service_distribution),
            "fault_type_top": top_items(fault_distribution),
        }
        for label, score in service_distribution.items():
            service_scores[label] += score
        for label, score in fault_distribution.items():
            fault_scores[label] += score
    if not service_scores:
        service_scores["unknown"] = 1.0
    if not fault_scores:
        fault_scores["unknown"] = 1.0
    service_ranking = sorted(service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = sorted(fault_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    prediction = build_prediction(
        "multi_source_baro_reproduction",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )
    prediction["modality_scores"] = modality_scores
    return prediction


def predict_cloudranger_reproduction(
    case: DatasetCase,
    dependency_graph: dict[str, dict[str, float]],
    service_vocabulary: list[str],
) -> dict[str, Any]:
    """Adapt CloudRanger's graph-based anomaly propagation to service nodes."""
    base = Counter()
    for metric, score in baro_metric_scores(case):
        service = service_from_metric_name(metric)
        if service in service_vocabulary:
            base[service] += score
    if not base:
        base["unknown"] = 1.0
    base_distribution = normalize_score_dict(dict(base))
    propagated = dict(base_distribution)
    for _ in range(5):
        next_scores = dict(base_distribution)
        for source, targets in dependency_graph.items():
            source_score = propagated.get(source, 0.0)
            for target, edge_weight in targets.items():
                next_scores[target] = next_scores.get(target, 0.0) + 0.35 * source_score * edge_weight
        propagated = normalize_score_dict(next_scores)
    service_ranking = sorted(propagated.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = fault_ranking_from_temporal_evidence(case)
    return build_prediction(
        "cloudranger_reproduction",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )


def predict_tracerca_reproduction(case: DatasetCase, service_vocabulary: list[str]) -> dict[str, Any]:
    """Adapt TraceRCA support/confidence ranking to aggregate span evidence."""
    traces = case.evidence.traces if isinstance(case.evidence.traces, dict) else {}
    service_scores: Counter[str] = Counter()
    operation_counts: Counter[str] = Counter()
    failed_counts: Counter[str] = Counter()
    known_services = service_vocabulary
    for span in traces.get("spans") or []:
        if not isinstance(span, dict):
            continue
        operation = str(span.get("operation", ""))
        operation_key = normalize_feature_text(operation)
        count = max(1.0, safe_float(span.get("count", 1.0)))
        failed = str(span.get("status_code", "0.0")) not in {"0", "0.0", "ok", "OK"}
        operation_counts[operation_key] += count
        if failed:
            failed_counts[operation_key] += count
        service = operation_target_service(operation, known_services)
        if not service:
            service = normalize_service(str(span.get("service_name", "")))
        if service in service_vocabulary and failed:
            support = count / max(1.0, safe_float(traces.get("failed_span_count", count)))
            confidence = count / max(1.0, operation_counts[operation_key])
            service_scores[service] += support * confidence
    if not service_scores:
        service_scores["unknown"] = 1.0
    service_ranking = sorted(service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = [("loss", 1.0)] if failed_counts else [("unknown", 1.0)]
    return build_prediction(
        "tracerca_reproduction",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )


def fault_ranking_from_temporal_evidence(case: DatasetCase) -> list[tuple[str, float]]:
    scores: Counter[str] = Counter()
    for signal in raw_metric_signals(case):
        fault = str(signal.get("fault_family", ""))
        if fault and fault != "unknown":
            scores[fault] += safe_float(signal.get("score", 0.0))
    if not scores:
        scores["unknown"] = 1.0
    return sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)


def baro_metric_scores(case: DatasetCase) -> list[tuple[str, float]]:
    source_files = case.metadata.get("source_files", {}) if isinstance(case.metadata, dict) else {}
    metrics_path = source_files.get("metrics") if isinstance(source_files, dict) else ""
    if metrics_path and case.fault_time:
        return cached_baro_metric_scores(str(metrics_path), int(case.fault_time))
    return [
        (str(signal.get("metric", "")), safe_float(signal.get("score", 0.0)))
        for signal in raw_metric_signals(case)
    ]


def predict_temporal_signal_fusion(case: DatasetCase) -> dict[str, Any]:
    metric_signals = raw_metric_signals(case)
    service_scores: Counter[str] = Counter()
    fault_scores: Counter[str] = Counter()

    for signal in metric_signals:
        service = normalize_service(str(signal.get("service", "")))
        fault_family = str(signal.get("fault_family", ""))
        score = safe_float(signal.get("score", 0.0))
        if service:
            service_scores[service] += score
        if fault_family:
            fault_scores[fault_family] += score
        if service and fault_family:
            service_scores[f"{service}::{fault_family}"] += 0.15 * score

    # Logs and traces are weaker localization hints. They are added with lower
    # weights because high-volume caller services can dominate raw counts.
    logs = case.evidence.logs if isinstance(case.evidence.logs, dict) else {}
    for service, count in (logs.get("component_counts") or {}).items():
        service_scores[normalize_service(str(service))] += 0.05 * math.log1p(safe_float(count))
    traces = case.evidence.traces if isinstance(case.evidence.traces, dict) else {}
    for span in traces.get("spans") or []:
        if isinstance(span, dict):
            service = normalize_service(str(span.get("service_name", "")))
            if service:
                service_scores[service] += 2.0 * math.log1p(safe_float(span.get("count", 1)))
            add_fault_keyword_scores(
                fault_scores,
                json.dumps(span, ensure_ascii=False),
                1.5 * math.log1p(safe_float(span.get("count", 1))),
            )

    normalized_service_scores = Counter()
    for key, value in service_scores.items():
        if "::" not in key:
            normalized_service_scores[key] += value
    if not normalized_service_scores:
        normalized_service_scores["unknown"] = 1.0
    if not fault_scores:
        fault_scores["unknown"] = 1.0
    service_ranking = sorted(normalized_service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = sorted(fault_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    prediction = build_prediction(
        "temporal_signal_fusion",
        service_ranking,
        fault_ranking,
        root_ranking=compose_root_ranking(service_ranking, fault_ranking),
    )
    prediction["top_metric_signals"] = [
        {
            "metric": str(signal.get("metric", "")),
            "service": str(signal.get("service", "")),
            "fault_family": str(signal.get("fault_family", "")),
            "score": round(safe_float(signal.get("score", 0.0)), 6),
        }
        for signal in metric_signals[:12]
    ]
    return prediction


def predict_hierarchical_temporal_fusion(
    case: DatasetCase,
    models: dict[str, Any],
    weights: dict[str, float],
) -> dict[str, Any]:
    cache = models.setdefault("_hierarchical_case_cache", {})
    cache_key = id(case)
    components = cache.get(cache_key)
    if components is None:
        signal_prediction = predict_temporal_signal_fusion(case)
        service_signal_scores = {
            str(item["label"]): safe_float(item["score"])
            for item in signal_prediction.get("root_cause_service_scores", [])
        }
        fault_signal_scores = {
            str(item["label"]): safe_float(item["score"])
            for item in signal_prediction.get("fault_type_scores", [])
        }
        pair_scores: Counter[str] = Counter()
        for signal in raw_metric_signals(case):
            service = normalize_service(str(signal.get("service", "")))
            fault = str(signal.get("fault_family", ""))
            if service and fault and fault != "unknown":
                pair_scores[f"{service}:{fault}"] += safe_float(signal.get("score", 0.0))
        components = {
            "signal_prediction": signal_prediction,
            "service_signal_scores": service_signal_scores,
            "fault_signal_scores": fault_signal_scores,
            "model_fault_scores": models["temporal"]["fault_type"].scores(case),
            "pair_scores": dict(pair_scores),
        }
        cache[cache_key] = components
    signal_prediction = components["signal_prediction"]
    service_signal_scores = components["service_signal_scores"]
    fault_signal_scores = components["fault_signal_scores"]
    service_scores = normalize_score_dict(service_signal_scores)
    fault_scores = blend_score_distributions(
        fault_signal_scores,
        components["model_fault_scores"],
        safe_float(weights.get("model_fault_mix", 0.5)),
    )
    normalized_pair_scores = normalize_score_dict(components["pair_scores"])

    service_ranking = sorted(service_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    fault_ranking = sorted(fault_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    compatibility = models.get("root_compatibility", {})
    roots: list[tuple[str, float]] = []
    root_components: dict[str, dict[str, float]] = {}
    for service, service_score in service_ranking[:10]:
        for fault, fault_score in fault_ranking[:10]:
            root = f"{service}:{fault}"
            pair_score = normalized_pair_scores.get(root, 0.0)
            compatibility_score = smoothed_compatibility(service, fault, compatibility)
            score = (
                safe_float(weights.get("service_weight", 1.0)) * service_score
                + safe_float(weights.get("fault_weight", 1.0)) * fault_score
                + safe_float(weights.get("temporal_pair_weight", 0.5)) * pair_score
                + safe_float(weights.get("compatibility_weight", 0.0)) * compatibility_score
            )
            roots.append((root, score))
            root_components[root] = {
                "service": service_score,
                "fault": fault_score,
                "temporal_pair": pair_score,
                "compatibility": compatibility_score,
            }
    root_ranking = sorted(roots, key=lambda item: (item[1], item[0]), reverse=True)[:20]
    prediction = build_prediction(
        "hierarchical_temporal_fusion",
        service_ranking,
        fault_ranking,
        root_ranking=root_ranking,
    )
    prediction["fusion_weights"] = dict(weights)
    prediction["root_score_components"] = {
        root: {name: round(value, 6) for name, value in root_components[root].items()}
        for root, _ in root_ranking[:10]
    }
    prediction["top_metric_signals"] = signal_prediction.get("top_metric_signals", [])
    return prediction


def blend_score_distributions(
    primary: dict[str, float],
    secondary: dict[str, float],
    secondary_weight: float,
) -> dict[str, float]:
    mix = min(1.0, max(0.0, secondary_weight))
    first = normalize_score_dict(primary)
    second = normalize_score_dict(secondary)
    labels = set(first) | set(second)
    return {
        label: (1.0 - mix) * first.get(label, 0.0) + mix * second.get(label, 0.0)
        for label in labels
    }


def smoothed_compatibility(service: str, fault: str, compatibility: dict[str, Any]) -> float:
    pair_counts = compatibility.get("pair_counts", {})
    service_counts = compatibility.get("service_counts", {})
    fault_count = max(1, len(compatibility.get("fault_types", [])))
    numerator = safe_float(pair_counts.get(f"{service}:{fault}", 0.0)) + 1.0
    denominator = safe_float(service_counts.get(service, 0.0)) + fault_count
    return numerator / denominator if denominator > 0 else 1.0 / fault_count


def build_prediction(
    method: str,
    service_ranking: list[tuple[str, float]],
    fault_ranking: list[tuple[str, float]],
    *,
    root_ranking: list[tuple[str, float]],
) -> dict[str, Any]:
    service = service_ranking[0][0] if service_ranking else "unknown"
    fault = fault_ranking[0][0] if fault_ranking else "unknown"
    root = root_ranking[0][0] if root_ranking else f"{service}:{fault}"
    root_service, root_fault = split_root(root)
    return {
        "method": method,
        "root_cause": root,
        "root_cause_service": root_service or service,
        "fault_type": root_fault or fault,
        "root_cause_ranking": [label for label, _ in root_ranking[:10]],
        "root_cause_service_ranking": [label for label, _ in service_ranking[:10]],
        "fault_type_ranking": [label for label, _ in fault_ranking[:10]],
        "root_cause_scores": score_items(root_ranking),
        "root_cause_service_scores": score_items(service_ranking),
        "fault_type_scores": score_items(fault_ranking),
    }


def compose_root_ranking(
    service_ranking: list[tuple[str, float]],
    fault_ranking: list[tuple[str, float]],
    limit: int = 20,
) -> list[tuple[str, float]]:
    roots = []
    for service, service_score in service_ranking[:10]:
        for fault, fault_score in fault_ranking[:10]:
            roots.append((f"{service}:{fault}", float(service_score) + float(fault_score)))
    return sorted(roots, key=lambda item: (item[1], item[0]), reverse=True)[:limit]


def attach_prediction(case: DatasetCase, prediction: dict[str, Any]) -> DatasetCase:
    metadata = dict(case.metadata)
    metadata["prediction"] = prediction
    return DatasetCase(
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


def label_parts(case: DatasetCase) -> LabelParts:
    root = str(case.label.final_root_cause if case.label else "")
    service, fault = split_root(root)
    if not service:
        service = str(case.metadata.get("root_cause_service", ""))
    if not fault:
        fault = str(case.metadata.get("fault_type", ""))
    return LabelParts(service=service, fault_type=fault, root=":".join(part for part in (service, fault) if part))


def split_root(root: str) -> tuple[str, str]:
    if ":" not in root:
        return root, ""
    service, fault = root.rsplit(":", 1)
    return service, fault


def log_features(case: DatasetCase) -> Counter[str]:
    logs = case.evidence.logs if isinstance(case.evidence.logs, dict) else {}
    features: Counter[str] = Counter()
    add_count_features(features, "log_component", logs.get("component_counts") or {})
    add_count_features(features, "log_template", logs.get("event_template_counts") or {}, normalize=True)
    features[f"log_template_count:{bin_number(logs.get('event_template_count', 0))}"] += 1
    features[f"log_record_count:{bin_number(logs.get('record_count', 0))}"] += 1
    features[f"log_actionable_count:{bin_number(logs.get('actionable_warning_error_count', 0))}"] += 1
    return +features


def metric_features(case: DatasetCase) -> Counter[str]:
    metrics = case.evidence.metrics if isinstance(case.evidence.metrics, dict) else {}
    summary = metrics.get("telemetry_summary") or {}
    last_values = summary.get("last_values") or {}
    features: Counter[str] = Counter()
    features[f"metric_count:{bin_number(summary.get('metric_count', 0))}"] += 1
    features[f"metric_rows:{bin_number(summary.get('row_count', 0))}"] += 1
    for name, value in last_values.items():
        text = normalize_feature_text(name)
        numeric = safe_float(value)
        amount = max(1.0, math.log1p(abs(numeric)))
        features[f"metric_name:{text}"] += 1.0
        for token in tokenize(text):
            features[f"metric_token:{token}"] += amount
        service = service_from_metric_name(str(name))
        if service:
            features[f"metric_service:{service}"] += amount
        features[f"metric_value_bin:{text}:{bin_number(numeric)}"] += 1.0
    return +features


def trace_features(case: DatasetCase) -> Counter[str]:
    traces = case.evidence.traces if isinstance(case.evidence.traces, dict) else {}
    features: Counter[str] = Counter()
    features[f"trace_span_count:{bin_number(traces.get('span_count', 0))}"] += 1
    features[f"trace_failed_span_count:{bin_number(traces.get('failed_span_count', 0))}"] += 1
    add_count_features(features, "trace_service", traces.get("service_counts") or {})
    add_count_features(features, "trace_status", traces.get("status_counts") or {})
    for span in traces.get("spans") or []:
        if not isinstance(span, dict):
            continue
        count = safe_float(span.get("count", 1))
        service = normalize_service(str(span.get("service_name", "")))
        status = normalize_feature_text(span.get("status_code", ""))
        operation = normalize_feature_text(span.get("operation", ""))
        if service:
            features[f"trace_failed_service:{service}"] += count
        if status:
            features[f"trace_failed_status:{status}"] += count
        if operation:
            features[f"trace_failed_operation:{operation}"] += count
            for token in tokenize(operation):
                features[f"trace_operation_token:{token}"] += count
    return +features


def all_features(case: DatasetCase) -> Counter[str]:
    features = Counter()
    features.update({f"logs::{key}": value for key, value in log_features(case).items()})
    features.update({f"metrics::{key}": value for key, value in metric_features(case).items()})
    features.update({f"traces::{key}": value for key, value in trace_features(case).items()})
    return +features


def temporal_all_features(case: DatasetCase) -> Counter[str]:
    features = all_features(case)
    for key, value in raw_metric_temporal_features(case).items():
        features[f"raw_metrics::{key}"] += value
    return +features


def raw_metric_temporal_features(case: DatasetCase) -> Counter[str]:
    features: Counter[str] = Counter()
    for signal in raw_metric_signals(case):
        score = safe_float(signal.get("score", 0.0))
        if score <= 0:
            continue
        amount = math.log1p(score)
        metric = normalize_feature_text(signal.get("metric", ""))
        service = normalize_service(str(signal.get("service", "")))
        fault_family = str(signal.get("fault_family", ""))
        direction = str(signal.get("direction", "flat"))
        if metric:
            features[f"metric:{metric}"] += amount
        if service:
            features[f"service:{service}"] += amount
        if fault_family:
            features[f"fault_family:{fault_family}"] += amount
        if service and fault_family:
            features[f"service_fault_family:{service}:{fault_family}"] += amount
        if fault_family and direction:
            features[f"fault_direction:{fault_family}:{direction}"] += amount
        for token in tokenize(metric):
            features[f"metric_token:{token}"] += amount
    return +features


def raw_metric_signals(case: DatasetCase) -> list[dict[str, Any]]:
    source_files = case.metadata.get("source_files", {}) if isinstance(case.metadata, dict) else {}
    metrics_path = source_files.get("metrics") if isinstance(source_files, dict) else ""
    if not metrics_path:
        return []
    return cached_raw_metric_signals(str(metrics_path))


@lru_cache(maxsize=512)
def cached_raw_metric_signals(metrics_path: str) -> list[dict[str, Any]]:
    path = Path(metrics_path)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return []
        metric_names = [name for name in header[1:] if name]
        size = len(metric_names)
        if not size:
            return []
        first_sums = [0.0] * size
        first_counts = [0] * size
        total_sums = [0.0] * size
        total_squares = [0.0] * size
        total_counts = [0] * size
        last_values: list[list[float]] = [[] for _ in range(size)]
        row_count = 0
        for row in reader:
            row_count += 1
            values = row[1:]
            for index, raw_value in enumerate(values[:size]):
                value = safe_float(raw_value)
                if row_count <= RAW_METRIC_WINDOW:
                    first_sums[index] += value
                    first_counts[index] += 1
                total_sums[index] += value
                total_squares[index] += value * value
                total_counts[index] += 1
                bucket = last_values[index]
                bucket.append(value)
                if len(bucket) > RAW_METRIC_WINDOW:
                    del bucket[0]

    signals: list[dict[str, Any]] = []
    for index, name in enumerate(metric_names):
        count = total_counts[index]
        if count <= 1 or first_counts[index] == 0 or not last_values[index]:
            continue
        first_mean = first_sums[index] / first_counts[index]
        last_mean = sum(last_values[index]) / len(last_values[index])
        total_mean = total_sums[index] / count
        variance = max(0.0, total_squares[index] / count - total_mean * total_mean)
        std = math.sqrt(variance)
        delta = last_mean - first_mean
        z_score = abs(delta) / (std + 1e-9)
        relative = abs(delta) / (abs(first_mean) + 1.0)
        score = z_score + math.log1p(relative)
        if score <= 0:
            continue
        family = infer_fault_family_from_metric(name)
        service = service_from_metric_name(name)
        signals.append(
            {
                "metric": name,
                "service": service,
                "fault_family": family,
                "score": score,
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
                "first_mean": first_mean,
                "last_mean": last_mean,
                "std": std,
            }
        )
    return sorted(signals, key=lambda item: (safe_float(item["score"]), str(item["metric"])), reverse=True)[
        :RAW_METRIC_TOP_N
    ]


@lru_cache(maxsize=512)
def cached_baro_metric_scores(metrics_path: str, fault_time: int) -> list[tuple[str, float]]:
    path = Path(metrics_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return []
        metric_names = [name for name in header[1:] if name]
        normal_values: list[list[float]] = [[] for _ in metric_names]
        anomalous_values: list[list[float]] = [[] for _ in metric_names]
        for row in reader:
            if not row:
                continue
            target = normal_values if safe_float(row[0]) < fault_time else anomalous_values
            for index, raw_value in enumerate(row[1 : len(metric_names) + 1]):
                target[index].append(safe_float(raw_value))

    ranks: list[tuple[str, float]] = []
    for name, normal, anomalous in zip(metric_names, normal_values, anomalous_values):
        if len(normal) < 2 or not anomalous:
            continue
        median = quantile(normal, 0.5)
        scale = quantile(normal, 0.75) - quantile(normal, 0.25)
        if scale <= 1e-12:
            continue
        score = max((value - median) / scale for value in anomalous)
        ranks.append((name, max(0.0, score)))
    return sorted(ranks, key=lambda item: (item[1], item[0]), reverse=True)


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = min(1.0, max(0.0, probability)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def infer_fault_family_from_metric(metric_name: str) -> str:
    text = metric_name.casefold()
    if "cpu" in text:
        return "cpu"
    if "memory" in text or "mem" in text or "rss" in text or "working-set" in text or "swap" in text:
        return "mem"
    if "disk" in text or "blkio" in text or "fs-" in text or "read" in text or "write" in text:
        return "disk"
    if "latency" in text or "duration" in text:
        return "delay"
    if "error" in text or "drop" in text or "dropped" in text or "loss" in text:
        return "loss"
    if "socket" in text:
        return "socket"
    if "network" in text:
        return "loss"
    return "unknown"


def add_count_features(features: Counter[str], prefix: str, values: dict[str, Any], *, normalize: bool = False) -> None:
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        text = normalize_feature_text(key) if normalize else normalize_service(str(key))
        amount = max(1.0, math.log1p(safe_float(value)))
        features[f"{prefix}:{text}"] += amount


def add_fault_keyword_scores(scores: Counter[str], text: str, amount: float) -> None:
    normalized = normalize_feature_text(text)
    for fault, keywords in FAULT_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            scores[fault] += amount


def service_from_metric_name(name: str) -> str:
    text = name.casefold()
    if "_" not in text:
        return ""
    return normalize_service(text.split("_", 1)[0])


def normalize_service(value: str) -> str:
    text = value.casefold().strip()
    replacements = {
        "frontendservice": "frontend",
        "front-end": "front-end",
        "cartservice": "carts",
        "paymentservice": "payment",
        "redis-master": "redis",
    }
    return replacements.get(text, text)


def evaluate_predictions(
    cases: list[DatasetCase],
    reference_roots: set[str] | None = None,
) -> dict[str, Any]:
    labeled = [case for case in cases if case.label is not None]
    root_top1 = accuracy(labeled, "root_cause", lambda case: label_parts(case).root)
    root_top3 = topk_accuracy(labeled, "root_cause_ranking", lambda case: label_parts(case).root, 3)
    diagnostics = factorization_diagnostics(labeled)
    metrics = {
        "case_count": len(cases),
        "root_accuracy": root_top1,
        "root_top3_accuracy": root_top3,
        "root_top5_accuracy": topk_accuracy(labeled, "root_cause_ranking", lambda case: label_parts(case).root, 5),
        "root_mrr": reciprocal_rank(labeled, "root_cause_ranking", lambda case: label_parts(case).root),
        "root_top3_gain": round(float(root_top3 or 0.0) - float(root_top1 or 0.0), 4),
        "service_accuracy": accuracy(labeled, "root_cause_service", lambda case: label_parts(case).service),
        "service_top3_accuracy": topk_accuracy(labeled, "root_cause_service_ranking", lambda case: label_parts(case).service, 3),
        "fault_type_accuracy": accuracy(labeled, "fault_type", lambda case: label_parts(case).fault_type),
        "fault_type_top3_accuracy": topk_accuracy(labeled, "fault_type_ranking", lambda case: label_parts(case).fault_type, 3),
        "root_macro_f1": macro_f1(labeled, "root_cause", lambda case: label_parts(case).root),
        "service_macro_f1": macro_f1(labeled, "root_cause_service", lambda case: label_parts(case).service),
        "fault_type_macro_f1": macro_f1(labeled, "fault_type", lambda case: label_parts(case).fault_type),
        "root_label_distribution": dict(Counter(label_parts(case).root for case in labeled)),
        "service_label_distribution": dict(Counter(label_parts(case).service for case in labeled)),
        "fault_type_label_distribution": dict(Counter(label_parts(case).fault_type for case in labeled)),
        "root_prediction_distribution": prediction_distribution(labeled, "root_cause"),
        "service_prediction_distribution": prediction_distribution(labeled, "root_cause_service"),
        "fault_type_prediction_distribution": prediction_distribution(labeled, "fault_type"),
        "root_confusion": confusion(labeled, "root_cause", lambda case: label_parts(case).root),
        "service_confusion": confusion(labeled, "root_cause_service", lambda case: label_parts(case).service),
        "fault_type_confusion": confusion(labeled, "fault_type", lambda case: label_parts(case).fault_type),
        **diagnostics,
    }
    if reference_roots is not None:
        unseen = [case for case in labeled if label_parts(case).root not in reference_roots]
        metrics.update(
            {
                "unseen_root_case_count": len(unseen),
                "unseen_root_accuracy": accuracy(unseen, "root_cause", lambda case: label_parts(case).root),
                "unseen_root_top3_accuracy": topk_accuracy(
                    unseen, "root_cause_ranking", lambda case: label_parts(case).root, 3
                ),
                "unseen_root_top5_accuracy": topk_accuracy(
                    unseen, "root_cause_ranking", lambda case: label_parts(case).root, 5
                ),
                "unseen_root_mrr": reciprocal_rank(
                    unseen, "root_cause_ranking", lambda case: label_parts(case).root
                ),
            }
        )
    return metrics


def factorization_diagnostics(cases: list[DatasetCase]) -> dict[str, Any]:
    if not cases:
        return {
            "factor_service_correct_rate": None,
            "factor_fault_correct_rate": None,
            "factor_both_correct_rate": None,
            "factor_service_only_correct_rate": None,
            "factor_fault_only_correct_rate": None,
            "combination_consistency_rate": None,
        }
    service_correct = 0
    fault_correct = 0
    both_correct = 0
    service_only = 0
    fault_only = 0
    consistent = 0
    for case in cases:
        prediction = case.metadata.get("prediction", {})
        service_ranking = prediction.get("root_cause_service_ranking", [])
        fault_ranking = prediction.get("fault_type_ranking", [])
        predicted_service = service_ranking[0] if service_ranking else "unknown"
        predicted_fault = fault_ranking[0] if fault_ranking else "unknown"
        parts = label_parts(case)
        service_ok = predicted_service == parts.service
        fault_ok = predicted_fault == parts.fault_type
        service_correct += int(service_ok)
        fault_correct += int(fault_ok)
        both_correct += int(service_ok and fault_ok)
        service_only += int(service_ok and not fault_ok)
        fault_only += int(fault_ok and not service_ok)
        consistent += int(prediction.get("root_cause") == f"{predicted_service}:{predicted_fault}")
    count = len(cases)
    return {
        "factor_service_correct_rate": round(service_correct / count, 4),
        "factor_fault_correct_rate": round(fault_correct / count, 4),
        "factor_both_correct_rate": round(both_correct / count, 4),
        "factor_service_only_correct_rate": round(service_only / count, 4),
        "factor_fault_only_correct_rate": round(fault_only / count, 4),
        "combination_consistency_rate": round(consistent / count, 4),
    }


def evaluate_grouped(cases: list[DatasetCase], key_getter: Callable[[DatasetCase], str]) -> dict[str, Any]:
    grouped: dict[str, list[DatasetCase]] = defaultdict(list)
    for case in cases:
        grouped[str(key_getter(case) or "unknown")].append(case)
    return {key: compact_metrics(evaluate_predictions(group_cases)) for key, group_cases in sorted(grouped.items())}


def compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "case_count",
        "root_accuracy",
        "root_top3_accuracy",
        "root_top5_accuracy",
        "root_mrr",
        "root_top3_gain",
        "unseen_root_case_count",
        "unseen_root_accuracy",
        "unseen_root_top3_accuracy",
        "unseen_root_top5_accuracy",
        "unseen_root_mrr",
        "service_accuracy",
        "service_top3_accuracy",
        "fault_type_accuracy",
        "fault_type_top3_accuracy",
        "root_macro_f1",
        "service_macro_f1",
        "fault_type_macro_f1",
        "factor_service_correct_rate",
        "factor_fault_correct_rate",
        "factor_both_correct_rate",
        "factor_service_only_correct_rate",
        "factor_fault_only_correct_rate",
        "combination_consistency_rate",
        "root_prediction_distribution",
        "service_prediction_distribution",
        "fault_type_prediction_distribution",
        "root_label_distribution",
        "service_label_distribution",
        "fault_type_label_distribution",
    ]
    return {key: metrics.get(key) for key in keys}


def split_label_overlap(
    train_cases: list[DatasetCase],
    dev_cases: list[DatasetCase],
    test_cases: list[DatasetCase],
) -> dict[str, Any]:
    train_roots = {label_parts(case).root for case in train_cases}
    dev_roots = {label_parts(case).root for case in dev_cases}
    test_roots = {label_parts(case).root for case in test_cases}
    train_services = {label_parts(case).service for case in train_cases}
    test_services = {label_parts(case).service for case in test_cases}
    train_faults = {label_parts(case).fault_type for case in train_cases}
    test_faults = {label_parts(case).fault_type for case in test_cases}
    return {
        "train_root_count": len(train_roots),
        "dev_root_count": len(dev_roots),
        "test_root_count": len(test_roots),
        "test_roots_seen_in_train": len(test_roots & train_roots),
        "test_roots_unseen_in_train": len(test_roots - train_roots),
        "test_services_seen_in_train": len(test_services & train_services),
        "test_services_unseen_in_train": len(test_services - train_services),
        "test_fault_types_seen_in_train": len(test_faults & train_faults),
        "test_fault_types_unseen_in_train": len(test_faults - train_faults),
    }


def accuracy(cases: list[DatasetCase], prediction_key: str, expected_getter: Callable[[DatasetCase], str]) -> float | None:
    if not cases:
        return None
    correct = sum(1 for case in cases if case.metadata.get("prediction", {}).get(prediction_key) == expected_getter(case))
    return round(correct / len(cases), 4)


def topk_accuracy(
    cases: list[DatasetCase],
    ranking_key: str,
    expected_getter: Callable[[DatasetCase], str],
    k: int,
) -> float | None:
    if not cases:
        return None
    correct = 0
    for case in cases:
        ranking = case.metadata.get("prediction", {}).get(ranking_key, [])
        if expected_getter(case) in ranking[:k]:
            correct += 1
    return round(correct / len(cases), 4)


def reciprocal_rank(
    cases: list[DatasetCase],
    ranking_key: str,
    expected_getter: Callable[[DatasetCase], str],
) -> float | None:
    ranks = []
    for case in cases:
        ranking = case.metadata.get("prediction", {}).get(ranking_key, [])
        expected = expected_getter(case)
        if expected in ranking:
            ranks.append(1 / (ranking.index(expected) + 1))
    return round(sum(ranks) / len(cases), 4) if cases else None


def macro_f1(cases: list[DatasetCase], prediction_key: str, expected_getter: Callable[[DatasetCase], str]) -> float | None:
    matrix = confusion(cases, prediction_key, expected_getter)
    values = [item["f1"] for item in matrix["per_class"] if item["f1"] is not None and item["support"] > 0]
    return round(sum(values) / len(values), 4) if values else None


def confusion(cases: list[DatasetCase], prediction_key: str, expected_getter: Callable[[DatasetCase], str]) -> dict[str, Any]:
    labels = sorted(
        set(expected_getter(case) for case in cases)
        | set(str(case.metadata.get("prediction", {}).get(prediction_key, "unpredicted")) for case in cases)
    )
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        expected = expected_getter(case)
        predicted = str(case.metadata.get("prediction", {}).get(prediction_key, "unpredicted"))
        counts[expected][predicted] += 1
    per_class = []
    for label in labels:
        tp = counts[label][label]
        fp = sum(counts[other][label] for other in labels if other != label)
        fn = sum(count for pred, count in counts[label].items() if pred != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        per_class.append(
            {
                "class": label,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "support": tp + fn,
                "predicted_support": tp + fp,
            }
        )
    return {
        "classes": labels,
        "rows": [
            {"expected": expected, "values": [counts[expected][predicted] for predicted in labels]}
            for expected in labels
        ],
        "per_class": per_class,
    }


def prediction_distribution(cases: list[DatasetCase], prediction_key: str) -> dict[str, int]:
    return dict(Counter(str(case.metadata.get("prediction", {}).get(prediction_key, "unpredicted")) for case in cases))


def build_markdown_report(
    dataset_dir: Path,
    output_dir: Path,
    summary: dict[str, Any],
    per_source: dict[str, Any],
    per_fault: dict[str, Any],
) -> str:
    test_items = {key.replace("test_", ""): value for key, value in summary["methods"].items() if key.startswith("test_")}
    best_root_method = best_method(test_items, "root_accuracy")
    best_fault_method = best_method(test_items, "fault_type_macro_f1")
    overlap = summary.get("split_label_overlap", {})
    lines = [
        "# RCAEval 正式实验报告",
        "",
        "## 数据集与任务",
        "",
        f"- 数据集：`{dataset_dir.relative_to(PROJECT_ROOT)}`",
        f"- 输出目录：`{output_dir.relative_to(PROJECT_ROOT)}`",
        f"- 训练/验证/测试：{summary['train_count']} / {summary['dev_count']} / {summary['test_count']}",
        "- 任务层级：根因服务、故障类型、组合根因 `service:fault_type`。",
        "- 特征来源：只使用 evidence.logs、evidence.metrics、evidence.traces，不使用 case ID、目录路径、split group 或标签元数据。",
        f"- 测试集组合根因：{overlap.get('test_root_count', '-') } 个，其中训练集中已出现 {overlap.get('test_roots_seen_in_train', '-') } 个，未出现 {overlap.get('test_roots_unseen_in_train', '-') } 个。",
        "",
        "## 方法对比",
        "",
        "| 方法 | 根因Top-1 | 根因Top-3 | 根因MRR | 服务Top-1 | 服务Top-3 | 故障类型Top-1 | 故障类型Macro-F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHOD_ORDER:
        item = test_items.get(method)
        if not item:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{method}` {METHOD_LABELS[method]}",
                    pct(item.get("root_accuracy")),
                    pct(item.get("root_top3_accuracy")),
                    decimal(item.get("root_mrr")),
                    pct(item.get("service_accuracy")),
                    pct(item.get("service_top3_accuracy")),
                    pct(item.get("fault_type_accuracy")),
                    pct(item.get("fault_type_macro_f1")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 后期融合权重",
            "",
            f"- logs={summary['selected_late_fusion_weights'].get('logs')}",
            f"- metrics={summary['selected_late_fusion_weights'].get('metrics')}",
            f"- traces={summary['selected_late_fusion_weights'].get('traces')}",
            "",
            "## hierarchical fusion weights",
            "",
            f"- service_weight={summary['selected_hierarchical_fusion_weights'].get('service_weight')}",
            f"- fault_weight={summary['selected_hierarchical_fusion_weights'].get('fault_weight')}",
            f"- model_fault_mix={summary['selected_hierarchical_fusion_weights'].get('model_fault_mix')}",
            f"- temporal_pair_weight={summary['selected_hierarchical_fusion_weights'].get('temporal_pair_weight')}",
            f"- compatibility_weight={summary['selected_hierarchical_fusion_weights'].get('compatibility_weight')}",
            "",
            "## 来源分层",
            "",
        ]
    )
    root_key = f"test_{best_root_method}" if best_root_method else ""
    fault_key = f"test_{best_fault_method}" if best_fault_method else ""
    if root_key in per_source:
        lines.append(f"组合根因 Top-1 最优方法：`{best_root_method}` {METHOD_LABELS.get(best_root_method, '')}")
        lines.extend(group_table(per_source[root_key], "来源"))
    if fault_key in per_source and fault_key != root_key:
        lines.extend(["", f"故障类型 Macro-F1 最优方法：`{best_fault_method}` {METHOD_LABELS.get(best_fault_method, '')}"])
        lines.extend(group_table(per_source[fault_key], "来源"))
    lines.extend(["", "## 故障类型分层", ""])
    if root_key in per_fault:
        lines.append(f"组合根因 Top-1 最优方法：`{best_root_method}` {METHOD_LABELS.get(best_root_method, '')}")
        lines.extend(group_table(per_fault[root_key], "故障类型"))
    if fault_key in per_fault and fault_key != root_key:
        lines.extend(["", f"故障类型 Macro-F1 最优方法：`{best_fault_method}` {METHOD_LABELS.get(best_fault_method, '')}"])
        lines.extend(group_table(per_fault[fault_key], "故障类型"))
    lines.extend(
        [
            "",
            "## 结果解读",
            "",
            "组合根因 `service:fault_type` 在无泄漏切分下比普通分类更难，因为同一注入场景的重复样本不会跨集合出现。若测试组合根因大量未在训练集中出现，根因 Top-1 更接近“服务定位 + 故障类型组合”的泛化能力，而不是记忆训练标签。",
            "因此论文中应同时报告服务 Top-1/Top-3、故障类型 Macro-F1 和组合根因 Top-K，避免只用单一指标解释方法有效性。",
            "",
            "## 解释边界",
            "",
            "RCAEval 是服务级软件故障注入数据，结果可用于证明多源观测证据下的根因定位与模态融合有效性。",
            "这些结果不能表述为终端硬件 FRU 换件准确率，也不能替代真实维修闭环 gold label。",
            "",
        ]
    )
    return "\n".join(lines)


def best_method(items: dict[str, Any], metric: str) -> str:
    best = ""
    best_value = -1.0
    for method, item in items.items():
        value = item.get(metric)
        if value is None:
            continue
        numeric = float(value)
        if numeric > best_value:
            best = method
            best_value = numeric
    return best


def group_table(items: dict[str, Any], label: str) -> list[str]:
    lines = [
        f"| {label} | 样本数 | 根因Top-1 | 根因Top-3 | 服务Top-1 | 故障类型Top-1 | 故障类型Macro-F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in items.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{name}`",
                    str(item.get("case_count")),
                    pct(item.get("root_accuracy")),
                    pct(item.get("root_top3_accuracy")),
                    pct(item.get("service_accuracy")),
                    pct(item.get("fault_type_accuracy")),
                    pct(item.get("fault_type_macro_f1")),
                ]
            )
            + " |"
        )
    return lines


def score_items(items: list[tuple[str, float]], limit: int = 10) -> list[dict[str, Any]]:
    return [{"label": label, "score": round(float(score), 6)} for label, score in items[:limit]]


def top_items(items: dict[str, float], limit: int = 5) -> list[dict[str, Any]]:
    return score_items(sorted(items.items(), key=lambda item: (item[1], item[0]), reverse=True), limit)


def normalize_score_dict(scores: dict[str, float]) -> dict[str, float]:
    positives = {key: max(0.0, float(value)) for key, value in scores.items()}
    total = sum(positives.values())
    if total <= 0:
        total = sum(abs(float(value)) for value in scores.values())
        return {key: abs(float(value)) / total for key, value in scores.items()} if total else {}
    return {key: value / total for key, value in positives.items()}


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


def normalize_feature_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().strip().split())


def tokenize(text: str) -> list[str]:
    tokens = []
    current = []
    for char in normalize_feature_text(text):
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
    return tokens[:60]


def bin_number(value: Any) -> str:
    number = safe_float(value)
    if number == 0:
        return "0"
    sign = "neg" if number < 0 else "pos"
    magnitude = int(math.floor(math.log10(abs(number)))) if abs(number) >= 1 else -1
    return f"{sign}_{magnitude}"


def safe_float(value: Any) -> float:
    try:
        if value in {None, ""}:
            return 0.0
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return 0.0
        return number
    except (TypeError, ValueError):
        return 0.0


def pct(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def decimal(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.4f}"


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
