"""Interactive setup for selecting or creating an FRU device profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fru_diagnosis.device_setup import (
    DEFAULT_ACTIVE_PROFILE_PATH,
    DEFAULT_REPORT_PATH,
    DEFAULT_SCAN_PATH,
    SetupInputs,
    setup_device_profile,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an FRU profile from operator input, hardware scan, and model knowledge base."
    )
    parser.add_argument("--device-type", help="Operator-declared type: laptop/server/router/custom.")
    parser.add_argument("--manufacturer", help="Manufacturer entered by operator.")
    parser.add_argument("--model", help="Model entered by operator.")
    parser.add_argument("--custom-name", help="Name used when creating a custom device profile.")
    parser.add_argument("--scan-path", default=str(DEFAULT_SCAN_PATH), help="Path to detected scan JSON.")
    parser.add_argument("--output", default=str(DEFAULT_ACTIVE_PROFILE_PATH), help="Output active FRU profile path.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="Output setup report path.")
    parser.add_argument(
        "--skip-detect",
        action="store_true",
        help="Use an existing scan file instead of running scripts/detect_fru.ps1.",
    )
    parser.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="Continue even if declared device type differs from detected type.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    device_type = args.device_type or input(
        "请输入设备类型（laptop/笔记本, server/服务器, router/路由器, custom/自定义）："
    ).strip()
    manufacturer = args.manufacturer
    model = args.model
    custom_name = args.custom_name

    if device_type.casefold() in {"laptop", "笔记本", "笔记本电脑", "notebook"}:
        if manufacturer is None:
            manufacturer = input("请输入厂家（可留空，留空则使用本机扫描结果）：").strip()
        if model is None:
            model = input("请输入具体型号（可留空，留空则使用本机扫描结果）：").strip()
    elif device_type.casefold() in {"custom", "自定义"} and custom_name is None:
        custom_name = input("请输入自定义设备名称：").strip()

    try:
        report = setup_device_profile(
            SetupInputs(
                declared_device_type=device_type,
                manufacturer=manufacturer or "",
                model=model or "",
                custom_name=custom_name or "",
                scan_path=Path(args.scan_path),
                output_path=Path(args.output),
                report_path=Path(args.report),
                run_detection=not args.skip_detect,
                allow_mismatch=args.allow_mismatch,
            )
        )
    except Exception as exc:
        print(f"FRU profile setup failed: {exc}")
        return 1

    print("FRU profile setup completed.")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
