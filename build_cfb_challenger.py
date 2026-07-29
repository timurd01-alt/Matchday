"""Build point-in-time CFBD advanced rows and a zero-weight ablation report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cfb_challenger import ablation_report, build_point_in_time_rows


def _load(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("rows", payload) if isinstance(payload, dict) else payload


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", required=True, help="Authorized CFBD /games JSON export")
    parser.add_argument("--advanced", required=True, help="Authorized normalized advanced game JSON")
    parser.add_argument("--talent", required=True, help="Authorized CFBD /talent JSON with season/year")
    parser.add_argument("--rows-output", default="cfb_challenger_rows.jsonl")
    parser.add_argument("--report-output", default="cfb_challenger_report.json")
    parser.add_argument("--min-history", type=int, default=3)
    parser.add_argument("--rolling-games", type=int, default=12)
    parser.add_argument("--min-train", type=int, default=100)
    args = parser.parse_args()
    paths = {name: Path(getattr(args, name)) for name in ("games", "advanced", "talent")}
    rows = build_point_in_time_rows(
        _load(paths["games"]), _load(paths["advanced"]), _load(paths["talent"]),
        args.min_history, args.rolling_games,
        {name: _hash(path) for name, path in paths.items()},
    )
    report = ablation_report(rows, args.min_train)
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with Path(args.rows_output).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"rows={len(rows)} out_of_sample={report['full']['model']['n']} "
          f"decision={report['promotion_gate']['decision']} production_weight=0")


if __name__ == "__main__":
    main()
