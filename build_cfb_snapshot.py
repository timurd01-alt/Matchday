"""Regenerates the college ranking blocks in `matchday-cfb-snapshot.js`.

The rankings in that file used to be hand-typed Elo numbers. They were computed
on an ESPN ingest that silently capped every scoreboard request at 25 events,
so roughly half of each season was missing and FCS teams -- who enter the data
only through money games -- looked like they played the hardest schedules in
the country. Those numbers cannot be repaired by editing them; they have to be
replaced by the engine's own.

So this script is the only writer of those two arrays. It reads the Bet Better
handoff through `betbetter_handoff`, which is the one place Matchday validates
anything from that engine, and rewrites the marked regions in place. Everything
else in the snapshot -- news, records, the bracket -- is left untouched.

Rewriting a marked region rather than the whole file is deliberate: the file is
partly hand-maintained, and a generator that owned all of it would either
discard that work or have to reproduce it.

    python build_cfb_snapshot.py
"""

from __future__ import annotations

import json
import pathlib
import sys

import betbetter_handoff

SNAPSHOT = pathlib.Path("matchday-cfb-snapshot.js")
BEGIN = "  /* BEGIN GENERATED RANKINGS -- build_cfb_snapshot.py */"
END = "  /* END GENERATED RANKINGS */"


def _dedupe(rows: list[dict], entry: dict) -> list[dict]:
    """One edition per table.

    The NCAAM handoff currently concatenates two rankings into one array -- the
    completed season and a new preseason poll -- so 433 ranks appear twice
    (Michigan is #1 with 40 games played and #1 again with 0). Rendering that
    would show every ranked team twice with two different ratings.

    The envelope says which edition the table is describing, so that is the one
    kept: when the note reports a completed season, prefer the rows that
    actually played games. Reported upstream; this guard should outlive the fix
    because a duplicate rank is never correct here.
    """
    completed = entry.get("season_in_progress") is False
    best: dict[int, dict] = {}
    for row in rows:
        rank = row.get("rank")
        if rank is None:
            continue
        played = row.get("season_games") or 0
        current = best.get(rank)
        if current is None:
            best[rank] = row
            continue
        current_played = current.get("season_games") or 0
        take = played > current_played if completed else played < current_played
        if take:
            best[rank] = row
    return [best[k] for k in sorted(best)]


def _rows(entry: dict) -> list[dict]:
    """The ranked rows, carrying the schedule each rating was earned against.

    `sos` ships with every row now, and it is not optional context: the whole
    point of the ingest fix was that a rating means nothing without the
    schedule behind it. Anything the row does not carry stays absent rather
    than being defaulted to a number that would read as measured.
    """
    out = []
    for row in entry.get("rankings") or []:
        out.append({
            "rank": row.get("rank"),
            "name": row.get("team_name"),
            # Both keys, because the conference table reads `rating` for
            # football and `model_score` for basketball.
            "rating": row.get("rating"),
            "model_score": row.get("rating"),
            "adj_o": row.get("adj_o"),
            "adj_d": row.get("adj_d"),
            "sos": row.get("sos"),
            "wins": row.get("wins"),
            "losses": row.get("losses"),
            "season_games": row.get("season_games"),
            "record": f"{row.get('wins') or 0}-{row.get('losses') or 0}",
            "scoring_margin": row.get("scoring_margin"),
            # Division and FCS schedule share are how a reader tells a 1-0 FCS
            # side from a ranked FBS one; the truncated-ingest bug was exactly a
            # failure to make that distinction visible.
            "division": row.get("division"),
            # Tier and its offset travel together. A measured correction put the
            # Power Four and Group of Five on one scale -- across 521 cross-tier
            # games the model had been crediting non-power teams +8.91 points
            # they had not earned -- and the unadjusted rating is kept beside it
            # so the correction is inspectable rather than invisible.
            "tier": row.get("tier"),
            "tier_offset": row.get("tier_offset"),
            "rating_unadjusted": row.get("rating_unadjusted"),
            "conference": row.get("conference"),
            "fcs_schedule_share": row.get("fcs_schedule_share"),
            "rated_games": row.get("rated_games"),
            "recent_form": row.get("recent_form") or "",
            "previous_rank": row.get("previous_rank"),
            "movement": row.get("movement"),
            "preseason_rank": row.get("preseason_rank"),
            "movement_since_preseason": row.get("movement_since_preseason"),
        })
    return out


