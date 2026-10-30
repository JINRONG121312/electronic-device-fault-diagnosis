# Loghub OS Weak-Label Experiment Report

> Deprecated: this report records a previous smoke-test dataset and baseline
> run. The processed dataset under `datasets/processed/loghub_os` has been
> deleted. Do not use the metrics below as formal experiment results.

Generated on 2026-06-29.

## Dataset

The Loghub Linux, Windows, and Mac OS samples do not provide official fault
labels. The project therefore uses deterministic weak labels after template
noise reduction. These labels are suitable for controlled prototype evaluation,
not for claiming ground-truth production accuracy.

Current processed corpus:

| Dataset | Cases | Weak label distribution | Target distribution |
|---|---:|---|---|
| Linux | 40 | `no_fault_observed=38`, `non_fru_fault=2` | `none=38`, `driver_or_os_fault=2` |
| Windows | 40 | `no_fault_observed=40` | `none=40` |
| Mac | 40 | `no_fault_observed=4`, `non_fru_fault=36` | `none=4`, `driver_or_os_fault=33`, `configuration_fault=2`, `os_fault=1` |

Total: 120 cases, chronological split by dataset with 84 train, 18 dev, and 18
test cases.

## Methods

| Method | Description |
|---|---|
| `rule_weighted` | Original keyword baseline. It searches the whole evidence JSON for tokens such as `driver`, `service`, `exception`, `fatal`, `disk`, and `battery`. |
| `graph_fusion` | New baseline using `fru_diagnosis.diagnostic_graph` and `fru_diagnosis.graph_inference`. It builds typed evidence, candidate, and fault-class nodes, then uses graph propagation and direct support scores. |

The frontend import endpoint now defaults to `graph_fusion`. The old keyword
baseline is still available for comparison.

## Results

### All 120 Cases

| Method | Target Acc. | Target Macro-F1 | Top-3 Target Acc. | Fault-Origin Acc. | Fault-Origin Macro-F1 | Prediction Distribution |
|---|---:|---:|---:|---:|---:|---|
| `rule_weighted` | 0.2500 | 0.1021 | 0.2500 | 0.2750 | 0.2200 | `driver_or_os_fault=112`, `storage_fru=8` |
| `graph_fusion` | 0.3083 | 0.1555 | 0.7083 | 0.5667 | 0.5852 | `none=37`, `firmware_or_config_fault=41`, `os_fault=39`, `driver_or_os_fault=1`, `power_adapter=2` |

### Test Split, 18 Cases

| Method | Target Acc. | Target Macro-F1 | Top-3 Target Acc. | Fault-Origin Acc. | Fault-Origin Macro-F1 | Prediction Distribution |
|---|---:|---:|---:|---:|---:|---|
| `rule_weighted` | 0.3889 | 0.2800 | 0.3889 | 0.3889 | 0.2800 | `driver_or_os_fault=17`, `storage_fru=1` |
| `graph_fusion` | 0.1667 | 0.2308 | 0.6111 | 0.5556 | 0.5490 | `none=3`, `firmware_or_config_fault=8`, `os_fault=6`, `power_adapter=1` |

Metric JSON files are under `reports/experiment_metrics/`.

## Interpretation

The original `rule_weighted` baseline has clear category collapse. Across all
120 cases it predicts `driver_or_os_fault` for 112 cases and never predicts
`none`, even though the weak labels contain 82 `none` targets. This explains the
very low macro-F1: the model gains some recall on driver-like cases, but recall
for `none`, `os_fault`, and `configuration_fault` is near zero.

The `graph_fusion` baseline fixes part of this failure mode. It predicts
`none` for 37 cases and raises fault-origin macro-F1 from 0.2200 to 0.5852 on
the full corpus. It also improves top-3 target accuracy from 0.2500 to 0.7083,
which is important for a diagnostic assistant because ranked candidates are more
useful than a single brittle label.

Target-level accuracy is still limited. The main cause is label-space mismatch:
the weak labels collapse many Mac anomalies into `driver_or_os_fault`, while the
graph model separates them into `firmware_or_config_fault`, `os_fault`, external
environment, and power-related candidates. For the paper, this should be framed
as a multi-granularity diagnosis problem:

- coarse layer: `no_fault_observed`, `non_fru_fault`, `replaceable_fru`;
- fault-class layer: `driver_fault`, `os_fault`, `firmware_fault`,
  `configuration_fault`, `external_environment_fault`, `hardware_fault`;
- service/repair target layer: concrete candidate or repair action.

## Next Changes

1. Train or calibrate a mapping layer from graph fault classes to the weak-label
   target taxonomy instead of hard-coding the mapping in the experiment script.
2. Add confidence thresholds so low-support candidate nodes do not override
   strong `no_fault_observed` evidence.
3. Add manual review or LLM-assisted review for windows with suppressed but
   semantically ambiguous events, especially Mac OS scheduler/network messages.
4. Report both coarse fault-origin metrics and ranked target metrics in the
   paper; single-label target accuracy alone understates the diagnostic value of
   ranked graph output.
