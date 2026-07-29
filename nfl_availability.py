"""Append-only, pregame-only NFL availability observations.

The module does not fetch or infer player status.  It accepts observations
only when the caller declares an approved authorization basis, timestamps
them before kickoff, and preserves them in a tamper-evident local ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
AUTHORIZATION_BASES = {"licensed", "open_license", "first_party", "user_supplied_with_permission"}
STATUSES = {"ACTIVE", "FULL", "PROBABLE", "QUESTIONABLE", "DOUBTFUL", "OUT", "IR", "PUP",
            "SUSPENDED", "UNKNOWN"}
POSITION_GROUPS = {"QB", "OL", "RB", "WR", "TE", "DL", "LB", "DB", "K", "P", "LS", "OTHER"}
ROLES = {"STARTER", "ROTATION", "DEPTH", "UNKNOWN"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _time(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field} timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_events(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    events = []
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid NFL availability JSON on line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"invalid NFL availability event on line {line_number}")
            events.append(event)
    return events


def validate(path: str | os.PathLike[str]) -> dict[str, Any]:
    previous = GENESIS_HASH
    seen = set()
    events = read_events(path)
    for line_number, event in enumerate(events, 1):
        if event.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported NFL availability schema on line {line_number}")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen:
            raise ValueError(f"missing or duplicate NFL availability event_id on line {line_number}")
        if event.get("previous_hash") != previous:
            raise ValueError(f"NFL availability chain break on line {line_number}")
        material = {key: value for key, value in event.items() if key != "record_hash"}
        actual = _digest(material)
        if event.get("record_hash") != actual:
            raise ValueError(f"NFL availability hash mismatch on line {line_number}")
        recorded_at = _time(event.get("recorded_at"), "recorded_at")
        for observation in event.get("observations") or []:
            if recorded_at >= _time(observation.get("kickoff"), "kickoff"):
                raise ValueError(f"post-kickoff NFL availability event on line {line_number}")
            if _time(observation.get("observed_at"), "observed_at") > recorded_at:
                raise ValueError(f"future-dated NFL availability observation on line {line_number}")
        seen.add(event_id)
        previous = actual
    return {"events": len(events), "last_hash": previous, "event_ids": seen}


def _normalize_observation(raw: dict[str, Any], recorded_at: datetime) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("each NFL availability observation must be an object")
    fixture_id = str(raw.get("fixture_id") or "").strip()
    team_code = str(raw.get("team_code") or "").strip().upper()
    player_id = str(raw.get("player_id") or "").strip()
    player_name = str(raw.get("player_name") or "").strip()
    if not fixture_id or not team_code or not (player_id or player_name):
        raise ValueError("availability observations require fixture_id, team_code, and player identity")
    kickoff = _time(raw.get("kickoff"), "kickoff")
    observed_at = _time(raw.get("observed_at"), "observed_at")
    if recorded_at >= kickoff:
        raise ValueError(f"availability for {fixture_id} must be recorded before kickoff")
    if observed_at > recorded_at:
        raise ValueError(f"availability for {fixture_id} cannot be observed after it is recorded")
    status = str(raw.get("status") or "").upper()
    position_group = str(raw.get("position_group") or "OTHER").upper()
    role = str(raw.get("role") or "UNKNOWN").upper()
    if status not in STATUSES:
        raise ValueError(f"unsupported NFL availability status: {status}")
    if position_group not in POSITION_GROUPS:
        raise ValueError(f"unsupported NFL availability position group: {position_group}")
    if role not in ROLES:
        raise ValueError(f"unsupported NFL availability role: {role}")
    confidence = raw.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("availability confidence must be numeric") from exc
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("availability confidence must be between 0 and 1")
    return {"fixture_id": fixture_id, "kickoff": _iso(kickoff), "observed_at": _iso(observed_at),
            "team_code": team_code, "player_id": player_id or None, "player_name": player_name or None,
            "position_group": position_group, "role": role, "status": status,
            "confidence": confidence, "source_observation_id": str(raw.get("source_observation_id") or "") or None}


def append_batch(
    path: str | os.PathLike[str], payload: dict[str, Any], recorded_at: str | None = None
) -> dict[str, Any]:
    """Validate and append one authorized batch; identical replays are idempotent."""
    if not isinstance(payload, dict):
        raise ValueError("NFL availability payload must be an object")
    source = str(payload.get("source") or "").strip()
    authorization_basis = str(payload.get("authorization_basis") or "").strip()
    source_reference = str(payload.get("source_reference") or "").strip()
    if not source or not source_reference:
        raise ValueError("NFL availability requires source and source_reference provenance")
    if "espn" in f"{source} {source_reference}".lower():
        raise ValueError("ESPN-origin availability is excluded")
    if authorization_basis not in AUTHORIZATION_BASES:
        raise ValueError("NFL availability authorization_basis is missing or unsupported")
    recorded = _time(recorded_at or datetime.now(timezone.utc).isoformat(), "recorded_at")
    fetched = _time(payload.get("fetched_at"), "fetched_at")
    if fetched > recorded:
        raise ValueError("fetched_at cannot be after recorded_at")
    observations = [_normalize_observation(item, recorded) for item in payload.get("observations") or []]
    if not observations:
        raise ValueError("NFL availability batch has no observations")
    observations.sort(key=lambda item: (item["fixture_id"], item["team_code"],
                                        item["player_id"] or item["player_name"] or ""))
    state = validate(path)
    identity = {"source": source, "authorization_basis": authorization_basis,
                "source_reference": source_reference, "fetched_at": _iso(fetched),
                "observations": observations}
    event_id = _digest(identity)
    if event_id in state["event_ids"]:
        return {"created": False, "event_id": event_id, "events": state["events"],
                "last_hash": state["last_hash"]}
    event = {"schema_version": SCHEMA_VERSION, "event_id": event_id, "recorded_at": _iso(recorded),
             "previous_hash": state["last_hash"], "source": source,
             "authorization_basis": authorization_basis, "source_reference": source_reference,
             "fetched_at": _iso(fetched), "observations": observations}
    event["record_hash"] = _digest(event)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    final = validate(target)
    return {"created": True, "event_id": event_id, "events": final["events"],
            "last_hash": final["last_hash"]}


def fixture_receipt(
    path: str | os.PathLike[str], fixture_id: Any, kickoff: Any, as_of: str | None = None
) -> dict[str, Any] | None:
    """Return the latest pregame observation per player for one fixture."""
    source = Path(path)
    if not source.exists() or not fixture_id:
        return None
    validate(source)
    fixture_kickoff = _time(kickoff, "kickoff")
    cutoff = min(_time(as_of or datetime.now(timezone.utc).isoformat(), "as_of"), fixture_kickoff)
    latest: dict[tuple[str, str], tuple[datetime, dict[str, Any], dict[str, Any]]] = {}
    contributing_events = set()
    for event in read_events(source):
        recorded = _time(event["recorded_at"], "recorded_at")
        if recorded > cutoff:
            continue
        for observation in event.get("observations") or []:
            if str(observation.get("fixture_id")) != str(fixture_id):
                continue
            if _time(observation.get("kickoff"), "kickoff") != fixture_kickoff:
                continue
            identity = str(observation.get("player_id") or observation.get("player_name") or "").lower()
            key = (str(observation.get("team_code") or ""), identity)
            observed = _time(observation.get("observed_at"), "observed_at")
            if observed <= cutoff and (key not in latest or observed >= latest[key][0]):
                latest[key] = (observed, observation, event)
    if not latest:
        return None
    observations = []
    summaries: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "players": 0, "out": 0, "doubtful": 0, "questionable": 0, "active": 0,
        "starter_out": 0, "position_groups": defaultdict(int)})
    for _observed, observation, event in sorted(latest.values(), key=lambda item: (
            item[1]["team_code"], item[1]["position_group"], item[1].get("player_name") or "")):
        contributing_events.add(event["event_id"])
        observations.append(observation)
        summary = summaries[observation["team_code"]]
        summary["players"] += 1
        status = observation["status"].lower()
        if status in {"out", "ir", "pup", "suspended"}:
            summary["out"] += 1
            summary["starter_out"] += int(observation["role"] == "STARTER")
        elif status in {"doubtful", "questionable"}:
            summary[status] += 1
        elif status in {"active", "full", "probable"}:
            summary["active"] += 1
        summary["position_groups"][observation["position_group"]] += 1
    clean_summaries = {team: {**summary, "position_groups": dict(summary["position_groups"])}
                       for team, summary in sorted(summaries.items())}
    return {"schema_version": SCHEMA_VERSION, "mode": "research_only", "production_weight": 0,
            "fixture_id": str(fixture_id), "as_of": _iso(cutoff), "observations": observations,
            "team_summaries": clean_summaries, "event_ids": sorted(contributing_events),
            "availability_probability_adjustment": 0}
