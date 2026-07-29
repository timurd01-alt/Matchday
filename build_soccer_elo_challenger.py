"""Build a frozen domestic-soccer cold-start shadow from licensed historical results."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import fetch_data
from soccer_elo_challenger import (DEFAULT_PARAMS, MODEL_VERSION, metrics,
                                   paired_week_interval, replay, source_hash, tune)


COMPETITIONS = ("EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1")
SEASONS = (2023, 2024, 2025)


def _write_cache(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def fetch_rows(cache_path: str | Path = "soccer_elo_history_cache.json") -> list[dict]:
    cache_file = Path(cache_path)
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    rows = []
    made_request = False
    for competition in COMPETITIONS:
        for season in SEASONS:
            key = f"{competition}:{season}"
            season_rows = cache.get(key)
            if not isinstance(season_rows, list):
                if made_request:
                    time.sleep(7)
                season_rows = fetch_data.fetch_football_data_historical_season(competition, season)
                cache[key] = season_rows
                _write_cache(cache_file, cache)
                made_request = True
                origin = "fetched"
            else:
                origin = "cache"
            for row in season_rows:
                rows.append({**row, "competition": competition, "season": season})
            print(f"{competition} {season}: {len(season_rows)} finished matches ({origin})")
    return rows


def build(rows: list[dict]) -> tuple[dict, dict]:
    params, validation = tune(rows, 2024)
    candidate_rows, state = replay(rows, params, 2025)
    baseline_rows, _ = replay(rows, DEFAULT_PARAMS, 2025)
    candidate_metrics, baseline_metrics = metrics(candidate_rows), metrics(baseline_rows)
    comparison = paired_week_interval(candidate_rows, baseline_rows)
    passed = bool(
        candidate_metrics["log_loss"] < baseline_metrics["log_loss"]
        and candidate_metrics["brier"] <= baseline_metrics["brier"]
        and comparison["ci95"][1] is not None and comparison["ci95"][1] < 0
        and candidate_metrics["n"] >= 1500
    )
    gate = {"passed": passed, "checks": {
        "log_loss_better_than_default_elo": candidate_metrics["log_loss"] < baseline_metrics["log_loss"],
        "brier_not_worse_than_default_elo": candidate_metrics["brier"] <= baseline_metrics["brier"],
        "paired_ci_excludes_no_improvement": comparison["ci95"][1] is not None and comparison["ci95"][1] < 0,
        "minimum_out_of_sample_games": candidate_metrics["n"] >= 1500,
    }, "decision": "eligible_for_prospective_shadow" if passed else "remain_offline_research"}
    report = {"schema_version": 1, "model_version": MODEL_VERSION,
              "design": {"tuning_season": 2024, "frozen_test_season": 2025,
                         "competitions": list(COMPETITIONS), "timing": "predict then update"},
              "validation": validation, "selected_params": params,
              "test": {"candidate": candidate_metrics, "default_elo": baseline_metrics,
                       "paired_bootstrap": comparison}, "promotion_gate": gate}
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    artifact = {"schema_version": 1, "model_version": MODEL_VERSION, "generated_at": generated,
                "source": "football-data.org licensed historical match results",
                "source_reference": "provider-contract:football-data.org",
                "source_hash": source_hash(rows), "competitions": list(COMPETITIONS),
                "trained_seasons": list(SEASONS), "trained_through": "2026-05-31",
                "research_only": True, "shadow_only": True, "production_weight": 0,
                "params": params, "state": state, "historical_gate": gate,
                "limitations": ["club transfers and manager changes are not modeled",
                                "newly promoted clubs begin at the league-neutral rating",
                                "prospective evidence is required before any production weight"]}
    return artifact, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="soccer_elo_challenger_model.json")
    parser.add_argument("--report", default="soccer_elo_challenger_backtest.json")
    parser.add_argument("--cache", default="soccer_elo_history_cache.json")
    args = parser.parse_args()
    artifact, report = build(fetch_rows(args.cache))
    Path(args.model).write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8", newline="\n")
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8", newline="\n")
    print(json.dumps(report["test"], indent=2))
    print(report["promotion_gate"])


if __name__ == "__main__":
    main()
