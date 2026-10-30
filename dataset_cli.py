"""Convert public datasets into the project JSONL case schema."""

from __future__ import annotations

import argparse
from pathlib import Path

from fru_diagnosis.datasets import dump_cases_jsonl
from fru_diagnosis.datasets.adapters import (
    iter_backblaze_cases,
    iter_gaia_cases,
    iter_loghub_cases,
    iter_openrepair_cases,
    iter_rcaeval_cases,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert datasets to fault diagnosis JSONL cases.")
    parser.add_argument("adapter", choices=["backblaze", "gaia", "loghub", "openrepair", "rcaeval"])
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dataset-name", default="loghub")
    args = parser.parse_args()

    if args.adapter == "backblaze":
        cases = iter_backblaze_cases(args.input_path, limit=args.limit)
    elif args.adapter == "gaia":
        cases = iter_gaia_cases(args.input_path, limit=args.limit)
    elif args.adapter == "loghub":
        cases = iter_loghub_cases(args.input_path, dataset_name=args.dataset_name, limit=args.limit)
    elif args.adapter == "rcaeval":
        cases = iter_rcaeval_cases(args.input_path, limit=args.limit)
    else:
        cases = iter_openrepair_cases(args.input_path, limit=args.limit)

    output_path = Path(args.output_path)
    dump_cases_jsonl(cases, output_path)
    print(f"Wrote normalized cases to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
