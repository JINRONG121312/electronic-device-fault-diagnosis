"""Heterogeneous diagnostic graph construction.

The graph is deliberately plain JSON so it can be used by the dashboard,
dataset experiments, and later GNN-based implementations without adding a
runtime dependency. Nodes represent evidence, components, candidates, and fault
classes. Edges carry typed support or contradiction relations.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Iterable

from .crash_diagnosis import diagnose_crash_dump
from .crash_dump_evidence import crash_dump_is_available
from .datasets import DatasetCase
from .log_parsers import enrich_log_evidence
from .log_noise_reduction import event_bucket_actionable_count, normalize_template


FAULT_CLASSES = (
    "driver_fault",
    "os_fault",
    "firmware_fault",
    "configuration_fault",
    "external_environment_fault",
    "hardware_fault",
    "data_or_filesystem_fault",
    "mixed_or_uncertain",
    "no_fault_observed",
)

EVIDENCE_SECTIONS = (
    "power",
    "battery",
    "storage",
    "memory",
    "network",
    "thermal",
    "performance",
    "display",
    "camera",
    "input",
    "audio",
    "usb",
    "mainboard",
    "device_inventory",
)

NEGATIVE_TEST_VALUES = {"failed", "fail", "error", "abnormal", "not_detected", "speaker_failed"}
POSITIVE_TEST_VALUES = {"passed", "pass", "ok", "normal", "not_applicable", "detected"}

TOKEN_TARGETS: tuple[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("driver", "stack", "ndis", "nvlddmkm", "igfx", "netwtw", "module"),
        ("driver_or_os_fault",),
        ("driver_fault",),
    ),
    (
        ("service control", "service", "daemon", "launchd", "trustedinstaller", "cbs", "wmi", "hresult"),
        ("os_fault", "driver_or_os_fault"),
        ("os_fault",),
    ),
    (
        ("windowsupdateagent", "system file", "appcrash", "activation", "security-spp"),
        ("os_fault",),
        ("os_fault",),
    ),
    (
        ("configuration", "config", "permission denied", "disabled", "policy", "invalid", "missing", "not found"),
        ("configuration_fault", "firmware_or_config_fault"),
        ("configuration_fault",),
    ),
    (
        ("bios", "firmware", "acpi", "ucsi", "ec"),
        ("firmware_or_config_fault",),
        ("firmware_fault",),
    ),
    (
        ("ntfs", "filesystem", "file system", "low disk", "volume", "corrupt"),
        ("data_or_filesystem_fault", "m2_ssd_module"),
        ("data_or_filesystem_fault",),
    ),
    (
        ("disk", "nvme", "smart", "bad block", "stornvme", "storahci", "storage"),
        ("m2_ssd_module", "motherboard"),
        ("hardware_fault",),
    ),
    (
        ("memory", "whea", "bugcheck", "machine check", "uncorrectable"),
        ("ram_module", "motherboard"),
        ("hardware_fault",),
    ),
    (
        ("battery", "charge", "adapter", "kernel-power", "power"),
        ("battery_pack", "power_adapter"),
        ("hardware_fault", "external_environment_fault"),
    ),
    (
        ("thermal", "overheat", "throttle", "fan"),
        ("fan_module", "heat_sink", "maintenance_condition_fault"),
        ("hardware_fault",),
    ),
    (
        ("wlan", "wifi", "wi-fi", "network", "bluetooth", "gateway", "router"),
        ("wlan_module", "external_environment_fault"),
        ("external_environment_fault",),
    ),
    (
        ("display", "graphics", "dxgkrnl", "video", "gpu", "monitor"),
        ("display_panel_module", "driver_or_os_fault"),
        ("driver_fault", "hardware_fault"),
    ),
    (
        ("audio", "speaker", "sound"),
        ("speaker_module", "driver_or_os_fault"),
        ("hardware_fault", "driver_fault"),
    ),
    (
        ("usb", "descriptor", "code 43", "disconnect", "reconnect", "type-c"),
        ("io_board", "connector_or_interconnect_fault"),
        ("hardware_fault",),
    ),
    (
        ("external", "dock", "cable", "outlet", "peripheral", "ambient"),
        ("external_environment_fault",),
        ("external_environment_fault",),
    ),
)


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._edge_keys: set[tuple[str, str, str]] = set()

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        *,
        prior: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if node_id in self.nodes:
            existing = self.nodes[node_id]
            existing["prior"] = max(float(existing.get("prior", 0.0) or 0.0), prior)
            existing.setdefault("metadata", {}).update(metadata or {})
            return
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "prior": round(max(0.0, prior), 4),
            "metadata": metadata or {},
        }

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        marker = (source, target, edge_type)
        if marker in self._edge_keys:
            for edge in self.edges:
                if (edge["source"], edge["target"], edge["type"]) == marker:
                    edge["weight"] = round(max(float(edge["weight"]), weight), 4)
                    edge.setdefault("metadata", {}).update(metadata or {})
                    break
            return
        self._edge_keys.add(marker)
        self.edges.append(
            {
                "source": source,
                "target": target,
                "type": edge_type,
                "weight": round(weight, 4),
                "metadata": metadata or {},
            }
        )

    def build(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        node_type_counts = Counter(node["type"] for node in self.nodes.values())
        edge_type_counts = Counter(edge["type"] for edge in self.edges)
        return {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "metadata": {
                "method": "heterogeneous_diagnostic_graph",
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "node_type_counts": dict(node_type_counts),
                "edge_type_counts": dict(edge_type_counts),
                **(metadata or {}),
            },
        }


def build_diagnostic_graph(
    profile: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    *,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a graph from a profile/runtime pair."""

    profile = profile or {}
    runtime = runtime or {}
    builder = GraphBuilder()
    builder.add_node("case:current", "case", "current case", prior=1.0)
    add_fault_class_nodes(builder)
    add_candidate_nodes(builder, profile, candidates or [])
    add_runtime_log_nodes(builder, runtime)
    add_trace_nodes(builder, runtime)
    add_inventory_nodes(builder, runtime)
    add_metric_nodes(builder, runtime)
    add_active_test_nodes(builder, runtime)
    add_crash_dump_nodes(builder, runtime)
    add_boundary_context_nodes(builder, runtime)
    return builder.build(
        {
            "profile_id": profile.get("profile_id", ""),
            "runtime_has_events": bool(runtime.get("events") or runtime.get("logs")),
            "candidate_count": len(candidates or []),
        }
    )


