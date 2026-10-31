"""Command-line entry point: `python -m opsagent diagnose --alert <path>`.

This file only parses arguments, calls into the package, and turns the outcome into an
exit code. Anything worth testing or reusing lives in other modules.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from opsagent.alert import AlertError, load_alert

EXIT_OK = 0
EXIT_INVALID_ALERT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsagent", description="First-pass triage for SQL Server incidents.")
    commands = parser.add_subparsers(dest="command", required=True)

    diagnose = commands.add_parser("diagnose", help="Investigate an alert and write a diagnosis (read-only).")
    diagnose.add_argument("--alert", type=Path, required=True, help="Path to the alert JSON file.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        alert = load_alert(args.alert)
    except AlertError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID_ALERT

    # Run the coordinator agent.
    print(f"Alert {alert.alert_id} is valid: signal={alert.signal}, server={alert.server}, database={alert.database}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
