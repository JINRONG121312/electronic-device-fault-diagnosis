"""Remote and cross-machine diagnosis intake."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .active_diagnosis import recommend_next_tests
from .decision_layer import decide_after_classification
from .diagnosis_engine import build_diagnosis_report
from .fault_classification import classify_fault_case


SYMPTOM_KEYWORDS = {
    "bsod": ["蓝屏", "blue screen", "bsod", "死机", "stop code", "bugcheck"],
    "black_screen": ["黑屏", "屏幕不亮", "无显示", "black screen"],
    "charging_failure": ["无法充电", "不充电", "充电失败", "电源", "battery", "charge"],
    "no_network": ["无法联网", "没网", "wifi", "wi-fi", "network", "网卡"],
    "boot_failure": ["无法启动", "开不了机", "启动失败", "boot", "开机失败"],
    "slow_io": ["卡顿", "很慢", "磁盘慢", "slow", "freeze"],
    "random_reboot": ["重启", "自动重启", "random reboot"],
}


SYMPTOM_COLLECTION_GROUPS = {
    "bsod": {
        "id": "crash_dump",
        "name": "Crash and blue-screen evidence",
        "layer": "crash_dump",
        "priority": "high",
        "why": "Stop-code and dump metadata separate driver, OS, memory, storage, and board-level candidates.",
        "items": [
            "BugCheck code, stop code, failure bucket, and crash timestamp",
            "C:\\Windows\\Minidump metadata or MEMORY.DMP metadata when available",
            "WHEA, Kernel-Power, disk, display, and driver events around the crash window",
            "Recently installed or updated drivers, Windows updates, firmware updates, and security software",
        ],
    },
    "black_screen": {
        "id": "display_path",
        "name": "Display-path evidence",
        "layer": "active_tests",
        "priority": "high",
        "why": "Black-screen symptoms require separating panel, backlight, GPU driver, display path, and boot-state faults.",
        "items": [
            "External monitor result and whether BIOS/UEFI setup is visible",
            "Panel backlight, keyboard backlight, fan spin, and CapsLock response",
            "Display driver events, EDID or monitor detection, brightness, and lid-state evidence",
            "Photos or video of the screen state when the machine cannot export logs",
        ],
    },
    "charging_failure": {
        "id": "power_charging",
        "name": "Power and charging evidence",
        "layer": "metrics",
        "priority": "high",
        "why": "Charging faults need evidence across adapter, battery, EC/ACPI/UCSI, connector, and firmware policy.",
        "items": [
            "AC adapter wattage, adapter LED, charging LED, battery percentage, and charge/discharge state",
            "Battery health, cycle count, design capacity, full-charge capacity, voltage, and current readings",
            "ACPI battery events, UCSI/USB-C controller events, BIOS battery health page if available",
            "Known-good adapter, outlet, and USB-C port cross-test results",
        ],
    },
    "no_network": {
        "id": "network_path",
        "name": "Network-path evidence",
        "layer": "active_tests",
        "priority": "medium",
        "why": "Network faults often come from driver, configuration, access point, external environment, or WLAN hardware.",
        "items": [
            "Adapter model, driver version, link state, IP configuration, DNS, gateway, and signal strength",
            "Gateway ping, DNS resolution, wired-vs-wireless comparison, and hotspot comparison",
            "Device Manager or kernel driver state, WLAN service status, and recent driver changes",
            "Bluetooth coexistence result when WLAN and Bluetooth share the same card",
        ],
    },
    "boot_failure": {
        "id": "boot_path",
        "name": "Boot-path evidence",
        "layer": "logs",
        "priority": "high",
        "why": "Boot failures need evidence that separates firmware setup, storage path, bootloader, OS image, and external-device causes.",
        "items": [
            "Exact boot error text, beep or blink code, BIOS storage visibility, and boot order",
            "Windows recovery or Linux boot journal messages if recovery environment is reachable",
            "SSD/NVMe SMART, filesystem check result, and recent disk or OS image changes",
            "Minimal-boot test without external peripherals",
        ],
    },
    "slow_io": {
        "id": "performance_io",
        "name": "Performance and I/O evidence",
        "layer": "metrics",
        "priority": "medium",
        "why": "Slow or freezing symptoms require separating storage degradation, memory pressure, thermal throttling, driver stalls, and background workload.",
        "items": [
            "Disk latency, queue length, SMART warnings, bad blocks, and filesystem errors",
            "CPU load, memory pressure, thermal throttling, fan state, and battery power mode",
            "Recent application installs, updates, antivirus scans, and background service errors",
            "Active read/write, memory, and temperature checks when safe to run",
        ],
    },
}


def build_remote_diagnosis(body: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Build a diagnosis result from customer-visible symptoms and optional remote evidence."""

    intake = normalize_customer_intake(body)
    runtime = build_runtime_from_remote_evidence(body, intake)
    case = build_fault_case(intake, runtime)
    classification = classify_fault_case(case)
    decision = decide_after_classification(classification)
    diagnosis_report = build_diagnosis_report(profile, runtime)
    next_tests = recommend_next_tests(diagnosis_report, intake["symptoms"], limit=5)

    return {
        "ok": True,
        "mode": "remote_cross_machine_diagnosis",
        "intake": intake,
        "classification": classification,
        "decision": decision,
        "next_tests": next_tests,
        "diagnosis_summary": diagnosis_report.get("summary", {}),
        "top_candidates": diagnosis_report.get("top_candidates", []),
        "remote_collection": build_remote_collection_guidance(intake, next_tests),
    }


