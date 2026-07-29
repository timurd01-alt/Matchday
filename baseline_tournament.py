"""Leakage-resistant baseline tournament over frozen Matchday forecasts."""

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
import market_snapshots


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "baseline-tournament-1.0.0"
MIN_GAMES = 256
MIN_TIME_BLOCKS = 16
MODEL_KEYS = (
    "league_prior", "raw_elo", "calibrated_elo", "matchday_independent",
    "matchday_market_informed", "no_vig_lock_market",
)


def _time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("baseline tournament timestamps must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("baseline tournament timestamps must include a timezone")
    return parsed


def _probabilities(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    clean = {}
    for outcome in ("h", "d", "a"):
        try:
            number = float(value.get(outcome, 0.0))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0:
            return None
        if number:
            clean[outcome] = number / 100.0 if number > 1.0 else number
    total = sum(clean.values())
    if not clean or total <= 0:
        return None
    return {outcome: number / total for outcome, number in clean.items()}


def _two_way(home_probability: Any) -> dict[str, float] | None:
    try:
        probability = float(home_probability)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        return None
    return {"h": probability, "a": 1.0 - probability}


def _settlement(grade: dict[str, Any], outcomes: set[str]) -> str | None:
    payload = grade.get("payload") or {}
    value = payload.get("market_result") if "d" in outcomes else payload.get("result")
    if value not in outcomes:
        value = payload.get("result")
    return value if value in outcomes else None


def _grade_at_cutoff(
    events: list[dict[str, Any]], cutoff: datetime
) -> dict[tuple[str, str], dict[str, Any]]:
    latest = {}
    for event in events:
        if event.get("event_type") != "forecast_graded" or not event.get("effective_at"):
            continue
        if _time(event["effective_at"]) <= cutoff:
            key = (str(event.get("competition") or ""), str(event.get("fixture_id") or ""))
            latest[key] = event
    return latest


def _league_prior(events: list[dict[str, Any]], lock: dict[str, Any], outcomes: set[str]) -> dict[str, float]:
    counts = {outcome: 2.0 for outcome in outcomes}  # frozen symmetric Dirichlet smoothing
    fixture_id = str(lock.get("fixture_id") or "")
    competition = str(lock.get("competition") or "")
    for (historical_competition, historical_id), grade in _grade_at_cutoff(
            events, _time(lock["effective_at"])).items():
        if historical_id == fixture_id or historical_competition != competition:
            continue
        result = _settlement(grade, outcomes)
        if result:
            counts[result] += 1.0
    total = sum(counts.values())
    return {outcome: counts[outcome] / total for outcome in sorted(outcomes)}


def _market_consensus(
    market_path: str | Path | None, fixture_id: str, competition: str, kickoff: Any,
    locked_at: datetime, outcomes: set[str], frozen_snapshot: Any
) -> tuple[dict[str, float] | None, dict[str, Any]]:
    if market_path and Path(market_path).exists():
        snapshots = market_snapshots.fixture_snapshots(market_path, fixture_id, kickoff, competition)
        eligible = [item for item in snapshots
                    if set(item.get("no_vig_probabilities") or {}) == outcomes
                    and _time(item["observed_at"]) <= locked_at
                    and _time(item["recorded_at"]) <= locked_at]
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in eligible:
            by_source[str(item.get("source") or "unknown")].append(item)
        selected = []
        for source in sorted(by_source):
            selected.append(sorted(by_source[source], key=lambda item: (
                _time(item["observed_at"]), _time(item["recorded_at"]), item["event_id"]))[-1])
        if selected:
            probabilities = {outcome: sum(float(item["no_vig_probabilities"][outcome])
                                                  for item in selected) / len(selected)
                             for outcome in sorted(outcomes)}
            return probabilities, {"basis": "authorized_timestamped_consensus",
                                   "sources": [item["source"] for item in selected],
                                   "event_ids": [item["event_id"] for item in selected]}
    normalized = _probabilities(frozen_snapshot)
    if normalized and set(normalized) == outcomes:
        return normalized, {"basis": "normalized_market_snapshot_frozen_in_forecast_lock",
                            "sources": [], "event_ids": []}
    return None, {"basis": "unavailable", "sources": [], "event_ids": []}


def extract_rows(
    events: Iterable[dict[str, Any]], market_path: str | Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    all_events = list(events)
    locks: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    latest_grades = {}
    counts: dict[str, int] = defaultdict(int)
    for event in all_events:
        fixture_id = str(event.get("fixture_id") or "")
        key = (str(event.get("competition") or ""), fixture_id)
        if event.get("event_type") == "forecast_locked":
            locks[key].append(event)
        elif event.get("event_type") == "forecast_graded":
            latest_grades[key] = event
    rows = []
    for (competition, fixture_id), fixture_locks in sorted(locks.items()):
        if len(fixture_locks) != 1:
            counts["ambiguous_locks"] += 1
            continue
        lock = fixture_locks[0]
        grade = latest_grades.get((competition, fixture_id))
        if not grade:
            counts["pending"] += 1
            continue
        payload = lock.get("payload") or {}
        lock_info = payload.get("lock") or {}
        model_payload = payload.get("model") or {}
        independent = _probabilities(model_payload.get("independent_probabilities"))
        if not independent:
            counts["invalid_independent_probability"] += 1
            continue
        outcomes = set(independent)
        result = _settlement(grade, outcomes)
        if not result:
            counts["incompatible_result"] += 1
            continue
        locked_at = _time(lock.get("effective_at"))
        kickoff = _time(lock_info.get("kickoff"))
        if locked_at >= kickoff:
            counts["invalid_lock_time"] += 1
            continue
        shadow = ((payload.get("features") or {}).get("nfl_challenger_shadow") or {})
        raw_elo = _two_way(shadow.get("elo_baseline_home_probability")) if outcomes == {"h", "a"} else None
        calibrated_elo = (_two_way(shadow.get("calibrated_elo_home_probability"))
                          if outcomes == {"h", "a"} else None)
        market_informed = _probabilities(model_payload.get("market_informed_probabilities"))
        if market_informed and set(market_informed) != outcomes:
            market_informed = None
        market_payload = payload.get("market") or {}
        no_vig_market, market_receipt = _market_consensus(
            market_path, fixture_id, competition, lock_info.get("kickoff"), locked_at, outcomes,
            market_payload.get("snapshot"))
        rows.append({"fixture_id": fixture_id, "competition": lock.get("competition"),
                     "lock_event_id": lock.get("event_id"), "grade_event_id": grade.get("event_id"),
                     "locked_at": lock.get("effective_at"), "kickoff": lock_info.get("kickoff"),
                     "outcome_universe": sorted(outcomes), "result": result,
                     "league_prior": _league_prior(all_events, lock, outcomes),
                     "raw_elo": raw_elo, "calibrated_elo": calibrated_elo,
                     "matchday_independent": independent,
                     "matchday_market_informed": market_informed,
                     "no_vig_lock_market": no_vig_market, "market_receipt": market_receipt})
    counts["eligible"] = len(rows)
    for key in MODEL_KEYS:
        counts[f"with_{key}"] = sum(isinstance(row.get(key), dict) for row in rows)
    return rows, dict(sorted(counts.items()))


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    eligible = [row for row in rows if isinstance(row.get(key), dict) and row["result"] in row[key]]
    if not eligible:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    losses = []
    briers = []
    hits = 0
    for row in eligible:
        probabilities = row[key]
        result = row["result"]
        probability = min(max(float(probabilities[result]), 1e-12), 1 - 1e-12)
        losses.append(-math.log(probability))
        briers.append(sum((float(probabilities.get(outcome, 0.0)) - float(outcome == result)) ** 2
                          for outcome in row["outcome_universe"]))
        hits += max(probabilities, key=probabilities.get) == result
    return {"n": len(eligible), "log_loss": round(sum(losses) / len(losses), 6),
            "brier": round(sum(briers) / len(briers), 6),
            "accuracy": round(hits / len(eligible), 6)}


def _paired(rows: list[dict[str, Any]], candidate: str, baseline: str,
            samples: int = 4000) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if not isinstance(row.get(candidate), dict) or not isinstance(row.get(baseline), dict):
            continue
        result = row["result"]
        if result not in row[candidate] or result not in row[baseline]:
            continue
        candidate_p = min(max(float(row[candidate][result]), 1e-12), 1 - 1e-12)
        baseline_p = min(max(float(row[baseline][result]), 1e-12), 1 - 1e-12)
        kickoff = _time(row["kickoff"])
        week = kickoff.isocalendar()
        block = f"{row['competition']}:{week.year}-W{week.week:02d}"
        grouped[block].append(-math.log(candidate_p) + math.log(baseline_p))
    blocks = sorted(grouped)
    values = [value for block in blocks for value in grouped[block]]
    output = {"candidate": candidate, "baseline": baseline, "n": len(values), "blocks": len(blocks),
              "mean_log_loss_delta": round(sum(values) / len(values), 6) if values else None,
              "ci95": [None, None], "method": "deterministic competition-week block bootstrap"}
    if len(blocks) < 2:
        return output
    seed_text = "|".join(f"{block}:{','.join(f'{value:.12f}' for value in grouped[block])}"
                         for block in blocks)
    rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16))
    estimates = []
    for _ in range(samples):
        selected = [rng.choice(blocks) for _ in blocks]
        draw = [value for block in selected for value in grouped[block]]
        estimates.append(sum(draw) / len(draw))
    estimates.sort()
    output["ci95"] = [round(estimates[int(samples * .025)], 6),
                      round(estimates[min(int(samples * .975), samples - 1)], 6)]
    return output


def build_report(
    forecast_paths: Iterable[str | Path], market_path: str | Path | None = None
) -> dict[str, Any]:
    all_events = []
    sources = []
    for value in forecast_paths:
        state = forecast_ledger.validate(value)
        all_events.extend(forecast_ledger.read_events(value))
        sources.append({"path": str(value), "events": state["events"], "last_hash": state["last_hash"]})
    market_source = None
    if market_path and Path(market_path).exists():
        state = market_snapshots.validate(market_path)
        market_source = {"path": str(market_path), "events": state["events"], "last_hash": state["last_hash"]}
    rows, coverage = extract_rows(all_events, market_path)
    overall = {key: _metrics(rows, key) for key in MODEL_KEYS}
    pairwise = {}
    for key in MODEL_KEYS:
        if key == "matchday_independent":
            continue
        same_fixtures = [row for row in rows
                         if isinstance(row.get(key), dict)
                         and isinstance(row.get("matchday_independent"), dict)]
        pairwise[key] = {
            "candidate_same_fixtures": _metrics(same_fixtures, key),
            "matchday_independent_same_fixtures": _metrics(same_fixtures, "matchday_independent"),
            "paired_log_loss": _paired(same_fixtures, key, "matchday_independent"),
        }
    by_competition = {}
    for competition in sorted({str(row.get("competition") or "") for row in rows}):
        subset = [row for row in rows if str(row.get("competition") or "") == competition]
        by_competition[competition] = {key: _metrics(subset, key) for key in MODEL_KEYS}
    common = [row for row in rows if all(isinstance(row.get(key), dict) for key in MODEL_KEYS)]
    common_metrics = {key: _metrics(common, key) for key in MODEL_KEYS}
    blocks = len({f"{row['competition']}:{_time(row['kickoff']).isocalendar().year}-W"
                  f"{_time(row['kickoff']).isocalendar().week:02d}" for row in rows})
    common_blocks = len({f"{row['competition']}:{_time(row['kickoff']).isocalendar().year}-W"
                         f"{_time(row['kickoff']).isocalendar().week:02d}" for row in common})
    ready = len(common) >= MIN_GAMES and common_blocks >= MIN_TIME_BLOCKS
    return {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
            "research_only": True, "production_weight": 0,
            "evaluation_contract": {"primary_metric": "log_loss", "secondary_metric": "multiclass_brier",
                "league_prior": "same-competition settled locked events known by target lock; Dirichlet(2) smoothing",
                "comparisons": "pairwise identical fixtures with competition-week block intervals",
                "minimum_all-model_common_games": MIN_GAMES,
                "minimum_time_blocks": MIN_TIME_BLOCKS,
                "decision_rule": "threshold permits review only; no automatic production promotion"},
            "forecast_sources": sources, "market_source": market_source, "coverage": coverage,
            "overall": overall, "pairwise_vs_matchday_independent": pairwise,
            "all_models_common_fixture_metrics": common_metrics,
            "all_models_common_fixtures": len(common), "time_blocks": blocks,
            "all_models_common_time_blocks": common_blocks,
            "by_competition": by_competition,
            "status": "ready_for_frozen_review" if ready else "collecting_comparable_evidence",
            "rows": rows}


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
