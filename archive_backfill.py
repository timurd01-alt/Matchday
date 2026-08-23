"""Seed the game archive from sources that cost no provider quota.

`game_archive.record_build()` captures games from today forward. This script
fills in the past, and it is deliberately restricted to sources that are either
already on disk or freely downloadable without a key:

  openfootball   openfootball_soccer_history_cache.json  25,452 soccer games
  balldontlie    balldontlie_season_*_cache.json         MLB / NBA / NFL seasons
  college        college_ncaa{m,f}_bundle_v*_cache.json  NCAAM / NCAAF seasons
  nflverse       nflverse_pbp_*.csv.gz                   NFL games from play-by-play
  data           data_*.json                             the current build payloads

Every one of those files was already paid for -- either fetched by a previous
run and cached, or published under an open licence. Re-reading them costs
nothing, which matters because the providers that hold this history are exactly
the ones this repository keeps running out of: AGENTS.md records CFBD going dark
for three weeks and CBBD sitting at zero.

`backfill_history.py` is the deliberate opposite of this script: it spends real
quota to pull seasons that no free source covers, and it feeds Elo directly.
The two are complementary, and this one is safe to run whenever.

## Why the caches are read directly rather than re-fetched

Confirmed by inspection, `balldontlie_season_mlb_cache.json` (1,611 games),
`college_ncaam_bundle_v5_cache.json` (6,317) and the `data_*.json` payloads all
store matches in the *same* normalized shape the fetch pipeline builds --
`{id, provider_id, kickoff, status, score:{home,away}, home:{name,code}, ...}`.
`game_archive.normalize_match()` therefore reads them as-is, with no
per-provider mapping to get wrong. openfootball and nflverse are the two that
need adapters, and both are open data.

## What this does not do yet

The `box` table stays empty. None of the free sources above carries team box
detail for basketball: the college bundles hold scores only, and CBBD's box
endpoint is quota-limited and unverified (see `ncaam_advanced_metrics.py`,
`MAPPING_VERIFIED = False`). nflverse *does* carry play-by-play detail, but NFL
efficiency already has a home in `advanced_metrics_nfl.json` via
`nflverse_team_profiles`, and duplicating it here would create a second number
for the same thing. Adjusted-efficiency ratings need a basketball box source;
finding a free one is the open task.

Usage:
    python archive_backfill.py --all
    python archive_backfill.py --source openfootball --source balldontlie
    python archive_backfill.py --all --dry-run
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import game_archive


# openfootball's competition labels -> Matchday comp keys. Anything not listed
# is skipped rather than guessed at: filing a game under the wrong competition
# is worse than not archiving it, because the archive is meant to be the
# trustworthy copy.
OPENFOOTBALL_COMPS = {
    "EPL": "EPL",
    "PL": "EPL",
    "LALIGA": "LALIGA",
    "PD": "LALIGA",
    "SERIEA": "SERIEA",
    "SA": "SERIEA",
    "BUNDESLIGA": "BUNDESLIGA",
    "BL1": "BUNDESLIGA",
    "LIGUE1": "LIGUE1",
    "FL1": "LIGUE1",
    "UCL": "UCL",
    "CL": "UCL",
    "WC": "WC",
}


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ! {path.name}: unreadable ({type(exc).__name__}: {exc})")
        return None


def _matches_of(payload: Any) -> list[dict[str, Any]]:
    """Pull the match list out of a cache, which is either a bare list or a dict."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("matches", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def source_openfootball() -> list[dict[str, Any]]:
    """25k+ historical soccer games, open-licensed, already on disk.

    These rows carry their own `competition` and `season` and use only
    `home.name` / `away.name` -- no team codes, no venue, no provider id. The
    row's own stable `id` is passed through as the provider id so re-running
    this never mints a duplicate.
    """
    path = Path("openfootball_soccer_history_cache.json")
    if not path.exists():
        print("  - openfootball cache not present; skipping")
        return []
    payload = _load_json(path)
    if payload is None:
        return []
    licence = payload.get("license") if isinstance(payload, dict) else None
    if isinstance(payload, dict) and payload.get("research_only"):
        print(f"  note: openfootball rows are marked research_only (licence: {licence})")

    rows: list[dict[str, Any]] = []
    skipped_comp: set[str] = set()
    for row in _matches_of(payload):
        raw_comp = str(row.get("competition") or "").strip().upper()
        comp = OPENFOOTBALL_COMPS.get(raw_comp)
        if not comp:
            skipped_comp.add(raw_comp)
            continue
        normalized = game_archive.normalize_match(comp, row, source="openfootball")
        if normalized:
            rows.append(normalized)
    if skipped_comp:
        print(f"  note: skipped unmapped competitions {sorted(skipped_comp)[:12]}")
    return rows


