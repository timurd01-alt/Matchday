"""Append-only, tamper-evident research ledger for Matchday forecasts.

The public scorecard JSON remains the application's read model.  This module is
the research event log: an official pregame lock and each materially different
grade are appended once, chained by SHA-256, and never rewritten in place.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64


def _safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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
                raise ValueError(f"invalid forecast ledger JSON on line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"invalid forecast ledger event on line {line_number}")
            events.append(event)
    return events


def validate(path: str | os.PathLike[str]) -> dict[str, Any]:
    previous = GENESIS_HASH
    seen: set[str] = set()
    events = read_events(path)
    for index, event in enumerate(events, 1):
        if event.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported forecast ledger schema on line {index}")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen:
            raise ValueError(f"missing or duplicate forecast ledger event_id on line {index}")
        if event.get("previous_hash") != previous:
            raise ValueError(f"forecast ledger chain break on line {index}")
        claimed = event.get("record_hash")
        material = {key: value for key, value in event.items() if key != "record_hash"}
        actual = _digest(material)
        if claimed != actual:
            raise ValueError(f"forecast ledger hash mismatch on line {index}")
        seen.add(event_id)
        previous = actual
    return {"events": len(events), "last_hash": previous, "event_ids": seen}


def append_event(
    path: str | os.PathLike[str],
    *,
    event_type: str,
    fixture_id: str,
    competition: str,
    effective_at: str | None,
    identity: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Append one deterministic event, or return the existing event on replay."""
    target = Path(path)
    state = validate(target)
    event_id = _digest({
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "fixture_id": str(fixture_id),
        "competition": str(competition),
        "identity": identity,
    })
    if event_id in state["event_ids"]:
        existing = next(event for event in read_events(target) if event.get("event_id") == event_id)
        return existing, False

    record = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "fixture_id": str(fixture_id),
        "competition": str(competition),
        "effective_at": effective_at,
        "previous_hash": state["last_hash"],
        "payload": _safe(payload),
    }
    record["record_hash"] = _digest(record)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(_canonical(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    # Read-after-write validation turns a partial/corrupt append into a failed job.
    validate(target)
    return record, True


def _forecast_payload(rec: dict[str, Any]) -> dict[str, Any]:
    prediction = rec.get("prediction_snapshot") or {}
    inputs = rec.get("input_snapshot") or {}
    match = inputs.get("match") or {}
    return {
        "lock": {
            "locked_at": rec.get("locked_at"),
            "kickoff": rec.get("kickoff"),
            "lead_time_seconds": rec.get("lead_time_seconds"),
            "status_at_lock": rec.get("status_at_lock"),
            "outcome_basis": rec.get("outcome_basis"),
        },
        "participants": {"home": rec.get("home"), "away": rec.get("away")},
        "model": {
            "version": rec.get("model_ver"),
            "code_marker": rec.get("model_code_marker"),
            "independent_probabilities": _safe(prediction.get("model")),
            "market_informed_probabilities": _safe(rec.get("probs")),
            "regulation_probabilities": _safe(rec.get("regulation_probs")),
            "pick": rec.get("pick"),
            "confidence": rec.get("confidence"),
        },
        "features": {
            "factor_snapshot": _safe(rec.get("factor_snapshot")),
            "advanced_metrics": _safe(match.get("advanced_metrics")),
            "data_quality": _safe(prediction.get("data_quality")),
            "mfti_shadow": _safe(rec.get("mfti_shadow")),
        },
        "market": {
            "snapshot": _safe(rec.get("market_snapshot")),
            "snapshot_at": rec.get("market_snapshot_at"),
            "basis": rec.get("market_basis"),
        },
        "provenance": {
            "competition": rec.get("competition"),
            "provider": match.get("data_source"),
            "source_metadata": _safe(match.get("advanced_metrics_meta")),
            "model_signal_schema": match.get("model_signal_schema"),
            "input_snapshot_hash": _digest(inputs),
        },
        "input_snapshot": _safe(inputs),
        "prediction_snapshot": _safe(prediction),
    }


def _grade_payload(rec: dict[str, Any]) -> dict[str, Any]:
    result_snapshot = _safe(rec.get("result_snapshot")) or {}
    return {
        "result": rec.get("result"),
        "model_result": rec.get("model_result"),
        "market_result": rec.get("market_result"),
        "score": rec.get("score"),
        "result_snapshot": result_snapshot,
        "model_hit": rec.get("model_hit"),
        "market_hit": rec.get("market_hit"),
        "value_hit": rec.get("value_hit"),
        "brier3": rec.get("brier3"),
        "log_loss": rec.get("log_loss"),
    }


def sync_pick_records(
    path: str | os.PathLike[str], records: Iterable[dict[str, Any]], competition: str
) -> dict[str, Any]:
    """Reconcile the append-only ledger from the official scorecard read model."""
    appended = 0
    for rec in sorted(records, key=lambda row: (str(row.get("locked_at") or ""), str(row.get("fixture_id") or ""))):
        if not isinstance(rec, dict) or rec.get("integrity_eligible") is not True:
            continue
        fixture_id = str(rec.get("fixture_id") or "")
        if not fixture_id or not isinstance(rec.get("prediction_snapshot"), dict):
            continue
        forecast_payload = _forecast_payload(rec)
        _, created = append_event(
            path,
            event_type="forecast_locked",
            fixture_id=fixture_id,
            competition=competition,
            effective_at=rec.get("locked_at"),
            identity={
                "locked_at": rec.get("locked_at"),
                "input_snapshot_hash": forecast_payload["provenance"]["input_snapshot_hash"],
                "prediction_snapshot_hash": _digest(rec.get("prediction_snapshot")),
            },
            payload=forecast_payload,
        )
        appended += int(created)

        if rec.get("result") not in {"h", "d", "a"}:
            continue
        grade_payload = _grade_payload(rec)
        result_snapshot = grade_payload.get("result_snapshot") or {}
        comparable_result = {key: value for key, value in result_snapshot.items() if key != "observed_at"}
        _, created = append_event(
            path,
            event_type="forecast_graded",
            fixture_id=fixture_id,
            competition=competition,
            effective_at=result_snapshot.get("observed_at"),
            identity={
                "locked_at": rec.get("locked_at"),
                "result": rec.get("result"),
                "market_result": rec.get("market_result"),
                "score": rec.get("score"),
                "result_snapshot": comparable_result,
            },
            payload=grade_payload,
        )
        appended += int(created)
    final = validate(path)
    return {"appended": appended, "events": final["events"], "last_hash": final["last_hash"]}
