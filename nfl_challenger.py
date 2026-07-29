"""Leakage-resistant NFL research challenger built from approved nflverse PBP.

The module intentionally has no network access and no production-pick hooks.
Every target-game feature is computed from completed prior week-blocks only.
Artifacts produced from this module must remain ``research_only`` until the
promotion protocol in ``docs/PREDICTION_RESEARCH_ROADMAP.md`` is satisfied.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


MODEL_VERSION = "nfl-challenger-0.1.0-shadow"
SCHEMA_VERSION = 1
ROLLING_GAMES = 16
HOME_ELO_ADVANTAGE = 55.0

PAIRED_METRICS = {
    "epa": "off_epa",
    "success": "success_rate",
    "explosive": "explosive_rate",
    "pass_epa": "pass_epa",
    "rush_epa": "rush_epa",
    "neutral_epa": "neutral_epa",
    "early_down_epa": "early_down_epa",
    "sack": "sack_rate",
    "redzone": "redzone_td_rate",
}

FEATURE_FAMILIES = {
    "epa": ["epa_matchup_edge"],
    "success": ["success_matchup_edge"],
    "explosive": ["explosive_matchup_edge"],
    "passing": ["pass_epa_matchup_edge", "cpoe_diff", "sack_matchup_edge"],
    "rushing": ["rush_epa_matchup_edge"],
    "situational": ["neutral_epa_matchup_edge", "early_down_epa_matchup_edge", "redzone_matchup_edge"],
    "pace_special": ["pace_diff", "pace_mean", "special_teams_epa_diff"],
    "rating_context": ["rest_diff", "history_gap"],
}
FEATURE_NAMES = [name for names in FEATURE_FAMILIES.values() for name in names]
STATE_FEATURE_NAMES = FEATURE_NAMES + ["elo_diff"]


def _num(value: Any, default: float | None = 0.0) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _iso_day(value: Any) -> str:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _season_type_order(value: str) -> int:
    return {"PRE": 0, "REG": 1, "POST": 2}.get(str(value).upper(), 3)


def _week_key(game: dict[str, Any]) -> tuple[int, int, int]:
    return (int(game.get("season") or 0), _season_type_order(game.get("season_type", "")),
            int(game.get("week") or 0))


def source_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aggregate_games(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse nflverse play rows into auditable team-game summaries."""
    games: dict[str, dict[str, Any]] = {}

    def game_record(raw: dict[str, Any]) -> dict[str, Any]:
        game_id = str(raw.get("game_id") or "").strip()
        game = games.setdefault(game_id, {
            "game_id": game_id,
            "season": int(_num(raw.get("season"), 0) or 0),
            "season_type": str(raw.get("season_type") or ""),
            "week": int(_num(raw.get("week"), 0) or 0),
            "game_date": _iso_day(raw.get("game_date")),
            "start_time": str(raw.get("start_time") or ""),
            "home_team": str(raw.get("home_team") or "").strip(),
            "away_team": str(raw.get("away_team") or "").strip(),
            "home_score": None,
            "away_score": None,
            "teams": defaultdict(lambda: defaultdict(float)),
            "drives": {},
            "clocks": defaultdict(list),
        })
        for field in ("season", "week"):
            if not game[field]:
                game[field] = int(_num(raw.get(field), 0) or 0)
        for field in ("season_type", "game_date", "start_time", "home_team", "away_team"):
            if not game[field]:
                game[field] = _iso_day(raw.get(field)) if field == "game_date" else str(raw.get(field) or "").strip()
        home_score = _num(raw.get("home_score"), None)
        away_score = _num(raw.get("away_score"), None)
        if home_score is not None:
            game["home_score"] = int(home_score)
        if away_score is not None:
            game["away_score"] = int(away_score)
        return game

    for raw in rows:
        game_id = str(raw.get("game_id") or "").strip()
        if not game_id:
            continue
        game = game_record(raw)
        offense = str(raw.get("posteam") or "").strip()
        defense = str(raw.get("defteam") or "").strip()
        if not offense or not defense:
            continue

        epa = _num(raw.get("epa"), None)
        special = _num(raw.get("special_teams_play"), 0) == 1
        if special and epa is not None:
            game["teams"][offense]["special_epa_sum"] += epa
            game["teams"][offense]["special_count"] += 1

        pass_play = _num(raw.get("pass_attempt"), 0) == 1 or _num(raw.get("qb_dropback"), 0) == 1
        rush_play = _num(raw.get("rush_attempt"), 0) == 1
        excluded = (_num(raw.get("qb_kneel"), 0) == 1 or _num(raw.get("qb_spike"), 0) == 1 or
                    _num(raw.get("aborted_play"), 0) == 1 or _num(raw.get("play_deleted"), 0) == 1)
        if excluded or not (pass_play or rush_play) or epa is None:
            continue

        stats = game["teams"][offense]
        allowed = game["teams"][defense]
        success = _num(raw.get("success"), None)
        success = float(success if success is not None else epa > 0)
        yards = _num(raw.get("yards_gained"), 0) or 0.0
        explosive = float((pass_play and yards >= 20) or (rush_play and yards >= 10))
        down = int(_num(raw.get("down"), 0) or 0)
        qtr = int(_num(raw.get("qtr"), 0) or 0)
        score_diff = _num(raw.get("score_differential"), 0) or 0.0

        for target, prefix in ((stats, "off"), (allowed, "def")):
            target[f"{prefix}_epa_sum"] += epa
            target[f"{prefix}_plays"] += 1
            target[f"{prefix}_success_sum"] += success
            target[f"{prefix}_explosive_sum"] += explosive
        if pass_play:
            stats["pass_epa_sum"] += epa
            stats["pass_plays"] += 1
            allowed["def_pass_epa_sum"] += epa
            allowed["def_pass_plays"] += 1
            cpoe = _num(raw.get("cpoe"), None)
            if cpoe is not None:
                stats["cpoe_sum"] += cpoe
                stats["cpoe_count"] += 1
            stats["dropbacks"] += 1
            allowed["dropbacks_faced"] += 1
            if _num(raw.get("sack"), 0) == 1:
                stats["sacks_allowed"] += 1
                allowed["sacks_forced"] += 1
        if rush_play:
            stats["rush_epa_sum"] += epa
            stats["rush_plays"] += 1
            allowed["def_rush_epa_sum"] += epa
            allowed["def_rush_plays"] += 1
        if abs(score_diff) <= 8 and qtr <= 3:
            stats["neutral_epa_sum"] += epa
            stats["neutral_plays"] += 1
            allowed["def_neutral_epa_sum"] += epa
            allowed["def_neutral_plays"] += 1
        if down in (1, 2):
            stats["early_epa_sum"] += epa
            stats["early_plays"] += 1
            allowed["def_early_epa_sum"] += epa
            allowed["def_early_plays"] += 1

        drive = str(raw.get("fixed_drive") or raw.get("drive") or "").strip()
        if drive:
            drive_state = game["drives"].setdefault((offense, drive), {"redzone": False, "touchdown": False})
            yardline = _num(raw.get("yardline_100"), None)
            if yardline is not None and yardline <= 20:
                drive_state["redzone"] = True
            if _num(raw.get("touchdown"), 0) == 1:
                drive_state["touchdown"] = True
        remaining = _num(raw.get("game_seconds_remaining"), None)
        if remaining is not None:
            game["clocks"][offense].append(remaining)

    output = []
    for game in games.values():
        if not game["home_team"] or not game["away_team"] or game["home_score"] is None or game["away_score"] is None:
            continue
        for (team, _drive), drive in game["drives"].items():
            if drive["redzone"]:
                game["teams"][team]["redzone_drives"] += 1
                game["teams"][team]["redzone_tds"] += float(drive["touchdown"])
        summaries = {}
        for team in (game["home_team"], game["away_team"]):
            values = game["teams"][team]
            clocks = sorted(set(game["clocks"].get(team, [])), reverse=True)
            elapsed = [before - after for before, after in zip(clocks, clocks[1:]) if 1 <= before - after <= 60]
            summaries[team] = {
                "off_epa": _rate(values["off_epa_sum"], values["off_plays"]),
                "def_epa_allowed": _rate(values["def_epa_sum"], values["def_plays"]),
                "success_rate": _rate(values["off_success_sum"], values["off_plays"]),
                "def_success_allowed": _rate(values["def_success_sum"], values["def_plays"]),
                "explosive_rate": _rate(values["off_explosive_sum"], values["off_plays"]),
                "def_explosive_allowed": _rate(values["def_explosive_sum"], values["def_plays"]),
                "pass_epa": _rate(values["pass_epa_sum"], values["pass_plays"]),
                "def_pass_epa_allowed": _rate(values["def_pass_epa_sum"], values["def_pass_plays"]),
                "rush_epa": _rate(values["rush_epa_sum"], values["rush_plays"]),
                "def_rush_epa_allowed": _rate(values["def_rush_epa_sum"], values["def_rush_plays"]),
                "neutral_epa": _rate(values["neutral_epa_sum"], values["neutral_plays"]),
                "def_neutral_epa_allowed": _rate(values["def_neutral_epa_sum"], values["def_neutral_plays"]),
                "early_down_epa": _rate(values["early_epa_sum"], values["early_plays"]),
                "def_early_down_epa_allowed": _rate(values["def_early_epa_sum"], values["def_early_plays"]),
                "cpoe": _rate(values["cpoe_sum"], values["cpoe_count"]),
                "sack_rate": _rate(values["sacks_allowed"], values["dropbacks"]),
                "def_sack_rate": _rate(values["sacks_forced"], values["dropbacks_faced"]),
                "redzone_td_rate": _rate(values["redzone_tds"], values["redzone_drives"]),
                "seconds_per_play": _mean(elapsed),
                "special_teams_epa": _rate(values["special_epa_sum"], values["special_count"]),
                "plays": int(values["off_plays"]),
            }
        output.append({
            "game_id": game["game_id"], "season": game["season"], "season_type": game["season_type"],
            "week": game["week"], "game_date": game["game_date"], "start_time": game["start_time"],
            "home_team": game["home_team"], "away_team": game["away_team"],
            "home_score": game["home_score"], "away_score": game["away_score"], "teams": summaries,
        })
    return sorted(output, key=lambda game: (_week_key(game), game["game_date"], game["game_id"]))


