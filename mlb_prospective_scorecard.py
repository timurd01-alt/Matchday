"""Grade frozen MLB challenger forecasts from Matchday's append-only ledger."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import forecast_ledger


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "mlb-prospective-shadow-1.0.0"
MIN_GAMES = 500
MIN_DATE_BLOCKS = 30


def _number(value: Any, *, percent: bool = False) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if percent:
        result /= 100.0
    return result if math.isfinite(result) and 0.0 < result < 1.0 else None


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _date_block(value: Any) -> str:
    parsed = _parse_time(value)
    return parsed.date().isoformat() if parsed else "unknown"


def _log_loss(probability: float, outcome: int) -> float:
    probability = min(max(probability, 1e-12), 1.0 - 1e-12)
    return -(outcome * math.log(probability) + (1 - outcome) * math.log(1.0 - probability))


def _score_result(payload: dict[str, Any]) -> str | None:
    score = payload.get("score")
    if isinstance(score, dict):
        home, away = score.get("home"), score.get("away")
    else:
        text = str(score or "").split("(", 1)[0].strip()
        try:
            home, away = text.split("-", 1)
        except ValueError:
            return None
    try:
        home_value, away_value = float(home), float(away)
    except (TypeError, ValueError):
        return None
    return "h" if home_value > away_value else "a" if away_value > home_value else "d"


def _capped_blend(official: float, challenger: float, weight: float = .10,
                  cap_points: float = 3.0) -> float:
    """Reproduce the deployable float-preserving cap and no-flip policy."""
    official_points = official * 100.0
    raw_shift = weight * (challenger * 100.0 - official_points)
    lower, upper = max(1.0, official_points - cap_points), min(99.0, official_points + cap_points)
    promoted = max(lower, min(upper, official_points + raw_shift))
    promoted = (max(50.0, promoted) if official_points >= 50.0
                else min(math.nextafter(50.0, -math.inf), promoted))
    return max(lower, min(upper, promoted)) / 100.0


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy": None, "calibration": []}
    brier = log_loss = hits = 0.0
    bands: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        probability = float(row[key])
        outcome = int(row["home_win"])
        brier += (probability - outcome) ** 2
        log_loss += _log_loss(probability, outcome)
        hits += int((probability >= 0.5) == bool(outcome))
        bands[min(int(probability * 10), 9)].append(row)
    calibration = [{
        "range": f"{band * 10}-{(band + 1) * 10}%", "n": len(values),
        "mean_probability": round(sum(float(row[key]) for row in values) / len(values), 6),
        "home_win_rate": round(sum(int(row["home_win"]) for row in values) / len(values), 6),
    } for band, values in sorted(bands.items())]
    count = len(rows)
    return {"n": count, "brier": round(brier / count, 6),
            "log_loss": round(log_loss / count, 6), "accuracy": round(hits / count, 6),
            "calibration": calibration}


def _rows_with_probability(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [row for row in rows if _number(row.get(key)) is not None]


def _paired_block_interval(
    rows: list[dict[str, Any]], candidate_key: str, baseline_key: str, samples: int = 4000
) -> dict[str, Any]:
    """Deterministic game-date bootstrap of candidate minus baseline log loss."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["date_block"]].append(
            _log_loss(float(row[candidate_key]), int(row["home_win"]))
            - _log_loss(float(row[baseline_key]), int(row["home_win"]))
        )
    blocks = sorted(grouped)
    deltas = [value for block in blocks for value in grouped[block]]
    result = {"n": len(deltas), "blocks": len(blocks),
              "mean_log_loss_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
              "ci95": [None, None], "method": "deterministic game-date block bootstrap"}
    if len(blocks) < 2:
        return result
    seed_material = "|".join(
        f"{row['fixture_id']}:{row[candidate_key]}:{row[baseline_key]}:{row['home_win']}"
        for row in sorted(rows, key=lambda item: (item["fixture_id"], item["lock_event_id"]))
    )
    rng = random.Random(int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16))
    estimates = []
    for _ in range(samples):
        draw = [rng.choice(blocks) for _ in blocks]
        values = [delta for block in draw for delta in grouped[block]]
        estimates.append(sum(values) / len(values))
    estimates.sort()
    result["ci95"] = [round(estimates[int(samples * 0.025)], 6),
                      round(estimates[min(int(samples * 0.975), samples - 1)], 6)]
    return result


