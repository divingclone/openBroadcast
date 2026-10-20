"""Installed GUI entry point; also used by the source/portable launcher."""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="openbroadcast-gui")
    parser.add_argument("--background", action="store_true",
                        help="start in the system tray after it becomes available")
    parser.add_argument("--check-runtime", metavar="REPORT",
                        help="check models and GUI, writing a JSON report")
    args = parser.parse_args(argv)
    if args.check_runtime:
        from .runtime_check import run
        return run(args.check_runtime)
    from .gui import main as gui_main
    return gui_main(background=args.background)


if __name__ == "__main__":
    raise SystemExit(main())