def source_balldontlie() -> list[dict[str, Any]]:
    """MLB / NBA / NFL games from caches a previous run already paid for."""
    rows: list[dict[str, Any]] = []
    for path in sorted(Path(".").glob("balldontlie_*_cache.json")):
        stem = path.stem                       # balldontlie_season_mlb_cache
        parts = stem.split("_")
        if len(parts) < 4:
            continue
        comp = parts[-2].upper()
        payload = _load_json(path)
        if payload is None:
            continue
        found = 0
        for match in _matches_of(payload):
            normalized = game_archive.normalize_match(comp, match, source="balldontlie")
            if normalized:
                rows.append(normalized)
                found += 1
        print(f"  {path.name}: {found} finished")
    return rows


def source_college() -> list[dict[str, Any]]:
    """NCAAM / NCAAF games from the cached CFBD / CBBD bundles.

    Only the highest bundle version present is read. The older `_v2`/`_v4`
    copies are the same seasons at an earlier point in time, and reading them
    all would just re-offer games the newest bundle already has.
    """
    rows: list[dict[str, Any]] = []
    for comp, pattern in (("NCAAM", "college_ncaam_bundle_v*_cache.json"),
                          ("NCAAF", "college_ncaaf_bundle_v*_cache.json")):
        bundles = sorted(Path(".").glob(pattern))
        if not bundles:
            print(f"  - no {comp} bundle present; skipping")
            continue
        newest = bundles[-1]
        payload = _load_json(newest)
        if payload is None:
            continue
        found = 0
        for match in _matches_of(payload):
            normalized = game_archive.normalize_match(comp, match, source=comp.lower())
            if normalized:
                rows.append(normalized)
                found += 1
        print(f"  {newest.name}: {found} finished")
    return rows


def source_nflverse() -> list[dict[str, Any]]:
    """NFL games rebuilt from open play-by-play files.

    The pbp file has one row per play, so a game's final score is the score
    after its last play. `total_home_score` / `total_away_score` are the running
    totals, and the file is in play order, so keeping the last row seen per
    game_id yields the final. Neither `home_score` nor `away_score` is used:
    both are game-level columns repeated on every row, and taking a running
    total's last value is verifiable from the data itself.
    """
    rows: list[dict[str, Any]] = []
    for path in sorted(Path(".").glob("nflverse_pbp_*.csv.gz")):
        finals: dict[str, dict[str, Any]] = {}
        try:
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
                for play in csv.DictReader(handle):
                    game_id = play.get("game_id")
                    if not game_id:
                        continue
                    finals[game_id] = play
        except (OSError, csv.Error) as exc:
            print(f"  ! {path.name}: unreadable ({type(exc).__name__}: {exc})")
            continue

        found = 0
        for game_id, play in finals.items():
            date = str(play.get("game_date") or "")
            if len(date) < 10:
                continue
            try:
                home_score = int(float(play.get("total_home_score") or 0))
                away_score = int(float(play.get("total_away_score") or 0))
            except (TypeError, ValueError):
                continue
            home, away = str(play.get("home_team") or ""), str(play.get("away_team") or "")
            if not home or not away:
                continue
            kickoff = f"{date[:10]}T00:00:00Z"
            week, season_type = play.get("week"), str(play.get("season_type") or "")
            rows.append({
                "game_id": game_archive.make_game_id("NFL", kickoff, home, away, game_id),
                "comp": "NFL",
                "season": game_archive.season_for("NFL", kickoff),
                "date_utc": kickoff,
                "stage": f"Week {week}" if season_type == "REG" and week else season_type,
                "venue": str(play.get("stadium") or ""),
                "home_name": home,
                "home_code": home,
                "away_name": away,
                "away_code": away,
                "home_score": home_score,
                "away_score": away_score,
                "status": "FINISHED",
                "source": "nflverse",
                "first_seen": game_archive._now(),
            })
            found += 1
        print(f"  {path.name}: {found} games")
    return rows


