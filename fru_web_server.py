"""Local web server for the interactive fault-diagnosis dashboard."""

from __future__ import annotations

import argparse
import ctypes
import json
import mimetypes
import os
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fru_diagnosis.collection_config import (
    archive_runtime_snapshot,
    build_resolved_settings,
    cleanup_history,
    list_history_snapshots,
    load_collection_settings,
    resolve_active_runtime_path,
    save_collection_settings,
)
from fru_diagnosis.dashboard_data import (
    PROJECT_ROOT,
    build_dashboard_payload,
    read_json,
    set_runtime_test_result,
)
from fru_diagnosis.datasets import DatasetCase, dump_cases_jsonl
from fru_diagnosis.diagnostic_workflow import run_diagnostic_workflow
from fru_diagnosis.remote_agent_client import (
    RemoteAgentError,
    collect_from_target_agent,
    probe_target_agent,
)
from fru_diagnosis.device_setup import (
    DEFAULT_ACTIVE_PROFILE_PATH,
    DEFAULT_REPORT_PATH,
    DEFAULT_SCAN_PATH,
    SetupInputs,
    setup_detected_device_profile,
    setup_device_profile,
)
from fru_diagnosis.web_api import ApiRoutes, api_error, ok


WEB_ROOT = PROJECT_ROOT / "web"
POWERSHELL = "powershell"
PYTHON = sys.executable
LOCK_DIR = PROJECT_ROOT / "reports" / "locks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local fault-diagnosis research dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    return parser


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, kind: str) -> str:
        with self._lock:
            job_id = str(self._next_id)
            self._next_id += 1
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "status": "running",
                "message": "",
                "returncode": None,
                "stdout": "",
                "stderr": "",
            }
            return job_id

    def update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(values)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None


JOBS = JobStore()


class BackgroundCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status: dict[str, Any] = {
            "running": False,
            "current_task": "",
            "last_started_at": None,
            "last_completed_at": None,
            "last_status": "idle",
            "last_message": "",
            "last_job_id": None,
            "next_run_at": None,
        }

    def start(self) -> dict[str, Any]:
        already_running = False
        with self._lock:
            if self._thread and self._thread.is_alive():
                already_running = True
            else:
                self._stop_event.clear()
                self._thread = threading.Thread(target=self._run_loop, daemon=True)
                self._thread.start()
                self._status.update(
                    {
                        "running": True,
                        "last_status": "started",
                        "last_message": "Background collection is running.",
                    }
                )
        if already_running:
            return self.status()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        with self._lock:
            self._status.update(
                {
                    "running": bool(self._thread and self._thread.is_alive()),
                    "last_status": "stopping",
                    "last_message": "Background collection stop requested.",
                    "next_run_at": None,
                }
            )
            return dict(self._status)

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            status["running"] = bool(self._thread and self._thread.is_alive())
            return status

    def _set_status(self, **values: Any) -> None:
        with self._lock:
            self._status.update(values)

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                settings = load_collection_settings()
                background = settings["background"]
                if not background.get("enabled", False):
                    break

                if background.get("collect_runtime", True):
                    self._run_runtime_collection(settings)

                if background.get("scan_fru", False) and not self._stop_event.is_set():
                    self._run_fru_scan()

                if self._stop_event.is_set():
                    break

                interval_seconds = int(background.get("interval_minutes", 30)) * 60
                next_run = datetime.now().timestamp() + interval_seconds
                self._set_status(
                    current_task="waiting",
                    next_run_at=datetime.fromtimestamp(next_run).isoformat(timespec="seconds"),
                    running=True,
                )
                self._stop_event.wait(interval_seconds)
        finally:
            self._set_status(running=False, current_task="", next_run_at=None)

    def _run_runtime_collection(self, settings: dict[str, Any]) -> None:
        background = settings["background"]
        output_path = resolve_active_runtime_path(settings)
        command = build_runtime_collection_command(
            output_path=output_path,
            hours=int(background.get("hours", 6)),
            max_system_events=int(background.get("max_system_events", 200)),
            max_application_events=int(background.get("max_application_events", 50)),
        )
        job_id = JOBS.create("background_runtime_collection")
        started_at = datetime.now().isoformat(timespec="seconds")
        self._set_status(
            current_task="runtime_collection",
            last_started_at=started_at,
            last_status="running",
            last_message="Collecting runtime data.",
            last_job_id=job_id,
            running=True,
        )
        run_job_command(job_id, command, on_success=lambda: archive_runtime_snapshot(settings, output_path))
        job = JOBS.get(job_id) or {}
        self._set_status(
            current_task="",
            last_completed_at=datetime.now().isoformat(timespec="seconds"),
            last_status=job.get("status", "unknown"),
            last_message=job.get("message", ""),
            running=True,
        )

    def _run_fru_scan(self) -> None:
        command = [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "detect_fru.ps1"),
            "-OutputPath",
            str(DEFAULT_SCAN_PATH),
            "-NoProgress",
        ]
        job_id = JOBS.create("background_fru_scan")
        self._set_status(
            current_task="fru_scan",
            last_started_at=datetime.now().isoformat(timespec="seconds"),
            last_status="running",
            last_message="Scanning serviceability inventory.",
            last_job_id=job_id,
            running=True,
        )
        run_job_command(
            job_id,
            command,
            on_success=lambda: setup_detected_device_profile(
                scan_path=DEFAULT_SCAN_PATH,
                output_path=DEFAULT_ACTIVE_PROFILE_PATH,
                report_path=DEFAULT_REPORT_PATH,
            ),
        )
        job = JOBS.get(job_id) or {}
        self._set_status(
            current_task="",
            last_completed_at=datetime.now().isoformat(timespec="seconds"),
            last_status=job.get("status", "unknown"),
            last_message=job.get("message", ""),
            running=True,
        )


