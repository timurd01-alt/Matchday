"""L2-regularised logistic regression shared by the college challengers.

Pure Python and deterministic, so a challenger's backtest is reproducible
from its rows alone. Rows carry `features`, an `outcome` of 0.0 or 1.0 and an
`eligible` flag; an optional baseline probability enters as a fixed offset, so
the fit learns a correction to it rather than replacing it.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + exp)
    exp = math.exp(max(value, -40.0))
    return exp / (1.0 + exp)


def fit_logistic(rows: Sequence[dict[str, Any]], feature_names: Sequence[str],
                 l2: float = 5.0, iterations: int = 300, learning_rate: float = 0.12,
                 baseline_probability_key: str | None = None) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("eligible") and row.get("outcome") in (0.0, 1.0)]
    if len(eligible) < 2:
        raise ValueError("at least two eligible rows are required")
    names = list(feature_names)
    means, scales = {}, {}
    for name in names:
        values = [float(row["features"].get(name, 0.0)) for row in eligible]
        means[name] = sum(values) / len(values)
        variance = sum((value - means[name]) ** 2 for value in values) / len(values)
        scales[name] = math.sqrt(variance) if variance > 1e-12 else 1.0
    positives = sum(row["outcome"] for row in eligible)
    prior = min(0.99, max(0.01, positives / len(eligible)))
    intercept = 0.0 if baseline_probability_key else math.log(prior / (1.0 - prior))
    matrix = [[(float(row["features"].get(name, 0.0)) - means[name]) / scales[name] for name in names]
              for row in eligible]
    outcomes = [float(row["outcome"]) for row in eligible]
    offsets = []
    for row in eligible:
        if baseline_probability_key:
            baseline = min(0.995, max(0.005, float(row[baseline_probability_key])))
            offsets.append(math.log(baseline / (1.0 - baseline)))
        else:
            offsets.append(0.0)
    coefficient_values = [0.0] * len(names)
    n = float(len(eligible))
    for step in range(iterations):
        grad_intercept = 0.0
        gradients = [0.0] * len(names)
        for vector, outcome, offset in zip(matrix, outcomes, offsets):
            score = offset + intercept + sum(weight * value for weight, value in zip(coefficient_values, vector))
            error = _sigmoid(score) - outcome
            grad_intercept += error
            for index, value in enumerate(vector):
                gradients[index] += error * value
        rate = learning_rate / math.sqrt(1.0 + step / 100.0)
        intercept_change = rate * grad_intercept / n
        intercept -= intercept_change
        largest_change = abs(intercept_change)
        for index in range(len(names)):
            change = rate * (gradients[index] / n + l2 * coefficient_values[index] / n)
            coefficient_values[index] -= change
            largest_change = max(largest_change, abs(change))
        if step >= 80 and largest_change < 1e-7:
            break
    coefficients = dict(zip(names, coefficient_values))
    return {
        "feature_names": names, "means": means, "scales": scales,
        "intercept": intercept, "coefficients": coefficients, "l2": l2,
        "training_rows": len(eligible), "baseline_probability_key": baseline_probability_key,
        "optimization_iterations": step + 1,
    }


def predict_probability(model: dict[str, Any], features: dict[str, float],
                        baseline_probability: float | None = None) -> float:
    score = float(model["intercept"])
    if model.get("baseline_probability_key"):
        if baseline_probability is None:
            baseline_probability = 1.0 / (1.0 + 10.0 ** (-float(features.get("elo_diff", 0.0))))
        baseline_probability = min(0.995, max(0.005, float(baseline_probability)))
        score += math.log(baseline_probability / (1.0 - baseline_probability))
    for name in model["feature_names"]:
        value = (float(features.get(name, 0.0)) - float(model["means"][name])) / float(model["scales"][name])
        score += float(model["coefficients"][name]) * value
    return min(0.995, max(0.005, _sigmoid(score)))
