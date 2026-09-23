"""Build the browser copy of a competition payload without private redundancy.

The checked-in/runtime payload remains untouched.  The Pages artifact does not
need the scorecard's reproducibility snapshots (the UI reads the compact Bet
Better scorecard in matchday-cfb-snapshot.js), and NCAAF's per-match
``betbetter_pick`` is the same handoff already published in that snapshot.
Removing those duplicate copies and writing compact JSON materially reduces
mobile download and parse time.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def public_payload(payload: dict, competition: str) -> dict:
    scorecard = payload.get("scorecard")
    if isinstance(scorecard, dict):
        scorecard.pop("picks", None)

    # The shared snapshot currently carries NCAAF Bet Better picks. NCAAM must
    # retain any attached picks until its handoff is added to that snapshot.
    if competition.lower() == "ncaaf":
        for match in payload.get("matches") or []:
            if isinstance(match, dict):
                match.pop("betbetter_pick", None)
    return payload


def build(source: Path, destination: Path, competition: str) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    public_payload(payload, competition)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("competition")
    args = parser.parse_args()
    build(args.source, args.destination, args.competition)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
