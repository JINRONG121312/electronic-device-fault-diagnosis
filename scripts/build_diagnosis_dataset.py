"""Build a versioned diagnosis dataset for formal experiments.

The builder keeps raw data, processed experiment inputs, and baseline outputs
separate. It can aggregate multiple source families when they are available,
and records missing optional sources in the manifest instead of silently
pretending they were used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fru_diagnosis.datasets import DatasetCase, dump_cases_jsonl, enrich_case, load_cases_jsonl
from fru_diagnosis.datasets.adapters.backblaze import iter_backblaze_cases
from fru_diagnosis.datasets.adapters.gaia import iter_gaia_cases
from fru_diagnosis.datasets.adapters.openrepair import iter_openrepair_cases
from fru_diagnosis.datasets.adapters.rcaeval import iter_rcaeval_cases

import prepare_loghub_os_dataset as loghub_os


SOURCE_CHOICES = ("loghub_os", "rcaeval", "gaia", "backblaze", "openrepair", "local_cases")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a versioned heterogeneous-evidence diagnosis dataset."
    )
    parser.add_argument("--version", default="diagnosis_current")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=SOURCE_CHOICES,
        default=list(SOURCE_CHOICES),
        help="Source families to include when raw files are available.",
    )
    parser.add_argument("--raw-root", default="datasets/raw")
    parser.add_argument("--processed-root", default="datasets/processed")
    parser.add_argument("--interim-root", default="datasets/interim")
    parser.add_argument(
        "--rcaeval-raw-dir",
        default=None,
        help="Optional RCAEval root override, e.g. datasets/raw/rcaeval/re2.",
    )
    parser.add_argument("--window-size", type=int, default=50)
    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument("--audit-sample-size", type=int, default=24)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--dev-ratio", type=float, default=0.10)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    validate_ratios(args.train_ratio, args.dev_ratio)

    raw_root = resolve_project_path(args.raw_root)
    processed_dir = resolve_project_path(args.processed_root) / args.version
    interim_dir = resolve_project_path(args.interim_root) / args.version

    if args.overwrite:
        clean_generated_dir(processed_dir)
        clean_generated_dir(interim_dir)
    elif processed_dir.exists():
        raise FileExistsError(
            f"{processed_dir} already exists. Use --overwrite to regenerate it."
        )

    processed_dir.mkdir(parents=True, exist_ok=True)
    interim_dir.mkdir(parents=True, exist_ok=True)

    all_cases: list[DatasetCase] = []
    source_stats: dict[str, Any] = {}
    skipped_sources: dict[str, str] = {}

    if "loghub_os" in args.sources:
        cases, stats, skipped = build_loghub_os_cases(
            raw_root=raw_root,
            interim_dir=interim_dir / "loghub_os",
            window_size=args.window_size,
            limit_rows=args.limit_rows,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        all_cases.extend(cases)
        source_stats["loghub_os"] = stats
        if skipped:
            skipped_sources.update(skipped)

    if "backblaze" in args.sources:
        cases, stats, skipped = build_csv_adapter_cases(
            source_name="backblaze",
            raw_dir=raw_root / "backblaze",
            iterator=iter_backblaze_cases,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        all_cases.extend(cases)
        source_stats["backblaze"] = stats
        if skipped:
            skipped_sources["backblaze"] = skipped

    if "rcaeval" in args.sources:
        rcaeval_raw_dir = resolve_project_path(args.rcaeval_raw_dir) if args.rcaeval_raw_dir else raw_root / "rcaeval"
        cases, stats, skipped = build_root_adapter_cases(
            source_name="rcaeval",
            raw_dir=rcaeval_raw_dir,
            iterator=iter_rcaeval_cases,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        all_cases.extend(cases)
        source_stats["rcaeval"] = stats
        if skipped:
            skipped_sources["rcaeval"] = skipped

    if "gaia" in args.sources:
        cases, stats, skipped = build_root_adapter_cases(
            source_name="gaia",
            raw_dir=raw_root / "gaia",
            iterator=iter_gaia_cases,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        all_cases.extend(cases)
        source_stats["gaia"] = stats
        if skipped:
            skipped_sources["gaia"] = skipped

    if "openrepair" in args.sources:
        cases, stats, skipped = build_csv_adapter_cases(
            source_name="openrepair",
            raw_dir=raw_root / "openrepair",
            iterator=iter_openrepair_cases,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        all_cases.extend(cases)
        source_stats["openrepair"] = stats
        if skipped:
            skipped_sources["openrepair"] = skipped

    if "local_cases" in args.sources:
        cases, stats, skipped = build_local_cases(
            raw_dir=raw_root / "local_cases",
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        all_cases.extend(cases)
        source_stats["local_cases"] = stats
        if skipped:
            skipped_sources["local_cases"] = skipped

    if not all_cases:
        raise RuntimeError("No cases were generated. Check raw data paths and --sources.")

    all_cases, duplicate_count = ensure_unique_case_ids(all_cases)
    write_dataset_files(processed_dir, all_cases)
    write_per_source_files(processed_dir / "per_source", all_cases)
    write_audit_sample(processed_dir / "audit_sample.jsonl", all_cases, args.audit_sample_size)

    stats = build_stats(
        version=args.version,
        cases=all_cases,
        source_stats=source_stats,
        skipped_sources=skipped_sources,
        duplicate_case_ids_renamed=duplicate_count,
    )
    write_json(stats, processed_dir / "stats.json")

    manifest = build_manifest(
        args=args,
        raw_root=raw_root,
        processed_dir=processed_dir,
        interim_dir=interim_dir,
        stats=stats,
        skipped_sources=skipped_sources,
    )
    write_json(manifest, processed_dir / "manifest.json")
    write_label_policy(processed_dir / "label_policy.md")
    write_readme(processed_dir, stats)

    print(f"Wrote {len(all_cases)} cases to {processed_dir}")
    print(f"Wrote manifest to {processed_dir / 'manifest.json'}")
    if skipped_sources:
        print(f"Skipped sources: {', '.join(sorted(skipped_sources))}")
    return 0


def build_loghub_os_cases(
    *,
    raw_root: Path,
    interim_dir: Path,
    window_size: int,
    limit_rows: int | None,
    train_ratio: float,
    dev_ratio: float,
) -> tuple[list[DatasetCase], dict[str, Any], dict[str, str]]:
    raw_dir = raw_root / "loghub"
    cases: list[DatasetCase] = []
    dataset_stats: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    interim_dir.mkdir(parents=True, exist_ok=True)

    for dataset_key in sorted(loghub_os.DATASETS):
        paths = loghub_os.dataset_paths(raw_dir, dataset_key)
        if not paths["structured"].exists() or not paths["templates"].exists():
            skipped[f"loghub_os:{dataset_key}"] = (
                f"missing {paths['structured']} or {paths['templates']}"
            )
            continue

        generated, stats = loghub_os.prepare_dataset(
            dataset_key=dataset_key,
            structured_csv=paths["structured"],
            template_csv=paths["templates"],
            window_size=window_size,
            limit_rows=limit_rows,
        )
        generated = assign_ordered_splits(
            [
                add_metadata(
                    case,
                    {
                        "source_family": "loghub_os",
                        "label_quality": "weak",
                        "formal_dataset_note": "weak_label_log_window",
                    },
                )
                for case in generated
            ],
            train_ratio=train_ratio,
            dev_ratio=dev_ratio,
        )
        stats["split_distribution"] = count_by_metadata(generated, "split")
        dataset_stats[dataset_key] = stats
        dump_cases_jsonl(generated, interim_dir / f"{dataset_key}.jsonl")
        cases.extend(generated)

    return cases, dataset_stats, skipped


def build_csv_adapter_cases(
    *,
    source_name: str,
    raw_dir: Path,
    iterator: Any,
    train_ratio: float,
    dev_ratio: float,
) -> tuple[list[DatasetCase], dict[str, Any], str | None]:
    if not raw_dir.exists():
        return [], {"case_count": 0, "files": []}, f"missing raw directory {raw_dir}"

    files = sorted(raw_dir.rglob("*.csv"))
    if not files:
        return [], {"case_count": 0, "files": []}, f"no CSV files under {raw_dir}"

    cases: list[DatasetCase] = []
    file_counts: dict[str, int] = {}
    for source_file in files:
        file_cases = [
            add_metadata(
                case,
                {
                    "source_family": source_name,
                    "source_file": str(source_file.relative_to(PROJECT_ROOT)),
                    "label_quality": case.label.confidence if case.label else "unknown",
                },
            )
            for case in iterator(source_file)
        ]
        file_counts[str(source_file.relative_to(PROJECT_ROOT))] = len(file_cases)
        cases.extend(file_cases)

    cases = assign_group_splits(cases, train_ratio=train_ratio, dev_ratio=dev_ratio)
    stats = {
        "case_count": len(cases),
        "files": file_counts,
        "split_distribution": count_by_metadata(cases, "split"),
        "label_distribution": count_labels(cases, "fault_origin"),
        "target_distribution": count_labels(cases, "target"),
    }
    return cases, stats, None


def build_root_adapter_cases(
    *,
    source_name: str,
    raw_dir: Path,
    iterator: Any,
    train_ratio: float,
    dev_ratio: float,
) -> tuple[list[DatasetCase], dict[str, Any], str | None]:
    if not raw_dir.exists():
        return [], {"case_count": 0, "root": str(raw_dir)}, f"missing raw directory {raw_dir}"

    cases = [
        add_metadata(
            case,
            {
                "source_family": source_name,
                "label_quality": case.label.confidence if case.label else "unknown",
            },
        )
        for case in iterator(raw_dir)
    ]
    if not cases:
        return [], {"case_count": 0, "root": str(raw_dir)}, f"no importable cases under {raw_dir}"

    cases = assign_group_splits(cases, train_ratio=train_ratio, dev_ratio=dev_ratio)
    stats = {
        "case_count": len(cases),
        "root": str(raw_dir.relative_to(PROJECT_ROOT)),
        "split_distribution": count_by_metadata(cases, "split"),
        "label_distribution": count_labels(cases, "fault_origin"),
        "target_distribution": count_labels(cases, "target"),
        "modalities_distribution": dict(
            Counter(
                ",".join(case.metadata.get("modalities", case.metadata.get("modalities_available", [])))
                for case in cases
            )
        ),
    }
    return cases, stats, None


def build_local_cases(
    *,
    raw_dir: Path,
    train_ratio: float,
    dev_ratio: float,
) -> tuple[list[DatasetCase], dict[str, Any], str | None]:
    if not raw_dir.exists():
        return [], {"case_count": 0, "files": []}, f"missing raw directory {raw_dir}"

    files = sorted(raw_dir.rglob("*.jsonl"))
    if not files:
        return [], {"case_count": 0, "files": []}, f"no JSONL files under {raw_dir}"

    cases: list[DatasetCase] = []
    file_counts: dict[str, int] = {}
    for source_file in files:
        file_cases = [
            add_metadata(
                case,
                {
                    "source_family": "local_cases",
                    "source_file": str(source_file.relative_to(PROJECT_ROOT)),
                    "label_quality": case.label.confidence if case.label else "unknown",
                },
            )
            for case in load_cases_jsonl(source_file)
        ]
        file_counts[str(source_file.relative_to(PROJECT_ROOT))] = len(file_cases)
        cases.extend(file_cases)

    cases = assign_group_splits(cases, train_ratio=train_ratio, dev_ratio=dev_ratio)
    stats = {
        "case_count": len(cases),
        "files": file_counts,
        "split_distribution": count_by_metadata(cases, "split"),
        "label_distribution": count_labels(cases, "fault_origin"),
        "target_distribution": count_labels(cases, "target"),
    }
    return cases, stats, None


def assign_ordered_splits(
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
        assigned.append(add_metadata(case, {"split": split}))
    return assigned


def assign_group_splits(
    cases: list[DatasetCase],
    *,
    train_ratio: float,
    dev_ratio: float,
) -> list[DatasetCase]:
    groups: dict[str, list[DatasetCase]] = defaultdict(list)
    group_strata: dict[str, str] = {}
    for case in cases:
        group = (
            case.metadata.get("split_group")
            or case.device_id
            or case.fault_case_id
            or case.case_id
        )
        groups[str(group)].append(case)
        group_strata.setdefault(
            str(group),
            str(case.metadata.get("split_stratum") or case.source_dataset or "default"),
        )

    split_by_group = {}
    strata: dict[str, list[str]] = defaultdict(list)
    for group in groups:
        strata[group_strata[group]].append(group)
    for stratum, stratum_groups in strata.items():
        ordered_groups = sorted(stratum_groups, key=stable_hash)
        train_end, dev_end = split_boundaries(len(ordered_groups), train_ratio, dev_ratio)
        for index, group in enumerate(ordered_groups):
            if index < train_end:
                split = "train"
            elif index < dev_end:
                split = "dev"
            else:
                split = "test"
            split_by_group[group] = split

    assigned = []
    for group, group_cases in groups.items():
        assigned.extend(add_metadata(case, {"split": split_by_group[group]}) for case in group_cases)
    return assigned


def add_metadata(case: DatasetCase, extra: dict[str, Any]) -> DatasetCase:
    case = enrich_case(case)
    metadata = dict(case.metadata)
    metadata.update(extra)
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


def rename_case(case: DatasetCase, case_id: str) -> DatasetCase:
    return DatasetCase(
        case_id=case_id,
        source_dataset=case.source_dataset,
        device_type=case.device_type,
        device_id=case.device_id,
        fault_case_id=case.fault_case_id,
        timestamp=case.timestamp,
        fault_time=case.fault_time,
        symptom=case.symptom,
        evidence=case.evidence,
        label=case.label,
        metadata=case.metadata,
    )


def ensure_unique_case_ids(cases: list[DatasetCase]) -> tuple[list[DatasetCase], int]:
    seen: Counter[str] = Counter()
    unique_cases: list[DatasetCase] = []
    renamed = 0
    for case in cases:
        seen[case.case_id] += 1
        if seen[case.case_id] == 1:
            unique_cases.append(case)
            continue
        renamed += 1
        unique_cases.append(rename_case(case, f"{case.case_id}_dup{seen[case.case_id]}"))
    return unique_cases, renamed


def write_dataset_files(processed_dir: Path, cases: list[DatasetCase]) -> None:
    dump_cases_jsonl(cases, processed_dir / "all.jsonl")
    for split in ("train", "dev", "test"):
        split_cases = [case for case in cases if case.metadata.get("split") == split]
        dump_cases_jsonl(split_cases, processed_dir / f"{split}.jsonl")


def write_per_source_files(per_source_dir: Path, cases: list[DatasetCase]) -> None:
    per_source_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[DatasetCase]] = defaultdict(list)
    for case in cases:
        key = safe_filename(str(case.source_dataset or "unknown"))
        grouped[key].append(case)
    for key, group_cases in sorted(grouped.items()):
        dump_cases_jsonl(group_cases, per_source_dir / f"{key}.jsonl")


def write_audit_sample(path: Path, cases: list[DatasetCase], sample_size: int) -> None:
    abnormal = [
        case
        for case in cases
        if case.label is not None and case.label.fault_origin != "no_fault_observed"
    ]
    normal = [
        case
        for case in cases
        if case.label is not None and case.label.fault_origin == "no_fault_observed"
    ]
    selected = abnormal[: sample_size // 2]
    selected.extend(normal[: max(0, sample_size - len(selected))])
    dump_cases_jsonl(selected[:sample_size], path)


def build_stats(
    *,
    version: str,
    cases: list[DatasetCase],
    source_stats: dict[str, Any],
    skipped_sources: dict[str, str],
    duplicate_case_ids_renamed: int,
) -> dict[str, Any]:
    return {
        "version": version,
        "generated_at": utc_now(),
        "case_count": len(cases),
        "split_distribution": count_by_metadata(cases, "split"),
        "source_dataset_distribution": dict(Counter(case.source_dataset for case in cases)),
        "source_family_distribution": count_by_metadata(cases, "source_family"),
        "device_type_distribution": dict(Counter(case.device_type for case in cases)),
        "fault_origin_distribution": count_labels(cases, "fault_origin"),
        "target_distribution": count_labels(cases, "target"),
        "serviceability_type_distribution": count_labels(cases, "serviceability_type"),
        "boundary_type_distribution": count_labels(cases, "boundary_type"),
        "label_confidence_distribution": count_labels(cases, "confidence"),
        "official_ground_truth_note": (
            "Loghub cases are weak-label log evidence. RCAEval and GAIA preserve "
            "injection ground truth for service-level validation; hardware or repair "
            "conclusions still require Backblaze, OpenRepair, or local closed-loop cases."
        ),
        "source_stats": source_stats,
        "skipped_sources": skipped_sources,
        "duplicate_case_ids_renamed": duplicate_case_ids_renamed,
    }


def build_manifest(
    *,
    args: argparse.Namespace,
    raw_root: Path,
    processed_dir: Path,
    interim_dir: Path,
    stats: dict[str, Any],
    skipped_sources: dict[str, str],
) -> dict[str, Any]:
    files = {
        "all": "all.jsonl",
        "train": "train.jsonl",
        "dev": "dev.jsonl",
        "test": "test.jsonl",
        "stats": "stats.json",
        "label_policy": "label_policy.md",
        "audit_sample": "audit_sample.jsonl",
    }
    return {
        "version": args.version,
        "generated_at": utc_now(),
        "builder": str(Path(__file__).relative_to(PROJECT_ROOT)),
        "raw_root": str(raw_root.relative_to(PROJECT_ROOT)),
        "processed_dir": str(processed_dir.relative_to(PROJECT_ROOT)),
        "interim_dir": str(interim_dir.relative_to(PROJECT_ROOT)),
        "sources_requested": list(args.sources),
        "sources_included": sorted(stats.get("source_family_distribution", {}).keys()),
        "sources_skipped": skipped_sources,
        "parameters": {
            "window_size": args.window_size,
            "limit_rows": args.limit_rows,
            "train_ratio": args.train_ratio,
            "dev_ratio": args.dev_ratio,
            "test_ratio": round(1.0 - args.train_ratio - args.dev_ratio, 4),
            "audit_sample_size": args.audit_sample_size,
            "rcaeval_raw_dir": str(resolve_project_path(args.rcaeval_raw_dir).relative_to(PROJECT_ROOT))
            if args.rcaeval_raw_dir
            else None,
        },
        "case_count": stats["case_count"],
        "split_distribution": stats["split_distribution"],
        "files": files,
        "artifact_sha256": collect_artifact_hashes(processed_dir),
    }


def collect_artifact_hashes(root: Path) -> dict[str, str]:
    """Hash generated artifacts before writing the manifest itself."""

    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_label_policy(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Label Policy",
                "",
                "This dataset uses three label-quality levels:",
                "",
                "- gold: closed-loop repair result, active test confirmation, or reliable hardware failure label.",
                "- silver: clear multi-source evidence but no closed-loop repair result.",
                "- weak: deterministic rule/template label. Loghub OS cases are weak labels.",
                "",
                "The main formal conclusions should prioritize gold/silver subsets when available.",
                "Weak-label Loghub OS results must be reported as weak-supervision evaluation only.",
                "",
                "Diagnosis labels are separated into:",
                "",
                "- fault_origin: coarse root-origin boundary.",
                "- target: concrete root-cause or candidate class.",
                "- serviceability_type: repair or service decision category.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_readme(processed_dir: Path, stats: dict[str, Any]) -> None:
    lines = [
        f"# {stats['version']} Dataset",
        "",
        "Generated formal experiment input for heterogeneous-evidence diagnosis.",
        "",
        "## Summary",
        "",
        f"- Cases: {stats['case_count']}",
        f"- Splits: {stats['split_distribution']}",
        f"- Sources: {stats['source_family_distribution']}",
        f"- Skipped sources: {stats['skipped_sources']}",
        "",
        "Baseline predictions should be written to `reports/experiments`, not this directory.",
        "",
    ]
    (processed_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def count_by_metadata(cases: Iterable[DatasetCase], key: str) -> dict[str, int]:
    return dict(Counter(str(case.metadata.get(key, "unknown")) for case in cases))


def count_labels(cases: Iterable[DatasetCase], key: str) -> dict[str, int]:
    values = []
    for case in cases:
        if case.label is None:
            values.append("unlabeled")
        else:
            values.append(str(getattr(case.label, key)))
    return dict(Counter(values))


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def clean_generated_dir(path: Path) -> None:
    path = path.resolve()
    root = PROJECT_ROOT.resolve()
    if not str(path).startswith(str(root)):
        raise ValueError(f"Refusing to clean outside project root: {path}")
    if path.exists():
        shutil.rmtree(path)


def resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def validate_ratios(train_ratio: float, dev_ratio: float) -> None:
    if train_ratio <= 0 or dev_ratio < 0:
        raise ValueError("Train/dev ratios must be non-negative and train must be positive.")
    if train_ratio + dev_ratio >= 1:
        raise ValueError("Train ratio plus dev ratio must leave a positive test split.")


def split_boundaries(total: int, train_ratio: float, dev_ratio: float) -> tuple[int, int]:
    train_count = int(round(total * train_ratio))
    dev_count = int(round(total * dev_ratio))
    if total > 0 and train_count >= total:
        train_count = total - 1
    if total - train_count - dev_count <= 0:
        dev_count = max(0, total - train_count - 1)
    if total >= 3 and dev_ratio > 0 and dev_count == 0:
        dev_count = 1
        if total - train_count - dev_count <= 0:
            train_count = max(1, total - dev_count - 1)
    return train_count, train_count + dev_count


def stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
