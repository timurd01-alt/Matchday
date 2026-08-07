"""Shared validation for immutable Matchday official-pick receipts."""

from __future__ import annotations

import datetime as dt


PICK_SCHEMA_VERSION = 2
MODEL_CODE_MARKER = "matchday-predictor-integrity-2026-07"
LEGACY_LOCK_WINDOW_HOURS = 12.0


def parse_utc(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def is_official_pick_record(
    record: object,
    *,
    schema_version: int = PICK_SCHEMA_VERSION,
    model_code_marker: str = MODEL_CODE_MARKER,
    default_lock_window_hours: float = LEGACY_LOCK_WINDOW_HOURS,
) -> bool:
    """Return true only for a receipt with verifiable pregame provenance."""
    if not isinstance(record, dict):
        return False
    try:
        lead = float(record.get("lead_time_seconds"))
        lock_hours = float(record.get("lock_window_hours", default_lock_window_hours))
    except (TypeError, ValueError):
        return False
    locked_at = parse_utc(record.get("locked_at"))
    kickoff = parse_utc(record.get("kickoff"))
    if locked_at is None or kickoff is None:
        return False
    calculated_lead = (kickoff - locked_at).total_seconds()
    return bool(
        record.get("schema_ver") == schema_version
        and record.get("model_code_marker") == model_code_marker
        and record.get("fixture_id")
        and record.get("integrity_eligible") is True
        and record.get("integrity_status") == "verified"
        and record.get("status_at_lock") == "UPCOMING"
        and 0 <= lead <= lock_hours * 3600
        and abs(calculated_lead - lead) <= 1.0
        and isinstance(record.get("prediction_snapshot"), dict)
        and isinstance(record.get("input_snapshot"), dict)
    )
