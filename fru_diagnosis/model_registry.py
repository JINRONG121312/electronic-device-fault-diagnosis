"""Known model registry for selecting official FRU profiles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
DEVICE_TYPE_REGISTRY_DIRS = {
    "laptop": KNOWLEDGE_ROOT / "laptops",
    "server": KNOWLEDGE_ROOT / "servers",
    "router": KNOWLEDGE_ROOT / "routers",
    "other": KNOWLEDGE_ROOT / "other_devices",
}
VENDOR_ALIASES = {
    "asus": {"asus", "asustek", "asustek_computer_inc"},
    "lenovo": {"lenovo", "lenovo_group_limited"},
}


@dataclass(frozen=True)
class KnownModelProfile:
    id: str
    vendor: str
    device_type: str
    model_family: str
    display_name: str
    config_path: Path
    manufacturer_patterns: tuple[str, ...]
    model_patterns: tuple[str, ...]
    market_name_patterns: tuple[str, ...]
    official_sources: tuple[str, ...]
    notes: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any], base_dir: Path) -> "KnownModelProfile":
        config_path = Path(raw["config_path"])
        if not config_path.is_absolute():
            config_path = base_dir / config_path

        return cls(
            id=str(raw["id"]),
            vendor=str(raw["vendor"]),
            device_type=str(raw["device_type"]),
            model_family=str(raw["model_family"]),
            display_name=str(raw["display_name"]),
            config_path=config_path,
            manufacturer_patterns=tuple(raw.get("manufacturer_patterns", [])),
            model_patterns=tuple(raw.get("model_patterns", [])),
            market_name_patterns=tuple(raw.get("market_name_patterns", [])),
            official_sources=tuple(raw.get("official_sources", [])),
            notes=tuple(raw.get("notes", [])),
        )


@dataclass(frozen=True)
class ModelMatch:
    profile: KnownModelProfile
    score: int
    reasons: tuple[str, ...]


def load_known_model_profiles(
    registry_path: str | Path | None = None,
    device_type: str | None = None,
    manufacturer: str = "",
) -> tuple[KnownModelProfile, ...]:
    paths = discover_registry_paths(
        registry_path=registry_path,
        device_type=device_type,
        manufacturer=manufacturer,
    )

    profiles: list[KnownModelProfile] = []
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        entries = raw.get("entries", [])
        profiles.extend(KnownModelProfile.from_dict(entry, PROJECT_ROOT) for entry in entries)
    return tuple(profiles)


def discover_registry_paths(
    registry_path: str | Path | None = None,
    device_type: str | None = None,
    manufacturer: str = "",
) -> tuple[Path, ...]:
    if registry_path is not None:
        return (Path(registry_path),)

    normalized_device_type = normalize_text(device_type or "")
    base_dir = DEVICE_TYPE_REGISTRY_DIRS.get(normalized_device_type)
    if base_dir is None or not base_dir.exists():
        return tuple()

    vendor_dir = find_vendor_registry_dir(base_dir, manufacturer)
    if vendor_dir is not None:
        registry = vendor_dir / "model_registry.json"
        return (registry,) if registry.exists() else tuple()

    direct_registry = base_dir / "model_registry.json"
    if direct_registry.exists():
        return (direct_registry,)

    return tuple(sorted(base_dir.rglob("model_registry.json")))


def find_vendor_registry_dir(base_dir: Path, manufacturer: str) -> Path | None:
    manufacturer_slug = slugify(manufacturer)
    if not manufacturer_slug:
        return None

    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        child_slug = slugify(child.name)
        if child_slug and (
            child_slug in manufacturer_slug or manufacturer_slug in child_slug
        ):
            return child

    for vendor, aliases in VENDOR_ALIASES.items():
        if manufacturer_slug in aliases or any(alias in manufacturer_slug for alias in aliases):
            candidate = base_dir / vendor
            if candidate.exists():
                return candidate

    return None


def find_known_model(
    device_type: str,
    manufacturer: str,
    model: str,
    display_name: str = "",
    registry_path: str | Path | None = None,
) -> ModelMatch | None:
    candidates = load_known_model_profiles(
        registry_path=registry_path,
        device_type=device_type,
        manufacturer=manufacturer,
    )
    query_text = normalize_text(" ".join([manufacturer, model, display_name]))
    normalized_device_type = normalize_text(device_type)

    best_match: ModelMatch | None = None
    for profile in candidates:
        if normalize_text(profile.device_type) != normalized_device_type:
            continue

        score = 0
        reasons: list[str] = []

        vendor_hit = first_pattern_hit(query_text, profile.manufacturer_patterns)
        if vendor_hit:
            score += 30
            reasons.append(f"manufacturer matched {vendor_hit!r}")

        model_hit = first_pattern_hit(query_text, profile.model_patterns)
        if model_hit:
            score += 60
            reasons.append(f"model matched {model_hit!r}")

        market_hit = first_pattern_hit(query_text, profile.market_name_patterns)
        if market_hit:
            score += 20
            reasons.append(f"market name matched {market_hit!r}")

        if score >= 60 and (best_match is None or score > best_match.score):
            best_match = ModelMatch(profile=profile, score=score, reasons=tuple(reasons))

    return best_match


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold())
    slug = slug.strip("_")
    return slug or "device"


def first_pattern_hit(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        normalized = normalize_text(pattern)
        if normalized and normalized in text:
            return pattern
    return None
