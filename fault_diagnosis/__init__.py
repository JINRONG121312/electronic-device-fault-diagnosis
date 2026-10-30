"""Research-facing fault diagnosis API.

This package provides a diagnosis-oriented namespace for the research work.
The existing :mod:`fru_diagnosis` package remains as the compatibility layer
for the current dashboard and device profiles.
"""

from .taxonomy import (
    FAULT_ORIGIN_TYPES,
    SERVICEABILITY_TYPES,
    FaultOrigin,
    ServiceabilityOutcome,
    classify_fault_origin,
)
from .active_diagnosis import recommend_next_tests
from .datasets import DatasetCase, EvidenceBundle, Label, case_from_runtime_info
from .diagnosis_engine import build_diagnosis_report
from .evidence_fusion import build_fusion_candidates, combine_beliefs_dempster_shafer
from .fault_classification import FAULT_CLASSES, classify_fault_case
from .decision_layer import decide_after_classification
from fru_diagnosis.boundary_assessment import assess_boundary
from fru_diagnosis.anomaly_detection import detect_anomalies
from fru_diagnosis.diagnostic_graph import build_diagnostic_graph, build_diagnostic_graph_from_case
from fru_diagnosis.diagnostic_workflow import run_diagnostic_workflow
from fru_diagnosis.graph_inference import infer_diagnostic_graph

__all__ = [
    "FAULT_ORIGIN_TYPES",
    "FAULT_CLASSES",
    "SERVICEABILITY_TYPES",
    "DatasetCase",
    "EvidenceBundle",
    "FaultOrigin",
    "Label",
    "ServiceabilityOutcome",
    "build_diagnosis_report",
    "build_fusion_candidates",
    "build_diagnostic_graph",
    "build_diagnostic_graph_from_case",
    "case_from_runtime_info",
    "classify_fault_origin",
    "combine_beliefs_dempster_shafer",
    "classify_fault_case",
    "assess_boundary",
    "decide_after_classification",
    "detect_anomalies",
    "infer_diagnostic_graph",
    "run_diagnostic_workflow",
    "recommend_next_tests",
]
