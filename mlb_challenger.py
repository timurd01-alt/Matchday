"""Leakage-resistant MLB challenger from Retrosheet event files and game logs.

Target-game starters, lineups, weather, and results never enter a feature row.
Every feature is computed from completed prior date blocks only.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
import re
from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Sequence

from advanced_metrics import _mean
from nfl_challenger import fit_logistic, predict_probability


MODEL_VERSION = "retrosheet-mlb-challenger-0.1.0"
HOME_ELO_ADVANTAGE = 32.0
FEATURE_FAMILIES = {
    "run_strength": ["pythagorean_diff", "run_diff_per_game_diff"],
    "plate_discipline": ["k_minus_bb_edge", "strikeout_rate_diff", "free_pass_rate_diff"],
    "power_contact": ["isolated_power_proxy_diff", "home_run_rate_diff", "hit_rate_diff"],
    "run_prevention": ["defense_independent_edge", "opponent_hit_rate_edge"],
    "bullpen_workload": ["bullpen_usage_3d_edge", "bullpen_coverage_mean"],
    "context": ["rest_diff", "history_gap", "season_progress"],
}
FEATURE_NAMES = [name for names in FEATURE_FAMILIES.values() for name in names]
_NON_PA = {"NP", "BK", "DI", "OA", "PB", "WP"}


def _csv(line: str) -> list[str]:
    try:
        return next(csv.reader([line]))
    except (csv.Error, StopIteration):
        return []


def _game_id(home: str, raw_date: str, number: str) -> str:
    digits = re.sub(r"\D", "", raw_date)
    return f"{home}{digits}{number or '0'}" if home and len(digits) == 8 else ""


def parse_game_logs(lines: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Parse the stable first 11 fields of official Retrosheet game logs."""
    games = {}
    for raw in lines:
        fields = _csv(raw)
        if len(fields) < 11:
            continue
        raw_date, number, away, home = fields[0].strip(), fields[1].strip(), fields[3].strip(), fields[6].strip()
        game_id = _game_id(home, raw_date, number)
        try:
            away_runs, home_runs = int(fields[9]), int(fields[10])
            game_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])).isoformat()
        except (TypeError, ValueError):
            continue
        if not game_id or not away or not home or away_runs == home_runs:
            continue
        games[game_id] = {
            "game_id": game_id, "game_date": game_date, "season": int(raw_date[:4]),
            "away_team": away, "home_team": home,
            "away_runs": away_runs, "home_runs": home_runs,
        }
    return games


def _is_plate_appearance(primary: str) -> bool:
    if not primary or primary in _NON_PA or primary.startswith(("SB", "CS", "PO")):
        return False
    return bool(re.match(r"^(?:K(?!E)|W|IW|HP|S(?!B)|D(?!I)|T|HR|E|FC|C|FLE|[1-9])", primary))


