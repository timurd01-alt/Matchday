"""Leakage-resistant College Football advanced-metrics challenger research."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from typing import Any, Iterable, Sequence

from advanced_metrics import _mean, _number, cfbd_advanced_game_records
from nfl_challenger import fit_logistic, predict_probability


MODEL_VERSION = "cfbd-advanced-challenger-0.1.0"
HOME_ELO_ADVANTAGE = 55.0
FEATURE_FAMILIES = {
    "ppa": ["ppa_offense_diff", "ppa_defense_edge"],
    "success": ["success_offense_diff", "success_defense_edge"],
    "explosiveness": ["explosiveness_offense_diff", "explosiveness_defense_edge"],
    "opponent_adjustment": [
        "adjusted_ppa_net_diff", "adjusted_success_net_diff",
        "adjusted_explosiveness_net_diff",
    ],
    "talent_prior": ["talent_z_diff", "talent_coverage_mean", "talent_age_years_mean"],
    "context": ["neutral_site", "week_progress", "history_gap"],
}
FEATURE_NAMES = [name for names in FEATURE_FAMILIES.values() for name in names]


def _elo_probability(home: float, away: float, neutral_site: bool) -> float:
    advantage = 0.0 if neutral_site else HOME_ELO_ADVANTAGE
    return 1.0 / (1.0 + 10 ** (-(home + advantage - away) / 400.0))


def _update_elo(elo: dict[str, float], home: str, away: str, outcome: float,
                margin: float, neutral_site: bool) -> None:
    expected = _elo_probability(elo.get(home, 1500.0), elo.get(away, 1500.0), neutral_site)
    multiplier = max(1.0, math.log1p(abs(margin)))
    change = 18.0 * multiplier * (outcome - expected)
    elo[home] = elo.get(home, 1500.0) + change
    elo[away] = elo.get(away, 1500.0) - change


def _team_profiles(history: dict[str, list[dict[str, Any]]], rolling_games: int) -> dict[str, dict[str, float]]:
    recent = {team: games[-rolling_games:] for team, games in history.items() if games}
    fields = ("ppa", "success_rate", "explosiveness")
    profiles: dict[str, dict[str, float]] = {team: {} for team in recent}
    for field in fields:
        allowed = f"{field}_allowed"
        all_games = [game for games in recent.values() for game in games]
        league = _mean(game[field] for game in all_games) or 0.0
        offense = {team: (_mean(game[field] for game in games) or league) - league
                   for team, games in recent.items()}
        defense = {team: league - (_mean(game[allowed] for game in games) or league)
                   for team, games in recent.items()}
        for _ in range(16):
            next_offense, next_defense = {}, {}
            for team, games in recent.items():
                shrink = len(games) / (len(games) + 4.0)
                next_offense[team] = ((_mean(
                    game[field] - league + defense.get(game["opponent"], 0.0)
                    for game in games) or 0.0) * shrink)
                next_defense[team] = ((_mean(
                    league + offense.get(game["opponent"], 0.0) - game[allowed]
                    for game in games) or 0.0) * shrink)
            offense, defense = next_offense, next_defense
        for team, games in recent.items():
            profiles[team][field] = _mean(game[field] for game in games) or league
            profiles[team][allowed] = _mean(game[allowed] for game in games) or league
            profiles[team][f"adjusted_{field}_net"] = offense.get(team, 0.0) + defense.get(team, 0.0)
    return profiles


def _talent_profiles(rows: Iterable[dict[str, Any]], season: int, week: int) -> dict[str, dict[str, float]]:
    candidates: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    for raw in rows:
        team = str(raw.get("team") or "").strip()
        talent_season = int(_number(raw.get("season", raw.get("year")), 0) or 0)
        available_week = int(_number(raw.get("availableWeek", raw.get("available_week")), 0) or 0)
        score = _number(raw.get("talent"), None)
        if (not team or not talent_season or score is None or score <= 0 or talent_season > season
                or talent_season == season and available_week >= week):
            continue
        candidates[team].append((talent_season, available_week, score))
    selected = {team: max(values, key=lambda value: (value[0], value[1]))
                for team, values in candidates.items()}
    scores = [item[2] for item in selected.values()]
    mean = _mean(scores) or 0.0
    variance = _mean((score - mean) ** 2 for score in scores) or 0.0
    scale = math.sqrt(variance) if variance > 1e-12 else 1.0
    return {team: {"z": (value[2] - mean) / scale, "age": float(season - value[0])}
            for team, value in selected.items()}


def _features(home: str, away: str, history: dict[str, list[dict[str, Any]]],
              talent: dict[str, dict[str, float]], week: int, neutral_site: bool,
              rolling_games: int) -> dict[str, float]:
    profiles = _team_profiles(history, rolling_games)
    home_profile, away_profile = profiles.get(home, {}), profiles.get(away, {})
    home_talent, away_talent = talent.get(home), talent.get(away)
    values = {
        "ppa_offense_diff": home_profile.get("ppa", 0.0) - away_profile.get("ppa", 0.0),
        "ppa_defense_edge": away_profile.get("ppa_allowed", 0.0) - home_profile.get("ppa_allowed", 0.0),
        "success_offense_diff": home_profile.get("success_rate", 0.0) - away_profile.get("success_rate", 0.0),
        "success_defense_edge": (away_profile.get("success_rate_allowed", 0.0)
                                 - home_profile.get("success_rate_allowed", 0.0)),
        "explosiveness_offense_diff": (home_profile.get("explosiveness", 0.0)
                                        - away_profile.get("explosiveness", 0.0)),
        "explosiveness_defense_edge": (away_profile.get("explosiveness_allowed", 0.0)
                                        - home_profile.get("explosiveness_allowed", 0.0)),
        "adjusted_ppa_net_diff": (home_profile.get("adjusted_ppa_net", 0.0)
                                  - away_profile.get("adjusted_ppa_net", 0.0)),
        "adjusted_success_net_diff": (home_profile.get("adjusted_success_rate_net", 0.0)
                                      - away_profile.get("adjusted_success_rate_net", 0.0)),
        "adjusted_explosiveness_net_diff": (
            home_profile.get("adjusted_explosiveness_net", 0.0)
            - away_profile.get("adjusted_explosiveness_net", 0.0)),
        "talent_z_diff": (home_talent or {}).get("z", 0.0) - (away_talent or {}).get("z", 0.0),
        "talent_coverage_mean": (float(home_talent is not None) + float(away_talent is not None)) / 2.0,
        "talent_age_years_mean": (((home_talent or {}).get("age", 2.0)
                                   + (away_talent or {}).get("age", 2.0)) / 2.0),
        "neutral_site": float(neutral_site),
        "week_progress": min(1.0, week / 15.0),
        "history_gap": (len(history.get(home, [])) - len(history.get(away, []))) / float(rolling_games),
    }
    return {name: float(values[name]) for name in FEATURE_NAMES}


def build_point_in_time_rows(
    games: Iterable[dict[str, Any]], advanced_rows: Iterable[dict[str, Any]],
    talent_rows: Iterable[dict[str, Any]] = (), min_history: int = 3,
    rolling_games: int = 12, source_hashes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    records = cfbd_advanced_game_records(games, advanced_rows)
    paired: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        paired[(record["season"], record["week"], record["game_id"])].append(record)
    blocks: dict[tuple[int, int], list[list[dict[str, Any]]]] = defaultdict(list)
    for (season, week, _game_id), pair in paired.items():
        if len(pair) == 2 and {item["is_home"] for item in pair} == {True, False}:
            blocks[(season, week)].append(pair)

    talent_rows = list(talent_rows)
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    observed_through: tuple[int, int] | None = None
    current_season = None
    rows = []
    for (season, week) in sorted(blocks):
        if season != current_season:
            if current_season is not None:
                for team in list(elo):
                    elo[team] = 1500.0 + 0.67 * (elo[team] - 1500.0)
            history = defaultdict(list)
            observed_through = None
            current_season = season
        talent = _talent_profiles(talent_rows, season, week)
        for pair in sorted(blocks[(season, week)], key=lambda items: items[0]["game_id"]):
            home = next(item for item in pair if item["is_home"])
            away = next(item for item in pair if not item["is_home"])
            home_team, away_team = home["team"], away["team"]
            home_games, away_games = len(history[home_team]), len(history[away_team])
            features = _features(home_team, away_team, history, talent, week,
                                 home["neutral_site"], rolling_games)
            rows.append({
                "schema_version": 1, "game_id": home["game_id"], "season": season, "week": week,
                "block_id": f"{season}-W{week:02d}", "game_date": home.get("game_date"),
                "home_team": home_team, "away_team": away_team,
                "home_history_games": home_games, "away_history_games": away_games,
                "eligible": home_games >= min_history and away_games >= min_history,
                "features": features,
                "elo_home_probability": _elo_probability(elo[home_team], elo[away_team], home["neutral_site"]),
                "outcome": float(home["points"] > away["points"]),
                "margin": home["points"] - away["points"],
                "feature_observed_through": (f"{observed_through[0]}-W{observed_through[1]:02d}"
                                             if observed_through else None),
                "timestamp_quality": "prior_completed_season_week_boundary",
                "talent_assumption": "season composite available before target week",
                "source_hashes": source_hashes or {},
            })
        # Seal the full week before its games enter any target feature.
        for pair in blocks[(season, week)]:
            home = next(item for item in pair if item["is_home"])
            away = next(item for item in pair if not item["is_home"])
            history[home["team"]].append(home)
            history[away["team"]].append(away)
            _update_elo(elo, home["team"], away["team"], float(home["points"] > away["points"]),
                        home["points"] - away["points"], home["neutral_site"])
        observed_through = (season, week)
    return rows


def _metrics(predictions: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    if not predictions:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    losses, briers, hits = [], [], []
    for item in predictions:
        probability = min(max(float(item[key]), .001), .999)
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
            blocks[row["block_id"]].append(row)
    train, predictions = [], []
    for block_id in sorted(blocks):
        test = blocks[block_id]
        if len(train) >= min_train:
            model = fit_logistic(train, feature_names, baseline_probability_key="elo_home_probability")
            for row in test:
                predictions.append({"game_id": row["game_id"], "block_id": block_id,
                                    "outcome": row["outcome"],
                                    "probability": predict_probability(model, row["features"], row["elo_home_probability"]),
                                    "elo_probability": row["elo_home_probability"]})
        train.extend(test)
    return {"model": _metrics(predictions, "probability"),
            "elo": _metrics(predictions, "elo_probability"), "predictions": predictions}


def _paired(candidate: Sequence[dict[str, Any]], baseline: Sequence[dict[str, Any]] | None = None,
            samples: int = 4000) -> dict[str, Any]:
    baseline_index = ({(item["block_id"], item["game_id"]): item for item in baseline}
                      if baseline is not None else {})
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in candidate:
        outcome = float(item["outcome"])
        first = min(max(float(item["probability"]), .001), .999)
        if baseline is None:
            second = min(max(float(item["elo_probability"]), .001), .999)
        else:
            other = baseline_index.get((item["block_id"], item["game_id"]))
            if not other:
                continue
            second = min(max(float(other["probability"]), .001), .999)
        first_loss = -(outcome*math.log(first)+(1-outcome)*math.log(1-first))
        second_loss = -(outcome*math.log(second)+(1-outcome)*math.log(1-second))
        grouped[item["block_id"]].append(first_loss-second_loss)
    blocks = sorted(grouped)
    values = [value for block in blocks for value in grouped[block]]
    output = {"n": len(values), "blocks": len(blocks),
              "mean_log_loss_difference": round(_mean(values) or 0.0, 6) if values else None,
              "ci95": [None, None], "method": "deterministic season-week block bootstrap"}
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
    for family, names in FEATURE_FAMILIES.items():
        result = rolling_backtest(rows, [name for name in FEATURE_NAMES if name not in names], min_train)
        result["full_vs_without_family"] = _paired(full["predictions"], result["predictions"])
        result.pop("predictions", None)
        families[family] = result
    paired = _paired(full["predictions"])
    gate = {
        "minimum_out_of_sample_games": full["model"]["n"] >= 500,
        "log_loss_better_than_elo": (full["model"]["log_loss"] is not None
                                      and full["model"]["log_loss"] < full["elo"]["log_loss"]),
        "paired_interval_below_zero": paired["ci95"][1] is not None and paired["ci95"][1] < 0,
    }
    passed = all(gate.values())
    return {"schema_version": 1, "model_version": MODEL_VERSION, "research_only": True,
            "production_weight": 0, "full": {"model": full["model"], "elo": full["elo"]},
            "paired_vs_elo": paired, "ablations": families,
            "promotion_gate": {"checks": gate,
                               "decision": "eligible_for_separate_review" if passed else "remain_research_only"}}
