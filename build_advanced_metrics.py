r"""Build normalized Matchday shadow profiles from approved local/download data.

Examples:
  python build_advanced_metrics.py basketball --input boxes.json --output advanced_metrics_ncaam.json
  python build_advanced_metrics.py cfbd --input cfbd_advanced.json --output advanced_metrics_ncaaf.json
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from advanced_metrics import (
    basketball_team_profiles,
    cfbd_advanced_team_profiles,
)


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
    basket = sub.add_parser("basketball"); basket.add_argument("--input", required=True); basket.add_argument("--output", required=True)
    basket.add_argument("--sport", choices=("NCAAM",), required=True); basket.add_argument("--source", required=True)
    basket.add_argument("--license", required=True); basket.add_argument("--min-games", type=int, default=3); basket.set_defaults(func=build_basketball)
    cfb = sub.add_parser("cfbd"); cfb.add_argument("--input", required=True); cfb.add_argument("--output", required=True); cfb.set_defaults(func=build_cfbd)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
