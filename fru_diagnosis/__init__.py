"""Compatibility helpers for device-serviceability diagnosis.

The research-facing namespace is :mod:`fault_diagnosis`. This package remains
in place for the current dashboard, device profiles, and FRU compatibility.
"""

from .fru_config import (
    DeviceProfile,
    EvidenceRule,
    FRUConfigError,
    FRUModule,
    Serviceability,
    load_device_profile,
    validate_device_profile,
)

__all__ = [
    "DeviceProfile",
    "EvidenceRule",
    "FRUConfigError",
    "FRUModule",
    "Serviceability",
    "load_device_profile",
    "validate_device_profile",
]
