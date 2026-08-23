"""Matchday's own durable record of every game it has ever seen.

## Why this exists

Every raw input this repository has ever pulled is thrown away. Confirmed by
reading `.gitignore` against `git ls-files`: `data_*.json`, every `*_cache.json`
bundle, `player_db_*.json` and the nflverse play-by-play are all ignored, and
what *is* tracked -- `ratings_elo.json`, `picks_log_*.json`, the forecast
ledgers -- is derived. The raw games those artifacts were computed from exist
nowhere afterwards.

Three consequences, all of them already observed in this repository:

1. **No rating can ever be recomputed.** `ratings_elo.json` is the accumulated
   output of `update_elo()` over games that no longer exist. A bug in the
   update rule is unfixable retroactively; the only repair is to re-pull years
   of history from providers.

2. **A one-time quota spend produced a one-time artifact.** `backfill_history.py`
   pulled "tens of thousands of games for MLB/NBA alone", fed each one to Elo,
   and kept none of them. Re-running it is the only way to get that data back,
   at full quota cost, from providers whose free tiers have since tightened.

3. **When a provider goes dark, so does the sport.** AGENTS.md records CFBD
   spending its 1,000-call month by 2026-08-10 and going dark for three weeks.
   `ncaam_advanced_metrics.py` -- the adjusted-efficiency model, this
   repository's KenPom analogue -- opens by stating that "nothing has ever fed
   it live data", because CBBD sits at zero remaining calls. A working model
   with no reachable inputs.

The archive is the fix for all three: the games are written down once, in git,
and every rating becomes a pure function of a local file instead of a live
provider call.

## Why the forward path is free

The hourly build already holds finished games with final scores -- 113 of them
in `data_mlb.json` at the time this module was written -- and overwrites that
file on the next run. `record_build()` is called from `build()` just before
that write, so archiving costs **zero additional provider calls**. It captures
what the fetch had anyway and was about to discard.

## Two tables, because scores alone cannot produce KenPom

`archive/games/<comp>/<season>.csv` holds one row per game: teams, final score,
date, venue, stage. Every provider returns this, so it is always populated.

`archive/box/<comp>/<season>.csv` holds one row per team-game of box detail:
field goals, turnovers, rebounds, free throws. Adjusted-efficiency ratings need
*possessions*, and possessions are `FGA - ORB + TO + 0.475*FTA` -- none of
which is derivable from a final score. The hourly build payload carries no box
detail for any sport (verified against data_ncaam.json / data_nfl.json:
`matches[].home` holds standings context only), so this table is fed by the
free bulk sources in `archive_backfill.py`, not by the forward hook. Splitting
the two means a thin provider still fills `games` rather than contributing
nothing.

## Why CSV, and why sorted by date

These files are read by models and diffed by humans, and they must stay cheap
in git. Rows are sorted by `(date_utc, game_id)`, so a normal day's capture
appends at the end of the newest partition and git stores a small delta.
Partitioning by competition and season bounds any single file: a rewrite
touches one season, never the whole archive.

## Why a settled score is never silently changed

`upsert_games()` refuses to overwrite the score of a game already recorded
FINISHED. This is the same principle the forecast ledgers enforce with a hash
chain -- evidence is written once -- but the failure it guards against is
specific and real: providers do revise box scores, and a silent revision would
retroactively alter the inputs behind picks that were already graded, with no
trace that anything moved. Conflicts are written to `archive/conflicts.jsonl`
for a human to look at, and the original row stands.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = 1

ARCHIVE_ROOT = Path("archive")
GAMES_DIR = ARCHIVE_ROOT / "games"
BOX_DIR = ARCHIVE_ROOT / "box"
CONFLICTS_PATH = ARCHIVE_ROOT / "conflicts.jsonl"

# Only these are archived. LIVE and UPCOMING rows carry a score that is not the
# final one, and writing them would defeat the whole point of a settled record.
FINISHED_STATUSES = {"FINISHED", "FT", "FINAL", "COMPLETED", "AET", "PEN"}

GAME_FIELDS: tuple[str, ...] = (
    "game_id",
    "comp",
    "season",
    "date_utc",
    "stage",
    "venue",
    "home_name",
    "home_code",
    "away_name",
    "away_code",
    "home_score",
    "away_score",
    "status",
    "source",
    "first_seen",
)

BOX_FIELDS: tuple[str, ...] = (
    "game_id",
    "comp",
    "season",
    "date_utc",
    "team_name",
    "team_code",
    "side",          # "home" | "away"
    "points",
    "fgm",
    "fga",
    "three_pm",
    "three_pa",
    "ftm",
    "fta",
    "orb",
    "drb",
    "turnovers",
    "assists",
    "possessions",   # blank unless derivable; see estimate_possessions()
    "source",
    "first_seen",
)

# Competitions whose season spans a calendar boundary, with the month (1-12) on
# or after which a game belongs to the season named for that starting year.
# MLB runs inside one calendar year, so it is deliberately absent.
_SEASON_START_MONTH: dict[str, int] = {
    "NFL": 3,
    "NCAAF": 3,
    "NBA": 7,
    "NCAAM": 7,
    "NHL": 7,
    "EPL": 7,
    "LALIGA": 7,
    "SERIEA": 7,
    "BUNDESLIGA": 7,
    "LIGUE1": 7,
    "UCL": 7,
}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def season_for(comp: str, date_utc: str) -> str:
    """The season a game belongs to, as a string.

    Returned as a string, not an int, because a cross-year season is written
    "2025-26" and a single-year one "2026", and a partition filename should say
    which it is without the reader having to know the sport's calendar.

    `season_context` in the build payload would be the natural source, but it is
    None for at least NCAAM (verified against data_ncaam.json), so the date is
    the only field that is reliably present.
    """
    year, month = int(date_utc[0:4]), int(date_utc[5:7])
    start_month = _SEASON_START_MONTH.get(comp.upper())
    if start_month is None:
        return str(year)
    start_year = year if month >= start_month else year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def make_game_id(comp: str, date_utc: str, home: str, away: str, provider_id: Any = None) -> str:
    """A stable identifier for a game, provider id preferred.

    The provider id is used when present because it survives a team being
    renamed. When it is absent the fallback hashes competition, calendar date
    and both team slugs -- deliberately the date and not the timestamp, since
    providers routinely nudge a kickoff time by minutes and that must not mint a
    second row for a game already recorded.
    """
    if provider_id not in (None, ""):
        return f"{comp.lower()}-{_slug(provider_id)}"
    material = f"{comp.lower()}|{date_utc[:10]}|{_slug(home)}|{_slug(away)}"
    return f"{comp.lower()}-x{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def partition_path(kind: str, comp: str, season: str) -> Path:
    root = GAMES_DIR if kind == "games" else BOX_DIR
    return root / comp.lower() / f"{season}.csv"


def read_partition(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_partition(path: Path, fields: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    """Write a partition atomically, sorted, with LF endings.

    `newline=""` plus an explicit `lineterminator` keeps the bytes identical on
    Windows and Linux. AGENTS.md documents what byte drift costs here: a CRLF
    checkout produced a second digest for an identical model artifact and cost
    the MLB promotion gate weeks of evidence it had to discard. These files are
    not hashed into governance today, but they are compared across a developer
    checkout and CI, and a whole-file diff every run would also defeat the
    small-delta design above.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        rows,
        key=lambda row: (
            str(row.get("date_utc") or ""),
            str(row.get("game_id") or ""),
            str(row.get("side") or ""),
        ),
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in ordered:
            writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in fields})
    os.replace(tmp, path)


