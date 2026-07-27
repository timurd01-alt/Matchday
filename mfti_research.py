"""Shadow-mode implementation of the Matchday Forecast Trust Index (MFTI).

Research contract:
- never changes a forecast;
- never invents an unavailable component;
- returns ``score=None`` until both pillars are complete;
- accepts scenario/availability/freshness/independent-model inputs only when
  they were explicitly captured before kickoff.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


# 0.1.1 corrects the stability normalizer only (see _stability); the frozen
# 0.1 architecture -- weights, exponents, the negative power mean and the
# withheld Evidence pillar -- is unchanged. Bumped rather than edited in place
# because receipts carry this string, and a "frozen" spec whose maths changed
# silently would make its own audit trail meaningless. Safe to correct now:
# no confirmatory evaluation has run and no scored receipt exists yet.
SPEC_VERSION = "MFTI-0.1.1-shadow"
OUTCOMES = ("h", "d", "a")
FLOOR = 0.05


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _probabilities(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    keys = [key for key in OUTCOMES if raw.get(key) is not None]
    if not keys or any(float(raw[key]) < 0 for key in keys):
        return None
    total = sum(float(raw[key]) for key in keys)
    if total <= 0:
        return None
    return {key: float(raw[key]) / total for key in keys}


def _kl(left: dict[str, float], right: dict[str, float]) -> float:
    value = 0.0
    for key, probability in left.items():
        if probability > 0:
            value += probability * math.log(probability / max(1e-15, right.get(key, 0.0)))
    return value


def _stability(vectors: list[dict[str, float]], weights: list[float]) -> dict[str, Any] | None:
    """Normalize weighted JSD onto [0, 1] against its true upper bound.

    Weighted JSD is bounded by BOTH log(outcome count) and H(weights), and the
    binding constraint is whichever is smaller.  Dividing by log(outcome count)
    alone left a floor under the score whenever H(weights) was smaller: two
    equally weighted, maximally opposed scenarios over a three-way soccer
    market could never score below 0.369, while the same total disagreement in
    a two-way market scored 0.0.  "Stability" therefore meant something
    different per sport, which would bias the index across competitions rather
    than measure anything about them.

    Returns None when the comparison is degenerate, so callers can report the
    component missing instead of inventing a score.
    """
    divergence = weighted_jsd(vectors, weights)
    if divergence is None:
        return None
    outcome_count = len(vectors[0])
    # A one-outcome "distribution" is an incomplete forecast, not a stable one.
    # Rule 4 of the protocol: absence never earns a perfect score.
    if outcome_count < 2:
        return None
    total_weight = sum(max(0.0, float(weight)) for weight in weights)
    if total_weight <= 0:
        return None
    shares = [max(0.0, float(weight)) / total_weight for weight in weights]
    weight_entropy = -sum(share * math.log(share) for share in shares if share > 0)
    bound = min(math.log(outcome_count), weight_entropy)
    # bound == 0 means a single scenario carries all the weight: there is no
    # second forecast to disagree with, so there is nothing to measure.
    if bound <= 0:
        return None
    return {"score": _clamp(1.0 - divergence / bound), "weighted_jsd": divergence}


def weighted_jsd(vectors: list[dict[str, float]], weights: list[float]) -> float | None:
    if len(vectors) < 2 or len(vectors) != len(weights):
        return None
    keys = set(vectors[0])
    if not keys or any(set(vector) != keys for vector in vectors):
        return None
    total_weight = sum(max(0.0, float(weight)) for weight in weights)
    if total_weight <= 0:
        return None
    normalized_weights = [max(0.0, float(weight)) / total_weight for weight in weights]
    mixture = {
        key: sum(weight * vector[key] for weight, vector in zip(normalized_weights, vectors))
        for key in keys
    }
    return sum(
        weight * _kl(vector, mixture)
        for weight, vector in zip(normalized_weights, vectors)
    )


def scenario_stability(raw_scenarios: Any) -> dict[str, Any]:
    if not isinstance(raw_scenarios, list):
        return _missing("scenario_forecasts_not_captured")
    vectors: list[dict[str, float]] = []
    weights: list[float] = []
    labels: list[str] = []
    for index, scenario in enumerate(raw_scenarios):
        if not isinstance(scenario, dict):
            continue
        vector = _probabilities(scenario.get("probabilities"))
        if vector is None:
            continue
        vectors.append(vector)
        weights.append(float(scenario.get("probability", 1.0)))
        labels.append(str(scenario.get("label") or f"scenario_{index + 1}"))
    stability = _stability(vectors, weights)
    if stability is None:
        return _missing("at_least_two_compatible_scenarios_required")
    maximum_swing = max(
        abs(left[key] - right[key])
        for left in vectors for right in vectors for key in left
    )
    return {
        "available": True,
        "score": round(stability["score"], 6),
        "weighted_jsd": round(stability["weighted_jsd"], 8),
        "maximum_probability_swing": round(maximum_swing, 6),
        "scenario_count": len(vectors),
        "labels": labels,
    }


def weighted_certainty(items: Any, missing_reason: str) -> dict[str, Any]:
    if not isinstance(items, list) or not items:
        return _missing(missing_reason)
    numerator = denominator = 0.0
    accepted = 0
    for item in items:
        if not isinstance(item, dict) or item.get("certainty") is None:
            continue
        weight = max(0.0, float(item.get("importance", 0.0)))
        numerator += weight * _clamp(float(item["certainty"]))
        denominator += weight
        accepted += 1
    if denominator <= 0:
        return _missing("positive_predeclared_importance_weights_required")
    return {"available": True, "score": round(numerator / denominator, 6), "item_count": accepted}


def freshness_score(items: Any) -> dict[str, Any]:
    if not isinstance(items, list) or not items:
        return _missing("input_freshness_not_captured")
    numerator = denominator = 0.0
    accepted = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        required = ("importance", "coverage", "age_hours", "half_life_hours")
        if any(item.get(key) is None for key in required):
            continue
        weight = max(0.0, float(item["importance"]))
        half_life = float(item["half_life_hours"])
        if half_life <= 0:
            continue
        contribution = _clamp(float(item["coverage"])) * 2 ** (
            -max(0.0, float(item["age_hours"])) / half_life
        )
        numerator += weight * contribution
        denominator += weight
        accepted += 1
    if denominator <= 0:
        return _missing("valid_freshness_items_required")
    return {"available": True, "score": round(numerator / denominator, 6), "item_count": accepted}


def independent_model_stability(items: Any) -> dict[str, Any]:
    if not isinstance(items, list):
        return _missing("independent_model_outputs_not_captured")
    vectors: list[dict[str, float]] = []
    weights: list[float] = []
    families: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("independent") is not True:
            continue
        vector = _probabilities(item.get("probabilities"))
        if vector is None:
            continue
        vectors.append(vector)
        weights.append(max(0.0, float(item.get("weight", 1.0))))
        families.append(str(item.get("family") or "unnamed"))
    stability = _stability(vectors, weights)
    if stability is None:
        return _missing("two_explicitly_independent_model_families_required")
    return {
        "available": True,
        "score": round(stability["score"], 6),
        "weighted_jsd": round(stability["weighted_jsd"], 8),
        "model_count": len(vectors),
        "families": families,
    }


def event_readiness(components: dict[str, dict[str, Any]]) -> dict[str, Any]:
    weights = {"scenario_stability": 0.35, "availability": 0.25,
               "freshness": 0.20, "model_stability": 0.20}
    unavailable = [key for key in weights if not components[key].get("available")]
    if unavailable:
        return {"available": False, "score": None, "missing_components": unavailable}
    denominator = sum(
        weight * max(FLOOR, float(components[key]["score"])) ** -2
        for key, weight in weights.items()
    )
    return {"available": True, "score": round(denominator ** -0.5, 6), "missing_components": []}


def historical_evidence(history: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Capture reconstructible evidence without pretending MFTI is calibrated.

    MFTI 0.1 deliberately withholds a normalized Evidence score until frozen
    development thresholds and an out-of-sample calibrator exist.
    """
    brier_values: list[float] = []
    log_values: list[float] = []
    uniform_brier: list[float] = []
    uniform_log: list[float] = []
    for record in history:
        result = record.get("result")
        vector = _probabilities(record.get("regulation_probs") or record.get("probs"))
        if vector is None or result not in vector:
            continue
        outcome = {key: float(key == result) for key in vector}
        brier_values.append(sum((vector[key] - outcome[key]) ** 2 for key in vector))
        log_values.append(-math.log(max(1e-15, vector[result])))
        uniform = 1.0 / len(vector)
        uniform_brier.append(sum((uniform - outcome[key]) ** 2 for key in vector))
        uniform_log.append(-math.log(uniform))
    n = len(brier_values)
    metrics: dict[str, Any] = {"eligible_prior_forecasts": n}
    if n:
        metrics.update({
            "mean_brier": round(sum(brier_values) / n, 6),
            "mean_log_loss": round(sum(log_values) / n, 6),
            "brier_skill_vs_uniform": round(1.0 - sum(brier_values) / sum(uniform_brier), 6),
            "log_skill_vs_uniform": round(1.0 - sum(log_values) / sum(uniform_log), 6),
        })
    return {
        "available": False,
        "score": None,
        "reason": "frozen_normalization_and_rolling_recalibration_not_fitted",
        "diagnostics": metrics,
    }


