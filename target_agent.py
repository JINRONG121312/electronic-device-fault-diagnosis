"""Lightweight target-machine evidence collection agent.

Run this on the machine being diagnosed, then connect to it from the main
dashboard machine. It intentionally uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


AGENT_VERSION = "target_agent_http_v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the target-machine evidence collection agent.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--token", default=os.environ.get("TARGET_AGENT_TOKEN", ""))
    parser.add_argument("--allow-unsafe-no-token", action="store_true")
    return parser


def build_capabilities() -> dict[str, Any]:
    os_family = detect_os_family()
    return {
        "ok": True,
        "agent_version": AGENT_VERSION,
        "hostname": socket.gethostname(),
        "os_family": os_family,
        "collection_modes": ["http_agent"],
        "evidence": {
            "inventory": True,
            "logs": True,
            "metrics": True,
            "active_tests": True,
            "crash_dump": os_family == "windows",
            "repair_result": False,
        },
        "requires_admin_for": required_privileges(os_family),
        "endpoints": {
            "health": "/api/health",
            "capabilities": "/api/capabilities",
            "collect": "/api/collect",
        },
    }


def required_privileges(os_family: str) -> list[str]:
    if os_family == "windows":
        return ["some event logs", "crash dump file metadata", "battery report"]
    if os_family == "linux":
        return ["kernel logs", "SMART data", "some hardware sensors"]
    return ["platform-specific logs and hardware metrics"]


def collect_evidence(request: dict[str, Any]) -> dict[str, Any]:
    symptoms = normalize_list(request.get("symptom") or request.get("symptoms"))
    fault_case_id = str(request.get("fault_case_id", "") or "").strip()
    fault_time = str(request.get("fault_time", "") or "").strip()
    collect = set(normalize_list(request.get("collect"))) or {
        "inventory",
        "logs",
        "metrics",
        "active_tests",
        "crash_dump",
    }
    window_minutes = int(request.get("time_window_minutes", 60) or 60)
    warnings: list[str] = []
    inventory = collect_inventory(warnings) if "inventory" in collect else {}
    logs = collect_logs(fault_time, window_minutes, warnings) if "logs" in collect else {}
    metrics = collect_metrics(warnings) if "metrics" in collect else {}
    active_tests = collect_active_tests(warnings) if "active_tests" in collect else {}
    crash_dump = collect_crash_dump(warnings) if "crash_dump" in collect else {}
    timestamp = datetime.now().isoformat(timespec="seconds")
    device_id = str(request.get("device_id") or inventory.get("system", {}).get("serial_number") or socket.gethostname())
    runtime_info = {
        "generated_at": timestamp,
        "system": inventory.get("system", {}),
        "device_inventory": inventory.get("device_inventory", {}),
        "events": logs,
        "power": metrics.get("power", {}),
        "battery": metrics.get("battery", {}),
        "storage": metrics.get("storage", {}),
        "memory": metrics.get("memory", {}),
        "network": metrics.get("network", {}),
        "thermal": metrics.get("thermal", {}),
        "tests": active_tests,
        "crash_dump": crash_dump,
        "collection": {
            "mode": "target_agent_http",
            "fault_time": fault_time,
            "time_window_minutes": window_minutes,
            "warnings": warnings,
        },
    }
    return {
        "ok": True,
        "schema": "fault_diagnosis_evidence_package.v1",
        "device_id": device_id,
        "fault_case_id": fault_case_id,
        "timestamp": timestamp,
        "symptom": symptoms,
        "evidence": {
            "inventory": inventory,
            "logs": logs,
            "metrics": metrics,
            "active_tests": active_tests,
            "crash_dump": crash_dump,
            "repair_result": {},
        },
        "runtime_info": runtime_info,
        "warnings": warnings,
    }


def collect_inventory(warnings: list[str]) -> dict[str, Any]:
    os_family = detect_os_family()
    system = {
        "hostname": socket.gethostname(),
        "os_family": os_family,
        "os_caption": platform.platform(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "manufacturer": "",
        "model": platform.node(),
        "serial_number": "",
        "bios_version": "",
    }
    if os_family == "windows":
        cim = run_json_powershell(
            "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | ConvertTo-Json -Compress",
            warnings,
        )
        bios = run_json_powershell(
            "Get-CimInstance Win32_BIOS | Select-Object SerialNumber,SMBIOSBIOSVersion | ConvertTo-Json -Compress",
            warnings,
        )
        if isinstance(cim, dict):
            system["manufacturer"] = str(cim.get("Manufacturer") or "")
            system["model"] = str(cim.get("Model") or system["model"])
        if isinstance(bios, dict):
            system["serial_number"] = str(bios.get("SerialNumber") or "")
            system["bios_version"] = str(bios.get("SMBIOSBIOSVersion") or "")
        problem_devices = run_json_powershell(
            "@(Get-PnpDevice | Where-Object Status -ne 'OK' | Select-Object -First 30 "
            "| ForEach-Object { [pscustomobject]@{Class=$_.Class; FriendlyName=$_.FriendlyName; "
            "InstanceId=$_.InstanceId; Status=$_.Status; Problem=$_.Problem} }) | ConvertTo-Json -Compress -Depth 4",
            warnings,
        )
        devices = normalize_json_rows(problem_devices)
    elif os_family == "linux":
        system["manufacturer"] = read_first_existing(
            ["/sys/class/dmi/id/sys_vendor", "/sys/devices/virtual/dmi/id/sys_vendor"]
        )
        system["model"] = read_first_existing(
            ["/sys/class/dmi/id/product_name", "/sys/devices/virtual/dmi/id/product_name"]
        ) or system["model"]
        system["serial_number"] = read_first_existing(
            ["/sys/class/dmi/id/product_serial", "/sys/devices/virtual/dmi/id/product_serial"]
        )
        system["bios_version"] = read_first_existing(
            ["/sys/class/dmi/id/bios_version", "/sys/devices/virtual/dmi/id/bios_version"]
        )
        devices = run_lines(["sh", "-c", "lspci 2>/dev/null | head -80"], warnings)
    else:
        devices = []
    return {
        "system": system,
        "device_inventory": {
            "problem_device_count": len(devices) if isinstance(devices, list) else 0,
            "problem_devices": devices,
        },
    }


def collect_logs(fault_time: str, window_minutes: int, warnings: list[str]) -> dict[str, Any]:
    os_family = detect_os_family()
    logs: dict[str, Any] = {
        "collection": {
            "mode": "fault_window" if fault_time else "recent",
            "fault_time": fault_time,
            "time_window_minutes": window_minutes,
        }
    }
    if os_family == "windows":
        hours = max(1, int((window_minutes * 2) / 60))
        script = (
            f"$start=(Get-Date).AddHours(-{hours}); "
            "Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$start} -MaxEvents 80 "
            "| Select-Object TimeCreated,ProviderName,Id,LevelDisplayName,Message "
            "| ConvertTo-Json -Compress"
        )
        system_events = normalize_json_rows(run_json_powershell(script, warnings))
        logs["system_events"] = system_events
        logs["total_warning_error_count"] = count_warning_error_events(system_events)
    elif os_family == "linux":
        since = build_linux_since(fault_time, window_minutes)
        lines = run_lines(["journalctl", "--since", since, "-n", "120", "--no-pager"], warnings)
        if not lines:
            lines = run_lines(["dmesg", "--ctime", "--level=err,warn"], warnings)
        logs["journal"] = lines[-120:] if isinstance(lines, list) else []
        logs["total_warning_error_count"] = len(logs["journal"])
    return logs


def collect_metrics(warnings: list[str]) -> dict[str, Any]:
    os_family = detect_os_family()
    metrics: dict[str, Any] = {
        "memory": collect_basic_memory_metrics(),
        "network": {"hostname": socket.gethostname(), "interfaces": collect_network_interfaces()},
        "storage": {},
        "battery": {},
        "power": {},
        "thermal": {},
    }
    if os_family == "windows":
        disks = run_json_powershell(
            "@(Get-CimInstance Win32_DiskDrive | ForEach-Object { [pscustomobject]@{Model=$_.Model; "
            "Status=$_.Status; Size=$_.Size; InterfaceType=$_.InterfaceType} }) | ConvertTo-Json -Compress -Depth 4",
            warnings,
        )
        batteries = run_json_powershell(
            "@(Get-CimInstance Win32_Battery | ForEach-Object { [pscustomobject]@{Name=$_.Name; "
            "BatteryStatus=$_.BatteryStatus; EstimatedChargeRemaining=$_.EstimatedChargeRemaining; Status=$_.Status} }) "
            "| ConvertTo-Json -Compress -Depth 4",
            warnings,
        )
        memory = run_json_powershell(
            "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress",
            warnings,
        )
        metrics["storage"] = {"drives": normalize_json_rows(disks)}
        metrics["battery"] = {"batteries": normalize_json_rows(batteries)}
        if isinstance(memory, dict):
            metrics["memory"] = memory
    elif os_family == "linux":
        metrics["storage"] = {
            "block_devices": run_lines(["sh", "-c", "lsblk -J 2>/dev/null || lsblk 2>/dev/null"], warnings)
        }
        metrics["memory"] = {"meminfo": read_key_value_file("/proc/meminfo")}
        metrics["thermal"] = {"thermal_zones": collect_linux_thermal()}
    return metrics


def collect_active_tests(warnings: list[str]) -> dict[str, Any]:
    return {
        "network_gateway": {
            "status": "not_run",
            "note": "Controller can request a later targeted ping or gateway test.",
        },
        "storage_short_test": {
            "status": "not_run",
            "note": "SMART self-test is not launched by default to avoid side effects.",
        },
        "display_external_monitor": {
            "status": "not_recorded",
            "note": "Record manually if the symptom is black screen or display failure.",
        },
    }


def collect_crash_dump(warnings: list[str]) -> dict[str, Any]:
    if detect_os_family() != "windows":
        return {
            "available": False,
            "source": "target_agent",
            "dump_files": [],
            "bugcheck_code": "",
            "probable_modules": [],
            "limitation": "Windows crash dump collection is not applicable on this OS.",
            "reason": "not_windows_target",
            "next_action": "collect_kernel_logs_and_hardware_metrics",
        }
    minidump = Path("C:/Windows/Minidump")
    memory_dump = Path("C:/Windows/MEMORY.DMP")
    dumps = []
    try:
        if minidump.exists():
            dumps = [
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                }
                for path in sorted(minidump.glob("*.dmp"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]
            ]
    except OSError as exc:
        warnings.append(f"minidump metadata failed: {exc}")
    memory_dump_meta = {}
    try:
        if memory_dump.exists():
            memory_dump_meta = {
                "path": str(memory_dump),
                "size_bytes": memory_dump.stat().st_size,
                "modified_at": datetime.fromtimestamp(memory_dump.stat().st_mtime).isoformat(timespec="seconds"),
            }
    except OSError as exc:
        warnings.append(f"memory dump metadata failed: {exc}")
    dump_files = [{**item, "kind": "minidump"} for item in dumps]
    if memory_dump_meta:
        dump_files.append({**memory_dump_meta, "kind": "memory_dump"})
    available = bool(dump_files)
    return {
        "minidumps": dumps,
        "memory_dump": memory_dump_meta,
        "available": available,
        "source": "target_agent",
        "dump_files": dump_files,
        "bugcheck_code": "",
        "probable_modules": [],
        "limitation": "" if available else "No minidump or MEMORY.DMP metadata was found on the target machine.",
        "reason": "" if available else "dump_not_found_or_machine_unavailable",
        "next_action": "" if available else "enable_dump_or_collect_offline_evidence",
    }


def collect_network_interfaces() -> list[dict[str, Any]]:
    interfaces = []
    try:
        for _index, name in socket.if_nameindex():
            interfaces.append({"name": name})
    except OSError:
        pass
    return interfaces


def collect_basic_memory_metrics() -> dict[str, Any]:
    if hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            page_count = int(os.sysconf("SC_PHYS_PAGES"))
            return {"total_bytes": page_size * page_count}
        except (OSError, ValueError):
            pass
    return {}


def collect_linux_thermal() -> list[dict[str, Any]]:
    zones = []
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        temp = zone / "temp"
        zone_type = zone / "type"
        if temp.exists():
            zones.append(
                {
                    "name": zone.name,
                    "type": read_text(zone_type),
                    "temperature_millic": read_text(temp),
                }
            )
    return zones


def run_json_powershell(script: str, warnings: list[str]) -> Any:
    completed = run_command(["powershell", "-NoProfile", "-Command", script], warnings, timeout=20)
    if not completed:
        return None
    try:
        return json.loads(completed)
    except json.JSONDecodeError:
        warnings.append("PowerShell command returned non-JSON output.")
        return None


def run_lines(command: list[str], warnings: list[str], timeout: int = 15) -> list[str]:
    output = run_command(command, warnings, timeout=timeout)
    return output.splitlines() if output else []


def run_command(command: list[str], warnings: list[str], timeout: int = 15) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"{command[0]} failed: {exc}")
        return ""
    if completed.returncode != 0 and completed.stderr.strip():
        warnings.append(completed.stderr.strip()[:300])
    return completed.stdout.strip()


def normalize_json_rows(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def count_warning_error_events(events: list[Any]) -> int:
    count = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        level = str(event.get("LevelDisplayName", "")).casefold()
        if "warning" in level or "error" in level or "critical" in level:
            count += 1
    return count


def build_linux_since(fault_time: str, window_minutes: int) -> str:
    if fault_time:
        try:
            dt = datetime.fromisoformat(fault_time)
            return (dt - timedelta(minutes=window_minutes)).isoformat(timespec="seconds")
        except ValueError:
            pass
    return f"-{max(1, int(window_minutes or 60))} minutes"


def read_first_existing(paths: list[str]) -> str:
    for path in paths:
        text = read_text(Path(path))
        if text:
            return text
    return ""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def read_key_value_file(path: str) -> dict[str, str]:
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def detect_os_family() -> str:
    system = platform.system().casefold()
    if system.startswith("win"):
        return "windows"
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "macos"
    return system or "unknown"


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class TargetAgentHandler(BaseHTTPRequestHandler):
    server_version = "FaultDiagnosisTargetAgent/1.0"
    token = ""

    def do_GET(self) -> None:
        if not self.authorized():
            self.respond_json({"ok": False, "error": "Unauthorized."}, HTTPStatus.UNAUTHORIZED)
            return
        if self.path == "/api/health":
            self.respond_json(
                {
                    "ok": True,
                    "service": "fault_diagnosis_target_agent",
                    "version": AGENT_VERSION,
                    "hostname": socket.gethostname(),
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            return
        if self.path == "/api/capabilities":
            self.respond_json(build_capabilities())
            return
        self.respond_json({"ok": False, "error": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self.authorized():
            self.respond_json({"ok": False, "error": "Unauthorized."}, HTTPStatus.UNAUTHORIZED)
            return
        if self.path != "/api/collect":
            self.respond_json({"ok": False, "error": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)
            return
        try:
            body = self.read_json_body()
            self.respond_json(collect_evidence(body))
        except Exception as exc:  # noqa: BLE001
            self.respond_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def authorized(self) -> bool:
        if not self.token:
            return True
        auth = self.headers.get("Authorization", "")
        bearer = auth.removeprefix("Bearer").strip()
        return self.headers.get("X-Agent-Token") == self.token or bearer == self.token

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        data = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def respond_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def main() -> int:
    args = build_parser().parse_args()
    if not args.token and not args.allow_unsafe_no_token:
        raise SystemExit("Refusing to start without --token. Use --allow-unsafe-no-token only in an isolated lab.")
    TargetAgentHandler.token = args.token
    server = ThreadingHTTPServer((args.host, args.port), TargetAgentHandler)
    print(f"Target evidence agent running at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTarget agent stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
