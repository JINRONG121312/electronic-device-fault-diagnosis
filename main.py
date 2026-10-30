"""Project entry point for launching the fault-diagnosis research dashboard."""

from __future__ import annotations

from fru_web_server import main as run_web_server


def main() -> int:
    return run_web_server()


if __name__ == "__main__":
    raise SystemExit(main())
