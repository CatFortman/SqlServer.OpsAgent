"""Command-line entry point: `python -m opsagent diagnose --alert <path>`.

This file only parses arguments, calls into the package, and turns the outcome into an
exit code. Anything worth testing or reusing lives in other modules.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from opsagent.alert import AlertError, load_alert
from opsagent.coordinator import AgentRunError, ConfigurationError, run_diagnosis
from opsagent.utils.transcript import TranscriptWriter

EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_INVALID_ALERT = 2
EXIT_CONFIGURATION = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opsagent", description="First-pass triage for SQL Server incidents."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    diagnose = commands.add_parser(
        "diagnose", help="Investigate an alert and write a diagnosis (read-only)."
    )
    diagnose.add_argument(
        "--alert", type=Path, required=True, help="Path to the alert JSON file."
    )
    diagnose.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Where run output is written (default: ./runs). Set it explicitly "
        "when something other than you launches the process.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        alert = load_alert(args.alert)
    except AlertError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID_ALERT

    run_dir = args.runs_dir / alert.alert_id
    try:
        with TranscriptWriter(run_dir) as transcript:
            result = asyncio.run(run_diagnosis(alert, transcript))
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION
    except AgentRunError as exc:
        print(f"Agent run failed: {exc}", file=sys.stderr)
        return EXIT_RUN_FAILED

    succeeded = result.subtype == "success" and not result.is_error
    if result.result:
        print(result.result)

    cost = f"${result.total_cost_usd:.4f}" if result.total_cost_usd is not None else "unknown"
    print(
        f"\n[{result.subtype}] turns={result.num_turns} cost={cost} "
        f"transcript={transcript.path}",
        file=sys.stderr,
    )
    return EXIT_OK if succeeded else EXIT_RUN_FAILED


if __name__ == "__main__":
    sys.exit(main())
