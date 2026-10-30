"""End-to-end diagnostic workflow orchestration."""

from __future__ import annotations

from typing import Any

from .active_diagnosis import completed_test_ids, recommend_next_tests
from .anomaly_detection import detect_anomalies
from .boundary_assessment import assess_boundary
from .crash_dump_evidence import normalize_crash_dump_evidence
from .decision_layer import decide_after_classification
from .diagnosis_engine import build_diagnosis_report
from .fault_classification import classify_fault_case
from .health_assessment import assess_device_health
from .remote_diagnosis import (
    build_cross_machine_collection_plan,
    build_fault_case,
    build_remote_collection_guidance,
    build_runtime_from_remote_evidence,
    normalize_customer_intake,
)


SELF_DETECTION = "self"
CROSS_MACHINE_REMOTE = "cross_machine_remote"
CROSS_MACHINE_INTERFACE = "cross_machine_interface"
CROSS_MACHINE_OFFLINE = "cross_machine_offline"
CROSS_MACHINE_POWER_OFF = "cross_machine_power_off"


def run_diagnostic_workflow(
    mode: str,
    body: dict[str, Any],
    profile: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run anomaly detection, fault classification, and decision in order."""

    normalized_mode = normalize_mode(mode or body.get("mode"))
    if normalized_mode == SELF_DETECTION:
        return run_self_detection(body, profile, runtime or {})
    return run_cross_machine_detection(normalized_mode, body, profile)


def run_self_detection(body: dict[str, Any], profile: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    symptoms = normalize_symptoms(body.get("symptoms") or body.get("symptom"))
    runtime = normalize_runtime_crash_dump(runtime, "self_after_reboot")
    anomaly = detect_anomalies(runtime, symptoms)
    health = assess_device_health(runtime, anomaly)
    case = build_self_fault_case(symptoms, runtime, anomaly)
    classification = classify_fault_case(case)
    classification["health_assessment"] = health
    diagnosis_report = build_diagnosis_report(profile, runtime)
    boundary = assess_boundary(runtime, classification, diagnosis_report.get("top_candidates", []), symptoms)
    classification["boundary_assessment"] = boundary
    decision = decide_after_classification(classification)
    next_tests = recommend_next_tests(
        diagnosis_report,
        symptoms,
        limit=5,
        boundary_assessment=boundary,
        completed_tests=completed_test_ids(runtime),
    )

    return {
        "ok": True,
        "mode": SELF_DETECTION,
        "scenario": {
            "id": SELF_DETECTION,
            "name": "自机检测",
            "description": "程序运行在当前机器上，说明操作系统仍可执行采集和诊断逻辑。",
        },
        "pipeline": build_pipeline(anomaly, classification, decision),
        "anomaly_detection": anomaly,
        "health_assessment": health,
        "classification": classification,
        "boundary_assessment": boundary,
        "decision": decision,
        "next_tests": next_tests,
        "active_diagnosis": build_active_diagnosis_state(runtime, boundary, next_tests),
        "system_health": build_system_health(anomaly, health),
        "diagnosis_summary": diagnosis_report.get("summary", {}),
        "top_candidates": diagnosis_report.get("top_candidates", []),
        "diagnostic_graph": diagnosis_report.get("diagnostic_graph", {}),
        "graph_inference": diagnosis_report.get("graph_inference", {}),
    }


def run_cross_machine_detection(mode: str, body: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    intake = normalize_customer_intake(body)
    runtime = build_runtime_from_remote_evidence(body, intake)
    crash_source = {
        CROSS_MACHINE_INTERFACE: "target_agent",
        CROSS_MACHINE_OFFLINE: "offline_import",
        CROSS_MACHINE_POWER_OFF: "unavailable",
    }.get(mode, "remote_description")
    runtime = normalize_runtime_crash_dump(runtime, crash_source)
    anomaly = detect_anomalies(runtime, intake["symptoms"])
    case = build_fault_case(intake, runtime)
    case["anomaly_detection"] = anomaly
    classification = classify_fault_case(case)
    diagnosis_report = build_diagnosis_report(profile, runtime)
    boundary = assess_boundary(runtime, classification, diagnosis_report.get("top_candidates", []), intake["symptoms"])
    classification["boundary_assessment"] = boundary
    decision = decide_after_classification(classification)
    next_tests = recommend_next_tests(
        diagnosis_report,
        intake["symptoms"],
        limit=5,
        boundary_assessment=boundary,
        completed_tests=completed_test_ids(runtime),
    )

    guidance = build_cross_machine_guidance(mode, intake, next_tests, decision)
    result = {
        "ok": True,
        "mode": mode,
        "scenario": cross_machine_scenario(mode),
        "intake": intake,
        "pipeline": build_pipeline(anomaly, classification, decision),
        "anomaly_detection": anomaly,
        "classification": classification,
        "boundary_assessment": boundary,
        "decision": decision,
        "next_tests": next_tests,
        "active_diagnosis": build_active_diagnosis_state(runtime, boundary, next_tests),
        "diagnosis_summary": diagnosis_report.get("summary", {}),
        "top_candidates": diagnosis_report.get("top_candidates", []),
        "diagnostic_graph": diagnosis_report.get("diagnostic_graph", {}),
        "graph_inference": diagnosis_report.get("graph_inference", {}),
        "guidance": guidance,
    }
    if mode == CROSS_MACHINE_REMOTE:
        result["remote_collection"] = guidance
        result["mode"] = "remote_cross_machine_diagnosis"
    return result


def build_self_fault_case(
    symptoms: list[str],
    runtime: dict[str, Any],
    anomaly: dict[str, Any],
) -> dict[str, Any]:
    return {
        "symptom": symptoms,
        "anomaly_detection": anomaly,
        "evidence": {
            "inventory": {
                "system": runtime.get("system", {}),
                "device_inventory": runtime.get("device_inventory", {}),
            },
            "logs": {"events": runtime.get("events", {})},
            "metrics": {
                "power": runtime.get("power", {}),
                "battery": runtime.get("battery", {}),
                "storage": runtime.get("storage", {}),
                "memory": runtime.get("memory", {}),
                "network": runtime.get("network", {}),
                "thermal": runtime.get("thermal", {}),
            },
            "active_tests": runtime.get("tests", {}),
            "crash_dump": runtime.get("crash_dump", {}),
        },
    }


def build_pipeline(
    anomaly: dict[str, Any],
    classification: dict[str, Any],
    decision: dict[str, Any],
) -> list[dict[str, Any]]:
    boundary = classification.get("boundary_assessment", {}) if isinstance(classification.get("boundary_assessment"), dict) else {}
    return [
        {
            "step": "anomaly_detection",
            "status": anomaly.get("status", "unknown"),
            "summary": f"anomaly_score={anomaly.get('anomaly_score', 0)}",
        },
        {
            "step": "fault_classification",
            "status": classification.get("predicted_fault_class", "mixed_or_uncertain"),
            "summary": f"top_class={classification.get('predicted_fault_class', '-')}",
        },
        {
            "step": "boundary_assessment",
            "status": boundary.get("boundary_type", "mixed_or_uncertain"),
            "summary": f"boundary={boundary.get('boundary_type', '-')}, confidence={boundary.get('confidence', 0)}",
        },
        {
            "step": "fault_decision",
            "status": decision.get("decision", "need_more_evidence"),
            "summary": "repair or evidence collection decision generated after classification",
        },
    ]


def build_system_health(anomaly: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    if health:
        return {
            "level": health.get("health_level", "unknown"),
            "status": anomaly.get("status", "unknown"),
            "health_score": health.get("health_score", 0),
            "anomaly_score": anomaly.get("anomaly_score", 0),
            "observed_abnormal_count": len(anomaly.get("observations", [])),
        }
    status = anomaly.get("status", "unknown")
    if status == "normal":
        level = "healthy"
    elif float(anomaly.get("anomaly_score", 0) or 0) >= 0.6:
        level = "unhealthy"
    else:
        level = "degraded"
    return {
        "level": level,
        "status": status,
        "anomaly_score": anomaly.get("anomaly_score", 0),
        "observed_abnormal_count": len(anomaly.get("observations", [])),
    }


def build_cross_machine_guidance(
    mode: str,
    intake: dict[str, Any],
    next_tests: list[dict[str, Any]],
    decision: dict[str, Any],
) -> dict[str, Any]:
    if mode == CROSS_MACHINE_REMOTE:
        guidance = build_remote_collection_guidance(intake, next_tests)
        guidance["scenario"] = mode
        guidance["primary_goal"] = "remote_guidance_from_description_and_prior_knowledge"
        guidance["llm_extension_point"] = "fine_tuned_model_can_rerank_questions_and_generate_customer_steps"
        return guidance
    if mode == CROSS_MACHINE_INTERFACE:
        return {
            "scenario": mode,
            "primary_goal": "collect_evidence_from_fault_machine_via_interface",
            "base_actions": [
                "connect to the fault machine through the agreed local or remote interface",
                "export runtime_info.json, event logs, device inventory, SMART data, and active-test results",
                "run the same anomaly-classification-decision pipeline on the collected evidence",
            ],
            "collection_plan": build_cross_machine_collection_plan(intake, mode),
            "next_best_tests": simplify_next_tests(next_tests),
        }
    if mode == CROSS_MACHINE_OFFLINE:
        return {
            "scenario": mode,
            "primary_goal": "diagnose_from_offline_evidence_exported_from_fault_machine",
            "base_actions": [
                "import runtime_info.json or offline evidence exported from the fault machine",
                "include Minidump, MEMORY.DMP metadata, System.evtx, Application.evtx, driver list, OS version, and SMART data when available",
                "run the same anomaly-classification-boundary-decision pipeline on imported evidence",
            ],
            "collection_plan": build_cross_machine_collection_plan(intake, mode),
            "next_best_tests": simplify_next_tests(next_tests),
        }
    if mode == CROSS_MACHINE_POWER_OFF:
        return {
            "scenario": mode,
            "primary_goal": "onsite_guidance_when_fault_machine_cannot_boot_or_power_on",
            "base_actions": [
                "record model, serial, visible symptom, power LED, adapter LED, fan spin, beep code, smell or liquid traces",
                "test known-good power adapter, outlet, battery reset path, and external display where applicable",
                "prioritize replaceable hardware only after external power and connector checks",
            ],
            "collection_plan": build_cross_machine_collection_plan(intake, mode),
            "replacement_guidance": decision.get("actions", []),
            "llm_extension_point": "fine_tuned_model_can_generate_step_by_step_field_service_guidance",
        }
    return {
        "scenario": mode,
        "primary_goal": "cross_machine_fault_diagnosis",
        "base_actions": ["collect more evidence before recommending repair"],
        "collection_plan": build_cross_machine_collection_plan(intake, mode),
        "next_best_tests": simplify_next_tests(next_tests),
    }


def simplify_next_tests(next_tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": item.get("id", ""), "name": item.get("name", ""), "score": item.get("score", 0)}
        for item in next_tests
    ]


def build_active_diagnosis_state(
    runtime: dict[str, Any],
    boundary: dict[str, Any],
    next_tests: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "method": "boundary_aware_information_gain_per_cost",
        "completed_tests": sorted(completed_test_ids(runtime)),
        "boundary_type": boundary.get("boundary_type", "mixed_or_uncertain"),
        "boundary_conflict": boundary.get("conflict_score", 0.0),
        "evidence_coverage": boundary.get("evidence_coverage", 0.0),
        "recommendation_count": len(next_tests),
        "recommendations": next_tests,
    }


def cross_machine_scenario(mode: str) -> dict[str, str]:
    scenarios = {
        CROSS_MACHINE_REMOTE: {
            "id": CROSS_MACHINE_REMOTE,
            "name": "互机远程检测",
            "description": "根据客户描述和先验知识库进行远程初诊和指导，后续可接入微调大模型。",
        },
        CROSS_MACHINE_INTERFACE: {
            "id": CROSS_MACHINE_INTERFACE,
            "name": "互机接口取证",
            "description": "故障机器在身边且可通过接口导出诊断证据。",
        },
        CROSS_MACHINE_OFFLINE: {
            "id": CROSS_MACHINE_OFFLINE,
            "name": "互机离线证据导入",
            "description": "故障机器不能稳定运行采集程序，但系统盘、WinPE、安全模式或拆盘证据仍可读取。",
        },
        CROSS_MACHINE_POWER_OFF: {
            "id": CROSS_MACHINE_POWER_OFF,
            "name": "互机断电现场指导",
            "description": "故障机器无法运行程序，根据先验知识库和现场观察指导排查和硬件更换。",
        },
    }
    return scenarios.get(mode, scenarios[CROSS_MACHINE_REMOTE])


def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().casefold()
    aliases = {
        "self": SELF_DETECTION,
        "self_detection": SELF_DETECTION,
        "local": SELF_DETECTION,
        "remote": CROSS_MACHINE_REMOTE,
        "cross_machine": CROSS_MACHINE_REMOTE,
        "cross_machine_remote": CROSS_MACHINE_REMOTE,
        "interface": CROSS_MACHINE_INTERFACE,
        "cross_machine_interface": CROSS_MACHINE_INTERFACE,
        "nearby_interface": CROSS_MACHINE_INTERFACE,
        "offline": CROSS_MACHINE_OFFLINE,
        "cross_machine_offline": CROSS_MACHINE_OFFLINE,
        "offline_import": CROSS_MACHINE_OFFLINE,
        "power_off": CROSS_MACHINE_POWER_OFF,
        "cross_machine_power_off": CROSS_MACHINE_POWER_OFF,
        "onsite_power_off": CROSS_MACHINE_POWER_OFF,
    }
    return aliases.get(text, CROSS_MACHINE_REMOTE)


def normalize_symptoms(value: Any) -> list[str]:
    if isinstance(value, list):
        symptoms = [str(item).strip() for item in value if str(item).strip()]
    elif value:
        symptoms = [str(value).strip()]
    else:
        symptoms = []
    return symptoms or ["unknown_symptom"]


def normalize_runtime_crash_dump(runtime: dict[str, Any], source: str) -> dict[str, Any]:
    normalized = dict(runtime or {})
    normalized["crash_dump"] = normalize_crash_dump_evidence(
        normalized.get("crash_dump", {}),
        source=source,
    )
    return normalized