def build_diagnostic_graph_from_case(
    case: DatasetCase,
    profile: dict[str, Any] | None = None,
    *,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a graph directly from a normalized dataset case."""

    return build_diagnostic_graph(
        profile or {},
        runtime_from_case(case),
        candidates=candidates,
    )


def runtime_from_case(case: DatasetCase) -> dict[str, Any]:
    evidence = case.evidence
    runtime = {
        "case_id": case.case_id,
        "system": evidence.inventory.get("system", {}),
        "bios": evidence.inventory.get("bios", {}),
        "mainboard": evidence.inventory.get("mainboard", {}),
        "device_inventory": evidence.inventory.get("device_inventory", evidence.inventory),
        "events": evidence.logs.get("events", {}),
        "logs": evidence.logs,
        "traces": evidence.traces,
        "tests": evidence.active_tests,
        "crash_dump": evidence.crash_dump,
        "repair_result": evidence.repair_result,
        "alignment": evidence.alignment,
        "quality": evidence.quality,
        "boundary": evidence.boundary,
    }
    for section, value in evidence.metrics.items():
        if isinstance(value, dict):
            runtime[section] = value
    return runtime


def add_fault_class_nodes(builder: GraphBuilder) -> None:
    for fault_class in FAULT_CLASSES:
        builder.add_node(
            f"fault:{fault_class}",
            "fault_class",
            fault_class,
            metadata={"fault_class": fault_class},
        )


def add_candidate_nodes(
    builder: GraphBuilder,
    profile: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> None:
    for fru in profile.get("fru_list", []) or []:
        fru_id = str(fru.get("id", "") or "")
        if not fru_id:
            continue
        node_id = f"candidate:{fru_id}"
        builder.add_node(
            node_id,
            "candidate",
            fru.get("name") or fru_id,
            metadata={
                "candidate": fru_id,
                "candidate_type": default_candidate_type(fru),
                "category": fru.get("category", ""),
                "source": "device_profile",
            },
        )
        link_candidate_to_fault(builder, node_id, fru_id, default_candidate_type(fru), str(fru.get("category", "")))

    for candidate in candidates:
        candidate_id = str(candidate.get("fru_id") or candidate.get("candidate") or "")
        if not candidate_id:
            continue
        node_id = f"candidate:{candidate_id}"
        builder.add_node(
            node_id,
            "candidate",
            candidate.get("fru_name") or candidate_id,
            prior=float(candidate.get("rank_score", 0) or 0) / 1000.0,
            metadata={
                "candidate": candidate_id,
                "candidate_type": candidate.get("candidate_type", ""),
                "category": candidate.get("category", ""),
                "source": "candidate_ranking",
                "rank_score": candidate.get("rank_score", 0),
            },
        )
        link_candidate_to_fault(
            builder,
            node_id,
            candidate_id,
            str(candidate.get("candidate_type", "")),
            str(candidate.get("category", "")),
        )


def default_candidate_type(fru: dict[str, Any]) -> str:
    serviceability = fru.get("serviceability", {})
    if isinstance(serviceability, dict) and serviceability.get("type"):
        return str(serviceability["type"])
    if fru.get("diagnosis_role") == "subsystem":
        return "non_replaceable_subsystem"
    if fru.get("replaceable", True):
        return "replaceable_fru"
    return "non_replaceable_subsystem"


def link_candidate_to_fault(
    builder: GraphBuilder,
    candidate_node: str,
    candidate_id: str,
    candidate_type: str,
    category: str,
) -> None:
    for fault_class in candidate_fault_classes(candidate_id, candidate_type, category):
        builder.add_edge(
            candidate_node,
            f"fault:{fault_class}",
            "maps_to_fault",
            weight=0.85,
            metadata={"reason": "candidate taxonomy mapping"},
        )


def candidate_fault_classes(candidate_id: str, candidate_type: str, category: str = "") -> list[str]:
    text = f"{candidate_id} {candidate_type} {category}".casefold()
    if "driver" in text:
        return ["driver_fault", "os_fault"]
    if "os_fault" in text or "software_or_os" in text:
        return ["os_fault"]
    if "firmware" in text or "bios" in text or "acpi" in text:
        return ["firmware_fault"]
    if "config" in text or "policy" in text:
        return ["configuration_fault"]
    if "external" in text or "environment" in text or "adapter" in text:
        return ["external_environment_fault"]
    if "filesystem" in text or "data" in text or "low_space" in text:
        return ["data_or_filesystem_fault"]
    if "maintenance" in text or "connector" in text or "multi_fault" in text:
        return ["mixed_or_uncertain"]
    if any(token in text for token in ["replaceable", "assembly", "hardware", "fru", "module", "subsystem"]):
        return ["hardware_fault"]
    return ["mixed_or_uncertain"]


def add_runtime_log_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    events = runtime.get("events", {}) if isinstance(runtime.get("events"), dict) else {}
    for bucket_name, bucket in event_buckets(events).items():
        add_event_bucket(builder, bucket_name, bucket)

    logs = runtime.get("logs", {}) if isinstance(runtime.get("logs"), dict) else {}
    if logs and not event_buckets(events):
        add_loghub_style_logs(builder, logs)


def add_event_bucket(builder: GraphBuilder, bucket_name: str, bucket: dict[str, Any]) -> None:
    actionable_count = event_bucket_actionable_count(bucket_name, bucket)
    raw_count = safe_int(bucket.get("total_count")) or safe_int(bucket.get("error_count")) + safe_int(bucket.get("warning_count"))
    bucket_node = f"component:{slug(bucket_name)}"
    builder.add_node(bucket_node, "component", bucket_name, metadata={"source": "events"})
    builder.add_edge("case:current", bucket_node, "contains", weight=0.2)
    samples = bucket.get("samples", []) if isinstance(bucket.get("samples"), list) else []
    if not samples and raw_count:
        samples = [{"message_excerpt": bucket_name, "provider": bucket_name}]
    for index, sample in enumerate(samples[:8]):
        text = sample_to_text(sample)
        signature = sample_signature(sample, fallback=f"{bucket_name}:{index}")
        node_id = f"log:{signature}"
        prior = min(1.0, 0.25 + actionable_count * 0.12) if actionable_count else 0.05
        builder.add_node(
            node_id,
            "log_template",
            text[:120] or bucket_name,
            prior=prior,
            metadata={
                "bucket": bucket_name,
                "raw_count": raw_count,
                "actionable_count": actionable_count,
                "sample": sample,
            },
        )
        builder.add_edge("case:current", node_id, "contains", weight=0.3)
        builder.add_edge(node_id, bucket_node, "emitted_by", weight=0.4)
        link_text_to_targets(builder, node_id, f"{bucket_name} {text}", base_weight=0.75 if actionable_count else 0.25)


def add_loghub_style_logs(builder: GraphBuilder, logs: dict[str, Any]) -> None:
    logs = enrich_log_evidence(logs, parser_name=str(logs.get("preferred_log_parser", "drain") or "drain"))
    component_counts = logs.get("component_counts", {}) if isinstance(logs.get("component_counts"), dict) else {}
    for component, count in sorted(component_counts.items(), key=lambda item: item[1], reverse=True)[:12]:
        component_node = f"component:{slug(component)}"
        builder.add_node(component_node, "component", str(component), metadata={"count": count, "source": "loghub"})
        builder.add_edge("case:current", component_node, "contains", weight=0.15)

    noise_profile = logs.get("noise_reduction", {}) if isinstance(logs.get("noise_reduction"), dict) else {}
    actionable_count = safe_int(logs.get("actionable_warning_error_count"), safe_int(noise_profile.get("actionable_event_count")))
    template_counts = logs.get("event_template_counts", {}) if isinstance(logs.get("event_template_counts"), dict) else {}
    for template, count in sorted(template_counts.items(), key=lambda item: item[1], reverse=True)[:20]:
        text = str(template)
        node_id = f"log:{stable_hash(normalize_template(text))}"
        prior = 0.1 if actionable_count == 0 else min(1.0, 0.2 + safe_int(count) * 0.04)
        builder.add_node(
            node_id,
            "log_template",
            text[:120],
            prior=prior,
            metadata={"raw_count": count, "actionable_count": actionable_count, "source": "loghub_template"},
        )
        builder.add_edge("case:current", node_id, "contains", weight=0.25)
        link_text_to_targets(builder, node_id, text, base_weight=0.7 if actionable_count else 0.1)

    weak_signals = logs.get("weak_label_signals", {}) if isinstance(logs.get("weak_label_signals"), dict) else {}
    for name, terms in weak_signals.items():
        if not isinstance(terms, list) or not terms:
            continue
        node_id = f"signal:{slug(name)}"
        text = " ".join(str(term) for term in terms)
        builder.add_node(node_id, "weak_signal", name, prior=0.25, metadata={"terms": terms})
        builder.add_edge("case:current", node_id, "contains", weight=0.2)
        link_text_to_targets(builder, node_id, text, base_weight=0.55)

    if actionable_count == 0:
        node_id = "signal:no_actionable_log_event"
        builder.add_node(node_id, "weak_signal", "no actionable log event", prior=0.4)
        builder.add_edge(node_id, "fault:no_fault_observed", "supports_fault", weight=0.8)


def add_trace_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    """Add trace spans without treating transport failures as hardware evidence."""

    traces = runtime.get("traces", {}) if isinstance(runtime.get("traces"), dict) else {}
    spans = traces.get("spans", traces.get("records", []))
    if not isinstance(spans, list):
        return

    for index, span in enumerate(spans[:200]):
        text = sample_to_text(span)
        if not text:
            continue
        status = str(span.get("status_code", "")) if isinstance(span, dict) else ""
        failed = status and status not in {"0", "200", "201", "202", "204", "ok", "OK"}
        node_id = f"trace:{stable_hash(text or str(index))}"
        builder.add_node(
            node_id,
            "trace_span",
            text[:160],
            prior=0.75 if failed else 0.15,
            metadata={"span": span, "status_code": status, "failed": bool(failed)},
        )
        builder.add_edge("case:current", node_id, "contains", weight=0.25)
        if failed:
            add_support_to_fault(builder, node_id, "os_fault", 0.45, "failed trace span")
            add_support_to_fault(builder, node_id, "external_environment_fault", 0.35, "failed trace span")
        link_text_to_targets(builder, node_id, text, base_weight=0.55 if failed else 0.1)


def add_inventory_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    inventory = runtime.get("device_inventory", {}) if isinstance(runtime.get("device_inventory"), dict) else {}
    problem_devices = inventory.get("problem_devices", []) if isinstance(inventory.get("problem_devices"), list) else []
    for index, device in enumerate(problem_devices[:12]):
        text = sample_to_text(device)
        node_id = f"inventory:{stable_hash(text or str(index))}"
        builder.add_node(node_id, "inventory_signal", text[:120] or "problem device", prior=0.55, metadata={"device": device})
        builder.add_edge("case:current", node_id, "contains", weight=0.25)
        link_text_to_targets(builder, node_id, text, base_weight=0.7)


def add_metric_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    for section in EVIDENCE_SECTIONS:
        value = runtime.get(section)
        if not isinstance(value, dict):
            continue
        for path, leaf in iter_leaf_values(value, prefix=section):
            signal = metric_signal(path, leaf)
            if not signal:
                continue
            node_id = f"metric:{stable_hash(path)}"
            builder.add_node(node_id, "metric_signal", path, prior=signal["prior"], metadata={"value": leaf})
            builder.add_edge("case:current", node_id, "contains", weight=0.2)
            for candidate in signal["candidates"]:
                add_support_to_candidate(builder, node_id, candidate, signal["weight"], "metric anomaly")
            for fault_class in signal["fault_classes"]:
                add_support_to_fault(builder, node_id, fault_class, signal["weight"], "metric anomaly")


def add_active_test_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    tests = runtime.get("tests", {}) if isinstance(runtime.get("tests"), dict) else {}
    for path, value in iter_leaf_values(tests, prefix="tests"):
        text = str(value).casefold()
        if value in {None, "", "not_run", "unknown"}:
            continue
        node_id = f"active_test:{stable_hash(path)}"
        failed = any(token in text for token in NEGATIVE_TEST_VALUES)
        passed = any(token in text for token in POSITIVE_TEST_VALUES)
        prior = 0.85 if failed else 0.25
        builder.add_node(node_id, "active_test", path, prior=prior, metadata={"value": value})
        builder.add_edge("case:current", node_id, "contains", weight=0.2)
        targets = active_test_targets(path, text)
        for candidate in targets:
            if failed:
                add_support_to_candidate(builder, node_id, candidate, 0.95, "failed active test")
            elif passed:
                add_contradiction_to_candidate(builder, node_id, candidate, 0.5, "passed active test")
        if failed:
            add_support_to_fault(builder, node_id, "hardware_fault", 0.7, "failed active test")


def add_crash_dump_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    crash_dump = runtime.get("crash_dump", {})
    if not crash_dump_is_available(crash_dump):
        return
    mapped = diagnose_crash_dump(crash_dump)
    node_id = f"crash:{stable_hash(sample_to_text(crash_dump))}"
    builder.add_node(node_id, "crash_signature", mapped.get("bugcheck") or "crash dump", prior=0.9, metadata=mapped)
    builder.add_edge("case:current", node_id, "contains", weight=0.4)
    for candidate in mapped.get("candidates", []):
        target = str(candidate.get("candidate", ""))
        belief = safe_float(candidate.get("belief"), 0.5)
        if target:
            add_support_to_candidate(builder, node_id, target, min(1.0, belief), "crash dump mapping")
        for fault_class in candidate_fault_classes(target, "", ""):
            add_support_to_fault(builder, node_id, fault_class, min(1.0, belief), "crash dump mapping")


def add_boundary_context_nodes(builder: GraphBuilder, runtime: dict[str, Any]) -> None:
    """Add explicit boundary roles, source quality and temporal windows."""

    boundary = runtime.get("boundary", {}) if isinstance(runtime.get("boundary"), dict) else {}
    roles = boundary.get("roles", []) if isinstance(boundary.get("roles"), list) else []
    scores = boundary.get("scores", {}) if isinstance(boundary.get("scores"), dict) else {}
    for role in roles:
        role_id = f"boundary:{slug(role)}"
        builder.add_node(
            role_id,
            "boundary_role",
            str(role),
            prior=min(1.0, safe_float(scores.get(role), 0.25)),
            metadata={"role": role, "score": scores.get(role, 0.0)},
        )
        builder.add_edge("case:current", role_id, "contains", weight=0.35)
        for fault_class in boundary_role_fault_classes(str(role)):
            add_support_to_fault(builder, role_id, fault_class, 0.25, "derived boundary role")

    quality = runtime.get("quality", {}) if isinstance(runtime.get("quality"), dict) else {}
    for source, value in quality.items():
        quality_id = f"quality:{slug(source)}"
        builder.add_node(
            quality_id,
            "source_quality",
            str(source),
            prior=min(1.0, safe_float(value, 0.0)),
            metadata={"source": source, "quality": value},
        )
        builder.add_edge("case:current", quality_id, "has_quality", weight=0.15)

    alignment = runtime.get("alignment", {}) if isinstance(runtime.get("alignment"), dict) else {}
    for source, time_range in (alignment.get("source_ranges", {}) or {}).items():
        window_id = f"window:{slug(source)}"
        builder.add_node(
            window_id,
            "event_window",
            f"{source} fault window",
            prior=0.35,
            metadata={"source": source, "range": time_range, "fault_time": alignment.get("fault_time", "")},
        )
        builder.add_edge("case:current", window_id, "contains", weight=0.2)
        for node_id, node in list(builder.nodes.items()):
            if node_id == window_id:
                continue
            source_type = node.get("type", "")
            if (source == "logs" and source_type == "log_template") or (source == "traces" and source_type == "trace_span") or (source == "metrics" and source_type == "metric_signal"):
                builder.add_edge(node_id, window_id, "in_window", weight=0.2)


def boundary_role_fault_classes(role: str) -> list[str]:
    return {
        "software_side": ["driver_fault", "os_fault", "configuration_fault", "data_or_filesystem_fault"],
        "firmware_control": ["firmware_fault", "configuration_fault"],
        "interface_path": ["hardware_fault", "driver_fault"],
        "hardware_endpoint": ["hardware_fault"],
        "external_environment": ["external_environment_fault"],
    }.get(role, ["mixed_or_uncertain"])


def link_text_to_targets(builder: GraphBuilder, source_node: str, text: str, *, base_weight: float) -> None:
    lowered = text.casefold()
    matched = False
    for tokens, candidates, fault_classes in TOKEN_TARGETS:
        if not any(token in lowered for token in tokens):
            continue
        matched = True
        weight = min(1.0, base_weight + 0.05 * sum(1 for token in tokens if token in lowered))
        for candidate in candidates:
            add_support_to_candidate(builder, source_node, candidate, weight, "token-to-candidate mapping")
        for fault_class in fault_classes:
            add_support_to_fault(builder, source_node, fault_class, weight, "token-to-fault mapping")
    if not matched and looks_benign(lowered):
        add_support_to_fault(builder, source_node, "no_fault_observed", 0.45, "benign operational log")


def add_support_to_candidate(builder: GraphBuilder, source: str, candidate: str, weight: float, reason: str) -> None:
    target = f"candidate:{candidate}"
    if target not in builder.nodes:
        builder.add_node(target, "candidate", candidate, metadata={"candidate": candidate, "source": "inferred"})
        link_candidate_to_fault(builder, target, candidate, "", "")
    builder.add_edge(source, target, "supports_candidate", weight=weight, metadata={"reason": reason})


def add_contradiction_to_candidate(builder: GraphBuilder, source: str, candidate: str, weight: float, reason: str) -> None:
    target = f"candidate:{candidate}"
    if target not in builder.nodes:
        builder.add_node(target, "candidate", candidate, metadata={"candidate": candidate, "source": "inferred"})
        link_candidate_to_fault(builder, target, candidate, "", "")
    builder.add_edge(source, target, "contradicts_candidate", weight=weight, metadata={"reason": reason})


def add_support_to_fault(builder: GraphBuilder, source: str, fault_class: str, weight: float, reason: str) -> None:
    target = f"fault:{fault_class}"
    if target not in builder.nodes:
        return
    builder.add_edge(source, target, "supports_fault", weight=weight, metadata={"reason": reason})


def metric_signal(path: str, value: Any) -> dict[str, Any] | None:
    text = f"{path} {value}".casefold()
    numeric = safe_float(value, None)
    if "free_percent" in path and numeric is not None and numeric < 12:
        return {
            "prior": 0.7,
            "weight": 0.8,
            "candidates": ["data_or_filesystem_fault", "m2_ssd_module"],
            "fault_classes": ["data_or_filesystem_fault"],
        }
    if "full_charge_capacity_ratio" in path and numeric is not None and numeric < 0.55:
        return {"prior": 0.65, "weight": 0.75, "candidates": ["battery_pack"], "fault_classes": ["hardware_fault"]}
    if "temperature" in path and numeric is not None and numeric >= 90:
        return {"prior": 0.65, "weight": 0.75, "candidates": ["fan_module", "heat_sink"], "fault_classes": ["hardware_fault"]}
    if "status" in path and any(token in text for token in ["error", "failed", "degraded", "unhealthy", "not ok"]):
        candidates, faults = targets_for_path(path)
        return {"prior": 0.55, "weight": 0.65, "candidates": candidates, "fault_classes": faults}
    return None


def active_test_targets(path: str, value_text: str) -> list[str]:
    text = f"{path} {value_text}".casefold()
    mapping = [
        ("power", ["power_adapter", "battery_pack"]),
        ("battery", ["battery_pack"]),
        ("storage", ["m2_ssd_module"]),
        ("memory", ["ram_module"]),
        ("network", ["wlan_module", "external_environment_fault"]),
        ("bluetooth", ["wlan_module"]),
        ("thermal", ["fan_module", "heat_sink"]),
        ("fan", ["fan_module"]),
        ("display", ["display_panel_module", "driver_or_os_fault"]),
        ("camera", ["camera_module"]),
        ("keyboard", ["keyboard_module"]),
        ("touchpad", ["touchpad_module"]),
        ("audio", ["speaker_module", "driver_or_os_fault"]),
        ("speaker", ["speaker_module"]),
        ("usb", ["io_board", "connector_or_interconnect_fault"]),
        ("io", ["io_board"]),
        ("mainboard", ["motherboard"]),
    ]
    targets: list[str] = []
    for token, candidates in mapping:
        if token in text:
            targets.extend(candidates)
    return list(dict.fromkeys(targets))


def targets_for_path(path: str) -> tuple[list[str], list[str]]:
    text = path.casefold()
    for token, candidates in [
        ("storage", ["m2_ssd_module"]),
        ("memory", ["ram_module"]),
        ("network", ["wlan_module"]),
        ("battery", ["battery_pack"]),
        ("power", ["power_adapter", "battery_pack"]),
        ("thermal", ["fan_module", "heat_sink"]),
        ("display", ["display_panel_module"]),
        ("audio", ["speaker_module"]),
        ("usb", ["io_board"]),
        ("mainboard", ["motherboard"]),
    ]:
        if token in text:
            return candidates, ["hardware_fault"]
    return [], ["mixed_or_uncertain"]


def event_buckets(events: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(key): value
        for key, value in events.items()
        if isinstance(value, dict) and key not in {"collection", "noise_reduction"}
    }


def sample_signature(sample: Any, fallback: str) -> str:
    if isinstance(sample, dict):
        text = sample.get("event_template") or sample.get("EventTemplate") or sample.get("message_excerpt") or sample.get("message") or fallback
    else:
        text = str(sample or fallback)
    return stable_hash(normalize_template(text))


def sample_to_text(sample: Any) -> str:
    if isinstance(sample, dict):
        return " ".join(str(value) for value in sample.values() if value is not None)
    return str(sample)


def iter_leaf_values(value: Any, *, prefix: str) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from iter_leaf_values(nested, prefix=nested_prefix)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from iter_leaf_values(nested, prefix=f"{prefix}[{index}]")
    else:
        yield prefix, value


def looks_benign(text: str) -> bool:
    return any(
        token in text
        for token in [
            "session opened",
            "session closed",
            "connection from",
            "completed successfully",
            "succeeded",
            "successfully",
        ]
    )


def slug(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip().casefold())
    return text.strip("_") or "unknown"


def stable_hash(value: Any) -> str:
    return hashlib.sha1(str(value).encode("utf-8", errors="ignore")).hexdigest()[:16]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