def _record_conflict(kind: str, existing: dict[str, Any], incoming: dict[str, Any], note: str) -> None:
    CONFLICTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _now(),
        "kind": kind,
        "note": note,
        "game_id": existing.get("game_id"),
        "existing": existing,
        "incoming": incoming,
    }
    with CONFLICTS_PATH.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _is_finished(status: Any) -> bool:
    return str(status or "").strip().upper() in FINISHED_STATUSES


def normalize_match(comp: str, match: dict[str, Any], source: str = "") -> dict[str, Any] | None:
    """Turn one build-payload match into an archive row, or None if not settled.

    Returns None rather than raising for anything unusable. A fetch that hands
    this module a half-populated fixture must not take the hourly build down --
    the archive is a side-effect of that build, never a gate on it.
    """
    if not _is_finished(match.get("status")):
        return None
    kickoff = str(match.get("kickoff") or "")
    if len(kickoff) < 10:
        return None
    home, away = match.get("home") or {}, match.get("away") or {}
    score = match.get("score") or {}
    home_score, away_score = score.get("home"), score.get("away")
    if home_score is None or away_score is None:
        return None
    home_name, away_name = str(home.get("name") or ""), str(away.get("name") or "")
    if not home_name or not away_name:
        return None
    return {
        "game_id": make_game_id(comp, kickoff, home_name, away_name,
                                match.get("provider_id") or match.get("id")),
        "comp": comp.upper(),
        "season": season_for(comp, kickoff),
        "date_utc": kickoff,
        "stage": str(match.get("stage") or ""),
        "venue": str(match.get("venue") or ""),
        "home_name": home_name,
        "home_code": str(home.get("code") or ""),
        "away_name": away_name,
        "away_code": str(away.get("code") or ""),
        "home_score": int(home_score),
        "away_score": int(away_score),
        "status": str(match.get("status") or "").upper(),
        "source": source or str(match.get("data_source") or ""),
        "first_seen": _now(),
    }


