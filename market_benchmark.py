"""Benchmark frozen Matchday forecasts against timestamped no-vig markets."""

from __future__ import annotations

import json
import hashlib
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import forecast_ledger
import market_snapshots


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "market-benchmark-1.0.0"


def _time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("market benchmark timestamps must include a timezone")
    return parsed


def _probabilities(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    clean = {}
    for key in ("h", "d", "a"):
        try:
            number = float(value.get(key, 0))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 0:
            return None
        if number:
            clean[key] = number / 100.0 if number > 1.0 else number
    total = sum(clean.values())
    if not clean or total <= 0:
        return None
    return {key: number / total for key, number in clean.items()}


def _source_consensus(
    snapshots: list[dict[str, Any]], cutoff: datetime, outcomes: set[str], earliest: bool = False
) -> dict[str, Any] | None:
    eligible = [snapshot for snapshot in snapshots
                if set(snapshot.get("no_vig_probabilities") or {}) == outcomes
                and _time(snapshot["observed_at"]) <= cutoff
                and _time(snapshot["recorded_at"]) <= cutoff]
    if not eligible:
        return None
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in eligible:
        by_source[str(snapshot.get("source") or "unknown")].append(snapshot)
    selected = []
    for source in sorted(by_source):
        ordered = sorted(by_source[source], key=lambda item: (
            _time(item["observed_at"]), _time(item["recorded_at"]), item["event_id"]))
        selected.append(ordered[0] if earliest else ordered[-1])
    probabilities = {outcome: sum(float(item["no_vig_probabilities"][outcome])
                                          for item in selected) / len(selected)
                     for outcome in sorted(outcomes)}
    return {"probabilities": probabilities, "sources": [item["source"] for item in selected],
            "source_count": len(selected), "event_ids": [item["event_id"] for item in selected],
            "observed_at": [item["observed_at"] for item in selected]}


def _metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    eligible = [row for row in rows if isinstance(row.get(key), dict)
                and row["result"] in row[key]]
    if not eligible:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    losses = []
    briers = []
    hits = 0
    for row in eligible:
        probabilities = row[key]
        result = row["result"]
        probability = min(max(float(probabilities[result]), 1e-12), 1.0 - 1e-12)
        losses.append(-math.log(probability))
        briers.append(sum((float(probabilities.get(side, 0.0)) - float(side == result)) ** 2
                          for side in probabilities))
        hits += max(probabilities, key=probabilities.get) == result
    return {"n": len(eligible), "log_loss": round(sum(losses) / len(losses), 6),
            "brier": round(sum(briers) / len(briers), 6),
            "accuracy": round(hits / len(eligible), 6)}


def _paired_interval(rows: list[dict[str, Any]], market_key: str, samples: int = 4000) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if not isinstance(row.get(market_key), dict):
            continue
        result = row["result"]
        model_probability = min(max(float(row["model_independent"][result]), 1e-12), 1 - 1e-12)
        market_probability = min(max(float(row[market_key][result]), 1e-12), 1 - 1e-12)
        kickoff = _time(row["kickoff"])
        week = kickoff.isocalendar()
        block = f"{row.get('competition')}:{week.year}-W{week.week:02d}"
        grouped[block].append(-math.log(model_probability) + math.log(market_probability))
    blocks = sorted(grouped)
    values = [value for block in blocks for value in grouped[block]]
    output = {"n": len(values), "blocks": len(blocks),
              "mean_matchday_minus_market_log_loss": round(sum(values) / len(values), 6) if values else None,
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


def _closing_movement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = []
    for row in rows:
        if not isinstance(row.get("lock_market"), dict) or not isinstance(row.get("closing_market"), dict):
            continue
        selected = max(row["model_independent"], key=row["model_independent"].get)
        values.append(float(row["closing_market"][selected]) - float(row["lock_market"][selected]))
    return {"n": len(values),
            "mean_probability_movement_toward_matchday_pick": round(sum(values) / len(values), 6) if values else None,
            "positive": sum(value > 0 for value in values), "zero": sum(value == 0 for value in values),
            "negative": sum(value < 0 for value in values)}


def _segment(rows: list[dict[str, Any]], classifier) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = classifier(row)
        if label:
            grouped[str(label)].append(row)
    output = {}
    for label, subset in sorted(grouped.items()):
        model = _metric(subset, "model_independent")
        market = _metric(subset, "closing_market")
        output[label] = {
            "n": len(subset), "matchday": model, "market": market,
            "matchday_minus_market_log_loss": (
                round(model["log_loss"] - market["log_loss"], 6)
                if model["log_loss"] is not None and market["log_loss"] is not None else None),
        }
    return output


def _outcome_segments(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe *where* market losses occur, without post-hoc model tuning."""
    eligible = [row for row in rows if isinstance(row.get("closing_market"), dict)]

    def favorite_result(row):
        market = row["closing_market"]
        favorite = max(market, key=market.get)
        return "favorite_won" if row["result"] == favorite else "underdog_or_draw_won"

    def agreement(row):
        model_pick = max(row["model_independent"], key=row["model_independent"].get)
        market_pick = max(row["closing_market"], key=row["closing_market"].get)
        return "agree" if model_pick == market_pick else "disagree"

    def confidence(row):
        pct = 100 * max(row["model_independent"].values())
        floor = int(pct // 10) * 10
        return f"{floor}-{floor + 9}%"

    def favorite_strength(row):
        pct = 100 * max(row["closing_market"].values())
        if pct < 55:
            return "pickem_under_55%"
        if pct < 65:
            return "favorite_55-64%"
        return "strong_favorite_65%+"

    return {
        "competition": _segment(eligible, lambda row: row.get("competition")),
        "realized_outcome": _segment(eligible, lambda row: row.get("result")),
        "favorite_result": _segment(eligible, favorite_result),
        "model_market_agreement": _segment(eligible, agreement),
        "model_confidence_band": _segment(eligible, confidence),
        "closing_favorite_strength": _segment(eligible, favorite_strength),
    }


def extract_rows(forecast_events: Iterable[dict[str, Any]], market_path: str | Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    locks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grades: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)
    for event in forecast_events:
        fixture_id = str(event.get("fixture_id") or "")
        if event.get("event_type") == "forecast_locked":
            locks[fixture_id].append(event)
        elif event.get("event_type") == "forecast_graded":
            grades[fixture_id] = event
    rows = []
    for fixture_id, fixture_locks in sorted(locks.items()):
        if len(fixture_locks) != 1:
            counts["ambiguous_locks"] += 1
            continue
        grade = grades.get(fixture_id)
        if not grade:
            counts["pending"] += 1
            continue
        grade_payload = grade.get("payload") or {}
        # 1X2 markets settle regulation time; knockout advancement may differ.
        result = grade_payload.get("market_result") or grade_payload.get("result")
        if result not in {"h", "d", "a"}:
            counts["invalid_result"] += 1
            continue
        lock = fixture_locks[0]
        payload = lock.get("payload") or {}
        lock_info = payload.get("lock") or {}
        model = _probabilities((payload.get("model") or {}).get("independent_probabilities"))
        if not model or result not in model:
            counts["invalid_model_probability"] += 1
            continue
        locked_at = _time(lock.get("effective_at"))
        kickoff = _time(lock_info.get("kickoff"))
        if locked_at >= kickoff:
            counts["invalid_lock_time"] += 1
            continue
        snapshots = market_snapshots.fixture_snapshots(
            market_path, fixture_id, lock_info.get("kickoff"), lock.get("competition")
        )
        outcomes = set(model)
        opening = _source_consensus(snapshots, kickoff, outcomes, earliest=True)
        at_lock = _source_consensus(snapshots, locked_at, outcomes)
        closing = _source_consensus(snapshots, kickoff, outcomes)
        rows.append({"fixture_id": fixture_id, "competition": lock.get("competition"),
                     "lock_event_id": lock.get("event_id"), "grade_event_id": grade.get("event_id"),
                     "locked_at": lock.get("effective_at"), "kickoff": lock_info.get("kickoff"),
                     "result": result, "model_independent": model,
                     "opening_market": opening["probabilities"] if opening else None,
                     "lock_market": at_lock["probabilities"] if at_lock else None,
                     "closing_market": closing["probabilities"] if closing else None,
                     "market_receipts": {"opening": opening, "lock": at_lock, "closing": closing}})
    counts["eligible_forecasts"] = len(rows)
    counts["with_opening_market"] = sum(row["opening_market"] is not None for row in rows)
    counts["with_lock_market"] = sum(row["lock_market"] is not None for row in rows)
    counts["with_closing_market"] = sum(row["closing_market"] is not None for row in rows)
    return rows, dict(sorted(counts.items()))


def build_report(forecast_paths: Iterable[str | Path], market_path: str | Path) -> dict[str, Any]:
    forecast_events = []
    forecast_sources = []
    for value in forecast_paths:
        state = forecast_ledger.validate(value)
        forecast_events.extend(forecast_ledger.read_events(value))
        forecast_sources.append({"path": str(value), "events": state["events"],
                                 "last_hash": state["last_hash"]})
    market_state = market_snapshots.validate(market_path)
    rows, coverage = extract_rows(forecast_events, market_path)
    comparisons = {}
    for stage in ("opening_market", "lock_market", "closing_market"):
        common = [row for row in rows if row.get(stage) is not None]
        comparisons[stage] = {"market": _metric(common, stage),
                              "matchday_independent_same_fixtures": _metric(common, "model_independent"),
                              "paired_log_loss": _paired_interval(common, stage)}
    return {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
            "research_only": True, "production_weight": 0,
            "method": {"margin_removal": "normalize implied probabilities to sum to one",
                       "consensus": "equal mean of the latest eligible no-vig snapshot per source",
                       "opening": "earliest pregame snapshot recorded per source",
                       "lock": "latest snapshot both observed and recorded by forecast lock",
                       "closing": "latest snapshot both observed and recorded before kickoff",
                       "primary_metric": "log_loss", "secondary_metric": "multiclass_brier"},
            "forecast_sources": forecast_sources,
            "market_source": {"path": str(market_path), "events": market_state["events"],
                              "last_hash": market_state["last_hash"]},
            "coverage": coverage, "comparisons": comparisons,
            "outcome_segments": _outcome_segments(rows),
            "closing_line_movement": _closing_movement(rows), "rows": rows}


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")
