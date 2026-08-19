"""Build NCAAM adjusted-efficiency profiles from CollegeBasketballData boxes.

`advanced_metrics.basketball_team_profiles` already implements the right model
for college basketball -- opponent-adjusted offensive and defensive ratings via
alternating ridge updates, tempo, Dean Oliver's four factors, and schedule
strength. Nothing has ever fed it live data. This module is the missing link
between the CBBD team box-score endpoint and that function, and it is the
critical path for the pre-registered 2026-27 season in
`ncaam_preregistration.json`.

## Why this module fails closed

`MAPPING_VERIFIED` is False. The CBBD team box-score field names below are the
documented/conventional ones, but they have NOT been read off a live response,
because CBBD is sitting at zero remaining calls for the period and this
repository holds no key. AGENTS.md states the rule for provider integration
plainly -- read the real fields off a live response first, never assume -- and
that rule exists because the last provider assumption in this repository
(`*_cache.json` silently never matching `odds_market_cache_<comp>.json`) burned
quota for weeks without an error.

So `refresh()` refuses to write a production artifact while the flag is False.
`verify_mapping()` exists to flip it: point it at one real response, read what
it reports, correct `TEAM_BOX_FIELDS` if the names differ, then set
`MAPPING_VERIFIED = True` in a commit that shows the evidence.

A wrong mapping here would not fail loudly. `basketball_game_records` drops any
team-game missing a required field, so a mis-named column produces zero
records, an empty profile set, and a cheerful "no data" -- the exact silent
degradation the quota work was written to stop.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from advanced_metrics import basketball_team_profiles


SCHEMA_VERSION = 1

# Set to True only in a commit that shows a real CBBD response confirming every
# name below. See verify_mapping().
MAPPING_VERIFIED = False

# internal field -> candidate CBBD keys, most likely first. Several are listed
# because CBBD has used both camelCase and flattened stat names across
# endpoints; normalize() takes the first key actually present on the row.
TEAM_BOX_FIELDS: dict[str, tuple[str, ...]] = {
    "points": ("points", "teamPoints", "score"),
    "fgm": ("fieldGoalsMade", "fgm"),
    "fga": ("fieldGoalsAttempted", "fga"),
    "three_pm": ("threePointFieldGoalsMade", "threePointersMade", "tpm"),
    "three_pa": ("threePointFieldGoalsAttempted", "threePointersAttempted", "tpa"),
    "fta": ("freeThrowsAttempted", "fta"),
    "orb": ("offensiveRebounds", "oreb"),
    "drb": ("defensiveRebounds", "dreb"),
    "tov": ("turnovers", "tov"),
}
IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "game_id": ("gameId", "game_id", "id"),
    "team": ("team", "school", "teamName"),
    "opponent": ("opponent", "opponentTeam"),
    "game_date": ("startDate", "gameDate", "date"),
}
# Everything basketball_game_records refuses to compute without.
REQUIRED = ("points", "fgm", "fga", "three_pm", "fta", "orb", "drb", "tov")


class MappingUnverified(RuntimeError):
    """Raised rather than writing an artifact from an unconfirmed field map."""


def _first_present(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def normalize(raw_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map CBBD team box rows onto basketball_game_records' expected shape."""
    normalized = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row: dict[str, Any] = {}
        for field, keys in IDENTITY_FIELDS.items():
            value = _first_present(raw, keys)
            if value is not None:
                row[field] = value
        for field, keys in TEAM_BOX_FIELDS.items():
            value = _first_present(raw, keys)
            if value is not None:
                row[field] = value
        if row.get("game_id") is None or not row.get("team"):
            continue
        if isinstance(row.get("game_date"), str):
            row["game_date"] = row["game_date"][:10]
        normalized.append(row)
    return normalized


