"""Grade frozen NFL shadow forecasts from Matchday's append-only ledger."""

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
PROTOCOL_VERSION = "nfl-prospective-shadow-1.0.0"
MIN_GAMES = 256
MIN_TIME_BLOCKS = 16


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and 0.0 < result < 1.0 else None


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _time_block(value: Any) -> str:
    parsed = _parse_time(value)
    if not parsed:
        return "unknown"
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy": None,
                "calibration": []}
    brier = log_loss = hits = 0.0
    bands: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        probability = float(row[key])
        outcome = float(row["home_win"])
        brier += (probability - outcome) ** 2
        clipped = min(max(probability, 1e-12), 1.0 - 1e-12)
        log_loss -= outcome * math.log(clipped) + (1.0 - outcome) * math.log(1.0 - clipped)
        hits += int((probability >= 0.5) == bool(outcome))
        bands[min(int(probability * 10), 9)].append(row)
    calibration = []
    for band, values in sorted(bands.items()):
        calibration.append({
            "range": f"{band * 10}-{(band + 1) * 10}%", "n": len(values),
            "mean_probability": round(sum(float(row[key]) for row in values) / len(values), 6),
            "home_win_rate": round(sum(float(row["home_win"]) for row in values) / len(values), 6),
        })
    count = len(rows)
    return {"n": count, "brier": round(brier / count, 6),
            "log_loss": round(log_loss / count, 6), "accuracy": round(hits / count, 6),
            "calibration": calibration}


def _log_loss(probability: float, outcome: int) -> float:
    probability = min(max(probability, 1e-12), 1.0 - 1e-12)
    return -(outcome * math.log(probability) + (1 - outcome) * math.log(1.0 - probability))


def _paired_block_interval(
    rows: list[dict[str, Any]], candidate_key: str, baseline_key: str, samples: int = 4000
) -> dict[str, Any]:
    """Deterministic week-block bootstrap of candidate minus baseline log loss."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row["time_block"]].append(
            _log_loss(float(row[candidate_key]), int(row["home_win"]))
            - _log_loss(float(row[baseline_key]), int(row["home_win"]))
        )
    blocks = sorted(grouped)
    deltas = [value for block in blocks for value in grouped[block]]
    result = {"n": len(deltas), "blocks": len(blocks),
              "mean_log_loss_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
              "ci95": [None, None], "method": "deterministic kickoff-week block bootstrap"}
    if len(blocks) < 2:
        return result
    seed_material = "|".join(
        f"{row['fixture_id']}:{row[candidate_key]}:{row[baseline_key]}:{row['home_win']}"
        for row in sorted(rows, key=lambda item: (item["fixture_id"], item["lock_event_id"]))
    )
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
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
    locks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grades: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        fixture_id = str(event.get("fixture_id") or "")
        if not fixture_id:
            continue
        if event.get("event_type") == "forecast_locked":
            locks[fixture_id].append(event)
        elif event.get("event_type") == "forecast_graded":
            grades[fixture_id] = event

    rows = []
    for fixture_id, fixture_locks in sorted(locks.items()):
        if len(fixture_locks) != 1:
            counts["ambiguous_locks"] += 1
            continue
        lock = fixture_locks[0]
        grade = grades.get(fixture_id)
        if not grade:
            counts["pending"] += 1
            continue
        lock_payload = lock.get("payload") or {}
        grade_payload = grade.get("payload") or {}
        result = grade_payload.get("result")
        if result == "d":
            counts["ties_excluded"] += 1
            continue
        if result not in {"h", "a"}:
            counts["invalid_result"] += 1
            continue
        lock_time = _parse_time(lock.get("effective_at"))
        kickoff = _parse_time((lock_payload.get("lock") or {}).get("kickoff"))
        if not lock_time or not kickoff or lock_time >= kickoff:
            counts["invalid_lock_time"] += 1
            continue
        shadow = ((lock_payload.get("features") or {}).get("nfl_challenger_shadow") or {})
        if shadow.get("production_weight") != 0 or shadow.get("mode") != "research_only":
            counts["not_frozen_shadow"] += 1
            continue
        challenger = _number(shadow.get("home_win_probability"))
        calibrated = _number(shadow.get("calibrated_elo_home_probability"))
        raw = _number(shadow.get("elo_baseline_home_probability"))
        if None in {challenger, calibrated, raw}:
            counts["missing_probability"] += 1
            continue
        rows.append({
            "fixture_id": fixture_id, "lock_event_id": lock.get("event_id"),
            "grade_event_id": grade.get("event_id"), "locked_at": lock.get("effective_at"),
            "kickoff": (lock_payload.get("lock") or {}).get("kickoff"),
            "time_block": _time_block((lock_payload.get("lock") or {}).get("kickoff")),
            "model_version": shadow.get("model_version"), "trained_through": shadow.get("trained_through"),
            "home_win": int(result == "h"), "challenger_home_probability": challenger,
            "calibrated_elo_home_probability": calibrated, "raw_elo_home_probability": raw,
        })
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
    rows, exclusions = extract_rows(all_events)
    calibrated_vs_raw = _paired_block_interval(
        rows, "calibrated_elo_home_probability", "raw_elo_home_probability")
    challenger_vs_calibrated = _paired_block_interval(
        rows, "challenger_home_probability", "calibrated_elo_home_probability")
    enough_data = len(rows) >= MIN_GAMES and calibrated_vs_raw["blocks"] >= MIN_TIME_BLOCKS
    return {
        "schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
        "research_only": True, "production_weight": 0,
        "evaluation_contract": {
            "unit": "one uniquely locked, later graded NFL fixture", "primary_metric": "log_loss",
            "secondary_metric": "brier", "tie_policy": "exclude", "minimum_games": MIN_GAMES,
            "minimum_kickoff_week_blocks": MIN_TIME_BLOCKS,
            "decision_rule": "evaluate only after both minimums; prospective evidence cannot auto-promote",
        },
        "sources": sources, "exclusions": exclusions,
        "models": {"raw_elo": _metrics(rows, "raw_elo_home_probability"),
                   "calibrated_elo": _metrics(rows, "calibrated_elo_home_probability"),
                   "advanced_challenger": _metrics(rows, "challenger_home_probability")},
        "comparisons": {"calibrated_elo_vs_raw_elo": calibrated_vs_raw,
                        "advanced_challenger_vs_calibrated_elo": challenger_vs_calibrated},
        "status": "ready_for_frozen_review" if enough_data else "collecting_prospective_evidence",
        "rows": rows,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
