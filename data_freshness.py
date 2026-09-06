"""Answer "is the published data actually up to date?" mechanically.

Matchday refreshes hourly and had not published a current NCAAF result for
five days before anyone noticed. Nothing was broken loudly: the fetch step is
`continue-on-error`, its failure handler downgrades a dead provider to a
`::warning::`, and the site then deploys the last-good snapshot. That is the
right call for one bad hour -- a stale board beats no board -- but it is
indistinguishable from the same failure repeating for a month, because nothing
ever compared the data's age against what the schedule says should be there.

This module is that comparison. It is read-only: it fetches nothing, spends no
provider quota, and never edits a payload. It reports, and it sets an exit
code so a run that quietly served stale data fails visibly instead.

Three separate things can be stale, and they fail independently:

  payload    -- `data_<key>.json` stopped changing. The usual cause is provider
                quota; `updated` is the honest age, not the file mtime, which
                a cache restore refreshes without changing a byte of content.
  results    -- a fixture whose kickoff has passed is still stamped UPCOMING,
                or carries a 0-0 placeholder. This is what a reader actually
                sees as wrong: a played game displayed as though it had not
                started.
  patch      -- `matchday-cfb-snapshot.js` is the browser-side repair layer
                built from the Bet Better handoff, which settles finished games
                the fixture feed could not afford to fetch. If the handoff is
                newer than the snapshot, the repair itself has gone stale and
                the site is patching from data older than what is on disk.

`results` is judged *after* applying the handoff, because that is what the
browser renders. A fixture the feed missed but the handoff settles is not a
user-visible problem, and reporting it as one would train everyone to ignore
this check -- which is precisely how the original failure survived five days.

Exit codes: 0 clean, 1 stale (something a reader would notice), 2 the report
could not be built at all.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
from typing import Any


SCHEMA_VERSION = 1

HANDOFF_PATH = pathlib.Path("betbetter_picks.json")
SNAPSHOT_PATH = pathlib.Path("matchday-cfb-snapshot.js")

# The hourly cron is `17 * * * *`, so a healthy payload is under an hour old
# and two consecutive misses is the first thing worth saying out loud. The
# failure threshold is deliberately not much larger: the whole point is to
# catch a stall in hours rather than the five days it actually took.
PAYLOAD_WARN_HOURS = 3.0
PAYLOAD_FAIL_HOURS = 12.0

# Mirrors multi_fetch.PAST_DUE_SCORE_GRACE_HOURS. A final score is not expected
# the instant a game ends -- the provider has to publish it and the next
# adaptive round has to pick it up -- so a fixture is only "unsettled" once it
# is this far past kickoff.
SETTLE_GRACE_HOURS = 8.0

# A snapshot older than the handoff it is built from means `build_cfb_snapshot`
# has not run since the handoff last landed. Small tolerance so the ordinary
# case (build runs seconds after the handoff commit) never trips it.
SNAPSHOT_LAG_TOLERANCE_MINUTES = 30.0

UPCOMING_STATUSES = {"UPCOMING", "SCHEDULED", "NS", "TIMED", "PST", ""}


def _sports() -> list[str]:
    """The competitions actually refreshed, read from the fetcher itself.

    Hard-coding a list here would drift the moment the published set changes --
    which it already has once, from twelve competitions down to college only.
    Checking freshness of a sport nothing fetches produces a permanent failure
    nobody can fix, so the fetcher's own list is the authority.
    """
    try:
        import multi_fetch

        return [key for key, _flag in multi_fetch.SPORTS]
    except Exception:
        return ["ncaaf", "ncaam"]


def _parse_iso(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        stamp = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return stamp.astimezone(datetime.timezone.utc)


def _hours_since(stamp: datetime.datetime | None, now: datetime.datetime) -> float | None:
    if stamp is None:
        return None
    return round((now - stamp).total_seconds() / 3600.0, 2)


def _team_key(name: Any) -> str:
    """Loose team-name key, matching what the browser does to join the handoff.

    Matchday stores "TCU" where the handoff carries "TCU Horned Frogs", so an
    exact match would drop nearly every row. This keeps the comparison to the
    leading words both sides agree on.
    """
    text = "".join(ch.lower() if (ch.isalnum() or ch.isspace()) else " " for ch in str(name or ""))
    return " ".join(text.split())


# Match strengths. Prefix matching is necessary -- Matchday says "TCU" where
# the handoff says "TCU Horned Frogs" -- but it is not safe on its own, because
# "Ohio" is a prefix of "Ohio State" and both are real FBS teams. So a prefix
# hit is deliberately weaker than an exact one, and `_settled_by_handoff`
# refuses to settle when the best available tier is ambiguous.
MATCH_NONE, MATCH_PREFIX, MATCH_EXACT = 0, 1, 2


def _name_strength(left: Any, right: Any) -> int:
    a, b = _team_key(left), _team_key(right)
    if not a or not b:
        return MATCH_NONE
    if a == b:
        return MATCH_EXACT
    if a.startswith(b + " ") or b.startswith(a + " "):
        return MATCH_PREFIX
    return MATCH_NONE


def _name_distance(left: Any, right: Any) -> int:
    """How many words the longer name adds to the shorter one.

    The handoff always appends a mascot, so an exact match is rare and the tier
    alone almost never separates "Ohio Bobcats" from "Ohio State Buckeyes" for
    a fixture listing "Ohio". Distance does: one added word versus two. The
    nearer name is the right one, and an equal distance stays ambiguous.
    """
    a, b = _team_key(left).split(), _team_key(right).split()
    return abs(len(a) - len(b))


def _names_match(left: Any, right: Any) -> bool:
    return _name_strength(left, right) != MATCH_NONE


def _shift_day(day: str, delta: int) -> str:
    try:
        base = datetime.date.fromisoformat(day)
    except ValueError:
        return ""
    return (base + datetime.timedelta(days=delta)).isoformat()


def load_handoff_results(path: pathlib.Path = HANDOFF_PATH) -> tuple[list[dict], datetime.datetime | None]:
    """Finished games from the Bet Better handoff, indexed by nothing yet.

    A missing handoff is normal rather than an error -- the engine is external
    and may simply not have run -- so this returns an empty list and lets the
    caller report the absence as its own finding.
    """
    if not path.exists():
        return [], None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    if document.get("source") != "betbetter":
        return [], None
    results = [r for r in (document.get("results") or []) if isinstance(r, dict)]
    return results, _parse_iso(document.get("generated_at"))


def _settled_by_handoff(match: dict, results: list[dict]) -> bool:
    """True when the handoff carries a score for this fixture.

    Matched on both team names and the calendar day, a day either side, because
    a late kickoff and its result can land on opposite sides of midnight UTC --
    the same tolerance `applyCurrentCfbSnapshot` uses in the browser.

    An exact name match beats a prefix one, and a tie at the best available
    strength settles nothing. Two teams whose names share a prefix -- Ohio and
    Ohio State -- would otherwise let one team's score mark the other's game as
    settled, which is worse than the staleness this check reports: it would
    hide a missing result instead of surfacing it.
    """
    day = str(match.get("kickoff") or "")[:10]
    if not day:
        return False
    days = {day, _shift_day(day, -1), _shift_day(day, 1)}
    home = (match.get("home") or {}).get("name")
    away = (match.get("away") or {}).get("name")

    best: tuple[int, int] | None = None
    hits = 0
    for row in results:
        if str(row.get("played_on") or "")[:10] not in days:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        strength = min(_name_strength(row.get("home"), home), _name_strength(row.get("away"), away))
        if strength == MATCH_NONE:
            continue
        # Higher tier first, then the nearer pair of names. Negated so a plain
        # max() picks the better candidate.
        rank = (
            strength,
            -(_name_distance(row.get("home"), home) + _name_distance(row.get("away"), away)),
        )
        if best is None or rank > best:
            best, hits = rank, 1
        elif rank == best:
            hits += 1
    return best is not None and hits == 1


def _unsettled(match: dict, now: datetime.datetime) -> bool:
    """A past-kickoff fixture with no usable result of its own.

    A 0-0 counts as missing rather than as a genuine scoreless draw: no sport
    published here ends 0-0 often enough for that to be worth preserving, and
    the placeholder is what a stalled MLB payload actually leaves behind.
    """
    kickoff = _parse_iso(match.get("kickoff") or match.get("date"))
    if kickoff is None:
        return False
    if (now - kickoff).total_seconds() / 3600.0 < SETTLE_GRACE_HOURS:
        return False
    status = str(match.get("status") or "").upper()
    score = match.get("score") or {}
    home, away = score.get("home"), score.get("away")
    if status in UPCOMING_STATUSES:
        return True
    return (home is None and away is None) or (home == 0 and away == 0)


def inspect_payload(
    key: str,
    results: list[dict],
    now: datetime.datetime,
    root: pathlib.Path = pathlib.Path("."),
) -> dict[str, Any]:
    path = root / f"data_{key}.json"
    finding: dict[str, Any] = {"sport": key, "path": str(path), "state": "ok", "problems": []}

    if not path.exists():
        finding.update(state="missing", problems=[f"{path} does not exist"])
        return finding

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        finding.update(state="unreadable", problems=[f"{path} could not be parsed: {exc}"])
        return finding

    updated = _parse_iso(payload.get("updated"))
    age = _hours_since(updated, now)
    finding["updated"] = payload.get("updated")
    finding["age_hours"] = age

    matches = [m for m in (payload.get("matches") or []) if isinstance(m, dict)]
    finding["matches"] = len(matches)

    raw = [m for m in matches if _unsettled(m, now)]
    remaining = [m for m in raw if not _settled_by_handoff(m, results)]
    finding["unsettled_in_payload"] = len(raw)
    finding["unsettled_after_handoff"] = len(remaining)
    finding["repaired_by_handoff"] = len(raw) - len(remaining)
    finding["examples"] = [
        {
            "kickoff": m.get("kickoff"),
            "home": (m.get("home") or {}).get("name"),
            "away": (m.get("away") or {}).get("name"),
            "status": m.get("status"),
        }
        for m in remaining[:5]
    ]

    if age is None:
        finding["problems"].append("payload has no usable `updated` stamp")
        finding["state"] = "stale"
    elif age >= PAYLOAD_FAIL_HOURS:
        finding["problems"].append(f"payload is {age:.1f}h old (fails at {PAYLOAD_FAIL_HOURS:.0f}h)")
        finding["state"] = "stale"
    elif age >= PAYLOAD_WARN_HOURS:
        finding["problems"].append(f"payload is {age:.1f}h old (warns at {PAYLOAD_WARN_HOURS:.0f}h)")
        finding["state"] = "aging"

    if remaining:
        finding["problems"].append(
            f"{len(remaining)} played fixture(s) still show no result, even after the handoff"
        )
        finding["state"] = "stale"

    return finding


def inspect_patch_layer(
    handoff_generated: datetime.datetime | None,
    now: datetime.datetime,
    root: pathlib.Path = pathlib.Path("."),
) -> dict[str, Any]:
    """Is the browser-side repair layer itself current?

    The snapshot has no timestamp inside it, so its mtime is all there is. That
    is unreliable across a fresh checkout, where every file is checked out at
    once -- so a snapshot that merely *looks* current in CI is reported as
    `unknown` rather than passed, and only a snapshot demonstrably older than
    the handoff is called stale.
    """
    snapshot = root / SNAPSHOT_PATH.name
    handoff = root / HANDOFF_PATH.name
    finding: dict[str, Any] = {"component": "cfb_snapshot", "state": "ok", "problems": []}

    finding["handoff_generated_at"] = handoff_generated.isoformat() if handoff_generated else None
    finding["handoff_age_hours"] = _hours_since(handoff_generated, now)

    if not handoff.exists():
        finding.update(state="missing", problems=["betbetter_picks.json is absent; nothing to patch from"])
        return finding
    if not snapshot.exists():
        finding.update(state="missing", problems=["matchday-cfb-snapshot.js is absent; the browser has no repair layer"])
        return finding

    snap_mtime = datetime.datetime.fromtimestamp(snapshot.stat().st_mtime, datetime.timezone.utc)
    hand_mtime = datetime.datetime.fromtimestamp(handoff.stat().st_mtime, datetime.timezone.utc)
    lag = (hand_mtime - snap_mtime).total_seconds() / 60.0
    finding["snapshot_lag_minutes"] = round(lag, 1)

    if lag > SNAPSHOT_LAG_TOLERANCE_MINUTES:
        finding["state"] = "stale"
        finding["problems"].append(
            f"snapshot is {lag:.0f} min older than the handoff; run `python build_cfb_snapshot.py`"
        )
    elif abs(lag) < 1.0:
        finding["state"] = "unknown"

    return finding


def build_report(now: datetime.datetime | None = None, root: pathlib.Path = pathlib.Path(".")) -> dict[str, Any]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    results, generated = load_handoff_results(root / HANDOFF_PATH.name)

    payloads = [inspect_payload(key, results, now, root) for key in _sports()]
    patch = inspect_patch_layer(generated, now, root)

    problems = [p for f in payloads for p in f["problems"]] + list(patch["problems"])
    stale = [f for f in payloads if f["state"] in ("stale", "missing", "unreadable")]
    stale_patch = patch["state"] in ("stale", "missing")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "state": "stale" if (stale or stale_patch) else ("aging" if problems else "ok"),
        "handoff_results": len(results),
        "payloads": payloads,
        "patch_layer": patch,
        "problem_count": len(problems),
    }


def render(report: dict[str, Any]) -> str:
    lines = [f"data freshness: {report['state'].upper()}  ({report['generated_at']})", ""]
    for finding in report["payloads"]:
        age = finding.get("age_hours")
        age_text = f"{age:.1f}h" if isinstance(age, (int, float)) else "unknown"
        lines.append(
            f"  {finding['sport']:<6} {finding['state']:<10} age={age_text:<9}"
            f" matches={finding.get('matches', 0):<4}"
            f" unsettled={finding.get('unsettled_after_handoff', 0)}"
            f" (handoff repaired {finding.get('repaired_by_handoff', 0)})"
        )
        for problem in finding["problems"]:
            lines.append(f"           - {problem}")
        for example in finding.get("examples", []):
            lines.append(
                f"           . {str(example.get('kickoff'))[:16]} "
                f"{example.get('home')} vs {example.get('away')} [{example.get('status')}]"
            )
    patch = report["patch_layer"]
    lines.append("")
    lines.append(f"  patch  {patch['state']:<10} handoff results={report['handoff_results']}")
    for problem in patch["problems"]:
        lines.append(f"           - {problem}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", help="write the JSON report here")
    parser.add_argument("--root", default=".", help="directory holding the payloads")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="always exit 0; use while the check is being introduced",
    )
    parser.add_argument("--github", action="store_true", help="emit GitHub Actions annotations")
    args = parser.parse_args(argv)

    try:
        report = build_report(root=pathlib.Path(args.root))
    except Exception as exc:  # the check must never be the thing that breaks a run
        print(f"data_freshness: could not build a report: {exc}")
        return 2

    print(render(report))

    if args.output:
        pathlib.Path(args.output).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    if args.github:
        level = "error" if report["state"] == "stale" else "warning"
        for finding in report["payloads"]:
            for problem in finding["problems"]:
                print(f"::{level}::{finding['sport']}: {problem}")
        for problem in report["patch_layer"]["problems"]:
            print(f"::{level}::patch layer: {problem}")

    if args.warn_only:
        return 0
    return 1 if report["state"] == "stale" else 0


if __name__ == "__main__":
    raise SystemExit(main())