BACKGROUND_COLLECTOR = BackgroundCollector()


def build_api_routes(handler: "FRURequestHandler") -> ApiRoutes:
    return ApiRoutes(
        get={
            "/api/dashboard": lambda _query: ok(build_configured_dashboard_payload()),
            "/api/health": lambda _query: ok(
                {
                    "ok": True,
                    "service": "fault_diagnosis_web",
                    "version": self_version(),
                    "web_root": str(WEB_ROOT),
                    "app_url": build_app_url(handler),
                    "note": "Open app_url in a browser for the dashboard. This endpoint is only a JSON health check.",
                    "checked_at": datetime.now().isoformat(timespec="seconds"),
                }
            ),
            "/api/job": handler.api_get_job,
            "/api/settings": lambda _query: ok(build_settings_payload()),
            "/api/background/status": lambda _query: ok({"ok": True, "status": BACKGROUND_COLLECTOR.status()}),
            "/api/experiments/loghub-os": lambda query: ok(build_loghub_os_experiment_payload(query)),
        },
        post={
            "/api/setup-profile": handler.api_setup_profile,
            "/api/scan-fru": handler.api_scan_fru,
            "/api/collect-runtime": handler.api_collect_runtime,
            "/api/diagnose": handler.api_diagnose,
            "/api/remote-diagnosis": handler.api_remote_diagnosis,
            "/api/target/probe": handler.api_target_probe,
            "/api/target/collect": handler.api_target_collect,
            "/api/update-test": handler.api_update_test,
            "/api/settings": handler.api_update_settings,
            "/api/background/start": handler.api_background_start,
            "/api/background/stop": lambda _body: handler.api_background_stop(),
            "/api/experiments/loghub-os/import": lambda body: ok(import_loghub_os_experiment(body)),
            "/api/experiments/loghub-os/import-test": lambda body: ok(import_loghub_os_test_cases(body)),
        },
    )