def normalize_customer_intake(body: dict[str, Any]) -> dict[str, Any]:
    description = str(body.get("description", "") or "").strip()
    symptoms = set(str(item).strip() for item in body.get("symptoms", []) if str(item).strip())
    symptoms.update(infer_symptoms(description))
    return {
        "customer_id": str(body.get("customer_id", "") or "").strip(),
        "device_id": str(body.get("device_id", "") or "").strip(),
        "manufacturer": str(body.get("manufacturer", "") or "").strip(),
        "model": str(body.get("model", "") or "").strip(),
        "os_family": str(body.get("os_family", "") or "").strip().casefold(),
        "fault_time": str(body.get("fault_time", "") or "").strip(),
        "description": description,
        "symptoms": sorted(symptoms) or ["unknown_symptom"],
        "observed_at": datetime.now().isoformat(timespec="seconds"),
    }


def infer_symptoms(description: str) -> set[str]:
    text = description.casefold()
    symptoms = set()
    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        if any(keyword.casefold() in text for keyword in keywords):
            symptoms.add(symptom)
    return symptoms


def build_runtime_from_remote_evidence(body: dict[str, Any], intake: dict[str, Any]) -> dict[str, Any]:
    runtime = parse_runtime_json(body.get("runtime_info"))
    system = dict(runtime.get("system", {})) if isinstance(runtime.get("system"), dict) else {}
    if intake["manufacturer"] and not system.get("manufacturer"):
        system["manufacturer"] = intake["manufacturer"]
    if intake["model"] and not system.get("model"):
        system["model"] = intake["model"]
    if intake["os_family"] and not system.get("os_caption"):
        system["os_caption"] = intake["os_family"]
    runtime["system"] = system
    runtime.setdefault("events", {})
    runtime["events"].setdefault("collection", {})
    if intake["fault_time"]:
        runtime["events"]["collection"]["fault_time"] = intake["fault_time"]
    runtime["customer_intake"] = intake
    return runtime


