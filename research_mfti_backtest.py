"""Research-only audit for the proposed Matchday Forecast Trust Index (MFTI).

This script is intentionally isolated from the application.  It reads locked pick
ledgers and writes nothing.  It answers two questions:

1. How have the stored probability vectors performed under proper scoring rules?
2. Is the ledger rich enough to backtest the complete MFTI without inventing data?

The full MFTI cannot be reconstructed unless the record contains point-in-time
scenario forecasts, availability certainty, input freshness/coverage, and outputs
from independent model families.  Missing components remain missing.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


OUTCOMES = ("h", "d", "a")
EPSILON = 1e-15


@dataclass(frozen=True)
class Forecast:
    competition: str
    event_id: str
    kickoff: datetime
    probabilities: dict[str, float]
    result: str
    market: dict[str, float] | None
    raw: dict[str, Any]


def _parse_time(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _normalize(values: dict[str, Any], keys: Iterable[str]) -> dict[str, float] | None:
    selected: dict[str, float] = {}
    for key in keys:
        value = values.get(key)
        if value is None:
            return None
        try:
            selected[key] = max(0.0, float(value))
        except (TypeError, ValueError):
            return None
    total = sum(selected.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in selected.items()}


def load_forecasts(pattern: str) -> tuple[list[Forecast], dict[str, int]]:
    forecasts: list[Forecast] = []
    inventory: Counter[str] = Counter()
    for filename in sorted(glob.glob(pattern)):
        path = Path(filename)
        competition = path.stem.removeprefix("picks_log_").upper()
        if path.stem == "picks_log":
            competition = "DEFAULT"
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
        rows = document.values() if isinstance(document, dict) else document
        for ordinal, row in enumerate(rows):
            inventory["records"] += 1
            result = row.get("result")
            if result not in OUTCOMES:
                inventory["unsettled"] += 1
                continue
            inventory["settled"] += 1
            probs = row.get("probs")
            if not isinstance(probs, dict):
                inventory["settled_without_probability_vector"] += 1
                continue
            active_keys = ("h", "a") if probs.get("d") in (None, 0, 0.0) else OUTCOMES
            normalized = _normalize(probs, active_keys)
            if normalized is None or result not in normalized:
                inventory["invalid_probability_vector"] += 1
                continue
            market_raw = row.get("market_snapshot")
            market = _normalize(market_raw, active_keys) if isinstance(market_raw, dict) else None
            event_id = str(row.get("id") or row.get("event_id") or f"{path.name}:{ordinal}")
            forecasts.append(
                Forecast(
                    competition=competition,
                    event_id=event_id,
                    kickoff=_parse_time(row.get("kickoff")),
                    probabilities=normalized,
                    result=result,
                    market=market,
                    raw=row,
                )
            )
            inventory["eligible_probability_forecasts"] += 1
            if market is not None:
                inventory["eligible_with_market_snapshot"] += 1
    forecasts.sort(key=lambda item: (item.kickoff, item.competition, item.event_id))
    return forecasts, dict(inventory)


def brier(probs: dict[str, float], result: str) -> float:
    return sum((probability - float(key == result)) ** 2 for key, probability in probs.items())


def log_loss(probs: dict[str, float], result: str) -> float:
    return -math.log(max(EPSILON, probs[result]))


def favorite_hit(forecast: Forecast) -> bool:
    return max(forecast.probabilities, key=forecast.probabilities.get) == forecast.result


def summarize(rows: list[Forecast]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    model_brier = [brier(row.probabilities, row.result) for row in rows]
    model_log = [log_loss(row.probabilities, row.result) for row in rows]
    uniform_brier: list[float] = []
    uniform_log: list[float] = []
    for row in rows:
        uniform = {key: 1.0 / len(row.probabilities) for key in row.probabilities}
        uniform_brier.append(brier(uniform, row.result))
        uniform_log.append(log_loss(uniform, row.result))
    market_rows = [row for row in rows if row.market is not None]
    return {
        "n": len(rows),
        "favorite_accuracy": sum(favorite_hit(row) for row in rows) / len(rows),
        "brier": sum(model_brier) / len(model_brier),
        "log_loss": sum(model_log) / len(model_log),
        "uniform_brier": sum(uniform_brier) / len(uniform_brier),
        "uniform_log_loss": sum(uniform_log) / len(uniform_log),
        "brier_skill_vs_uniform": 1.0 - sum(model_brier) / sum(uniform_brier),
        "log_skill_vs_uniform": 1.0 - sum(model_log) / sum(uniform_log),
        "market": summarize_market(market_rows),
    }


def summarize_market(rows: list[Forecast]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    model_brier = sum(brier(row.probabilities, row.result) for row in rows) / len(rows)
    market_brier = sum(brier(row.market or {}, row.result) for row in rows) / len(rows)
    model_log = sum(log_loss(row.probabilities, row.result) for row in rows) / len(rows)
    market_log = sum(log_loss(row.market or {}, row.result) for row in rows) / len(rows)
    return {
        "n": len(rows),
        "model_brier": model_brier,
        "market_brier": market_brier,
        "brier_skill_vs_market": 1.0 - model_brier / market_brier,
        "model_log_loss": model_log,
        "market_log_loss": market_log,
        "log_skill_vs_market": 1.0 - model_log / market_log,
    }


def calibration_table(rows: list[Forecast]) -> list[dict[str, Any]]:
    """Top-outcome reliability table; diagnostic only, never the main score."""
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for row in rows:
        favorite = max(row.probabilities, key=row.probabilities.get)
        confidence = row.probabilities[favorite]
        lower = min(90, int(confidence * 10) * 10)
        buckets[lower].append((confidence, favorite == row.result))
    table = []
    for lower, values in sorted(buckets.items()):
        table.append(
            {
                "band": f"{lower}-{lower + 9}%",
                "n": len(values),
                "mean_forecast": sum(item[0] for item in values) / len(values),
                "observed_rate": sum(item[1] for item in values) / len(values),
            }
        )
    return table


def _captured(row: Forecast, component: str, input_key: str) -> bool:
    """Was this MFTI component actually captured for this pick?

    Checks the shadow receipt first, since that is the authoritative record of
    what was available at lock time, then falls back to the raw ``mfti_inputs``
    block and finally to a top-level key.  The receipt/input names are the ones
    mfti_research actually reads (``availability``, ``freshness``,
    ``independent_models``); this function previously looked only for a
    different set of top-level names that nothing ever writes
    (``availability_probabilities``, ``input_freshness``,
    ``independent_model_outputs``), so coverage would have reported a flat 0%
    forever once the shadow receipt was wired in -- reading as a data drought
    rather than a naming mismatch.
    """
    receipt = row.raw.get("mfti_shadow")
    if isinstance(receipt, dict):
        entry = (receipt.get("components") or {}).get(component)
        if isinstance(entry, dict) and entry.get("available") is not None:
            return bool(entry.get("available"))
    inputs = row.raw.get("mfti_inputs")
    if isinstance(inputs, dict) and inputs.get(input_key):
        return True
    return bool(row.raw.get(input_key))


def component_coverage(rows: list[Forecast]) -> dict[str, Any]:
    requirements = {
        "historical_probability_and_result": lambda row: bool(row.probabilities) and bool(row.result),
        "timestamped_market_benchmark": lambda row: row.market is not None and bool(row.raw.get("market_snapshot_at")),
        "scenario_forecasts": lambda row: _captured(row, "scenario_stability", "scenario_forecasts"),
        "availability_probabilities": lambda row: _captured(row, "availability", "availability"),
        "freshness_and_coverage": lambda row: _captured(row, "freshness", "freshness"),
        "independent_model_outputs": lambda row: _captured(row, "model_stability", "independent_models"),
    }
    return {
        key: {
            "available": sum(bool(test(row)) for row in rows),
            "total": len(rows),
            "coverage": (sum(bool(test(row)) for row in rows) / len(rows)) if rows else 0.0,
        }
        for key, test in requirements.items()
    }


def shadow_summary(rows: list[Forecast]) -> dict[str, Any]:
    receipts = [row for row in rows if isinstance(row.raw.get("mfti_shadow"), dict)]
    scored = [row for row in receipts if row.raw["mfti_shadow"].get("score") is not None]
    bands: dict[int, list[Forecast]] = defaultdict(list)
    for row in scored:
        score = float(row.raw["mfti_shadow"]["score"])
        bands[min(90, int(score // 10) * 10)].append(row)
    return {
        "receipts": len(receipts),
        "complete_scores": len(scored),
        "bands": [
            {
                "band": f"{lower}-{lower + 9}",
                **summarize(values),
            }
            for lower, values in sorted(bands.items())
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="picks_log*.json")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    forecasts, inventory = load_forecasts(args.pattern)
    by_competition = {
        competition: summarize([row for row in forecasts if row.competition == competition])
        for competition in sorted({row.competition for row in forecasts})
    }
    report = {
        "status": "partial_backtest_only",
        "reason": (
            "The probability model and Historical Evidence inputs are partly reconstructible; "
            "the full MFTI Event Readiness pillar is not present in historical ledgers."
        ),
        "inventory": inventory,
        "aggregate": summarize(forecasts),
        "by_competition": by_competition,
        "calibration": calibration_table(forecasts),
        "mfti_component_coverage": component_coverage(forecasts),
        "mfti_shadow": shadow_summary(forecasts),
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print("MFTI RESEARCH BACKTEST")
    print("Status: PARTIAL ONLY (no production files changed)\n")
    print(report["reason"])
    print(f"\nEligible settled probability forecasts: {len(forecasts)}")
    aggregate = report["aggregate"]
    print(f"Favorite accuracy: {aggregate.get('favorite_accuracy', 0):.1%}")
    print(f"Brier: {aggregate.get('brier', 0):.4f}")
    print(f"Log loss: {aggregate.get('log_loss', 0):.4f}")
    print(f"Brier skill vs uniform: {aggregate.get('brier_skill_vs_uniform', 0):+.1%}")
    print(f"Log skill vs uniform: {aggregate.get('log_skill_vs_uniform', 0):+.1%}")
    print("\nBy competition:")
    for competition, metrics in by_competition.items():
        print(
            f"  {competition:12} n={metrics['n']:3d} "
            f"acc={metrics['favorite_accuracy']:.1%} "
            f"BS={metrics['brier']:.4f} LL={metrics['log_loss']:.4f}"
        )
    print("\nMFTI component coverage:")
    for component, coverage in report["mfti_component_coverage"].items():
        print(f"  {component:36} {coverage['available']:3d}/{coverage['total']:3d}")
    print(f"\nShadow receipts: {report['mfti_shadow']['receipts']}")
    print(f"Complete historical MFTI scores: {report['mfti_shadow']['complete_scores']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
