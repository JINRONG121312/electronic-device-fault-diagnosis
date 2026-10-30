"""Build dashboard payloads for the fault-diagnosis research interface."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .anomaly_detection import detect_anomalies
from .diagnosis_engine import build_diagnosis_report
from .diagnostic_workflow import build_system_health
from .health_assessment import assess_device_health


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "configs" / "active_device.json"
DEFAULT_RUNTIME_PATH = PROJECT_ROOT / "data" / "runtime_info.json"
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "knowledge" / "fru_signal_catalog.json"
DEFAULT_SETUP_REPORT_PATH = PROJECT_ROOT / "reports" / "fru_profile_setup_report.json"
DEFAULT_FRU_ZH_PATH = PROJECT_ROOT / "knowledge" / "fru_zh_explanations.json"


def build_dashboard_payload(
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    runtime_path: str | Path = DEFAULT_RUNTIME_PATH,
    catalog_path: str | Path = DEFAULT_CATALOG_PATH,
    setup_report_path: str | Path = DEFAULT_SETUP_REPORT_PATH,
    fru_zh_path: str | Path = DEFAULT_FRU_ZH_PATH,
) -> dict[str, Any]:
    """Return the combined data used by the interactive dashboard."""

    profile = read_json(profile_path, default={})
    runtime = read_json(runtime_path, default={})
    catalog = read_json(catalog_path, default={})
    setup_report = read_json(setup_report_path, default={})
    fru_zh = read_json(fru_zh_path, default={})

    target_frus = get_target_frus(profile)
    coverage = build_profile_signal_coverage(runtime, catalog, target_frus)
    coverage_summary = summarize_coverage(coverage)
    collection_plan = build_collection_plan(target_frus, coverage, catalog)
    collection_readiness = summarize_collection_plan(collection_plan)
    diagnosis = build_diagnosis_report(profile, runtime, coverage, collection_plan)
    anomaly = detect_anomalies(runtime)
    health = assess_device_health(runtime, anomaly)
    categories = Counter(fru.get("category", "Unknown") for fru in target_frus)
    verification = Counter(
        fru.get("verification_status", "unknown") for fru in target_frus
    )
    event_buckets = summarize_event_buckets(runtime.get("events", {}))

    platform = infer_platform(profile, runtime)
    evidence_layers = build_evidence_layers(runtime)

    return {
        "profile": profile,
        "runtime": runtime,
        "catalog": catalog,
        "setup_report": setup_report,
        "fru_zh_explanations": fru_zh,
        "platform": platform,
        "evidence_layers": evidence_layers,
        "anomaly_detection": anomaly,
        "health_assessment": health,
        "system_health": build_system_health(anomaly, health),
        "diagnosis": diagnosis,
        "collection_plan": collection_plan,
        "collection_readiness": collection_readiness,
        "target_frus": [
            enrich_fru_for_dashboard(
                fru,
                coverage.get(str(fru.get("id", "")), {}),
                catalog,
                fru_zh,
            )
            for fru in target_frus
        ],
        "summary": {
            "device_type": profile.get("device_type", "-"),
            "display_name": profile.get("display_name", "-"),
            "profile_version": profile.get("version", "-"),
            "generated_at": runtime.get("generated_at", "-"),
            "window_hours": runtime.get("window_hours", "-"),
            "target_fru_count": len(target_frus),
            "problem_device_count": runtime.get("device_inventory", {}).get(
                "problem_device_count", 0
            ),
            "total_warning_error_count": runtime.get("events", {}).get(
                "total_warning_error_count", 0
            ),
            "event_collection": runtime.get("events", {}).get("collection", {}),
            "category_counts": dict(sorted(categories.items())),
            "verification_counts": dict(sorted(verification.items())),
            "event_buckets": event_buckets,
            "signal_coverage": coverage_summary,
            "collection_readiness": collection_readiness,
            "diagnosis": diagnosis.get("summary", {}),
            "health": {
                "score": health.get("health_score", 0),
                "level": health.get("health_level", "unknown"),
                "description": health.get("description", ""),
                "maintenance_cadence": health.get("maintenance_strategy", {}).get("cadence", "-"),
                "needs_follow_up_count": len(
                    health.get("maintenance_strategy", {}).get("follow_up_diagnostics", [])
                ),
                "urgent_action_count": len(
                    health.get("maintenance_strategy", {}).get("immediate_actions", [])
                ),
            },
            "source_files": {
                "profile": relative_path(profile_path),
                "runtime": relative_path(runtime_path),
                "catalog": relative_path(catalog_path),
                "setup_report": relative_path(setup_report_path),
            },
        },
        "metrics": extract_metric_sections(runtime),
    }


def infer_platform(profile: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    system = runtime.get("system", {})
    os_caption = str(system.get("os_caption", "") or "")
    os_version = str(system.get("os_version", "") or "")
    if "windows" in os_caption.casefold() or os_version.startswith("10."):
        os_family = "windows"
    elif "linux" in os_caption.casefold():
        os_family = "linux"
    elif os_caption:
        os_family = "other"
    else:
        os_family = "unknown"

    return {
        "device_type": profile.get("device_type", "unknown"),
        "os_family": os_family,
        "os_caption": os_caption or "-",
        "os_version": os_version or "-",
        "manufacturer": system.get("manufacturer", "-"),
        "model": system.get("model", "-"),
        "collector_profile": f"{profile.get('device_type', 'device')}.{os_family}",
    }


def build_evidence_layers(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    events = runtime.get("events", {})
    tests = runtime.get("tests", {})
    collection_status = runtime.get("collection_status", {}) if isinstance(runtime.get("collection_status"), dict) else {}
    return [
        {
            "id": "inventory",
            "name": "设备清单层",
            "description": "识别模块是否存在、驱动是否枚举、PnP/总线是否报错。",
            "records": count_inventory_records(runtime),
            "status": evidence_layer_status(
                bool(runtime.get("device_inventory") or runtime.get("system")),
                collection_status,
                {"inventory.pnp_devices", "system.computer", "system.os"},
            ),
        },
        {
            "id": "metrics",
            "name": "运行指标层",
            "description": "采集电源、存储、内存、网络、温度、性能等连续或状态指标。",
            "records": count_metric_records(runtime),
            "status": evidence_layer_status(
                bool(runtime),
                collection_status,
                {
                    "battery.win32_battery",
                    "storage.disk_drive",
                    "memory.physical_memory",
                    "network.adapters",
                    "thermal.acpi_zones",
                },
            ),
        },
        {
            "id": "logs",
            "name": "日志事件层",
            "description": "把系统日志映射到软件、固件、环境和硬件边界相关的证据桶。",
            "records": int(events.get("total_warning_error_count", 0) or 0),
            "status": evidence_layer_status(bool(events), collection_status, {"logs.system", "logs.application"}),
        },
        {
            "id": "active_tests",
            "name": "主动测试层",
            "description": "补充无法由操作系统被动观测的屏幕、扬声器、LED、接口等测试。",
            "records": count_active_test_records(tests),
            "status": layer_status(bool(tests)),
        },
    ]


def count_inventory_records(runtime: dict[str, Any]) -> int:
    sections = [
        runtime.get("storage", {}).get("drives", []),
        runtime.get("memory", {}).get("modules", []),
        runtime.get("network", {}).get("adapters", []),
        runtime.get("display", {}).get("adapters", []),
        runtime.get("display", {}).get("monitors", []),
        runtime.get("input", {}).get("keyboards", []),
        runtime.get("input", {}).get("touchpad_devices", []),
        runtime.get("camera", {}).get("devices", []),
        runtime.get("audio", {}).get("devices", []),
        runtime.get("usb", {}).get("controllers", []),
    ]
    return sum(len(section) for section in sections if isinstance(section, list))


def count_metric_records(runtime: dict[str, Any]) -> int:
    metric_sections = [
        "battery",
        "power",
        "storage",
        "memory",
        "network",
        "display",
        "thermal",
        "performance",
    ]
    count = 0
    for section in metric_sections:
        value = runtime.get(section)
        if isinstance(value, dict):
            count += len(value)
    return count


def count_active_test_records(tests: dict[str, Any]) -> int:
    count = 0
    for group in tests.values():
        if isinstance(group, dict):
            count += len(group)
    return count


def layer_status(has_data: bool) -> str:
    return "ready" if has_data else "missing"


def evidence_layer_status(
    has_data: bool,
    collection_status: dict[str, Any],
    sources: set[str],
) -> str:
    if any(
        isinstance(collection_status.get(source), dict)
        and collection_status[source].get("status") == "failed"
        for source in sources
    ):
        return "failed"
    return layer_status(has_data)


def enrich_fru_for_dashboard(
    fru: dict[str, Any],
    coverage: dict[str, Any],
    catalog: dict[str, Any],
    fru_zh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fru_id = str(fru.get("id", ""))
    catalog_item = find_catalog_item(catalog, fru_id)
    zh_explanation = get_fru_zh_explanation(fru_zh or {}, fru)
    serviceability = normalize_serviceability(fru)
    return {
        **fru,
        "serviceability": serviceability,
        "zh_explanation": zh_explanation,
        "coverage": coverage,
        "signals": {
            "required": enrich_signals(
                catalog_item.get("required", []), coverage.get("required_keys", set())
            ),
            "enhancing": enrich_signals(
                catalog_item.get("enhancing", []), coverage.get("enhancing_keys", set())
            ),
            "active_test": enrich_signals(
                catalog_item.get("active_test", []), coverage.get("active_test_keys", set())
            ),
        },
        "replacement_limitations": catalog_item.get("replacement_limitations", []),
        "collection_plan": build_fru_collection_plan(fru, coverage, catalog_item),
    }


def get_fru_zh_explanation(fru_zh: dict[str, Any], fru: dict[str, Any]) -> dict[str, Any]:
    fru_id = str(fru.get("id", ""))
    explanations = fru_zh.get("fru_explanations", {})
    if not isinstance(explanations, dict):
        return build_generic_zh_explanation(fru)
    explanation = explanations.get(fru_id, {})
    if isinstance(explanation, dict) and explanation:
        return explanation
    return build_generic_zh_explanation(fru)


def build_generic_zh_explanation(fru: dict[str, Any]) -> dict[str, str]:
    category = str(fru.get("category", "OtherFRU"))
    name = str(fru.get("name", "") or fru.get("id", "") or "FRU 模块")
    category_zh = {
        "PowerFRU": "电源/电池模块",
        "ComputeFRU": "计算/内存模块",
        "StorageFRU": "存储模块",
        "CommunicationFRU": "通信模块",
        "ThermalFRU": "散热模块",
        "DisplayFRU": "显示模块",
        "InputFRU": "输入模块",
        "InterfaceFRU": "接口模块",
        "SensorFRU": "传感器模块",
        "MainboardFRU": "主板模块",
        "OtherFRU": "其他服务性对象",
    }.get(category, "服务性对象")
    return {
        "name_zh": name,
        "category_zh": category_zh,
        "brief": f"{name} 是扫描识别到的{category_zh}，当前按自定义诊断画像参与故障诊断。",
    }


def enrich_signals(
    signals: list[dict[str, Any]], present_keys: set[str]
) -> list[dict[str, Any]]:
    return [{**signal, "present": signal.get("key") in present_keys} for signal in signals]


def build_signal_coverage(
    runtime: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for item in catalog.get("fru_signals", []):
        fru_id = str(item.get("fru_id", ""))
        coverage[fru_id] = build_signal_coverage_for_item(runtime, item)
    return coverage


def build_profile_signal_coverage(
    runtime: dict[str, Any],
    catalog: dict[str, Any],
    target_frus: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build coverage for the current profile, with category fallback templates."""

    coverage: dict[str, dict[str, Any]] = {}
    for fru in target_frus:
        fru_id = str(fru.get("id", ""))
        catalog_item = resolve_catalog_item_for_fru(catalog, fru)
        coverage[fru_id] = build_signal_coverage_for_item(runtime, catalog_item)
        coverage[fru_id]["catalog_fru_id"] = catalog_item.get("fru_id", "")
        coverage[fru_id]["catalog_match"] = (
            "exact" if catalog_item.get("fru_id") == fru_id else "fallback"
        )
    return coverage


