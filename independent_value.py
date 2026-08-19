"""Ask whether Matchday's independent read adds anything over the market.

This is the question the whole project turns on, and until now it has never
been computed anywhere. An ad-hoc pass over the committed pick logs on
2026-08-19 found the answer to be no:

    agrees with the market pick   81.5% of graded picks, winning 55.1%
    disagrees                     18.5%,                 winning 40.5%

Four fifths of the time Matchday repeats the market and inherits the market's
record, adding nothing. The one fifth of the time it has an original opinion,
it is wrong more often than a coin flip. A number that important should not
live in a chat log, so this module computes it as maintained code.

## Why this reads picks_log rather than the ledgers

`market_benchmark.py` answers a similar question far more rigorously, from the
append-only forecast ledger paired against recorded market snapshots. It is the
authority and this module is not. But the market snapshot ledger only began
persisting on 2026-08-19, so that report has no data yet and will not for
months, whereas `picks_log_*.json` is committed, holds hundreds of graded
fixtures, and already carries a lock-time market snapshot on each one.

The tradeoff is honest and worth naming: the pick logs are the site's published
record, which `update_scorecard`'s self-heal pass may correct after the fact,
so they are *descriptive* rather than tamper-evident. Treat a result here as a
strong hint, and `market_benchmark_report.json` as the verdict once it fills.
The report says so in its own `authority` field so a reader cannot mistake one
for the other.

## What it measures

Splitting on agreement is the point. A model that always names the favourite
cannot be evaluated on its overall hit rate, because that rate is the market's,
borrowed. Only the disagreements carry the model's own information, and only
the paired proper-scoring comparison says whether its *probabilities* are
better -- a model can pick the same side as the market and still add value by
being better calibrated, or pick differently and lose by being overconfident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
OUTCOMES = ("h", "d", "a")
MIN_FIXTURES = 100
MIN_DATE_BLOCKS = 20
BOOTSTRAP_SAMPLES = 4000
EPSILON = 1e-12


def _probabilities(raw: Any) -> dict[str, float] | None:
    """Normalize a stored {h,d,a} percentage map to probabilities summing to 1."""
    if not isinstance(raw, dict):
        return None
    values: dict[str, float] = {}
    for key in OUTCOMES:
        try:
            value = float(raw.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            values[key] = value
    total = sum(values.values())
    if total <= 0:
        return None
    return {key: max(value / total, EPSILON) for key, value in values.items()}


def _log_loss(probabilities: dict[str, float], result: str) -> float | None:
    probability = probabilities.get(result)
    return None if probability is None else -math.log(min(max(probability, EPSILON), 1.0))


def _brier(probabilities: dict[str, float], result: str) -> float:
    return sum((probabilities.get(key, 0.0) - (1.0 if key == result else 0.0)) ** 2
               for key in OUTCOMES)


def extract_rows(paths: Iterable[str | Path]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pull graded picks that carry both a model read and a lock-time market."""
    rows: list[dict[str, Any]] = []
    excluded: dict[str, int] = defaultdict(int)
    for value in paths:
        path = Path(value)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            excluded["unreadable_pick_log"] += 1
            continue
        records = payload.values() if isinstance(payload, dict) else payload
        for record in records:
            if not isinstance(record, dict):
                continue
            result = record.get("result")
            if result not in OUTCOMES:
                excluded["ungraded"] += 1
                continue
            model = _probabilities(record.get("probs"))
            market = _probabilities(record.get("market_snapshot"))
            pick = record.get("pick")
            if model is None or pick not in OUTCOMES:
                excluded["missing_model_read"] += 1
                continue
            market_pick = record.get("market_pick")
            if market_pick not in OUTCOMES:
                # A stored snapshot still names a favourite even when
                # market_pick was never written.
                market_pick = max(market, key=market.get) if market else None
            if market_pick not in OUTCOMES:
                excluded["no_market_comparison"] += 1
                continue
            # Deliberately NOT requiring market probabilities here. Far more
            # records carry the market's pick than carry its full probability
            # map (287 graded / 227 with a pick / 168 with probabilities on
            # 2026-08-19), and the agreement split -- the headline question of
            # whether Matchday is just repeating the line -- needs only the
            # pick. Dropping to the probability subset would discard a quarter
            # of the evidence for that question to satisfy a scoring comparison
            # it is not part of. Each metric below uses every row that can
            # support it, and reports its own n.
            if market is None:
                excluded["missing_market_probabilities"] += 1
            rows.append({
                "fixture_id": str(record.get("fixture_id") or ""),
                "competition": str(record.get("competition")
                                   or path.stem.removeprefix("picks_log_")).upper(),
                "date_block": str(record.get("kickoff") or "")[:10] or "unknown",
                "result": result, "pick": pick, "market_pick": market_pick,
                "model": model, "market": market,
                "has_market_probabilities": market is not None,
                "agrees": pick == market_pick,
                "model_correct": pick == result,
                "market_correct": market_pick == result,
            })
    return rows, dict(sorted(excluded.items()))


