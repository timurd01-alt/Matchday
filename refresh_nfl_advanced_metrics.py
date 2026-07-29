"""Refresh a last-good authorized NFL advanced profile for live reasoning."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from types import SimpleNamespace

from build_advanced_metrics import build_nfl


def candidate_seasons(today: dt.date) -> list[int]:
    active = today.year if today.month >= 9 else today.year - 1
    return [active, active - 1]


def refresh(output: str = "advanced_metrics_nfl.json", today: dt.date | None = None,
            min_teams: int = 20) -> dict | None:
    today = today or dt.date.today()
    destination = Path(output)
    candidate = destination.with_name(destination.stem + ".candidate.json")
    failures = []
    for season in candidate_seasons(today):
        try:
            args = SimpleNamespace(season=season, input=None, output=str(candidate), min_plays=50)
            build_nfl(args)
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            profiles = payload.get("profiles") or {}
            if len(profiles) < min_teams:
                failures.append(f"{season}: only {len(profiles)} teams met coverage")
                continue
            coverage = payload.setdefault("coverage", {})
            coverage["season_role"] = "current" if season == today.year else "prior_completed"
            coverage["used_for"] = "expanded-view research reasoning; official probability weight 0"
            coverage["teams"] = len(profiles)
            payload["production_weight"] = 0
            candidate.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(candidate, destination)
            return payload
        except Exception as exc:  # last-good output survives provider/network failures
            failures.append(f"{season}: {type(exc).__name__}: {exc}")
    if candidate.exists():
        candidate.unlink()
    if destination.exists():
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
            if payload.get("shadow_only") is True and payload.get("profiles"):
                print("NFL advanced refresh failed; preserving last-good profile: " + "; ".join(failures))
                return payload
        except Exception:
            pass
    print("NFL advanced metrics unavailable: " + "; ".join(failures))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="advanced_metrics_nfl.json")
    parser.add_argument("--today", help="YYYY-MM-DD test/override date")
    parser.add_argument("--min-teams", type=int, default=20)
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else None
    payload = refresh(args.output, today, args.min_teams)
    if payload:
        coverage = payload.get("coverage") or {}
        print(f"NFL research profile ready: season={coverage.get('season')} "
              f"role={coverage.get('season_role')} teams={len(payload.get('profiles') or {})} weight=0")


if __name__ == "__main__":
    main()
