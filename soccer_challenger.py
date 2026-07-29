"""Coverage-aware, chronological StatsBomb Open Data soccer challenger."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Sequence

from advanced_metrics import _mean, statsbomb_match_records


MODEL_VERSION = "statsbomb-open-threeway-0.1.0"
CLASSES = ("home", "draw", "away")
FEATURE_FAMILIES = {
    "xg_strength": ["adjusted_xg_net_diff", "xg_for_diff", "xg_defense_edge"],
    "shot_quality": ["npxg_per_shot_diff", "shots_diff", "shot_quality_coverage_mean"],
    "possession_territory": [
        "possession_share_diff", "field_tilt_diff", "pass_completion_diff", "territory_coverage_mean",
    ],
    "pressure": ["pressure_diff"],
    "set_piece": ["set_piece_xg_share_diff"],
    "lineup_history": ["lineup_continuity_diff", "lineup_coverage_mean"],
    "context": ["rest_diff", "history_gap"],
}
FEATURE_NAMES = [name for names in FEATURE_FAMILIES.values() for name in names]


def _poisson_probability(home_lambda: float, away_lambda: float) -> dict[str, float]:
    home_mass = [math.exp(-home_lambda) * home_lambda**goals / math.factorial(goals) for goals in range(11)]
    away_mass = [math.exp(-away_lambda) * away_lambda**goals / math.factorial(goals) for goals in range(11)]
    probabilities = {name: 0.0 for name in CLASSES}
    for home_goals, home_probability in enumerate(home_mass):
        for away_goals, away_probability in enumerate(away_mass):
            key = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"
            probabilities[key] += home_probability * away_probability
    total = sum(probabilities.values()) or 1.0
    return {key: value / total for key, value in probabilities.items()}


def _poisson_baseline(home: str, away: str, history: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    games = [game for team_games in history.values() for game in team_games]
    league_home = _mean(game["goals"] for game in games if game["is_home"]) or 1.4
    league_away = _mean(game["goals"] for game in games if not game["is_home"]) or 1.1
    league = (league_home + league_away) / 2.0

    def rates(team: str) -> tuple[float, float, float]:
        team_games = history.get(team, [])
        shrink = len(team_games) / (len(team_games) + 5.0)
        scored = _mean(game["goals"] for game in team_games) or league
        allowed = _mean(game["opponent_goals"] for game in team_games) or league
        return scored, allowed, shrink

    home_for, home_allowed, home_shrink = rates(home)
    away_for, away_allowed, away_shrink = rates(away)
    home_lambda = league_home + .5 * home_shrink * (home_for - league) + .5 * away_shrink * (away_allowed - league)
    away_lambda = league_away + .5 * away_shrink * (away_for - league) + .5 * home_shrink * (home_allowed - league)
    return _poisson_probability(min(4.0, max(.15, home_lambda)), min(4.0, max(.15, away_lambda)))


def _elo_probabilities(home_rating: float, away_rating: float) -> dict[str, float]:
    difference = home_rating + 65.0 - away_rating
    decisive_home = 1.0 / (1.0 + 10 ** (-difference / 400.0))
    draw = min(.30, max(.12, .27 * math.exp(-abs(difference) / 600.0)))
    return {"home": (1.0 - draw) * decisive_home, "draw": draw,
            "away": (1.0 - draw) * (1.0 - decisive_home)}


def _update_elo(elo: dict[str, float], home: str, away: str, outcome: str, margin: int) -> None:
    expected = 1.0 / (1.0 + 10 ** (-(elo.get(home, 1500.0) + 65.0 - elo.get(away, 1500.0)) / 400.0))
    actual = 1.0 if outcome == "home" else 0.0 if outcome == "away" else .5
    change = 18.0 * max(1.0, math.log1p(abs(margin))) * (actual - expected)
    elo[home] = elo.get(home, 1500.0) + change
    elo[away] = elo.get(away, 1500.0) - change


def _team_profiles(history: dict[str, list[dict[str, Any]]], rolling_matches: int) -> dict[str, dict[str, float]]:
    recent = {team: games[-rolling_matches:] for team, games in history.items() if games}
    all_games = [game for games in recent.values() for game in games]
    league_xg = _mean(game["xg"] for game in all_games) or 1.2
    attack = {team: (_mean(game["xg"] for game in games) or league_xg) - league_xg
              for team, games in recent.items()}
    defense = {team: league_xg - (_mean(game["xg_allowed"] for game in games) or league_xg)
               for team, games in recent.items()}
    for _ in range(16):
        next_attack, next_defense = {}, {}
        for team, games in recent.items():
            shrink = len(games) / (len(games) + 4.0)
            next_attack[team] = ((_mean(game["xg"] - league_xg + defense.get(game["opponent"], 0.0)
                                         for game in games) or 0.0) * shrink)
            next_defense[team] = ((_mean(league_xg + attack.get(game["opponent"], 0.0) - game["xg_allowed"]
                                          for game in games) or 0.0) * shrink)
        attack, defense = next_attack, next_defense

    profiles = {}
    mean_fields = ("xg", "xg_allowed", "shots", "pressures_per_opponent_pass",
                   "possession_sequence_share", "field_tilt", "pass_completion_rate",
                   "set_piece_xg_share", "lineup_continuity")
    league_fields = {field: (_mean(game.get(field) for game in all_games) or 0.0) for field in mean_fields}
    for team, games in recent.items():
        profile = {field: (_mean(game.get(field) for game in games)
                           if _mean(game.get(field) for game in games) is not None else league_fields[field])
                   for field in mean_fields}
        shot_xg = sum(game["npxg"] for game in games)
        shots = sum(game["shots"] for game in games)
        profile["npxg_per_shot"] = shot_xg / shots if shots else 0.0
        profile["adjusted_xg_net"] = attack.get(team, 0.0) + defense.get(team, 0.0)
        profile["shot_quality_coverage"] = sum(game.get("xg_per_shot") is not None for game in games) / len(games)
        profile["territory_coverage"] = sum(
            game.get("possession_sequence_share") is not None and game.get("field_tilt") is not None
            for game in games) / len(games)
        profile["lineup_coverage"] = sum(game.get("lineup_continuity") is not None for game in games) / len(games)
        profiles[team] = profile
    return profiles


def _features(home: str, away: str, history: dict[str, list[dict[str, Any]]],
              last_played: dict[str, str], match_date: str, rolling_matches: int) -> dict[str, float]:
    profiles = _team_profiles(history, rolling_matches)
    hp, ap = profiles.get(home, {}), profiles.get(away, {})
    target = date.fromisoformat(match_date)
    rests = []
    for team in (home, away):
        prior = last_played.get(team)
        rests.append(min(30, max(0, (target - date.fromisoformat(prior)).days)) if prior else 7)
    values = {
        "adjusted_xg_net_diff": hp.get("adjusted_xg_net", 0.0) - ap.get("adjusted_xg_net", 0.0),
        "xg_for_diff": hp.get("xg", 0.0) - ap.get("xg", 0.0),
        "xg_defense_edge": ap.get("xg_allowed", 0.0) - hp.get("xg_allowed", 0.0),
        "npxg_per_shot_diff": hp.get("npxg_per_shot", 0.0) - ap.get("npxg_per_shot", 0.0),
        "shots_diff": (hp.get("shots", 0.0) - ap.get("shots", 0.0)) / 10.0,
        "shot_quality_coverage_mean": (hp.get("shot_quality_coverage", 0.0) + ap.get("shot_quality_coverage", 0.0)) / 2.0,
        "possession_share_diff": hp.get("possession_sequence_share", 0.0) - ap.get("possession_sequence_share", 0.0),
        "field_tilt_diff": hp.get("field_tilt", 0.0) - ap.get("field_tilt", 0.0),
        "pass_completion_diff": hp.get("pass_completion_rate", 0.0) - ap.get("pass_completion_rate", 0.0),
        "territory_coverage_mean": (hp.get("territory_coverage", 0.0) + ap.get("territory_coverage", 0.0)) / 2.0,
        "pressure_diff": hp.get("pressures_per_opponent_pass", 0.0) - ap.get("pressures_per_opponent_pass", 0.0),
        "set_piece_xg_share_diff": hp.get("set_piece_xg_share", 0.0) - ap.get("set_piece_xg_share", 0.0),
        "lineup_continuity_diff": hp.get("lineup_continuity", 0.0) - ap.get("lineup_continuity", 0.0),
        "lineup_coverage_mean": (hp.get("lineup_coverage", 0.0) + ap.get("lineup_coverage", 0.0)) / 2.0,
        "rest_diff": (rests[0] - rests[1]) / 14.0,
        "history_gap": (len(history.get(home, [])) - len(history.get(away, []))) / float(rolling_matches),
    }
    return {name: float(values[name]) for name in FEATURE_NAMES}


def build_point_in_time_rows(
    matches: Iterable[dict[str, Any]], events: Iterable[dict[str, Any]],
    min_history: int = 3, rolling_matches: int = 12,
    source_hashes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    records = statsbomb_match_records(matches, events)
    paired: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        paired[record["match_id"]].append(record)
    by_date: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for pair in paired.values():
        if len(pair) == 2 and {item["is_home"] for item in pair} == {True, False}:
            by_date[pair[0]["match_date"]].append(pair)

    histories: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    last_played: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    last_lineup: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(dict)
    elo: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(lambda: 1500.0))
    rows = []
    for match_date in sorted(by_date):
        for pair in sorted(by_date[match_date], key=lambda items: items[0]["match_id"]):
            home = next(item for item in pair if item["is_home"])
            away = next(item for item in pair if not item["is_home"])
            context = (home["competition_id"], home["season_id"])
            history, played, ratings = histories[context], last_played[context], elo[context]
            home_team, away_team = home["team"], away["team"]
            outcome = "home" if home["goals"] > away["goals"] else "away" if away["goals"] > home["goals"] else "draw"
            rows.append({
                "schema_version": 1, "match_id": home["match_id"], "match_date": match_date,
                "block_id": match_date, "competition_id": home["competition_id"],
                "competition_name": home["competition_name"], "season_id": home["season_id"],
                "season_name": home["season_name"], "home_team": home_team, "away_team": away_team,
                "home_history_matches": len(history[home_team]),
                "away_history_matches": len(history[away_team]),
                "eligible": len(history[home_team]) >= min_history and len(history[away_team]) >= min_history,
                "features": _features(home_team, away_team, history, played, match_date, rolling_matches),
                "poisson_probabilities": _poisson_baseline(home_team, away_team, history),
                "elo_probabilities": _elo_probabilities(ratings[home_team], ratings[away_team]),
                "outcome": outcome, "regulation_score": [home["goals"], away["goals"]],
                "feature_observed_through": max((played.get(home_team), played.get(away_team)),
                                                key=lambda value: value or "") or None,
                "timestamp_quality": "prior_completed_match_date_boundary",
                "event_coverage": {"home_events": home["event_count"], "away_events": away["event_count"],
                                   "home_lineup_players": home["lineup_count"],
                                   "away_lineup_players": away["lineup_count"]},
                "source_hashes": source_hashes or {},
            })
        # No match on this date can influence another match on the same date.
        for pair in by_date[match_date]:
            home = next(item for item in pair if item["is_home"])
            away = next(item for item in pair if not item["is_home"])
            context = (home["competition_id"], home["season_id"])
            history, lineups = histories[context], last_lineup[context]
            for item in (home, away):
                team = item["team"]
                current = set(item.get("lineup") or [])
                prior = lineups.get(team, set())
                stored = dict(item)
                stored["lineup_continuity"] = (len(current & prior) / len(current | prior)
                                                if current and prior else None)
                history[team].append(stored)
                last_played[context][team] = match_date
                if current:
                    lineups[team] = current
            outcome = "home" if home["goals"] > away["goals"] else "away" if away["goals"] > home["goals"] else "draw"
            _update_elo(elo[context], home["team"], away["team"], outcome,
                        home["goals"] - away["goals"])
    return rows


def _softmax(values: Sequence[float]) -> list[float]:
    peak = max(values)
    exp = [math.exp(max(-40.0, min(40.0, value - peak))) for value in values]
    total = sum(exp)
    return [value / total for value in exp]


def fit_multinomial(rows: Sequence[dict[str, Any]], feature_names: Sequence[str],
                    l2: float = 5.0, iterations: int = 350, learning_rate: float = .10) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible") and row.get("outcome") in CLASSES]
    if len(eligible) < 2:
        raise ValueError("at least two eligible soccer rows are required")
    names = list(feature_names)
    means, scales = {}, {}
    for name in names:
        values = [float(row["features"].get(name, 0.0)) for row in eligible]
        means[name] = sum(values) / len(values)
        variance = sum((value - means[name]) ** 2 for value in values) / len(values)
        scales[name] = math.sqrt(variance) if variance > 1e-12 else 1.0
    matrix = [[(float(row["features"].get(name, 0.0)) - means[name]) / scales[name] for name in names]
              for row in eligible]
    weights = [[0.0] * len(names) for _ in CLASSES]
    intercepts = [0.0] * len(CLASSES)
    for step in range(iterations):
        grad_w = [[0.0] * len(names) for _ in CLASSES]
        grad_i = [0.0] * len(CLASSES)
        for row, vector in zip(eligible, matrix):
            logits = [math.log(max(.001, row["poisson_probabilities"][label])) + intercepts[index]
                      + sum(weight * value for weight, value in zip(weights[index], vector))
                      for index, label in enumerate(CLASSES)]
            probabilities = _softmax(logits)
            for index, label in enumerate(CLASSES):
                error = probabilities[index] - float(row["outcome"] == label)
                grad_i[index] += error
                for feature_index, value in enumerate(vector):
                    grad_w[index][feature_index] += error * value
        rate = learning_rate / math.sqrt(1.0 + step / 100.0)
        count = float(len(eligible))
        for index in range(len(CLASSES)):
            intercepts[index] -= rate * grad_i[index] / count
            for feature_index in range(len(names)):
                weights[index][feature_index] -= rate * (
                    grad_w[index][feature_index] / count + l2 * weights[index][feature_index] / count)
    return {"feature_names": names, "means": means, "scales": scales,
            "intercepts": dict(zip(CLASSES, intercepts)),
            "coefficients": {label: dict(zip(names, weights[index])) for index, label in enumerate(CLASSES)},
            "training_rows": len(eligible), "l2": l2, "optimization_iterations": iterations}


def predict_probabilities(model: dict[str, Any], features: dict[str, float],
                          baseline: dict[str, float]) -> dict[str, float]:
    logits = []
    for label in CLASSES:
        score = math.log(max(.001, baseline[label])) + float(model["intercepts"][label])
        for name in model["feature_names"]:
            standardized = ((float(features.get(name, 0.0)) - float(model["means"][name]))
                            / float(model["scales"][name]))
            score += float(model["coefficients"][label][name]) * standardized
        logits.append(score)
    probabilities = _softmax(logits)
    return dict(zip(CLASSES, probabilities))


def _metrics(predictions: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    if not predictions:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    losses, briers, hits = [], [], []
    for item in predictions:
        probabilities = item[key]
        outcome = item["outcome"]
        losses.append(-math.log(min(.999, max(.001, probabilities[outcome]))))
        briers.append(sum((probabilities[label] - float(label == outcome)) ** 2 for label in CLASSES))
        hits.append(float(max(CLASSES, key=lambda label: probabilities[label]) == outcome))
    return {"n": len(predictions), "log_loss": round(_mean(losses) or 0.0, 6),
            "brier": round(_mean(briers) or 0.0, 6), "accuracy": round(_mean(hits) or 0.0, 6)}


def rolling_backtest(rows: Sequence[dict[str, Any]], feature_names: Sequence[str] = FEATURE_NAMES,
                     min_train: int = 100) -> dict[str, Any]:
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("eligible"):
            blocks[row["block_id"]].append(row)
    train, predictions = [], []
    for block_id in sorted(blocks):
        test = blocks[block_id]
        if len(train) >= min_train:
            model = fit_multinomial(train, feature_names)
            for row in test:
                predictions.append({"match_id": row["match_id"], "block_id": block_id,
                                    "outcome": row["outcome"],
                                    "probabilities": predict_probabilities(
                                        model, row["features"], row["poisson_probabilities"]),
                                    "poisson_probabilities": row["poisson_probabilities"],
                                    "elo_probabilities": row["elo_probabilities"]})
        train.extend(test)
    return {"model": _metrics(predictions, "probabilities"),
            "poisson": _metrics(predictions, "poisson_probabilities"),
            "elo": _metrics(predictions, "elo_probabilities"), "predictions": predictions}


def _paired(candidate: Sequence[dict[str, Any]], baseline_key: str | None = None,
            other: Sequence[dict[str, Any]] | None = None, samples: int = 4000) -> dict[str, Any]:
    other_index = ({(item["block_id"], item["match_id"]): item for item in other} if other is not None else {})
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in candidate:
        outcome = item["outcome"]
        first = item["probabilities"][outcome]
        if other is not None:
            match = other_index.get((item["block_id"], item["match_id"]))
            if not match:
                continue
            second = match["probabilities"][outcome]
        else:
            second = item[baseline_key or "poisson_probabilities"][outcome]
        grouped[item["block_id"]].append(-math.log(max(.001, first)) + math.log(max(.001, second)))
    blocks = sorted(grouped)
    values = [value for block in blocks for value in grouped[block]]
    output = {"n": len(values), "blocks": len(blocks),
              "mean_log_loss_difference": round(_mean(values) or 0.0, 6) if values else None,
              "ci95": [None, None], "method": "deterministic match-date block bootstrap"}
    if len(blocks) < 2:
        return output
    seed = int(hashlib.sha256("|".join(blocks).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        draw = [value for block in (rng.choice(blocks) for _ in blocks) for value in grouped[block]]
        estimates.append(sum(draw) / len(draw))
    estimates.sort()
    output["ci95"] = [round(estimates[int(samples*.025)], 6),
                      round(estimates[min(int(samples*.975), samples-1)], 6)]
    return output


def ablation_report(rows: Sequence[dict[str, Any]], min_train: int = 100) -> dict[str, Any]:
    full = rolling_backtest(rows, FEATURE_NAMES, min_train)
    families = {}
    for family, removed in FEATURE_FAMILIES.items():
        result = rolling_backtest(rows, [name for name in FEATURE_NAMES if name not in removed], min_train)
        result["full_vs_without_family"] = _paired(full["predictions"], other=result["predictions"])
        result.pop("predictions", None)
        families[family] = result
    paired_poisson = _paired(full["predictions"], "poisson_probabilities")
    paired_elo = _paired(full["predictions"], "elo_probabilities")
    gate = {
        "minimum_out_of_sample_matches": full["model"]["n"] >= 500,
        "log_loss_better_than_poisson": (full["model"]["log_loss"] is not None
                                           and full["model"]["log_loss"] < full["poisson"]["log_loss"]),
        "log_loss_better_than_elo": (full["model"]["log_loss"] is not None
                                      and full["model"]["log_loss"] < full["elo"]["log_loss"]),
        "paired_poisson_interval_below_zero": (paired_poisson["ci95"][1] is not None
                                                and paired_poisson["ci95"][1] < 0),
    }
    contexts = sorted({(row["competition_id"], row["season_id"]) for row in rows})
    return {"schema_version": 1, "model_version": MODEL_VERSION, "research_only": True,
            "production_weight": 0,
            "coverage": {"complete_matches": len(rows),
                         "eligible_matches": sum(bool(row.get("eligible")) for row in rows),
                         "competition_seasons": [{"competition_id": item[0], "season_id": item[1]}
                                                 for item in contexts]},
            "full": {"model": full["model"], "poisson": full["poisson"], "elo": full["elo"]},
            "paired_vs_poisson": paired_poisson, "paired_vs_elo": paired_elo,
            "ablations": families,
            "promotion_gate": {"checks": gate,
                               "decision": "eligible_for_separate_review" if all(gate.values())
                               else "remain_research_only"}}
