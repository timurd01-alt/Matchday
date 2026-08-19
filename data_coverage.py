"""Measure what the prediction models asked for and did not get.

Matchday publishes a pick for every fixture it lists, whether or not the
inputs behind that pick actually arrived. A fixture with no market prices, no
lineups and no head-to-head history still gets a probability, and nothing in
the published payload distinguishes it from one built on everything the model
wanted. That is the gap this measures: not whether a fetch errored -- fetch
failures already have their own signal -- but whether the data is *there*.

Four kinds of gap, because they call for different work:

  missing_input      A family the model uses is absent on fixtures close
                     enough to kick off that it should have arrived. Usually
                     a cadence, quota or adapter problem.
  stale_feed         A competition's payload has not been rebuilt inside its
                     freshness budget while it still has imminent fixtures.
  unsourced_family   A family that is empty on EVERY fixture of EVERY
                     competition. Nothing is failing; nothing was ever wired
                     up. This is a sourcing decision, not a repair.
  thin_evidence      A competition publishing picks with too few graded
                     results to say anything about whether they are any good.

Everything here is read-only and derived. It never edits a payload, a pick
log or a ledger, and it reports competitions rather than fixtures so a task
built from it is about a pipeline rather than a single row.

Off-season is not a gap. A competition with no fixtures inside the horizon is
skipped for input and freshness gaps entirely -- NBA and NHL sit at zero
fixtures for months at a time, and a loop that reports them every hour for
half the year teaches its reader to ignore it.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1

# How close to kickoff a fixture must be before its inputs are expected. Odds
# and lineups genuinely do not exist for a fixture months out, so measuring
# them there would report a permanent, unfixable gap.
INPUT_HORIZON_HOURS = 72

# A family present on fewer than this share of imminent fixtures is reported.
# Not 100%: some fixtures legitimately lack lineups until an hour before
# kickoff, and a floor that demands perfection fires constantly.
COVERAGE_FLOOR = 0.5

# Below this many imminent fixtures a percentage is noise, not a measurement.
MIN_FIXTURES_FOR_COVERAGE = 5

# A competition with imminent fixtures should have been rebuilt this recently.
# The publish workflow runs hourly, so a day is many missed runs, not one.
FRESHNESS_BUDGET_HOURS = 24

# Graded fixtures needed before a competition's accuracy is worth discussing.
MIN_GRADED_FIXTURES = 30


def _has_markets(match: dict) -> bool:
    return bool(match.get("markets"))


def _has_lineups(match: dict) -> bool:
    lineups = match.get("lineups")
    return bool(lineups) and lineups is not None


def _has_injuries(match: dict) -> bool:
    injuries = match.get("injuries") or {}
    return bool(injuries.get("home") or injuries.get("away"))


def _has_h2h(match: dict) -> bool:
    return bool(match.get("h2h"))


def _has_prediction(match: dict) -> bool:
    prediction = match.get("prediction") or {}
    return bool(prediction.get("model") or prediction.get("pick"))


# (family, predicate, severity when missing). Prediction is critical because a
# fixture published without one is a hole in the product itself; the rest
# degrade a forecast without removing it.
INPUT_FAMILIES: tuple[tuple[str, Callable[[dict], bool], str], ...] = (
    ("prediction", _has_prediction, "critical"),
    ("markets", _has_markets, "critical"),
    ("lineups", _has_lineups, "warn"),
    ("injuries", _has_injuries, "warn"),
    ("h2h", _has_h2h, "warn"),
)


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_time(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _gap(kind: str, severity: str, competition: str, summary: str,
         **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "competition": competition,
            "summary": summary, **extra}


def _payloads(base: Path) -> dict[str, dict[str, Any]]:
    """Published competition payloads, keyed by competition.

    data.json is a duplicate of whichever competition was built last (MLB at
    the time of writing) and is skipped when a data_<comp>.json exists for the
    same key, so one competition cannot be counted -- or reported -- twice.
    """
    found: dict[str, dict[str, Any]] = {}
    for name in sorted(glob.glob("data_*.json", root_dir=str(base))) + ["data.json"]:
        payload = _load_json(base / name)
        if not isinstance(payload, dict):
            continue
        key = str(payload.get("comp_key") or Path(name).stem.replace("data_", "")).upper()
        found.setdefault(key, payload)
    return found


def _imminent(payload: dict, now: datetime.datetime) -> list[dict]:
    horizon = now + datetime.timedelta(hours=INPUT_HORIZON_HOURS)
    upcoming = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        if str(match.get("status") or "").upper() not in ("UPCOMING", "LIVE"):
            continue
        kickoff = _parse_time(match.get("kickoff"))
        if kickoff and now <= kickoff <= horizon:
            upcoming.append(match)
    return upcoming


def input_gaps(payloads: dict[str, dict], now: datetime.datetime,
               skip_families: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Per-competition coverage gaps inside the horizon.

    `skip_families` carries the families already reported as unsourced
    everywhere. Without it the same absence is reported twice -- once per
    competition as a coverage shortfall, once globally as a sourcing gap --
    and the per-competition version is the misleading one, because it frames
    a provider that was never wired up as a competition that is missing data.
    """
    gaps = []
    for comp, payload in sorted(payloads.items()):
        fixtures = _imminent(payload, now)
        if len(fixtures) < MIN_FIXTURES_FOR_COVERAGE:
            continue
        for family, predicate, severity in INPUT_FAMILIES:
            if family in skip_families:
                continue
            covered = sum(1 for match in fixtures if predicate(match))
            share = covered / len(fixtures)
            if share < COVERAGE_FLOOR:
                gaps.append(_gap(
                    "missing_input", severity, comp,
                    f"{comp}: {family} present on {covered}/{len(fixtures)} "
                    f"({share:.0%}) fixtures kicking off within "
                    f"{INPUT_HORIZON_HOURS}h, below the "
                    f"{COVERAGE_FLOOR:.0%} floor.",
                    family=family, covered=covered, total=len(fixtures),
                    share=round(share, 4)))
    return gaps


