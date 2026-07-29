"""Build a zero-weight three-way challenger from a local StatsBomb Open Data tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from soccer_challenger import ablation_report, build_point_in_time_rows


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Local official hudl/open-data checkout")
    parser.add_argument("--competition-id", required=True)
    parser.add_argument("--season-id", required=True)
    parser.add_argument("--rows-output", default="soccer_challenger_rows.jsonl")
    parser.add_argument("--report-output", default="soccer_challenger_report.json")
    parser.add_argument("--min-history", type=int, default=3)
    parser.add_argument("--rolling-matches", type=int, default=12)
    parser.add_argument("--min-train", type=int, default=100)
    args = parser.parse_args()
    root = Path(args.root)
    matches_path = root / "data" / "matches" / args.competition_id / f"{args.season_id}.json"
    matches = json.loads(matches_path.read_text(encoding="utf-8"))
    for match in matches:
        match.setdefault("competition_id", args.competition_id)
        match.setdefault("season_id", args.season_id)
    event_paths, events = [], []
    for match in matches:
        match_id = str(match.get("match_id") or "")
        path = root / "data" / "events" / f"{match_id}.json"
        if not match_id or not path.exists():
            continue
        event_paths.append(path)
        match_events = json.loads(path.read_text(encoding="utf-8"))
        for event in match_events:
            event.setdefault("match_id", match_id)
        events.extend(match_events)
    rows = build_point_in_time_rows(
        matches, events, args.min_history, args.rolling_matches,
        {"matches": _hash_files([matches_path]), "events_manifest": _hash_files(event_paths)},
    )
    report = ablation_report(rows, args.min_train)
    report["coverage"]["metadata_matches"] = len(matches)
    report["coverage"]["event_files"] = len(event_paths)
    report["coverage"]["missing_event_files"] = len(matches) - len(event_paths)
    report["source"] = {
        "name": "StatsBomb Open Data", "repository": "https://github.com/hudl/open-data",
        "attribution_required": True, "attach_live": False,
    }
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with Path(args.rows_output).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"rows={len(rows)} event_files={len(event_paths)}/{len(matches)} "
          f"out_of_sample={report['full']['model']['n']} "
          f"decision={report['promotion_gate']['decision']} production_weight=0")


if __name__ == "__main__":
    main()