def verify_mapping(raw_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Report how well TEAM_BOX_FIELDS matches a real response.

    Run this against one live CBBD page before setting MAPPING_VERIFIED.
    `unmapped_keys` is the useful column: a stat sitting there under a name this
    module does not know is precisely the silent-zero failure described above.
    """
    rows = [row for row in raw_rows if isinstance(row, dict)]
    resolved: dict[str, dict[str, Any]] = {}
    matched_keys: set[str] = set()
    for field, keys in {**IDENTITY_FIELDS, **TEAM_BOX_FIELDS}.items():
        hits: dict[str, int] = defaultdict(int)
        for row in rows:
            for key in keys:
                if key in row and row[key] is not None:
                    hits[key] += 1
                    matched_keys.add(key)
                    break
        covered = sum(hits.values())
        resolved[field] = {
            "resolved_key": max(hits, key=hits.get) if hits else None,
            "rows_covered": covered,
            "coverage_pct": round(100 * covered / len(rows), 2) if rows else 0.0,
        }
    seen_keys = {key for row in rows for key in row}
    missing_required = [field for field in REQUIRED
                        if resolved.get(field, {}).get("resolved_key") is None]
    return {
        "rows_inspected": len(rows),
        "fields": resolved,
        "missing_required_fields": missing_required,
        "unmapped_keys": sorted(seen_keys - matched_keys),
        "ready_to_verify": bool(rows) and not missing_required and all(
            resolved[field]["coverage_pct"] >= 95.0 for field in REQUIRED),
    }


def build_profiles(raw_rows: Iterable[dict[str, Any]], min_games: int = 5) -> dict[str, Any]:
    rows = normalize(raw_rows)
    profiles = basketball_team_profiles(rows, min_games=min_games)
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": "NCAAM",
        "source": "CollegeBasketballData team box scores",
        "license": "active CBBD API tier; no raw redistribution",
        "production_weight": 0,
        "research_only": True,
        "mapping_verified": MAPPING_VERIFIED,
        "coverage": {"normalized_rows": len(rows), "teams": len(profiles),
                     "min_games": min_games},
        "profiles": profiles,
    }


def refresh(fetcher: Callable[[], Iterable[dict[str, Any]]],
            output: str = "advanced_metrics_ncaam.json",
            min_games: int = 5, min_teams: int = 50,
            allow_unverified: bool = False) -> dict[str, Any] | None:
    """Fetch, build and persist. Refuses to run on an unconfirmed field map."""
    if not MAPPING_VERIFIED and not allow_unverified:
        raise MappingUnverified(
            "CBBD team box-score field names have not been confirmed against a live "
            "response. Run verify_mapping() on one real page, correct TEAM_BOX_FIELDS "
            "if needed, then set MAPPING_VERIFIED = True. Refusing to spend provider "
            "quota or publish an artifact built from an assumed mapping."
        )
    payload = build_profiles(fetcher(), min_games=min_games)
    if len(payload["profiles"]) < min_teams:
        print(f"NCAAM advanced metrics: only {len(payload['profiles'])} teams met "
              f"coverage (needed {min_teams}); leaving any last-good artifact in place")
        return None
    destination = Path(output)
    candidate = destination.with_name(destination.stem + ".candidate.json")
    candidate.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    candidate.replace(destination)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", help="JSON file of raw CBBD team box rows")
    parser.add_argument("--output", default="advanced_metrics_ncaam.json")
    parser.add_argument("--min-games", type=int, default=5)
    parser.add_argument("--min-teams", type=int, default=50)
    parser.add_argument("--verify", action="store_true",
                        help="report field-mapping coverage instead of building")
    parser.add_argument("--allow-unverified", action="store_true",
                        help="build anyway from a local file; never for production")
    args = parser.parse_args(argv)

    if not args.input:
        print("NCAAM advanced metrics: no --input supplied. Live CBBD fetch stays "
              "disabled until MAPPING_VERIFIED is set; see the module docstring.")
        return 0
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    raw = raw if isinstance(raw, list) else raw.get("rows") or []
    if args.verify:
        print(json.dumps(verify_mapping(raw), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    payload = refresh(lambda: raw, args.output, args.min_games, args.min_teams,
                      allow_unverified=args.allow_unverified)
    if payload:
        print(f"NCAAM research profile ready: teams={len(payload['profiles'])} "
              f"rows={payload['coverage']['normalized_rows']} weight=0 "
              f"mapping_verified={payload['mapping_verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
