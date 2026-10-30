"""Validate and summarize runtime information collected for fault diagnosis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize collected runtime info.")
    parser.add_argument(
        "runtime_info",
        nargs="?",
        default="data/runtime_info.json",
        help="Path to runtime_info.json.",
    )
    parser.add_argument(
        "--catalog",
        default="knowledge/fru_signal_catalog.json",
        help="Path to the serviceability signal catalog.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    runtime = read_json(args.runtime_info)
    catalog = read_json(args.catalog)

    print("Runtime information summary")
    print(f"- generated_at: {runtime.get('generated_at')}")
    print(f"- system: {runtime.get('system', {}).get('manufacturer')} {runtime.get('system', {}).get('model')}")
    print(f"- window_hours: {runtime.get('window_hours')}")
    print(f"- total warning/error events: {runtime.get('events', {}).get('total_warning_error_count')}")
    print(f"- problem devices: {runtime.get('device_inventory', {}).get('problem_device_count')}")

    print("\nFault evidence coverage")
    for fru in catalog.get("fru_signals", []):
        fru_id = fru.get("fru_id")
        required = fru.get("required", [])
        enhancing = fru.get("enhancing", [])
        active_test = fru.get("active_test", [])
        present_required = sum(
            1 for signal in required if get_nested(runtime, signal.get("key", "")) is not None
        )
        print(
            f"- {fru_id}: required {present_required}/{len(required)}, "
            f"enhancing {len(enhancing)}, active_tests {len(active_test)}"
        )

    return 0


def get_nested(data: dict[str, Any], key: str) -> Any:
    if not key:
        return None
    values = get_nested_values(data, key.split("."))
    values = [value for value in values if value is not None]
    if not values:
        return None
    return values


def get_nested_values(current: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return [current]

    part = parts[0]
    rest = parts[1:]
    is_array = part.endswith("[]")
    clean_part = part[:-2] if is_array else part

    if not isinstance(current, dict) or clean_part not in current:
        return []

    next_value = current[clean_part]
    if is_array:
        if not isinstance(next_value, list):
            return []
        values: list[Any] = []
        for item in next_value:
            values.extend(get_nested_values(item, rest))
        return values

    return get_nested_values(next_value, rest)


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
