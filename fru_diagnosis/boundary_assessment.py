"""Hardware/software boundary assessment for electronic-device diagnosis."""

from __future__ import annotations

from typing import Any

from .crash_dump_evidence import crash_dump_is_available


SOFTWARE_CLASSES = {
    "driver_fault",
    "os_fault",
    "configuration_fault",
    "data_or_filesystem_fault",
}
HARDWARE_CLASSES = {"hardware_fault"}
FIRMWARE_CLASSES = {"firmware_fault"}
EXTERNAL_CLASSES = {"external_environment_fault"}


def assess_boundary(
    runtime: dict[str, Any],
    classification: dict[str, Any],
    top_candidates: list[dict[str, Any]] | None = None,
    symptoms: list[str] | None = None,
) -> dict[str, Any]:
    """Classify whether current evidence is software-side, hardware-side, boundary, or uncertain."""

    top_candidates = top_candidates or []
    symptoms = symptoms or []
    text = stringify_evidence(
        {
            "events": runtime.get("events", {}),
            "device_inventory": runtime.get("device_inventory", {}),
            "tests": runtime.get("tests", {}),
            "crash_dump": runtime.get("crash_dump", {}),
            "storage": runtime.get("storage", {}),
            "memory": runtime.get("memory", {}),
            "network": runtime.get("network", {}),
            "power": runtime.get("power", {}),
            "battery": runtime.get("battery", {}),
            "thermal": runtime.get("thermal", {}),
            "metrics": runtime.get("metrics", {}),
            "symptoms": symptoms,
        }
    ).casefold()
    supporting: list[dict[str, Any]] = []
    conflicting: list[dict[str, Any]] = []
    missing: list[str] = []

    software_score = score_from_classification(classification, SOFTWARE_CLASSES)
    hardware_score = score_from_classification(classification, HARDWARE_CLASSES)
    firmware_score = score_from_classification(classification, FIRMWARE_CLASSES)
    external_score = score_from_classification(classification, EXTERNAL_CLASSES)
    interface_score = 0.0
    quality = source_quality(runtime)

    software_hits = match_tokens(
        text,
        [
            "driver",
            "service control",
            "kernel",
            "stack",
            "ndis",
            "appcrash",
            "ntfs",
            "filesystem",
            "file system",
            "low disk",
            "policy",
            "configuration",
            "power plan",
        ],
    )
    firmware_hits = match_tokens(text, ["bios", "firmware", "acpi", "ec", "ucsi", "secure boot"])
    hardware_hits = match_tokens(
        text,
        [
            "smart",
            "whea",
            "memory",
            "nvme",
            "disk failure",
            "bad block",
            "problem_device_count",
            "not_detected",
            "predicted_failure",
        ],
    )
    interface_hits = match_tokens(
        text,
        [
            "pcie",
            "usb",
            "sata",
            "i2c",
            "nvme",
            "ucsi",
            "descriptor request failed",
            "code 43",
            "disconnect",
            "reconnect",
            "link down",
            "connector",
            "adapter",
        ],
    )
    failed_tests = count_failed_values(runtime.get("tests", {}))
    if failed_tests:
        hardware_score += 0.35 * quality["active_tests"]
        hardware_hits.append(f"failed_active_tests={failed_tests}")
    if has_positive_count(runtime.get("device_inventory", {}), {"problem_device_count"}):
        hardware_score += 0.25 * quality["inventory"]
        interface_score += 0.2 * quality["inventory"]
        interface_hits.append("problem_device_count")
    if crash_dump_is_available(runtime.get("crash_dump")):
        software_score += 0.15 * quality["crash_dump"]
        missing.append("compare dump stack with hardware telemetry")
    if software_hits:
        software_score += min(0.45, len(software_hits) * 0.12 * quality["logs"])
        supporting.append({"side": "software", "evidence": software_hits[:5]})
    if firmware_hits:
        firmware_score += min(0.45, len(firmware_hits) * 0.14 * max(quality["logs"], quality["inventory"]))
        supporting.append({"side": "firmware_control", "evidence": firmware_hits[:5]})
    if hardware_hits:
        hardware_score += min(0.55, len(hardware_hits) * 0.14 * max(quality["metrics"], quality["inventory"], quality["active_tests"]))
        supporting.append({"side": "hardware", "evidence": hardware_hits[:5]})
    if interface_hits:
        interface_score += min(
            0.55,
            len(interface_hits)
            * 0.12
            * max(quality["metrics"], quality["inventory"], quality["active_tests"], quality["logs"]),
        )
        supporting.append({"side": "interface_path", "evidence": interface_hits[:5]})

    explicit_boundary = runtime.get("boundary", {}) if isinstance(runtime.get("boundary"), dict) else {}
    explicit_scores = explicit_boundary.get("scores", {}) if isinstance(explicit_boundary.get("scores"), dict) else {}
    software_score += float(explicit_scores.get("software_side", 0.0) or 0.0) * 0.3
    firmware_score += float(explicit_scores.get("firmware_control", 0.0) or 0.0) * 0.3
    hardware_score += float(explicit_scores.get("hardware_endpoint", 0.0) or 0.0) * 0.3
    interface_score += float(explicit_scores.get("interface_path", 0.0) or 0.0) * 0.3
    external_score += float(explicit_scores.get("external_environment", 0.0) or 0.0) * 0.3

    candidate_roles = [str(item.get("boundary_role", "")) for item in top_candidates[:5]]
    if "hardware_endpoint" in candidate_roles:
        hardware_score += 0.15
    if "interface_path" in candidate_roles:
        interface_score += 0.15
    if any(role in {"software_side", "firmware_control"} for role in candidate_roles):
        software_score += 0.15
    if any(item.get("candidate_type") == "non_fru_fault" for item in top_candidates[:3]):
        software_score += 0.15
    if any(item.get("candidate_type") != "non_fru_fault" and item.get("status") in {"suspect", "possible"} for item in top_candidates[:3]):
        hardware_score += 0.15

    boundary_score = 0.0
    if software_score > 0 and hardware_score > 0:
        boundary_score += min(0.85, (software_score + hardware_score) / 2)
    if firmware_score > 0 and hardware_score > 0:
        boundary_score += 0.25
    if interface_score > 0 and (software_score > 0 or firmware_score > 0 or hardware_score > 0):
        boundary_score += 0.25
    boundary_score = min(boundary_score, 1.0)

    if not supporting and max(software_score, hardware_score, firmware_score, external_score) < 0.25:
        boundary_type = "mixed_or_uncertain"
        confidence = 0.2
        reason = "Only weak symptom or inventory context is available; boundary attribution is not reliable yet."
        missing.extend(["fault-window logs", "active hardware tests", "driver and firmware state"])
    elif boundary_score >= 0.45:
        boundary_type = "hardware_software_boundary"
        confidence = round(min(0.92, max(boundary_score, 0.55)), 2)
        reason = "Evidence spans software/firmware control and hardware or interface-path signals."
        if software_score > hardware_score + 0.25:
            conflicting.append({"side": "software", "note": "Software evidence is stronger than hardware evidence."})
        elif hardware_score > software_score + 0.25:
            conflicting.append({"side": "hardware", "note": "Hardware evidence is stronger than software evidence."})
        missing.extend(["targeted boundary isolation test", "confirmatory active hardware test"])
    elif hardware_score >= max(software_score, firmware_score, external_score) + 0.2:
        boundary_type = "hardware_side"
        confidence = round(min(0.9, max(hardware_score, 0.45)), 2)
        reason = "Current evidence is dominated by hardware health, device-state, or failed active-test signals."
        if software_score:
            conflicting.append({"side": "software", "note": "Some software context exists but is weaker."})
        missing.append("confirm hardware failure before service action")
    elif software_score >= max(hardware_score, firmware_score, external_score) + 0.15:
        boundary_type = "software_side"
        confidence = round(min(0.88, max(software_score, 0.45)), 2)
        reason = "Current evidence is dominated by driver, OS, configuration, or filesystem context without hardware confirmation."
        if hardware_score:
            conflicting.append({"side": "hardware", "note": "Some hardware context exists but is weaker."})
        missing.append("exclude hardware path with low-risk active test")
    elif external_score > 0:
        boundary_type = "mixed_or_uncertain"
        confidence = round(min(0.65, external_score), 2)
        reason = "External environment evidence is present; isolate environment before assigning software or hardware root cause."
        missing.append("controlled external-environment retest")
    else:
        boundary_type = "mixed_or_uncertain"
        confidence = 0.35
        reason = "Evidence directions are close or incomplete."
        missing.extend(["fault-window logs", "active tests"])

    posterior = boundary_posterior(
        software_score,
        firmware_score,
        interface_score,
        hardware_score,
        external_score,
    )
    conflict_score = min(
        1.0,
        posterior["software_side"] + posterior["firmware_control"]
        if posterior["hardware_endpoint"] + posterior["interface_path"] > 0.2
        else 0.0,
    )
    if conflict_score > 0.35 and boundary_type != "mixed_or_uncertain":
        confidence = round(float(confidence) * 0.9, 2)
        conflicting.append({"side": "cross_layer", "note": "Software/control and physical-path evidence are both material."})
    if evidence_coverage(quality) < 0.25:
        confidence = round(min(float(confidence), 0.5), 2)
        missing.append("independent non-log evidence")

    return {
        "task": "boundary_assessment",
        "boundary_type": boundary_type,
        "confidence": confidence,
        "supporting_evidence": supporting,
        "conflicting_evidence": conflicting,
        "missing_evidence": unique_list(missing),
        "reason": reason,
        "next_best_boundary_test": next_boundary_test(boundary_type, symptoms, text),
        "posterior": posterior,
        "conflict_score": round(conflict_score, 3),
        "source_quality": quality,
        "evidence_coverage": round(evidence_coverage(quality), 3),
        "scores": {
            "software_side": round(min(software_score, 1.0), 3),
            "hardware_side": round(min(hardware_score, 1.0), 3),
            "interface_path": round(min(interface_score, 1.0), 3),
            "firmware_control": round(min(firmware_score, 1.0), 3),
            "external_environment": round(min(external_score, 1.0), 3),
            "boundary": round(boundary_score, 3),
        },
    }


