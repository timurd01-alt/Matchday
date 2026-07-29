"""Attach NFL learned-challenger probabilities as non-production shadow data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from advanced_metrics_store import NFL_ALIASES, normalize_team
from nfl_challenger import (
    MODEL_VERSION,
    feature_contributions,
    matchup_features,
    predict_probability,
    quarterback_profile,
    rating_cache,
)


def load_artifact(path: str | Path = "nfl_challenger_model.json") -> dict[str, Any] | None:
    source = Path(path)
    if not source.exists():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("model_version") != MODEL_VERSION:
        raise ValueError(f"unsupported NFL challenger artifact: {source}")
    if payload.get("research_only") is not True or payload.get("shadow_only") is not True:
        raise ValueError(f"NFL challenger must remain research-only: {source}")
    if payload.get("production_weight") != 0:
        raise ValueError(f"NFL challenger production weight must be zero: {source}")
    if "espn" in str(payload.get("source") or "").lower() or payload.get("espn_origin_excluded") is not True:
        raise ValueError(f"NFL challenger source provenance is prohibited or incomplete: {source}")
    return payload


def _code_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for code, name in NFL_ALIASES.items():
        for value in (code, name):
            index.setdefault(normalize_team(value), [])
            if code not in index[normalize_team(value)]:
                index[normalize_team(value)].append(code)
    return index


def _resolve_code(value: Any, index: dict[str, list[str]], history: dict[str, Any]) -> str | None:
    raw = str(value or "").upper()
    if raw in history:
        return raw
    return next((code for code in index.get(normalize_team(value), []) if code in history), None)


def _resolve_team(team: dict[str, Any], index: dict[str, list[str]], history: dict[str, Any]) -> str | None:
    return (_resolve_code(team.get("code"), index, history) or
            _resolve_code(team.get("name"), index, history))


def _kickoff_day(match: dict[str, Any]) -> str:
    text = str(match.get("kickoff") or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return ""


def attach_nfl_challenger_shadows(matches, path: str | Path = "nfl_challenger_model.json") -> dict[str, Any]:
    artifact = load_artifact(path)
    if not artifact:
        return {"file": None, "matches": 0, "skipped": 0}
    state, model = artifact["state"], artifact["model"]
    history = state.get("team_games") or {}
    elo = state.get("elo") or {}
    last_played = state.get("last_played") or {}
    trained_through = str(state.get("trained_through") or "")
    index = _code_index()
    rolling_games = int(state.get("rolling_games") or 16)
    ratings = rating_cache(history, rolling_games)
    attached = skipped = 0
    for match in matches:
        day = _kickoff_day(match)
        # Prevent a season-complete artifact from being attached to an older
        # fixture where it would contain future games relative to kickoff.
        if not day or (trained_through and day <= trained_through) or match.get("status") == "FINISHED":
            skipped += 1
            continue
        home = _resolve_team(match.get("home") or {}, index, history)
        away = _resolve_team(match.get("away") or {}, index, history)
        if not home or not away or home not in history or away not in history:
            skipped += 1
            continue
        features = matchup_features(home, away, history, elo, last_played, day, rolling_games, ratings)
        offseason_days = max((datetime.fromisoformat(day).date() - datetime.fromisoformat(trained_through).date()).days, 0)
        qb_assumptions = {
            "home": quarterback_profile(history, home, rolling_games),
            "away": quarterback_profile(history, away, rolling_games),
        }
        for assumption in qb_assumptions.values():
            observed = assumption.get("last_observed")
            freshness_days = ((datetime.fromisoformat(day).date() - datetime.fromisoformat(observed).date()).days
                              if observed else None)
            assumption["assumption_freshness_days"] = freshness_days
            assumption["availability_confirmed"] = False
            assumption["effective_uncertainty"] = max(
                float(assumption.get("uncertainty") or 0.0), 0.75 if offseason_days > 45 else 0.0
            )
        elo_probability = 1.0 / (1.0 + 10.0 ** (-float(features.get("elo_diff", 0.0))))
        probability = predict_probability(model, features, elo_probability)
        match["nfl_challenger_shadow"] = {
            "schema_version": 1, "model_version": artifact["model_version"],
            "mode": "research_only", "production_weight": 0,
            "home_win_probability": round(probability, 6),
            "away_win_probability": round(1.0 - probability, 6),
            "elo_baseline_home_probability": round(elo_probability, 6),
            "learned_residual_vs_elo": round(probability - elo_probability, 6),
            "features": features, "top_contributions": feature_contributions(model, features),
            "quarterback_assumptions": qb_assumptions,
            "quarterback_basis": "last observed primary QB and prior appearances only; target starter not asserted",
            "trained_through": trained_through,
            "uncertainty_flags": (["offseason_roster_and_qb_changes_not_modeled"] if offseason_days > 45 else []),
            "promotion_status": artifact.get("promotion_status"),
        }
        attached += 1
    return {"file": str(path), "matches": attached, "skipped": skipped}
