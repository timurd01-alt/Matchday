"""Chronological basketball box-score challenger research."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Sequence

from advanced_metrics import _mean, basketball_game_records
from nfl_challenger import fit_logistic, predict_probability


MODEL_VERSION = "basketball-boxscore-challenger-0.1.0"
HOME_ELO_ADVANTAGE = 70.0
FEATURE_FAMILIES = {
    "adjusted_efficiency": ["adjusted_net_diff"],
    "shooting": ["efg_diff", "three_point_attempt_rate_diff", "three_point_attempt_coverage_mean"],
    "possession": ["tov_edge", "orb_rate_diff", "ft_rate_diff"],
    "tempo": ["tempo_mean", "tempo_diff"],
    "context": ["rest_diff", "history_gap"],
}
FEATURE_NAMES = [name for names in FEATURE_FAMILIES.values() for name in names]


def _elo_probability(home: float, away: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(home + HOME_ELO_ADVANTAGE - away) / 400.0))


def _update_elo(elo: dict[str, float], home: str, away: str, outcome: float, margin: float) -> None:
    expected = _elo_probability(elo.get(home, 1500.0), elo.get(away, 1500.0))
    multiplier = max(1.0, math.log1p(abs(margin)))
    change = 18.0 * multiplier * (outcome - expected)
    elo[home] = elo.get(home, 1500.0) + change
    elo[away] = elo.get(away, 1500.0) - change


def _team_profiles(history: dict[str, list[dict[str, Any]]], rolling_games: int) -> dict[str, dict[str, float]]:
    recent = {team: games[-rolling_games:] for team, games in history.items() if games}
    all_games = [game for games in recent.values() for game in games]
    league = _mean(game["off_rating"] for game in all_games) or 100.0
    profile_fields = ("possessions", "efg", "tov_rate", "orb_rate", "ft_rate",
                      "three_point_attempt_rate")
    league_fields = {field: (_mean(game.get(field) for game in all_games) or 0.0)
                     for field in profile_fields}
    offense = {team: (_mean(game["off_rating"] for game in games) or league) - league
               for team, games in recent.items()}
    defense = {team: league - (_mean(game["def_rating"] for game in games) or league)
               for team, games in recent.items()}
    for _ in range(16):
        next_offense, next_defense = {}, {}
        for team, games in recent.items():
            shrink = len(games) / (len(games) + 5.0)
            next_offense[team] = ((_mean(game["off_rating"] - league
                                          + defense.get(game["opponent"], 0.0) for game in games) or 0.0)
                                  * shrink)
            next_defense[team] = ((_mean(league - game["def_rating"]
                                          + offense.get(game["opponent"], 0.0) for game in games) or 0.0)
                                  * shrink)
        offense, defense = next_offense, next_defense
    profiles = {}
    for team, games in recent.items():
        profiles[team] = {}
        for field in profile_fields:
            observed = _mean(game.get(field) for game in games)
            profiles[team][field] = observed if observed is not None else league_fields[field]
        profiles[team]["three_point_attempt_coverage"] = (
            sum(game.get("three_point_attempt_rate") is not None for game in games) / len(games))
        profiles[team]["adjusted_net"] = offense.get(team, 0.0) + defense.get(team, 0.0)
    return profiles


def _features(home: str, away: str, history: dict[str, list[dict[str, Any]]],
              last_played: dict[str, str], target_day: str, rolling_games: int) -> dict[str, float]:
    profiles = _team_profiles(history, rolling_games)
    home_profile, away_profile = profiles.get(home, {}), profiles.get(away, {})
    home_tempo, away_tempo = home_profile.get("possessions", 0.0), away_profile.get("possessions", 0.0)
    target = date.fromisoformat(target_day)
    rests = []
    for team in (home, away):
        prior = last_played.get(team)
        rests.append(min(14, max(0, (target - date.fromisoformat(prior)).days)) if prior else 7)
    values = {
        "adjusted_net_diff": (home_profile.get("adjusted_net", 0.0)
                              - away_profile.get("adjusted_net", 0.0)) / 10.0,
        "efg_diff": home_profile.get("efg", 0.0) - away_profile.get("efg", 0.0),
        "three_point_attempt_rate_diff": (home_profile.get("three_point_attempt_rate", 0.0)
                                           - away_profile.get("three_point_attempt_rate", 0.0)),
        "three_point_attempt_coverage_mean": (
            home_profile.get("three_point_attempt_coverage", 0.0)
            + away_profile.get("three_point_attempt_coverage", 0.0)) / 2.0,
        "tov_edge": away_profile.get("tov_rate", 0.0) - home_profile.get("tov_rate", 0.0),
        "orb_rate_diff": home_profile.get("orb_rate", 0.0) - away_profile.get("orb_rate", 0.0),
        "ft_rate_diff": home_profile.get("ft_rate", 0.0) - away_profile.get("ft_rate", 0.0),
        "tempo_mean": ((home_tempo + away_tempo) / 2.0 - 70.0) / 10.0,
        "tempo_diff": (home_tempo - away_tempo) / 10.0,
        "rest_diff": (rests[0] - rests[1]) / 7.0,
        "history_gap": (len(history.get(home, [])) - len(history.get(away, []))) / float(rolling_games),
    }
    return {name: float(values.get(name, 0.0)) for name in FEATURE_NAMES}


def build_point_in_time_rows(
    boxes: Iterable[dict[str, Any]], min_history: int = 5, rolling_games: int = 20
) -> list[dict[str, Any]]:
    records = basketball_game_records(boxes)
    games: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        try:
            date.fromisoformat(str(record.get("game_date") or ""))
        except ValueError:
            continue
        if record.get("game_date"):
            games[(record["game_date"], record["game_id"])].append(record)
    by_day: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for (game_day, _game_id), pair in games.items():
        if (len(pair) == 2 and {item.get("is_home") for item in pair} == {True, False}
                and pair[0]["points"] != pair[1]["points"]):
            by_day[game_day].append(pair)
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    last_played: dict[str, str] = {}
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    rows = []
    for game_day in sorted(by_day):
        for pair in sorted(by_day[game_day], key=lambda items: items[0]["game_id"]):
            home = next(item for item in pair if item["is_home"])
            away = next(item for item in pair if not item["is_home"])
            home_team, away_team = home["team"], away["team"]
            home_games, away_games = len(history[home_team]), len(history[away_team])
            rows.append({"game_id": home["game_id"], "game_date": game_day,
                         "home_team": home_team, "away_team": away_team,
                         "home_history_games": home_games, "away_history_games": away_games,
                         "eligible": home_games >= min_history and away_games >= min_history,
                         "features": _features(home_team, away_team, history, last_played,
                                               game_day, rolling_games),
                         "elo_home_probability": _elo_probability(elo[home_team], elo[away_team]),
                         "outcome": float(home["points"] > away["points"]),
                         "margin": home["points"] - away["points"],
                         "feature_observed_through": max(
                             (last_played.get(home_team), last_played.get(away_team)),
                             key=lambda value: value or "") or None})
        # Seal the date block before any game from it enters another target's features.
        for pair in by_day[game_day]:
            home = next(item for item in pair if item["is_home"])
            away = next(item for item in pair if not item["is_home"])
            for item in pair:
                history[item["team"]].append(item)
                last_played[item["team"]] = game_day
            _update_elo(elo, home["team"], away["team"], float(home["points"] > away["points"]),
                        home["points"] - away["points"])
    return rows


def _metrics(predictions: Sequence[dict[str, Any]], probability_key: str) -> dict[str, Any]:
    if not predictions:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    losses = []; briers = []; hits = []
    for item in predictions:
        probability = min(max(float(item[probability_key]), .001), .999)
        outcome = float(item["outcome"])
        losses.append(-(outcome * math.log(probability) + (1-outcome) * math.log(1-probability)))
        briers.append((probability-outcome) ** 2)
        hits.append(float((probability >= .5) == bool(outcome)))
    return {"n": len(predictions), "log_loss": round(_mean(losses) or 0.0, 6),
            "brier": round(_mean(briers) or 0.0, 6), "accuracy": round(_mean(hits) or 0.0, 6)}


def rolling_backtest(rows: Sequence[dict[str, Any]], feature_names: Sequence[str] = FEATURE_NAMES,
                     min_train: int = 100) -> dict[str, Any]:
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("eligible"):
            blocks[row["game_date"]].append(row)
    train = []
    predictions = []
    for game_day in sorted(blocks):
        test = blocks[game_day]
        if len(train) >= min_train:
            model = fit_logistic(train, feature_names, baseline_probability_key="elo_home_probability")
            for row in test:
                predictions.append({"game_id": row["game_id"], "game_date": game_day,
                                    "outcome": row["outcome"],
                                    "probability": predict_probability(model, row["features"],
                                                                       row["elo_home_probability"]),
                                    "elo_probability": row["elo_home_probability"]})
        train.extend(test)
    return {"model": _metrics(predictions, "probability"),
            "elo": _metrics(predictions, "elo_probability"), "predictions": predictions}


def _paired_interval(predictions: Sequence[dict[str, Any]], samples: int = 4000) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in predictions:
        outcome = float(item["outcome"])
        model = min(max(float(item["probability"]), .001), .999)
        elo = min(max(float(item["elo_probability"]), .001), .999)
        model_loss = -(outcome*math.log(model)+(1-outcome)*math.log(1-model))
        elo_loss = -(outcome*math.log(elo)+(1-outcome)*math.log(1-elo))
        grouped[item["game_date"]].append(model_loss-elo_loss)
    blocks = sorted(grouped); values = [value for block in blocks for value in grouped[block]]
    output = {"n": len(values), "blocks": len(blocks),
              "mean_model_minus_elo_log_loss": round(_mean(values) or 0.0, 6) if values else None,
              "ci95": [None, None], "method": "deterministic game-date block bootstrap"}
    if len(blocks) < 2:
        return output
    seed = int(hashlib.sha256("|".join(blocks).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed); estimates = []
    for _ in range(samples):
        chosen = [rng.choice(blocks) for _ in blocks]
        draw = [value for block in chosen for value in grouped[block]]
        estimates.append(sum(draw)/len(draw))
    estimates.sort()
    output["ci95"] = [round(estimates[int(samples*.025)], 6),
                      round(estimates[min(int(samples*.975), samples-1)], 6)]
    return output


def _paired_models(candidate: Sequence[dict[str, Any]], baseline: Sequence[dict[str, Any]],
                   samples: int = 4000) -> dict[str, Any]:
    baseline_index = {(item["game_date"], item["game_id"]): item for item in baseline}
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in candidate:
        other = baseline_index.get((item["game_date"], item["game_id"]))
        if not other:
            continue
        outcome = float(item["outcome"])
        first = min(max(float(item["probability"]), .001), .999)
        second = min(max(float(other["probability"]), .001), .999)
        first_loss = -(outcome*math.log(first)+(1-outcome)*math.log(1-first))
        second_loss = -(outcome*math.log(second)+(1-outcome)*math.log(1-second))
        grouped[item["game_date"]].append(first_loss-second_loss)
    blocks = sorted(grouped); values = [value for block in blocks for value in grouped[block]]
    output = {"n": len(values), "blocks": len(blocks),
              "mean_full_minus_without_family_log_loss": round(_mean(values) or 0.0, 6) if values else None,
              "ci95": [None, None], "method": "deterministic game-date block bootstrap"}
    if len(blocks) < 2:
        return output
    seed = int(hashlib.sha256(("ablation|" + "|".join(blocks)).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed); estimates = []
    for _ in range(samples):
        chosen = [rng.choice(blocks) for _ in blocks]
        draw = [value for block in chosen for value in grouped[block]]
        estimates.append(sum(draw)/len(draw))
    estimates.sort()
    output["ci95"] = [round(estimates[int(samples*.025)], 6),
                      round(estimates[min(int(samples*.975), samples-1)], 6)]
    return output


def ablation_report(rows: Sequence[dict[str, Any]], min_train: int = 100) -> dict[str, Any]:
    full = rolling_backtest(rows, FEATURE_NAMES, min_train)
    families = {}
    for family, names in FEATURE_FAMILIES.items():
        kept = [name for name in FEATURE_NAMES if name not in names]
        families[family] = rolling_backtest(rows, kept, min_train)
        families[family]["full_vs_without_family"] = _paired_models(
            full["predictions"], families[family]["predictions"])
        families[family].pop("predictions", None)
    paired = _paired_interval(full["predictions"])
    gate = {"minimum_out_of_sample_games": full["model"]["n"] >= 500,
            "log_loss_better_than_elo": (full["model"]["log_loss"] is not None
                                          and full["model"]["log_loss"] < full["elo"]["log_loss"]),
            "paired_interval_below_zero": paired["ci95"][1] is not None and paired["ci95"][1] < 0}
    passed = all(gate.values())
    return {"schema_version": 1, "model_version": MODEL_VERSION,
            "research_only": True, "production_weight": 0,
            "full": {"model": full["model"], "elo": full["elo"]},
            "paired_vs_elo": paired, "ablations": families,
            "promotion_gate": {"checks": gate,
                               "decision": "eligible_for_separate_review" if passed else "remain_research_only"}}
