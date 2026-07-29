"""Authorized, append-only pregame market snapshots with no-vig probabilities."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
AUTHORIZATION_BASES = {"licensed", "open_license", "first_party", "user_supplied_with_permission"}


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
                raise ValueError(f"invalid market snapshot JSON on line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"invalid market snapshot event on line {line_number}")
            events.append(event)
    return events


def validate(path: str | os.PathLike[str]) -> dict[str, Any]:
    previous = GENESIS_HASH
    seen = set()
    events = read_events(path)
    for line_number, event in enumerate(events, 1):
        if event.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported market snapshot schema on line {line_number}")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen:
            raise ValueError(f"missing or duplicate market snapshot event_id on line {line_number}")
        if event.get("previous_hash") != previous:
            raise ValueError(f"market snapshot chain break on line {line_number}")
        material = {key: value for key, value in event.items() if key != "record_hash"}
        actual = _digest(material)
        if event.get("record_hash") != actual:
            raise ValueError(f"market snapshot hash mismatch on line {line_number}")
        recorded = _time(event.get("recorded_at"), "recorded_at")
        for snapshot in event.get("snapshots") or []:
            if recorded >= _time(snapshot.get("kickoff"), "kickoff"):
                raise ValueError(f"post-kickoff market snapshot event on line {line_number}")
            if _time(snapshot.get("observed_at"), "observed_at") > recorded:
                raise ValueError(f"future-dated market snapshot on line {line_number}")
        seen.add(event_id)
        previous = actual
    return {"events": len(events), "last_hash": previous, "event_ids": seen}


def no_vig_probabilities(values: dict[str, Any], odds_format: str) -> tuple[dict[str, float], dict[str, float], float]:
    """Return raw implied probabilities, normalized probabilities, and overround."""
    if not isinstance(values, dict) or set(values) not in ({"h", "a"}, {"h", "d", "a"}):
        raise ValueError("market outcomes must contain exactly h/a or h/d/a")
    raw = {}
    for outcome, value in values.items():
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid market value for {outcome}") from exc
        if not math.isfinite(number):
            raise ValueError(f"invalid market value for {outcome}")
        if odds_format == "decimal":
            if number <= 1.0:
                raise ValueError("decimal odds must be greater than 1")
            raw[outcome] = 1.0 / number
        elif odds_format == "probability":
            if not 0.0 < number < 1.0:
                raise ValueError("probabilities must be strictly between 0 and 1")
            raw[outcome] = number
        else:
            raise ValueError("odds_format must be decimal or probability")
    total = sum(raw.values())
    normalized = {key: value / total for key, value in raw.items()}
    return ({key: round(value, 8) for key, value in raw.items()},
            {key: round(value, 8) for key, value in normalized.items()}, round(total - 1.0, 8))


def _normalize_snapshot(raw: dict[str, Any], recorded: datetime) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("each market snapshot must be an object")
    fixture_id = str(raw.get("fixture_id") or "").strip()
    competition = str(raw.get("competition") or "").strip().upper()
    market_type = str(raw.get("market_type") or "").strip().lower()
    if not fixture_id or not competition or market_type not in {"moneyline", "1x2"}:
        raise ValueError("market snapshot requires fixture_id, competition, and moneyline/1x2 market_type")
    kickoff = _time(raw.get("kickoff"), "kickoff")
    observed = _time(raw.get("observed_at"), "observed_at")
    if recorded >= kickoff:
        raise ValueError(f"market snapshot for {fixture_id} must be recorded before kickoff")
    if observed > recorded:
        raise ValueError(f"market snapshot for {fixture_id} cannot be observed after it is recorded")
    odds_format = str(raw.get("odds_format") or "").strip().lower()
    values = raw.get("outcomes")
    implied, no_vig, overround = no_vig_probabilities(values, odds_format)
    if market_type == "moneyline" and set(no_vig) != {"h", "a"}:
        raise ValueError("moneyline snapshots must be two-way h/a")
    if market_type == "1x2" and set(no_vig) != {"h", "d", "a"}:
        raise ValueError("1x2 snapshots must be three-way h/d/a")
    return {"fixture_id": fixture_id, "competition": competition, "kickoff": _iso(kickoff),
            "observed_at": _iso(observed), "market_type": market_type, "odds_format": odds_format,
            "outcomes": {key: float(values[key]) for key in no_vig},
            "raw_implied_probabilities": implied, "no_vig_probabilities": no_vig,
            "overround": overround, "source_snapshot_id": str(raw.get("source_snapshot_id") or "") or None}


def append_batch(
    path: str | os.PathLike[str], payload: dict[str, Any], recorded_at: str | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("market payload must be an object")
    source = str(payload.get("source") or "").strip()
    authorization = str(payload.get("authorization_basis") or "").strip()
    reference = str(payload.get("source_reference") or "").strip()
    if not source or not reference:
        raise ValueError("market snapshots require source and source_reference provenance")
    if "espn" in f"{source} {reference}".lower():
        raise ValueError("ESPN-origin market snapshots are excluded")
    if authorization not in AUTHORIZATION_BASES:
        raise ValueError("market authorization_basis is missing or unsupported")
    recorded = _time(recorded_at or datetime.now(timezone.utc).isoformat(), "recorded_at")
    fetched = _time(payload.get("fetched_at"), "fetched_at")
    if fetched > recorded:
        raise ValueError("fetched_at cannot be after recorded_at")
    snapshots = [_normalize_snapshot(item, recorded) for item in payload.get("snapshots") or []]
    if not snapshots:
        raise ValueError("market batch has no snapshots")
    snapshots.sort(key=lambda item: (item["fixture_id"], item["market_type"], item["observed_at"]))
    state = validate(path)
    identity = {"source": source, "authorization_basis": authorization, "source_reference": reference,
                "fetched_at": _iso(fetched), "snapshots": snapshots}
    event_id = _digest(identity)
    if event_id in state["event_ids"]:
        return {"created": False, "event_id": event_id, "events": state["events"],
                "last_hash": state["last_hash"]}
    event = {"schema_version": SCHEMA_VERSION, "event_id": event_id, "recorded_at": _iso(recorded),
             "previous_hash": state["last_hash"], "source": source,
             "authorization_basis": authorization, "source_reference": reference,
             "fetched_at": _iso(fetched), "snapshots": snapshots}
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


def fixture_snapshots(path: str | os.PathLike[str], fixture_id: Any, kickoff: Any) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists() or not fixture_id:
        return []
    validate(source)
    fixture_kickoff = _time(kickoff, "kickoff")
    output = []
    for event in read_events(source):
        recorded = _time(event["recorded_at"], "recorded_at")
        for snapshot in event.get("snapshots") or []:
            if (str(snapshot.get("fixture_id")) == str(fixture_id)
                    and _time(snapshot.get("kickoff"), "kickoff") == fixture_kickoff):
                output.append({**snapshot, "recorded_at": _iso(recorded),
                               "event_id": event["event_id"], "source": event["source"]})
    return sorted(output, key=lambda item: (item["observed_at"], item["recorded_at"], item["event_id"]))
