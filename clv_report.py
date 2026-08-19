"""Measure closing line value: does the market move toward Matchday's pick?

Matchday has been judging itself on win rate, which is close to the worst
available instrument for the question it actually cares about. Game outcomes
are near-coin-flips, so separating a real one- or two-point edge from noise
takes thousands of graded fixtures -- which is why the MLB gate needs 500 games
and why an answer is years away at most competitions' fixture rates.

Closing line value asks the same question through a much quieter channel. Lock
a forecast early, then look at where the market ended up. If the closing
consensus has moved toward the side Matchday picked, the market came to agree
with a read Matchday held first. Line movement carries far less variance than
match results, so a given amount of evidence goes much further -- hundreds of
fixtures rather than thousands.

Two guards keep this honest:

  * **Lead time.** CLV is only meaningful if the lock genuinely precedes the
    close. A pick locked ninety seconds before kickoff has nothing to be right
    early about, and its "movement" is noise. Every segment reports its lock
    lead-time distribution, and segments whose typical lead is under
    MIN_LEAD_MINUTES are reported but never given a verdict.

  * **Date-block bootstrap.** Fixtures on the same day share news, weather and
    market conditions, so treating them as independent overstates confidence.
    The interval resamples whole game-dates, matching the method the
    prospective scorecards already use.

Known limitation: rows come from `market_benchmark.extract_rows`, which pairs
locks with grades, so a fixture enters this report only once it has been
graded. CLV itself needs no result and could in principle be measured at
kickoff. Reusing the tested extraction -- with its participant-orientation
matching and no-vig consensus handling -- is worth the delay, which is hours
rather than the weeks the statistical gain saves.

This report is descriptive. It never feeds a forecast, and a segment showing
positive CLV is a place to investigate, not a licence to weight anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import forecast_ledger
import market_benchmark


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "matchday-clv-1.0.0"

# Below this many fixtures a segment gets numbers but no verdict. CLV converges
# far faster than outcome accuracy, but not instantly.
MIN_FIXTURES = 100
# Whole game-dates, not fixtures: same-day fixtures are correlated.
MIN_DATE_BLOCKS = 20
# A lock closer than this to kickoff cannot meaningfully precede the close.
MIN_LEAD_MINUTES = 30.0
BOOTSTRAP_SAMPLES = 4000


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _date_block(value: Any) -> str | None:
    moment = _time(value)
    return moment.date().isoformat() if moment else None


def _lead_minutes(row: dict[str, Any]) -> float | None:
    locked, kickoff = _time(row.get("locked_at")), _time(row.get("kickoff"))
    if locked is None or kickoff is None:
        return None
    return (kickoff - locked).total_seconds() / 60.0


def _selected(row: dict[str, Any]) -> str | None:
    model = row.get("model_independent")
    return max(model, key=model.get) if isinstance(model, dict) and model else None


def movement(row: dict[str, Any], *, frm: str = "lock_market") -> float | None:
    """Probability the market assigns to Matchday's pick, close minus `frm`."""
    start, close = row.get(frm), row.get("closing_market")
    pick = _selected(row)
    if not isinstance(start, dict) or not isinstance(close, dict) or pick is None:
        return None
    if pick not in start or pick not in close:
        return None
    try:
        return float(close[pick]) - float(start[pick])
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(int(len(ordered) * fraction), len(ordered) - 1)], 3)


