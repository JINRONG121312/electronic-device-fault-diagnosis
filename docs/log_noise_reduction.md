# Log Noise Reduction Method

This project treats `Error` and `Warning` as noisy evidence, not direct fault
labels. The implementation is based on two papers that are fixed as the
project references for this feature:

1. **Reducing Events to Augment Log-based Anomaly Detection Models: An Empirical Study**  
   arXiv: https://arxiv.org/abs/2409.04834  
   Used for the key idea of reducing anti-events and duplicative events before
   anomaly scoring.

2. **Log-based Anomaly Detection with Deep Learning: How Far Are We?**  
   arXiv: https://arxiv.org/abs/2202.04301  
   Used for the caution that grouping choices, noisy data, and weak labels can
   materially affect log-anomaly results.

## Project Policy

The system no longer treats every `Error` or `Warning` as an actionable fault
signal. Log evidence first passes through template-level noise reduction:

- normalize each log line into a template signature;
- classify templates into `key_event`, `anti_event`, `duplicative_event`, or
  `ordinary_event`;
- suppress recoverable or explicitly ignored events;
- compress repeated events so a burst of identical warnings contributes one
  actionable event instead of many;
- retain severe templates such as `panic`, `bugcheck`, `WHEA`, `bad block`,
  `uncorrectable`, or `predictive failure`.

## Implementation

- `fru_diagnosis/log_noise_reduction.py` contains the shared implementation and
  paper references.
- `scripts/prepare_loghub_os_dataset.py` uses the reduced actionable event count
  for LogHub weak labels.
- `fru_diagnosis/anomaly_detection.py` reports actionable warning/error counts,
  while preserving raw counts for context.
- `fru_diagnosis/health_assessment.py` explains when raw warning/error logs were
  reduced to no actionable evidence.
- `fru_diagnosis/diagnosis_engine.py` uses reduced counts for rule matching and
  candidate scoring.

This design keeps the model conservative: repeated benign warnings are not
over-weighted, but severe or rule-relevant events still participate in diagnosis.
