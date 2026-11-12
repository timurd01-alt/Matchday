"""Seed the game archive from sources that cost no provider quota.

`game_archive.record_build()` captures games from today forward. This script
fills in the past, and it is deliberately restricted to sources that are either
already on disk or freely downloadable without a key:

  college        college_ncaa{m,f}_bundle_v*_cache.json  NCAAM / NCAAF seasons
  data           data_*.json                             the current build payloads
  handoff        trdlab_picks.json -> results         every football final this season

Every one of those files was already paid for by a previous run. Re-reading them costs
nothing, which matters because the providers that hold this history are exactly
the ones this repository keeps running out of: AGENTS.md records CFBD going dark
for three weeks and CBBD sitting at zero.

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


def _short_names(comp: str) -> list[str]:
    """Every team name the pipeline itself uses for `comp`: its payload and the archive."""
    payload = _load_json(Path(f"data_{comp.lower()}.json"))
    names = set()
    for match in _matches_of(payload) if payload is not None else []:
        for side in ("home", "away"):
            name = (match.get(side) or {}).get("name")
            if name:
                names.add(str(name))
    for row in game_archive.load_games(comp):
        names.update(name for name in (row.get("home_name"), row.get("away_name")) if name)
    return sorted(names)


# The word after a school's name that makes it a *different* school: "Texas"
# + "Southern Tigers", "Alabama" + "State Hornets", "Utah" + "Tech Trailblazers",
# "North Carolina" + "A&T Aggies". A mascot never starts with one of these, so
# a pipeline name followed by one is the prefix of another school, not that
# school with its mascot appended. Compared after `_normalize`, so "A&M" is
# "am", "A&T" is "at" and "St." is "st".
_SCHOOL_QUALIFIERS = frozenset({
    "state", "st", "tech", "am", "at", "southern", "northern", "eastern", "western",
    "central", "christian", "baptist", "poly", "international", "city", "valley",
    "methodist", "wesleyan", "lutheran", "gulf", "coast", "southeastern",
    "southwestern", "northeastern", "northwestern", "upstate", "mountain",
})


def _tokens(name: Any) -> list[str]:
    import trdlab_handoff as handoff
    return [token for token in (handoff._normalize(part) for part in str(name or "").split()) if token]


def _short_for(full: Any, shorts: Sequence[str]) -> str | None:
    """The pipeline's name for the handoff team `full`, or None if none fits.

    A pipeline name fits only when its words are the leading *words* of `full`
    and what follows reads as a mascot. Matching on characters, as this once
    did, let "Texas" claim "Texas Southern Tigers" and "Utah" claim "Utah Tech
    Trailblazers": the FCS school is absent from the pipeline's name list, so
    the longest compatible prefix was the FBS school sharing its first word,
    and a game against an FCS opponent was archived as a game against the FBS
    one (Build 1112T).
    """
    words = str(full or "").split()
    full_tokens = _tokens(full)
    best: tuple[int, str] | None = None
    for short in shorts:
        short_tokens = _tokens(short)
        if not short_tokens or full_tokens[:len(short_tokens)] != short_tokens:
            continue
        if len(short_tokens) < len(full_tokens):
            following = full_tokens[len(short_tokens)]
            raw = _raw_word_after(words, len(short_tokens))
            if following in _SCHOOL_QUALIFIERS or raw.startswith("(") or "-" in raw:
                continue
        if best is None or len(short_tokens) > best[0]:
            best = (len(short_tokens), short)
    return best[1] if best else None


def _raw_word_after(words: list[str], token_count: int) -> str:
    """The raw word holding normalized token number `token_count` (0-based)."""
    seen = 0
    for word in words:
        if not _tokens(word):
            continue
        if seen == token_count:
            return word
        seen += 1
    return ""


def handoff_name_map(full_names: Iterable[Any], shorts: Sequence[str]) -> dict[str, str]:
    """Map every handoff team name to the name it is archived under.

    A name with no fitting pipeline name keeps its full form. So does every
    name in a set that would land on the *same* pipeline name: two schools
    cannot both be "Alabama", and with no way to tell which one is, archiving
    the full names is a cosmetic cost while guessing would record a game that
    never happened.
    """
    names = sorted({str(name) for name in full_names if name})
    proposed = {name: _short_for(name, shorts) for name in names}
    claims: dict[str, int] = {}
    for short in proposed.values():
        if short:
            claims[short] = claims.get(short, 0) + 1
    return {name: (short if short and claims[short] == 1 else name) for name, short in proposed.items()}


def source_handoff() -> list[dict[str, Any]]:
    """Season football finals from the engine's handoff (`trdlab_picks.json` -> results).

    The handoff carries every final of the season, while `data_*.json` only
    holds the display window, so this is what covers the weeks before the
    hourly archive hook was committed. Its event ids are ESPN's. For football
    those are also CFBD's ids, the scheme the pipeline archives under, so
    `game_id` dedupes against `record_build()` rows. It names teams with the
    mascot appended; `handoff_name_map` maps each name to the pipeline's short
    name and keeps it as-is when no pipeline name fits.

    Basketball is skipped on purpose. CBBD numbers its games itself (377909
    where ESPN says 401920982), so a handoff NCAAM row can never dedupe
    against the pipeline's, and archiving them put 523 ESPN-id rows beside
    CBBD's in 2026-27 -- two providers in one season, 308 games stored twice
    (Build 1112T). The pipeline's own hook now archives the whole fetched
    season instead of the display window, which is the gap this was filling.
    """
    import trdlab_handoff as handoff

    document = _load_json(Path(handoff.DEFAULT_HANDOFF_PATH))
    if not isinstance(document, dict):
        print("  - no handoff present; skipping")
        return []
    results = [result for result in document.get("results") or []
               if str(result.get("competition") or "").upper() in HANDOFF_COMPETITIONS]
    rows: list[dict[str, Any]] = []
    names: dict[str, dict[str, str]] = {}
    for result in results:
        comp = str(result.get("competition") or "").upper()
        if comp not in names:
            names[comp] = handoff_name_map(
                (r.get(side) for r in results
                 if str(r.get("competition") or "").upper() == comp for side in ("home", "away")),
                _short_names(comp))
        match = {
            "id": result.get("event_id"),
            "provider_id": result.get("event_id"),
            "kickoff": result.get("kickoff"),
            "status": "FINISHED",
            "score": {"home": result.get("home_score"), "away": result.get("away_score")},
            "home": {"name": names[comp].get(str(result.get("home") or ""), str(result.get("home") or ""))},
            "away": {"name": names[comp].get(str(result.get("away") or ""), str(result.get("away") or ""))},
        }
        normalized = game_archive.normalize_match(comp, match, source=comp.lower())
        if normalized:
            rows.append(normalized)
    print(f"  {handoff.DEFAULT_HANDOFF_PATH}: {len(rows)} finished")
    return rows


# Competitions whose handoff event ids are the pipeline's own ids. See
# `source_handoff` for why NCAAM is not one of them.
HANDOFF_COMPETITIONS = frozenset({"NCAAF"})


SOURCES: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "college": source_college,
    "data": source_data,
    "handoff": source_handoff,
}

# Provider identity (aliases, precedence) lives in game_archive, because the
# write path needs it too: see `game_archive.retire_provisional`.
SOURCE_PRECEDENCE = game_archive.SOURCE_PRECEDENCE
canonical_source = game_archive.canonical_source
_precedence = game_archive.source_precedence


def resolve_overlaps(rows: Iterable[dict[str, Any]],
                     archived: Callable[[str, str], Iterable[dict[str, Any]]] | None = None,
                     ) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep one provider per (competition, season). Returns (kept, notes).

    Scoped to the season rather than the whole competition on purpose: a source
    that covers only older seasons must not be discarded wholesale because
    another covers the current one.

    `archived(comp, season)` returns the rows already on disk for a season.
    They take part in choosing the season's provider but are never returned:
    this decides what may be *added*. Without them the choice only saw one
    run's rows, so an hourly run of a single source always found one provider
    and resolved nothing, however many the season already held.
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
        on_disk = {canonical_source(row.get("source"))
                   for row in (archived(comp, season) if archived else ())}
        providers = set(by_provider) | on_disk
        if len(providers) == 1:
            kept.extend(next(iter(by_provider.values())).values())
            continue
        winner = min(providers, key=lambda name: (_precedence(name), name))
        winner_rows = list(by_provider.get(winner, {}).values())
        kept.extend(winner_rows)
        # A losing provider's game is dropped only where the winner already
        # holds the same game. One the winner lacks is kept, provisionally:
        # resolution decides which copy of a game stands, never whether the
        # game is recorded. `upsert_games` retires it once the winner's copy
        # arrives (Build 1112U -- 1112T dropped 215 games the winner lacked).
        owned = winner_rows + [row for row in (archived(comp, season) if archived else ())
                               if canonical_source(row.get("source")) == winner]
        dropped: dict[str, int] = {}
        provisional: dict[str, int] = {}
        for name, items in sorted(by_provider.items()):
            if name == winner:
                continue
            twinned: set[str] = set()
            for one, two in game_archive.cross_id_duplicates(list(items.values()) + owned):
                for row in (one, two):
                    if canonical_source(row.get("source")) == name:
                        twinned.add(str(row["game_id"]))
            for game_id, row in items.items():
                if game_id in twinned:
                    dropped[name] = dropped.get(name, 0) + 1
                else:
                    kept.append(row)
                    provisional[name] = provisional.get(name, 0) + 1
        if dropped or provisional:
            notes.append(f"{comp} {season}: {winner!r} owns the season ({len(winner_rows)} incoming); "
                         f"dropped duplicates {dropped}; kept provisionally (no {winner} copy yet) "
                         f"{provisional}")
    return kept, notes


def _archived_season(comp: str, season: str) -> list[dict[str, str]]:
    return game_archive.read_partition(game_archive.partition_path("games", comp, season))


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

    resolved, notes = resolve_overlaps(collected, _archived_season)
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