class FRURequestHandler(SimpleHTTPRequestHandler):
    server_version = "FaultDiagnosisWeb/1.0"

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        request_path = parsed.path
        if request_path == "/":
            return str(WEB_ROOT / "index.html")

        relative = request_path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        try:
            candidate.relative_to(WEB_ROOT.resolve())
        except ValueError:
            return str(WEB_ROOT / "index.html")
        return str(candidate)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            status, payload = build_api_routes(self).handle_get(parsed.path, parse_qs(parsed.query))
            self.respond_json(payload, status=status)
            return

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self.read_json_body()
            status, payload = build_api_routes(self).handle_post(parsed.path, body)
            self.respond_json(payload, status=status)
        except ValueError as exc:
            self.respond_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.respond_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def api_get_job(self, query: dict[str, list[str]]) -> tuple[HTTPStatus, dict[str, Any]]:
        job_id = query.get("id", [""])[0]
        job = JOBS.get(job_id)
        if job is None:
            return api_error(HTTPStatus.NOT_FOUND, f"Unknown job id: {job_id}")
        return ok(job)

    def api_setup_profile(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        inputs = SetupInputs(
            declared_device_type=str(body.get("device_type", "")).strip(),
            manufacturer=str(body.get("manufacturer", "")).strip(),
            model=str(body.get("model", "")).strip(),
            custom_name=str(body.get("custom_name", "")).strip(),
            scan_path=DEFAULT_SCAN_PATH,
            output_path=DEFAULT_ACTIVE_PROFILE_PATH,
            report_path=DEFAULT_REPORT_PATH,
            run_detection=bool(body.get("run_detection", False)),
            allow_mismatch=bool(body.get("allow_mismatch", False)),
        )
        report = setup_device_profile(inputs)
        return ok({"ok": True, "report": report, "dashboard": build_configured_dashboard_payload()})

    def api_scan_fru(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        no_progress = bool(body.get("no_progress", True))
        command = [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "detect_fru.ps1"),
            "-OutputPath",
            str(DEFAULT_SCAN_PATH),
        ]
        if no_progress:
            command.append("-NoProgress")
        job_id = run_background_job(
            "fru_scan",
            command,
            on_success=lambda: setup_detected_device_profile(
                scan_path=DEFAULT_SCAN_PATH,
                output_path=DEFAULT_ACTIVE_PROFILE_PATH,
                report_path=DEFAULT_REPORT_PATH,
            ),
        )
        return ok({"ok": True, "job_id": job_id})

    def api_collect_runtime(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        settings = load_collection_settings()
        output_path = resolve_active_runtime_path(settings)
        hours = int(body.get("hours", 6) or 6)
        max_system_events = int(body.get("max_system_events", 200) or 200)
        max_application_events = int(body.get("max_application_events", 50) or 50)
        fault_time = str(body.get("fault_time", "") or "").strip()
        before_fault_minutes = int(body.get("before_fault_minutes", 60) or 60)
        after_fault_minutes = int(body.get("after_fault_minutes", 15) or 15)
        command = build_runtime_collection_command(
            output_path=output_path,
            hours=hours,
            max_system_events=max_system_events,
            max_application_events=max_application_events,
            fault_time=fault_time,
            before_fault_minutes=before_fault_minutes,
            after_fault_minutes=after_fault_minutes,
        )
        job_id = run_background_job(
            "runtime_collection",
            command,
            on_success=lambda: archive_runtime_snapshot(settings, output_path),
        )
        return ok({"ok": True, "job_id": job_id})

    def api_remote_diagnosis(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        profile = read_json(DEFAULT_ACTIVE_PROFILE_PATH, default={})
        return ok(run_diagnostic_workflow("cross_machine_remote", body, profile))

    def api_diagnose(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        profile = read_json(DEFAULT_ACTIVE_PROFILE_PATH, default={})
        settings = load_collection_settings()
        runtime = read_json(resolve_active_runtime_path(settings), default={})
        mode = str(body.get("mode", "") or "").strip()
        return ok(run_diagnostic_workflow(mode, body, profile, runtime=runtime))

    def api_target_probe(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        try:
            return ok(
                probe_target_agent(
                    str(body.get("target_url", "") or "").strip(),
                    token=str(body.get("token", "") or "").strip(),
                    timeout=int(body.get("timeout", 8) or 8),
                )
            )
        except RemoteAgentError as exc:
            return api_error(HTTPStatus.BAD_GATEWAY, str(exc))

    def api_target_collect(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        target_url = str(body.get("target_url", "") or "").strip()
        token = str(body.get("token", "") or "").strip()
        request_body = build_target_collection_request(body)
        try:
            collected = collect_from_target_agent(
                target_url,
                token=token,
                request_body=request_body,
                timeout=int(body.get("timeout", 45) or 45),
            )
        except RemoteAgentError as exc:
            return api_error(HTTPStatus.BAD_GATEWAY, str(exc))

        profile = read_json(DEFAULT_ACTIVE_PROFILE_PATH, default={})
        diagnosis_body = {
            "mode": "cross_machine_interface",
            "manufacturer": body.get("manufacturer", ""),
            "model": body.get("model", ""),
            "os_family": body.get("os_family", ""),
            "fault_time": body.get("fault_time", ""),
            "symptoms": request_body.get("symptom", []),
            "description": body.get("description", ""),
            "runtime_info": collected["runtime_info"],
            "customer_id": body.get("customer_id", ""),
            "device_id": request_body.get("device_id", ""),
        }
        diagnosis = run_diagnostic_workflow("cross_machine_interface", diagnosis_body, profile)
        return ok(
            {
                "ok": True,
                "target_url": collected["target_url"],
                "request": request_body,
                "evidence_package": collected["evidence_package"],
                "runtime_info": collected["runtime_info"],
                "diagnosis": diagnosis,
            }
        )

    def api_update_test(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        key = str(body.get("key", "")).strip()
        value = str(body.get("value", "")).strip()
        settings = load_collection_settings()
        runtime = set_runtime_test_result(key, value, resolve_active_runtime_path(settings))
        return ok(
            {
                "ok": True,
                "runtime_generated_at": runtime.get("generated_at"),
                "dashboard": build_configured_dashboard_payload(),
            }
        )

    def api_update_settings(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        settings = save_collection_settings(body)
        cleanup_history(settings)
        if settings["background"].get("enabled", False):
            status = BACKGROUND_COLLECTOR.start()
        else:
            status = BACKGROUND_COLLECTOR.stop()
        return ok(
            {
                "ok": True,
                "settings": settings,
                "resolved": build_resolved_settings(settings),
                "history": list_history_snapshots(settings),
                "background_status": status,
                "dashboard": build_configured_dashboard_payload(),
            }
        )

    def api_background_start(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        settings = load_collection_settings()
        if isinstance(body.get("background"), dict):
            settings["background"].update(body["background"])
        settings["background"]["enabled"] = True
        settings = save_collection_settings(settings)
        status = BACKGROUND_COLLECTOR.start()
        return ok(
            {
                "ok": True,
                "settings": settings,
                "resolved": build_resolved_settings(settings),
                "background_status": status,
            }
        )

    def api_background_stop(self) -> tuple[HTTPStatus, dict[str, Any]]:
        settings = load_collection_settings()
        settings["background"]["enabled"] = False
        settings = save_collection_settings(settings)
        status = BACKGROUND_COLLECTOR.stop()
        return ok(
            {
                "ok": True,
                "settings": settings,
                "resolved": build_resolved_settings(settings),
                "background_status": status,
            }
        )

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def respond_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_error(self, status: HTTPStatus, message: str) -> None:
        self.respond_json({"ok": False, "error": message}, status=status)

    def guess_type(self, path: str) -> str:
        if path.endswith(".js"):
            return "application/javascript; charset=utf-8"
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        if path.endswith(".html"):
            return "text/html; charset=utf-8"
        return mimetypes.guess_type(path)[0] or "application/octet-stream"


def build_settings_payload() -> dict[str, Any]:
    settings = load_collection_settings()
    return {
        "ok": True,
        "settings": settings,
        "resolved": build_resolved_settings(settings),
        "history": list_history_snapshots(settings),
        "background_status": BACKGROUND_COLLECTOR.status(),
    }


def build_app_url(handler: "FRURequestHandler") -> str:
    headers = getattr(handler, "headers", None)
    host = str(headers.get("Host", "") or "").strip() if headers is not None else ""
    if not host:
        host = "localhost:8780"
    return f"http://{host}/"


def build_target_collection_request(body: dict[str, Any]) -> dict[str, Any]:
    collect = body.get("collect")
    if not isinstance(collect, list) or not collect:
        collect = ["inventory", "logs", "metrics", "active_tests", "crash_dump"]
    symptoms = body.get("symptoms") or body.get("symptom") or []
    if isinstance(symptoms, str):
        symptoms = [symptoms]
    if not isinstance(symptoms, list):
        symptoms = []
    return {
        "fault_case_id": str(body.get("fault_case_id") or body.get("customer_id") or "").strip(),
        "device_id": str(body.get("device_id", "") or "").strip(),
        "fault_time": str(body.get("fault_time", "") or "").strip(),
        "symptom": [str(item).strip() for item in symptoms if str(item).strip()],
        "collect": [str(item).strip() for item in collect if str(item).strip()],
        "time_window_minutes": int(body.get("time_window_minutes", 60) or 60),
    }


def build_configured_dashboard_payload() -> dict[str, Any]:
    settings = load_collection_settings()
    payload = build_dashboard_payload(runtime_path=resolve_active_runtime_path(settings))
    payload["collection_settings"] = settings
    payload["collection_resolved"] = build_resolved_settings(settings)
    payload["collection_history"] = list_history_snapshots(settings)
    payload["background_status"] = BACKGROUND_COLLECTOR.status()
    return payload


def build_loghub_os_experiment_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    processed_dir = PROJECT_ROOT / "datasets" / "processed" / "loghub_os"
    stats_path = processed_dir / "stats.json"
    case_paths = resolve_loghub_experiment_case_paths(processed_dir)

    stats = read_json(stats_path, default={})
    cases = []
    for path in case_paths:
        cases.extend(load_jsonl_cases(path))
    limit = parse_int_query(query, "limit", default=30)
    dataset_filter = (query.get("dataset", ["all"])[0] or "all").strip().lower()
    label_filter = (query.get("label", ["all"])[0] or "all").strip().lower()
    split_filter = (query.get("split", ["test"])[0] or "test").strip().lower()
    matrix_key = (query.get("matrix_key", ["target"])[0] or "target").strip().lower()
    if matrix_key not in {"fault_origin", "target", "serviceability_type"}:
        matrix_key = "target"

    filtered_cases = filter_experiment_cases(
        cases,
        dataset_filter=dataset_filter,
        label_filter=label_filter,
        split_filter=split_filter,
    )
    split_metrics = {
        split: evaluate_experiment_cases(
            filter_experiment_cases(cases, dataset_filter=dataset_filter, label_filter=label_filter, split_filter=split),
            matrix_key=matrix_key,
        )
        for split in ["train", "dev", "test", "all"]
    }
    corpus = summarize_experiment_corpus(cases)

    return {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": stats,
        "corpus": corpus,
        "metrics": evaluate_experiment_cases(filtered_cases, matrix_key=matrix_key),
        "split_metrics": split_metrics,
        "test_metrics": split_metrics["test"],
        "filters": {
            "dataset": dataset_filter,
            "label": label_filter,
            "split": split_filter,
            "matrix_key": matrix_key,
            "limit": limit,
        },
        "case_count": len(cases),
        "filtered_count": len(filtered_cases),
        "cases": [summarize_experiment_case(case) for case in filtered_cases[:limit]],
        "paths": {
            "processed_dir": str(processed_dir),
            "stats": str(stats_path),
            "cases": [str(path) for path in case_paths],
        },
        "note": (
            "Loghub Linux/Windows/Mac do not include official fault labels. "
            "Displayed expected labels are weak labels or imported labels used for experiment evaluation."
        ),
    }


def resolve_loghub_experiment_case_paths(processed_dir: Path) -> list[Path]:
    base_path = processed_dir / "all_pred.jsonl"
    if not base_path.exists():
        base_path = processed_dir / "all.jsonl"
    paths = [base_path] if base_path.exists() else []
    imported_pred = processed_dir / "imported_test_pred.jsonl"
    imported_raw = processed_dir / "imported_test.jsonl"
    if imported_pred.exists():
        paths.append(imported_pred)
    elif imported_raw.exists():
        paths.append(imported_raw)
    return paths


def import_loghub_os_experiment(body: dict[str, Any]) -> dict[str, Any]:
    datasets = body.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        datasets = ["linux", "windows", "mac"]
    allowed = {"linux", "windows", "mac"}
    selected = [str(item).strip().lower() for item in datasets if str(item).strip().lower() in allowed]
    if not selected:
        selected = ["linux", "windows", "mac"]
    window_size = int(body.get("window_size", 50) or 50)
    window_size = max(1, min(window_size, 500))
    force_download = bool(body.get("force_download", False))
    skip_download = bool(body.get("skip_download", True))
    method = normalize_experiment_method(body.get("method", "graph_fusion"))

    prepare_command = [
        PYTHON,
        str(PROJECT_ROOT / "scripts" / "prepare_loghub_os_dataset.py"),
        "--datasets",
        *selected,
        "--window-size",
        str(window_size),
    ]
    if skip_download:
        prepare_command.append("--skip-download")
    if force_download:
        prepare_command.append("--force-download")

    prepare = subprocess.run(
        prepare_command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if prepare.returncode != 0:
        return {
            "ok": False,
            "stage": "prepare",
            "returncode": prepare.returncode,
            "stdout": prepare.stdout[-4000:],
            "stderr": prepare.stderr[-4000:],
        }

    processed_dir = PROJECT_ROOT / "datasets" / "processed" / "loghub_os"
    baseline = subprocess.run(
        [
            PYTHON,
            str(PROJECT_ROOT / "experiments" / "run_baselines.py"),
            str(processed_dir / "all.jsonl"),
            str(processed_dir / "all_pred.jsonl"),
            "--method",
            method,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if baseline.returncode != 0:
        return {
            "ok": False,
            "stage": "baseline",
            "returncode": baseline.returncode,
            "stdout": baseline.stdout[-4000:],
            "stderr": baseline.stderr[-4000:],
        }

    payload = build_loghub_os_experiment_payload({"split": ["test"], "limit": ["30"]})
    payload["import"] = {
        "ok": True,
        "datasets": selected,
        "window_size": window_size,
        "method": method,
        "prepare_stdout": prepare.stdout[-2000:],
        "baseline_stdout": baseline.stdout[-2000:],
    }
    return payload


def import_loghub_os_test_cases(body: dict[str, Any]) -> dict[str, Any]:
    filename = str(body.get("filename", "") or "imported_test.jsonl").strip()
    content = str(body.get("content", "") or "")
    if not content.strip():
        return {"ok": False, "error": "Uploaded test sample JSONL is empty."}
    if len(content.encode("utf-8")) > 5 * 1024 * 1024:
        return {"ok": False, "error": "Uploaded test sample JSONL exceeds 5 MiB."}

    imported_at = datetime.now().isoformat(timespec="seconds")
    try:
        cases, warnings = parse_imported_test_cases(content, filename=filename, imported_at=imported_at)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not cases:
        return {"ok": False, "error": "No DatasetCase records were found in uploaded JSONL."}

    processed_dir = PROJECT_ROOT / "datasets" / "processed" / "loghub_os"
    processed_dir.mkdir(parents=True, exist_ok=True)
    imported_path = processed_dir / "imported_test.jsonl"
    predicted_path = processed_dir / "imported_test_pred.jsonl"
    method = normalize_experiment_method(body.get("method", "graph_fusion"))
    dump_cases_jsonl(cases, imported_path)

    baseline = subprocess.run(
        [
            PYTHON,
            str(PROJECT_ROOT / "experiments" / "run_baselines.py"),
            str(imported_path),
            str(predicted_path),
            "--method",
            method,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if baseline.returncode != 0:
        return {
            "ok": False,
            "stage": "baseline",
            "returncode": baseline.returncode,
            "stdout": baseline.stdout[-4000:],
            "stderr": baseline.stderr[-4000:],
        }

    payload = build_loghub_os_experiment_payload(
        {"dataset": ["imported_test"], "split": ["test"], "matrix_key": ["target"], "limit": ["30"]}
    )
    payload["import"] = {
        "ok": True,
        "mode": "uploaded_test_jsonl",
        "filename": filename,
        "case_count": len(cases),
        "method": method,
        "warnings": warnings[:20],
        "imported_path": str(imported_path),
        "predicted_path": str(predicted_path),
        "baseline_stdout": baseline.stdout[-2000:],
    }
    return payload


def normalize_experiment_method(value: Any) -> str:
    method = str(value or "").strip().lower()
    if method in {"rule_weighted", "graph_fusion"}:
        return method
    return "graph_fusion"


def parse_imported_test_cases(
    content: str,
    *,
    filename: str,
    imported_at: str,
) -> tuple[list[DatasetCase], list[str]]:
    cases: list[DatasetCase] = []
    warnings: list[str] = []
    safe_filename = Path(filename).name or "imported_test.jsonl"
    for line_number, line in enumerate(content.splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at uploaded line {line_number}: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"Uploaded line {line_number} is not a DatasetCase object.")
        try:
            case = DatasetCase.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Uploaded line {line_number} is not a valid DatasetCase: {exc}") from exc
        if case.label is None:
            warnings.append(f"{case.case_id}: missing label; it will not contribute to confusion-matrix accuracy.")
        metadata = dict(case.metadata)
        metadata.update(
            {
                "dataset_key": "imported_test",
                "split": "test",
                "imported_filename": safe_filename,
                "imported_at": imported_at,
                "manual_import": True,
            }
        )
        cases.append(
            DatasetCase(
                case_id=f"imported_test_{len(cases) + 1:04d}_{case.case_id}",
                source_dataset=case.source_dataset or "uploaded_test_jsonl",
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
    return cases, warnings


def filter_experiment_cases(
    cases: list[dict[str, Any]],
    *,
    dataset_filter: str,
    label_filter: str,
    split_filter: str,
) -> list[dict[str, Any]]:
    filtered_cases = []
    for case in cases:
        metadata = case.get("metadata", {})
        dataset_key = str(metadata.get("dataset_key", "")).lower()
        split = str(metadata.get("split", "")).lower()
        fault_origin = str((case.get("label") or {}).get("fault_origin", "")).lower()
        if dataset_filter != "all" and dataset_key != dataset_filter:
            continue
        if label_filter != "all" and fault_origin != label_filter:
            continue
        if split_filter != "all" and split != split_filter:
            continue
        filtered_cases.append(case)
    return filtered_cases


def load_jsonl_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    cases = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                case = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(case, dict):
                cases.append(case)
    return cases


def parse_int_query(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        value = int(query.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 500))


def evaluate_experiment_cases(cases: list[dict[str, Any]], matrix_key: str = "target") -> dict[str, Any]:
    labeled = [case for case in cases if isinstance(case.get("label"), dict)]
    with_predictions = [
        case
        for case in labeled
        if isinstance(case.get("metadata", {}).get("prediction"), dict)
    ]
    matrix = build_confusion_matrix(with_predictions, matrix_key)
    return {
        "case_count": len(cases),
        "labeled_count": len(labeled),
        "predicted_count": len(with_predictions),
        "fault_origin_accuracy": experiment_accuracy(with_predictions, "fault_origin"),
        "target_accuracy": experiment_accuracy(with_predictions, "target"),
        "serviceability_type_accuracy": experiment_accuracy(with_predictions, "serviceability_type"),
        "replacement_recommendation_accuracy": experiment_replacement_accuracy(with_predictions),
        "label_distribution": dict(Counter((case.get("label") or {}).get("fault_origin", "unlabeled") for case in labeled)),
        "dataset_distribution": dict(Counter(case.get("metadata", {}).get("dataset_key", "unknown") for case in cases)),
        "split_distribution": dict(Counter(case.get("metadata", {}).get("split", "unknown") for case in cases)),
        "target_distribution": dict(Counter((case.get("label") or {}).get("target", "unlabeled") for case in labeled)),
        "confusion_matrix": matrix,
        "macro_precision": macro_average(matrix.get("per_class", []), "precision"),
        "macro_recall": macro_average(matrix.get("per_class", []), "recall"),
        "macro_f1": macro_average(matrix.get("per_class", []), "f1"),
    }


def summarize_experiment_corpus(cases: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [case for case in cases if isinstance(case.get("label"), dict)]
    return {
        "case_count": len(cases),
        "labeled_count": len(labeled),
        "predicted_count": sum(1 for case in cases if isinstance(case.get("metadata", {}).get("prediction"), dict)),
        "dataset_distribution": dict(Counter(case.get("metadata", {}).get("dataset_key", "unknown") for case in cases)),
        "split_distribution": dict(Counter(case.get("metadata", {}).get("split", "unknown") for case in cases)),
        "label_distribution": dict(Counter((case.get("label") or {}).get("fault_origin", "unlabeled") for case in labeled)),
        "target_distribution": dict(Counter((case.get("label") or {}).get("target", "unlabeled") for case in labeled)),
    }


def macro_average(items: list[dict[str, Any]], key: str) -> float | None:
    values = [item.get(key) for item in items if item.get(key) is not None]
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 4)


def experiment_accuracy(cases: list[dict[str, Any]], key: str) -> float | None:
    if not cases:
        return None
    total = 0
    correct = 0
    for case in cases:
        label = case.get("label") or {}
        prediction = case.get("metadata", {}).get("prediction") or {}
        if prediction.get(key) == label.get(key):
            correct += 1
        total += 1
    return round(correct / total, 4) if total else None


def experiment_replacement_accuracy(cases: list[dict[str, Any]]) -> float | None:
    if not cases:
        return None
    total = 0
    correct = 0
    for case in cases:
        label = case.get("label") or {}
        prediction = case.get("metadata", {}).get("prediction") or {}
        predicted = prediction.get("replacement_recommended")
        if predicted is None:
            continue
        expected = label.get("serviceability_type") == "replaceable_fru"
        if bool(predicted) == expected:
            correct += 1
        total += 1
    return round(correct / total, 4) if total else None


def build_confusion_matrix(cases: list[dict[str, Any]], key: str) -> dict[str, Any]:
    labels = []
    matrix_counts: dict[str, Counter[str]] = {}
    for case in cases:
        label = case.get("label") or {}
        prediction = case.get("metadata", {}).get("prediction") or {}
        expected = str(label.get(key, "unlabeled") or "unlabeled")
        predicted = str(prediction.get(key, "unpredicted") or "unpredicted")
        labels.extend([expected, predicted])
        matrix_counts.setdefault(expected, Counter())[predicted] += 1

    classes = sorted(set(labels))
    rows = []
    total = 0
    correct = 0
    for expected in classes:
        values = []
        row_total = 0
        for predicted in classes:
            count = int(matrix_counts.get(expected, Counter()).get(predicted, 0))
            values.append(count)
            row_total += count
            total += count
            if expected == predicted:
                correct += count
        rows.append({"expected": expected, "values": values, "total": row_total})

    per_class = []
    for klass in classes:
        tp = int(matrix_counts.get(klass, Counter()).get(klass, 0))
        fp = sum(int(matrix_counts.get(other, Counter()).get(klass, 0)) for other in classes if other != klass)
        fn = sum(int(count) for predicted, count in matrix_counts.get(klass, Counter()).items() if predicted != klass)
        support = tp + fn
        predicted_support = tp + fp
        precision = round(tp / predicted_support, 4) if predicted_support else (0.0 if support else None)
        recall = round(tp / support, 4) if support else None
        if precision is None or recall is None:
            f1 = None
        elif precision + recall:
            f1 = round(2 * precision * recall / (precision + recall), 4)
        else:
            f1 = 0.0
        per_class.append(
            {
                "class": klass,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": support,
            }
        )

    return {
        "key": key,
        "classes": classes,
        "rows": rows,
        "per_class": per_class,
        "total": total,
        "accuracy": round(correct / total, 4) if total else None,
    }


def summarize_experiment_case(case: dict[str, Any]) -> dict[str, Any]:
    label = case.get("label") or {}
    metadata = case.get("metadata") or {}
    logs = ((case.get("evidence") or {}).get("logs") or {})
    prediction = metadata.get("prediction") if isinstance(metadata.get("prediction"), dict) else {}
    expected_values = {
        "fault_origin": label.get("fault_origin", ""),
        "target": label.get("target", ""),
        "serviceability_type": label.get("serviceability_type", ""),
    }
    predicted_values = {
        "fault_origin": prediction.get("fault_origin", ""),
        "target": prediction.get("target", ""),
        "serviceability_type": prediction.get("serviceability_type", ""),
    }
    return {
        "case_id": case.get("case_id", ""),
        "source_dataset": case.get("source_dataset", ""),
        "dataset_key": metadata.get("dataset_key", ""),
        "split": metadata.get("split", ""),
        "line_start": metadata.get("line_start", ""),
        "line_end": metadata.get("line_end", ""),
        "timestamp": case.get("timestamp", ""),
        "fault_origin": label.get("fault_origin", ""),
        "target": label.get("target", ""),
        "serviceability_type": label.get("serviceability_type", ""),
        "confidence": label.get("confidence", ""),
        "prediction": prediction,
        "expected": expected_values,
        "predicted": predicted_values,
        "prediction_match": {
            "fault_origin": prediction.get("fault_origin") == label.get("fault_origin") if prediction else None,
            "target": prediction.get("target") == label.get("target") if prediction else None,
            "serviceability_type": prediction.get("serviceability_type") == label.get("serviceability_type") if prediction else None,
        },
        "signals": logs.get("weak_label_signals", {}),
        "event_id_counts": logs.get("event_id_counts", {}),
        "component_counts": logs.get("component_counts", {}),
        "evidence_messages": (logs.get("evidence_messages") or [])[:6],
        "raw_messages": (logs.get("raw_messages") or [])[:8],
        "manual_review_required": metadata.get("manual_review_required", False),
    }


def self_version() -> str:
    return "frontend_backend_split_healthcheck"


def build_runtime_collection_command(
    output_path: str | Path,
    hours: int,
    max_system_events: int,
    max_application_events: int,
    fault_time: str = "",
    before_fault_minutes: int = 60,
    after_fault_minutes: int = 15,
) -> list[str]:
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PROJECT_ROOT / "scripts" / "collect_runtime_info.ps1"),
        "-OutputPath",
        str(output_path),
        "-Hours",
        str(hours),
        "-MaxSystemEvents",
        str(max_system_events),
        "-MaxApplicationEvents",
        str(max_application_events),
        "-NoProgress",
    ]
    if fault_time:
        command.extend(
            [
                "-FaultTime",
                fault_time,
                "-BeforeFaultMinutes",
                str(before_fault_minutes),
                "-AfterFaultMinutes",
                str(after_fault_minutes),
            ]
        )
    return command


def run_background_job(
    kind: str,
    command: list[str],
    on_success: Any | None = None,
) -> str:
    job_id = JOBS.create(kind)

    def worker() -> None:
        run_job_command(job_id, command, on_success=on_success)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return job_id


def run_job_command(
    job_id: str,
    command: list[str],
    on_success: Any | None = None,
) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        status = "completed" if completed.returncode == 0 else "failed"
        result: Any | None = None
        if completed.returncode == 0 and on_success is not None:
            result = on_success()
        JOBS.update(
            job_id,
            status=status,
            returncode=completed.returncode,
            stdout=completed.stdout[-4000:],
            stderr=completed.stderr[-4000:],
            message="completed" if completed.returncode == 0 else "failed",
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        JOBS.update(job_id, status="failed", stderr=str(exc), message="exception")


def json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def acquire_server_lock(host: str, port: int) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / f"web_{host.replace('.', '_')}_{port}.lock"
    if lock_path.exists():
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        pid = int(existing.get("pid", 0) or 0)
        if pid and is_process_running(pid):
            raise SystemExit(
                f"Web server already appears to be running on {host}:{port} "
                f"(pid {pid}). Stop it or choose another port."
            )
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "host": host,
                "port": port,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return lock_path


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return is_windows_process_running(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_windows_process_running(pid: int) -> bool:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def main() -> int:
    args = build_parser().parse_args()
    if not WEB_ROOT.exists():
        raise SystemExit(f"Missing web root: {WEB_ROOT}")

    lock_path = acquire_server_lock(args.host, args.port)
    server = ThreadingHTTPServer((args.host, args.port), FRURequestHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Fault diagnosis research dashboard running at {url}")
    if load_collection_settings()["background"].get("enabled", False):
        BACKGROUND_COLLECTOR.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        BACKGROUND_COLLECTOR.stop()
        server.server_close()
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