def parse_runtime_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"remote_parse_error": "runtime_info is not valid JSON"}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_fault_case(intake: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "symptom": intake["symptoms"],
        "evidence": {
            "inventory": {
                "system": runtime.get("system", {}),
                "device_inventory": runtime.get("device_inventory", {}),
            },
            "logs": {"events": runtime.get("events", {})},
            "metrics": {
                "power": runtime.get("power", {}),
                "battery": runtime.get("battery", {}),
                "storage": runtime.get("storage", {}),
                "memory": runtime.get("memory", {}),
                "network": runtime.get("network", {}),
                "thermal": runtime.get("thermal", {}),
            },
            "active_tests": runtime.get("tests", {}),
            "crash_dump": runtime.get("crash_dump", {}),
        },
    }


def build_remote_collection_guidance(
    intake: dict[str, Any],
    next_tests: list[dict[str, Any]],
) -> dict[str, Any]:
    os_family = intake.get("os_family") or "unknown"
    base_actions = [
        "确认设备型号、操作系统版本、故障发生时间和可见症状。",
        "在故障机器上导出 runtime_info.json 后复制到当前诊断机器。",
    ]
    if os_family == "windows" or "bsod" in intake.get("symptoms", []):
        base_actions.append("Windows 故障建议补充事件日志、PnP 设备状态、最近驱动变更和 minidump 元数据。")
    if os_family == "linux":
        base_actions.append("Linux 故障建议补充 journalctl、dmesg、lspci/lsusb、SMART 和 systemd 服务状态。")
    return {
        "scenario": "diagnose_another_machine",
        "base_actions": base_actions,
        "collection_plan": build_cross_machine_collection_plan(intake, "cross_machine_remote"),
        "next_best_tests": [
            {
                "id": test.get("id", ""),
                "name": test.get("name", ""),
                "score": test.get("score", 0),
            }
            for test in next_tests
        ],
    }


