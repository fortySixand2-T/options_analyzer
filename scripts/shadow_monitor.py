#!/usr/bin/env python3
"""
Shadow trade monitor — checks open trades every 5 minutes during market hours.

Usage:
    python scripts/shadow_monitor.py           # Run monitor loop
    python scripts/shadow_monitor.py --once    # Run one check cycle and exit

Options Analytics Team — 2026-05
"""

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="Shadow trade monitor — live exit rule checking",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run one check cycle and exit (no loop)",
    )
    args = parser.parse_args()

    from data.shadow_monitor import run_monitor_cycle, run_monitor_loop

    if args.once:
        result = run_monitor_cycle()
        print(json.dumps(result, indent=2))
    else:
        run_monitor_loop()


if __name__ == "__main__":
    main()