def _recent(history: dict[str, list[dict[str, Any]]], team: str, limit: int) -> list[dict[str, Any]]:
    return history.get(team, [])[-limit:]


def _raw_average(history: dict[str, list[dict[str, Any]]], team: str, metric: str, limit: int) -> float:
    return _mean(game.get(metric) for game in _recent(history, team, limit)) or 0.0


def _adjusted_components(history: dict[str, list[dict[str, Any]]], metric: str,
                         limit: int) -> tuple[float, dict[str, float], dict[str, float]]:
    observations = []
    for team, games in history.items():
        for game in games[-limit:]:
            value = game.get(metric)
            if value is not None and game.get("opponent"):
                observations.append((team, game["opponent"], float(value)))
    league = _mean(value for _team, _opponent, value in observations) or 0.0
    offense = defaultdict(float)
    defense = defaultdict(float)
    by_offense: dict[str, list[tuple[str, float]]] = defaultdict(list)
    by_defense: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for team, opponent, value in observations:
        by_offense[team].append((opponent, value))
        by_defense[opponent].append((team, value))
    for _ in range(12):
        next_offense, next_defense = defaultdict(float), defaultdict(float)
        for team, values in by_offense.items():
            shrink = len(values) / (len(values) + 4.0)
            next_offense[team] = shrink * (_mean(value - league - defense[opponent]
                                                   for opponent, value in values) or 0.0)
        for team, values in by_defense.items():
            shrink = len(values) / (len(values) + 4.0)
            next_defense[team] = shrink * (_mean(value - league - next_offense[opponent]
                                                   for opponent, value in values) or 0.0)
        offense, defense = next_offense, next_defense
    return league, dict(offense), dict(defense)


