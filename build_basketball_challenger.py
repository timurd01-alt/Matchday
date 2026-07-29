"""Build chronological basketball box-score rows and an ablation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from basketball_challenger import ablation_report, build_point_in_time_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Authorized normalized paired box-score JSON")
    parser.add_argument("--rows-output", default="basketball_challenger_rows.jsonl")
    parser.add_argument("--report-output", default="basketball_challenger_report.json")
    parser.add_argument("--min-history", type=int, default=5)
    parser.add_argument("--rolling-games", type=int, default=20)
    parser.add_argument("--min-train", type=int, default=100)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    boxes = payload.get("rows", payload) if isinstance(payload, dict) else payload
    rows = build_point_in_time_rows(boxes, args.min_history, args.rolling_games)
    report = ablation_report(rows, args.min_train)
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with Path(args.rows_output).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"rows={len(rows)} out_of_sample={report['full']['model']['n']} "
          f"decision={report['promotion_gate']['decision']} production_weight=0")


if __name__ == "__main__":
    main()
