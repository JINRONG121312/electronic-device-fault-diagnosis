"""Run literature-derived RCA baselines on the canonical RCAEval split."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.run_rcaeval_formal_experiment import (
    attach_prediction,
    build_dependency_graph,
    compact_metrics,
    evaluate_predictions,
    label_parts,
    predict_case,
)
from fru_diagnosis.datasets import dump_cases_jsonl, load_cases_jsonl


METHODS = (
    "baro_reproduction",
    "multi_source_baro_reproduction",
    "cloudranger_reproduction",
    "tracerca_reproduction",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RCAEval literature baseline reproductions.")
    parser.add_argument("--dataset-dir", default="datasets/processed/diagnosis_v7_rcaeval_re2")
    parser.add_argument(
        "--output-dir",
        default="reports/experiments/diagnosis_v7_rcaeval_re2_literature_baselines",
    )
    args = parser.parse_args()

    dataset_dir = resolve_path(args.dataset_dir)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    train_cases = load_cases_jsonl(dataset_dir / "train.jsonl")
    test_cases = load_cases_jsonl(dataset_dir / "test.jsonl")
    train_roots = {label_parts(case).root for case in train_cases}
    models: dict[str, Any] = {
        "dependency_graph": build_dependency_graph(train_cases),
        "service_vocabulary": sorted(
            {label_parts(case).service for case in train_cases if label_parts(case).service}
        ),
    }

    summary: dict[str, Any] = {
        "dataset_dir": str(dataset_dir.relative_to(PROJECT_ROOT)),
        "train_count": len(train_cases),
        "test_count": len(test_cases),
        "methods": {},
        "reproduction_scope": "service:fault_type on the canonical leakage-free split",
        "source_implementation": "https://github.com/phamquiluan/RCAEval",
        "source_checked": "2026-07-12",
        "adaptation_notes": {
            "baro_reproduction": "Published robust pre/post metric scaling; metric nodes are mapped to the training service vocabulary.",
            "multi_source_baro_reproduction": "Equal modality fusion; normalized cases retain aggregate log and trace statistics rather than the original time-series tables.",
            "cloudranger_reproduction": "Metric anomaly scores are propagated on a train-only service dependency graph reconstructed from aggregate failed spans.",
            "tracerca_reproduction": "Support-confidence ranking is applied to aggregate failed spans; trace IDs and full normal traces are unavailable after normalization.",
        },
    }
    for method in METHODS:
        predicted = [attach_prediction(case, predict_case(case, method, models)) for case in test_cases]
        dump_cases_jsonl(predicted, output_dir / f"test_{method}.jsonl")
        metrics = evaluate_predictions(predicted, reference_roots=train_roots)
        summary["methods"][method] = compact_metrics(metrics)
        write_json(metrics, output_dir / f"test_{method}_metrics.json")

    write_json(summary, output_dir / "metrics_summary.json")
    (output_dir / "literature_baseline_report.md").write_text(build_report(summary), encoding="utf-8")
    print(f"Wrote literature baseline reproductions to {output_dir}")
    return 0


def build_report(summary: dict[str, Any]) -> str:
    lines = [
        "# RCAEval literature baseline reproductions",
        "",
        f"Dataset: `{summary['dataset_dir']}`; train/test: {summary['train_count']}/{summary['test_count']}.",
        "",
        "| Method | Root Top-1 | Root Top-3 | Root Top-5 | Root MRR | Root Macro-F1 | Service Top-1 | Fault Macro-F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        item = summary["methods"][method]
        lines.append(
            f"| `{method}` | {decimal(item.get('root_accuracy'))} | "
            f"{decimal(item.get('root_top3_accuracy'))} | {decimal(item.get('root_top5_accuracy'))} | "
            f"{decimal(item.get('root_mrr'))} | {decimal(item.get('root_macro_f1'))} | "
            f"{decimal(item.get('service_accuracy'))} | {decimal(item.get('fault_type_macro_f1'))} |"
        )
    lines.extend(["", "## Adaptation notes", ""])
    for method, note in summary["adaptation_notes"].items():
        lines.append(f"- `{method}`: {note}")
    lines.extend(
        [
            "",
            "These are adapted reproductions, not byte-identical executions of the upstream package. "
            "The distinction is required because the canonical project cases store aggregate log/trace evidence and use a service-level label space.",
        ]
    )
    return "\n".join(lines)


def decimal(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def write_json(value: Any, path: Path) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
