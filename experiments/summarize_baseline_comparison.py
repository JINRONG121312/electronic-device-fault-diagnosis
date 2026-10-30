"""Summarize baseline-comparison metrics for a diagnosis experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.evaluate_cases import evaluate
from fru_diagnosis.datasets import load_cases_jsonl

GROUPS = {
    "mixed_test": "混合测试集",
    "silver_test": "银标签测试集",
    "weak_test": "弱标签测试集",
}

METHODS = {
    "rule_weighted": "规则关键词下限",
    "graph_fusion": "异构证据图融合",
    "log_template_tfidf": "Drain 模板 TF-IDF",
}

METRICS = [
    ("fault_origin_accuracy", "边界准确率"),
    ("target_accuracy", "根因准确率"),
    ("top3_target_accuracy", "Top-3 根因覆盖率"),
    ("target_macro_f1", "根因 Macro-F1"),
    ("serviceability_type_accuracy", "服务性准确率"),
    ("replacement_recommendation_accuracy", "换件建议准确率"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize baseline comparison metrics.")
    parser.add_argument("--experiment-dir", default="reports/experiments/diagnosis_v3_loghub2k")
    parser.add_argument("--dataset-dir", default="datasets/processed/diagnosis_v3_loghub2k")
    args = parser.parse_args()

    experiment_dir = Path(args.experiment_dir)
    dataset_dir = Path(args.dataset_dir)
    summary = build_summary(experiment_dir)
    write_json(summary, experiment_dir / "metrics_summary.json")
    report = build_markdown_report(summary, dataset_dir)
    (experiment_dir / "baseline_comparison.md").write_text(report, encoding="utf-8")
    print(f"Wrote metrics summary to {experiment_dir / 'metrics_summary.json'}")
    print(f"Wrote comparison report to {experiment_dir / 'baseline_comparison.md'}")
    return 0


def build_summary(experiment_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for group in GROUPS:
        for method in METHODS:
            path = experiment_dir / f"{group}_{method}.jsonl"
            if group == "mixed_test":
                path = experiment_dir / f"test_{method}.jsonl"
            if not path.exists():
                continue
            metrics = evaluate(load_cases_jsonl(path))
            summary[f"{group}_{method}"] = compact_metrics(metrics)
    return summary


def compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "case_count",
        "fault_origin_accuracy",
        "target_accuracy",
        "top3_target_accuracy",
        "target_macro_f1",
        "target_macro_precision",
        "target_macro_recall",
        "serviceability_type_accuracy",
        "replacement_recommendation_accuracy",
        "unnecessary_replacement_rate",
        "mean_reciprocal_rank",
        "prediction_distribution",
        "fault_origin_prediction_distribution",
        "label_distribution",
        "target_label_distribution",
    ]
    return {key: metrics.get(key) for key in keys}


def build_markdown_report(summary: dict[str, Any], dataset_dir: Path) -> str:
    lines = [
        "# 基线对比实验结果",
        "",
        "## 数据集",
        "",
        f"- 数据集：`{dataset_dir}`",
        "- 日志解析：Drain",
        "- 窗口：50 行日志 / case",
        "- 抽样：不抽样，全量非重叠窗口",
        "",
        "## 方法设置",
        "",
        "| 方法 | 角色 | 证据输入 | 说明 |",
        "|---|---|---|---|",
        "| `rule_weighted` | 弱下限 | 原始证据文本 | 关键词规则匹配，只用于说明简单规则不足 |",
        "| `log_template_tfidf` | 强日志诊断基线 | Drain 模板、模板计数、事件序列、日志文本、level/component | 监督式 TF-IDF 最近质心分类，不使用数据集来源特征 |",
        "| `graph_fusion` | 当前项目方法 | 标准化证据图 | 可解释图传播，目前在该数据集上主要是日志证据 |",
        "",
    ]
    for group, label in GROUPS.items():
        lines.extend(build_group_table(summary, group, label))
        lines.append("")

    lines.extend(
        [
            "## 实验结论",
            "",
            "1. `rule_weighted` 只能作为弱下限，不能作为主要对比方法。它在混合测试集根因准确率为 0，说明关键词规则存在明显类别塌缩。",
            "2. `log_template_tfidf` 是当前更合理的日志故障诊断基线。它利用 Drain 模板和事件序列，能代表“日志解析 + 统计学习”的传统强基线。",
            "3. 在当前 Loghub-2k 处理数据上，`log_template_tfidf` 的根因准确率高于 `graph_fusion`，说明该数据集主要验证的是日志分类能力，而不是完整异构证据融合能力。",
            "4. `graph_fusion` 的价值不能只靠纯日志数据证明。后续需要引入或构造包含指标、设备清单、崩溃转储、主动测试、维修结果的样本，比较 `log_template_tfidf` 与 `graph_fusion full-evidence` 在软硬件边界判断、误换件抑制、补采建议上的差异。",
            "",
            "## 答辩中建议表述",
            "",
            "当前实验已经证明：简单关键词规则不足以支撑电子设备故障诊断；Drain 模板 TF-IDF 是更强的日志诊断基线。由于现阶段数据主要来自日志/trace，强日志基线在根因分类上表现更高是合理的。这反而明确了本项目下一阶段的优化方向：从纯日志诊断扩展到异构证据融合诊断，重点评估软硬件边界判断和证据不足时的主动补采能力。",
            "",
        ]
    )
    return "\n".join(lines)


def build_group_table(summary: dict[str, Any], group: str, label: str) -> list[str]:
    lines = [
        f"## {label}",
        "",
        "| 方法 | 样本数 | 边界准确率 | 根因准确率 | Top-3 根因覆盖率 | 根因 Macro-F1 | 服务性准确率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for method, method_label in METHODS.items():
        item = summary.get(f"{group}_{method}")
        if not item:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{method}` ({method_label})",
                    str(item.get("case_count")),
                    decimal(item.get("fault_origin_accuracy")),
                    decimal(item.get("target_accuracy")),
                    decimal(item.get("top3_target_accuracy")),
                    decimal(item.get("target_macro_f1")),
                    decimal(item.get("serviceability_type_accuracy")),
                ]
            )
            + " |"
        )
    return lines


def decimal(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.4f}"


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
