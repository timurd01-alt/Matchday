r"""Build Matchday's point-in-time NFL research challenger.

Example:
  python build_nfl_challenger.py --input nflverse_pbp_2023.csv.gz `
    nflverse_pbp_2024.csv.gz nflverse_pbp_2025.csv.gz
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

from nfl_challenger import (
    ablation_report,
    aggregate_games,
    build_point_in_time_rows,
    make_artifact,
    source_sha256,
    write_json,
)


def read_rows(paths):
    for path in paths:
        opener = gzip.open if path.suffix.lower() == ".gz" else open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, help="Approved nflverse PBP CSV/CSV.GZ files")
    parser.add_argument("--artifact", default="nfl_challenger_model.json")
    parser.add_argument("--rows-output", default="nfl_challenger_training_rows.jsonl")
    parser.add_argument("--report-output", default="nfl_challenger_backtest.json")
    parser.add_argument("--rolling-games", type=int, default=16)
    parser.add_argument("--min-history", type=int, default=4)
    parser.add_argument("--min-train", type=int, default=96)
    parser.add_argument("--test-size", type=int, default=32)
    args = parser.parse_args()

    paths = [Path(value) for value in args.input]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise SystemExit(f"missing input file(s): {', '.join(missing)}")
    hashes = {path.name: source_sha256(path) for path in paths}
    games = aggregate_games(read_rows(paths))
    rows, state = build_point_in_time_rows(games, args.rolling_games, args.min_history, hashes)
    eligible = [row for row in rows if row.get("eligible")]
    if len(eligible) <= args.min_train:
        raise SystemExit(f"only {len(eligible)} eligible games; need more than --min-train={args.min_train}")
    report = ablation_report(rows, args.min_train, args.test_size)
    artifact = make_artifact(rows, state, report, hashes)
    write_json(args.artifact, artifact)
    write_json(args.report_output, report)
    with Path(args.rows_output).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"games={len(games)} eligible_rows={len(eligible)}")
    print(f"shadow artifact: {args.artifact}")
    print(f"rolling log loss={report['full']['model']['log_loss']} elo={report['full']['elo']['log_loss']}")
    print(f"promotion_status={artifact['promotion_status']} production_weight=0")


if __name__ == "__main__":
    main()