def source_quality(runtime: dict[str, Any]) -> dict[str, float]:
    """Return bounded quality gates, defaulting conservatively for raw runtime data."""

    supplied = runtime.get("quality", {}) if isinstance(runtime.get("quality"), dict) else {}
    sections = {
        "logs": runtime.get("events") or runtime.get("logs"),
        "metrics": runtime.get("metrics") or runtime.get("storage") or runtime.get("memory") or runtime.get("thermal"),
        "inventory": runtime.get("device_inventory"),
        "active_tests": runtime.get("tests"),
        "crash_dump": runtime.get("crash_dump"),
    }
    result = {}
    for name, value in sections.items():
        raw = supplied.get(name) if name in supplied else (1.0 if has_content(value) else 0.0)
        try:
            result[name] = round(max(0.0, min(1.0, float(raw))), 4)
        except (TypeError, ValueError):
            result[name] = 0.0
    return result


def evidence_coverage(quality: dict[str, float]) -> float:
    present = [value for value in quality.values() if value > 0]
    return sum(present) / len(quality) if quality else 0.0


def boundary_posterior(
    software: float,
    firmware: float,
    interface: float,
    hardware: float,
    external: float,
) -> dict[str, float]:
    values = {
        "software_side": max(0.0, software),
        "firmware_control": max(0.0, firmware),
        "hardware_endpoint": max(0.0, hardware),
        "interface_path": max(0.0, interface),
        "external_environment": max(0.0, external),
    }
    total = sum(values.values())
    if total <= 0:
        return {key: 0.0 for key in values}
    return {key: round(value / total, 4) for key, value in values.items()}