def parse_event_games(lines: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Collapse raw event records into per-game batting and pitcher-use counts."""
    games: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for raw in lines:
        fields = _csv(raw.strip())
        if not fields:
            continue
        kind = fields[0]
        if kind == "id" and len(fields) > 1:
            current = {
                "game_id": fields[1].strip(), "away_team": "", "home_team": "",
                "batting": defaultdict(lambda: defaultdict(float)),
                "pitchers": defaultdict(set),
            }
            games[current["game_id"]] = current
            continue
        if current is None:
            continue
        if kind == "info" and len(fields) > 2:
            if fields[1] == "visteam":
                current["away_team"] = fields[2].strip()
            elif fields[1] == "hometeam":
                current["home_team"] = fields[2].strip()
            continue
        if kind in {"start", "sub"} and len(fields) > 5 and fields[5].strip() == "1":
            team = current["away_team"] if fields[3].strip() == "0" else current["home_team"]
            if team:
                current["pitchers"][team].add(fields[1].strip())
            continue
        if kind != "play" or len(fields) < 7:
            continue
        team = current["away_team"] if fields[2].strip() == "0" else current["home_team"]
        primary = fields[6].split(".", 1)[0].split("/", 1)[0].strip()
        if not team or not _is_plate_appearance(primary):
            continue
        totals = current["batting"][team]
        totals["pa"] += 1
        if re.match(r"^K(?!E)", primary):
            totals["strikeouts"] += 1
        if re.match(r"^(?:W|IW|HP)", primary):
            totals["free_passes"] += 1
        if re.match(r"^(?:S(?!B)|D(?!I)|T|HR)", primary):
            totals["hits"] += 1
        if re.match(r"^D(?!I)", primary):
            totals["doubles"] += 1
        if primary.startswith("T"):
            totals["triples"] += 1
        if primary.startswith("HR"):
            totals["home_runs"] += 1
    return games


def retrosheet_game_records(event_lines: Iterable[str], game_log_lines: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    events, logs = parse_event_games(event_lines), parse_game_logs(game_log_lines)
    records, rejected = [], defaultdict(int)
    for game_id, game in sorted(logs.items(), key=lambda item: (item[1]["game_date"], item[0])):
        event = events.get(game_id)
        if not event:
            rejected["missing_event_game"] += 1
            continue
        home, away = game["home_team"], game["away_team"]
        if event["home_team"] != home or event["away_team"] != away:
            rejected["team_mismatch"] += 1
            continue
        if not event["batting"].get(home) or not event["batting"].get(away):
            rejected["incomplete_batting_pair"] += 1
            continue
        for team, opponent, is_home in ((home, away, True), (away, home, False)):
            offense = event["batting"][team]
            allowed = event["batting"][opponent]
            records.append({
                "game_id": game_id, "game_date": game["game_date"], "season": game["season"],
                "team": team, "opponent": opponent, "is_home": is_home,
                "runs": game["home_runs"] if is_home else game["away_runs"],
                "runs_allowed": game["away_runs"] if is_home else game["home_runs"],
                **{name: float(offense.get(name, 0.0)) for name in
                   ("pa", "strikeouts", "free_passes", "hits", "doubles", "triples", "home_runs")},
                **{f"opponent_{name}": float(allowed.get(name, 0.0)) for name in
                   ("pa", "strikeouts", "free_passes", "hits", "home_runs")},
                "pitchers_used": len(event["pitchers"].get(team, set())),
                "bullpen_observed": bool(event["pitchers"].get(team)),
            })
    return records, dict(rejected)


def _elo_probability(home: float, away: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(home + HOME_ELO_ADVANTAGE - away) / 400.0))


def _update_elo(elo: dict[str, float], home: str, away: str, outcome: float, margin: int) -> None:
    expected = _elo_probability(elo.get(home, 1500.0), elo.get(away, 1500.0))
    change = 12.0 * min(2.0, max(1.0, math.log1p(abs(margin)))) * (outcome - expected)
    elo[home] = elo.get(home, 1500.0) + change
    elo[away] = elo.get(away, 1500.0) - change


def _profile(games: Sequence[dict[str, Any]]) -> dict[str, float]:
    totals = defaultdict(float)
    for game in games:
        for key, value in game.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] += float(value)
    pa, opp_pa = totals["pa"], totals["opponent_pa"]
    count = max(1.0, float(len(games)))
    rs, ra = totals["runs"], totals["runs_allowed"]
    denominator = rs ** 1.83 + ra ** 1.83
    return {
        "pythagorean": rs ** 1.83 / denominator if denominator else .5,
        "run_diff_per_game": (rs - ra) / count,
        "strikeout_rate": totals["strikeouts"] / pa if pa else 0.0,
        "free_pass_rate": totals["free_passes"] / pa if pa else 0.0,
        "k_minus_bb": (totals["strikeouts"] - totals["free_passes"]) / pa if pa else 0.0,
        "isolated_power_proxy": (totals["doubles"] + 2 * totals["triples"] + 3 * totals["home_runs"]) / pa if pa else 0.0,
        "home_run_rate": totals["home_runs"] / pa if pa else 0.0,
        "hit_rate": totals["hits"] / pa if pa else 0.0,
        "opponent_hit_rate": totals["opponent_hits"] / opp_pa if opp_pa else 0.0,
        "defense_independent_allowed": ((totals["opponent_free_passes"] - totals["opponent_strikeouts"]
                                          + 3 * totals["opponent_home_runs"]) / opp_pa if opp_pa else 0.0),
        "event_coverage": float(pa > 0 and opp_pa > 0),
        "bullpen_coverage": sum(bool(game.get("bullpen_observed")) for game in games) / count,
    }


def _bullpen_usage(history: Sequence[dict[str, Any]], target_day: str) -> float:
    target = date.fromisoformat(target_day)
    return sum(max(0.0, float(game.get("pitchers_used") or 0) - 1.0) for game in history
               if 0 < (target - date.fromisoformat(game["game_date"])).days <= 3)


def _features(home: str, away: str, history: dict[str, list[dict[str, Any]]], last_played: dict[str, str],
              target_day: str, rolling_games: int, season_game: int) -> dict[str, float]:
    hp = _profile(history.get(home, [])[-rolling_games:])
    ap = _profile(history.get(away, [])[-rolling_games:])
    target = date.fromisoformat(target_day)
    rests = [min(7, max(0, (target - date.fromisoformat(last_played[team])).days)) if team in last_played else 3
             for team in (home, away)]
    values = {
        "pythagorean_diff": hp["pythagorean"] - ap["pythagorean"],
        "run_diff_per_game_diff": hp["run_diff_per_game"] - ap["run_diff_per_game"],
        "k_minus_bb_edge": ap["k_minus_bb"] - hp["k_minus_bb"],
        "strikeout_rate_diff": hp["strikeout_rate"] - ap["strikeout_rate"],
        "free_pass_rate_diff": hp["free_pass_rate"] - ap["free_pass_rate"],
        "isolated_power_proxy_diff": hp["isolated_power_proxy"] - ap["isolated_power_proxy"],
        "home_run_rate_diff": hp["home_run_rate"] - ap["home_run_rate"],
        "hit_rate_diff": hp["hit_rate"] - ap["hit_rate"],
        "defense_independent_edge": ap["defense_independent_allowed"] - hp["defense_independent_allowed"],
        "opponent_hit_rate_edge": ap["opponent_hit_rate"] - hp["opponent_hit_rate"],
        "bullpen_usage_3d_edge": (_bullpen_usage(history.get(away, []), target_day)
                                   - _bullpen_usage(history.get(home, []), target_day)) / 6.0,
        "bullpen_coverage_mean": (hp["bullpen_coverage"] + ap["bullpen_coverage"]) / 2.0,
        "rest_diff": (rests[0] - rests[1]) / 3.0,
        "history_gap": (len(history.get(home, [])) - len(history.get(away, []))) / float(rolling_games),
        "season_progress": min(1.0, season_game / 162.0),
    }
    return {name: float(values[name]) for name in FEATURE_NAMES}


def build_point_in_time_rows(event_lines: Iterable[str], game_log_lines: Iterable[str], min_history: int = 10,
                             rolling_games: int = 40, source_hashes: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records, rejected = retrosheet_game_records(event_lines, game_log_lines)
    paired: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        paired[record["game_id"]].append(record)
    by_date: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for pair in paired.values():
        if len(pair) == 2 and {row["is_home"] for row in pair} == {True, False}:
            by_date[pair[0]["game_date"]].append(pair)

    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    last_played: dict[str, str] = {}
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    current_season = None
    observed_through = None
    rows = []
    for game_day in sorted(by_date):
        season = int(game_day[:4])
        if season != current_season:
            if current_season is not None:
                for team in list(elo):
                    elo[team] = 1500.0 + .67 * (elo[team] - 1500.0)
            history, last_played, observed_through, current_season = defaultdict(list), {}, None, season
        for pair in sorted(by_date[game_day], key=lambda value: value[0]["game_id"]):
            home = next(row for row in pair if row["is_home"])
            away = next(row for row in pair if not row["is_home"])
            h, a = home["team"], away["team"]
            rows.append({
                "schema_version": 1, "game_id": home["game_id"], "game_date": game_day,
                "block_id": game_day, "season": season, "home_team": h, "away_team": a,
                "home_history_games": len(history[h]), "away_history_games": len(history[a]),
                "eligible": len(history[h]) >= min_history and len(history[a]) >= min_history,
                "features": _features(h, a, history, last_played, game_day, rolling_games, len(history[h])),
                "elo_home_probability": _elo_probability(elo[h], elo[a]),
                "outcome": float(home["runs"] > away["runs"]), "margin": home["runs"] - away["runs"],
                "feature_observed_through": observed_through,
                "timestamp_quality": "prior_completed_game_date_boundary",
                "target_game_personnel_used": False,
                "unavailable_pregame_families": ["confirmed_starter", "confirmed_lineup", "weather"],
                "source_hashes": source_hashes or {},
            })
        for pair in by_date[game_day]:
            home = next(row for row in pair if row["is_home"])
            away = next(row for row in pair if not row["is_home"])
            history[home["team"]].append(home); history[away["team"]].append(away)
            last_played[home["team"]] = game_day; last_played[away["team"]] = game_day
            _update_elo(elo, home["team"], away["team"], float(home["runs"] > away["runs"]),
                        home["runs"] - away["runs"])
        observed_through = game_day
    return rows, rejected


def _metrics(predictions: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    if not predictions:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    losses, briers, hits = [], [], []
    for item in predictions:
        p, y = min(.999, max(.001, float(item[key]))), float(item["outcome"])
        losses.append(-(y * math.log(p) + (1-y) * math.log(1-p)))
        briers.append((p-y) ** 2); hits.append(float((p >= .5) == bool(y)))
    return {"n": len(predictions), "log_loss": round(_mean(losses) or 0.0, 6),
            "brier": round(_mean(briers) or 0.0, 6), "accuracy": round(_mean(hits) or 0.0, 6)}


def rolling_backtest(rows: Sequence[dict[str, Any]], feature_names: Sequence[str] = FEATURE_NAMES,
                     min_train: int = 1000, use_elo_offset: bool = True) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible")]
    seasons = sorted({row["season"] for row in eligible})
    predictions = []
    for season in seasons:
        train = [row for row in eligible if row["season"] < season]
        test = [row for row in eligible if row["season"] == season]
        if len(train) < min_train or not test:
            continue
        baseline_key = "elo_home_probability" if use_elo_offset else None
        model = fit_logistic(train, feature_names, l2=8.0, iterations=180,
                             baseline_probability_key=baseline_key)
        for row in test:
            predictions.append({"game_id": row["game_id"], "game_date": row["game_date"],
                                "season": season, "outcome": row["outcome"],
                                "probability": predict_probability(
                                    model, row["features"],
                                    row["elo_home_probability"] if use_elo_offset else None),
                                "elo_probability": row["elo_home_probability"]})
    return {"model": _metrics(predictions, "probability"), "elo": _metrics(predictions, "elo_probability"),
            "predictions": predictions,
            "design": {"rolling_origin": "train prior seasons, test next untouched season",
                       "min_train": min_train, "elo_offset": use_elo_offset}}


def standings_compatible_backtest(rows: Sequence[dict[str, Any]], min_train: int = 1000) -> dict[str, Any]:
    """Evaluate the subset reconstructible from Matchday's licensed live team totals."""
    return rolling_backtest(rows, FEATURE_FAMILIES["run_strength"], min_train, use_elo_offset=False)


def fit_standings_compatible_model(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible")]
    model = fit_logistic(eligible, FEATURE_FAMILIES["run_strength"], l2=8.0, iterations=180)
    return {"model": model, "training_rows": len(eligible),
            "trained_through": max((row["game_date"] for row in eligible), default=None)}


def _paired_interval(primary: Sequence[dict[str, Any]], comparison: Sequence[dict[str, Any]] | None = None,
                     samples: int = 3000) -> dict[str, Any]:
    other = {(row["game_date"], row["game_id"]): row for row in (comparison or [])}
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in primary:
        y = float(row["outcome"]); p = min(.999, max(.001, float(row["probability"])))
        qrow = other.get((row["game_date"], row["game_id"])) if comparison is not None else row
        if qrow is None:
            continue
        q = min(.999, max(.001, float(qrow["probability"] if comparison is not None else row["elo_probability"])))
        grouped[row["game_date"]].append(-(y*math.log(p)+(1-y)*math.log(1-p)) + (y*math.log(q)+(1-y)*math.log(1-q)))
    blocks = sorted(grouped); values = [value for block in blocks for value in grouped[block]]
    result = {"n": len(values), "blocks": len(blocks), "mean_log_loss_delta": round(_mean(values) or 0.0, 6) if values else None,
              "ci95": [None, None], "method": "deterministic game-date block bootstrap"}
    if len(blocks) < 2:
        return result
    rng = random.Random(int(hashlib.sha256("|".join(blocks).encode()).hexdigest()[:16], 16))
    estimates = []
    for _ in range(samples):
        draw = [value for block in (rng.choice(blocks) for _ in blocks) for value in grouped[block]]
        estimates.append(sum(draw) / len(draw))
    estimates.sort(); result["ci95"] = [round(estimates[int(samples*.025)], 6), round(estimates[min(samples-1, int(samples*.975))], 6)]
    return result


def ablation_report(rows: Sequence[dict[str, Any]], min_train: int = 1000) -> dict[str, Any]:
    full = rolling_backtest(rows, FEATURE_NAMES, min_train)
    families = {}
    for family, removed in FEATURE_FAMILIES.items():
        result = rolling_backtest(rows, [name for name in FEATURE_NAMES if name not in removed], min_train)
        families[family] = {"removed_features": removed, "model": result["model"],
                            "full_vs_without_family": _paired_interval(full["predictions"], result["predictions"])}
    paired = _paired_interval(full["predictions"])
    checks = {
        "minimum_out_of_sample_games": full["model"]["n"] >= 1000,
        "minimum_test_seasons": len({row["season"] for row in full["predictions"]}) >= 2,
        "log_loss_better_than_elo": (full["model"]["log_loss"] is not None and full["model"]["log_loss"] < full["elo"]["log_loss"]),
        "brier_not_worse_than_elo": (full["model"]["brier"] is not None and full["model"]["brier"] <= full["elo"]["brier"]),
        "paired_interval_below_zero": paired["ci95"][1] is not None and paired["ci95"][1] < 0,
    }
    passed = all(checks.values())
    live = standings_compatible_backtest(rows, min_train)
    live_paired = _paired_interval(live["predictions"])
    live_checks = {
        "minimum_out_of_sample_games": live["model"]["n"] >= 1000,
        "minimum_test_seasons": len({row["season"] for row in live["predictions"]}) >= 2,
        "log_loss_better_than_elo": (live["model"]["log_loss"] is not None
                                      and live["model"]["log_loss"] < live["elo"]["log_loss"]),
        "brier_not_worse_than_elo": (live["model"]["brier"] is not None
                                      and live["model"]["brier"] <= live["elo"]["brier"]),
        "paired_interval_below_zero": live_paired["ci95"][1] is not None and live_paired["ci95"][1] < 0,
    }
    return {"schema_version": 1, "model_version": MODEL_VERSION, "research_only": True,
            "production_weight": 0, "full": {"model": full["model"], "elo": full["elo"], "design": full["design"]},
            "paired_vs_elo": paired, "ablations": families,
            "promotion_gate": {"checks": checks, "decision": "eligible_for_prospective_review" if passed else "remain_research_only"},
            "standings_compatible_candidate": {
                "features": FEATURE_FAMILIES["run_strength"], "model": live["model"], "elo": live["elo"],
                "paired_vs_elo": live_paired, "checks": live_checks,
                "decision": "eligible_for_prospective_shadow" if all(live_checks.values()) else "remain_research_only",
            },
            "live_personnel_gate": {"decision": "blocked_without_timestamped_pregame_source",
                                    "required": ["probable_or_confirmed_starter", "lineup", "bullpen_availability"]}}
