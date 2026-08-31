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
        rows = _rows(entry)
        payload = {**_meta(entry), "rankings": rows,
                   # The published poll is the first 25 of the same table.
                   "top25": [r for r in rows if (r.get("rank") or 999) <= 25]}
        if sport == "ncaaf":
            payload["projected_bracket"] = cfp_bracket(entry)
        blocks.append(f"  const {const}={json.dumps(payload, ensure_ascii=False)};")

    text = path.read_text(encoding="utf-8")
    start, stop = text.index(BEGIN), text.index(END)
    generated = BEGIN + "\n" + "\n".join(blocks) + "\n"
    path.write_text(text[:start] + generated + text[stop:], encoding="utf-8", newline="\n")
    return f"regenerated {sum(len(b) for b in blocks)} bytes of rankings"


if __name__ == "__main__":
    print(build())
    sys.exit(0)