def build_cross_machine_collection_plan(intake: dict[str, Any], mode: str) -> dict[str, Any]:
    """Return effective evidence to collect when diagnosing a known-bad peer device."""

    symptoms = set(intake.get("symptoms") or [])
    os_family = str(intake.get("os_family") or "unknown").casefold()
    can_export = mode != "cross_machine_power_off"
    offline_import = mode == "cross_machine_offline"
    groups = [
        {
            "id": "case_context",
            "name": "Case context",
            "layer": "inventory",
            "priority": "high",
            "why": "Model, OS, time, and symptom context anchor every later evidence item to the correct device and fault window.",
            "items": [
                "Manufacturer, model, serial number or asset ID, and device role",
                "OS family, OS version, BIOS/UEFI version, and recent update time if known",
                "Fault occurrence time, recurrence frequency, trigger operation, and whether the fault is reproducible",
                "Customer-visible symptom description using exact on-screen text when available",
            ],
        }
    ]

    if can_export:
        groups.extend(
            [
                {
                    "id": "runtime_bundle",
                    "name": "Runtime evidence bundle",
                    "layer": "inventory",
                    "priority": "high",
                    "why": "A normalized runtime_info.json lets the same anomaly-classification-decision pipeline run on another machine's evidence.",
                    "items": [
                        "runtime_info.json exported from the fault machine",
                        "Hardware inventory, device inventory, problem-device count, driver versions, and firmware versions",
                        "Active test results and repair or maintenance actions already attempted",
                    ],
                },
                {
                    "id": "fault_window_logs",
                    "name": "Fault-window logs",
                    "layer": "logs",
                    "priority": "high",
                    "why": "Logs around the fault timestamp provide temporal evidence instead of generic historical noise.",
                    "items": [
                        "System and application logs from before and after the fault time",
                        "Driver, storage, display, power, kernel, service, and update events",
                        "Event severity, provider, event ID, message excerpt, and timestamp",
                    ],
                },
                {
                    "id": "device_health_metrics",
                    "name": "Device health metrics",
                    "layer": "metrics",
                    "priority": "medium",
                    "why": "Metrics distinguish transient software states from degraded hardware or environmental conditions.",
                    "items": [
                        "SMART/NVMe health, bad block or filesystem errors, temperature, and disk latency",
                        "Battery, adapter, charge state, ACPI/UCSI, CPU, memory, thermal, and fan evidence",
                        "Network, display, storage, and power active-test outputs when safe to collect",
                    ],
                },
            ]
        )
        if offline_import:
            groups.append(
                {
                    "id": "offline_crash_evidence",
                    "name": "Offline crash and event evidence",
                    "layer": "crash_dump",
                    "priority": "high",
                    "why": "Offline files preserve evidence when the fault machine cannot run a live collector reliably.",
                    "items": [
                        "C:\\Windows\\Minidump\\ and C:\\Windows\\MEMORY.DMP metadata from the fault-machine system disk",
                        "System.evtx and Application.evtx from C:\\Windows\\System32\\winevt\\Logs",
                        "Driver list, OS version, recent update records, and SMART/NVMe health exported from WinPE, safe mode, or another host",
                    ],
                }
            )
    else:
        groups.extend(
            [
                {
                    "id": "field_observation",
                    "name": "Field-observable evidence",
                    "layer": "active_tests",
                    "priority": "high",
                    "why": "When the fault machine cannot run the collector, visible signals are the only safe first evidence.",
                    "items": [
                        "Power LED, charging LED, adapter LED, fan spin, beep or blink code, keyboard backlight, and heat or odor",
                        "Exact screen state, error text, vendor logo behavior, and whether BIOS/UEFI setup can be opened",
                        "Photos or short videos of the symptom and all indicator states",
                    ],
                },
                {
                    "id": "external_isolation",
                    "name": "External isolation checks",
                    "layer": "active_tests",
                    "priority": "high",
                    "why": "External power, display, and peripheral checks reduce false hardware-replacement decisions.",
                    "items": [
                        "Known-good adapter, outlet, USB-C port, battery reset path, and power-button hold result",
                        "External display result, minimal-boot result without peripherals, and storage visibility in BIOS when reachable",
                        "Physical damage, liquid trace, loose connector suspicion, impact history, and recent field repair history",
                    ],
                },
            ]
        )

    if os_family == "windows" and can_export:
        groups.append(
            {
                "id": "windows_specific",
                "name": "Windows-specific evidence",
                "layer": "logs",
                "priority": "high",
                "why": "Windows diagnosis depends heavily on event logs, PnP state, dump metadata, and recent driver or update changes.",
                "items": [
                    "System/Application event logs, Reliability Monitor records, and Windows Update history",
                    "Device Manager PnP problem devices, driver versions, and recently changed drivers",
                    "Minidump metadata for crash symptoms and powercfg battery report for charging symptoms",
                ],
            }
        )
    elif os_family == "linux" and can_export:
        groups.append(
            {
                "id": "linux_specific",
                "name": "Linux-specific evidence",
                "layer": "logs",
                "priority": "high",
                "why": "Linux diagnosis needs kernel, service, device-bus, and package-change evidence to isolate software and hardware boundaries.",
                "items": [
                    "journalctl and dmesg logs around the fault time",
                    "lspci, lsusb, lsblk, smartctl, systemd failed services, and kernel version",
                    "Recent package, kernel, firmware, DKMS, or driver changes",
                ],
            }
        )

    for symptom in symptoms:
        symptom_group = SYMPTOM_COLLECTION_GROUPS.get(symptom)
        if symptom_group and symptom_group["id"] not in {group["id"] for group in groups}:
            groups.append(dict(symptom_group))

    priority_order = {"high": 0, "medium": 1, "low": 2}
    groups.sort(key=lambda item: priority_order.get(str(item.get("priority", "medium")), 1))
    return {
        "mode": mode,
        "can_export_runtime": can_export,
        "summary": (
            "Import an offline evidence package copied from the fault machine."
            if offline_import
            else "Collect a transferable evidence package from the fault machine."
            if can_export
            else "Collect field-observable evidence because the fault machine cannot run the collector."
        ),
        "groups": groups,
        "required_before_decision": [
            "device identity",
            "fault symptom",
            "fault time",
            "runtime evidence package" if can_export else "field observation record",
        ],
    }