def source_data() -> list[dict[str, Any]]:
    """The current build payloads, for competitions with no cache of their own."""
    rows: list[dict[str, Any]] = []
    for path in sorted(Path(".").glob("data_*.json")):
        comp = path.stem[len("data_"):].upper()
        payload = _load_json(path)
        if payload is None:
            continue
        found = 0
        for match in _matches_of(payload):
            normalized = game_archive.normalize_match(comp, match)
            if normalized:
                rows.append(normalized)
                found += 1
        if found:
            print(f"  {path.name}: {found} finished")
    return rows


SOURCES: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "openfootball": source_openfootball,
    "balldontlie": source_balldontlie,
    "college": source_college,
    "nflverse": source_nflverse,
    "data": source_data,
}

# Which source owns a (competition, season) when more than one covers it.
# Lower number wins.
#
# This is not a quality judgement, it is an identity one. Two sources describe
# the same game with different ids and different team naming -- nflverse calls
# it `2021_01_ARI_TEN` between "TEN" and "ARI", BallDontLie calls it
# `bdl-nfl-423945` between "Tennessee Titans" and "Arizona Cardinals" -- so
# nothing downstream can tell they are one game, and archiving both silently
# doubles the season. Measured before this rule existed: NFL collected 1,709
# rows for 1,424 real games, every 2025 game counted twice.
#
# The pipeline sources rank above the bulk ones because `record_build()` keeps
# collecting those competitions every hour using *their* ids. If a season were
# seeded from openfootball or nflverse instead, the forward hook would re-add
# each game under a second id from the next run onward -- turning a one-time
# duplicate into a permanent one. The bulk sources are therefore what fills
# seasons the live pipeline does not reach, which is exactly the history this
# archive was built to hold.
SOURCE_PRECEDENCE: dict[str, int] = {
    "balldontlie": 0,
    "cbbd": 0,
    "cfbd": 0,
    "football_data": 0,
    "api_football": 0,
    "nflverse": 5,
    "openfootball": 5,
}
_DEFAULT_PRECEDENCE = 1   # an unrecognised live pipeline source

# The same provider reaches this script under several spellings: the caches are
# labelled by the reader that loaded them ("balldontlie", "ncaam"), while rows
# taken from a `data_*.json` payload carry that payload's own `data_source`
# ("BALLDONTLIE", "CollegeBasketballData"). Those are not competing sources --
# they are one provider, with one id scheme, so `game_id` already dedupes them.
#
# Resolving them as rivals is actively destructive, and was: keying on the raw
# label made "BALLDONTLIE" (113 rows from data_mlb.json) beat "balldontlie"
# (1,698 rows from the season cache) and threw away most of MLB history. Only
# genuinely different id namespaces may be resolved against each other.
_SOURCE_ALIASES: dict[str, str] = {
    "balldontlie": "balldontlie",
    "bdl": "balldontlie",
    "ncaam": "cbbd",
    "cbbd": "cbbd",
    "collegebasketballdata": "cbbd",
    "ncaaf": "cfbd",
    "cfbd": "cfbd",
    "collegefootballdata": "cfbd",
    "football_data": "football_data",
    "football-data": "football_data",
    "footballdata": "football_data",
    "api_football": "api_football",
    "apisports": "api_football",
    "api-football": "api_football",
    "nflverse": "nflverse",
    "openfootball": "openfootball",
}


