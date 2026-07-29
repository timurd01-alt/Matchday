"""Build the read-only MLB prospective shadow scorecard from forecast ledgers."""

from __future__ import annotations

import argparse

from mlb_prospective_scorecard import build_report, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", nargs="+", required=True,
                        help="One or more tamper-evident forecast_ledger_*.jsonl files")
    parser.add_argument("--output", default="mlb_prospective_scorecard.json")
    args = parser.parse_args()
    report = build_report(args.ledger)
    write_report(args.output, report)
    models = report["models"]
    print(f"eligible={models['official']['n']} status={report['status']}")
    print(f"challenger_log_loss={models['run_strength_challenger']['log_loss']} "
          f"official_log_loss={models['official']['log_loss']}")


if __name__ == "__main__":
    main()
