"""Refuse to ship a handoff whose numbers are built on missing or distorted data.

Each check is a failure that reached the site without anything stopping it:

* unscored -- 2026-10-18: the data poller was not running on Saturday, 29 of
  62 FBS finals never reached the engine, and ratings, records and the poll
  were published without them. The engine's own staleness check said
  "current" because it compares the archive with the feed, and both were
  missing the same games. Here a game whose kickoff passed hours ago and that
  still has no result means the week is incomplete, whatever the feed says.
* records -- BYU was published 5-0 after beating Notre Dame (6-0). Every
  ranked team's record must equal the results the same handoff carries.
* projected scores -- 2026-10-18: projected scores for 60-70% favourites
  showed a 16.5-point margin against a 4.2-point reality, because the score
  was conditioned on the favourite winning while the model's own line said
  6.4. A shown score must stay close to the model line it is drawn from.

Run with no arguments it checks trdlab_picks.json next to it and exits
non-zero on a failure, which stops the Sunday ship before the push.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
UNSCORED_GRACE_HOURS = 6       # a game this long past kickoff should be final
MAX_UNSCORED = 2               # one postponement is not a missing week
MAX_RECORD_MISMATCHES = 2
MAX_MEAN_MARGIN_GAP = 4.0      # points between shown score and model line, on average


def _kickoff(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def unscored(doc: dict, now: dt.datetime) -> list[str]:
    finished = {str(r.get("event_id")) for r in doc.get("results") or []}
    out = []
    for fixture in doc.get("fixtures") or []:
        kickoff = _kickoff(fixture.get("kickoff"))
        if fixture.get("sport") != "ncaaf" or kickoff is None:
            continue
        if kickoff < now - dt.timedelta(hours=UNSCORED_GRACE_HOURS) and \
                str(fixture.get("event_id")) not in finished and fixture.get("status") != "post":
            out.append(f"{fixture.get('away')} at {fixture.get('home')} ({fixture.get('kickoff')})")
    return out


def record_mismatches(doc: dict) -> list[str]:
    season = max((int(r.get("season") or 0) for r in doc.get("results") or []), default=0)
    tally: dict[str, list[int]] = {}
    for r in doc.get("results") or []:
        if r.get("sport") != "ncaaf" or int(r.get("season") or 0) != season:
            continue
        hs, as_ = r.get("home_score"), r.get("away_score")
        if hs is None or as_ is None or hs == as_:
            continue
        winner, loser = (r["home"], r["away"]) if hs > as_ else (r["away"], r["home"])
        tally.setdefault(winner, [0, 0])[0] += 1
        tally.setdefault(loser, [0, 0])[1] += 1
    out = []
    rows = ((doc.get("rankings") or {}).get("ncaaf") or {}).get("rankings") or []
    for row in rows:
        if not row.get("rank") or int(row["rank"]) > 25:
            continue
        name = row.get("team_name")
        if name not in tally:
            continue
        w, l = tally[name]
        if (int(row.get("wins") or 0), int(row.get("losses") or 0)) != (w, l):
            out.append(f"{name}: published {row.get('wins')}-{row.get('losses')}, results say {w}-{l}")
    return out


def margin_gap(doc: dict) -> tuple[float, int]:
    gaps = []
    for pick in doc.get("picks") or []:
        score, line = pick.get("projected_score"), pick.get("model_line")
        if not score or not line or line.get("home_margin") is None:
            continue
        gaps.append(abs((score["home"] - score["away"]) - float(line["home_margin"])))
    return (sum(gaps) / len(gaps) if gaps else 0.0), len(gaps)


def check(doc: dict, now: dt.datetime) -> tuple[bool, list[str]]:
    problems, notes = [], []
    missing = unscored(doc, now)
    notes.append(f"{len(missing)} games past kickoff without a result")
    if len(missing) > MAX_UNSCORED:
        problems.append(f"{len(missing)} games kicked off over {UNSCORED_GRACE_HOURS}h ago with no result "
                        f"(is the data poller running?): " + "; ".join(missing[:8]))
    bad = record_mismatches(doc)
    notes.append(f"{len(bad)} top-25 records disagree with results")
    if len(bad) > MAX_RECORD_MISMATCHES:
        problems.append("published records disagree with results: " + "; ".join(bad[:8]))
    gap, n = margin_gap(doc)
    notes.append(f"projected-score margin is {gap:.1f} pts from the model line on average ({n} games)")
    if n and gap > MAX_MEAN_MARGIN_GAP:
        problems.append(f"projected scores sit {gap:.1f} pts from the model line on average "
                        f"(limit {MAX_MEAN_MARGIN_GAP}); the score is no longer drawn from the model")
    return not problems, problems or notes


def main() -> int:
    doc = json.loads((ROOT / "trdlab_picks.json").read_text(encoding="utf-8"))
    ok, lines = check(doc, dt.datetime.now(dt.timezone.utc))
    for line in lines:
        print(("REFUSING TO SHIP: " if not ok else "") + line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
