r"""Build normalized Matchday shadow profiles from approved local/download data.

Examples:
  python build_advanced_metrics.py nfl --season 2025 --output advanced_metrics_nfl.json
  python build_advanced_metrics.py statsbomb --root C:\data\open-data --output advanced_metrics_soccer.json
  python build_advanced_metrics.py retrosheet --root C:\data\retrosheet --output advanced_metrics_mlb.json
  python build_advanced_metrics.py basketball --input boxes.json --output advanced_metrics_nba.json
  python build_advanced_metrics.py cfbd --input cfbd_advanced.json --output advanced_metrics_ncaaf.json
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from advanced_metrics import (
    basketball_team_profiles,
    cfbd_advanced_team_profiles,
    nflverse_team_profiles,
    retrosheet_event_profiles,
    statsbomb_team_profiles,
)


NFLVERSE_PBP = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
STATSBOMB_RAW = "https://raw.githubusercontent.com/hudl/open-data/master/data"


def _load_rows(path: Path):
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("rows", payload) if isinstance(payload, dict) else payload
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(args, sport, source, license_name, profiles, coverage=None, attach_live=True):
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sport": sport,
        "source": source,
        "license": license_name,
        "shadow_only": True,
        "attach_live": bool(attach_live),
        "coverage": coverage or {},
        "profiles": profiles,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(profiles)} {sport} profiles to {args.output}")


def build_nfl(args):
    path = Path(args.input) if args.input else Path(f"nflverse_pbp_{args.season}.csv.gz")
    if not path.exists():
        request = urllib.request.Request(NFLVERSE_PBP.format(season=args.season), headers={"User-Agent": "Matchday/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as target:
            target.write(response.read())
    profiles = nflverse_team_profiles(_load_rows(path), min_plays=args.min_plays)
    _write(args, "NFL", "nflverse-data pbp release", "CC BY 4.0",
           profiles, {"season": args.season, "input": str(path)})


def build_statsbomb(args):
    root = Path(args.root)
    if args.download:
        if args.competition_id is None or args.season_id is None:
            raise SystemExit("--download requires --competition-id and --season-id")
        matches_url = f"{STATSBOMB_RAW}/matches/{args.competition_id}/{args.season_id}.json"
        request = urllib.request.Request(matches_url, headers={"User-Agent": "Matchday/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            matches = json.loads(response.read().decode("utf-8"))
        event_dir = root / "data" / "events"
        event_dir.mkdir(parents=True, exist_ok=True)
        for index, match in enumerate(matches, 1):
            match_id = str(match.get("match_id") or "")
            if not match_id:
                continue
            destination = event_dir / f"{match_id}.json"
            if destination.exists():
                continue
            request = urllib.request.Request(f"{STATSBOMB_RAW}/events/{match_id}.json",
                                             headers={"User-Agent": "Matchday/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                destination.write_bytes(response.read())
            if index % 10 == 0:
                print(f"downloaded {index}/{len(matches)} StatsBomb event files")
    event_files = sorted((root / "data" / "events").glob("*.json"))
    events = []
    for path in event_files:
        match_id = path.stem
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            row.setdefault("match_id", match_id)
        events.extend(rows)
    profiles = statsbomb_team_profiles(events, min_matches=args.min_matches)
    _write(args, "soccer", "StatsBomb Open Data", "StatsBomb Open Data user agreement; attribution/logo required",
           profiles, {"event_files": len(event_files), "root": str(root),
                      "competition_id": args.competition_id, "season_id": args.season_id,
                      "historical_research_only": True}, attach_live=False)


def build_retrosheet(args):
    root = Path(args.root)
    files = sorted(path for path in root.rglob("*") if path.is_file() and re_event_file(path))
    lines = []
    for path in files:
        lines.extend(path.read_text(encoding="latin-1").splitlines())
    profiles = retrosheet_event_profiles(lines, min_plate_appearances=args.min_pa)
    _write(args, "MLB", "Retrosheet event files",
           "Use requires Retrosheet's prominent attribution statement from https://www.retrosheet.org/game.htm",
           profiles, {"event_files": len(files), "root": str(root), "historical_research_only": True},
           attach_live=False)


def re_event_file(path: Path) -> bool:
    suffix = path.suffix.upper()
    return suffix in {".EVA", ".EVN", ".EVE"} or path.name.upper().endswith(("EVA", "EVN", "EVE"))


def build_basketball(args):
    profiles = basketball_team_profiles(_load_rows(Path(args.input)), min_games=args.min_games)
    _write(args, args.sport, args.source, args.license, profiles, {"input": args.input})


def build_cfbd(args):
    rows = _load_rows(Path(args.input))
    profiles = cfbd_advanced_team_profiles(rows)
    _write(args, "NCAAF", "CollegeFootballData /stats/season/advanced", "active CFBD API tier",
           profiles, {"input": args.input})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    nfl = sub.add_parser("nfl"); nfl.add_argument("--season", type=int, required=True); nfl.add_argument("--input")
    nfl.add_argument("--output", required=True); nfl.add_argument("--min-plays", type=int, default=50); nfl.set_defaults(func=build_nfl)
    sb = sub.add_parser("statsbomb"); sb.add_argument("--root", required=True); sb.add_argument("--output", required=True)
    sb.add_argument("--min-matches", type=int, default=1); sb.add_argument("--download", action="store_true")
    sb.add_argument("--competition-id", type=int); sb.add_argument("--season-id", type=int); sb.set_defaults(func=build_statsbomb)
    retro = sub.add_parser("retrosheet"); retro.add_argument("--root", required=True); retro.add_argument("--output", required=True)
    retro.add_argument("--min-pa", type=int, default=100); retro.set_defaults(func=build_retrosheet)
    basket = sub.add_parser("basketball"); basket.add_argument("--input", required=True); basket.add_argument("--output", required=True)
    basket.add_argument("--sport", choices=("NBA", "NCAAM"), required=True); basket.add_argument("--source", required=True)
    basket.add_argument("--license", required=True); basket.add_argument("--min-games", type=int, default=3); basket.set_defaults(func=build_basketball)
    cfb = sub.add_parser("cfbd"); cfb.add_argument("--input", required=True); cfb.add_argument("--output", required=True); cfb.set_defaults(func=build_cfbd)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