def has_content(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(has_content(item) for item in value)
    return value not in {None, "", "unknown", "not_run", "not_available"}


def score_from_classification(classification: dict[str, Any], classes: set[str]) -> float:
    score = 0.0
    for item in classification.get("class_ranking", []) or []:
        if item.get("fault_class") in classes:
            try:
                score = max(score, float(item.get("score", 0.0) or 0.0))
            except (TypeError, ValueError):
                pass
    if classification.get("predicted_fault_class") in classes:
        score = max(score, 0.35)
    return score


def next_boundary_test(boundary_type: str, symptoms: list[str], text: str) -> str:
    symptom_set = {str(item).casefold() for item in symptoms}
    if "bsod" in symptom_set or "bugcheck" in text:
        return "collect_minidump_and_correlate_with_whea_driver_storage_events"
    if "charging_failure" in symptom_set or "ucsi" in text or "acpi" in text:
        return "run_known_good_adapter_test_and_collect_acpi_ucsi_battery_state"
    if "black_screen" in symptom_set or "display" in text:
        return "run_external_display_test_and_compare_driver_event_timeline"
    if "no_network" in symptom_set or "ndis" in text:
        return "run_gateway_ping_driver_state_and_hotspot_comparison"
    if boundary_type == "hardware_side":
        return "run_confirmatory_hardware_active_test"
    if boundary_type == "software_side":
        return "rollback_or_update_driver_then_retest_symptom"
    return "collect_fault_window_logs_and_run_low_risk_active_tests"


def match_tokens(text: str, tokens: list[str]) -> list[str]:
    return [token for token in tokens if token in text]


def stringify_evidence(value: Any) -> str:
    if isinstance(value, dict):
        pieces = []
        for key, item in value.items():
            text = stringify_evidence(item)
            if text:
                pieces.append(f"{key} {text}")
        return " ".join(pieces)
    if isinstance(value, list):
        return " ".join(stringify_evidence(item) for item in value)
    if value in {None, ""}:
        return ""
    return str(value)


def count_failed_values(value: Any) -> int:
    if isinstance(value, dict):
        return sum(count_failed_values(item) for item in value.values())
    if isinstance(value, list):
        return sum(count_failed_values(item) for item in value)
    return 1 if str(value).casefold() in {"failed", "fail", "error", "abnormal", "not_detected", "predicted_failure"} else 0


def has_positive_count(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in keys:
                try:
                    if int(item or 0) > 0:
                        return True
                except (TypeError, ValueError):
                    pass
            if has_positive_count(item, keys):
                return True
    if isinstance(value, list):
        return any(has_positive_count(item, keys) for item in value)
    return False


def unique_list(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def boundary_role_for_candidate(candidate: dict[str, Any]) -> tuple[str, str]:
    candidate_type = str(candidate.get("candidate_type", ""))
    category = str(candidate.get("category", "")).casefold()
    fru_id = str(candidate.get("fru_id", "")).casefold()
    if candidate_type == "non_fru_fault":
        if "firmware" in category or "config" in category or "firmware" in fru_id:
            return "firmware_control", "Candidate points to firmware, ACPI, or configuration control before hardware replacement."
        if "external" in category or "environment" in fru_id:
            return "external_environment", "Candidate points to external environment or peripheral conditions."
        return "software_side", "Candidate is a software, driver, OS, data, or configuration explanation."
    if any(token in fru_id or token in category for token in ["connector", "interconnect", "usb", "pcie", "io", "adapter"]):
        return "interface_path", "Candidate sits on the interface path between software control and hardware endpoint."
    if any(token in fru_id or token in category for token in ["motherboard", "memory", "storage", "battery", "display", "wlan", "power"]):
        return "hardware_endpoint", "Candidate is a physical hardware endpoint or serviceable assembly."
    return "hardware_endpoint", "Candidate is represented as a serviceability object in the hardware path."