def freshness_gaps(payloads: dict[str, dict], now: datetime.datetime) -> list[dict[str, Any]]:
    gaps = []
    for comp, payload in sorted(payloads.items()):
        if not _imminent(payload, now):
            continue  # off-season or nothing scheduled; staleness is expected
        updated = _parse_time(payload.get("updated"))
        if updated is None:
            gaps.append(_gap(
                "stale_feed", "critical", comp,
                f"{comp}: payload carries no readable `updated` timestamp, so "
                f"its freshness cannot be established at all."))
            continue
        age_hours = (now - updated).total_seconds() / 3600
        if age_hours > FRESHNESS_BUDGET_HOURS:
            gaps.append(_gap(
                "stale_feed", "critical", comp,
                f"{comp}: last rebuilt {age_hours:.0f}h ago against a "
                f"{FRESHNESS_BUDGET_HOURS}h budget, while it still has "
                f"fixtures inside {INPUT_HORIZON_HOURS}h. Picks are being "
                f"published from a payload that is not being refreshed.",
                age_hours=round(age_hours, 1),
                updated=updated.isoformat()))
    return gaps


def unsourced_family_gaps(payloads: dict[str, dict]) -> list[dict[str, Any]]:
    """Families empty on every fixture everywhere.

    Measured across ALL fixtures rather than the imminent window: a family
    that never arrives is not a cadence problem that a horizon would reveal,
    and using the whole corpus makes "never" mean never.
    """
    totals = {family: [0, 0] for family, _, _ in INPUT_FAMILIES}
    for payload in payloads.values():
        for match in payload.get("matches") or []:
            if not isinstance(match, dict):
                continue
            for family, predicate, _severity in INPUT_FAMILIES:
                totals[family][1] += 1
                if predicate(match):
                    totals[family][0] += 1
    gaps = []
    for family, (covered, total) in sorted(totals.items()):
        if total and covered == 0:
            gaps.append(_gap(
                "unsourced_family", "warn", "ALL",
                f"{family} is empty on all {total} fixtures across every "
                f"competition. Nothing is failing -- no provider is wired to "
                f"supply it. Sourcing it is a decision, not a repair.",
                family=family, total=total))
    return gaps


