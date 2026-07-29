"""Build the frozen Matchday baseline tournament report."""

from __future__ import annotations

import argparse

from baseline_tournament import build_report, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-ledger", nargs="+", required=True)
    parser.add_argument("--market-ledger")
    parser.add_argument("--output", default="baseline_tournament_report.json")
    args = parser.parse_args()
    report = build_report(args.forecast_ledger, args.market_ledger)
    write_report(args.output, report)
    print(f"eligible={report['coverage']['eligible']} common={report['all_models_common_fixtures']} "
          f"status={report['status']}")


if __name__ == "__main__":
    main()
