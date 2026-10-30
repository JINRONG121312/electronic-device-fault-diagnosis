"""Controller-side client for collecting evidence from a target-agent machine."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .crash_dump_evidence import normalize_crash_dump_evidence


DEFAULT_TIMEOUT_SECONDS = 8


class RemoteAgentError(RuntimeError):
    """Raised when a target agent cannot be reached or returns invalid data."""


def probe_target_agent(
    base_url: str,
    token: str = "",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return target-agent health and capability metadata."""

    health = request_agent_json(base_url, "/api/health", token=token, timeout=timeout)
    capabilities = request_agent_json(base_url, "/api/capabilities", token=token, timeout=timeout)
    return {
        "ok": True,
        "target_url": normalize_base_url(base_url),
        "health": health,
        "capabilities": capabilities,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def collect_from_target_agent(
    base_url: str,
    token: str,
    request_body: dict[str, Any],
    timeout: int = 45,
) -> dict[str, Any]:
    """Ask the target machine to collect a standard evidence package."""

    payload = request_agent_json(
        base_url,
        "/api/collect",
        token=token,
        timeout=timeout,
        method="POST",
        body=request_body,
    )
    runtime_info = evidence_package_to_runtime_info(payload)
    return {
        "ok": True,
        "target_url": normalize_base_url(base_url),
        "evidence_package": payload,
        "runtime_info": runtime_info,
        "collected_at": datetime.now().isoformat(timespec="seconds"),
    }


def request_agent_json(
    base_url: str,
    path: str,
    token: str = "",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = urljoin(normalize_base_url(base_url) + "/", path.lstrip("/"))
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Agent-Token"] = token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured local agent URL.
            raw = response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RemoteAgentError(f"Target agent returned HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RemoteAgentError(f"Cannot reach target agent: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RemoteAgentError("Target agent request timed out.") from exc

    try:
        data_obj = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RemoteAgentError("Target agent did not return valid JSON.") from exc
    if not isinstance(data_obj, dict):
        raise RemoteAgentError("Target agent response must be a JSON object.")
    if data_obj.get("ok") is False:
        raise RemoteAgentError(str(data_obj.get("error") or "Target agent returned an error."))
    return data_obj


def normalize_base_url(base_url: str) -> str:
    text = str(base_url or "").strip().rstrip("/")
    if not text:
        raise RemoteAgentError("Target agent URL is required.")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteAgentError("Target agent URL must start with http:// or https://.")
    if not parsed.netloc:
        raise RemoteAgentError("Target agent URL must include host and port.")
    return text


def evidence_package_to_runtime_info(package: dict[str, Any]) -> dict[str, Any]:
    """Convert a standard Evidence Package into the runtime_info shape used by the diagnosis pipeline."""

    runtime = package.get("runtime_info")
    if isinstance(runtime, dict):
        normalized = dict(runtime)
        normalized["crash_dump"] = normalize_crash_dump_evidence(
            normalized.get("crash_dump", {}),
            source="target_agent",
        )
        return normalized
    evidence = package.get("evidence") if isinstance(package.get("evidence"), dict) else {}
    inventory = evidence.get("inventory", {}) if isinstance(evidence.get("inventory"), dict) else {}
    logs = evidence.get("logs", {}) if isinstance(evidence.get("logs"), dict) else {}
    metrics = evidence.get("metrics", {}) if isinstance(evidence.get("metrics"), dict) else {}
    return {
        "generated_at": package.get("timestamp"),
        "system": inventory.get("system", {}),
        "device_inventory": inventory.get("device_inventory", {}),
        "events": logs,
        "power": metrics.get("power", {}),
        "battery": metrics.get("battery", {}),
        "storage": metrics.get("storage", {}),
        "memory": metrics.get("memory", {}),
        "network": metrics.get("network", {}),
        "thermal": metrics.get("thermal", {}),
        "tests": evidence.get("active_tests", {}),
        "crash_dump": normalize_crash_dump_evidence(evidence.get("crash_dump", {}), source="target_agent"),
        "customer_intake": {
            "fault_case_id": package.get("fault_case_id", ""),
            "symptoms": package.get("symptom", []),
        },
    }