def rating_cache(history: dict[str, list[dict[str, Any]]], limit: int) -> dict[str, tuple[float, dict[str, float], dict[str, float]]]:
    cache = {}
    for family, metric in PAIRED_METRICS.items():
        cache[family] = _adjusted_components(history, metric, limit)
    return cache


def matchup_features(home: str, away: str, history: dict[str, list[dict[str, Any]]],
                     elo: dict[str, float], last_played: dict[str, str], forecast_day: str,
                     rolling_games: int = ROLLING_GAMES,
                     ratings: dict[str, tuple[float, dict[str, float], dict[str, float]]] | None = None
                     ) -> dict[str, float]:
    ratings = ratings or rating_cache(history, rolling_games)
    features: dict[str, float] = {}
    for family, (_league, offense, defense) in ratings.items():
        home_expected = offense.get(home, 0.0) + defense.get(away, 0.0)
        away_expected = offense.get(away, 0.0) + defense.get(home, 0.0)
        features[f"{family}_matchup_edge"] = home_expected - away_expected
    features["cpoe_diff"] = _raw_average(history, home, "cpoe", rolling_games) - _raw_average(history, away, "cpoe", rolling_games)
    home_pace = _raw_average(history, home, "seconds_per_play", rolling_games)
    away_pace = _raw_average(history, away, "seconds_per_play", rolling_games)
    features["pace_diff"] = (home_pace - away_pace) / 10.0
    features["pace_mean"] = ((home_pace + away_pace) / 2.0 - 28.0) / 10.0 if home_pace and away_pace else 0.0
    features["special_teams_epa_diff"] = (_raw_average(history, home, "special_teams_epa", rolling_games) -
                                           _raw_average(history, away, "special_teams_epa", rolling_games))
    features["elo_diff"] = (elo.get(home, 1500.0) - elo.get(away, 1500.0) + HOME_ELO_ADVANTAGE) / 400.0

    target = date.fromisoformat(forecast_day) if forecast_day else None
    rests = []
    for team in (home, away):
        prior = last_played.get(team)
        if target and prior:
            rests.append(max(0, min(21, (target - date.fromisoformat(prior)).days)))
        else:
            rests.append(7)
    features["rest_diff"] = (rests[0] - rests[1]) / 14.0
    home_games = len(_recent(history, home, rolling_games))
    away_games = len(_recent(history, away, rolling_games))
    features["history_gap"] = (home_games - away_games) / float(rolling_games)
    return {name: float(features.get(name, 0.0)) for name in STATE_FEATURE_NAMES}


