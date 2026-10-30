"""Prepare migrated Loghub-2k datasets for diagnosis experiments.

This script intentionally does not use datasets/raw/loghub or the previous
Loghub OS weak-label dataset. It consumes the migrated datasets under
datasets/raw/loghub_2k and builds DatasetCase JSONL files for software-layer
diagnosis experiments.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fru_diagnosis.datasets import DatasetCase, EvidenceBundle, Label, dump_cases_jsonl
from fru_diagnosis.log_parsers import available_log_parsers, parse_logs
from fru_diagnosis.log_noise_reduction import LOG_NOISE_REDUCTION_REFERENCES, build_log_noise_profile

try:
    from prepare_loghub_os_dataset import classify_log_window, select_evidence_messages
except ModuleNotFoundError:
    from scripts.prepare_loghub_os_dataset import classify_log_window, select_evidence_messages


DEFAULT_DATASETS = (
    "BGL",
    "Hadoop",
    "HDFS",
    "OpenStack",
    "Spark",
    "Zookeeper",
    "Apache",
    "OpenSSH",
    "Proxifier",
)

SKIPPED_BY_DESIGN = {
    "Linux": "OS 2k logs are excluded because the user requested not to use the loghub_os-style dataset.",
    "Mac": "OS 2k logs are excluded because the user requested not to use the loghub_os-style dataset.",
    "Thunderbird": "The local 2k structured file contains only non-alert labels, so it is not useful for the main weak-label experiment.",
    "HealthApp": "Mobile health app logs are less aligned with computer-class electronic equipment diagnosis.",
    "HPC": "The local 2k file has no alert label column; BGL is preferred as the labeled HPC-style source.",
}

ALL_DATASET_TOKEN = "all"

ALERT_LABEL_DATASETS = {"BGL"}

DATASET_RATIONALE = {
    "BGL": "Alert/non-alert labels from a computer system log; suitable for boundary evaluation.",
    "Hadoop": "Distributed software service logs from injected failure experiments, but local 2k lacks abnormal_label.txt.",
    "HDFS": "Storage-service logs with trace-like block activity; local 2k lacks anomaly_label.csv.",
    "OpenStack": "Cloud control-plane logs from normal and injected-failure cases, local 2k has no scenario label.",
    "Spark": "Distributed application runtime logs, suitable for software-layer weak-label evidence.",
    "Zookeeper": "Distributed coordination service logs, suitable for configuration/session evidence.",
    "Apache": "Web-server error logs, suitable for service-runtime diagnosis evidence.",
    "OpenSSH": "Authentication/remote-login service logs, suitable for service/security evidence.",
    "Proxifier": "Desktop network/proxy software logs, suitable for external-environment/network evidence.",
    "Linux": "Operating-system logs from the migrated 2k corpus; included only when explicitly processing all migrated datasets.",
    "Mac": "Operating-system logs from the migrated 2k corpus; included only when explicitly processing all migrated datasets.",
    "Thunderbird": "Application logs with a Label column in the local 2k file, but all local labels are non-alert.",
    "HealthApp": "Mobile application logs; weak auxiliary evidence, less aligned with computer-class device diagnosis.",
    "HPC": "High-performance computing logs without a local alert label column; weak auxiliary evidence.",
}


@dataclass(frozen=True)
class DatasetBuildResult:
    dataset: str
    cases: list[DatasetCase]
    stats: dict[str, Any]
    skipped: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare migrated Loghub-2k diagnosis cases.")
    parser.add_argument("--raw-dir", default="datasets/raw/loghub_2k")
    parser.add_argument("--processed-dir", default="datasets/processed/diagnosis_v3_loghub2k")
    parser.add_argument("--version", default="diagnosis_v3_loghub2k")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=list(DEFAULT_DATASETS),
        help="Datasets to build. Use 'all' to process every dataset directory under raw-dir.",
    )
    parser.add_argument("--window-size", type=int, default=50)
    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument(
        "--log-parser",
        choices=available_log_parsers(),
        default="source",
        help=(
            "Log parser used to populate event templates. 'source' preserves "
            "EventTemplate/EventId columns; 'drain' reparses raw Content with "
            "the in-project Drain adapter."
        ),
    )
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--dev-ratio", type=float, default=0.10)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    validate_ratios(args.train_ratio, args.dev_ratio)
    raw_dir = resolve_project_path(args.raw_dir)
    processed_dir = resolve_project_path(args.processed_dir)
    requested_dataset_tokens = list(args.datasets)
    args.datasets = expand_requested_datasets(args.datasets, raw_dir)
    if args.overwrite and processed_dir.exists():
        clean_dir(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    all_cases: list[DatasetCase] = []
    source_stats: dict[str, Any] = {}
    skipped: dict[str, str] = (
        {}
        if is_all_dataset_request(requested_dataset_tokens)
        else {
            dataset: reason
            for dataset, reason in SKIPPED_BY_DESIGN.items()
            if dataset not in set(args.datasets)
        }
    )

    for dataset in args.datasets:
        result = build_dataset(
            dataset=dataset,
            raw_dir=raw_dir,
            window_size=args.window_size,
            limit_rows=args.limit_rows,
            log_parser=args.log_parser,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        if result.skipped:
            skipped[dataset] = result.skipped
            continue
        all_cases.extend(result.cases)
        source_stats[dataset] = result.stats

    if not all_cases:
        raise RuntimeError("No Loghub-2k diagnosis cases were generated.")

    write_outputs(
        processed_dir=processed_dir,
        version=args.version,
        cases=all_cases,
        source_stats=source_stats,
        skipped=skipped,
        args=args,
        requested_dataset_tokens=requested_dataset_tokens,
    )
    print(f"Wrote {len(all_cases)} cases to {processed_dir}")
    print(f"Included datasets: {', '.join(sorted(source_stats))}")
    return 0


def is_all_dataset_request(datasets: list[str]) -> bool:
    return len(datasets) == 1 and datasets[0].casefold() == ALL_DATASET_TOKEN


def expand_requested_datasets(datasets: list[str], raw_dir: Path) -> list[str]:
    if not is_all_dataset_request(datasets):
        return datasets
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw dataset directory does not exist: {raw_dir}")
    return sorted(child.name for child in raw_dir.iterdir() if child.is_dir())


def build_dataset(
    *,
    dataset: str,
    raw_dir: Path,
    window_size: int,
    limit_rows: int | None,
    log_parser: str,
    train_ratio: float,
    dev_ratio: float,
) -> DatasetBuildResult:
    dataset_dir = raw_dir / dataset
    if not dataset_dir.exists():
        return DatasetBuildResult(dataset, [], {}, f"missing directory {dataset_dir}")
    structured = dataset_dir / f"{dataset}_2k.log_structured_corrected.csv"
    if not structured.exists():
        structured = dataset_dir / f"{dataset}_2k.log_structured.csv"
    if not structured.exists():
        return DatasetBuildResult(dataset, [], {}, f"missing structured CSV for {dataset}")

    rows = read_rows(structured, limit_rows=limit_rows)
    cases = [
        window_to_case(dataset, index, window, log_parser=log_parser)
        for index, window in enumerate(chunked(rows, window_size))
        if window
    ]
    cases = assign_splits(cases, train_ratio=train_ratio, dev_ratio=dev_ratio)
    stats = {
        "rationale": DATASET_RATIONALE.get(dataset, ""),
        "log_parser": log_parser,
        "label_mode": "alert_label" if dataset in ALERT_LABEL_DATASETS else "weak_evidence_scoring",
        "source_structured_csv": str(structured.relative_to(PROJECT_ROOT)),
        "raw_rows_processed": len(rows),
        "case_count": len(cases),
        "split_distribution": count_by_metadata(cases, "split"),
        "fault_origin_distribution": count_labels(cases, "fault_origin"),
        "target_distribution": count_labels(cases, "target"),
        "serviceability_type_distribution": count_labels(cases, "serviceability_type"),
        "boundary_type_distribution": count_labels(cases, "boundary_type"),
        "label_confidence_distribution": count_labels(cases, "confidence"),
        "manual_review_required_count": count_metadata_true(cases, "manual_review_required"),
        "evidence_label_conflict_count": count_metadata_true(cases, "evidence_label_conflict"),
        "event_template_count": count_distinct_templates(cases),
    }
    if "Label" in (rows[0].keys() if rows else []):
        stats["raw_label_distribution"] = dict(Counter(row.get("Label", "") for row in rows))
    return DatasetBuildResult(dataset, cases, stats)


def window_to_case(
    dataset: str,
    window_index: int,
    rows: list[dict[str, str]],
    *,
    log_parser: str = "source",
) -> DatasetCase:
    line_ids = [to_int(row.get("LineId", "")) for row in rows]
    line_ids = [line_id for line_id in line_ids if line_id is not None]
    messages = [row.get("Content", "") for row in rows]
    parsed_logs = parse_logs(
        [
            {
                "LineId": row.get("LineId", ""),
                "Content": row.get("Content", ""),
                "EventId": row.get("EventId", ""),
                "EventTemplate": row.get("EventTemplate", ""),
            }
            for row in rows
        ],
        parser_name=log_parser,
    )
    parsed_evidence = parsed_logs.to_log_evidence(include_parsed_events=True)
    templates = parsed_logs.event_template_sequence
    event_ids = parsed_logs.event_id_sequence
    components = [first_present(row, ["Component", "Program", "Process", "Type", "Location"]) for row in rows]
    levels = [first_present(row, ["Level", "State", "Flag"]) for row in rows]
    labels = [row.get("Label", "-") for row in rows if "Label" in row]
    entries = [
        {
            "message": row.get("Content", ""),
            "template": parsed_line.event_template,
            "event_id": parsed_line.event_id,
            "level": first_present(row, ["Level", "State", "Flag"]),
            "component": first_present(row, ["Component", "Program", "Process", "Type", "Location"]),
        }
        for row, parsed_line in zip(rows, parsed_logs.lines)
    ]
    noise_profile = build_log_noise_profile(entries)
    actionable_event_count = int(noise_profile.get("actionable_event_count", 0) or 0)
    evidence_messages = list(noise_profile.get("retained_messages", [])) or select_evidence_messages(
        messages,
        ["fatal", "error", "failed", "failure", "exception", "timeout", "invalid", "denied"],
    )
    joined_text = "\n".join(messages + templates).casefold()

    if dataset in ALERT_LABEL_DATASETS:
        label = classify_alert_window(dataset, labels, evidence_messages, templates, joined_text)
    else:
        decision = classify_log_window(
            dataset_key=dataset.casefold(),
            actionable_event_count=actionable_event_count,
            evidence_messages=evidence_messages,
            templates=templates,
            joined_text=joined_text,
        )
        label = Label(
            fault_origin=decision.fault_origin,
            target=decision.target,
            serviceability_type=decision.serviceability_type,
            repair_action=decision.repair_action,
            fixed=None,
            confidence="weak",
            source=f"loghub2k_{dataset}.weak_evidence_scoring",
        )
        decision_metadata = decision.to_dict()

    if dataset in ALERT_LABEL_DATASETS:
        decision_metadata = {
            "policy_version": "loghub2k_alert_label_v1",
            "raw_label_counts": dict(Counter(labels)),
            "alert_labels": sorted({label for label in labels if label and label != "-"}),
        }

    abnormal = label.fault_origin != "no_fault_observed"
    evidence_suggests_anomaly = actionable_event_count > 0 or bool(evidence_messages)
    evidence_label_conflict = (
        dataset in ALERT_LABEL_DATASETS
        and label.fault_origin == "no_fault_observed"
        and evidence_suggests_anomaly
    )
    evidence = EvidenceBundle(
        logs={
            "dataset": f"loghub2k_{dataset}",
            "row_count": len(rows),
            "line_range": {
                "start": min(line_ids) if line_ids else "",
                "end": max(line_ids) if line_ids else "",
            },
            "time_range": {
                "start": format_time(rows[0]) if rows else "",
                "end": format_time(rows[-1]) if rows else "",
            },
            "level_counts": dict(Counter(level for level in levels if level)),
            "component_counts": dict(Counter(component for component in components if component).most_common(20)),
            "event_id_counts": dict(Counter(event_ids).most_common(20)),
            "event_template_counts": dict(Counter(templates).most_common(20)),
            "event_id_sequence": parsed_evidence["event_id_sequence"],
            "event_template_sequence": parsed_evidence["event_template_sequence"],
            "parsed_events": parsed_evidence["parsed_events"],
            "log_parser": parsed_evidence["log_parser"],
            "raw_label_counts": dict(Counter(labels)) if labels else {},
            "noise_reduction": noise_profile,
            "raw_messages": messages,
            "evidence_messages": evidence_messages,
            "actionable_warning_error_count": actionable_event_count,
            "weak_label_decision": decision_metadata,
        }
    )
    return DatasetCase(
        case_id=f"loghub2k_{dataset.casefold()}_window_{window_index:06d}",
        source_dataset=f"loghub2k_{dataset.casefold()}",
        device_type="computer_system",
        timestamp=format_time(rows[0]) if rows else "",
        fault_time=format_time(rows[0]) if abnormal and rows else "",
        symptom=("log_anomaly",) if abnormal else ("log_observation",),
        evidence=evidence,
        label=label,
        metadata={
            "dataset_key": dataset,
            "source_family": "loghub_2k",
            "log_parser": log_parser,
            "window_index": window_index,
            "window_size": len(rows),
            "line_start": min(line_ids) if line_ids else "",
            "line_end": max(line_ids) if line_ids else "",
            "label_quality": label.confidence,
            "label_mode": "alert_label" if dataset in ALERT_LABEL_DATASETS else "weak_evidence_scoring",
            "official_boundary_label_available": dataset in ALERT_LABEL_DATASETS,
            "evidence_suggests_anomaly": evidence_suggests_anomaly,
            "evidence_label_conflict": evidence_label_conflict,
            "manual_review_required": label.confidence == "weak" or evidence_label_conflict,
        },
    )


def classify_alert_window(
    dataset: str,
    labels: list[str],
    evidence_messages: list[str],
    templates: list[str],
    joined_text: str,
) -> Label:
    alert_labels = [label for label in labels if label and label != "-"]
    if not alert_labels:
        return Label(
            fault_origin="no_fault_observed",
            target="none",
            serviceability_type="none",
            repair_action="no_repair",
            fixed=None,
            confidence="silver",
            source=f"loghub2k_{dataset}.alert_label",
        )
    target = classify_alert_target(alert_labels, "\n".join(evidence_messages + templates).casefold() or joined_text)
    return Label(
        fault_origin="non_fru_fault",
        target=target,
        serviceability_type="non_fru_fault",
        repair_action=repair_action_for_target(target),
        fixed=None,
        confidence="silver",
        source=f"loghub2k_{dataset}.alert_label",
    )


def classify_alert_target(alert_labels: list[str], text: str) -> str:
    label_text = " ".join(alert_labels).casefold()
    combined = f"{label_text} {text}".casefold()
    if any(token in combined for token in ["stor", "disk", "filesystem", "io error", "i/o"]):
        return "data_or_filesystem_fault"
    if any(token in combined for token in ["network", "socket", "connection", "route", "timeout"]):
        return "external_environment_fault"
    if any(token in combined for token in ["mount", "config", "permission", "invalid"]):
        return "firmware_or_config_fault"
    if any(token in combined for token in ["app", "ciod", "child", "read", "res", "out"]):
        return "os_fault"
    if any(token in combined for token in ["kernel", "kern", "tlb", "interrupt", "fatal"]):
        return "driver_or_os_fault"
    return "os_fault"


def repair_action_for_target(target: str) -> str:
    return {
        "driver_or_os_fault": "investigate_driver_or_os_logs",
        "os_fault": "repair_or_restart_service_component",
        "firmware_or_config_fault": "check_configuration_or_platform_setting",
        "external_environment_fault": "validate_network_or_external_dependency",
        "data_or_filesystem_fault": "check_data_filesystem_or_storage_service",
        "none": "no_repair",
    }.get(target, "investigate_logs")


def assign_splits(
    cases: list[DatasetCase],
    *,
    train_ratio: float,
    dev_ratio: float,
) -> list[DatasetCase]:
    train_end, dev_end = split_boundaries(len(cases), train_ratio, dev_ratio)
    assigned = []
    for index, case in enumerate(cases):
        if index < train_end:
            split = "train"
        elif index < dev_end:
            split = "dev"
        else:
            split = "test"
        metadata = dict(case.metadata)
        metadata["split"] = split
        assigned.append(
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
    return assigned


def write_outputs(
    *,
    processed_dir: Path,
    version: str,
    cases: list[DatasetCase],
    source_stats: dict[str, Any],
    skipped: dict[str, str],
    args: argparse.Namespace,
    requested_dataset_tokens: list[str],
) -> None:
    dump_cases_jsonl(cases, processed_dir / "all.jsonl")
    for split in ("train", "dev", "test"):
        dump_cases_jsonl(
            [case for case in cases if case.metadata.get("split") == split],
            processed_dir / f"{split}.jsonl",
        )
    for confidence in sorted({case.label.confidence for case in cases if case.label is not None}):
        confidence_cases = [case for case in cases if case.label and case.label.confidence == confidence]
        dump_cases_jsonl(confidence_cases, processed_dir / f"{confidence}.jsonl")
        for split in ("train", "dev", "test"):
            dump_cases_jsonl(
                [case for case in confidence_cases if case.metadata.get("split") == split],
                processed_dir / f"{confidence}_{split}.jsonl",
            )
    per_source = processed_dir / "per_source"
    per_source.mkdir(parents=True, exist_ok=True)
    for source_dataset in sorted({case.source_dataset for case in cases}):
        dump_cases_jsonl(
            [case for case in cases if case.source_dataset == source_dataset],
            per_source / f"{source_dataset}.jsonl",
        )

    policy = sampling_policy(args.window_size, args.limit_rows)
    stats = build_stats(version, cases, source_stats, skipped, sampling_policy=policy)
    write_json(stats, processed_dir / "stats.json")
    write_json(
        {
            "version": version,
            "generated_by": "scripts/prepare_loghub2k_diagnosis_dataset.py",
            "raw_dir": str(resolve_project_path(args.raw_dir).relative_to(PROJECT_ROOT)),
            "processed_dir": str(processed_dir.relative_to(PROJECT_ROOT)),
            "requested_datasets": requested_dataset_tokens,
            "resolved_datasets": list(args.datasets),
            "included_datasets": sorted(source_stats),
            "skipped_datasets": skipped,
            "parameters": {
                "window_size": args.window_size,
                "limit_rows": args.limit_rows,
                "sampling_policy": policy,
                "log_parser": args.log_parser,
                "train_ratio": args.train_ratio,
                "dev_ratio": args.dev_ratio,
                "test_ratio": round(1 - args.train_ratio - args.dev_ratio, 4),
            },
            "case_count": len(cases),
            "split_distribution": count_by_metadata(cases, "split"),
        },
        processed_dir / "manifest.json",
    )
    (processed_dir / "label_policy.md").write_text(
        label_policy_text(included_datasets=sorted(source_stats), skipped=skipped),
        encoding="utf-8",
    )
    (processed_dir / "README.md").write_text(readme_text(version, stats), encoding="utf-8")
    manifest_path = processed_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = {
        str(path.relative_to(processed_dir)).replace("\\", "/"): sha256_file(path)
        for path in sorted(processed_dir.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    write_json(manifest, manifest_path)


def build_stats(
    version: str,
    cases: list[DatasetCase],
    source_stats: dict[str, Any],
    skipped: dict[str, str],
    sampling_policy: str,
) -> dict[str, Any]:
    return {
        "version": version,
        "sampling_policy": sampling_policy,
        "case_count": len(cases),
        "split_distribution": count_by_metadata(cases, "split"),
        "source_dataset_distribution": dict(Counter(case.source_dataset for case in cases)),
        "fault_origin_distribution": count_labels(cases, "fault_origin"),
        "target_distribution": count_labels(cases, "target"),
        "serviceability_type_distribution": count_labels(cases, "serviceability_type"),
        "label_confidence_distribution": count_labels(cases, "confidence"),
        "manual_review_required_count": count_metadata_true(cases, "manual_review_required"),
        "evidence_label_conflict_count": count_metadata_true(cases, "evidence_label_conflict"),
        "source_stats": source_stats,
        "skipped_datasets": skipped,
        "note": (
            "This dataset is built from migrated Loghub-2k sources, not the "
            "previous Loghub OS processed dataset. BGL alert boundaries are "
            "silver labels; other selected service logs use evidence-scored weak labels."
        ),
    }


def sampling_policy(window_size: int, limit_rows: int | None) -> str:
    if limit_rows is not None:
        return f"limited_to_first_{limit_rows}_rows_then_exhaustive_windows"
    if window_size == 1:
        return "no_sampling_one_log_row_per_case"
    return f"no_row_sampling_exhaustive_non_overlapping_windows_of_{window_size}_rows"


def label_policy_text(*, included_datasets: list[str], skipped: dict[str, str]) -> str:
    lines = [
        "# Label Policy",
        "",
        "This dataset is built from migrated Loghub-2k datasets.",
        "",
        f"- Included datasets: {', '.join(included_datasets)}.",
        "- BGL uses the original alert/non-alert label column for anomaly boundary labels.",
        "- BGL target labels are mapped weakly from alert category and evidence text.",
        "- Non-BGL datasets use evidence-scored weak labels unless official labels are explicitly available in the local 2k files.",
        "- `silver_*.jsonl` files should be preferred for boundary evaluation; `weak_*.jsonl` files are auxiliary data for pretraining, ablation, and case analysis.",
        "- `evidence_label_conflict=true` means the source boundary label is normal but retained diagnostic evidence exists, so the case should be manually reviewed before being used as hard ground truth.",
    ]
    if skipped:
        lines.append("- Skipped datasets: " + "; ".join(f"{name}: {reason}" for name, reason in sorted(skipped.items())) + ".")
    lines.extend(
        [
            "",
            "Use this dataset for software-layer log/trace diagnosis experiments, not as hardware repair ground truth.",
            "",
        ]
    )
    return "\n".join(lines)


def readme_text(version: str, stats: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {version}",
            "",
            "Migrated Loghub-2k diagnosis dataset for software-layer fault diagnosis.",
            "",
            f"- Cases: {stats['case_count']}",
            f"- Sampling policy: {stats['sampling_policy']}",
            f"- Splits: {stats['split_distribution']}",
            f"- Sources: {stats['source_dataset_distribution']}",
            f"- Label confidence: {stats['label_confidence_distribution']}",
            f"- Manual review required: {stats['manual_review_required_count']}",
            f"- Evidence/label conflicts: {stats['evidence_label_conflict_count']}",
            "",
            "Recommended use:",
            "",
            "- `silver_train/dev/test.jsonl`: BGL alert-boundary evaluation.",
            "- `weak_train/dev/test.jsonl`: auxiliary weak-label service-log experiments.",
            "- `test.jsonl`: mixed-quality smoke test only; do not report it as clean ground truth.",
            "",
            "Baseline outputs should be written under reports/experiments.",
            "",
        ]
    )


def read_rows(path: Path, limit_rows: int | None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for index, row in enumerate(reader):
            if limit_rows is not None and index >= limit_rows:
                break
            rows.append({key: str(value or "") for key, value in row.items()})
        return rows


def chunked(rows: list[dict[str, str]], size: int) -> Iterable[list[dict[str, str]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def first_present(row: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return value
    return ""


def format_time(row: dict[str, str]) -> str:
    pieces = [
        row.get("Date", ""),
        row.get("Month", ""),
        row.get("Day", ""),
        row.get("Time", ""),
        row.get("Timestamp", ""),
    ]
    return " ".join(piece for piece in pieces if piece).strip()


def to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def count_by_metadata(cases: Iterable[DatasetCase], key: str) -> dict[str, int]:
    return dict(Counter(str(case.metadata.get(key, "unknown")) for case in cases))


def count_distinct_templates(cases: Iterable[DatasetCase]) -> int:
    templates = set()
    for case in cases:
        counts = case.evidence.logs.get("event_template_counts", {})
        if isinstance(counts, dict):
            templates.update(str(template) for template in counts if template)
    return len(templates)


def count_labels(cases: Iterable[DatasetCase], key: str) -> dict[str, int]:
    values = []
    for case in cases:
        values.append(str(getattr(case.label, key)) if case.label is not None else "unlabeled")
    return dict(Counter(values))


def count_metadata_true(cases: Iterable[DatasetCase], key: str) -> int:
    return sum(1 for case in cases if bool(case.metadata.get(key)))


def split_boundaries(total: int, train_ratio: float, dev_ratio: float) -> tuple[int, int]:
    train_count = int(round(total * train_ratio))
    dev_count = int(round(total * dev_ratio))
    if total > 0 and train_count >= total:
        train_count = total - 1
    if total - train_count - dev_count <= 0:
        dev_count = max(0, total - train_count - 1)
    return train_count, train_count + dev_count


def validate_ratios(train_ratio: float, dev_ratio: float) -> None:
    if train_ratio <= 0 or dev_ratio < 0:
        raise ValueError("Train/dev ratios must be non-negative and train must be positive.")
    if train_ratio + dev_ratio >= 1:
        raise ValueError("Train plus dev ratio must leave a positive test split.")


def clean_dir(path: Path) -> None:
    resolved = path.resolve()
    root = PROJECT_ROOT.resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError(f"Refusing to delete outside project root: {resolved}")
    for child in resolved.iterdir():
        if child.is_dir():
            import shutil

            shutil.rmtree(child)
        else:
            child.unlink()


def resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
