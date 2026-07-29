"""Evidence-bound capped use of the NFL calibrated-Elo signal."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS = "approved_for_capped_historical_pilot"
MAX_WEIGHT = 0.10
MAX_SHIFT_POINTS = 3.0
MIN_OOS_GAMES = 500


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_nfl_adjustment_policy(
    path: str | Path = "nfl_model_adjustment.json",
) -> dict[str, Any] | None:
    source = Path(path)
    if not source.exists():
        return None
    policy = json.loads(source.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ValueError("unsupported NFL adjustment policy schema")
    if policy.get("status") != STATUS:
        if policy.get("production_weight") not in {None, 0, 0.0}:
            raise ValueError("inactive NFL adjustment policy cannot have non-zero weight")
        return None
    if policy.get("signal") != "calibrated_elo" or policy.get("basis") != "historical_oos_pilot":
        raise ValueError("only calibrated Elo may enter the historical NFL pilot")
    weight, cap = _finite(policy.get("production_weight")), _finite(policy.get("max_shift_points"))
    if weight is None or not (0 < weight <= MAX_WEIGHT):
        raise ValueError("NFL adjustment exceeds the 10% production-weight cap")
    if cap is None or not (0 < cap <= MAX_SHIFT_POINTS):
        raise ValueError("NFL adjustment exceeds the three-point probability cap")
    if policy.get("allow_pick_flip") is not False:
        raise ValueError("the historical NFL pilot cannot flip an official pick")
    if not policy.get("approved_at") or not policy.get("approved_by"):
        raise ValueError("NFL adjustment requires an explicit dated owner approval")

    report_path = (source.resolve().parent / str(policy.get("evidence_report") or "")).resolve()
    if report_path.parent != source.resolve().parent or not report_path.is_file():
        raise ValueError("NFL adjustment evidence must be committed beside the policy")
    evidence = report_path.read_bytes()
    digest = hashlib.sha256(evidence).hexdigest()
    if digest != str(policy.get("evidence_sha256") or "").lower():
        raise ValueError("NFL adjustment evidence hash mismatch")
    report = json.loads(evidence.decode("utf-8"))
    full = report.get("full") or {}
    calibrated, raw = full.get("calibrated_elo") or {}, full.get("raw_elo") or {}
    interval = (full.get("elo_calibration_paired_bootstrap") or {}).get("ci95") or []
    if int(calibrated.get("n") or 0) < MIN_OOS_GAMES:
        raise ValueError("NFL calibrated Elo has insufficient out-of-sample coverage")
    if not (float(calibrated["log_loss"]) < float(raw["log_loss"])
            and float(calibrated["brier"]) < float(raw["brier"])):
        raise ValueError("NFL calibrated Elo did not improve both proper scores")
    if len(interval) != 2 or _finite(interval[1]) is None or float(interval[1]) >= 0:
        raise ValueError("NFL calibrated-Elo improvement interval includes no improvement")
    approved = dict(policy)
    approved["verified_evidence_sha256"] = digest
    approved["historical_oos_games"] = int(calibrated["n"])
    return approved


def _more_than_twelve_hours_before_kickoff(match: dict[str, Any]) -> bool:
    try:
        kickoff = datetime.fromisoformat(str(match.get("kickoff")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (kickoff - datetime.now(timezone.utc)).total_seconds() > 12 * 3600


def apply_nfl_adjustment(
    match: dict[str, Any], prediction: dict[str, Any], policy: dict[str, Any] | None,
    *, allow_inside_lock_window: bool = True,
) -> dict[str, Any] | None:
    if not policy:
        return None
    existing = prediction.get("research_promotion") or {}
    if (existing.get("signal") == "calibrated_elo"
            and existing.get("evidence_sha256") == policy.get("verified_evidence_sha256")):
        return existing
    if not allow_inside_lock_window and not _more_than_twelve_hours_before_kickoff(match):
        return None
    shadow = match.get("nfl_challenger_shadow") or {}
    if (shadow.get("mode") != "research_only" or shadow.get("production_weight") != 0
            or shadow.get("model_version") != policy.get("model_version")
            or shadow.get("elo_calibration_status") != "eligible_for_prospective_shadow"):
        raise ValueError("live NFL calibrated-Elo shadow does not match the approved artifact")
    calibrated = _finite(shadow.get("calibrated_elo_home_probability"))
    probabilities = prediction.get("adjusted") or prediction.get("regulation_probs") or {}
    home, away = _finite(probabilities.get("h")), _finite(probabilities.get("a"))
    if calibrated is None or home is None or away is None or home + away <= 0:
        return None
    before_home = 100.0 * home / (home + away)
    raw_shift = float(policy["production_weight"]) * (calibrated * 100.0 - before_home)
    applied = max(-float(policy["max_shift_points"]), min(float(policy["max_shift_points"]), raw_shift))
    after_home = before_home + applied
    if before_home >= 50:
        after_home = max(51.0, after_home)
    else:
        after_home = min(49.0, after_home)
    after_home = max(1, min(99, int(round(after_home))))
    after = {"h": after_home, "d": 0, "a": 100 - after_home}
    pick = "h" if before_home >= 50 else "a"
    pick_name = (match.get("home") or {}).get("name") if pick == "h" else (match.get("away") or {}).get("name")
    prediction["adjusted"] = dict(after)
    prediction["regulation_probs"] = dict(after)
    prediction["pick"] = pick; prediction["regulation_pick"] = pick
    prediction["pick_name"] = pick_name; prediction["regulation_pick_name"] = pick_name
    prediction["confidence"] = after[pick]; prediction["regulation_confidence"] = after[pick]
    receipt = {"schema_version": 1, "signal": "calibrated_elo",
               "model_version": policy["model_version"], "promotion_basis": policy["basis"],
               "production_weight": float(policy["production_weight"]),
               "max_shift_points": float(policy["max_shift_points"]), "pick_flip_allowed": False,
               "official_before": {"h": round(before_home), "d": 0, "a": round(100 - before_home)},
               "official_after": after, "calibrated_elo_home_probability": round(calibrated, 6),
               "raw_shift_points": round(raw_shift, 3),
               "applied_shift_points": round(after_home - before_home, 3),
               "historical_oos_games": policy["historical_oos_games"],
               "prospective_status": policy.get("prospective_status"),
               "evidence_sha256": policy["verified_evidence_sha256"]}
    prediction["research_promotion"] = receipt
    return receipt
