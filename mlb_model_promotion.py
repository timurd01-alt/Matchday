"""Controlled, evidence-bound promotion of the frozen MLB challenger."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
POLICY_STATUS = "approved_for_capped_production"
PROTOCOL_VERSION = "mlb-prospective-shadow-1.0.0"
MAX_PRODUCTION_WEIGHT = 0.10
MAX_SHIFT_POINTS = 3.0
MIN_GAMES = 500
MIN_DATE_BLOCKS = 30


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def load_mlb_promotion_policy(
    path: str | Path = "mlb_model_promotion.json",
) -> dict[str, Any] | None:
    """Return an approved policy or ``None`` while evidence is collecting.

    A non-zero policy is accepted only when its committed evidence report has
    enough prospective observations and beats the official model on both
    proper scores with a paired log-loss interval entirely below zero.
    """
    source = Path(path)
    if not source.exists():
        return None
    payload = _read_json(source)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported MLB promotion policy schema: {source}")
    status = str(payload.get("status") or "")
    weight = _finite(payload.get("production_weight"))
    if status != POLICY_STATUS:
        if weight not in {None, 0.0}:
            raise ValueError("an unapproved MLB promotion policy cannot have non-zero weight")
        return None
    if weight is None or not (0.0 < weight <= MAX_PRODUCTION_WEIGHT):
        raise ValueError(f"MLB production weight must be in (0, {MAX_PRODUCTION_WEIGHT}]")
    max_shift = _finite(payload.get("max_shift_points"))
    if max_shift is None or not (0.0 < max_shift <= MAX_SHIFT_POINTS):
        raise ValueError(f"MLB probability shift cap must be in (0, {MAX_SHIFT_POINTS}]")
    if payload.get("signal") != "run_strength_challenger":
        raise ValueError("only the frozen MLB run-strength challenger can be promoted")
    if payload.get("allow_pick_flip") is not False:
        raise ValueError("the first controlled MLB promotion cannot flip the official pick")
    model_version = str(payload.get("model_version") or "")
    if not model_version:
        raise ValueError("approved MLB promotion is missing its model version")

    review = payload.get("manual_review") or {}
    if review.get("decision") != "passed" or not review.get("reviewed_at") or not review.get("reviewer"):
        raise ValueError("approved MLB promotion requires a named, timestamped manual review")
    expected_hash = str(review.get("report_sha256") or "").lower()
    if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
        raise ValueError("approved MLB promotion requires a valid evidence SHA-256")

    root = source.resolve().parent
    evidence_path = (root / str(review.get("report") or "")).resolve()
    if evidence_path.parent != root or not evidence_path.is_file():
        raise ValueError("MLB promotion evidence must be a committed file beside the policy")
    evidence_bytes = evidence_path.read_bytes()
    actual_hash = hashlib.sha256(evidence_bytes).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("MLB promotion evidence hash does not match the reviewed report")
    report = json.loads(evidence_bytes.decode("utf-8"))
    if report.get("protocol_version") != PROTOCOL_VERSION or report.get("status") != "ready_for_frozen_review":
        raise ValueError("MLB promotion evidence has not reached frozen review")
    official = ((report.get("models") or {}).get("official") or {})
    challenger = ((report.get("models") or {}).get("run_strength_challenger") or {})
    comparison = ((report.get("comparisons") or {}).get("run_strength_vs_official") or {})
    interval = comparison.get("ci95") or []
    if int(challenger.get("n") or 0) < MIN_GAMES or int(comparison.get("blocks") or 0) < MIN_DATE_BLOCKS:
        raise ValueError("MLB promotion evidence has insufficient prospective coverage")
    if len(interval) != 2 or _finite(interval[1]) is None or float(interval[1]) >= 0:
        raise ValueError("MLB challenger log-loss interval does not beat the official model")
    for metric in ("log_loss", "brier"):
        candidate_value = _finite(challenger.get(metric))
        official_value = _finite(official.get(metric))
        if candidate_value is None or official_value is None or candidate_value >= official_value:
            raise ValueError(f"MLB challenger does not improve prospective {metric}")

    approved = dict(payload)
    approved["verified_report_sha256"] = actual_hash
    return approved


def apply_mlb_promotion(
    match: dict[str, Any], prediction: dict[str, Any], policy: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Blend a reviewed shadow probability into the official two-way forecast."""
    if not policy:
        return None
    shadow = match.get("mlb_challenger_shadow") or {}
    if (shadow.get("mode") != "prospective_shadow"
            or shadow.get("production_weight") != 0
            or shadow.get("model_version") != policy.get("model_version")):
        raise ValueError("live MLB shadow does not match the approved frozen model")
    shadow_home = _finite(shadow.get("home_win_probability"))
    probabilities = prediction.get("adjusted") or prediction.get("regulation_probs") or {}
    official_home = _finite(probabilities.get("h"))
    official_away = _finite(probabilities.get("a"))
    if shadow_home is None or not (0.0 < shadow_home < 1.0) or official_home is None or official_away is None:
        return None
    if official_home + official_away <= 0:
        return None
    official_home = 100.0 * official_home / (official_home + official_away)
    weight = float(policy["production_weight"])
    cap = float(policy["max_shift_points"])
    raw_shift = weight * (shadow_home * 100.0 - official_home)
    applied_shift = max(-cap, min(cap, raw_shift))
    promoted_home = official_home + applied_shift
    # The first controlled stage may recalibrate confidence but cannot reverse
    # the published side. A later policy version can define a separate flip gate.
    if official_home >= 50.0:
        promoted_home = max(51.0, promoted_home)
    else:
        promoted_home = min(49.0, promoted_home)
    promoted_home = max(1, min(99, int(round(promoted_home))))
    promoted_away = 100 - promoted_home
    pick = "h" if promoted_home >= 50 else "a"
    pick_name = (match.get("home") or {}).get("name") if pick == "h" else (match.get("away") or {}).get("name")

    pre_promotion = {"h": int(round(official_home)), "d": 0, "a": int(round(100 - official_home))}
    promoted = {"h": promoted_home, "d": 0, "a": promoted_away}
    prediction["adjusted"] = dict(promoted)
    prediction["regulation_probs"] = dict(promoted)
    prediction["pick"] = pick
    prediction["pick_name"] = pick_name
    prediction["confidence"] = promoted[pick]
    prediction["regulation_pick"] = pick
    prediction["regulation_pick_name"] = pick_name
    prediction["regulation_confidence"] = promoted[pick]
    receipt = {
        "schema_version": 1, "signal": policy["signal"], "model_version": policy["model_version"],
        "production_weight": weight, "max_shift_points": cap, "pick_flip_allowed": False,
        "official_before": pre_promotion, "official_after": promoted,
        "shadow_home_probability": round(shadow_home, 6),
        "raw_shift_points": round(raw_shift, 3),
        "applied_shift_points": round(promoted_home - official_home, 3),
        "evidence_sha256": policy["verified_report_sha256"],
    }
    prediction["research_promotion"] = receipt
    return receipt