def _is_mid_season(payload: dict) -> bool:
    """Whether a competition is actually running right now.

    A pick can only be graded if it was locked, and it can only be locked if
    the system saw the fixture while it was still upcoming. So "no graded
    evidence" means completely different things depending on where a
    competition is in its year, and only one of them is a defect:

      all upcoming   -- the season has not started. EPL on 2026-08-19 was
                        14 fixtures, 0 finished, first kickoff Aug 21.
      all finished   -- the season is over, or the fixtures were first seen
                        already complete and were therefore quarantined
                        rather than locked (fetch_data._lock_decision returns
                        first_seen_finished). UCL on the same day: 13
                        finished, 0 upcoming, next season in September.
      both           -- fixtures are being played and observed. Now an empty
                        pick log means something is broken.

    Without this, the report flagged seven competitions on a single August
    afternoon for the crime of being between seasons, which is the same
    false-positive class the interface audit already had to be cured of.
    """
    finished = upcoming = 0
    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        status = str(match.get("status") or "").upper()
        if status == "FINISHED":
            finished += 1
        elif status in ("UPCOMING", "LIVE"):
            upcoming += 1
    return bool(finished and upcoming)


def evidence_gaps(base: Path, payloads: dict[str, dict]) -> list[dict[str, Any]]:
    """Competitions publishing picks without enough graded results to judge."""
    graded: dict[str, int] = {}
    for name in sorted(glob.glob("picks_log_*.json", root_dir=str(base))):
        rows = _load_json(base / name)
        if not isinstance(rows, dict):
            continue
        key = Path(name).stem.replace("picks_log_", "").upper()
        graded[key] = sum(
            1 for row in rows.values()
            if isinstance(row, dict) and row.get("result"))
    gaps = []
    for comp, payload in sorted(payloads.items()):
        if not (payload.get("matches") or []):
            continue  # nothing published, nothing to judge
        if not _is_mid_season(payload):
            continue  # between seasons: an empty pick log is expected, not a gap
        count = graded.get(comp, 0)
        if count >= MIN_GRADED_FIXTURES:
            continue
        if comp not in graded:
            gaps.append(_gap(
                "thin_evidence", "warn", comp,
                f"{comp}: publishing picks with no graded pick log at all, so "
                f"nothing measures whether they are right.",
                graded=0, required=MIN_GRADED_FIXTURES))
        else:
            gaps.append(_gap(
                "thin_evidence", "warn", comp,
                f"{comp}: {count} graded fixture(s) against the "
                f"{MIN_GRADED_FIXTURES} needed before its accuracy is worth "
                f"quoting.",
                graded=count, required=MIN_GRADED_FIXTURES))
    return gaps


SEVERITY_ORDER = {"critical": 0, "warn": 1}
KIND_ORDER = {"stale_feed": 0, "missing_input": 1,
              "thin_evidence": 2, "unsourced_family": 3}


def build_report(root: str | Path = ".",
                 now: datetime.datetime | None = None) -> dict[str, Any]:
    base = Path(root)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    payloads = _payloads(base)
    gaps: list[dict[str, Any]] = []
    unsourced = unsourced_family_gaps(payloads)
    gaps.extend(freshness_gaps(payloads, now))
    gaps.extend(input_gaps(
        payloads, now, frozenset(item["family"] for item in unsourced)))
    gaps.extend(evidence_gaps(base, payloads))
    gaps.extend(unsourced)
    gaps.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9),
                                KIND_ORDER.get(item["kind"], 9),
                                item["competition"]))
    counts: dict[str, int] = {}
    for item in gaps:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {"schema_version": SCHEMA_VERSION,
            "generated_at": now.isoformat(),
            "competitions": sorted(payloads),
            "gaps": gaps, "by_kind": counts,
            "critical": sum(1 for item in gaps if item["severity"] == "critical"),
            "warnings": sum(1 for item in gaps if item["severity"] == "warn")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", help="write the report JSON to this path")
    args = parser.parse_args(argv)

    report = build_report(args.root)
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
    if not report["gaps"]:
        print(f"data_coverage: no gaps across "
              f"{len(report['competitions'])} competition(s)")
    else:
        print(f"data_coverage: {report['critical']} critical, "
              f"{report['warnings']} warning(s)")
        for item in report["gaps"]:
            print(f"  [{item['severity']}] {item['kind']}: {item['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
