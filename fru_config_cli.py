"""Command-line utility for validating FRU configuration profiles."""

from __future__ import annotations

import argparse
import json

from fru_diagnosis import FRUConfigError, load_device_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and summarize an FRU device profile."
    )
    parser.add_argument("profile", help="Path to a JSON/YAML FRU profile.")
    parser.add_argument(
        "--show-frus",
        action="store_true",
        help="Print the FRU list after validation.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        profile = load_device_profile(args.profile)
    except (FRUConfigError, json.JSONDecodeError) as exc:
        print(f"FRU profile validation failed: {exc}")
        return 1

    print("FRU profile validation passed.")
    print(json.dumps(profile.to_summary(), ensure_ascii=False, indent=2))

    if args.show_frus:
        for fru in profile.fru_list:
            print(
                f"- {fru.id}: {fru.name} "
                f"({fru.category}, replaceable={fru.replaceable}, "
                f"role={fru.diagnosis_role}, "
                f"verified={fru.verification_status}, "
                f"rules={len(fru.evidence_rules)})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
