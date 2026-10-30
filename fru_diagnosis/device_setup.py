"""Device setup flow for selecting or creating an FRU profile."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fru_config import load_device_profile
from .model_registry import ModelMatch, find_known_model, slugify


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_PATH = PROJECT_ROOT / "configs" / "detected_device.json"
DEFAULT_ACTIVE_PROFILE_PATH = PROJECT_ROOT / "configs" / "active_device.json"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "reports" / "fru_profile_setup_report.json"

SUPPORTED_INITIAL_DEVICE_TYPES = {
    "laptop",
    "server",
    "router",
    "custom",
}


@dataclass(frozen=True)
class SetupInputs:
    declared_device_type: str
    manufacturer: str = ""
    model: str = ""
    custom_name: str = ""
    scan_path: Path = DEFAULT_SCAN_PATH
    output_path: Path = DEFAULT_ACTIVE_PROFILE_PATH
    report_path: Path = DEFAULT_REPORT_PATH
    run_detection: bool = True
    allow_mismatch: bool = False


def run_fru_detection(output_path: Path = DEFAULT_SCAN_PATH) -> None:
    script = PROJECT_ROOT / "scripts" / "detect_fru.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-OutputPath",
        str(output_path),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def setup_device_profile(inputs: SetupInputs) -> dict[str, Any]:
    declared_device_type = normalize_device_type(inputs.declared_device_type)
    if declared_device_type not in SUPPORTED_INITIAL_DEVICE_TYPES:
        raise ValueError(
            f"Unsupported device type {inputs.declared_device_type!r}. "
            f"Use one of {sorted(SUPPORTED_INITIAL_DEVICE_TYPES)}."
        )

    if inputs.run_detection:
        run_fru_detection(inputs.scan_path)

    scan_profile = read_json(inputs.scan_path)
    detected_device_type = normalize_device_type(str(scan_profile.get("device_type", "")))
    device_type_match = is_device_type_match(declared_device_type, detected_device_type)
    if not device_type_match and not inputs.allow_mismatch:
        raise ValueError(
            f"Operator declared {declared_device_type!r}, but hardware scan detected "
            f"{detected_device_type!r}. Re-run with explicit confirmation if this is expected."
        )

    if declared_device_type == "laptop":
        return setup_laptop_profile(inputs, scan_profile, device_type_match)

    if declared_device_type in {"server", "router"}:
        return setup_reserved_device_type(inputs, scan_profile, device_type_match)

    return setup_custom_profile(inputs, scan_profile, device_type_match)


def setup_detected_device_profile(
    scan_path: Path = DEFAULT_SCAN_PATH,
    output_path: Path = DEFAULT_ACTIVE_PROFILE_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    scan_profile = read_json(scan_path)
    metadata = scan_profile.get("metadata", {})
    detected_device_type = normalize_device_type(str(scan_profile.get("device_type", "")))
    declared_device_type = (
        detected_device_type
        if detected_device_type in SUPPORTED_INITIAL_DEVICE_TYPES
        else "custom"
    )

    return setup_device_profile(
        SetupInputs(
            declared_device_type=declared_device_type,
            manufacturer=str(metadata.get("manufacturer", "")),
            model=str(metadata.get("model", "")),
            scan_path=scan_path,
            output_path=output_path,
            report_path=report_path,
            run_detection=False,
            allow_mismatch=True,
        )
    )


def setup_laptop_profile(
    inputs: SetupInputs,
    scan_profile: dict[str, Any],
    device_type_match: bool,
) -> dict[str, Any]:
    metadata = scan_profile.get("metadata", {})
    manufacturer = inputs.manufacturer or str(metadata.get("manufacturer", ""))
    model = inputs.model or str(metadata.get("model", ""))
    display_name = str(scan_profile.get("display_name", ""))

    match = find_known_model(
        device_type="laptop",
        manufacturer=manufacturer,
        model=model,
        display_name=display_name,
    )

    if match is None:
        custom_name = inputs.custom_name or build_custom_name(manufacturer, model, display_name)
        return setup_custom_profile(
            SetupInputs(
                declared_device_type=inputs.declared_device_type,
                manufacturer=manufacturer,
                model=model,
                custom_name=custom_name,
                scan_path=inputs.scan_path,
                output_path=inputs.output_path,
                report_path=inputs.report_path,
                run_detection=False,
                allow_mismatch=inputs.allow_mismatch,
            ),
            scan_profile,
            device_type_match,
        )

    selected_profile = read_json(match.profile.config_path)
    enriched_profile = enrich_selected_profile(
        selected_profile=selected_profile,
        scan_profile=scan_profile,
        match=match,
        operator_inputs=inputs,
        device_type_match=device_type_match,
    )
    write_json(inputs.output_path, enriched_profile)

    report = build_setup_report(
        mode="known_model_profile",
        output_path=inputs.output_path,
        scan_path=inputs.scan_path,
        selected_profile=enriched_profile,
        scan_profile=scan_profile,
        device_type_match=device_type_match,
        model_match=match,
    )
    write_json(inputs.report_path, report)
    load_device_profile(inputs.output_path)
    return report


def setup_reserved_device_type(
    inputs: SetupInputs,
    scan_profile: dict[str, Any],
    device_type_match: bool,
) -> dict[str, Any]:
    custom_name = inputs.custom_name or f"{inputs.declared_device_type}_custom_device"
    report = setup_custom_profile(
        SetupInputs(
            declared_device_type=inputs.declared_device_type,
            manufacturer=inputs.manufacturer,
            model=inputs.model,
            custom_name=custom_name,
            scan_path=inputs.scan_path,
            output_path=inputs.output_path,
            report_path=inputs.report_path,
            run_detection=False,
            allow_mismatch=inputs.allow_mismatch,
        ),
        scan_profile,
        device_type_match,
    )
    report["reserved_device_type"] = True
    report["message"] = (
        f"{inputs.declared_device_type} is reserved for later vertical "
        "generalization; a custom scan-derived profile was created for now."
    )
    write_json(inputs.report_path, report)
    return report


def setup_custom_profile(
    inputs: SetupInputs,
    scan_profile: dict[str, Any],
    device_type_match: bool,
) -> dict[str, Any]:
    custom_name = inputs.custom_name or build_custom_name(
        inputs.manufacturer,
        inputs.model,
        str(scan_profile.get("display_name", "")),
    )
    output_path = Path(inputs.output_path)
    activate_profile = output_path.name == DEFAULT_ACTIVE_PROFILE_PATH.name
    active_profile_path = output_path
    saved_profile_path = (
        custom_output_path(custom_name, output_path.parent)
        if activate_profile
        else output_path
    )

    profile = copy.deepcopy(scan_profile)
    profile["display_name"] = custom_name
    profile.setdefault("metadata", {})
    profile["metadata"].update(
        {
            "setup_mode": "custom_scan_profile",
            "operator_declared_device_type": normalize_device_type(
                inputs.declared_device_type
            ),
            "device_type_verified_by_scan": device_type_match,
            "custom_device_name": custom_name,
            "source_scan_path": str(inputs.scan_path),
            "saved_profile_path": str(saved_profile_path),
        }
    )

    for fru in profile.get("fru_list", []):
        fru.setdefault("diagnosis_role", "target_fru")
        fru.setdefault("verification_status", "detected_only")
        fru.setdefault("source_refs", ["hardware_scan"])

    write_json(saved_profile_path, profile)
    if activate_profile:
        write_json(active_profile_path, profile)

    report = build_setup_report(
        mode="custom_scan_profile",
        output_path=active_profile_path if activate_profile else saved_profile_path,
        scan_path=inputs.scan_path,
        selected_profile=profile,
        scan_profile=scan_profile,
        device_type_match=device_type_match,
        model_match=None,
    )
    report["saved_profile_path"] = str(saved_profile_path)
    if activate_profile:
        report["active_profile_path"] = str(active_profile_path)
    write_json(inputs.report_path, report)
    load_device_profile(active_profile_path if activate_profile else saved_profile_path)
    return report


def enrich_selected_profile(
    selected_profile: dict[str, Any],
    scan_profile: dict[str, Any],
    match: ModelMatch,
    operator_inputs: SetupInputs,
    device_type_match: bool,
) -> dict[str, Any]:
    profile = copy.deepcopy(selected_profile)
    metadata = profile.setdefault("metadata", {})
    scan_metadata = scan_profile.get("metadata", {})
    metadata.update(
        {
            "setup_mode": "known_model_profile",
            "selected_registry_id": match.profile.id,
            "selected_model_family": match.profile.model_family,
            "model_match_score": match.score,
            "model_match_reasons": list(match.reasons),
            "operator_declared_device_type": normalize_device_type(
                operator_inputs.declared_device_type
            ),
            "operator_manufacturer": operator_inputs.manufacturer,
            "operator_model": operator_inputs.model,
            "scan_manufacturer": scan_metadata.get("manufacturer", ""),
            "scan_model": scan_metadata.get("model", ""),
            "scan_display_name": scan_profile.get("display_name", ""),
            "source_scan_path": str(operator_inputs.scan_path),
            "device_type_verified_by_scan": device_type_match,
        }
    )
    return profile


def build_setup_report(
    mode: str,
    output_path: Path,
    scan_path: Path,
    selected_profile: dict[str, Any],
    scan_profile: dict[str, Any],
    device_type_match: bool,
    model_match: ModelMatch | None,
) -> dict[str, Any]:
    verification = verify_scan_against_selected_profile(scan_profile, selected_profile)
    report: dict[str, Any] = {
        "mode": mode,
        "output_path": str(output_path),
        "scan_path": str(scan_path),
        "device_type_match": device_type_match,
        "selected_profile": {
            "device_type": selected_profile.get("device_type"),
            "display_name": selected_profile.get("display_name"),
            "fru_count": len(selected_profile.get("fru_list", [])),
        },
        "scan_profile": {
            "device_type": scan_profile.get("device_type"),
            "display_name": scan_profile.get("display_name"),
            "fru_count": len(scan_profile.get("fru_list", [])),
        },
        "verification": verification,
    }
    if model_match is not None:
        report["model_match"] = {
            "registry_id": model_match.profile.id,
            "score": model_match.score,
            "reasons": list(model_match.reasons),
            "config_path": str(model_match.profile.config_path),
        }
    return report


def verify_scan_against_selected_profile(
    scan_profile: dict[str, Any],
    selected_profile: dict[str, Any],
) -> dict[str, Any]:
    scan_frus = scan_profile.get("fru_list", [])
    selected_frus = selected_profile.get("fru_list", [])
    matched: list[dict[str, Any]] = []
    not_observable: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for fru in selected_frus:
        result = find_scan_support_for_target_fru(fru, scan_frus)
        if result["status"] == "matched":
            matched.append(result)
        elif result["status"] == "not_observable_by_scan":
            not_observable.append(result)
        else:
            missing.append(result)

    scan_only = classify_scan_only_components(scan_frus)

    return {
        "matched_target_frus": matched,
        "not_observable_by_basic_scan": not_observable,
        "missing_or_needs_active_test": missing,
        "scan_only_components": scan_only,
        "accuracy_summary": {
            "target_fru_count": len(selected_frus),
            "matched_count": len(matched),
            "not_observable_count": len(not_observable),
            "missing_or_needs_active_test_count": len(missing),
            "basic_scan_match_ratio": round(
                len(matched) / max(1, len(selected_frus) - len(not_observable)), 3
            ),
        },
    }


def find_scan_support_for_target_fru(
    target_fru: dict[str, Any],
    scan_frus: list[dict[str, Any]],
) -> dict[str, Any]:
    target_id = str(target_fru.get("id", ""))
    expected = TARGET_FRU_SCAN_EXPECTATIONS.get(target_id)
    if expected is None:
        return {
            "target_fru_id": target_id,
            "target_fru_name": target_fru.get("name", ""),
            "status": "not_observable_by_scan",
            "reason": "No basic WMI/CIM verification rule is defined for this FRU.",
        }

    if expected.get("not_observable"):
        return {
            "target_fru_id": target_id,
            "target_fru_name": target_fru.get("name", ""),
            "status": "not_observable_by_scan",
            "reason": expected["reason"],
        }

    best_scan_fru = find_best_scan_match(scan_frus, expected)
    if best_scan_fru is not None:
        return {
            "target_fru_id": target_id,
            "target_fru_name": target_fru.get("name", ""),
            "status": "matched",
            "matched_scan_fru_id": best_scan_fru.get("id", ""),
            "matched_scan_fru_name": best_scan_fru.get("name", ""),
            "reason": expected["reason"],
        }

    return {
        "target_fru_id": target_id,
        "target_fru_name": target_fru.get("name", ""),
        "status": "missing_or_needs_active_test",
        "reason": expected["reason"],
    }


TARGET_FRU_SCAN_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "power_adapter": {
        "not_observable": True,
        "reason": "Windows basic inventory does not reliably expose external adapter wattage; use active power test.",
    },
    "battery_pack": {
        "categories": {"PowerFRU"},
        "keywords": {"battery"},
        "reason": "Battery is visible through Win32_Battery.",
    },
    "m2_ssd_module": {
        "categories": {"StorageFRU"},
        "keywords": {"ssd", "nvme", "storage", "drive"},
        "reason": "Installed NVMe drive is visible through Win32_DiskDrive.",
    },
    "ram_module": {
        "categories": {"ComputeFRU"},
        "keywords": {"memory", "ram", "dimm"},
        "reason": "Installed SO-DIMM module is visible through Win32_PhysicalMemory.",
    },
    "wlan_module": {
        "categories": {"CommunicationFRU"},
        "keywords": {"wi-fi", "wifi", "wireless", "wlan", "bluetooth"},
        "reason": "Wireless or Bluetooth adapter is visible through network/device inventory.",
    },
    "fan_module": {
        "categories": {"ThermalFRU"},
        "keywords": {"fan", "thermal", "cooling"},
        "reason": "Windows may expose only a logical thermal subsystem; active fan test is still needed.",
    },
    "heat_sink": {
        "not_observable": True,
        "reason": "Heat sink is a passive part and cannot be directly confirmed by OS inventory.",
    },
    "motherboard": {
        "categories": {"MainboardFRU"},
        "keywords": {"mainboard", "motherboard", "system board", "asus"},
        "reason": "Baseboard is visible through Win32_BaseBoard.",
    },
    "display_panel_module": {
        "categories": {"DisplayFRU"},
        "preferred_keywords": {"panel", "monitor", "screen"},
        "keywords": {"display", "monitor", "panel", "screen"},
        "target_hint": "panel",
        "reason": "Basic scan detects monitor/panel inventory; panel health still needs active display test.",
    },
    "camera_module": {
        "categories": {"SensorFRU"},
        "keywords": {"camera", "webcam"},
        "reason": "Camera may be visible through PnP device inventory.",
    },
    "keyboard_module": {
        "categories": {"InputFRU"},
        "preferred_keywords": {"keyboard"},
        "keywords": {"keyboard"},
        "target_hint": "keyboard",
        "reason": "Keyboard is visible through Win32_Keyboard or HID inventory.",
    },
    "touchpad_module": {
        "categories": {"InputFRU"},
        "preferred_keywords": {"touchpad", "trackpad"},
        "keywords": {"touchpad", "trackpad", "i2c hid"},
        "target_hint": "touchpad",
        "reason": "Touchpad often appears as HID/I2C HID; active input test improves confidence.",
    },
    "speaker_module": {
        "not_observable": True,
        "reason": "Audio controller is not enough to confirm speaker module health; use active audio test.",
    },
    "led_board": {
        "not_observable": True,
        "reason": "LED board is not reliably exposed by OS inventory; use visual/active LED test.",
    },
    "io_board": {
        "categories": {"InterfaceFRU"},
        "preferred_keywords": {"usb", "interface", "type-c"},
        "keywords": {"usb", "interface", "type-c", "io", "audio"},
        "reason": "USB/I/O controllers are visible, but board-level localization needs port active tests.",
    },
}


def find_best_scan_match(
    scan_frus: list[dict[str, Any]],
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    scored_matches: list[tuple[int, dict[str, Any]]] = []
    for scan_fru in scan_frus:
        score = score_scan_fru_match(scan_fru, expected)
        if score > 0:
            scored_matches.append((score, scan_fru))

    if not scored_matches:
        return None
    scored_matches.sort(key=lambda item: item[0], reverse=True)
    return scored_matches[0][1]


def score_scan_fru_match(scan_fru: dict[str, Any], expected: dict[str, Any]) -> int:
    categories = expected.get("categories", set())
    if categories and scan_fru.get("category") not in categories:
        return 0
    haystack = " ".join(
        [
            str(scan_fru.get("id", "")),
            str(scan_fru.get("name", "")),
            str(scan_fru.get("description", "")),
            " ".join(scan_fru.get("aliases", [])),
        ]
    ).casefold()

    keywords = expected.get("keywords", set())
    if not any(keyword.casefold() in haystack for keyword in keywords):
        return 0

    score = 10
    preferred_keywords = expected.get("preferred_keywords", set())
    for keyword in preferred_keywords:
        if keyword.casefold() in haystack:
            score += 20

    scan_id = str(scan_fru.get("id", "")).casefold()
    target_hint = expected.get("target_hint")
    if target_hint and target_hint.casefold() in scan_id:
        score += 30

    return score


def classify_scan_only_components(scan_frus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for scan_fru in scan_frus:
        haystack = " ".join(
            [
                str(scan_fru.get("id", "")),
                str(scan_fru.get("name", "")),
                str(scan_fru.get("description", "")),
            ]
        ).casefold()
        mapped_to = None
        reason = None
        if "bluetooth device" in haystack or "personal area network" in haystack:
            mapped_to = "wlan_module"
            reason = "Bluetooth PAN is a logical function of the WLAN/Bluetooth module."
        elif "intel(r) uhd graphics" in haystack or "nvidia" in haystack:
            mapped_to = "motherboard"
            reason = "Laptop GPU/iGPU is not a standalone replaceable FRU for this model."
        elif "core(tm)" in haystack or "processor" in haystack:
            mapped_to = "motherboard"
            reason = "Laptop CPU is not a standalone replaceable FRU for this model."
        elif "realtek pcie gbe" in haystack or "ethernet" in haystack:
            mapped_to = "io_board_or_motherboard"
            reason = "LAN evidence should be mapped to I/O board or motherboard."
        elif "usb" in haystack:
            mapped_to = "io_board_or_motherboard"
            reason = "USB controller evidence should be mapped to I/O board or motherboard."

        if mapped_to:
            results.append(
                {
                    "scan_fru_id": scan_fru.get("id", ""),
                    "scan_fru_name": scan_fru.get("name", ""),
                    "mapped_to": mapped_to,
                    "reason": reason,
                }
            )
    return results


def is_device_type_match(declared_device_type: str, detected_device_type: str) -> bool:
    if declared_device_type == detected_device_type:
        return True
    if declared_device_type == "custom":
        return True
    if declared_device_type == "server" and detected_device_type == "desktop_or_server":
        return True
    return False


def normalize_device_type(value: str) -> str:
    mapping = {
        "笔记本": "laptop",
        "笔记本电脑": "laptop",
        "laptop": "laptop",
        "notebook": "laptop",
        "服务器": "server",
        "server": "server",
        "路由器": "router",
        "router": "router",
        "自定义": "custom",
        "custom": "custom",
    }
    return mapping.get(value.strip().casefold(), value.strip().casefold())


def build_custom_name(manufacturer: str, model: str, display_name: str) -> str:
    name = " ".join(item for item in [manufacturer, model] if item.strip()).strip()
    return name or display_name or "Custom Electronic Information Device"


def custom_output_path(custom_name: str, base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else PROJECT_ROOT / "configs"
    return root / f"custom_{slugify(custom_name)}.json"


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_profile(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
