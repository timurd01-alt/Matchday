"""Private, append-only MLB research locks collected during the public pause.

This ledger is deliberately independent of ``picks_log_mlb.json`` and the
public fixture payload.  It preserves prospective evidence while official MLB
forecasts are disabled, without turning a research forecast into a public pick.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import forecast_ledger


LOCK_EVENT = "mlb_shadow_locked"
GRADE_EVENT = "mlb_shadow_graded"
PROTOCOL_VERSION = "mlb-paused-shadow-lock-1.0.0"
LOCK_WINDOW_HOURS = 2.0


def _safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _digest(value: Any) -> str:
    material = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _probability(value: Any, *, percent: bool = False) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if percent:
        result /= 100.0
    return round(result, 6) if 0.0 < result < 1.0 else None


def _input_snapshot(match: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id", "kickoff", "status", "home", "away", "markets", "venue",
        "weather", "injuries", "lineups", "personnel", "personnel_shadow",
        "pregame_context", "pregame_provenance", "venue_context",
        "advanced_metrics", "advanced_metrics_meta", "data_source",
        "model_signal_schema", "mlb_challenger_shadow",
    )
    return _safe({key: match.get(key) for key in fields})


def _existing_locks(events: Iterable[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    locks = {}
    for event in events:
        if event.get("event_type") != LOCK_EVENT:
            continue
        payload = event.get("payload") or {}
        model_version = str(((payload.get("candidate") or {}).get("model_version")) or "")
        locks[(str(event.get("fixture_id") or ""), model_version)] = event
    return locks


def lock_match(path: str | Path, match: dict[str, Any], prediction: dict[str, Any],
               now: datetime | None = None) -> bool:
    """Freeze one pregame baseline/challenger pair, idempotently."""
    if str(match.get("status") or "").upper() != "UPCOMING":
        return False
    kickoff = _parse_time(match.get("kickoff"))
    current = _utc(now)
    if kickoff is None:
        return False
    lead_seconds = (kickoff - current).total_seconds()
    if lead_seconds <= 0 or lead_seconds > LOCK_WINDOW_HOURS * 3600:
        return False

    challenger = match.get("mlb_challenger_shadow") or {}
    if (challenger.get("mode") != "prospective_shadow"
            or challenger.get("production_weight") != 0):
        return False
    model_version = str(challenger.get("model_version") or "")
    artifact_sha256 = str(challenger.get("artifact_sha256") or "")
    feature_schema = challenger.get("feature_schema") or []
    feature_schema_version = challenger.get("feature_schema_version")
    transformation_version = str(challenger.get("transformation_version") or "")
    candidate_home = _probability(challenger.get("home_win_probability"))
    baseline_home = _probability((prediction.get("regulation_probs") or {}).get("h"), percent=True)
    baseline_model_version = str(prediction.get("model_version") or "")
    baseline_model_signal_schema = prediction.get("model_signal_schema")
    independent_home = _probability((prediction.get("model") or {}).get("h"), percent=True)
    league_home_prior = _probability(challenger.get("league_home_prior_probability"))
    if (not model_version or len(artifact_sha256) != 64 or not feature_schema
            or feature_schema_version is None or not transformation_version
            or not baseline_model_version or baseline_model_signal_schema is None
            or candidate_home is None or baseline_home is None or independent_home is None
            or league_home_prior is None):
        return False

    target = Path(path)
    forecast_ledger.validate(target)
    events = forecast_ledger.read_events(target)
    if (str(match.get("id") or ""), model_version) in _existing_locks(events):
        return False

    market = (match.get("markets") or {}).get("1x2") or {}
    market_home = _probability(market.get("home_pct"), percent=True)
    market_observed = _parse_time(market.get("observed_at"))
    market_missing_reason = None
    if market_home is None:
        market_missing_reason = "missing_probability"
    elif market_observed is None:
        market_home = None
        market_missing_reason = "missing_or_unparseable_observed_at"
    elif market_observed > current or market_observed >= kickoff:
        market_home = None
        market_missing_reason = "quote_observed_after_lock"
    snapshot = _input_snapshot(match)
    readiness = _safe(match.get("pregame_context") or {})
    missing_inputs = sorted(key for key, status in (readiness.get("inputs") or {}).items()
                            if status == "missing")
    missing_personnel = sorted(set(
        list(challenger.get("missing_personnel") or [])
        + [key for key in missing_inputs
           if key in {"injuries", "starting_pitchers", "lineups", "bullpen"}]
    ))
    effective_at = _iso(current)
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "lock": {
            "effective_at": effective_at, "kickoff": match.get("kickoff"),
            "lead_time_seconds": round(lead_seconds, 3),
            "lock_window_hours": LOCK_WINDOW_HOURS, "status_at_lock": "UPCOMING",
        },
        "participants": {
            "home": (match.get("home") or {}).get("name"),
            "away": (match.get("away") or {}).get("name"),
        },
        "baseline": {
            "model_version": baseline_model_version,
            "model_signal_schema": baseline_model_signal_schema,
            "home_win_probability": baseline_home,
            "source": "paused production model raw pre-publication forecast",
        },
        "league_home_prior": {"home_win_probability": league_home_prior},
        "independent_official": {"home_win_probability": independent_home},
        "candidate": {
            "model_version": model_version,
            "artifact_sha256": artifact_sha256,
            "feature_schema": _safe(feature_schema),
            "feature_schema_version": challenger.get("feature_schema_version"),
            "transformation_version": challenger.get("transformation_version"),
            "trained_through": challenger.get("trained_through"),
            "home_win_probability": candidate_home,
            "production_weight": 0, "mode": "prospective_shadow",
            "features": _safe(challenger.get("features") or {}),
        },
        "market": {
            "home_win_probability": market_home,
            "observed_at": market.get("observed_at"),
            "missing_reason": market_missing_reason,
            "snapshot_id": market.get("snapshot_id"),
            "books": market.get("books"), "source": market.get("source"),
        },
        "readiness": readiness,
        "personnel_missingness": missing_personnel,
        "provenance": {
            "competition": "MLB", "provider": match.get("data_source"),
            "training_cutoff": challenger.get("trained_through"),
            "candidate_artifact_sha256": artifact_sha256,
            "candidate_feature_schema": _safe(feature_schema),
            "feature_schema_version": feature_schema_version,
            "transformation_version": transformation_version,
            "input_snapshot_hash": _digest(snapshot),
        },
        "input_snapshot": snapshot,
    }
    _, created = forecast_ledger.append_event(
        target, event_type=LOCK_EVENT, fixture_id=str(match.get("id") or ""),
        competition="MLB", effective_at=effective_at,
        identity={"protocol_version": PROTOCOL_VERSION, "model_version": model_version},
        payload=payload,
    )
    return created


def grade_matches(path: str | Path, matches: Iterable[dict[str, Any]],
                  now: datetime | None = None) -> int:
    """Append result events for previously frozen locks; never mutate a lock."""
    target = Path(path)
    forecast_ledger.validate(target)
    events = forecast_ledger.read_events(target)
    locks_by_fixture: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("event_type") == LOCK_EVENT:
            locks_by_fixture.setdefault(str(event.get("fixture_id") or ""), []).append(event)
    appended = 0
    for match in matches:
        fixture_id = str(match.get("id") or "")
        if str(match.get("status") or "").upper() != "FINISHED" or fixture_id not in locks_by_fixture:
            continue
        score = match.get("score") or {}
        try:
            home_score, away_score = float(score.get("home")), float(score.get("away"))
        except (TypeError, ValueError):
            continue
        result = "h" if home_score > away_score else "a" if away_score > home_score else "d"
        grade_time = _utc(now)
        for lock in locks_by_fixture[fixture_id]:
            lock_payload = lock.get("payload") or {}
            locked_kickoff = _parse_time((lock_payload.get("lock") or {}).get("kickoff"))
            current_kickoff = _parse_time(match.get("kickoff"))
            locked_participants = lock_payload.get("participants") or {}
            current_participants = {
                "home": (match.get("home") or {}).get("name"),
                "away": (match.get("away") or {}).get("name"),
            }
            if (locked_kickoff is None or current_kickoff != locked_kickoff
                    or current_participants != locked_participants):
                raise ValueError(
                    f"MLB shadow grade fixture identity mismatch for {fixture_id}")
            if grade_time < locked_kickoff:
                raise ValueError(f"MLB shadow grade precedes locked kickoff for {fixture_id}")
            effective_at = _iso(grade_time)
            payload = {
                "protocol_version": PROTOCOL_VERSION,
                "lock_event_id": lock.get("event_id"), "result": result,
                "fixture_identity": {
                    "fixture_id": fixture_id, "kickoff": match.get("kickoff"),
                    "participants": current_participants,
                },
                "score": {"home": score.get("home"), "away": score.get("away")},
                "result_snapshot": _safe(score),
                "outcome_source": {
                    "provider": match.get("data_source"),
                    "observed_at": (score.get("observed_at") or
                                    match.get("result_observed_at") or
                                    match.get("updated_at")),
                    "recorded_at": effective_at,
                },
            }
            _, created = forecast_ledger.append_event(
                target, event_type=GRADE_EVENT, fixture_id=fixture_id,
                competition="MLB", effective_at=effective_at,
                identity={"lock_event_id": lock.get("event_id"), "result": result,
                          "score": payload["score"]}, payload=payload,
            )
            appended += int(created)
    return appended


def sync(path: str | Path, matches: Iterable[dict[str, Any]],
         predictions: dict[str, dict[str, Any]] | None = None,
         now: datetime | None = None) -> dict[str, Any]:
    """Lock eligible forecasts and grade finals in one deterministic pass."""
    rows = list(matches)
    predictions = predictions or {}
    locked = sum(int(lock_match(path, match, predictions.get(str(match.get("id") or ""), {}), now))
                 for match in rows)
    graded = grade_matches(path, rows, now)
    state = forecast_ledger.validate(path)
    return {"locked": locked, "graded": graded, "events": state["events"],
            "last_hash": state["last_hash"]}