def _meta(entry: dict) -> dict:
    """What the table has to say about itself before anyone reads a number."""
    return {
        "available": bool(entry.get("available")),
        "season": entry.get("season"),
        "published_on": entry.get("published_on"),
        # season_in_progress is the difference between a poll and a record of
        # last season. The UI must render `note` either way.
        "season_in_progress": bool(entry.get("season_in_progress")),
        "note": entry.get("note") or "",
        "basis": entry.get("basis") or {},
        "coverage": entry.get("coverage") or {},
        # Teams held out of the ranking, each with its reason. Publishing the
        # exclusions is the difference between a filtered table and a quiet one.
        "withheld": entry.get("withheld") or [],
    }


def cfp_bracket(entry: dict) -> list[dict]:
    """A 12-team CFP field seeded from the current ratings, labelled a projection.

    This is a projection in the strict sense: no selection committee has met and
    no conference championship has been played, so nothing here is a result.
    Every round says so in its own title, because a bracket screenshotted out of
    context has no other way to carry the caveat.

    What it deliberately does NOT do is model the five conference-champion
    auto-bids. That needs conference membership and a champion per conference;
    seeding purely by rating would quietly present an at-large-only field as if
    it were the real format. Until that lands this is "the top twelve by
    rating", and it is named that way rather than dressed up as bracketology.
    """
    rows = [r for r in (entry.get("rankings") or []) if r.get("rank")][:12]
    if len(rows) < 12:
        return []
    seed = {r["rank"]: r["team_name"] for r in rows}
    first = [(5, 12), (6, 11), (7, 10), (8, 9)]
    return [
        {"round": "CFP First Round — projected, top 12 by rating",
         "matches": [{"home": seed[h], "away": seed[a], "home_slot": str(h),
                      "away_slot": str(a), "status": "PROJECTED", "score": {}}
                     for h, a in first]},
        {"round": "CFP Quarter-finals — projected, top 4 seeds on bye",
         "matches": [{"home": seed[n], "away": "First-round winner", "home_slot": str(n),
                      "away_slot": "path", "status": "PROJECTED", "score": {}}
                     for n in (1, 2, 3, 4)]},
    ]


def build(path: pathlib.Path = SNAPSHOT) -> str:
    document = betbetter_handoff.load()
    if not document:
        raise SystemExit("no Bet Better handoff found; nothing regenerated")

    blocks = []
    for sport, const in (("ncaaf", "MATCHDAY_CFB_RANKINGS"),
                         ("ncaam", "MATCHDAY_NCAAM_RANKINGS")):
        entry = betbetter_handoff.rankings(document, sport)
        rows = _dedupe(_rows(entry), entry)
        payload = {**_meta(entry), "rankings": rows,
                   # The published poll is the first 25 of the same table.
                   "top25": [r for r in rows if (r.get("rank") or 999) <= 25]}
        if sport == "ncaaf":
            payload["projected_bracket"] = cfp_bracket(entry)
        blocks.append(f"  const {const}={json.dumps(payload, ensure_ascii=False)};")

    results = [r for r in (document.get("results") or [])
               if r.get("home") and r.get("away")
               and r.get("home_score") is not None and r.get("away_score") is not None]
    blocks.append("  const MATCHDAY_BETBETTER_RESULTS="
                  + json.dumps(results, ensure_ascii=False) + ";")

    # The editorial underdog call and the owner's own picks. Both ship whole --
    # the upset carries a caveat that must be rendered verbatim, and the picks
    # carry their own exclusions and a reportability flag that decide how the
    # record may be described.
    fixtures = [f for f in (document.get("fixtures") or [])
                if f.get("home") and f.get("away") and f.get("kickoff")]
    blocks.append("  const MATCHDAY_BETBETTER_FIXTURES="
                  + json.dumps(fixtures, ensure_ascii=False) + ";")

    blocks.append("  const MATCHDAY_BETBETTER_UPSET="
                  + json.dumps(document.get("upset_of_the_week") or {}, ensure_ascii=False) + ";")
    blocks.append("  const MATCHDAY_BETBETTER_USER_PICKS="
                  + json.dumps(document.get("user_picks") or {}, ensure_ascii=False) + ";")

    picks = [p for p in (document.get("picks") or [])
             if str(p.get("basis") or "") == betbetter_handoff.LIVE_BASIS
             and not p.get("official_pick")]
    blocks.append("  const MATCHDAY_BETBETTER_PICKS="
                  + json.dumps(picks, ensure_ascii=False) + ";")

    text = path.read_text(encoding="utf-8")
    start, stop = text.index(BEGIN), text.index(END)
    generated = BEGIN + "\n" + "\n".join(blocks) + "\n"
    path.write_text(text[:start] + generated + text[stop:], encoding="utf-8", newline="\n")
    return f"regenerated {sum(len(b) for b in blocks)} bytes of rankings"


if __name__ == "__main__":
    print(build())
    sys.exit(0)
