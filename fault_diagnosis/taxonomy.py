"""Fault diagnosis taxonomy for research-facing outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FaultOrigin:
    """Primary fault source used by diagnosis experiments."""

    id: str
    name: str
    description: str
    software_layer: bool


@dataclass(frozen=True)
class ServiceabilityOutcome:
    """How a diagnosed fault can be acted on after root-cause isolation."""

    id: str
    name: str
    description: str
    replacement_oriented: bool


FAULT_ORIGIN_TYPES: tuple[FaultOrigin, ...] = (
    FaultOrigin(
        id="driver_fault",
        name="Driver fault",
        description="Fault caused by a device driver, driver conflict, or third-party kernel module.",
        software_layer=True,
    ),
    FaultOrigin(
        id="os_fault",
        name="Operating-system fault",
        description="Fault caused by OS service, update, file corruption, scheduler, or system component.",
        software_layer=True,
    ),
    FaultOrigin(
        id="firmware_fault",
        name="Firmware fault",
        description="Fault caused by BIOS, EC, ACPI, UCSI, or firmware-level policy.",
        software_layer=True,
    ),
    FaultOrigin(
        id="configuration_fault",
        name="Configuration fault",
        description="Fault caused by disabled devices, power policy, network settings, boot settings, or service configuration.",
        software_layer=True,
    ),
    FaultOrigin(
        id="external_environment_fault",
        name="External environment fault",
        description="Fault caused by charger, cable, dock, router, peripheral, outlet, or operating environment.",
        software_layer=False,
    ),
    FaultOrigin(
        id="hardware_fault",
        name="Hardware fault",
        description="Fault caused by a physical component, board path, or replaceable hardware module.",
        software_layer=False,
    ),
    FaultOrigin(
        id="mixed_or_uncertain",
        name="Mixed or uncertain fault",
        description="Evidence is insufficient or points to multiple interacting sources.",
        software_layer=False,
    ),
)

SERVICEABILITY_TYPES: tuple[ServiceabilityOutcome, ...] = (
    ServiceabilityOutcome(
        id="software_repairable",
        name="Software repairable",
        description="Repair through driver update, rollback, reinstall, OS repair, or service recovery.",
        replacement_oriented=False,
    ),
    ServiceabilityOutcome(
        id="firmware_repairable",
        name="Firmware repairable",
        description="Repair through BIOS/EC update, firmware setting restore, or firmware policy correction.",
        replacement_oriented=False,
    ),
    ServiceabilityOutcome(
        id="configuration_repairable",
        name="Configuration repairable",
        description="Repair through configuration correction, policy reset, service enablement, or resource cleanup.",
        replacement_oriented=False,
    ),
    ServiceabilityOutcome(
        id="externally_reproducible",
        name="Externally reproducible",
        description="Validate under known-good external power, network, cable, dock, or peripheral environment.",
        replacement_oriented=False,
    ),
    ServiceabilityOutcome(
        id="replaceable_hardware",
        name="Replaceable hardware",
        description="Fault likely requires replacement of a FRU, service assembly, or external part.",
        replacement_oriented=True,
    ),
    ServiceabilityOutcome(
        id="need_more_evidence",
        name="Need more evidence",
        description="Current evidence is not sufficient; active evidence collection is recommended.",
        replacement_oriented=False,
    ),
)


def classify_fault_origin(candidate_type: str, category: str = "") -> str:
    """Map legacy candidate/serviceability labels to the research taxonomy."""

    text = f"{candidate_type} {category}".casefold()
    if any(token in text for token in ["driver", "os", "software"]):
        return "driver_fault" if "driver" in text else "os_fault"
    if any(token in text for token in ["firmware", "bios", "acpi", "ucsi"]):
        return "firmware_fault"
    if "config" in text or "policy" in text:
        return "configuration_fault"
    if any(token in text for token in ["external", "environment", "adapter", "router", "cable"]):
        return "external_environment_fault"
    if any(token in text for token in ["replaceable", "hardware", "assembly", "subsystem", "fru"]):
        return "hardware_fault"
    return "mixed_or_uncertain"

