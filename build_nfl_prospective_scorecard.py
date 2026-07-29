"""Build the read-only NFL prospective shadow scorecard from forecast ledgers."""

from __future__ import annotations

import argparse

from nfl_prospective_scorecard import build_report, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", nargs="+", required=True,
                        help="One or more tamper-evident forecast_ledger_*.jsonl files")
    parser.add_argument("--output", default="nfl_prospective_scorecard.json")
    args = parser.parse_args()
    report = build_report(args.ledger)
    write_report(args.output, report)
    models = report["models"]
    print(f"eligible={models['calibrated_elo']['n']} status={report['status']}")
    print(f"calibrated_elo_log_loss={models['calibrated_elo']['log_loss']} "
          f"raw_elo_log_loss={models['raw_elo']['log_loss']} "
          f"challenger_log_loss={models['advanced_challenger']['log_loss']}")


if __name__ == "__main__":
    main()