def _bootstrap(blocks: dict[str, list[float]], seed_material: str) -> list[float | None]:
    """Deterministic game-date block bootstrap of the mean movement."""
    names = sorted(blocks)
    if len(names) < 2:
        return [None, None]
    rng = random.Random(int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16))
    estimates = []
    for _ in range(BOOTSTRAP_SAMPLES):
        draw = [rng.choice(names) for _ in names]
        values = [value for name in draw for value in blocks[name]]
        estimates.append(sum(values) / len(values))
    estimates.sort()
    return [round(estimates[int(BOOTSTRAP_SAMPLES * 0.025)], 6),
            round(estimates[min(int(BOOTSTRAP_SAMPLES * 0.975), BOOTSTRAP_SAMPLES - 1)], 6)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocks: dict[str, list[float]] = defaultdict(list)
    values: list[float] = []
    from_open: list[float] = []
    leads: list[float] = []
    seed_parts = []
    for row in sorted(rows, key=lambda item: (str(item.get("fixture_id")),
                                              str(item.get("lock_event_id")))):
        delta = movement(row)
        if delta is None:
            continue
        block = _date_block(row.get("kickoff")) or "unknown"
        blocks[block].append(delta)
        values.append(delta)
        seed_parts.append(f"{row.get('fixture_id')}:{delta}")
        open_delta = movement(row, frm="opening_market")
        if open_delta is not None:
            from_open.append(open_delta)
        lead = _lead_minutes(row)
        if lead is not None:
            leads.append(lead)

    count = len(values)
    median_lead = _percentile(leads, 0.5)
    summary: dict[str, Any] = {
        "n": count,
        "date_blocks": len(blocks),
        "mean_movement_toward_pick": round(sum(values) / count, 6) if count else None,
        "median_movement_toward_pick": _percentile(values, 0.5),
        "ci95": _bootstrap(blocks, "|".join(seed_parts)) if count else [None, None],
        "positive": sum(value > 0 for value in values),
        "zero": sum(value == 0 for value in values),
        "negative": sum(value < 0 for value in values),
        "share_positive": round(sum(value > 0 for value in values) / count, 4) if count else None,
        "mean_movement_from_opening": (round(sum(from_open) / len(from_open), 6)
                                       if from_open else None),
        "lock_lead_minutes": {
            "n": len(leads), "median": median_lead,
            "p10": _percentile(leads, 0.10), "p90": _percentile(leads, 0.90),
        },
    }
    summary["verdict"] = _verdict(summary, median_lead)
    return summary


def _verdict(summary: dict[str, Any], median_lead: float | None) -> dict[str, Any]:
    """State the honest reading, and refuse to state one when it isn't earned."""
    if median_lead is not None and median_lead < MIN_LEAD_MINUTES:
        return {"state": "not_measurable",
                "detail": f"median lock lead of {median_lead} minutes is under the "
                          f"{MIN_LEAD_MINUTES:.0f}-minute floor; these locks do not "
                          "meaningfully precede the close"}
    if summary["n"] < MIN_FIXTURES or summary["date_blocks"] < MIN_DATE_BLOCKS:
        return {"state": "insufficient_evidence",
                "detail": f"{summary['n']} of {MIN_FIXTURES} fixtures and "
                          f"{summary['date_blocks']} of {MIN_DATE_BLOCKS} game-dates"}
    low, high = summary["ci95"]
    if low is None or high is None:
        return {"state": "insufficient_evidence", "detail": "interval not estimable"}
    if low > 0:
        return {"state": "market_moves_toward_matchday",
                "detail": f"95% interval [{low}, {high}] lies entirely above zero"}
    if high < 0:
        return {"state": "market_moves_against_matchday",
                "detail": f"95% interval [{low}, {high}] lies entirely below zero"}
    return {"state": "no_detectable_edge",
            "detail": f"95% interval [{low}, {high}] contains zero"}


def build_report(forecast_paths: Iterable[str | Path], market_path: str | Path) -> dict[str, Any]:
    events = []
    sources = []
    for value in forecast_paths:
        path = Path(value)
        state = forecast_ledger.validate(path)
        events.extend(forecast_ledger.read_events(path))
        sources.append({"path": str(path), "events": state["events"],
                        "last_hash": state["last_hash"]})
    rows, exclusions = market_benchmark.extract_rows(events, market_path)

    by_competition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_competition[str(row.get("competition") or "UNKNOWN").upper()].append(row)

    return {
        "schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION,
        "research_only": True, "production_weight": 0,
        "method": {
            "metric": "closing probability minus lock probability, on the outcome "
                      "Matchday's independent model ranked first",
            "sign": "positive means the market moved toward Matchday's pick",
            "interval": "deterministic game-date block bootstrap",
            "minimum_fixtures": MIN_FIXTURES, "minimum_date_blocks": MIN_DATE_BLOCKS,
            "minimum_median_lock_lead_minutes": MIN_LEAD_MINUTES,
            "decision_rule": "descriptive only; positive CLV is a place to investigate, "
                             "never a weight to apply",
        },
        "forecast_sources": sources,
        "market_source": {"path": str(market_path)},
        "exclusions": exclusions,
        "overall": summarize(rows),
        "by_competition": {name: summarize(subset)
                           for name, subset in sorted(by_competition.items())},
    }


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--forecast-ledger", nargs="+", required=True)
    parser.add_argument("--market-ledger", required=True)
    parser.add_argument("--output", default="clv_report.json")
    args = parser.parse_args(argv)

    report = build_report(args.forecast_ledger, args.market_ledger)
    write_report(args.output, report)
    overall = report["overall"]
    print(f"overall n={overall['n']} blocks={overall['date_blocks']} "
          f"mean={overall['mean_movement_toward_pick']} "
          f"ci95={overall['ci95']} -> {overall['verdict']['state']}")
    for name, summary in report["by_competition"].items():
        print(f"  {name:12} n={summary['n']:5} mean={summary['mean_movement_toward_pick']} "
              f"-> {summary['verdict']['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
