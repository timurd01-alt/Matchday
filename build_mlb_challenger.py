"""Build chronological MLB challenger rows from official Retrosheet files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_advanced_metrics import re_event_file
from mlb_challenger import MODEL_VERSION, ablation_report, build_point_in_time_rows, fit_standings_compatible_model


def _files(root: Path, event: bool) -> list[Path]:
    files = [path for path in root.rglob("*") if path.is_file()]
    if event:
        return sorted(path for path in files if re_event_file(path))
    return sorted(path for path in files if path.name.upper().startswith("GL") and path.suffix.upper() in {".TXT", ".CSV"})


def _hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8")); digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _lines(paths: list[Path]):
    for path in paths:
        yield from path.read_text(encoding="latin-1").splitlines()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-root", required=True)
    parser.add_argument("--gamelogs-root", required=True)
    parser.add_argument("--rows-output", default="mlb_challenger_rows.jsonl")
    parser.add_argument("--report-output", default="mlb_challenger_report.json")
    parser.add_argument("--model-output", default="mlb_run_strength_model_v1.json")
    parser.add_argument("--min-history", type=int, default=10)
    parser.add_argument("--rolling-games", type=int, default=40)
    parser.add_argument("--min-train", type=int, default=1000)
    args = parser.parse_args()

    event_files = _files(Path(args.events_root), True)
    game_log_files = _files(Path(args.gamelogs_root), False)
    if not event_files or not game_log_files:
        raise SystemExit("Retrosheet event files and game-log files are both required")
    hashes = {"event_files_sha256": _hash(event_files), "game_logs_sha256": _hash(game_log_files)}
    rows, rejected = build_point_in_time_rows(_lines(event_files), _lines(game_log_files),
                                               args.min_history, args.rolling_games, hashes)
    report = ablation_report(rows, args.min_train)
    report["coverage"] = {"event_files": len(event_files), "game_log_files": len(game_log_files),
                          "complete_games": len(rows), "rejected": rejected}
    report["source"] = {
        "name": "Retrosheet event files and game logs",
        "notice": ('The information used here was obtained free of charge from and is copyrighted by '
                   'Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".'),
        "retrieved_by_user": True,
    }
    fitted = fit_standings_compatible_model(rows)
    artifact = {
        "schema_version": 1, "model_version": MODEL_VERSION,
        "research_only": True, "shadow_only": True, "production_weight": 0,
        "source": report["source"], "source_hashes": hashes,
        "feature_contract": "licensed live season runs-for/runs-against through the prior completed game",
        "features": report["standings_compatible_candidate"]["features"],
        "historical_validation": report["standings_compatible_candidate"],
        "promotion_status": "eligible_for_prospective_shadow_not_production",
        **fitted,
    }
    Path(args.report_output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(args.model_output).write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with Path(args.rows_output).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"rows={len(rows)} out_of_sample={report['full']['model']['n']} "
          f"decision={report['promotion_gate']['decision']} production_weight=0")


if __name__ == "__main__":
    main()
