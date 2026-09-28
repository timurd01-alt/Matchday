"""Refuse to ship a handoff that quietly lost this week's picks.

2026-09-28: a feed re-keyed a week of games, their forecasts no longer
attached, and the site went from about 90 picks this week to 17 with nothing
failing. This compares the picks kicking off in the next seven days in the new
betbetter_picks.json against the copy already on main, and exits non-zero --
stopping the Sunday ship before the push -- if the new one lost a large share.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
MAX_DROP = 0.30          # lose more than 30% of this week's picks -> refuse
MIN_BASELINE = 20        # too few live picks to judge a drop (off-season)


def upcoming(document: dict, now: dt.datetime) -> int:
    end = now + dt.timedelta(days=7)
    count = 0
    for pick in document.get("picks") or []:
        try:
            kickoff = dt.datetime.fromisoformat(str(pick.get("kickoff")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now <= kickoff <= end:
            count += 1
    return count


def check(new: dict, live: dict | None, now: dt.datetime) -> tuple[bool, str]:
    fresh = upcoming(new, now)
    if not live:
        return True, f"{fresh} picks in the next 7 days (no live copy to compare)"
    before = upcoming(live, now)
    if before < MIN_BASELINE:
        return True, f"{fresh} picks in the next 7 days (live had {before}; too few to compare)"
    if fresh < before * (1 - MAX_DROP):
        return False, (f"REFUSING TO SHIP: picks in the next 7 days fell from {before} "
                       f"to {fresh}. A feed may have re-keyed games so their forecasts "
                       f"no longer attach. Re-run the forecast before shipping.")
    return True, f"{fresh} picks in the next 7 days (live had {before})"


def main() -> int:
    new = json.loads((ROOT / "betbetter_picks.json").read_text(encoding="utf-8"))
    try:
        live = json.loads(subprocess.check_output(
            ["git", "show", "HEAD:betbetter_picks.json"], cwd=ROOT).decode("utf-8-sig"))
    except (subprocess.CalledProcessError, ValueError):
        live = None
    ok, message = check(new, live, dt.datetime.now(dt.timezone.utc))
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
