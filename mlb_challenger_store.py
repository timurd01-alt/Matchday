"""Attach the validated MLB run-strength challenger as a zero-weight shadow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb_challenger import MODEL_VERSION
from nfl_challenger import feature_contributions, predict_probability


def load_artifact(path: str | Path = "mlb_run_strength_model_v1.json") -> dict[str, Any] | None:
    source = Path(path)
    if not source.exists():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("model_version") != MODEL_VERSION:
        raise ValueError(f"unsupported MLB challenger artifact: {source}")
    if payload.get("research_only") is not True or payload.get("shadow_only") is not True:
        raise ValueError(f"MLB challenger must remain research-only: {source}")
    if payload.get("production_weight") != 0:
        raise ValueError(f"MLB challenger production weight must be zero: {source}")
    notice = str(((payload.get("source") or {}).get("notice")) or "")
    if "copyrighted by Retrosheet" not in notice:
        raise ValueError(f"MLB challenger is missing required Retrosheet attribution: {source}")
    candidate = payload.get("historical_validation") or {}
    if candidate.get("decision") != "eligible_for_prospective_shadow":
        raise ValueError(f"MLB challenger did not clear its historical shadow gate: {source}")
    return payload


def _profile(team: dict[str, Any]) -> dict[str, float] | None:
    try:
        games = int(team.get("pld") or 0)
        runs = float(team.get("gf"))
        allowed = float(team.get("ga"))
    except (TypeError, ValueError):
        return None
    if games < 10 or runs < 0 or allowed < 0:
        return None
    denominator = runs ** 1.83 + allowed ** 1.83
    return {"games": games,
            "pythagorean": runs ** 1.83 / denominator if denominator else .5,
            "run_diff_per_game": (runs - allowed) / games}


def attach_mlb_challenger_shadows(matches, path: str | Path = "mlb_run_strength_model_v1.json") -> dict[str, Any]:
    artifact = load_artifact(path)
    if not artifact:
        return {"file": None, "matches": 0, "skipped": 0}
    attached = skipped = 0
    for match in matches:
        if str(match.get("status") or "").upper() in {"FINISHED", "CANCELLED", "POSTPONED"}:
            skipped += 1
            continue
        home, away = _profile(match.get("home") or {}), _profile(match.get("away") or {})
        if not home or not away:
            skipped += 1
            continue
        features = {
            "pythagorean_diff": home["pythagorean"] - away["pythagorean"],
            "run_diff_per_game_diff": home["run_diff_per_game"] - away["run_diff_per_game"],
        }
        probability = predict_probability(artifact["model"], features)
        match["mlb_challenger_shadow"] = {
            "schema_version": 1, "model_version": artifact["model_version"],
            "mode": "prospective_shadow", "production_weight": 0,
            "home_win_probability": round(probability, 6),
            "away_win_probability": round(1.0 - probability, 6),
            "features": {name: round(value, 6) for name, value in features.items()},
            "top_contributions": feature_contributions(artifact["model"], features),
            "live_feature_source": "licensed BALLDONTLIE season team totals through prior completed games",
            "historical_training_source": "Retrosheet event files and game logs",
            "retrosheet_notice": artifact["source"]["notice"],
            "trained_through": artifact.get("trained_through"),
            "home_games": home["games"], "away_games": away["games"],
            "historical_validation": artifact.get("historical_validation"),
            "promotion_status": artifact.get("promotion_status"),
            "missing_personnel": ["probable_or_confirmed_starter", "confirmed_lineup", "bullpen_availability"],
        }
        attached += 1
    return {"file": str(path), "matches": attached, "skipped": skipped}
