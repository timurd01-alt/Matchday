"""Controlled, evidence-bound promotion of the frozen MLB challenger."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
POLICY_STATUS = "approved_for_capped_production"
PROTOCOL_VERSION = "mlb-prospective-shadow-1.0.0"
MAX_PRODUCTION_WEIGHT = 0.10
MAX_SHIFT_POINTS = 3.0
MIN_GAMES = 500
MIN_DATE_BLOCKS = 30
COHORT_FIELDS = ("model_version", "trained_through", "artifact_sha256",
                 "feature_schema_version", "transformation_version")


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


def _cohort(payload: dict[str, Any], label: str) -> dict[str, str]:
    cohort = {}
    for field in COHORT_FIELDS:
        value = str(payload.get(field) or "")
        if not value:
            raise ValueError(f"{label} is missing cohort field {field}")
        cohort[field] = value
    digest = cohort["artifact_sha256"].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{label} has an invalid artifact_sha256")
    cohort["artifact_sha256"] = digest
    return cohort


def _require_same_cohort(actual: dict[str, Any], expected: dict[str, str], label: str) -> None:
    if _cohort(actual, label) != expected:
        raise ValueError(f"{label} does not match the approved frozen cohort")


def _baseline_cohort(payload: dict[str, Any], label: str) -> dict[str, Any]:
    model_version = str(payload.get("model_version") or "")
    signal_schema = payload.get("model_signal_schema")
    if not model_version:
        raise ValueError(f"{label} is missing baseline model_version")
    if isinstance(signal_schema, bool) or not isinstance(signal_schema, int) or signal_schema < 1:
        raise ValueError(f"{label} has an invalid baseline model_signal_schema")
    return {"model_version": model_version, "model_signal_schema": signal_schema}


def _require_same_baseline(row: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    actual = {
        "model_version": row.get("baseline_model_version"),
        "model_signal_schema": row.get("baseline_model_signal_schema"),
    }
    if _baseline_cohort(actual, label) != expected:
        raise ValueError(f"{label} does not match the approved incumbent baseline cohort")


def _log_loss(probability: float, outcome: int) -> float:
    probability = min(max(probability, 1e-12), 1.0 - 1e-12)
    return -(outcome * math.log(probability) + (1 - outcome) * math.log(1.0 - probability))


def _deployable_probability(official: float, challenger: float, weight: float,
                            cap_points: float) -> float:
    official_points = official * 100.0
    raw_shift = weight * (challenger * 100.0 - official_points)
    lower, upper = max(1.0, official_points - cap_points), min(99.0, official_points + cap_points)
    promoted = max(lower, min(upper, official_points + raw_shift))
    promoted = (max(50.0, promoted) if official_points >= 50.0
                else min(math.nextafter(50.0, -math.inf), promoted))
    return max(lower, min(upper, promoted)) / 100.0


def _recompute_evidence(rows: list[dict[str, Any]], weight: float,
                        cap_points: float, expected_cohort: dict[str, str],
                        expected_baseline: dict[str, Any]) -> dict[str, Any]:
    """Validate immutable rows and independently reproduce every promotion metric."""
    seen_fixtures, seen_locks, seen_grades = set(), set(), set()
    grouped: dict[str, list[float]] = defaultdict(list)
    official_losses, capped_losses = [], []
    official_brier = capped_brier = 0.0
    canonical_rows = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"MLB evidence row {index} is not an object")
        _require_same_cohort(row, expected_cohort, f"MLB evidence row {index}")
        _require_same_baseline(row, expected_baseline, f"MLB evidence row {index}")
        fixture_id = str(row.get("fixture_id") or "")
        lock_event_id = str(row.get("lock_event_id") or "")
        grade_event_id = str(row.get("grade_event_id") or "")
        if not fixture_id or not lock_event_id or not grade_event_id:
            raise ValueError(f"MLB evidence row {index} is missing immutable event identity")
        if fixture_id in seen_fixtures or lock_event_id in seen_locks or grade_event_id in seen_grades:
            raise ValueError(f"MLB evidence row {index} duplicates immutable event identity")
        seen_fixtures.add(fixture_id)
        seen_locks.add(lock_event_id)
        seen_grades.add(grade_event_id)
        outcome = row.get("home_win")
        if isinstance(outcome, bool) or not isinstance(outcome, int) or outcome not in {0, 1}:
            raise ValueError(f"MLB evidence row {index} has an impossible outcome")
        official = _finite(row.get("official_home_probability"))
        challenger = _finite(row.get("challenger_home_probability"))
        reported_capped = _finite(row.get("capped_blend_home_probability"))
        if any(value is None or not (0.0 < value < 1.0)
               for value in (official, challenger, reported_capped)):
            raise ValueError(f"MLB evidence row {index} has an impossible probability")
        expected_capped = _deployable_probability(official, challenger, weight, cap_points)
        if reported_capped != expected_capped:
            raise ValueError(f"MLB evidence row {index} has a fabricated capped-blend probability")
        date_block = str(row.get("date_block") or "")
        try:
            date.fromisoformat(date_block)
        except ValueError as exc:
            raise ValueError(f"MLB evidence row {index} has an invalid date block") from exc
        official_loss = _log_loss(official, outcome)
        capped_loss = _log_loss(expected_capped, outcome)
        delta = capped_loss - official_loss
        official_losses.append(official_loss)
        capped_losses.append(capped_loss)
        official_brier += (official - outcome) ** 2
        capped_brier += (expected_capped - outcome) ** 2
        grouped[date_block].append(delta)
        canonical_rows.append((fixture_id, lock_event_id, expected_capped, official, outcome))
    count = len(rows)
    blocks = sorted(grouped)
    deltas = [value for block in blocks for value in grouped[block]]
    comparison = {"n": count, "blocks": len(blocks),
                  "mean_log_loss_delta": round(sum(deltas) / count, 6),
                  "ci95": [None, None]}
    if len(blocks) >= 2:
        seed_material = "|".join(
            f"{fixture}:{candidate}:{official}:{outcome}"
            for fixture, lock, candidate, official, outcome
            in sorted(canonical_rows, key=lambda item: (item[0], item[1]))
        )
        rng = random.Random(int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16))
        estimates = []
        for _ in range(4000):
            draw = [rng.choice(blocks) for _ in blocks]
            values = [delta for block in draw for delta in grouped[block]]
            estimates.append(sum(values) / len(values))
        estimates.sort()
        comparison["ci95"] = [round(estimates[100], 6), round(estimates[3900], 6)]
    return {
        "official": {"n": count, "log_loss": round(sum(official_losses) / count, 6),
                     "brier": round(official_brier / count, 6)},
        "capped_blend": {"n": count, "log_loss": round(sum(capped_losses) / count, 6),
                         "brier": round(capped_brier / count, 6)},
        "comparison": comparison,
    }


def _require_summary_matches(reported: dict[str, Any], recomputed: dict[str, Any],
                             fields: tuple[str, ...], label: str) -> None:
    for field in fields:
        actual, expected = reported.get(field), recomputed.get(field)
        if field in {"n", "blocks"}:
            if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
                raise ValueError(f"{label} {field} does not match immutable evidence rows")
        elif _finite(actual) is None or not math.isclose(float(actual), float(expected),
                                                         rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"{label} {field} does not match immutable evidence rows")


def load_mlb_promotion_policy(path: str | Path = "mlb_model_promotion.json") -> dict[str, Any] | None:
    """Return a reviewed policy only for the exact deployable blend/cohort."""
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
    expected_cohort = _cohort(payload, "approved MLB policy")
    expected_baseline = _baseline_cohort(payload.get("baseline_cohort") or {},
                                         "approved MLB policy")

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
    _require_same_cohort(report.get("cohort") or {}, expected_cohort, "MLB evidence cohort")
    if _baseline_cohort(report.get("baseline_cohort") or {}, "MLB evidence baseline cohort") != expected_baseline:
        raise ValueError("MLB evidence baseline cohort does not match the approved incumbent")

    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) < MIN_GAMES:
        raise ValueError("MLB promotion evidence has insufficient prospective coverage")

    deployment = report.get("deployment_evaluation") or {}
    configuration = deployment.get("policy") or {}
    if (_finite(configuration.get("production_weight")) != weight
            or _finite(configuration.get("max_shift_points")) != max_shift
            or configuration.get("allow_pick_flip") is not False
            or configuration.get("probability_rounding") != "none"):
        raise ValueError("MLB evidence did not evaluate the exact deployable capped blend")
    recomputed = _recompute_evidence(rows, weight, max_shift, expected_cohort, expected_baseline)
    models = deployment.get("models") or {}
    official, capped = models.get("official") or {}, models.get("capped_blend") or {}
    comparison = ((deployment.get("comparisons") or {}).get("capped_blend_vs_official") or {})
    _require_summary_matches(official, recomputed["official"], ("n", "log_loss", "brier"),
                             "MLB official summary")
    _require_summary_matches(capped, recomputed["capped_blend"], ("n", "log_loss", "brier"),
                             "MLB capped-blend summary")
    _require_summary_matches(comparison, recomputed["comparison"],
                             ("n", "blocks", "mean_log_loss_delta"),
                             "MLB capped-blend comparison")
    interval = comparison.get("ci95") or []
    expected_interval = recomputed["comparison"]["ci95"]
    if (not isinstance(interval, list) or len(interval) != 2
            or any(_finite(value) is None for value in interval)
            or any(not math.isclose(float(value), float(expected), rel_tol=0.0, abs_tol=1e-9)
                   for value, expected in zip(interval, expected_interval))):
        raise ValueError("MLB capped-blend CI does not match immutable evidence rows")
    sample_sizes = [int(official.get("n") or 0), int(capped.get("n") or 0),
                    int(comparison.get("n") or 0), len(rows)]
    if min(sample_sizes) < MIN_GAMES or len(set(sample_sizes)) != 1:
        raise ValueError("MLB deployable blend evidence has inconsistent prospective coverage")
    if int(comparison.get("blocks") or 0) < MIN_DATE_BLOCKS:
        raise ValueError("MLB promotion evidence has insufficient prospective date blocks")
    if len(interval) != 2 or _finite(interval[1]) is None or float(interval[1]) >= 0:
        raise ValueError("MLB capped blend log-loss interval does not beat the official model")
    for metric in ("log_loss", "brier"):
        candidate_value, official_value = _finite(capped.get(metric)), _finite(official.get(metric))
        if candidate_value is None or official_value is None or candidate_value >= official_value:
            raise ValueError(f"MLB capped blend does not improve prospective {metric}")

    approved = dict(payload)
    approved["verified_report_sha256"] = actual_hash
    approved["verified_cohort"] = expected_cohort
    approved["verified_baseline_cohort"] = expected_baseline
    return approved


def apply_mlb_promotion(match: dict[str, Any], prediction: dict[str, Any],
                        policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """Blend the reviewed shadow while enforcing the final probability cap."""
    if not policy:
        return None
    expected_cohort = _cohort(policy, "approved MLB policy")
    shadow = match.get("mlb_challenger_shadow") or {}
    if shadow.get("mode") != "prospective_shadow" or shadow.get("production_weight") != 0:
        raise ValueError("live MLB shadow is not a frozen prospective shadow")
    _require_same_cohort(shadow, expected_cohort, "live MLB shadow")
    shadow_home = _finite(shadow.get("home_win_probability"))
    probabilities = prediction.get("adjusted") or prediction.get("regulation_probs") or {}
    official_home, official_away = _finite(probabilities.get("h")), _finite(probabilities.get("a"))
    if shadow_home is None or not (0.0 < shadow_home < 1.0) or official_home is None or official_away is None:
        return None
    if official_home + official_away <= 0:
        return None
    official_home = 100.0 * official_home / (official_home + official_away)
    weight, cap = float(policy["production_weight"]), float(policy["max_shift_points"])
    raw_shift = weight * (shadow_home * 100.0 - official_home)
    lower, upper = max(1.0, official_home - cap), min(99.0, official_home + cap)
    promoted_home = max(lower, min(upper, official_home + raw_shift))
    # Apply no-flip first, then the final cap. Retaining floats avoids an
    # integer-rounding step that can cross either boundary near 50 or the cap.
    if official_home >= 50.0:
        promoted_home = max(50.0, promoted_home)
    else:
        promoted_home = min(math.nextafter(50.0, -math.inf), promoted_home)
    promoted_home = max(lower, min(upper, promoted_home))
    promoted_away = 100.0 - promoted_home
    if abs(promoted_home - official_home) > cap + 1e-12:
        raise AssertionError("final MLB promotion probability exceeded its shift cap")
    pick = "h" if promoted_home >= 50.0 else "a"
    pick_name = (match.get("home") or {}).get("name") if pick == "h" else (match.get("away") or {}).get("name")
    pre_promotion = {"h": official_home, "d": 0, "a": 100.0 - official_home}
    promoted = {"h": promoted_home, "d": 0, "a": promoted_away}
    prediction["adjusted"] = dict(promoted)
    prediction["regulation_probs"] = dict(promoted)
    prediction["pick"], prediction["pick_name"] = pick, pick_name
    prediction["confidence"] = promoted[pick]
    prediction["regulation_pick"], prediction["regulation_pick_name"] = pick, pick_name
    prediction["regulation_confidence"] = promoted[pick]
    receipt = {
        "schema_version": 1, "signal": policy["signal"], "model_version": policy["model_version"],
        "production_weight": weight, "max_shift_points": cap, "pick_flip_allowed": False,
        "official_before": pre_promotion, "official_after": promoted,
        "shadow_home_probability": shadow_home, "raw_shift_points": raw_shift,
        "applied_shift_points": promoted_home - official_home,
        "evidence_sha256": policy["verified_report_sha256"], "cohort": expected_cohort,
    }
    prediction["research_promotion"] = receipt
    return receipt
