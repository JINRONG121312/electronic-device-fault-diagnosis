"""Evaluate normalized dataset cases with fault-diagnosis metrics.

This script is intentionally lightweight. It evaluates predictions already
written into each case metadata under metadata.prediction so experiments can
compare different methods without changing the production diagnosis engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fru_diagnosis.datasets import DatasetCase, enrich_case, load_cases_jsonl


def evaluate(cases: list[DatasetCase]) -> dict[str, Any]:
    labeled = [enrich_case(case) for case in cases if case.label is not None]
    with_predictions = [
        case
        for case in labeled
        if isinstance(case.metadata.get("prediction"), dict)
    ]
    target_matrix = build_confusion_matrix(with_predictions, "target")
    fault_origin_matrix = build_confusion_matrix(with_predictions, "fault_origin")
    serviceability_matrix = build_confusion_matrix(with_predictions, "serviceability_type")
    boundary_matrix = build_confusion_matrix(with_predictions, "boundary_type")
    metrics = {
        "case_count": len(cases),
        "labeled_count": len(labeled),
        "predicted_count": len(with_predictions),
        "fault_origin_accuracy": accuracy(with_predictions, "fault_origin"),
        "target_accuracy": accuracy(with_predictions, "target"),
        "top3_target_accuracy": topk_accuracy(with_predictions, "target", k=3),
        "serviceability_type_accuracy": accuracy(with_predictions, "serviceability_type"),
        "boundary_accuracy": accuracy(with_predictions, "boundary_type"),
        "top3_boundary_accuracy": topk_accuracy(with_predictions, "boundary_type", k=3),
        "replacement_recommendation_accuracy": replacement_accuracy(with_predictions),
        "mean_reciprocal_rank": mean_reciprocal_rank(with_predictions),
        "unnecessary_replacement_rate": unnecessary_replacement_rate(with_predictions),
        "average_next_test_count": average_next_test_count(with_predictions),
        "active_test_hit_at_1": active_test_hit_rate(with_predictions, 1),
        "active_test_hit_at_3": active_test_hit_rate(with_predictions, 3),
        "mean_recommended_information_gain": mean_recommended_information_gain(with_predictions),
        "mean_realized_information_gain": mean_realized_information_gain(with_predictions),
        "label_distribution": dict(Counter(case.label.fault_origin for case in labeled)),
        "target_label_distribution": dict(Counter(case.label.target for case in labeled if case.label is not None)),
        "prediction_distribution": prediction_distribution(with_predictions, "target"),
        "fault_origin_prediction_distribution": prediction_distribution(with_predictions, "fault_origin"),
        "boundary_label_distribution": dict(Counter(case.label.boundary_type for case in labeled)),
        "boundary_prediction_distribution": prediction_distribution(with_predictions, "boundary_type"),
        "target_macro_precision": macro_average(target_matrix["per_class"], "precision"),
        "target_macro_recall": macro_average(target_matrix["per_class"], "recall"),
        "target_macro_f1": macro_average(target_matrix["per_class"], "f1"),
        "fault_origin_macro_f1": macro_average(fault_origin_matrix["per_class"], "f1"),
        "serviceability_type_macro_f1": macro_average(serviceability_matrix["per_class"], "f1"),
        "boundary_macro_precision": macro_average(boundary_matrix["per_class"], "precision"),
        "boundary_macro_recall": macro_average(boundary_matrix["per_class"], "recall"),
        "boundary_macro_f1": macro_average(boundary_matrix["per_class"], "f1"),
        "boundary_expected_calibration_error": expected_calibration_error(
            with_predictions,
            key="boundary_type",
            confidence_key="boundary_confidence",
        ),
        "boundary_selective_accuracy_at_0_6": selective_accuracy(
            with_predictions,
            key="boundary_type",
            confidence_key="boundary_confidence",
            threshold=0.6,
        ),
        "target_confusion_matrix": target_matrix,
        "fault_origin_confusion_matrix": fault_origin_matrix,
        "serviceability_type_confusion_matrix": serviceability_matrix,
        "boundary_confusion_matrix": boundary_matrix,
    }
    return metrics


def accuracy(cases: list[DatasetCase], key: str) -> float | None:
    if not cases:
        return None
    correct = 0
    total = 0
    for case in cases:
        if case.label is None:
            continue
        prediction = case.metadata.get("prediction", {})
        expected = getattr(case.label, key)
        if prediction.get(key) == expected:
            correct += 1
        total += 1
    return round(correct / total, 4) if total else None


def topk_accuracy(cases: list[DatasetCase], key: str, k: int) -> float | None:
    if not cases:
        return None
    correct = 0
    total = 0
    for case in cases:
        if case.label is None:
            continue
        prediction = case.metadata.get("prediction", {})
        ranked = prediction.get(f"{key}_ranking", [])
        if not ranked and prediction.get(key):
            ranked = [prediction.get(key)]
        if getattr(case.label, key) in ranked[:k]:
            correct += 1
        total += 1
    return round(correct / total, 4) if total else None


def replacement_accuracy(cases: list[DatasetCase]) -> float | None:
    if not cases:
        return None
    correct = 0
    total = 0
    for case in cases:
        if case.label is None:
            continue
        expected = case.label.serviceability_type == "replaceable_fru"
        predicted = case.metadata.get("prediction", {}).get("replacement_recommended")
        if predicted is None:
            continue
        if bool(predicted) == expected:
            correct += 1
        total += 1
    return round(correct / total, 4) if total else None


def mean_reciprocal_rank(cases: list[DatasetCase]) -> float | None:
    ranks = []
    for case in cases:
        if case.label is None:
            continue
        ranked = case.metadata.get("prediction", {}).get("target_ranking", [])
        try:
            rank = ranked.index(case.label.target) + 1
        except ValueError:
            continue
        ranks.append(1 / rank)
    return round(sum(ranks) / len(ranks), 4) if ranks else None


def unnecessary_replacement_rate(cases: list[DatasetCase]) -> float | None:
    total_replacement_predictions = 0
    unnecessary = 0
    for case in cases:
        if case.label is None:
            continue
        prediction = case.metadata.get("prediction", {})
        if prediction.get("replacement_recommended"):
            total_replacement_predictions += 1
            if case.label.serviceability_type != "replaceable_fru":
                unnecessary += 1
    if total_replacement_predictions == 0:
        return None
    return round(unnecessary / total_replacement_predictions, 4)


def average_next_test_count(cases: list[DatasetCase]) -> float | None:
    counts = [
        len(case.metadata.get("prediction", {}).get("next_tests", []))
        for case in cases
        if isinstance(case.metadata.get("prediction"), dict)
    ]
    return round(sum(counts) / len(counts), 4) if counts else None


def active_test_hit_rate(cases: list[DatasetCase], k: int) -> float | None:
    """Evaluate recommendations only where a case provides expected test labels."""

    hits = []
    for case in cases:
        expected = case.metadata.get("expected_next_tests", [])
        if not isinstance(expected, list) or not expected:
            continue
        recommended = case.metadata.get("prediction", {}).get("next_tests", [])
        recommended_ids = [
            item.get("id", item) if isinstance(item, dict) else item
            for item in recommended[:k]
        ]
        hits.append(bool(set(str(item) for item in expected).intersection(map(str, recommended_ids))))
    return round(sum(hits) / len(hits), 4) if hits else None


def mean_recommended_information_gain(cases: list[DatasetCase]) -> float | None:
    values = []
    for case in cases:
        recommendations = case.metadata.get("prediction", {}).get("next_tests", [])
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            value = item.get("boundary_expected_information_gain", item.get("expected_information_gain"))
            if value is not None:
                values.append(float(value))
    return round(sum(values) / len(values), 4) if values else None


def mean_realized_information_gain(cases: list[DatasetCase]) -> float | None:
    values = []
    for case in cases:
        transition = case.metadata.get("active_test_transition")
        if isinstance(transition, dict) and transition.get("realized_information_gain") is not None:
            values.append(float(transition["realized_information_gain"]))
    return round(sum(values) / len(values), 4) if values else None


def prediction_distribution(cases: list[DatasetCase], key: str) -> dict[str, int]:
    return dict(Counter(str(case.metadata.get("prediction", {}).get(key, "unpredicted")) for case in cases))


def build_confusion_matrix(cases: list[DatasetCase], key: str) -> dict[str, Any]:
    labels = []
    matrix_counts: dict[str, Counter[str]] = {}
    for case in cases:
        if case.label is None:
            continue
        prediction = case.metadata.get("prediction", {})
        expected = str(getattr(case.label, key))
        predicted = str(prediction.get(key, "unpredicted") or "unpredicted")
        labels.extend([expected, predicted])
        matrix_counts.setdefault(expected, Counter())[predicted] += 1

    classes = sorted(set(labels))
    rows = []
    total = 0
    correct = 0
    for expected in classes:
        values = []
        row_total = 0
        for predicted in classes:
            count = int(matrix_counts.get(expected, Counter()).get(predicted, 0))
            values.append(count)
            row_total += count
            total += count
            if expected == predicted:
                correct += count
        rows.append({"expected": expected, "values": values, "total": row_total})

    per_class = []
    for klass in classes:
        tp = int(matrix_counts.get(klass, Counter()).get(klass, 0))
        fp = sum(int(matrix_counts.get(other, Counter()).get(klass, 0)) for other in classes if other != klass)
        fn = sum(int(count) for predicted, count in matrix_counts.get(klass, Counter()).items() if predicted != klass)
        support = tp + fn
        predicted_support = tp + fp
        precision = round(tp / predicted_support, 4) if predicted_support else (0.0 if support else None)
        recall = round(tp / support, 4) if support else None
        if precision is None or recall is None:
            f1 = None
        elif precision + recall:
            f1 = round(2 * precision * recall / (precision + recall), 4)
        else:
            f1 = 0.0
        per_class.append(
            {
                "class": klass,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": support,
                "predicted_support": predicted_support,
            }
        )

    return {
        "key": key,
        "classes": classes,
        "rows": rows,
        "per_class": per_class,
        "total": total,
        "accuracy": round(correct / total, 4) if total else None,
    }


def macro_average(items: list[dict[str, Any]], key: str) -> float | None:
    values = [item.get(key) for item in items if item.get(key) is not None]
    return round(sum(float(value) for value in values) / len(values), 4) if values else None


def expected_calibration_error(
    cases: list[DatasetCase],
    *,
    key: str,
    confidence_key: str,
    bins: int = 10,
) -> float | None:
    samples: list[tuple[float, float]] = []
    for case in cases:
        if case.label is None:
            continue
        prediction = case.metadata.get("prediction", {})
        if confidence_key not in prediction:
            continue
        confidence = max(0.0, min(1.0, float(prediction.get(confidence_key, 0.0) or 0.0)))
        correct = 1.0 if prediction.get(key) == getattr(case.label, key) else 0.0
        samples.append((confidence, correct))
    if not samples:
        return None
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            item
            for item in samples
            if lower <= item[0] and (item[0] <= upper if index == bins - 1 else item[0] < upper)
        ]
        if not bucket:
            continue
        mean_confidence = sum(item[0] for item in bucket) / len(bucket)
        mean_accuracy = sum(item[1] for item in bucket) / len(bucket)
        error += len(bucket) / len(samples) * abs(mean_accuracy - mean_confidence)
    return round(error, 4)


def selective_accuracy(
    cases: list[DatasetCase],
    *,
    key: str,
    confidence_key: str,
    threshold: float,
) -> dict[str, float] | None:
    selected = []
    for case in cases:
        if case.label is None:
            continue
        prediction = case.metadata.get("prediction", {})
        confidence = prediction.get(confidence_key)
        if confidence is None or float(confidence) < threshold:
            continue
        selected.append(prediction.get(key) == getattr(case.label, key))
    if not selected:
        return None
    return {
        "threshold": threshold,
        "coverage": round(len(selected) / len(cases), 4),
        "accuracy": round(sum(selected) / len(selected), 4),
        "selected_count": len(selected),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate normalized fault diagnosis cases.")
    parser.add_argument("cases_jsonl")
    parser.add_argument("--json", action="store_true", help="Print metrics as formatted JSON.")
    parser.add_argument("--output-json", default="", help="Optional path for the metrics JSON artifact.")
    args = parser.parse_args()

    metrics = evaluate(load_cases_jsonl(Path(args.cases_jsonl)))
    if args.output_json:
        target = Path(args.output_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for key, value in metrics.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