def _elo_probability(home_elo: float, away_elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(home_elo + HOME_ELO_ADVANTAGE - away_elo) / 400.0))


def _update_elo(elo: dict[str, float], home: str, away: str, home_score: int, away_score: int) -> None:
    expected = _elo_probability(elo.get(home, 1500.0), elo.get(away, 1500.0))
    actual = 1.0 if home_score > away_score else 0.0 if home_score < away_score else 0.5
    margin = abs(home_score - away_score)
    multiplier = math.log(max(1.0, margin) + 1.0) * (2.2 / ((elo.get(home, 1500.0) - elo.get(away, 1500.0)) * 0.001 + 2.2))
    change = 20.0 * max(0.5, multiplier) * (actual - expected)
    elo[home] = elo.get(home, 1500.0) + change
    elo[away] = elo.get(away, 1500.0) - change


def build_point_in_time_rows(games: Sequence[dict[str, Any]], rolling_games: int = ROLLING_GAMES,
                             min_history: int = 4, source_hashes: dict[str, str] | None = None
                             ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create target-game rows, updating histories only after a week is sealed."""
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    last_played: dict[str, str] = {}
    rows = []
    blocks: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        blocks[_week_key(game)].append(game)

    for block_key in sorted(blocks):
        block = sorted(blocks[block_key], key=lambda game: (game["game_date"], game["game_id"]))
        for game in block:
            home, away = game["home_team"], game["away_team"]
            if game["home_score"] == game["away_score"]:
                continue
            home_count, away_count = len(history[home]), len(history[away])
            features = matchup_features(home, away, history, elo, last_played, game["game_date"], rolling_games)
            prior_dates = [last_played.get(home), last_played.get(away)]
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "game_id": game["game_id"], "season": game["season"], "season_type": game["season_type"],
                "week": game["week"], "block_key": list(block_key), "game_date": game["game_date"],
                "forecast_at": f"{game['game_date']}T00:00:00Z",
                "feature_observed_through": max((value for value in prior_dates if value), default=None),
                "timestamp_quality": "prior_completed_week_boundary",
                "home_team": home, "away_team": away,
                "home_history_games": home_count, "away_history_games": away_count,
                "eligible": home_count >= min_history and away_count >= min_history,
                "features": features,
                "elo_home_probability": _elo_probability(elo[home], elo[away]),
                "outcome": 1.0 if game["home_score"] > game["away_score"] else 0.0,
                "home_score": game["home_score"], "away_score": game["away_score"],
                "source_hashes": source_hashes or {},
            })
        # Seal the block only after every target feature has been constructed.
        for game in block:
            home, away = game["home_team"], game["away_team"]
            for team, opponent in ((home, away), (away, home)):
                summary = dict(game["teams"].get(team) or {})
                summary.update({"game_id": game["game_id"], "game_date": game["game_date"], "opponent": opponent})
                history[team].append(summary)
                last_played[team] = game["game_date"]
            _update_elo(elo, home, away, game["home_score"], game["away_score"])

    state = {
        "rolling_games": rolling_games,
        "team_games": {team: games[-rolling_games:] for team, games in history.items()},
        "elo": dict(elo), "last_played": last_played,
        "trained_through": max(last_played.values(), default=None),
    }
    return rows, state


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + exp)
    exp = math.exp(max(value, -40.0))
    return exp / (1.0 + exp)


def fit_logistic(rows: Sequence[dict[str, Any]], feature_names: Sequence[str] = FEATURE_NAMES,
                 l2: float = 5.0, iterations: int = 300, learning_rate: float = 0.12,
                 baseline_probability_key: str | None = None) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible") and row.get("outcome") in (0.0, 1.0)]
    if len(eligible) < 2:
        raise ValueError("at least two eligible NFL rows are required")
    names = list(feature_names)
    means, scales = {}, {}
    for name in names:
        values = [float(row["features"].get(name, 0.0)) for row in eligible]
        means[name] = sum(values) / len(values)
        variance = sum((value - means[name]) ** 2 for value in values) / len(values)
        scales[name] = math.sqrt(variance) if variance > 1e-12 else 1.0
    positives = sum(row["outcome"] for row in eligible)
    prior = min(0.99, max(0.01, positives / len(eligible)))
    intercept = 0.0 if baseline_probability_key else math.log(prior / (1.0 - prior))
    matrix = [[(float(row["features"].get(name, 0.0)) - means[name]) / scales[name] for name in names]
              for row in eligible]
    outcomes = [float(row["outcome"]) for row in eligible]
    offsets = []
    for row in eligible:
        if baseline_probability_key:
            baseline = min(0.995, max(0.005, float(row[baseline_probability_key])))
            offsets.append(math.log(baseline / (1.0 - baseline)))
        else:
            offsets.append(0.0)
    coefficient_values = [0.0] * len(names)
    n = float(len(eligible))
    for step in range(iterations):
        grad_intercept = 0.0
        gradients = [0.0] * len(names)
        for vector, outcome, offset in zip(matrix, outcomes, offsets):
            score = offset + intercept + sum(weight * value for weight, value in zip(coefficient_values, vector))
            error = _sigmoid(score) - outcome
            grad_intercept += error
            for index, value in enumerate(vector):
                gradients[index] += error * value
        rate = learning_rate / math.sqrt(1.0 + step / 100.0)
        intercept_change = rate * grad_intercept / n
        intercept -= intercept_change
        largest_change = abs(intercept_change)
        for index in range(len(names)):
            change = rate * (gradients[index] / n + l2 * coefficient_values[index] / n)
            coefficient_values[index] -= change
            largest_change = max(largest_change, abs(change))
        if step >= 80 and largest_change < 1e-7:
            break
    coefficients = dict(zip(names, coefficient_values))
    return {
        "feature_names": names, "means": means, "scales": scales,
        "intercept": intercept, "coefficients": coefficients, "l2": l2,
        "training_rows": len(eligible), "baseline_probability_key": baseline_probability_key,
        "optimization_iterations": step + 1,
    }


def predict_probability(model: dict[str, Any], features: dict[str, float],
                        baseline_probability: float | None = None) -> float:
    score = float(model["intercept"])
    if model.get("baseline_probability_key"):
        if baseline_probability is None:
            baseline_probability = 1.0 / (1.0 + 10.0 ** (-float(features.get("elo_diff", 0.0))))
        baseline_probability = min(0.995, max(0.005, float(baseline_probability)))
        score += math.log(baseline_probability / (1.0 - baseline_probability))
    for name in model["feature_names"]:
        value = (float(features.get(name, 0.0)) - float(model["means"][name])) / float(model["scales"][name])
        score += float(model["coefficients"][name]) * value
    return min(0.995, max(0.005, _sigmoid(score)))


def _forecast_metrics(predictions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not predictions:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy": None, "calibration": []}
    losses, briers, hits = [], [], []
    bins: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for item in predictions:
        probability = min(0.999, max(0.001, float(item["probability"])))
        outcome = float(item["outcome"])
        losses.append(-(outcome * math.log(probability) + (1.0 - outcome) * math.log(1.0 - probability)))
        briers.append((probability - outcome) ** 2)
        hits.append(float((probability >= 0.5) == bool(outcome)))
        bins[min(9, int(probability * 10))].append((probability, outcome))
    calibration = [{"range": f"{key * 10}-{(key + 1) * 10}%", "n": len(values),
                    "mean_probability": round(_mean(p for p, _y in values) or 0.0, 4),
                    "observed_rate": round(_mean(y for _p, y in values) or 0.0, 4)}
                   for key, values in sorted(bins.items())]
    return {"n": len(predictions), "brier": round(_mean(briers) or 0.0, 6),
            "log_loss": round(_mean(losses) or 0.0, 6), "accuracy": round(_mean(hits) or 0.0, 6),
            "calibration": calibration}


def _paired_bootstrap(predictions: Sequence[dict[str, Any]], samples: int = 1000) -> dict[str, Any]:
    blocks: dict[tuple[int, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in predictions:
        blocks[tuple(item["block_key"])].append(item)
    keys = list(blocks)
    if len(keys) < 2:
        return {"mean_log_loss_delta_vs_elo": None, "ci95": [None, None], "blocks": len(keys)}
    rng = random.Random(20260729)
    deltas = []
    for _ in range(samples):
        chosen = [rng.choice(keys) for _key in keys]
        model_loss, elo_loss = [], []
        for key in chosen:
            for item in blocks[key]:
                y = float(item["outcome"])
                for bucket, probability in ((model_loss, item["probability"]), (elo_loss, item["elo_probability"])):
                    p = min(0.999, max(0.001, float(probability)))
                    bucket.append(-(y * math.log(p) + (1.0 - y) * math.log(1.0 - p)))
        deltas.append((_mean(model_loss) or 0.0) - (_mean(elo_loss) or 0.0))
    deltas.sort()
    return {"mean_log_loss_delta_vs_elo": round(_mean(deltas) or 0.0, 6),
            "ci95": [round(deltas[int(0.025 * samples)], 6), round(deltas[min(samples - 1, int(0.975 * samples))], 6)],
            "blocks": len(keys)}


def rolling_backtest(rows: Sequence[dict[str, Any]], feature_names: Sequence[str] = FEATURE_NAMES,
                     min_train: int = 96, test_size: int = 32) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible")]
    predictions = []
    cursor = min_train
    while cursor < len(eligible):
        train = eligible[:cursor]
        test = eligible[cursor:cursor + test_size]
        model = fit_logistic(train, feature_names, baseline_probability_key="elo_home_probability")
        base_rate = min(0.99, max(0.01, _mean(row["outcome"] for row in train) or 0.5))
        for row in test:
            predictions.append({
                "game_id": row["game_id"], "block_key": row["block_key"], "outcome": row["outcome"],
                "probability": predict_probability(model, row["features"], row["elo_home_probability"]),
                "elo_probability": row["elo_home_probability"], "base_probability": base_rate,
            })
        cursor += len(test)
    model_metrics = _forecast_metrics(predictions)
    elo_metrics = _forecast_metrics([{**item, "probability": item["elo_probability"]} for item in predictions])
    base_metrics = _forecast_metrics([{**item, "probability": item["base_probability"]} for item in predictions])
    return {"model": model_metrics, "elo": elo_metrics, "league_home_rate": base_metrics,
            "design": {"min_train": min_train, "test_size": test_size, "chronological_expanding_window": True},
            "paired_bootstrap": _paired_bootstrap(predictions), "predictions": predictions}


def ablation_report(rows: Sequence[dict[str, Any]], min_train: int = 96, test_size: int = 32) -> dict[str, Any]:
    full = rolling_backtest(rows, FEATURE_NAMES, min_train, test_size)
    families = {}
    for family, removed in FEATURE_FAMILIES.items():
        retained = [name for name in FEATURE_NAMES if name not in removed]
        result = rolling_backtest(rows, retained, min_train, test_size)
        full_loss = full["model"]["log_loss"]
        without_loss = result["model"]["log_loss"]
        families[family] = {
            "removed_features": removed, "without_log_loss": without_loss,
            "log_loss_increase_without_family": (round(without_loss - full_loss, 6)
                                                  if full_loss is not None and without_loss is not None else None),
            "without_brier": result["model"]["brier"], "n": result["model"]["n"],
        }
    return {"full": {key: value for key, value in full.items() if key != "predictions"}, "families": families}


def feature_contributions(model: dict[str, Any], features: dict[str, float], limit: int = 6) -> list[dict[str, Any]]:
    values = []
    for name in model["feature_names"]:
        standardized = (float(features.get(name, 0.0)) - float(model["means"][name])) / float(model["scales"][name])
        contribution = float(model["coefficients"][name]) * standardized
        values.append({"feature": name, "contribution": round(contribution, 5),
                       "direction": "home" if contribution >= 0 else "away"})
    return sorted(values, key=lambda item: abs(item["contribution"]), reverse=True)[:limit]


def promotion_gate(report: dict[str, Any]) -> dict[str, Any]:
    full = report.get("full") or report
    model = full.get("model") or {}
    elo = full.get("elo") or {}
    interval = (full.get("paired_bootstrap") or {}).get("ci95") or [None, None]
    checks = {
        "log_loss_better_than_elo": (model.get("log_loss") is not None and elo.get("log_loss") is not None and
                                      model["log_loss"] < elo["log_loss"]),
        "brier_not_worse_than_elo": (model.get("brier") is not None and elo.get("brier") is not None and
                                      model["brier"] <= elo["brier"]),
        "paired_ci_excludes_no_improvement": interval[1] is not None and interval[1] < 0,
        "minimum_out_of_sample_games": int(model.get("n") or 0) >= 500,
    }
    passed = all(checks.values())
    return {
        "passed": passed, "checks": checks,
        "decision": "eligible_for_separate_review" if passed else "remain_shadow_only",
        "reason": ("all frozen statistical gates passed; manual compliance and prediction audit still required"
                   if passed else "challenger has not demonstrated stable proper-score improvement over Elo"),
    }


def make_artifact(rows: Sequence[dict[str, Any]], state: dict[str, Any], report: dict[str, Any],
                  source_hashes: dict[str, str]) -> dict[str, Any]:
    model = fit_logistic(rows, FEATURE_NAMES, baseline_probability_key="elo_home_probability")
    gate = promotion_gate(report)
    return {
        "schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sport": "NFL", "source": "nflverse-data pbp release", "license": "CC BY 4.0",
        "research_only": True, "shadow_only": True, "production_weight": 0,
        "promotion_status": gate["decision"], "promotion_gate": gate, "espn_origin_excluded": True,
        "feature_contract": {
            "timing": "prior completed week boundary only", "rolling_games": state["rolling_games"],
            "features": FEATURE_NAMES, "families": FEATURE_FAMILIES,
        },
        "model": model, "state": state, "backtest": report,
        "source_hashes": source_hashes,
    }


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