def _bootstrap_delta(rows: list[dict[str, Any]]) -> list[float | None]:
    """Game-date block bootstrap of model minus market log loss. Negative is better."""
    blocks: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        model_loss = _log_loss(row["model"], row["result"])
        market_loss = _log_loss(row["market"], row["result"])
        if model_loss is None or market_loss is None:
            continue
        blocks[row["date_block"]].append(model_loss - market_loss)
    names = sorted(blocks)
    if len(names) < 2:
        return [None, None]
    seed = "|".join(f"{row['fixture_id']}:{row['result']}" for row in
                    sorted(rows, key=lambda item: item["fixture_id"]))
    rng = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))
    estimates = []
    for _ in range(BOOTSTRAP_SAMPLES):
        draw = [rng.choice(names) for _ in names]
        values = [value for name in draw for value in blocks[name]]
        estimates.append(sum(values) / len(values))
    estimates.sort()
    return [round(estimates[int(BOOTSTRAP_SAMPLES * 0.025)], 6),
            round(estimates[min(int(BOOTSTRAP_SAMPLES * 0.975), BOOTSTRAP_SAMPLES - 1)], 6)]


def _scores(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    losses = [_log_loss(row[key], row["result"]) for row in rows]
    losses = [value for value in losses if value is not None]
    if not losses:
        return {"n": 0, "log_loss": None, "brier": None, "hit_rate": None}
    correct = sum(row["model_correct"] if key == "model" else row["market_correct"]
                  for row in rows)
    return {
        "n": len(rows),
        "log_loss": round(sum(losses) / len(losses), 6),
        "brier": round(sum(_brier(row[key], row["result"]) for row in rows) / len(rows), 6),
        "hit_rate": round(correct / len(rows), 4),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    agree = [row for row in rows if row["agrees"]]
    disagree = [row for row in rows if not row["agrees"]]
    scored = [row for row in rows if row["has_market_probabilities"]]
    interval = _bootstrap_delta(scored)
    model_scores = _scores(scored, "model")
    market_scores = _scores(scored, "market")
    summary = {
        "n": total,
        "date_blocks": len({row["date_block"] for row in rows}),
        "n_with_market_probabilities": len(scored),
        "agreement": {
            "n": len(agree),
            "share": round(len(agree) / total, 4) if total else None,
            "hit_rate": (round(sum(row["model_correct"] for row in agree) / len(agree), 4)
                         if agree else None),
        },
        "disagreement": {
            "n": len(disagree),
            "share": round(len(disagree) / total, 4) if total else None,
            "matchday_hit_rate": (round(sum(row["model_correct"] for row in disagree)
                                        / len(disagree), 4) if disagree else None),
            "market_hit_rate": (round(sum(row["market_correct"] for row in disagree)
                                      / len(disagree), 4) if disagree else None),
        },
        "scores": {"matchday": model_scores, "market": market_scores},
        "paired_log_loss_delta": {
            "mean": (round(model_scores["log_loss"] - market_scores["log_loss"], 6)
                     if model_scores["log_loss"] is not None
                     and market_scores["log_loss"] is not None else None),
            "ci95": interval,
            "sign": "negative means Matchday's probabilities beat the market's",
        },
    }
    summary["verdict"] = _verdict(summary)
    return summary


def _verdict(summary: dict[str, Any]) -> dict[str, Any]:
    # Gated on the scored subset: the verdict is about the paired probability
    # comparison, which only rows carrying market probabilities contribute to.
    scored = summary["n_with_market_probabilities"]
    if scored < MIN_FIXTURES or summary["date_blocks"] < MIN_DATE_BLOCKS:
        return {"state": "insufficient_evidence",
                "detail": f"{scored} of {MIN_FIXTURES} fixtures with market "
                          f"probabilities and {summary['date_blocks']} of "
                          f"{MIN_DATE_BLOCKS} game-dates"}
    low, high = summary["paired_log_loss_delta"]["ci95"]
    if low is None or high is None:
        return {"state": "insufficient_evidence", "detail": "interval not estimable"}
    if high < 0:
        return {"state": "adds_value_over_market",
                "detail": f"paired log-loss interval [{low}, {high}] lies below zero"}
    if low > 0:
        return {"state": "worse_than_market",
                "detail": f"paired log-loss interval [{low}, {high}] lies above zero"}
    return {"state": "no_detectable_difference",
            "detail": f"paired log-loss interval [{low}, {high}] contains zero"}


def build_report(paths: Iterable[str | Path]) -> dict[str, Any]:
    rows, excluded = extract_rows(paths)
    by_competition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_competition[row["competition"]].append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "research_only": True, "production_weight": 0,
        "authority": "DESCRIPTIVE. Built from the published pick logs, which the "
                     "scorecard's self-heal pass may correct after the fact. "
                     "market_benchmark_report.json, built from the append-only forecast "
                     "ledger and recorded market snapshots, is the tamper-evident "
                     "authority; prefer it once it has data.",
        "method": {
            "split": "agreement with the market's own pick at lock time",
            "primary": "paired log loss, Matchday minus market, on identical fixtures",
            "interval": "deterministic game-date block bootstrap",
            "population": "The agreement split uses every graded pick carrying the "
                          "market's pick. The paired scoring comparison uses the smaller "
                          "subset that also carries the market's probabilities; each "
                          "metric reports its own n.",
            "note": "Overall hit rate is not evidence about the model: when Matchday "
                    "names the market's favourite it inherits the market's record. "
                    "Only the disagreements carry its own information.",
        },
        "excluded": excluded,
        "overall": summarize(rows) if rows else {"n": 0},
        "by_competition": {name: summarize(subset)
                           for name, subset in sorted(by_competition.items()) if subset},
    }


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--picks", nargs="*", help="pick logs (default: picks_log_*.json)")
    parser.add_argument("--output", default="independent_value_report.json")
    args = parser.parse_args(argv)

    paths = args.picks or sorted(str(path) for path in Path(".").glob("picks_log_*.json"))
    report = build_report(paths)
    write_report(args.output, report)
    overall = report["overall"]
    if not overall.get("n"):
        print("no graded picks with a market snapshot yet")
        return 0
    agree, disagree = overall["agreement"], overall["disagreement"]
    print(f"graded={overall['n']} blocks={overall['date_blocks']}")
    print(f"  agrees with market   {agree['n']:5} ({agree['share']:.1%})  hit {agree['hit_rate']:.1%}")
    print(f"  disagrees            {disagree['n']:5} ({disagree['share']:.1%})  "
          f"Matchday {disagree['matchday_hit_rate']:.1%} vs market {disagree['market_hit_rate']:.1%}")
    print(f"  paired log loss delta {overall['paired_log_loss_delta']['mean']} "
          f"ci95={overall['paired_log_loss_delta']['ci95']} -> {overall['verdict']['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