def canonical_source(source: Any) -> str:
    """Collapse a source label to the provider whose id scheme it uses."""
    key = str(source or "").strip().lower().replace(" ", "")
    return _SOURCE_ALIASES.get(key, key or "unknown")


def _precedence(source: str) -> int:
    return SOURCE_PRECEDENCE.get(source, _DEFAULT_PRECEDENCE)


def resolve_overlaps(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep one provider per (competition, season). Returns (kept, notes).

    Scoped to the season rather than the whole competition on purpose: nflverse
    holds 2021-22 through 2024-25 for NFL and BallDontLie only 2025-26, so a
    blanket per-competition winner would throw away four seasons that nothing
    else covers.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["comp"]), str(row["season"])), []).append(row)

    kept: list[dict[str, Any]] = []
    notes: list[str] = []
    for (comp, season), season_rows in sorted(grouped.items()):
        by_provider: dict[str, dict[str, dict[str, Any]]] = {}
        for row in season_rows:
            provider = canonical_source(row.get("source"))
            # Deduped here as well as below, so a provider's row count reflects
            # distinct games and cannot be inflated by appearing in two caches.
            by_provider.setdefault(provider, {})[str(row["game_id"])] = row
        if len(by_provider) == 1:
            kept.extend(next(iter(by_provider.values())).values())
            continue
        winner = min(by_provider, key=lambda name: (_precedence(name), name))
        kept.extend(by_provider[winner].values())
        dropped = {name: len(items) for name, items in by_provider.items() if name != winner}
        notes.append(f"{comp} {season}: kept {len(by_provider[winner])} from {winner!r}; "
                     f"dropped duplicates {dropped}")
    return kept, notes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", action="append", choices=sorted(SOURCES), default=None,
                        help="run one source; repeatable. Default is --all.")
    parser.add_argument("--all", action="store_true", help="run every free source")
    parser.add_argument("--dry-run", action="store_true", help="report what would be archived, write nothing")
    args = parser.parse_args(argv)

    names = sorted(SOURCES) if (args.all or not args.source) else args.source
    collected: list[dict[str, Any]] = []
    for name in names:
        print(f"[{name}]")
        collected.extend(SOURCES[name]())

    if not collected:
        print("\nnothing to archive")
        return 0

    resolved, notes = resolve_overlaps(collected)
    if notes:
        print("\noverlapping sources resolved:")
        for note in notes:
            print(f"  {note}")

    unique: dict[str, dict[str, Any]] = {}
    for row in resolved:
        unique.setdefault(str(row["game_id"]), row)
    print(f"\n{len(collected)} row(s) collected, {len(resolved)} after overlap resolution, "
          f"{len(unique)} unique game(s)")

    if args.dry_run:
        by_comp: dict[str, int] = {}
        for row in unique.values():
            by_comp[str(row["comp"])] = by_comp.get(str(row["comp"]), 0) + 1
        for comp in sorted(by_comp):
            print(f"  {comp:12} {by_comp[comp]}")
        print("dry run: nothing written")
        return 0

    result = game_archive.upsert_games(unique.values())
    print(f"archived: +{result['added']} new, {result['unchanged']} already present, "
          f"{result['conflicts']} conflict(s)")

    report = game_archive.validate()
    for problem in report["problems"]:
        print(f"::error::{problem}")
    if report["problems"]:
        return 1
    print(f"archive now holds {report['games']} game(s), {report['box_rows']} box row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
