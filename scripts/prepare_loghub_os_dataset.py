"""Download and prepare Loghub OS logs for weak-label experiments.

The Loghub Linux/Windows/Mac datasets do not provide official anomaly labels.
This script creates weakly labeled, windowed DatasetCase JSONL files so the
project's experiment scripts can run on a reproducible OS log benchmark.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fru_diagnosis.datasets import DatasetCase, EvidenceBundle, Label, dump_cases_jsonl, enrich_case
from fru_diagnosis.log_noise_reduction import (
    LOG_NOISE_REDUCTION_REFERENCES,
    build_log_noise_profile,
)


LOGHUB_RAW_BASE = "https://raw.githubusercontent.com/logpai/loghub/master"
LOGHUB_CDN_BASE = "https://cdn.jsdelivr.net/gh/logpai/loghub@master"
DATASETS = {
    "linux": {
        "display_name": "Linux",
        "description": "Linux system log",
        "official_lines": 25_567,
        "official_time_span": "263.9 days",
        "raw_size": "2.25MiB",
    },
    "windows": {
        "display_name": "Windows",
        "description": "Windows event log",
        "official_lines": 114_608_388,
        "official_time_span": "226.7 days",
        "raw_size": "26.09GiB",
    },
    "mac": {
        "display_name": "Mac",
        "description": "Mac OS log",
        "official_lines": 117_283,
        "official_time_span": "7.0 days",
        "raw_size": "16.09MiB",
    },
}

ABNORMAL_KEYWORDS = {
    "fatal",
    "panic",
    "exception",
    "failed",
    "failure",
    "error",
    "hresult",
    "bugcheck",
    "crash",
    "segmentation fault",
    "segfault",
}

CONFIG_KEYWORDS = {
    "configuration",
    "config",
    "permission denied",
    "invalid",
    "missing",
    "not found",
    "unrecognized",
}

OS_DRIVER_KEYWORDS = {
    "driver",
    "kernel",
    "module",
    "service",
    "daemon",
    "launchd",
    "trustedinstaller",
    "windowsupdateagent",
    "cbs",
    "wmi",
}

WEAK_LABEL_POLICY_VERSION = "loghub_os_v2_evidence_scored"

SEVERE_KEYWORDS = {
    "bad block",
    "bugcheck",
    "crash",
    "fatal",
    "kernel panic",
    "machine check",
    "media error",
    "panic",
    "segfault",
    "segmentation fault",
    "uncorrectable",
    "whea",
}

BENIGN_KEYWORDS = {
    "completed successfully",
    "loaded",
    "no startup processing required",
    "session closed",
    "session opened",
    "starts successfully",
    "startup complete",
    "succeeded",
    "successfully",
}

TARGET_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "driver_or_os_fault": (
        ("kernel panic", 4.0),
        ("bugcheck", 4.0),
        ("segfault", 3.0),
        ("segmentation fault", 3.0),
        ("driver", 2.6),
        ("kernel", 1.5),
        ("module", 1.4),
        ("hid", 1.1),
    ),
    "os_fault": (
        ("cbs", 2.8),
        ("trustedinstaller", 2.6),
        ("windowsupdateagent", 2.4),
        ("hresult", 2.0),
        ("manifest", 1.8),
        ("package", 1.6),
        ("launchd", 1.6),
        ("daemon", 1.5),
        ("service", 1.4),
        ("iconservicesagent", 1.4),
        ("webkit", 1.2),
        ("sosaccount", 1.2),
    ),
    "firmware_or_config_fault": (
        ("acpi", 3.0),
        ("bios", 2.8),
        ("firmware", 2.8),
        ("pci", 2.2),
        ("irq routing", 2.0),
        ("configuration", 2.0),
        ("config", 1.8),
        ("invalid", 1.8),
        ("unrecognized", 1.6),
        ("missing", 1.6),
        ("not found", 1.6),
        ("permission denied", 1.8),
        ("account identity not set", 2.2),
        ("path not allowed", 2.0),
        ("dnsconfig", 2.0),
    ),
    "external_environment_fault": (
        ("network is down", 3.0),
        ("no network route", 3.0),
        ("internet connection appears to be offline", 3.0),
        ("request timed out", 2.6),
        ("timed out", 2.2),
        ("offline", 2.2),
        ("connectx", 1.8),
        ("socket_connect", 1.8),
        ("socket connect", 1.8),
        ("dns", 1.5),
        ("gateway", 1.5),
        ("router", 1.5),
        ("outlet", 1.5),
        ("external", 1.2),
    ),
    "data_or_filesystem_fault": (
        ("bad block", 3.5),
        ("media error", 3.5),
        ("ntfs", 2.4),
        ("filesystem", 2.2),
        ("file system", 2.2),
        ("corrupt", 2.2),
        ("volume", 1.6),
        ("low disk", 1.8),
    ),
}

TARGET_PRIORITY = (
    "firmware_or_config_fault",
    "os_fault",
    "driver_or_os_fault",
    "external_environment_fault",
    "data_or_filesystem_fault",
)


@dataclass(frozen=True)
class WeakLabelDecision:
    abnormal: bool
    target: str
    fault_origin: str
    serviceability_type: str
    repair_action: str
    evidence_strength: float
    target_scores: dict[str, float]
    matched_terms: dict[str, list[str]]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "abnormal": self.abnormal,
            "target": self.target,
            "fault_origin": self.fault_origin,
            "serviceability_type": self.serviceability_type,
            "repair_action": self.repair_action,
            "evidence_strength": self.evidence_strength,
            "target_scores": self.target_scores,
            "matched_terms": self.matched_terms,
            "reason": self.reason,
            "policy_version": WEAK_LABEL_POLICY_VERSION,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and prepare Loghub Linux/Windows/Mac weak-label cases."
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=sorted(DATASETS),
        default=sorted(DATASETS),
        help="Datasets to prepare. Defaults to all OS datasets.",
    )
    parser.add_argument("--raw-dir", default="datasets/raw/loghub")
    parser.add_argument("--processed-dir", default="datasets/interim/loghub_os_repro")
    parser.add_argument("--window-size", type=int, default=50)
    parser.add_argument("--limit-rows", type=int, default=None)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    if args.window_size <= 0:
        raise ValueError("--window-size must be greater than zero")

    raw_dir = Path(args.raw_dir)
    processed_dir = Path(args.processed_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    all_cases: list[DatasetCase] = []
    stats: dict[str, Any] = {
        "note": (
            "Loghub Linux/Windows/Mac do not include official fault labels. "
            "Labels generated here are weak labels from deterministic rules."
        ),
        "window_size": args.window_size,
        "limit_rows": args.limit_rows,
        "datasets": {},
    }

    for dataset_key in args.datasets:
        paths = dataset_paths(raw_dir, dataset_key)
        if not args.skip_download:
            download_dataset_files(dataset_key, paths, force=args.force_download)

        cases, dataset_stats = prepare_dataset(
            dataset_key=dataset_key,
            structured_csv=paths["structured"],
            template_csv=paths["templates"],
            window_size=args.window_size,
            limit_rows=args.limit_rows,
        )
        cases = assign_splits(cases)
        stats["datasets"][dataset_key] = dataset_stats
        stats["datasets"][dataset_key]["split_distribution"] = dict(
            Counter(case.metadata.get("split", "unknown") for case in cases)
        )

        dataset_out = processed_dir / f"{dataset_key}.jsonl"
        dump_cases_jsonl(cases, dataset_out)
        all_cases.extend(cases)

    dump_cases_jsonl(all_cases, processed_dir / "all.jsonl")
    for split in ["train", "dev", "test"]:
        split_cases = [case for case in all_cases if case.metadata.get("split") == split]
        dump_cases_jsonl(split_cases, processed_dir / f"{split}.jsonl")

    write_json(stats, processed_dir / "stats.json")
    write_readme(processed_dir, stats)
    write_prompt_templates(processed_dir / "prompts")

    print(f"Wrote {len(all_cases)} cases to {processed_dir}")
    print(f"Wrote stats to {processed_dir / 'stats.json'}")
    return 0


def dataset_paths(raw_dir: Path, dataset_key: str) -> dict[str, Path]:
    display_name = DATASETS[dataset_key]["display_name"]
    target_dir = raw_dir / dataset_key
    return {
        "dir": target_dir,
        "structured": target_dir / f"{display_name}_2k.log_structured.csv",
        "templates": target_dir / f"{display_name}_2k.log_templates.csv",
    }


def download_dataset_files(dataset_key: str, paths: dict[str, Path], force: bool) -> None:
    display_name = DATASETS[dataset_key]["display_name"]
    paths["dir"].mkdir(parents=True, exist_ok=True)
    files = {
        paths["structured"]: [
            f"{LOGHUB_RAW_BASE}/{display_name}/{display_name}_2k.log_structured.csv",
            f"{LOGHUB_CDN_BASE}/{display_name}/{display_name}_2k.log_structured.csv",
        ],
        paths["templates"]: [
            f"{LOGHUB_RAW_BASE}/{display_name}/{display_name}_2k.log_templates.csv",
            f"{LOGHUB_CDN_BASE}/{display_name}/{display_name}_2k.log_templates.csv",
        ],
    }
    for target, urls in files.items():
        if target.exists() and target.stat().st_size > 0 and not force:
            print(f"Using existing {target}")
            continue
        print(f"Downloading {target.name}")
        download_file(urls, target)


def download_file(urls: list[str], target: Path, retries: int = 4) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    headers = {"User-Agent": "codex-loghub-preparer"}
    last_error: Exception | None = None
    for url in urls:
        for attempt in range(1, retries + 1):
            try:
                content_length = probe_content_length(url, headers)
                if content_length and content_length > 0:
                    print(f"  {url} ({content_length} bytes)")
                    download_file_in_ranges(url, tmp_target, headers, content_length)
                else:
                    print(f"  {url}")
                    download_file_streaming(url, tmp_target, headers)
                tmp_target.replace(target)
                print(f"  wrote {target}")
                return
            except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
                last_error = exc
                if tmp_target.exists():
                    tmp_target.unlink()
                time.sleep(min(attempt * 2, 8))
    raise RuntimeError(f"Failed to download {target.name}") from last_error


def probe_content_length(url: str, headers: dict[str, str]) -> int | None:
    request = urllib.request.Request(url, headers=headers, method="HEAD")
    with urllib.request.urlopen(request, timeout=20) as response:
        value = response.headers.get("Content-Length")
    return int(value) if value and value.isdigit() else None


def download_file_in_ranges(
    url: str,
    target: Path,
    headers: dict[str, str],
    content_length: int,
    chunk_size: int = 64 * 1024,
) -> None:
    with target.open("wb") as handle:
        offset = 0
        while offset < content_length:
            end = min(offset + chunk_size - 1, content_length - 1)
            chunk = request_range(url, headers, offset, end)
            if not chunk:
                raise RuntimeError(f"Empty response for byte range {offset}-{end}")
            handle.write(chunk[: end - offset + 1])
            offset += len(chunk[: end - offset + 1])
    if target.stat().st_size != content_length:
        raise RuntimeError(
            f"Downloaded size mismatch for {target.name}: "
            f"{target.stat().st_size} != {content_length}"
        )


def request_range(url: str, headers: dict[str, str], start: int, end: int) -> bytes:
    request_headers = dict(headers)
    request_headers["Range"] = f"bytes={start}-{end}"
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def download_file_streaming(url: str, target: Path, headers: dict[str, str]) -> None:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        with target.open("wb") as handle:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                handle.write(chunk)


def prepare_dataset(
    *,
    dataset_key: str,
    structured_csv: Path,
    template_csv: Path,
    window_size: int,
    limit_rows: int | None,
) -> tuple[list[DatasetCase], dict[str, Any]]:
    rows = read_structured_rows(structured_csv, limit_rows=limit_rows)
    cases = [
        window_to_case(dataset_key, window_index, window)
        for window_index, window in enumerate(chunked(rows, window_size))
    ]
    label_distribution = Counter(
        case.label.fault_origin if case.label else "unlabeled" for case in cases
    )
    target_distribution = Counter(case.label.target if case.label else "unlabeled" for case in cases)
    stats = {
        **DATASETS[dataset_key],
        "official_label_available": False,
        "official_fault_count": 0,
        "source_structured_csv": str(structured_csv),
        "source_template_csv": str(template_csv),
        "raw_rows_processed": len(rows),
        "case_count": len(cases),
        "template_count": count_templates(template_csv),
        "label_distribution": dict(label_distribution),
        "target_distribution": dict(target_distribution),
        "weak_label_policy": {
            "version": WEAK_LABEL_POLICY_VERSION,
            "abnormal_keywords": sorted(ABNORMAL_KEYWORDS),
            "config_keywords": sorted(CONFIG_KEYWORDS),
            "os_driver_keywords": sorted(OS_DRIVER_KEYWORDS),
            "target_rules": {
                target: [term for term, _ in rules]
                for target, rules in TARGET_RULES.items()
            },
            "noise_reduction": "template_event_noise_reduction",
            "references": LOG_NOISE_REDUCTION_REFERENCES,
            "confidence": "weak",
        },
    }
    return cases, stats


def read_structured_rows(path: Path, limit_rows: int | None) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing structured CSV: {path}")
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "Content" not in (reader.fieldnames or []):
            raise ValueError(f"Structured CSV must contain a Content column: {path}")
        for index, row in enumerate(reader):
            if limit_rows is not None and index >= limit_rows:
                break
            rows.append({key: str(value or "") for key, value in row.items()})
    return rows


def chunked(rows: list[dict[str, str]], size: int) -> Iterable[list[dict[str, str]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def window_to_case(dataset_key: str, window_index: int, rows: list[dict[str, str]]) -> DatasetCase:
    dataset_name = f"loghub_{dataset_key}"
    line_ids = [to_int(row.get("LineId", "")) for row in rows]
    line_ids = [line_id for line_id in line_ids if line_id is not None]
    messages = [row.get("Content", "") for row in rows]
    templates = [row.get("EventTemplate", "") for row in rows if row.get("EventTemplate")]
    event_ids = [row.get("EventId", "") for row in rows if row.get("EventId")]
    components = [row.get("Component", "") for row in rows if row.get("Component")]
    levels = [row.get("Level", "") for row in rows if row.get("Level")]
    joined_text = "\n".join(messages + templates).casefold()
    abnormal_terms = sorted(term for term in ABNORMAL_KEYWORDS if term in joined_text)
    config_terms = sorted(term for term in CONFIG_KEYWORDS if term in joined_text)
    os_driver_terms = sorted(term for term in OS_DRIVER_KEYWORDS if term in joined_text)
    noise_profile = build_log_noise_profile(
        [
            {
                "message": row.get("Content", ""),
                "template": row.get("EventTemplate", ""),
                "event_id": row.get("EventId", ""),
                "level": row.get("Level", ""),
                "component": row.get("Component", ""),
            }
            for row in rows
        ]
    )
    actionable_event_count = int(noise_profile.get("actionable_event_count", 0) or 0)
    evidence_messages = list(noise_profile.get("retained_messages", [])) or select_evidence_messages(
        messages,
        abnormal_terms + config_terms + sorted(SEVERE_KEYWORDS),
    )
    decision = classify_log_window(
        dataset_key=dataset_key,
        actionable_event_count=actionable_event_count,
        evidence_messages=evidence_messages,
        templates=templates,
        joined_text=joined_text,
    )
    symptom = ("log_anomaly",) if decision.abnormal else ("log_observation",)

    evidence = EvidenceBundle(
        logs={
            "dataset": dataset_name,
            "row_count": len(rows),
            "line_range": {
                "start": min(line_ids) if line_ids else "",
                "end": max(line_ids) if line_ids else "",
            },
            "time_range": {
                "start": format_timestamp(rows[0]) if rows else "",
                "end": format_timestamp(rows[-1]) if rows else "",
            },
            "level_counts": dict(Counter(levels)),
            "component_counts": dict(Counter(components).most_common(20)),
            "event_id_counts": dict(Counter(event_ids).most_common(20)),
            "event_template_counts": dict(Counter(templates).most_common(20)),
            "noise_reduction": noise_profile,
            "raw_warning_error_count": len(rows),
            "actionable_warning_error_count": actionable_event_count,
            "raw_messages": messages,
            "evidence_messages": evidence_messages,
            "weak_label_signals": {
                "abnormal_terms": abnormal_terms,
                "config_terms": config_terms,
                "os_driver_terms": os_driver_terms,
                "severe_terms": sorted(term for term in SEVERE_KEYWORDS if term in joined_text),
                "target_scores": decision.target_scores,
                "matched_terms": decision.matched_terms,
            },
            "weak_label_decision": decision.to_dict(),
        }
    )
    label = Label(
        fault_origin=decision.fault_origin,
        target=decision.target,
        serviceability_type=decision.serviceability_type,
        repair_action=decision.repair_action,
        fixed=None,
        confidence="weak",
        source=f"{dataset_name}.weak_rules",
    )
    metadata = {
        "dataset_key": dataset_key,
        "window_index": window_index,
        "window_size": len(rows),
        "line_start": min(line_ids) if line_ids else "",
        "line_end": max(line_ids) if line_ids else "",
        "official_label_available": False,
        "manual_review_required": decision.abnormal or noise_profile.get("suppressed_event_count", 0) > 0,
        "labeling_prompt_template": "prompts/log_window_labeling_prompt.md",
        "weak_label_policy_version": WEAK_LABEL_POLICY_VERSION,
        "evidence_strength": decision.evidence_strength,
    }
    return enrich_case(DatasetCase(
        case_id=f"{dataset_name}_window_{window_index:06d}",
        source_dataset=dataset_name,
        device_type="computer_system",
        timestamp=format_timestamp(rows[0]) if rows else "",
        fault_time=format_timestamp(rows[0]) if decision.abnormal and rows else "",
        symptom=symptom,
        evidence=evidence,
        label=label,
        metadata=metadata,
    ))


def classify_log_window(
    *,
    dataset_key: str,
    actionable_event_count: int,
    evidence_messages: list[str],
    templates: list[str],
    joined_text: str,
) -> WeakLabelDecision:
    """Classify one log window with evidence-scored weak labels.

    The policy is intentionally still weak supervision, but it avoids the old
    binary shortcut where every actionable event became driver_or_os_fault and
    every non-actionable event became none.
    """

    diagnostic_text = "\n".join(evidence_messages + templates[:20]).casefold()
    if not diagnostic_text.strip():
        diagnostic_text = joined_text.casefold()

    target_scores, matched_terms = score_targets(diagnostic_text, dataset_key)
    top_target, top_score = choose_target(target_scores)
    severe_terms = sorted(term for term in SEVERE_KEYWORDS if term in diagnostic_text)
    abnormal_terms = sorted(term for term in ABNORMAL_KEYWORDS if term in diagnostic_text)
    benign_terms = sorted(term for term in BENIGN_KEYWORDS if term in diagnostic_text)
    has_fault_term = bool(severe_terms or abnormal_terms)

    evidence_strength = round(actionable_event_count * 1.5 + top_score, 4)
    abnormal = actionable_event_count > 0 or bool(severe_terms) or (
        has_fault_term and top_score >= 2.0
    )
    if not abnormal and top_score >= 3.2 and not benign_terms:
        abnormal = True

    if not abnormal:
        return WeakLabelDecision(
            abnormal=False,
            target="none",
            fault_origin="no_fault_observed",
            serviceability_type="none",
            repair_action="no_repair",
            evidence_strength=evidence_strength,
            target_scores=target_scores,
            matched_terms=matched_terms,
            reason="no strong diagnostic evidence after scoring",
        )

    target = top_target if top_target != "unknown" else classify_target([], [], diagnostic_text)
    return WeakLabelDecision(
        abnormal=True,
        target=target,
        fault_origin="non_fru_fault",
        serviceability_type="non_fru_fault",
        repair_action=repair_action_for_target(target),
        evidence_strength=evidence_strength,
        target_scores=target_scores,
        matched_terms=matched_terms,
        reason=label_reason(actionable_event_count, top_target, top_score, severe_terms, abnormal_terms),
    )


def score_targets(text: str, dataset_key: str) -> tuple[dict[str, float], dict[str, list[str]]]:
    scores: dict[str, float] = {target: 0.0 for target in TARGET_RULES}
    matched: dict[str, list[str]] = {target: [] for target in TARGET_RULES}
    for target, rules in TARGET_RULES.items():
        for term, weight in rules:
            if term in text:
                scores[target] += weight
                matched[target].append(term)

    # Dataset-specific log vocabulary calibration. These are still weak-label
    # rules, but they keep OS servicing logs, macOS account/config logs, and
    # Linux firmware/platform logs from collapsing into one driver bucket.
    if dataset_key == "windows" and any(
        term in text for term in ["cbs", "trustedinstaller", "windowsupdateagent", "hresult"]
    ):
        scores["os_fault"] += 2.0
        matched["os_fault"].append("windows_servicing_context")
    if dataset_key == "mac" and any(
        term in text for term in ["account identity not set", "dnsconfig", "path not allowed", "unrecognized"]
    ):
        scores["firmware_or_config_fault"] += 1.5
        matched["firmware_or_config_fault"].append("mac_configuration_context")
    if dataset_key == "linux" and any(term in text for term in ["acpi", "bios", "pci"]):
        scores["firmware_or_config_fault"] += 1.5
        matched["firmware_or_config_fault"].append("linux_platform_context")

    scores = {target: round(value, 4) for target, value in scores.items() if value > 0}
    matched = {target: terms for target, terms in matched.items() if terms}
    return scores, matched


def choose_target(target_scores: dict[str, float]) -> tuple[str, float]:
    if not target_scores:
        return "unknown", 0.0
    best_score = max(target_scores.values())
    tied = {target for target, score in target_scores.items() if score == best_score}
    for target in TARGET_PRIORITY:
        if target in tied:
            return target, best_score
    target = sorted(tied)[0]
    return target, best_score


def repair_action_for_target(target: str) -> str:
    return {
        "driver_or_os_fault": "investigate_driver_or_os_logs",
        "os_fault": "repair_or_update_os_component",
        "firmware_or_config_fault": "check_firmware_or_configuration",
        "configuration_fault": "repair_configuration",
        "external_environment_fault": "validate_external_environment",
        "data_or_filesystem_fault": "check_filesystem_or_data_integrity",
    }.get(target, "investigate_logs")


def label_reason(
    actionable_event_count: int,
    top_target: str,
    top_score: float,
    severe_terms: list[str],
    abnormal_terms: list[str],
) -> str:
    if severe_terms:
        return f"severe terms {severe_terms} support {top_target}"
    if actionable_event_count > 0:
        return f"{actionable_event_count} actionable log templates support {top_target}"
    return f"diagnostic terms {abnormal_terms} scored {top_score:.2f} for {top_target}"


def classify_target(
    config_terms: list[str],
    os_driver_terms: list[str],
    joined_text: str,
) -> str:
    if "panic" in joined_text or "kernel" in joined_text or "driver" in joined_text:
        return "driver_or_os_fault"
    if os_driver_terms:
        return "driver_or_os_fault"
    if config_terms:
        return "configuration_fault"
    return "os_fault"


def select_evidence_messages(messages: list[str], terms: list[str], limit: int = 8) -> list[str]:
    if not terms:
        return []
    selected = []
    for message in messages:
        text = message.casefold()
        if any(term in text for term in terms):
            selected.append(message)
        if len(selected) >= limit:
            break
    return selected


def format_timestamp(row: dict[str, str]) -> str:
    pieces = [
        row.get("Month", ""),
        row.get("Date", ""),
        row.get("Time", ""),
    ]
    if not any(pieces):
        pieces = [row.get("Date", ""), row.get("Time", "")]
    return " ".join(piece for piece in pieces if piece).strip()


def to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def count_templates(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def assign_splits(cases: list[DatasetCase]) -> list[DatasetCase]:
    total = len(cases)
    assigned = []
    for index, case in enumerate(cases):
        ratio = index / total if total else 0
        if ratio < 0.7:
            split = "train"
        elif ratio < 0.85:
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


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_readme(processed_dir: Path, stats: dict[str, Any]) -> None:
    lines = [
        "# Loghub OS Weak-Label Dataset",
        "",
        "This directory is generated by `scripts/prepare_loghub_os_dataset.py`.",
        "",
        "Linux, Windows, and Mac in Loghub do not include official fault labels. "
        "The JSONL labels here are weak labels produced by deterministic rules and "
        "should be described as weak supervision, not ground truth.",
        "",
        "## Files",
        "",
        "- `all.jsonl`: all generated cases.",
        "- `linux.jsonl`, `windows.jsonl`, `mac.jsonl`: per-dataset cases.",
        "- `train.jsonl`, `dev.jsonl`, `test.jsonl`: chronological splits within each dataset.",
        "- `stats.json`: dataset statistics and weak-label policy.",
        "- `prompts/`: prompt templates for manual or LLM-assisted review.",
        "",
        "## Summary",
        "",
        "| Dataset | Rows processed | Cases | Templates | Weak abnormal cases | Official fault labels |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for dataset_key, dataset_stats in stats["datasets"].items():
        labels = dataset_stats.get("label_distribution", {})
        weak_abnormal = labels.get("non_fru_fault", 0)
        lines.append(
            "| {name} | {rows} | {cases} | {templates} | {weak} | 0 |".format(
                name=dataset_stats["display_name"],
                rows=dataset_stats["raw_rows_processed"],
                cases=dataset_stats["case_count"],
                templates=dataset_stats["template_count"],
                weak=weak_abnormal,
            )
        )
    lines.extend(
        [
            "",
            "## Example",
            "",
            "```powershell",
            "python experiments\\run_baselines.py datasets\\interim\\loghub_os_repro\\all.jsonl reports\\experiments\\retired_loghub_os\\all_pred.jsonl",
            "python experiments\\evaluate_cases.py reports\\experiments\\retired_loghub_os\\all_pred.jsonl",
            "```",
            "",
        ]
    )
    (processed_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_prompt_templates(prompt_dir: Path) -> None:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompts = {
        "log_window_labeling_prompt.md": """# Log Window Labeling Prompt