def extract_rows(events: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    locks: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    legacy_grades: dict[str, dict[str, Any]] = {}
    shadow_grades: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        fixture_id = str(event.get("fixture_id") or "")
        if not fixture_id:
            continue
        if event.get("event_type") == "forecast_locked":
            locks[(fixture_id, "legacy")].append(event)
        elif event.get("event_type") == "forecast_graded":
            legacy_grades[fixture_id] = event
        elif event.get("event_type") == "mlb_shadow_locked":
            candidate = (event.get("payload") or {}).get("candidate") or {}
            locks[(fixture_id, str(candidate.get("model_version") or "missing"))].append(event)
        elif event.get("event_type") == "mlb_shadow_graded":
            lock_event_id = str(((event.get("payload") or {}).get("lock_event_id")) or "")
            if lock_event_id:
                shadow_grades[lock_event_id] = event

    rows = []
    for (fixture_id, cohort_model), fixture_locks in sorted(locks.items()):
        if len(fixture_locks) != 1:
            counts["ambiguous_locks"] += 1
            continue
        lock = fixture_locks[0]
        is_shadow = lock.get("event_type") == "mlb_shadow_locked"
        grade = (shadow_grades.get(str(lock.get("event_id") or "")) if is_shadow
                 else legacy_grades.get(fixture_id))
        if not grade:
            counts["pending"] += 1
            continue
        lock_payload = lock.get("payload") or {}
        grade_payload = grade.get("payload") or {}
        if str(grade.get("fixture_id") or "") != fixture_id:
            counts["invalid_grade_fixture_identity"] += 1
            continue
        if is_shadow and str(grade_payload.get("lock_event_id") or "") != str(lock.get("event_id") or ""):
            counts["invalid_grade_fixture_identity"] += 1
            continue
        result = grade_payload.get("result")
        if result == "d":
            counts["ties_excluded"] += 1
            continue
        if result not in {"h", "a"}:
            counts["invalid_result"] += 1
            continue
        lock_time = _parse_time(lock.get("effective_at"))
        kickoff_text = (lock_payload.get("lock") or {}).get("kickoff")
        kickoff = _parse_time(kickoff_text)
        if not lock_time or not kickoff or lock_time >= kickoff:
            counts["invalid_lock_time"] += 1
            continue
        grade_time = _parse_time(grade.get("effective_at"))
        if not grade_time or grade_time < kickoff:
            counts["invalid_grade_time"] += 1
            continue
        if _score_result(grade_payload) != result:
            counts["score_result_mismatch"] += 1
            continue
        if is_shadow:
            grade_identity = grade_payload.get("fixture_identity") or {}
            if (str(grade_identity.get("fixture_id") or "") != fixture_id
                    or _parse_time(grade_identity.get("kickoff")) != kickoff
                    or (grade_identity.get("participants") or {}) != (lock_payload.get("participants") or {})):
                counts["invalid_grade_fixture_identity"] += 1
                continue
        shadow = ((lock_payload.get("candidate") or {}) if is_shadow else
                  ((lock_payload.get("features") or {}).get("mlb_challenger_shadow") or {}))
        if shadow.get("production_weight") != 0 or shadow.get("mode") != "prospective_shadow":
            counts["not_frozen_shadow"] += 1
            continue
        challenger = _number(shadow.get("home_win_probability"))
        official = (_number(((lock_payload.get("baseline") or {}).get("home_win_probability"))
                            if is_shadow else
                            ((lock_payload.get("model") or {}).get("regulation_probabilities") or {}).get("h"),
                            percent=not is_shadow))
        if challenger is None or official is None:
            counts["missing_probability"] += 1
            continue
        row = {
            "fixture_id": fixture_id, "lock_event_id": lock.get("event_id"),
            "grade_event_id": grade.get("event_id"), "locked_at": lock.get("effective_at"),
            "kickoff": kickoff_text, "date_block": _date_block(kickoff_text),
            "model_version": shadow.get("model_version"), "trained_through": shadow.get("trained_through"),
            "baseline_model_version": ((lock_payload.get("baseline") or {}).get("model_version")
                                       if is_shadow else
                                       (lock_payload.get("model") or {}).get("version")),
            "baseline_model_signal_schema": (
                (lock_payload.get("baseline") or {}).get("model_signal_schema") if is_shadow else
                (lock_payload.get("provenance") or {}).get("model_signal_schema")),
            "home_win": int(result == "h"), "challenger_home_probability": challenger,
            "official_home_probability": official,
            "capped_blend_home_probability": _capped_blend(official, challenger),
            "missing_personnel": ((lock_payload.get("personnel_missingness") or []) if is_shadow
                                  else shadow.get("missing_personnel") or []),
        }
        if is_shadow:
            row.update({
                "league_home_prior_probability": _number(
                    (lock_payload.get("league_home_prior") or {}).get("home_win_probability")),
                "independent_official_home_probability": _number(
                    (lock_payload.get("independent_official") or {}).get("home_win_probability")),
                "market_home_probability": _number(
                    (lock_payload.get("market") or {}).get("home_win_probability")),
                "market_missing_reason": (lock_payload.get("market") or {}).get("missing_reason"),
                "artifact_sha256": shadow.get("artifact_sha256"),
                "feature_schema_version": shadow.get("feature_schema_version"),
                "transformation_version": shadow.get("transformation_version"),
                "readiness": lock_payload.get("readiness") or {},
            })
        rows.append(row)
    counts["eligible"] = len(rows)
    return rows, dict(sorted(counts.items()))


def build_report(paths: Iterable[str | Path]) -> dict[str, Any]:
    all_events = []
    sources = []
    for value in paths:
        path = Path(value)
        state = forecast_ledger.validate(path)
        all_events.extend(forecast_ledger.read_events(path))
        sources.append({"path": str(path), "events": state["events"], "last_hash": state["last_hash"]})
    cohort_fields = ("model_version", "trained_through", "artifact_sha256",
                     "feature_schema_version", "transformation_version")
    cohorts = set()
    legacy_locks_present = False
    for event in all_events:
        if event.get("event_type") == "forecast_locked":
            legacy_locks_present = True
        if event.get("event_type") != "mlb_shadow_locked":
            continue
        candidate = (event.get("payload") or {}).get("candidate") or {}
        identity = tuple(candidate.get(key) for key in cohort_fields)
        if not all(identity):
            raise ValueError("MLB shadow lock is missing its exact candidate cohort identity")
        cohorts.add(identity)
    if len(cohorts) > 1:
        raise ValueError("mixed MLB challenger artifact cohorts cannot be aggregated")
    if cohorts and legacy_locks_present:
        raise ValueError("legacy MLB locks without exact artifact identity cannot join a shadow cohort")
    rows, exclusions = extract_rows(all_events)
    baseline_fields = ("model_version", "model_signal_schema")
    baseline_cohorts = {
        (row.get("baseline_model_version"), row.get("baseline_model_signal_schema"))
        for row in rows
    }
    if cohorts and any(not all(identity) for identity in baseline_cohorts):
        raise ValueError("MLB shadow evidence is missing incumbent baseline cohort identity")
    if len(baseline_cohorts) > 1:
        raise ValueError("mixed MLB incumbent baseline cohorts cannot be aggregated")
    comparison = _paired_block_interval(rows, "challenger_home_probability", "official_home_probability")
    capped_comparison = _paired_block_interval(
        rows, "capped_blend_home_probability", "official_home_probability")
    market_rows = _rows_with_probability(rows, "market_home_probability")
    independent_rows = _rows_with_probability(rows, "independent_official_home_probability")
    prior_rows = _rows_with_probability(rows, "league_home_prior_probability")
    enough_data = len(rows) >= MIN_GAMES and capped_comparison["blocks"] >= MIN_DATE_BLOCKS
    cohort = (dict(zip(cohort_fields, next(iter(cohorts)))) if cohorts else {
        key: None for key in cohort_fields
    })
    baseline_cohort = (dict(zip(baseline_fields, next(iter(baseline_cohorts))))
                       if baseline_cohorts else {key: None for key in baseline_fields})
    missingness: dict[str, int] = defaultdict(int)
    market_missingness: dict[str, int] = defaultdict(int)
    for row in rows:
        for reason in row.get("missing_personnel") or []:
            missingness[str(reason)] += 1
        if row.get("market_home_probability") is None:
            market_missingness[str(row.get("market_missing_reason") or "missing_probability")] += 1
    official_metrics = _metrics(rows, "official_home_probability")
    challenger_metrics = _metrics(rows, "challenger_home_probability")
    capped_metrics = _metrics(rows, "capped_blend_home_probability")
    return {
        "schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
        "research_only": True, "production_weight": 0,
        "cohort": cohort,
        "baseline_cohort": baseline_cohort,
        "evaluation_contract": {
            "unit": "one uniquely locked, later graded MLB fixture", "primary_metric": "log_loss",
            "secondary_metric": "brier", "tie_policy": "exclude", "minimum_games": MIN_GAMES,
            "minimum_game_date_blocks": MIN_DATE_BLOCKS,
            "decision_rule": "evaluate only after both minimums; prospective evidence cannot auto-promote",
        },
        "sources": sources, "exclusions": exclusions,
        "coverage": {
            "eligible_graded": len(rows),
            "market_available": len(market_rows),
            "independent_official_available": len(independent_rows),
            "league_home_prior_available": len(prior_rows),
            "personnel_missing_reasons": dict(sorted(missingness.items())),
            "market_missing_reasons": dict(sorted(market_missingness.items())),
            "event_exclusion_reasons": exclusions,
        },
        "models": {
            "official": official_metrics,
            "run_strength_challenger": challenger_metrics,
            "capped_blend": capped_metrics,
            "independent_official": _metrics(independent_rows, "independent_official_home_probability"),
            "league_home_prior": _metrics(prior_rows, "league_home_prior_probability"),
            "no_vig_lock_market": _metrics(market_rows, "market_home_probability"),
        },
        "comparisons": {"run_strength_vs_official": comparison},
        "deployment_evaluation": {
            "policy": {"production_weight": .10, "max_shift_points": 3.0,
                       "allow_pick_flip": False, "probability_rounding": "none"},
            "models": {"official": official_metrics, "capped_blend": capped_metrics},
            "comparisons": {"capped_blend_vs_official": capped_comparison},
        },
        "status": "ready_for_frozen_review" if enough_data else "collecting_prospective_evidence",
        "rows": rows,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
