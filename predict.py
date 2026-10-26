#!/usr/bin/env python3
"""
Soccer prediction CLI — generate high-probability picks for accumulator bets.

Usage:
  predict today -n 5
  predict tomorrow --count 10
  predict export [file]   Export to SportyBet-friendly CSV and plain-text
  python predict.py today
"""

import argparse
import sys
from pathlib import Path

# Allow running as script: python predict.py today -n 5
if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from predictor.aggregator import format_accumulator, rank_for_accumulator
from predictor.exports import export_file
from predictor.fetchers import fetch_all


def _latest_predictions_file() -> Path | None:
    """Return the most recent .md file in .predictions/ (searches day folders)."""
    pred_dir = Path(__file__).resolve().parent / ".predictions"
    if not pred_dir.exists():
        return None
    md_files = sorted(pred_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return md_files[0] if md_files else None


def cmd_export(args: argparse.Namespace) -> int:
    """Export predictions to SportyBet-friendly formats."""
    if args.file:
        input_path = Path(args.file)
        if not input_path.exists():
            print(f"Error: File not found: {input_path}")
            return 1
    else:
        input_path = _latest_predictions_file()
        if not input_path:
            print(
                "Error: No prediction files in .predictions/. Run predictions-today or predictions-tomorrow first."
            )
            return 1
        pred_dir = Path(__file__).resolve().parent / ".predictions"
        try:
            rel = input_path.relative_to(pred_dir)
        except ValueError:
            rel = input_path.name
        print(f"Using latest: {rel}")

    result = export_file(input_path)
    if not result:
        print("Error: No picks found in file (could not parse table).")
        return 1

    print("\nExported for SportyBet:\n")
    for fmt, path in result.items():
        labels = {
            "csv": "CSV (Match, Tip, Odds)",
            "txt": "Plain text (match | tip | odds)",
            "search": "Match names only (search)",
        }
        print(f"  {labels[fmt]}: {path}")

    print(
        "\nTip: Open the CSV in Excel, or copy lines from the .txt file while placing bets on SportyBet."
    )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate best soccer predictions for accumulator bets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  predict today -n 5         Top 5 predictions for today
  predict tomorrow -n 10     Top 10 predictions for tomorrow
  predict export             Export latest to SportyBet CSV/txt
  predict export file.md     Export specific prediction file
        """,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True, help="Command")

    for day in ("today", "tomorrow"):
        sub = subparsers.add_parser(day, help=f"Predictions for {day}")
        sub.add_argument(
            "-n",
            "--count",
            type=int,
            default=5,
            metavar="N",
            help="Number of predictions to include in accumulator (default: 5)",
        )
        sub.set_defaults(cmd=day)

    export_parser = subparsers.add_parser(
        "export", help="Export to SportyBet-friendly CSV and plain-text"
    )
    export_parser.add_argument(
        "file",
        nargs="?",
        help="Prediction .md file (default: latest in .predictions/)",
    )
    export_parser.set_defaults(cmd="export")

    args = parser.parse_args()

    if args.cmd == "export":
        return cmd_export(args)

    # today / tomorrow
    day = args.cmd
    count = args.count

    if count < 1 or count > 20:
        print("Error: --count must be between 1 and 20.")
        return 1

    print(f"Fetching {day}'s predictions...")
    predictions = fetch_all(day)
    top = rank_for_accumulator(predictions, count)

    print(f"\nTop {len(top)} high-probability picks for {day} (accumulator):\n")
    print(format_accumulator(top))
    return 0


if __name__ == "__main__":
    exit(main())