def build_shadow_receipt(
    match: dict[str, Any], prediction: dict[str, Any], history: Iterable[dict[str, Any]], locked_at: str
) -> dict[str, Any]:
    research = match.get("mfti_inputs") if isinstance(match.get("mfti_inputs"), dict) else {}
    scenarios = research.get("scenario_forecasts") or prediction.get("scenario_forecasts")
    components = {
        "scenario_stability": scenario_stability(scenarios),
        "availability": weighted_certainty(
            research.get("availability"), "availability_probabilities_not_captured"
        ),
        "freshness": freshness_score(research.get("freshness")),
        "model_stability": independent_model_stability(research.get("independent_models")),
    }
    evidence = historical_evidence(history)
    readiness = event_readiness(components)
    score = None
    status = "incomplete"
    if evidence.get("available") and readiness.get("available"):
        score = round(100.0 * float(evidence["score"]) ** 0.60 * float(readiness["score"]) ** 0.40, 2)
        status = "complete"
    missing = []
    if not evidence.get("available"):
        missing.append("historical_evidence")
    missing.extend(readiness.get("missing_components") or [])
    return {
        "spec_version": SPEC_VERSION,
        "mode": "shadow_research_only",
        "captured_at": locked_at,
        "status": status,
        "score": score,
        "historical_evidence": evidence,
        "event_readiness": readiness,
        "components": components,
        "missing_components": missing,
        "affects_prediction": False,
        "user_visible": False,
    }


def _missing(reason: str) -> dict[str, Any]:
    return {"available": False, "score": None, "reason": reason}
