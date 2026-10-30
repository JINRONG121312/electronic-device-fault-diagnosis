# Project Module Map

This project is organized as a fault-diagnosis research prototype with a local
dashboard, evidence collection scripts, dataset conversion tools, and
experiment runners.

## Core Modules

| Module | Role | Keep / Clean Decision |
|---|---|---|
| `fru_diagnosis/` | Main implementation package. It contains diagnosis scoring, diagnostic graph construction, graph inference, evidence fusion, anomaly detection, device setup, collection config, dashboard payloads, and web API helpers. | Keep. This is the active implementation used by the dashboard and tests. |
| `fault_diagnosis/` | Research-facing namespace. Most files are compatibility facades that re-export stable APIs from `fru_diagnosis/`, plus taxonomy entry points for the paper-facing naming. | Keep. Deleting it would break research imports and tests. |
| `web/` | Browser UI for local diagnosis, remote diagnosis, experiment display, and fault graph visualization. | Keep. This is the active frontend. |
| `scripts/` | Operational scripts for runtime collection, BSOD evidence collection, FRU/device scanning, Loghub OS preparation, and server startup. | Keep. These are still referenced by backend routes, docs, and tests. |
| `experiments/` | Experiment runners and evaluators. `run_baselines.py` now supports both keyword baseline and graph-fusion baseline; `evaluate_cases.py` reports accuracy, macro-F1, prediction distributions, and confusion matrices. | Keep active runners. Removed unused ablation skeleton. |
| `datasets/` | Canonical raw sources and versioned experiment inputs. | Keep only registered datasets. Obsolete generated versions and download caches were removed to prevent accidental citation. |
| `knowledge/` | Ontologies, rules, signal catalog, model registries, and device-specific knowledge files. | Keep. Used by diagnosis and device setup. |
| `configs/` | Active and sample device profiles plus collection settings. | Keep. Used by dashboard and scripts. |
| `reports/` | Generated logs, runtime reports, experiment metrics, and server locks. | Keep useful reports. Clean stale locks and obsolete static dashboard output. |
| `tests/` | Unit tests for dataset, graph diagnosis, web API boundaries, workflow, and collection logic. | Keep. Added experiment script coverage. |

## Removed Items

The cleanup was limited to files that were empty, generated, obsolete, or not
referenced by active code paths:

- `test-1.py`: empty root-level script.
- `generate_dashboard.py`: obsolete static HTML dashboard generator, superseded by `fru_web_server.py` and `web/`.
- `experiments/ablation.py`: unused experiment skeleton with no runner integration.
- `reports/fru_dashboard.html`: generated static dashboard artifact from the removed script.
- stale web lock files for ports `8781`, `8783`, `8784`, and `8785`.
- Python `__pycache__/` directories.

The current `8780` lock was retained while the active dashboard process was
running.

## Active Execution Flow

```text
scripts/collect_runtime_info.ps1 or uploaded evidence
-> fru_diagnosis.datasets schema
-> fru_diagnosis.diagnostic_graph
-> fru_diagnosis.graph_inference
-> fru_diagnosis.diagnosis_engine / evidence_fusion / decision_layer
-> fru_web_server.py API
-> web/ fault graph and experiment visualization
```

## Canonical Datasets

```text
datasets/processed/diagnosis_v3_loghub2k
  software-log baseline only; weak/silver labels

datasets/processed/diagnosis_v7_rcaeval_re2
  primary multi-source software root-cause experiment

datasets/processed/diagnosis_v8_rcaeval_re2_re3
  supplementary cross-release robustness experiment
```

Datasets not listed in `datasets/source_registry.json` must not be used for
formal claims. Hardware/software boundary evaluation requires a future dataset
that passes `validate_diagnosis_dataset.py --profile boundary`.
