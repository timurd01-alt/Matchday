"""Seed the game archive from sources that cost no provider quota.

`game_archive.record_build()` captures games from today forward. This script
fills in the past, and it is deliberately restricted to sources that are either
already on disk or freely downloadable without a key:

  college        college_ncaa{m,f}_bundle_v*_cache.json  NCAAM / NCAAF seasons
  data           data_*.json                             the current build payloads

Every one of those files was already paid for by a previous run. Re-reading them costs
nothing, which matters because the providers that hold this history are exactly
the ones this repository keeps running out of: AGENTS.md records CFBD going dark
for three weeks and CBBD sitting at zero.

`backfill_history.py` is the deliberate opposite of this script: it spends real
quota to pull seasons that no free source covers, and it feeds Elo directly.
The two are complementary, and this one is safe to run whenever.

## Why the caches are read directly rather than re-fetched

Confirmed by inspection, `college_ncaam_bundle_v5_cache.json` (6,317) and the
`data_*.json` payloads store matches in the *same* normalized shape the fetch
pipeline builds -- `{id, provider_id, kickoff, status, score:{home,away},
home:{name,code}, ...}`. `game_archive.normalize_match()` therefore reads them
as-is, with no per-provider mapping to get wrong.

## What this does not do yet

The `box` table stays empty. None of the free sources above carries team box
detail for basketball: the college bundles hold scores only, and CBBD's box
endpoint is quota-limited and unverified (see `ncaam_advanced_metrics.py`,
`MAPPING_VERIFIED = False`). Adjusted-efficiency ratings need a basketball box
source; finding a free one is the open task.

Usage:
    python archive_backfill.py --all
    python archive_backfill.py --source college
    python archive_backfill.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import game_archive


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
    "college": source_college,
    "data": source_data,
}

# Which source owns a (competition, season) when more than one covers it.
# Lower number wins.
#
# This is an identity rule, not a quality judgement. Two sources describe the
# same game with different ids and different team naming, so nothing downstream
# can tell they are one game, and archiving both silently doubles the season.
# The pipeline sources rank first because `record_build()` keeps collecting
# those competitions every hour using *their* ids.
SOURCE_PRECEDENCE: dict[str, int] = {
    "cbbd": 0,
    "cfbd": 0,
}
_DEFAULT_PRECEDENCE = 1   # an unrecognised source

# The same provider reaches this script under several spellings: the caches are
# labelled by the reader that loaded them ("ncaam"), while rows taken from a
# `data_*.json` payload carry that payload's own `data_source`
# ("CollegeBasketballData"). Those are one provider with one id scheme, so
# `game_id` already dedupes them; resolving them as rivals would throw games away.
_SOURCE_ALIASES: dict[str, str] = {
    "ncaam": "cbbd",
    "cbbd": "cbbd",
    "collegebasketballdata": "cbbd",
    "ncaaf": "cfbd",
    "cfbd": "cfbd",
    "collegefootballdata": "cfbd",
}


def canonical_source(source: Any) -> str:
    """Collapse a source label to the provider whose id scheme it uses."""
    key = str(source or "").strip().lower().replace(" ", "")
    return _SOURCE_ALIASES.get(key, key or "unknown")


def _precedence(source: str) -> int:
    return SOURCE_PRECEDENCE.get(source, _DEFAULT_PRECEDENCE)


def resolve_overlaps(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep one provider per (competition, season). Returns (kept, notes).

    Scoped to the season rather than the whole competition on purpose: a source
    that covers only older seasons must not be discarded wholesale because
    another covers the current one.
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