def build_signal_coverage_for_item(
    runtime: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    required = item.get("required", [])
    enhancing = item.get("enhancing", [])
    active_test = item.get("active_test", [])
    required_keys = present_signal_keys(runtime, required)
    enhancing_keys = present_signal_keys(runtime, enhancing)
    active_test_keys = present_signal_keys(runtime, active_test)
    missing_required = missing_signals(required, required_keys)
    missing_enhancing = missing_signals(enhancing, enhancing_keys)
    missing_active_test = missing_signals(active_test, active_test_keys)
    required_total = len(required)
    required_present = len(required_keys)
    enhancing_total = len(enhancing)
    enhancing_present = len(enhancing_keys)
    active_total = len(active_test)
    active_present = len(active_test_keys)
    weighted_total = required_total * 3 + enhancing_total + active_total * 2
    weighted_present = required_present * 3 + enhancing_present + active_present * 2
    score = int(round((weighted_present / weighted_total) * 100)) if weighted_total else 0

    if required_total and required_present == required_total and active_total and active_present == active_total:
        readiness = "ready"
    elif required_total and required_present == required_total:
        readiness = "passive_ready"
    elif required_present > 0 or enhancing_present > 0 or active_present > 0:
        readiness = "partial"
    else:
        readiness = "missing"

    return {
        "required_present": required_present,
        "required_total": required_total,
        "enhancing_present": enhancing_present,
        "enhancing_total": enhancing_total,
        "active_test_present": active_present,
        "active_test_total": active_total,
        "required_keys": required_keys,
        "enhancing_keys": enhancing_keys,
        "active_test_keys": active_test_keys,
        "missing_required": missing_required,
        "missing_enhancing": missing_enhancing,
        "missing_active_test": missing_active_test,
        "score": score,
        "readiness": readiness,
    }


def present_signal_keys(runtime: dict[str, Any], signals: list[dict[str, Any]]) -> set[str]:
    return {
        str(signal.get("key", ""))
        for signal in signals
        if get_nested(runtime, str(signal.get("key", ""))) is not None
    }


def missing_signals(
    signals: list[dict[str, Any]],
    present_keys: set[str],
) -> list[dict[str, Any]]:
    return [
        signal
        for signal in signals
        if str(signal.get("key", "")) not in present_keys
    ]


def summarize_coverage(coverage: dict[str, dict[str, Any]]) -> dict[str, int]:
    required_present = sum(item.get("required_present", 0) for item in coverage.values())
    required_total = sum(item.get("required_total", 0) for item in coverage.values())
    enhancing_present = sum(item.get("enhancing_present", 0) for item in coverage.values())
    enhancing_total = sum(item.get("enhancing_total", 0) for item in coverage.values())
    active_test_present = sum(item.get("active_test_present", 0) for item in coverage.values())
    active_test_total = sum(item.get("active_test_total", 0) for item in coverage.values())
    score_values = [int(item.get("score", 0) or 0) for item in coverage.values()]
    return {
        "required_present": required_present,
        "required_total": required_total,
        "enhancing_present": enhancing_present,
        "enhancing_total": enhancing_total,
        "active_test_present": active_test_present,
        "active_test_total": active_test_total,
        "average_score": round(sum(score_values) / len(score_values), 1) if score_values else 0,
    }


def get_target_frus(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fru
        for fru in profile.get("fru_list", [])
        if is_serviceability_target(fru)
    ]


def is_serviceability_target(fru: dict[str, Any]) -> bool:
    if fru.get("diagnosis_role") != "target_fru":
        return False
    serviceability = normalize_serviceability(fru)
    return serviceability.get("type") in {
        "replaceable_fru",
        "serviceable_assembly",
        "external_part",
    }


def normalize_serviceability(fru: dict[str, Any]) -> dict[str, Any]:
    raw = fru.get("serviceability")
    if isinstance(raw, dict):
        service_type = raw.get("type") or default_serviceability_type_for_fru(fru)
        return {
            "type": service_type,
            "level": raw.get("level") or default_serviceability_level(service_type),
            "replacement_target": raw.get("replacement_target") or (
                fru.get("id") if service_type in {"replaceable_fru", "serviceable_assembly"} else None
            ),
            "parent_assembly": raw.get("parent_assembly"),
            "requires_disassembly": bool(raw.get("requires_disassembly", True)),
            "cost_level": raw.get("cost_level", "unknown"),
            "confidence_required": raw.get("confidence_required", "high"),
            "action": raw.get("action") or default_service_action(service_type, str(fru.get("id", ""))),
            "notes": raw.get("notes", []),
        }

    service_type = default_serviceability_type_for_fru(fru)
    return {
        "type": service_type,
        "level": default_serviceability_level(service_type),
        "replacement_target": fru.get("id") if service_type in {"replaceable_fru", "serviceable_assembly"} else None,
        "parent_assembly": None if fru.get("replaceable") else "motherboard",
        "requires_disassembly": service_type not in {"external_part", "non_fru_fault", "maintenance_condition"},
        "cost_level": "unknown",
        "confidence_required": "high",
        "action": default_service_action(service_type, str(fru.get("id", ""))),
        "notes": [],
    }


def default_serviceability_type_for_fru(fru: dict[str, Any]) -> str:
    if fru.get("diagnosis_role") == "subsystem":
        return "non_replaceable_subsystem"
    if fru.get("replaceable", True):
        return "replaceable_fru"
    return "non_replaceable_subsystem"


def default_serviceability_level(service_type: str) -> str:
    return {
        "replaceable_fru": "field_replaceable",
        "serviceable_assembly": "assembly_replaceable",
        "non_replaceable_subsystem": "not_individually_replaceable",
        "non_fru_fault": "not_replaceable",
        "external_part": "external",
        "maintenance_condition": "not_replaceable",
    }.get(service_type, "field_replaceable")


def default_service_action(service_type: str, fru_id: str) -> str:
    if service_type == "replaceable_fru":
        return f"Replace or reseat {fru_id} after sufficient evidence."
    if service_type == "serviceable_assembly":
        return f"Repair or replace the parent assembly for {fru_id}."
    if service_type == "non_replaceable_subsystem":
        return f"Use {fru_id} as evidence for its parent assembly; do not replace it directly."
    if service_type == "external_part":
        return f"Swap or validate external part {fru_id}."
    return "Do not replace a hardware module before excluding this condition."


def find_catalog_item(catalog: dict[str, Any], fru_id: str) -> dict[str, Any]:
    for item in catalog.get("fru_signals", []):
        if item.get("fru_id") == fru_id:
            return item
    return {}


def resolve_catalog_item_for_fru(
    catalog: dict[str, Any],
    fru: dict[str, Any],
) -> dict[str, Any]:
    exact = find_catalog_item(catalog, str(fru.get("id", "")))
    if exact:
        return exact

    fru_id = str(fru.get("id", ""))
    category = str(fru.get("category", ""))
    aliases = [str(alias) for alias in fru.get("aliases", [])]
    haystack = " ".join(
        [
            fru_id,
            str(fru.get("name", "")),
            str(fru.get("description", "")),
            " ".join(aliases),
        ]
    ).casefold()

    fallback_by_category = {
        "PowerFRU": "battery_pack" if "battery" in haystack else "power_adapter",
        "StorageFRU": "m2_ssd_module",
        "ComputeFRU": "ram_module",
        "CommunicationFRU": "wlan_module",
        "ThermalFRU": "heat_sink" if "sink" in haystack or "heatsink" in haystack else "fan_module",
        "DisplayFRU": "display_panel_module",
        "InputFRU": "touchpad_module" if "touchpad" in haystack or "trackpad" in haystack else "keyboard_module",
        "SensorFRU": "camera_module",
        "InterfaceFRU": "speaker_module" if "speaker" in haystack or "audio" in haystack else "io_board",
        "MainboardFRU": "motherboard",
    }
    fallback_id = fallback_by_category.get(category, "motherboard")
    return find_catalog_item(catalog, fallback_id) or {
        "fru_id": fallback_id,
        "required": [],
        "enhancing": [],
        "active_test": [],
        "replacement_limitations": [],
    }


def build_collection_plan(
    target_frus: list[dict[str, Any]],
    coverage: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    plans = []
    for fru in target_frus:
        fru_id = str(fru.get("id", ""))
        catalog_item = resolve_catalog_item_for_fru(catalog, fru)
        plans.append(build_fru_collection_plan(fru, coverage.get(fru_id, {}), catalog_item))
    return sorted(
        plans,
        key=lambda item: (
            readiness_rank(item.get("readiness", "")),
            item.get("score", 0),
            item.get("fru_id", ""),
        ),
    )


def build_fru_collection_plan(
    fru: dict[str, Any],
    coverage: dict[str, Any],
    catalog_item: dict[str, Any],
) -> dict[str, Any]:
    required = list(catalog_item.get("required", []))
    enhancing = list(catalog_item.get("enhancing", []))
    active_test = list(catalog_item.get("active_test", []))
    missing_required = list(coverage.get("missing_required", required))
    missing_enhancing = list(coverage.get("missing_enhancing", enhancing))
    missing_active_test = list(coverage.get("missing_active_test", active_test))
    present_keys = {
        "required": sorted(coverage.get("required_keys", set())),
        "enhancing": sorted(coverage.get("enhancing_keys", set())),
        "active_test": sorted(coverage.get("active_test_keys", set())),
    }
    return {
        "fru_id": str(fru.get("id", "")),
        "fru_name": fru.get("name", ""),
        "category": fru.get("category", ""),
        "catalog_fru_id": catalog_item.get("fru_id", ""),
        "catalog_match": coverage.get("catalog_match", "exact"),
        "score": int(coverage.get("score", 0) or 0),
        "readiness": coverage.get("readiness", "missing"),
        "required": required,
        "enhancing": enhancing,
        "active_test": active_test,
        "missing_required": missing_required,
        "missing_enhancing": missing_enhancing,
        "missing_active_test": missing_active_test,
        "present_keys": present_keys,
        "next_actions": build_next_collection_actions(
            missing_required,
            missing_enhancing,
            missing_active_test,
        ),
        "source_layers": summarize_source_layers(required + enhancing + active_test),
    }


def build_next_collection_actions(
    missing_required: list[dict[str, Any]],
    missing_enhancing: list[dict[str, Any]],
    missing_active_test: list[dict[str, Any]],
) -> list[dict[str, str]]:
    actions = []
    for signal in missing_required[:4]:
        actions.append(
            {
                "priority": "required",
                "key": str(signal.get("key", "")),
                "source": str(signal.get("source", "")),
                "description": str(signal.get("description", "")),
            }
        )
    for signal in missing_active_test[:3]:
        actions.append(
            {
                "priority": "active_test",
                "key": str(signal.get("key", "")),
                "source": str(signal.get("source", "manual")),
                "description": str(signal.get("description", "")),
            }
        )
    if not actions:
        for signal in missing_enhancing[:3]:
            actions.append(
                {
                    "priority": "enhancing",
                    "key": str(signal.get("key", "")),
                    "source": str(signal.get("source", "")),
                    "description": str(signal.get("description", "")),
                }
            )
    return actions


def summarize_source_layers(signals: list[dict[str, Any]]) -> dict[str, int]:
    layers: Counter[str] = Counter()
    for signal in signals:
        source = str(signal.get("source", "") or "").casefold()
        key = str(signal.get("key", "") or "")
        if key.startswith("tests."):
            layers["active_test"] += 1
        elif "event" in source or "log" in source:
            layers["log"] += 1
        elif any(token in source for token in ["win32", "pnp", "inventory", "cim", "baseboard"]):
            layers["inventory"] += 1
        else:
            layers["metric"] += 1
    return dict(sorted(layers.items()))


def summarize_collection_plan(plans: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(plan.get("readiness", "missing") for plan in plans)
    total = len(plans)
    scores = [int(plan.get("score", 0) or 0) for plan in plans]
    blocked = [
        plan
        for plan in plans
        if plan.get("readiness") in {"missing", "partial"}
    ]
    return {
        "total_fru_count": total,
        "ready_count": counts.get("ready", 0),
        "passive_ready_count": counts.get("passive_ready", 0),
        "partial_count": counts.get("partial", 0),
        "missing_count": counts.get("missing", 0),
        "average_score": round(sum(scores) / total, 1) if total else 0,
        "lowest_score_frus": [
            {
                "fru_id": item.get("fru_id", ""),
                "fru_name": item.get("fru_name", ""),
                "score": item.get("score", 0),
                "readiness": item.get("readiness", ""),
            }
            for item in plans[:5]
        ],
        "blocking_missing_required": sum(
            len(plan.get("missing_required", [])) for plan in blocked
        ),
        "blocking_missing_active_tests": sum(
            len(plan.get("missing_active_test", [])) for plan in blocked
        ),
    }


def readiness_rank(readiness: str) -> int:
    return {
        "missing": 0,
        "partial": 1,
        "passive_ready": 2,
        "ready": 3,
    }.get(readiness, 1)


def summarize_event_buckets(events: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    for key, value in events.items():
        if key in {"total_warning_error_count", "collection"} or not isinstance(value, dict):
            continue
        buckets.append(
            {
                "name": key,
                "error_count": int(value.get("error_count", 0) or 0),
                "warning_count": int(value.get("warning_count", 0) or 0),
                "total_count": int(value.get("total_count", 0) or 0),
                "samples": value.get("samples", []),
                "rules": value.get("rules", {}),
            }
        )
    return sorted(buckets, key=lambda item: item["total_count"], reverse=True)


def extract_metric_sections(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "system": runtime.get("system", {}),
        "bios": runtime.get("bios", {}),
        "mainboard": runtime.get("mainboard", {}),
        "battery": runtime.get("battery", {}),
        "power": runtime.get("power", {}),
        "storage": runtime.get("storage", {}),
        "memory": runtime.get("memory", {}),
        "network": runtime.get("network", {}),
        "display": runtime.get("display", {}),
        "input": runtime.get("input", {}),
        "camera": runtime.get("camera", {}),
        "audio": runtime.get("audio", {}),
        "usb": runtime.get("usb", {}),
        "thermal": runtime.get("thermal", {}),
        "performance": runtime.get("performance", {}),
        "device_inventory": runtime.get("device_inventory", {}),
        "tests": runtime.get("tests", {}),
    }


def set_runtime_test_result(
    key: str,
    value: str,
    runtime_path: str | Path = DEFAULT_RUNTIME_PATH,
) -> dict[str, Any]:
    if not key.startswith("tests."):
        raise ValueError("Only tests.* keys can be updated from the dashboard.")
    if "[]" in key:
        raise ValueError("Array paths are not supported for active-test updates.")

    allowed_values = {"not_run", "passed", "failed", "inconclusive", "not_applicable"}
    if value not in allowed_values:
        raise ValueError(f"Unsupported active-test result: {value}")

    runtime = read_json(runtime_path, default={})
    set_nested(runtime, key.split("."), value)
    write_json(runtime_path, runtime)
    return runtime


def set_nested(data: dict[str, Any], parts: list[str], value: Any) -> None:
    if not parts:
        raise ValueError("Path cannot be empty.")
    current: dict[str, Any] = data
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def get_nested(data: dict[str, Any], key: str) -> Any:
    if not key:
        return None
    values = get_nested_values(data, key.split("."))
    values = [value for value in values if value not in (None, "not_run", "")]
    return values if values else None


def get_nested_values(current: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return [current]

    part = parts[0]
    rest = parts[1:]
    is_array = part.endswith("[]")
    clean_part = part[:-2] if is_array else part

    if not isinstance(current, dict) or clean_part not in current:
        return []

    next_value = current[clean_part]
    if is_array:
        if not isinstance(next_value, list):
            return []
        values: list[Any] = []
        for item in next_value:
            values.extend(get_nested_values(item, rest))
        return values

    return get_nested_values(next_value, rest)


def read_json(path: str | Path, default: Any | None = None) -> Any:
    source = resolve_project_path(path)
    if not source.exists():
        if default is not None:
            return default
        raise FileNotFoundError(source)
    return json.loads(source.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    target = resolve_project_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def relative_path(path: str | Path) -> str:
    resolved = resolve_project_path(path)
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)
