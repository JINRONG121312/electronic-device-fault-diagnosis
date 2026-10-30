"""Load and validate FRU configuration files.

The configuration layer keeps device-specific FRU definitions outside the
diagnosis engine. A new device can be supported by adding a profile file
instead of rewriting inference logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SUPPORTED_FRU_CATEGORIES = {
    "PowerFRU",
    "ComputeFRU",
    "StorageFRU",
    "CommunicationFRU",
    "ThermalFRU",
    "DisplayFRU",
    "InputFRU",
    "InterfaceFRU",
    "SensorFRU",
    "MainboardFRU",
    "OtherFRU",
}

SUPPORTED_EVIDENCE_TYPES = {
    "log_pattern",
    "metric_threshold",
    "health_warning",
    "device_state",
    "active_test",
    "symptom",
}

SUPPORTED_DIAGNOSIS_ROLES = {
    "target_fru",
    "subsystem",
    "evidence_only",
}

SUPPORTED_VERIFICATION_STATUSES = {
    "official_service_manual",
    "official_spec",
    "detected_only",
    "model_inferred",
    "unverified",
}

SUPPORTED_SERVICEABILITY_TYPES = {
    "replaceable_fru",
    "serviceable_assembly",
    "non_replaceable_subsystem",
    "non_fru_fault",
    "external_part",
    "maintenance_condition",
}

SUPPORTED_SERVICEABILITY_LEVELS = {
    "field_replaceable",
    "service_center_replaceable",
    "assembly_replaceable",
    "not_individually_replaceable",
    "external",
    "not_replaceable",
}

SUPPORTED_COST_LEVELS = {"low", "medium", "high", "unknown"}

SUPPORTED_CONFIDENCE_LEVELS = {"low", "medium", "high"}


class FRUConfigError(ValueError):
    """Raised when an FRU profile is missing required or valid fields."""


@dataclass(frozen=True)
class EvidenceRule:
    """A rule describing evidence that points to one FRU."""

    id: str
    evidence_type: str
    description: str
    weight: float = 1.0
    source: str | None = None
    pattern: str | None = None
    metric: str | None = None
    operator: str | None = None
    threshold: float | int | str | bool | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str) -> "EvidenceRule":
        require_keys(raw, ["id", "evidence_type", "description"], path)

        evidence_type = require_str(raw, "evidence_type", path)
        if evidence_type not in SUPPORTED_EVIDENCE_TYPES:
            raise FRUConfigError(
                f"{path}.evidence_type must be one of "
                f"{sorted(SUPPORTED_EVIDENCE_TYPES)}, got {evidence_type!r}"
            )

        weight = raw.get("weight", 1.0)
        if not isinstance(weight, (int, float)):
            raise FRUConfigError(f"{path}.weight must be a number")
        if weight <= 0:
            raise FRUConfigError(f"{path}.weight must be greater than 0")

        return cls(
            id=require_str(raw, "id", path),
            evidence_type=evidence_type,
            description=require_str(raw, "description", path),
            weight=float(weight),
            source=optional_str(raw, "source", path),
            pattern=optional_str(raw, "pattern", path),
            metric=optional_str(raw, "metric", path),
            operator=optional_str(raw, "operator", path),
            threshold=raw.get("threshold"),
        )


@dataclass(frozen=True)
class Serviceability:
    """How a diagnosis candidate maps to a repair action."""

    type: str
    level: str
    replacement_target: str | None = None
    parent_assembly: str | None = None
    requires_disassembly: bool = True
    cost_level: str = "unknown"
    confidence_required: str = "high"
    action: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any] | None,
        path: str,
        *,
        fru_id: str,
        replaceable: bool,
        diagnosis_role: str,
    ) -> "Serviceability":
        if raw is None:
            return default_serviceability(
                fru_id=fru_id,
                replaceable=replaceable,
                diagnosis_role=diagnosis_role,
            )
        if not isinstance(raw, dict):
            raise FRUConfigError(f"{path}.serviceability must be an object")

        service_type = raw.get("type")
        if service_type is None:
            service_type = default_serviceability_type(replaceable, diagnosis_role)
        if service_type not in SUPPORTED_SERVICEABILITY_TYPES:
            raise FRUConfigError(
                f"{path}.serviceability.type must be one of "
                f"{sorted(SUPPORTED_SERVICEABILITY_TYPES)}, got {service_type!r}"
            )

        level = raw.get("level")
        if level is None:
            level = default_serviceability_level(str(service_type))
        if level not in SUPPORTED_SERVICEABILITY_LEVELS:
            raise FRUConfigError(
                f"{path}.serviceability.level must be one of "
                f"{sorted(SUPPORTED_SERVICEABILITY_LEVELS)}, got {level!r}"
            )

        cost_level = raw.get("cost_level", "unknown")
        if cost_level not in SUPPORTED_COST_LEVELS:
            raise FRUConfigError(
                f"{path}.serviceability.cost_level must be one of "
                f"{sorted(SUPPORTED_COST_LEVELS)}, got {cost_level!r}"
            )

        confidence_required = raw.get("confidence_required", "high")
        if confidence_required not in SUPPORTED_CONFIDENCE_LEVELS:
            raise FRUConfigError(
                f"{path}.serviceability.confidence_required must be one of "
                f"{sorted(SUPPORTED_CONFIDENCE_LEVELS)}, got {confidence_required!r}"
            )

        requires_disassembly = raw.get("requires_disassembly", True)
        if not isinstance(requires_disassembly, bool):
            raise FRUConfigError(f"{path}.serviceability.requires_disassembly must be a boolean")

        notes = raw.get("notes", [])
        if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
            raise FRUConfigError(f"{path}.serviceability.notes must be a list of strings")

        return cls(
            type=str(service_type),
            level=str(level),
            replacement_target=optional_str(raw, "replacement_target", f"{path}.serviceability"),
            parent_assembly=optional_str(raw, "parent_assembly", f"{path}.serviceability"),
            requires_disassembly=requires_disassembly,
            cost_level=str(cost_level),
            confidence_required=str(confidence_required),
            action=str(raw.get("action", "")),
            notes=tuple(notes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "level": self.level,
            "replacement_target": self.replacement_target,
            "parent_assembly": self.parent_assembly,
            "requires_disassembly": self.requires_disassembly,
            "cost_level": self.cost_level,
            "confidence_required": self.confidence_required,
            "action": self.action,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class FRUModule:
    """A field-replaceable unit defined by a device profile."""

    id: str
    name: str
    category: str
    replaceable: bool = True
    description: str = ""
    diagnosis_role: str = "target_fru"
    verification_status: str = "unverified"
    aliases: tuple[str, ...] = field(default_factory=tuple)
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    evidence_rules: tuple[EvidenceRule, ...] = field(default_factory=tuple)
    serviceability: Serviceability | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str) -> "FRUModule":
        require_keys(raw, ["id", "name", "category"], path)

        category = require_str(raw, "category", path)
        if category not in SUPPORTED_FRU_CATEGORIES:
            raise FRUConfigError(
                f"{path}.category must be one of "
                f"{sorted(SUPPORTED_FRU_CATEGORIES)}, got {category!r}"
            )

        replaceable = raw.get("replaceable", True)
        if not isinstance(replaceable, bool):
            raise FRUConfigError(f"{path}.replaceable must be a boolean")

        diagnosis_role = raw.get("diagnosis_role", "target_fru")
        if diagnosis_role not in SUPPORTED_DIAGNOSIS_ROLES:
            raise FRUConfigError(
                f"{path}.diagnosis_role must be one of "
                f"{sorted(SUPPORTED_DIAGNOSIS_ROLES)}, got {diagnosis_role!r}"
            )

        verification_status = raw.get("verification_status", "unverified")
        if verification_status not in SUPPORTED_VERIFICATION_STATUSES:
            raise FRUConfigError(
                f"{path}.verification_status must be one of "
                f"{sorted(SUPPORTED_VERIFICATION_STATUSES)}, "
                f"got {verification_status!r}"
            )

        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) for item in aliases
        ):
            raise FRUConfigError(f"{path}.aliases must be a list of strings")

        source_refs = raw.get("source_refs", [])
        if not isinstance(source_refs, list) or not all(
            isinstance(item, str) for item in source_refs
        ):
            raise FRUConfigError(f"{path}.source_refs must be a list of strings")

        evidence_rules = raw.get("evidence_rules", [])
        if not isinstance(evidence_rules, list):
            raise FRUConfigError(f"{path}.evidence_rules must be a list")

        parsed_rules = tuple(
            EvidenceRule.from_dict(rule, f"{path}.evidence_rules[{index}]")
            for index, rule in enumerate(evidence_rules)
        )

        return cls(
            id=require_str(raw, "id", path),
            name=require_str(raw, "name", path),
            category=category,
            replaceable=replaceable,
            description=str(raw.get("description", "")),
            diagnosis_role=diagnosis_role,
            verification_status=verification_status,
            aliases=tuple(aliases),
            source_refs=tuple(source_refs),
            evidence_rules=parsed_rules,
            serviceability=Serviceability.from_dict(
                raw.get("serviceability"),
                path,
                fru_id=require_str(raw, "id", path),
                replaceable=replaceable,
                diagnosis_role=diagnosis_role,
            ),
        )


@dataclass(frozen=True)
class DeviceProfile:
    """A complete FRU profile for one electronic information device type."""

    device_type: str
    display_name: str
    version: str
    fru_list: tuple[FRUModule, ...]
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str = "<profile>") -> "DeviceProfile":
        require_keys(raw, ["device_type", "display_name", "version", "fru_list"], path)

        fru_list = raw.get("fru_list")
        if not isinstance(fru_list, list) or not fru_list:
            raise FRUConfigError(f"{path}.fru_list must be a non-empty list")

        parsed_frus = tuple(
            FRUModule.from_dict(fru, f"{path}.fru_list[{index}]")
            for index, fru in enumerate(fru_list)
        )

        profile = cls(
            device_type=require_str(raw, "device_type", path),
            display_name=require_str(raw, "display_name", path),
            version=require_str(raw, "version", path),
            description=str(raw.get("description", "")),
            metadata=dict(raw.get("metadata", {})),
            fru_list=parsed_frus,
        )
        validate_device_profile(profile)
        return profile

    def get_fru(self, fru_id: str) -> FRUModule:
        for fru in self.fru_list:
            if fru.id == fru_id:
                return fru
        raise KeyError(f"Unknown FRU id: {fru_id}")

    def frus_by_category(self, category: str) -> tuple[FRUModule, ...]:
        return tuple(fru for fru in self.fru_list if fru.category == category)

    def replaceable_frus(self) -> tuple[FRUModule, ...]:
        return tuple(
            fru
            for fru in self.fru_list
            if is_serviceable_replacement_target(fru)
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "device_type": self.device_type,
            "display_name": self.display_name,
            "version": self.version,
            "fru_count": len(self.fru_list),
            "replaceable_fru_count": len(self.replaceable_frus()),
            "serviceability_counts": serviceability_counts(self.fru_list),
            "categories": sorted({fru.category for fru in self.fru_list}),
        }


def load_device_profile(config_path: str | Path) -> DeviceProfile:
    """Load one device FRU profile from JSON or YAML."""

    path = Path(config_path)
    if not path.exists():
        raise FRUConfigError(f"FRU profile does not exist: {path}")
    if not path.is_file():
        raise FRUConfigError(f"FRU profile is not a file: {path}")

    raw = load_raw_config(path)
    if not isinstance(raw, dict):
        raise FRUConfigError("FRU profile root must be an object")
    return DeviceProfile.from_dict(raw, path=str(path))


def load_raw_config(path: Path) -> Any:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix == ".json":
        return json.loads(text)

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise FRUConfigError(
                "YAML profiles require PyYAML. Install it or use JSON profiles."
            ) from exc
        return yaml.safe_load(text)

    raise FRUConfigError(
        f"Unsupported profile format {suffix!r}. Use .json, .yaml, or .yml."
    )


def validate_device_profile(profile: DeviceProfile) -> None:
    """Validate cross-FRU constraints that need the parsed profile."""

    fru_ids = [fru.id for fru in profile.fru_list]
    duplicate_fru_ids = find_duplicates(fru_ids)
    if duplicate_fru_ids:
        raise FRUConfigError(f"Duplicate FRU ids: {sorted(duplicate_fru_ids)}")

    evidence_ids: list[str] = []
    for fru in profile.fru_list:
        evidence_ids.extend(rule.id for rule in fru.evidence_rules)
    duplicate_evidence_ids = find_duplicates(evidence_ids)
    if duplicate_evidence_ids:
        raise FRUConfigError(
            f"Duplicate evidence rule ids: {sorted(duplicate_evidence_ids)}"
        )


def default_serviceability(
    *,
    fru_id: str,
    replaceable: bool,
    diagnosis_role: str,
) -> Serviceability:
    service_type = default_serviceability_type(replaceable, diagnosis_role)
    return Serviceability(
        type=service_type,
        level=default_serviceability_level(service_type),
        replacement_target=fru_id if service_type in {"replaceable_fru", "serviceable_assembly"} else None,
        parent_assembly=None if replaceable else "motherboard",
        requires_disassembly=service_type not in {"external_part", "non_fru_fault", "maintenance_condition"},
        cost_level="unknown",
        confidence_required="high",
        action=default_service_action(service_type, fru_id),
        notes=(),
    )


def default_serviceability_type(replaceable: bool, diagnosis_role: str) -> str:
    if diagnosis_role == "subsystem":
        return "non_replaceable_subsystem"
    if replaceable:
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


def is_serviceable_replacement_target(fru: FRUModule) -> bool:
    serviceability = fru.serviceability
    service_type = serviceability.type if serviceability else default_serviceability_type(
        fru.replaceable,
        fru.diagnosis_role,
    )
    return fru.diagnosis_role == "target_fru" and service_type in {
        "replaceable_fru",
        "serviceable_assembly",
        "external_part",
    }


def serviceability_counts(frus: tuple[FRUModule, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fru in frus:
        service_type = (
            fru.serviceability.type
            if fru.serviceability
            else default_serviceability_type(fru.replaceable, fru.diagnosis_role)
        )
        counts[service_type] = counts.get(service_type, 0) + 1
    return dict(sorted(counts.items()))


def find_duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def require_keys(raw: dict[str, Any], keys: list[str], path: str) -> None:
    for key in keys:
        if key not in raw:
            raise FRUConfigError(f"{path}.{key} is required")


def require_str(raw: dict[str, Any], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FRUConfigError(f"{path}.{key} must be a non-empty string")
    return value


def optional_str(raw: dict[str, Any], key: str, path: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise FRUConfigError(f"{path}.{key} must be a non-empty string when provided")
    return value
