"""Write an auditable quality report for a processed diagnosis dataset."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Chinese dataset quality report.")
    parser.add_argument("processed_dir", help="Versioned directory under datasets/processed.")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--registry", default="datasets/source_registry.json")
    args = parser.parse_args()

    processed_dir = resolve_path(args.processed_dir)
    output_dir = resolve_path(args.output_dir) if args.output_dir else processed_dir / "quality_report"
    registry_path = resolve_path(args.registry)
    cases = load_jsonl(processed_dir / "all.jsonl")
    registry = load_json(registry_path) if registry_path.exists() else {}
    report = build_report(cases, registry)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "质量报告.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote quality report to {output_dir}")
    return 0


def resolve_path(value: str | None) -> Path:
    if not value:
        return PROJECT_ROOT
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def count_values(cases: list[dict[str, Any]], value_for_case: Any) -> dict[str, int]:
    return dict(sorted(Counter(str(value_for_case(case)) for case in cases).items()))


def build_report(cases: list[dict[str, Any]], registry: dict[str, Any]) -> dict[str, Any]:
    split_counts = count_values(cases, lambda case: case.get("metadata", {}).get("split", "unknown"))
    sources = count_values(cases, lambda case: case.get("metadata", {}).get("source_family", "unknown"))
    domains = count_values(cases, lambda case: case.get("metadata", {}).get("domain", "unknown"))
    targets = count_values(cases, lambda case: (case.get("label") or {}).get("target", "unlabeled"))
    confidence = count_values(cases, lambda case: (case.get("label") or {}).get("confidence", "unknown"))
    modalities = modality_summary(cases)
    split_by_benchmark = crosstab(cases, "benchmark")
    split_by_fault_type = crosstab(cases, "fault_type")
    group_integrity = split_group_integrity(cases)
    registered_sources = registry.get("sources", registry)
    referenced_sources = {
        key: registered_sources[key]
        for key in sources
        if key in registered_sources
    }
    return {
        "case_count": len(cases),
        "split_distribution": split_counts,
        "source_family_distribution": sources,
        "domain_distribution": domains,
        "target_distribution": targets,
        "label_confidence_distribution": confidence,
        "modality_coverage": modalities,
        "benchmark_by_split": split_by_benchmark,
        "fault_type_by_split": split_by_fault_type,
        "split_group_integrity": group_integrity,
        "source_registry": referenced_sources,
        "interpretation_limits": [
            "RCAEval labels describe injected service-level software faults, not endpoint hardware FRU failures.",
            "All cases in the current RCAEval-only version have silver labels; do not report them as repair-confirmed gold labels.",
            "Fault-type cross-tabs are descriptive unless every evaluated class is represented in both training and test splits.",
        ],
    }


def modality_summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    modalities = ("logs", "metrics", "traces", "inventory", "active_tests", "crash_dump", "repair_result")
    return {
        modality: sum(bool((case.get("evidence") or {}).get(modality)) for case in cases)
        for modality in modalities
    }


def crosstab(cases: list[dict[str, Any]], metadata_key: str) -> dict[str, dict[str, int]]:
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        metadata = case.get("metadata") or {}
        row = str(metadata.get(metadata_key, "unknown"))
        split = str(metadata.get("split", "unknown"))
        table[row][split] += 1
    return {row: dict(sorted(columns.items())) for row, columns in sorted(table.items())}


def split_group_integrity(cases: list[dict[str, Any]]) -> dict[str, int]:
    groups: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        metadata = case.get("metadata") or {}
        group = str(metadata.get("split_group") or case.get("fault_case_id") or case.get("case_id"))
        groups[group].add(str(metadata.get("split", "unknown")))
    return {
        "group_count": len(groups),
        "cross_split_group_count": sum(len(splits) > 1 for splits in groups.values()),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 数据集质量报告",
        "",
        "## 概览",
        "",
        f"- 案例数：{report['case_count']}",
        f"- 划分：{format_counts(report['split_distribution'])}",
        f"- 来源：{format_counts(report['source_family_distribution'])}",
        f"- 领域：{format_counts(report['domain_distribution'])}",
        f"- 标签置信度：{format_counts(report['label_confidence_distribution'])}",
        "",
        "## 证据模态覆盖",
        "",
        *[f"- {name}：{count}" for name, count in report["modality_coverage"].items()],
        "",
        "## 泄漏检查",
        "",
        f"- 场景组数：{report['split_group_integrity']['group_count']}",
        f"- 跨集合场景组数：{report['split_group_integrity']['cross_split_group_count']}",
        "",
        "## 分布核验",
        "",
        "### 基准-划分",
        "",
        *[f"- {name}：{format_counts(counts)}" for name, counts in report["benchmark_by_split"].items()],
        "",
        "### 注入故障类型-划分",
        "",
        *[f"- {name}：{format_counts(counts)}" for name, counts in report["fault_type_by_split"].items()],
        "",
        "## 使用边界",
        "",
        *[f"- {item}" for item in report["interpretation_limits"]],
        "",
        "## 来源登记",
        "",
    ]
    for source, metadata in report["source_registry"].items():
        lines.extend(
            [
                f"### {metadata.get('name', source)}",
                "",
                f"- 记录：{metadata.get('record_url', '')}",
                f"- 论文 DOI：{metadata.get('publication_doi', '')}",
                f"- 许可证：{metadata.get('license', '')}",
                f"- 使用子集：{metadata.get('used_subset', '')}",
                f"- 可支持的结论：{metadata.get('permitted_claim', '')}",
                f"- 限制：{metadata.get('restriction', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def format_counts(counts: dict[str, int]) -> str:
    return "；".join(f"{key}={value}" for key, value in sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
