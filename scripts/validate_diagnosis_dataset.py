"""Validate a versioned diagnosis dataset before it is used in experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_EVIDENCE_KEYS = {
    "inventory",
    "logs",
    "traces",
    "metrics",
    "active_tests",
    "crash_dump",
    "repair_result",
}
BOUNDARY_CLASSES = {
    "software_side",
    "firmware_control",
    "interface_path",
    "hardware_endpoint",
    "external_environment",
    "no_fault_observed",
}
REQUIRED_BOUNDARY_TEST_CLASSES = {"software_side", "interface_path", "hardware_endpoint"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate processed diagnosis dataset integrity.")
    parser.add_argument("processed_dir")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--profile",
        choices=("integrity", "boundary"),
        default="integrity",
        help="Use boundary to enforce hardware/software boundary research readiness.",
    )
    args = parser.parse_args()

    report = validate_dataset(resolve_path(args.processed_dir), profile=args.profile)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_summary(report)
    return 1 if report["errors"] else 0


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def validate_dataset(processed_dir: Path, *, profile: str = "integrity") -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required_files = ("all.jsonl", "train.jsonl", "dev.jsonl", "test.jsonl", "stats.json", "manifest.json")
    for filename in required_files:
        if not (processed_dir / filename).is_file():
            errors.append(f"missing required artifact: {filename}")
    if errors:
        return {"dataset": str(processed_dir), "errors": errors, "warnings": warnings}

    all_cases = load_jsonl(processed_dir / "all.jsonl", errors)
    split_cases = {split: load_jsonl(processed_dir / f"{split}.jsonl", errors) for split in ("train", "dev", "test")}
    manifest = load_json(processed_dir / "manifest.json", errors)
    stats = load_json(processed_dir / "stats.json", errors)
    validate_case_schema(all_cases, errors)
    validate_splits(all_cases, split_cases, errors)
    validate_counts(all_cases, split_cases, manifest, stats, errors)
    validate_split_groups(all_cases, errors)
    validate_hashes(processed_dir, manifest, errors, warnings)
    add_label_warnings(all_cases, warnings)
    boundary_readiness = None
    if profile == "boundary":
        boundary_readiness = validate_boundary_readiness(all_cases, split_cases, errors, warnings)

    return {
        "dataset": str(processed_dir),
        "profile": profile,
        "case_count": len(all_cases),
        "split_distribution": {name: len(cases) for name, cases in split_cases.items()},
        "errors": errors,
        "warnings": warnings,
        "boundary_readiness": boundary_readiness,
    }


def validate_boundary_readiness(
    cases: list[dict[str, Any]],
    split_cases: dict[str, list[dict[str, Any]]],
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    labels = [str((case.get("label") or {}).get("boundary_type", "")) for case in cases]
    missing_label_count = sum(not label for label in labels)
    invalid_labels = sorted({label for label in labels if label and label not in BOUNDARY_CLASSES})
    if missing_label_count:
        errors.append(f"boundary profile requires explicit boundary_type labels: {missing_label_count} missing")
    if invalid_labels:
        errors.append("invalid boundary_type labels: " + ", ".join(invalid_labels))

    test_cases = split_cases.get("test", [])
    test_distribution = Counter(
        str((case.get("label") or {}).get("boundary_type", ""))
        for case in test_cases
    )
    absent = sorted(REQUIRED_BOUNDARY_TEST_CLASSES.difference(test_distribution))
    if absent:
        errors.append("boundary test split is missing required classes: " + ", ".join(absent))
    underrepresented = sorted(
        label
        for label in REQUIRED_BOUNDARY_TEST_CLASSES
        if 0 < test_distribution.get(label, 0) < 3
    )
    if underrepresented:
        errors.append(
            "boundary test classes need at least 3 cases each: " + ", ".join(underrepresented)
        )

    critical_cases = [
        case
        for case in cases
        if str((case.get("label") or {}).get("boundary_type", ""))
        in {"interface_path", "hardware_endpoint"}
    ]
    unconfirmed = [
        str(case.get("case_id", ""))
        for case in critical_cases
        if not has_confirmatory_boundary_evidence(case.get("evidence") or {})
    ]
    if unconfirmed:
        errors.append(
            "interface/hardware cases lack confirmatory non-log evidence: "
            + ", ".join(unconfirmed[:5])
            + (f" (+{len(unconfirmed) - 5} more)" if len(unconfirmed) > 5 else "")
        )

    weak_critical_test = [
        str(case.get("case_id", ""))
        for case in test_cases
        if str((case.get("label") or {}).get("boundary_type", ""))
        in {"interface_path", "hardware_endpoint"}
        and str((case.get("label") or {}).get("confidence", "")).casefold() == "weak"
    ]
    if weak_critical_test:
        errors.append(
            "interface/hardware test labels must be gold or silver, not weak: "
            + ", ".join(weak_critical_test[:5])
        )

    if not critical_cases:
        warnings.append("no interface_path or hardware_endpoint cases are available")
    return {
        "ready": not any("boundary" in error or "interface/hardware" in error for error in errors),
        "label_distribution": dict(Counter(label for label in labels if label)),
        "test_distribution": dict(test_distribution),
        "missing_label_count": missing_label_count,
        "critical_case_count": len(critical_cases),
        "unconfirmed_critical_case_count": len(unconfirmed),
    }


def has_confirmatory_boundary_evidence(evidence: dict[str, Any]) -> bool:
    if has_content(evidence.get("active_tests")) or has_content(evidence.get("repair_result")):
        return True
    inventory_text = json.dumps(evidence.get("inventory", {}), ensure_ascii=False).casefold()
    metric_text = json.dumps(evidence.get("metrics", {}), ensure_ascii=False).casefold()
    crash_text = json.dumps(evidence.get("crash_dump", {}), ensure_ascii=False).casefold()
    tokens = (
        "problem_device", "not_detected", "code 43", "link down", "smart",
        "predicted_failure", "whea", "machine check", "bad block", "failed",
    )
    return any(token in f"{inventory_text} {metric_text} {crash_text}" for token in tokens)


def has_content(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(has_content(item) for item in value)
    return value not in {None, "", "unknown", "not_run", "not_available"}


def load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    errors.append(f"invalid JSON at {path.name}:{line_number}: {exc.msg}")
    except OSError as exc:
        errors.append(f"cannot read {path.name}: {exc}")
    return records


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read {path.name}: {exc}")
        return {}


def validate_case_schema(cases: list[dict[str, Any]], errors: list[str]) -> None:
    ids: Counter[str] = Counter()
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("case_id", ""))
        if not case_id:
            errors.append(f"case {index} is missing case_id")
        ids[case_id] += 1
        metadata = case.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("split") not in {"train", "dev", "test"}:
            errors.append(f"case {case_id or index} has invalid split metadata")
        evidence = case.get("evidence")
        if not isinstance(evidence, dict) or not REQUIRED_EVIDENCE_KEYS.issubset(evidence):
            errors.append(f"case {case_id or index} has incomplete evidence schema")
        label = case.get("label")
        if not isinstance(label, dict) or not label.get("target") or not label.get("confidence"):
            errors.append(f"case {case_id or index} has incomplete label schema")
    duplicates = sorted(case_id for case_id, count in ids.items() if case_id and count > 1)
    if duplicates:
        errors.append(f"duplicate case_id values: {', '.join(duplicates[:5])}")


def validate_splits(
    all_cases: list[dict[str, Any]],
    split_cases: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    all_ids = {str(case.get("case_id", "")) for case in all_cases}
    observed_ids: set[str] = set()
    for split, cases in split_cases.items():
        ids = {str(case.get("case_id", "")) for case in cases}
        if len(ids) != len(cases):
            errors.append(f"duplicate case IDs in {split}.jsonl")
        overlap = observed_ids.intersection(ids)
        if overlap:
            errors.append(f"case IDs appear in multiple splits: {', '.join(sorted(overlap)[:5])}")
        observed_ids.update(ids)
        metadata_mismatch = [case.get("case_id", "") for case in cases if (case.get("metadata") or {}).get("split") != split]
        if metadata_mismatch:
            errors.append(f"split metadata mismatch in {split}.jsonl")
    if all_ids != observed_ids:
        errors.append("all.jsonl does not equal the disjoint union of train/dev/test JSONL files")


def validate_counts(
    cases: list[dict[str, Any]],
    split_cases: dict[str, list[dict[str, Any]]],
    manifest: dict[str, Any],
    stats: dict[str, Any],
    errors: list[str],
) -> None:
    expected = {name: len(records) for name, records in split_cases.items()}
    if manifest.get("case_count") != len(cases):
        errors.append("manifest case_count does not match all.jsonl")
    if stats.get("case_count") != len(cases):
        errors.append("stats case_count does not match all.jsonl")
    for source_name, distribution in (("manifest", manifest.get("split_distribution", {})), ("stats", stats.get("split_distribution", {}))):
        if distribution != expected:
            errors.append(f"{source_name} split_distribution does not match split files")


def validate_split_groups(cases: list[dict[str, Any]], errors: list[str]) -> None:
    groups: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        metadata = case.get("metadata") or {}
        group = str(metadata.get("split_group") or case.get("fault_case_id") or case.get("case_id"))
        groups[group].add(str(metadata.get("split", "")))
    leaked = sorted(group for group, splits in groups.items() if len(splits) > 1)
    if leaked:
        errors.append(f"split-group leakage: {', '.join(leaked[:5])}")


def validate_hashes(processed_dir: Path, manifest: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    expected_hashes = manifest.get("artifact_sha256")
    if not isinstance(expected_hashes, dict):
        warnings.append("manifest has no artifact_sha256 section; rebuild the dataset to add reproducibility hashes")
        return
    for relative_path, expected in expected_hashes.items():
        path = processed_dir / relative_path
        if not path.is_file():
            errors.append(f"hashed artifact is missing: {relative_path}")
        elif sha256_file(path) != expected:
            errors.append(f"artifact hash mismatch: {relative_path}")


def add_label_warnings(cases: list[dict[str, Any]], warnings: list[str]) -> None:
    fault_type_splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        metadata = case.get("metadata") or {}
        fault_type = str(metadata.get("fault_type", ""))
        if fault_type:
            fault_type_splits[fault_type].add(str(metadata.get("split", "")))
    absent_from_test = sorted(label for label, splits in fault_type_splits.items() if "test" not in splits)
    if absent_from_test:
        warnings.append(
            "fault types absent from test split: " + ", ".join(absent_from_test) + "; do not report full fault-type macro-F1"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def print_summary(report: dict[str, Any]) -> None:
    print(f"Dataset: {report['dataset']}")
    print(f"Cases: {report.get('case_count', 0)}")
    print(f"Splits: {report.get('split_distribution', {})}")
    print(f"Errors: {len(report['errors'])}")
    for item in report["errors"]:
        print(f"  ERROR: {item}")
    print(f"Warnings: {len(report['warnings'])}")
    for item in report["warnings"]:
        print(f"  WARNING: {item}")


if __name__ == "__main__":
    raise SystemExit(main())