def upsert_games(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Merge rows into their season partitions. Returns a counts summary.

    A row already present keeps its original `first_seen` -- that field records
    when Matchday first observed the game, and refreshing it every hour would
    both destroy the provenance and rewrite every line of the partition on every
    run.
    """
    added = kept = conflicted = 0
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["comp"]), str(row["season"])), []).append(row)

    for (comp, season), incoming_rows in grouped.items():
        path = partition_path("games", comp, season)
        existing = {str(row["game_id"]): row for row in read_partition(path)}
        changed = False
        for incoming in incoming_rows:
            game_id = str(incoming["game_id"])
            prior = existing.get(game_id)
            if prior is None:
                existing[game_id] = incoming
                added += 1
                changed = True
                continue
            same_score = (str(prior.get("home_score")) == str(incoming.get("home_score"))
                          and str(prior.get("away_score")) == str(incoming.get("away_score")))
            if same_score:
                kept += 1
                continue
            # A settled score moved. Keep the original, leave a trace.
            _record_conflict("score_revision", prior, incoming,
                             "provider reported a different final score for a game already archived")
            conflicted += 1
        if changed:
            _write_partition(path, GAME_FIELDS, existing.values())
    return {"added": added, "unchanged": kept, "conflicts": conflicted}


def record_build(comp: str, matches: Iterable[dict[str, Any]], source: str = "") -> dict[str, int]:
    """Archive every finished game in one competition build. Never raises.

    Called from `fetch_data.build()` immediately before `data_<comp>.json` is
    written. It is wrapped defensively because that build publishes the live
    site: an archive bug must degrade to "nothing archived this run", never to a
    failed deploy. The next run re-archives whatever it missed, since the games
    it reads are finished and therefore still present in the payload.
    """
    try:
        rows = [row for row in (normalize_match(comp, match, source) for match in matches) if row]
        if not rows:
            return {"added": 0, "unchanged": 0, "conflicts": 0}
        return upsert_games(rows)
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"  archive: skipped ({type(exc).__name__}: {exc})")
        return {"added": 0, "unchanged": 0, "conflicts": 0, "error": 1}


def estimate_possessions(row: dict[str, Any]) -> float | None:
    """Dean Oliver's possession estimate, or None when an input is missing.

    `FGA - ORB + TO + 0.475*FTA`. Returns None rather than substituting zero for
    an absent field: a zero would silently understate possessions and inflate
    every efficiency rating computed from the row, which is precisely the kind
    of quiet degradation `ncaam_advanced_metrics.py` refuses to ship.
    """
    try:
        fga, orb, tov, fta = (float(row[key]) for key in ("fga", "orb", "turnovers", "fta"))
    except (KeyError, TypeError, ValueError):
        return None
    return round(fga - orb + tov + 0.475 * fta, 2)


def upsert_box(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Merge team-game box rows into their season partitions.

    Keyed on `(game_id, side)` because a game contributes exactly two rows.
    Possessions are filled in here when derivable, so every consumer reads the
    same number instead of each one re-deriving it slightly differently.
    """
    added = kept = 0
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        row.setdefault("first_seen", _now())
        if not row.get("possessions"):
            possessions = estimate_possessions(row)
            row["possessions"] = "" if possessions is None else possessions
        grouped.setdefault((str(row["comp"]), str(row["season"])), []).append(row)

    for (comp, season), incoming_rows in grouped.items():
        path = partition_path("box", comp, season)
        existing = {(str(row["game_id"]), str(row.get("side"))): row for row in read_partition(path)}
        changed = False
        for incoming in incoming_rows:
            key = (str(incoming["game_id"]), str(incoming.get("side")))
            if key in existing:
                kept += 1
                continue
            existing[key] = incoming
            added += 1
            changed = True
        if changed:
            _write_partition(path, BOX_FIELDS, existing.values())
    return {"added": added, "unchanged": kept}


def load_games(comp: str | None = None, season: str | None = None) -> list[dict[str, str]]:
    """Read archived games back, optionally filtered. The models' entry point."""
    return _load(GAMES_DIR, comp, season)


def load_box(comp: str | None = None, season: str | None = None) -> list[dict[str, str]]:
    return _load(BOX_DIR, comp, season)


def _load(root: Path, comp: str | None, season: str | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not root.exists():
        return rows
    for comp_dir in sorted(root.iterdir()):
        if not comp_dir.is_dir() or (comp and comp_dir.name != comp.lower()):
            continue
        for partition in sorted(comp_dir.glob("*.csv")):
            if season and partition.stem != season:
                continue
            rows.extend(read_partition(partition))
    return rows


def validate() -> dict[str, Any]:
    """Check every partition for the damage that would make the archive untrustworthy.

    Run in CI before the archive is committed. It deliberately does not check
    "did this run add rows" -- a quiet day legitimately adds none -- only that
    what is on disk is internally sound: no duplicate ids, no unparseable
    scores, no row filed under the wrong season or competition.
    """
    problems: list[str] = []
    seen: set[str] = set()
    games = 0
    for comp_dir in sorted(GAMES_DIR.iterdir()) if GAMES_DIR.exists() else []:
        if not comp_dir.is_dir():
            continue
        for partition in sorted(comp_dir.glob("*.csv")):
            for index, row in enumerate(read_partition(partition), 2):
                games += 1
                where = f"{partition.as_posix()}:{index}"
                game_id = str(row.get("game_id") or "")
                if not game_id:
                    problems.append(f"{where}: missing game_id")
                elif game_id in seen:
                    problems.append(f"{where}: duplicate game_id {game_id}")
                seen.add(game_id)
                if str(row.get("comp") or "").lower() != comp_dir.name:
                    problems.append(f"{where}: comp {row.get('comp')!r} filed under {comp_dir.name}")
                if str(row.get("season") or "") != partition.stem:
                    problems.append(f"{where}: season {row.get('season')!r} filed in {partition.name}")
                for field in ("home_score", "away_score"):
                    try:
                        int(str(row.get(field)))
                    except (TypeError, ValueError):
                        problems.append(f"{where}: unparseable {field} {row.get(field)!r}")
                if not _is_finished(row.get("status")):
                    problems.append(f"{where}: archived a non-final status {row.get('status')!r}")

    box_rows = 0
    box_seen: set[tuple[str, str]] = set()
    for comp_dir in sorted(BOX_DIR.iterdir()) if BOX_DIR.exists() else []:
        if not comp_dir.is_dir():
            continue
        for partition in sorted(comp_dir.glob("*.csv")):
            for index, row in enumerate(read_partition(partition), 2):
                box_rows += 1
                key = (str(row.get("game_id") or ""), str(row.get("side") or ""))
                if key in box_seen:
                    problems.append(f"{partition.as_posix()}:{index}: duplicate box row for {key}")
                box_seen.add(key)

    return {"games": games, "box_rows": box_rows, "problems": problems}


def summary() -> dict[str, Any]:
    """Per-competition counts, for the workflow log and `next_task.py`."""
    competitions: dict[str, Any] = {}
    for row in load_games():
        entry = competitions.setdefault(row["comp"], {"games": 0, "seasons": set()})
        entry["games"] += 1
        entry["seasons"].add(row["season"])
    total = sum(entry["games"] for entry in competitions.values())
    for entry in competitions.values():
        entry["seasons"] = sorted(entry["seasons"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "total_games": total,
        "competitions": competitions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Inspect or validate the Matchday game archive.")
    parser.add_argument("command", choices=("validate", "summary"))
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = validate()
        print(f"archive: {report['games']} game(s), {report['box_rows']} box row(s)")
        for problem in report["problems"]:
            print(f"::error::{problem}")
        if report["problems"]:
            print(f"{len(report['problems'])} problem(s) found")
            return 1
        print("archive verified")
        return 0

    print(json.dumps(summary(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