You are an operating-system log fault-analysis assistant.
Decide whether the log window shows a software-layer anomaly.
Use only the log content. Do not invent hardware faults.

Return JSON:

```json
{
  "is_abnormal": true,
  "fault_origin": "no_fault_observed | non_fru_fault | uncertain",
  "target": "none | driver_or_os_fault | os_fault | configuration_fault | uncertain",
  "serviceability_type": "none | non_fru_fault | need_more_evidence",
  "confidence": "weak | medium | high",
  "evidence": ["short quoted log phrase"],
  "reason": "one-sentence rationale"
}
```

Log window:

```text
{{logs}}
```
""",
        "case_review_prompt.md": """# Weak Label Review Prompt

Review whether this rule-generated weak label is reasonable.
Check:

1. Whether ordinary warnings were mislabeled as faults.
2. Whether a single error was over-interpreted as a real fault.
3. Whether the label should be changed to uncertain.
4. Whether there is clear evidence for driver_or_os_fault.

Original label:

```json
{{weak_label}}
```

Logs:

```text
{{logs}}
```

Return:

```json
{
  "keep_label": true,
  "corrected_label": {},
  "review_note": "short explanation"
}
```
""",
        "dataset_description_prompt.md": """# Dataset Description Prompt

Write an experiment dataset construction description from the statistics below.
Distinguish official labels from weak labels. State clearly that Loghub OS logs
do not provide official fault labels, and that this experiment set uses rules
plus manual sample review for weak supervision.

Statistics:

```json
{{dataset_stats}}
```
""",
    }
    for filename, content in prompts.items():
        (prompt_dir / filename).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
