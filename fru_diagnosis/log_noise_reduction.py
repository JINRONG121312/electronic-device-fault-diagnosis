"""Template-based log noise reduction for diagnosis evidence.

The implementation follows the project-level interpretation of two papers:
LogCleaner separates useful events from anti-events and duplicative events,
while broader log-anomaly evaluations show that grouping and noisy labels can
change detection results substantially. The code is intentionally conservative:
it compresses repeated warnings and suppresses recoverable errors, but keeps
severe or rule-relevant events as actionable evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable


LOG_NOISE_REDUCTION_REFERENCES = [
    {
        "id": "zhang2024logcleaner",
        "title": "Reducing Events to Augment Log-based Anomaly Detection Models: An Empirical Study",
        "url": "https://arxiv.org/abs/2409.04834",
        "method_role": "anti-events and duplicative-events are reduced before anomaly scoring",
    },
    {
        "id": "le2022howfar",
        "title": "Log-based Anomaly Detection with Deep Learning: How Far Are We?",
        "url": "https://arxiv.org/abs/2202.04301",
        "method_role": "weak labels are kept conservative because grouping and data noise affect results",
    },
]

SEVERE_TERMS = {
    "bad block",
    "bugcheck",
    "bus fatal",
    "checkstop",
    "crash",
    "critical",
    "data loss",
    "fatal",
    "kernel panic",
    "machine check",
    "media error",
    "memory corruption",
    "panic",
    "predictive failure",
    "segmentation fault",
    "segfault",
    "uncorrectable",
    "whea",
}

ABNORMAL_TERMS = {
    "abnormal",
    "access denied",
    "denied",
    "error",
    "exception",
    "fail",
    "failed",
    "failure",
    "hresult",
    "invalid",
    "missing",
    "not found",
    "timeout",
    "unrecognized",
}

IMPACT_TERMS = {
    "acpi",
    "adapter",
    "bad block",
    "battery",
    "bios",
    "corrupt",
    "degraded",
    "device",
    "disk",
    "driver",
    "firmware",
    "gpu",
    "kernel",
    "limited",
    "memory",
    "module",
    "network",
    "ntfs",
    "service",
    "throttle",
    "thermal",
    "wlan",
}

BENIGN_PHRASES = {
    "already exists",
    "completed successfully",
    "handled",
    "ignore",
    "ignored",
    "ignoring",
    "no action required",
    "not applicable",
    "retry succeeded",
    "succeeded",
    "successful",
    "successfully",
}

ORDINARY_EVENT_PATTERNS = (
    re.compile(r"\bconnection from\b", re.IGNORECASE),
    re.compile(r"\bsession (opened|closed)\b", re.IGNORECASE),
    re.compile(r"scheduler_.*\bignoring\b", re.IGNORECASE),
    re.compile(r"\blocation icon should now be\b", re.IGNORECASE),
    re.compile(r"\bthermal pressure state:\s*\d+\s+memory pressure state:\s*\d+", re.IGNORECASE),
)

NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
HEX_RE = re.compile(r"0x[0-9A-Fa-f]+")
UUID_RE = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
SPACE_RE = re.compile(r"\s+")


def build_log_noise_profile(
    entries: Iterable[dict[str, Any]],
    *,
    text_key: str = "message",
    template_key: str = "template",
    event_id_key: str = "event_id",
    level_key: str = "level",
    component_key: str = "component",
    rule_patterns: Iterable[re.Pattern[str]] | None = None,
    duplicate_threshold: int = 4,
    detail_limit: int = 8,
) -> dict[str, Any]:
    """Return a compressed, diagnosis-oriented event profile.

    Actionable counts are compressed by template/signature. For example, 16
    identical warnings become one actionable event if they are still relevant,
    or zero if they look recoverable/benign.
    """

    records = [
        normalize_entry(
            entry,
            text_key=text_key,
            template_key=template_key,
            event_id_key=event_id_key,
            level_key=level_key,
            component_key=component_key,
        )
        for entry in entries
    ]
    signatures = Counter(record["signature"] for record in records)
    first_by_signature: dict[str, dict[str, Any]] = {}
    for record in records:
        first_by_signature.setdefault(record["signature"], record)

    event_type_counts: Counter[str] = Counter()
    retained_templates: list[dict[str, Any]] = []
    suppressed_templates: list[dict[str, Any]] = []
    retained_messages: list[str] = []
    actionable_count = 0
    duplicative_event_count = 0
    anti_event_count = 0
    ordinary_event_count = 0

    patterns = list(rule_patterns or [])
    for signature, count in signatures.most_common():
        record = first_by_signature[signature]
        classification = classify_record(
            record,
            count=count,
            total=len(records),
            rule_patterns=patterns,
            duplicate_threshold=duplicate_threshold,
        )
        event_type = classification["event_type"]
        event_type_counts[event_type] += count
        summary = {
            "signature": signature,
            "template": record["template"],
            "event_id": record["event_id"],
            "component": record["component"],
            "level": record["level"],
            "raw_count": count,
            "event_type": event_type,
            "reason": classification["reason"],
        }
        if classification["actionable"]:
            retained_count = 1 if count > 1 else count
            actionable_count += retained_count
            if count > retained_count:
                duplicative_event_count += count - retained_count
            retained_templates.append({**summary, "retained_count": retained_count})
            if len(retained_messages) < detail_limit and record["message"]:
                retained_messages.append(record["message"])
        else:
            if event_type == "anti_event":
                anti_event_count += count
            elif event_type == "duplicative_event":
                duplicative_event_count += count
            else:
                ordinary_event_count += count
            suppressed_templates.append(summary)

    raw_count = len(records)
    suppressed_count = max(0, raw_count - actionable_count)
    return {
        "method": "template_event_noise_reduction",
        "references": LOG_NOISE_REDUCTION_REFERENCES,
        "raw_event_count": raw_count,
        "actionable_event_count": actionable_count,
        "suppressed_event_count": suppressed_count,
        "anti_event_count": anti_event_count,
        "duplicative_event_count": duplicative_event_count,
        "ordinary_event_count": ordinary_event_count,
        "reduction_ratio": round(suppressed_count / raw_count, 4) if raw_count else 0.0,
        "event_type_counts": dict(event_type_counts),
        "retained_templates": retained_templates[:detail_limit],
        "suppressed_templates": suppressed_templates[:detail_limit],
        "retained_messages": retained_messages,
    }


def normalize_entry(
    entry: dict[str, Any],
    *,
    text_key: str,
    template_key: str,
    event_id_key: str,
    level_key: str,
    component_key: str,
) -> dict[str, str]:
    message = str(entry.get(text_key) or entry.get("message_excerpt") or entry.get("Content") or "")
    template = str(entry.get(template_key) or entry.get("EventTemplate") or "")
    event_id = str(entry.get(event_id_key) or entry.get("EventId") or "")
    level = str(entry.get(level_key) or entry.get("Level") or "")
    component = str(
        entry.get(component_key)
        or entry.get("Component")
        or entry.get("provider")
        or entry.get("Provider")
        or ""
    )
    signature_text = template or message
    signature = "|".join(
        item
        for item in [
            component.casefold(),
            event_id.casefold(),
            normalize_template(signature_text),
        ]
        if item
    )
    if not signature:
        signature = normalize_template(message)
    return {
        "message": message,
        "template": template or normalize_template(message),
        "event_id": event_id,
        "level": level,
        "component": component,
        "signature": signature,
        "text": " ".join([component, event_id, level, template, message]).casefold(),
    }


def normalize_template(value: Any) -> str:
    text = str(value or "").casefold()
    text = UUID_RE.sub("<uuid>", text)
    text = IP_RE.sub("<ip>", text)
    text = HEX_RE.sub("<hex>", text)
    text = NUMBER_RE.sub("<num>", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def classify_record(
    record: dict[str, str],
    *,
    count: int,
    total: int,
    rule_patterns: list[re.Pattern[str]],
    duplicate_threshold: int,
) -> dict[str, Any]:
    text = record["text"]
    level = record["level"].casefold()
    is_warning_error = any(
        token in level
        for token in ["critical", "error", "err", "warning", "warn", "错误", "警告", "严重"]
    )
    has_severe = contains_any(text, SEVERE_TERMS)
    has_abnormal = contains_any(text, ABNORMAL_TERMS)
    has_impact = contains_any(text, IMPACT_TERMS)
    has_benign = contains_any(text, BENIGN_PHRASES)
    has_rule_match = any(pattern.search(text) for pattern in rule_patterns)
    is_ordinary_pattern = any(pattern.search(text) for pattern in ORDINARY_EVENT_PATTERNS)
    is_duplicate = count >= duplicate_threshold or (total > 0 and count / total >= 0.35 and count > 1)

    if has_severe:
        return {"actionable": True, "event_type": "key_event", "reason": "severe fault term"}
    if has_benign and not (has_rule_match and has_impact):
        return {"actionable": False, "event_type": "anti_event", "reason": "recoverable or explicitly ignored event"}
    if is_ordinary_pattern and not has_rule_match:
        return {"actionable": False, "event_type": "ordinary_event", "reason": "routine operational template"}
    if has_abnormal and (has_impact or is_warning_error or has_rule_match):
        return {"actionable": True, "event_type": "key_event", "reason": "abnormal term with diagnostic context"}
    if has_rule_match and is_warning_error:
        return {"actionable": True, "event_type": "key_event", "reason": "matches diagnosis rule after level filtering"}
    if has_impact and is_warning_error:
        return {"actionable": True, "event_type": "key_event", "reason": "warning/error affects a diagnostic component"}
    if is_duplicate:
        return {"actionable": False, "event_type": "duplicative_event", "reason": "high-frequency duplicate without fault terms"}
    return {"actionable": False, "event_type": "ordinary_event", "reason": "no actionable fault signal"}


def contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def runtime_actionable_event_count(events: dict[str, Any]) -> int:
    """Return actionable warning/error count with fallback for old runtime JSON."""

    explicit = events.get("actionable_warning_error_count")
    if explicit is not None:
        return safe_int(explicit)

    total = 0
    saw_bucket = False
    for name, bucket in event_buckets(events).items():
        saw_bucket = True
        total += event_bucket_actionable_count(name, bucket)
    if saw_bucket:
        return total
    return safe_int(events.get("total_warning_error_count", 0))


def event_bucket_actionable_count(
    name: str,
    bucket: dict[str, Any],
    rule_patterns: Iterable[re.Pattern[str]] | None = None,
) -> int:
    if not isinstance(bucket, dict):
        return 0
    explicit = bucket.get("actionable_count")
    if explicit is not None:
        return safe_int(explicit)
    profile = bucket.get("noise_reduction")
    if isinstance(profile, dict) and "actionable_event_count" in profile:
        return safe_int(profile.get("actionable_event_count"))

    samples = bucket.get("samples", [])
    if isinstance(samples, list) and samples:
        patterns = list(rule_patterns or bucket_rule_patterns(name, bucket))
        entries = [sample_to_entry(sample) for sample in samples]
        return safe_int(build_log_noise_profile(entries, rule_patterns=patterns).get("actionable_event_count"))

    raw_total = safe_int(bucket.get("total_count"))
    if raw_total <= 0:
        raw_total = safe_int(bucket.get("error_count")) + safe_int(bucket.get("warning_count"))
    if raw_total <= 0:
        return 0
    return 1 if raw_total >= 4 else raw_total


def sample_is_actionable(
    sample: Any,
    *,
    rule_patterns: Iterable[re.Pattern[str]] | None = None,
) -> bool:
    entry = sample_to_entry(sample)
    profile = build_log_noise_profile([entry], rule_patterns=list(rule_patterns or []))
    return safe_int(profile.get("actionable_event_count")) > 0


def sample_to_entry(sample: Any) -> dict[str, Any]:
    if isinstance(sample, dict):
        return {
            "message": sample.get("message_excerpt") or sample.get("message") or sample.get("Content") or "",
            "template": sample.get("event_template") or sample.get("EventTemplate") or "",
            "event_id": sample.get("event_id") or sample.get("EventId") or "",
            "level": sample.get("level") or sample.get("Level") or "",
            "component": sample.get("provider") or sample.get("Component") or sample.get("source") or "",
        }
    return {"message": str(sample)}


def event_buckets(events: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: value
        for key, value in events.items()
        if isinstance(value, dict) and key not in {"collection", "noise_reduction"}
    }


def bucket_rule_patterns(name: str, bucket: dict[str, Any]) -> list[re.Pattern[str]]:
    tokens = [str(name)]
    rules = bucket.get("rules", {}) if isinstance(bucket.get("rules"), dict) else {}
    tokens.extend(str(item) for item in rules.get("provider_patterns", []) if item)
    tokens.extend(str(item) for item in rules.get("message_patterns", []) if item)
    return [
        re.compile(re.escape(token), re.IGNORECASE)
        for token in tokens
        if token.strip()
    ]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
