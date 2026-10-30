"""Collection storage and scheduler settings."""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "configs" / "collection_settings.json"

DEFAULT_COLLECTION_SETTINGS: dict[str, Any] = {
    "storage": {
        "active_runtime_path": "data/runtime_info.json",
        "history_dir": "data/history",
        "save_history": True,
        "filename_template": "runtime_{timestamp}.json",
        "retention_count": 30,
    },
    "background": {
        "enabled": False,
        "interval_minutes": 30,
        "collect_runtime": True,
        "scan_fru": False,
        "hours": 6,
        "max_system_events": 200,
        "max_application_events": 50,
    },
}


def load_collection_settings(
    settings_path: str | Path = DEFAULT_SETTINGS_PATH,
) -> dict[str, Any]:
    """Load settings and merge missing keys with defaults."""

    path = resolve_project_path(settings_path)
    if not path.exists():
        return copy.deepcopy(DEFAULT_COLLECTION_SETTINGS)

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Collection settings must be a JSON object.")
    return normalize_collection_settings(data)


def save_collection_settings(
    settings: dict[str, Any],
    settings_path: str | Path = DEFAULT_SETTINGS_PATH,
) -> dict[str, Any]:
    """Normalize and save collection settings."""

    normalized = normalize_collection_settings(settings)
    path = resolve_project_path(settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def normalize_collection_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = deep_merge(DEFAULT_COLLECTION_SETTINGS, settings)
    storage = merged["storage"]
    background = merged["background"]

    storage["active_runtime_path"] = normalize_path_string(
        storage.get("active_runtime_path"),
        DEFAULT_COLLECTION_SETTINGS["storage"]["active_runtime_path"],
    )
    storage["history_dir"] = normalize_path_string(
        storage.get("history_dir"),
        DEFAULT_COLLECTION_SETTINGS["storage"]["history_dir"],
    )
    storage["save_history"] = bool(storage.get("save_history", True))
    template = str(storage.get("filename_template", "") or "").strip()
    if "{timestamp}" not in template:
        template = DEFAULT_COLLECTION_SETTINGS["storage"]["filename_template"]
    storage["filename_template"] = Path(template).name
    storage["retention_count"] = clamp_int(storage.get("retention_count"), 1, 10000, 30)

    background["enabled"] = bool(background.get("enabled", False))
    background["interval_minutes"] = clamp_int(
        background.get("interval_minutes"), 1, 10080, 30
    )
    background["collect_runtime"] = bool(background.get("collect_runtime", True))
    background["scan_fru"] = bool(background.get("scan_fru", False))
    background["hours"] = clamp_int(background.get("hours"), 1, 168, 6)
    background["max_system_events"] = clamp_int(
        background.get("max_system_events"), 10, 5000, 200
    )
    background["max_application_events"] = clamp_int(
        background.get("max_application_events"), 10, 5000, 50
    )
    return merged


def deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_path_string(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def resolve_active_runtime_path(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_collection_settings()
    return resolve_project_path(settings["storage"]["active_runtime_path"])


def resolve_history_dir(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_collection_settings()
    return resolve_project_path(settings["storage"]["history_dir"])


def resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved


def relative_project_path(path: str | Path) -> str:
    resolved = resolve_project_path(path)
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def build_resolved_settings(settings: dict[str, Any]) -> dict[str, str]:
    return {
        "active_runtime_path": str(resolve_active_runtime_path(settings)),
        "active_runtime_relative": relative_project_path(
            settings["storage"]["active_runtime_path"]
        ),
        "history_dir": str(resolve_history_dir(settings)),
        "history_relative": relative_project_path(settings["storage"]["history_dir"]),
        "settings_path": str(DEFAULT_SETTINGS_PATH),
    }


def archive_runtime_snapshot(
    settings: dict[str, Any] | None = None,
    source_path: str | Path | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any] | None:
    """Copy the active runtime file into the configured history directory."""

    settings = settings or load_collection_settings()
    storage = settings["storage"]
    if not storage.get("save_history", True):
        return None

    source = resolve_project_path(source_path or resolve_active_runtime_path(settings))
    if not source.exists():
        return None

    history_dir = resolve_history_dir(settings)
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_time = timestamp or datetime.now()
    stamp = snapshot_time.strftime("%Y%m%d_%H%M%S")
    filename = Path(str(storage["filename_template"]).format(timestamp=stamp)).name
    target = history_dir / filename
    shutil.copy2(source, target)
    os.utime(target, (snapshot_time.timestamp(), snapshot_time.timestamp()))
    removed = cleanup_history(settings)
    return {
        "path": relative_project_path(target),
        "absolute_path": str(target),
        "retention_removed": removed,
    }


def cleanup_history(settings: dict[str, Any] | None = None) -> list[str]:
    """Keep only the newest managed runtime snapshots."""

    settings = settings or load_collection_settings()
    history_dir = resolve_history_dir(settings)
    if not history_dir.exists() or not history_dir.is_dir():
        return []

    template = str(settings["storage"]["filename_template"])
    prefix, suffix = template.split("{timestamp}", 1)
    files = [
        path
        for path in history_dir.iterdir()
        if path.is_file()
        and path.name.startswith(prefix)
        and path.name.endswith(suffix)
        and path.suffix.lower() == ".json"
    ]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    keep = int(settings["storage"]["retention_count"])
    removed: list[str] = []
    for path in files[keep:]:
        path.unlink()
        removed.append(relative_project_path(path))
    return removed


def list_history_snapshots(
    settings: dict[str, Any] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    settings = settings or load_collection_settings()
    history_dir = resolve_history_dir(settings)
    if not history_dir.exists() or not history_dir.is_dir():
        return []

    template = str(settings["storage"]["filename_template"])
    prefix, suffix = template.split("{timestamp}", 1)
    snapshots: list[dict[str, Any]] = []
    for path in history_dir.iterdir():
        if (
            not path.is_file()
            or not path.name.startswith(prefix)
            or not path.name.endswith(suffix)
            or path.suffix.lower() != ".json"
        ):
            continue
        stat = path.stat()
        snapshots.append(
            {
                "path": relative_project_path(path),
                "absolute_path": str(path),
                "filename": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds"
                ),
            }
        )

    snapshots.sort(key=lambda item: item["modified_at"], reverse=True)
    return snapshots[:limit]
