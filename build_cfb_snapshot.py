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
import re
import sys

import betbetter_handoff
import ap_poll

SNAPSHOT = pathlib.Path("matchday-cfb-snapshot.js")
BEGIN = "  /* BEGIN GENERATED RANKINGS -- build_cfb_snapshot.py */"
END = "  /* END GENERATED RANKINGS */"


def _team_key(value: object) -> str:
    """Stable join key for the AP poll and Matchday's rating table."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


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


# A conference title is what earns an automatic bid, so a listing that is not a
# conference cannot produce a champion. Independents reach the field only as an
# at-large -- which is exactly how Notre Dame gets in when it is ranked high
# enough, and how it misses when it is not.
NON_CONFERENCE_GROUPS = frozenset({"FBS Independents"})

CFP_FIELD = 12
# 2026-27: the four named conference champions and the highest-ranked champion
# of these six conferences qualify. Notre Dame also qualifies automatically
# if ranked in the top 12; otherwise seven places are at-large.
CFP_POWER_FOUR = frozenset({"ACC", "Big Ten", "Big 12", "SEC"})
CFP_OTHER_AUTO = frozenset({"American", "American Athletic", "Conference USA",
                            "Mid-American", "Mountain West", "Pac-12", "Sun Belt"})

# 5v12, 6v11, 7v10, 8v9, higher seed at home. The four winners meet the seeds on
# bye in the order below -- 1 plays the 8/9 winner, not whoever it likes.
CFP_FIRST_ROUND = ((5, 12), (6, 11), (7, 10), (8, 9))
CFP_QUARTERS = ((1, (8, 9)), (2, (7, 10)), (3, (6, 11)), (4, (5, 12)))


def projected_champions(rows: list[dict]) -> dict[str, dict]:
    """The best-rated team in each conference, as that conference's projected
    champion.

    No title game has been played, so this is a projection like everything else
    in the bracket. It is the only piece the ratings cannot state directly: a
    champion is decided on a field, and the highest-rated team in a conference
    is the honest stand-in for one until it is.
    """
    best: dict[str, dict] = {}
    for row in rows:
        conference = str(row.get("conference") or "").strip()
        rank = row.get("rank")
        if not conference or conference in NON_CONFERENCE_GROUPS or not rank:
            continue
        if conference not in best or rank < best[conference]["rank"]:
            best[conference] = row
    return best


def cfp_field(entry: dict) -> list[dict]:
    """The projected twelve, in seed order.

    AP rank is a provisional selection proxy, not a claim that the AP selects
    the CFP. The four power-conference champions, best eligible other champion,
    and (when AP top-12) Notre Dame take automatic places. Remaining teams enter
    by ranking. Automatic qualifiers outside the top 12 are seeded at the bottom.
    """
    rows = sorted((r for r in (entry.get("rankings") or []) if r.get("rank")),
                  key=lambda r: r["rank"])
    if len(rows) < CFP_FIELD:
        return []
    champions = projected_champions(rows)
    auto = [champions[c] for c in CFP_POWER_FOUR if c in champions]
    other = sorted((champions[c] for c in CFP_OTHER_AUTO if c in champions),
                   key=lambda r: r["rank"])
    if other:
        auto.append(other[0])
    notre_dame = next((r for r in rows if str(r.get("team_name") or "").startswith("Notre Dame")
                       and r["rank"] <= 12), None)
    if notre_dame:
        auto.append(notre_dame)
    if len(auto) < 5:
        return []
    taken = {r["team_key"] for r in auto}
    at_large = [r for r in rows if r["team_key"] not in taken][:CFP_FIELD - len(auto)]
    field = sorted(auto + at_large, key=lambda r: r["rank"])
    if len(field) < CFP_FIELD:
        return []
    for seed, row in enumerate(field, 1):
        row["cfp_seed"] = seed
        row["cfp_bid"] = ("Notre Dame" if notre_dame and row["team_key"] == notre_dame["team_key"]
                          else "champion" if row["team_key"] in taken else "at-large")
    return field


def cfp_bracket(entry: dict) -> list[dict]:
    """A 12-team CFP field, selected and seeded the way the format selects and
    seeds one, and labelled a projection throughout.

    This is a projection in the strict sense: no selection committee has met and
    no conference championship has been played, so nothing here is a result.
    Every round says so in its own title, because a bracket screenshotted out of
    context has no other way to carry the caveat.
    """
    field = cfp_field(entry)
    if not field:
        return []
    seed = {row["cfp_seed"]: row for row in field}
    name = lambda n: seed[n]["team_name"]
    return [
        {"round": "CFP First Round — projected: 2026 automatic bids and at-large",
         "matches": [{"home": name(h), "away": name(a), "home_slot": str(h),
                      "away_slot": str(a), "status": "PROJECTED", "score": {}}
                     for h, a in CFP_FIRST_ROUND]},
        {"round": "CFP Quarter-finals — projected, top four seeds on bye",
         "matches": [{"home": name(n), "away": f"Winner {a} v {b}",
                      "home_slot": str(n), "away_slot": f"{a}/{b}",
                      "status": "PROJECTED", "score": {}}
                     for n, (a, b) in CFP_QUARTERS]},
    ]


def build(path: pathlib.Path = SNAPSHOT) -> str:
    document = betbetter_handoff.load()
    if not document:
        raise SystemExit("no Bet Better handoff found; nothing regenerated")

    blocks = []
    # The browser can distinguish a current Bet Better repair layer from the
    # older quota-limited fixture payload. Without this timestamp the header
    # permanently advertised "fallback snapshot" even immediately after a
    # fresh prediction handoff had repaired the slate.
    blocks.append("  const MATCHDAY_BETBETTER_GENERATED_AT="
                  + json.dumps(document.get("generated_at") or "",
                               ensure_ascii=False) + ";")
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

    # The official poll and the model power rating are deliberately separate.
    # Refresh the former from the published AP ranks; if the network response
    # is incomplete, ap_poll keeps the last complete 1-25 snapshot.
    poll = ap_poll.refresh()
    poll_rows = poll.get("rankings") or []
    rating_entry = betbetter_handoff.rankings(document, "ncaaf")
    raw_rating_rows = rating_entry.get("rankings") or []
    rating_rows = _dedupe(_rows(rating_entry), rating_entry)
    by_name = {_team_key(r.get("name")): r for r in rating_rows}
    raw_by_name = {_team_key(r.get("team_name")): r for r in raw_rating_rows}
    bracket_rows = []
    for item in poll_rows:
        rated = raw_by_name.get(_team_key(item.get("name")))
        if not rated:
            continue
        bracket_rows.append({**rated, "rank": item["rank"]})
    # The AP publishes only 25 teams, while an automatic qualifier can be
    # unranked. Keep the AP order for its 25, then use model order solely to
    # choose and place otherwise-unranked projected conference champions.
    ap_keys = {r["team_key"] for r in bracket_rows}
    for model_rank, rated in enumerate(sorted(raw_rating_rows,
                                               key=lambda r: r.get("rank") or 9999), 1):
        if rated.get("team_key") not in ap_keys:
            bracket_rows.append({**rated, "rank": 1000 + model_rank})
    bracket = cfp_bracket({"rankings": bracket_rows}) if len(ap_keys) == 25 else []
    poll_payload = {**poll, "rankings": []}
    for row in poll_rows:
        rated = by_name.get(_team_key(row.get("name"))) or {}
        poll_payload["rankings"].append({
            **row,
            "pos": row["rank"],
            # The AP publishes each ranked team's record alongside the rank,
            # and that is the record belonging to this table. The model
            # ranking's copy is frozen at the moment its own poll was
            # published, so the week's results are missing from it: on
            # 23 September six ranked teams read a game short, with LSU shown
            # at 2-0 after losing. Fall back to the model's only when the AP
            # sends none.
            "record": row.get("record") or rated.get("record") or "—",
            "rating": rated.get("rating"),
            "external_rank": rated.get("rank"),
            "code": "",
        })
    blocks.append("  const MATCHDAY_CFB_AP_POLL="
                  + json.dumps(poll_payload, ensure_ascii=False) + ";")
    blocks.append("  const MATCHDAY_CFB_AP_BRACKET="
                  + json.dumps(bracket, ensure_ascii=False) + ";")

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

    # The marquee game. Distinct from the upset: that one is the model's most
    # contrarian call and carries the inverted-sign warning, this one is simply
    # the best matchup on the board and is not selected on the market at all.
    blocks.append("  const MATCHDAY_BETBETTER_GAME_OF_THE_WEEK="
                  + json.dumps(document.get("game_of_the_week") or {},
                               ensure_ascii=False) + ";")

    # This season's per-team offense and defense from the engine's own
    # play-by-play. The expanded view's profile used a previous-season CFBD file
    # that never refreshed; these move every week with the ratings.
    blocks.append("  const MATCHDAY_BETBETTER_TEAM_PROFILES="
                  + json.dumps((document.get("team_profiles") or {}).get("ncaaf") or {},
                               ensure_ascii=False) + ";")

    # The season's biggest upsets, judged against the closing price, for the
    # board card that used to list the most recent finals.
    blocks.append("  const MATCHDAY_BETBETTER_UPSETS="
                  + json.dumps((document.get("upsets") or {}).get("ncaaf") or {},
                               ensure_ascii=False) + ";")

    # The owner's own Top 25 ballot, with each team's résumé frozen on the day
    # it was cast. Kept apart from the power rating on purpose: that table is
    # the model's, this one is a person's judgement. {} until the first ballot.
    blocks.append("  const MATCHDAY_BETBETTER_BALLOT="
                  + json.dumps((document.get("ballots") or {}).get("ncaaf") or {},
                               ensure_ascii=False) + ";")

    blocks.append("  const MATCHDAY_BETBETTER_UPSET="
                  + json.dumps(document.get("upset_of_the_week") or {}, ensure_ascii=False) + ";")
    blocks.append("  const MATCHDAY_BETBETTER_USER_PICKS="
                  + json.dumps(document.get("user_picks") or {}, ensure_ascii=False) + ";")

    # The engine's graded record. The block this replaces was eight games typed
    # into the snapshot by hand on the day the site went college-only, sitting
    # outside the generated region so nothing ever refreshed it -- it still
    # described the 29 August slate weeks later. Generated now, so it moves.
    blocks.append("  const MATCHDAY_BETBETTER_SCORECARD="
                  + json.dumps(document.get("scorecard") or {},
                               ensure_ascii=False) + ";")

    picks = [p for p in (document.get("picks") or [])
             if str(p.get("basis") or "") == betbetter_handoff.LIVE_BASIS
             and not p.get("official_pick")]
    blocks.append("  const MATCHDAY_BETBETTER_PICKS="
                  + json.dumps(picks, ensure_ascii=False) + ";")

    # Which sports the engine actually covers. The expanded view needs it to
    # tell "Bet Better has not priced this fixture" apart from "this sport has
    # no Bet Better read at all, so Matchday's own forecast is the model read".
    blocks.append("  const MATCHDAY_BETBETTER_SPORTS="
                  + json.dumps(document.get("sports") or [],
                               ensure_ascii=False) + ";")

    # The gap caveat lives on the document, not on each pick, so a baked pick
    # arrives without it -- `_display_block` only copies it onto picks the fetch
    # attaches. The expanded view renders the gap either way, so the warning
    # that must travel with it is baked once here rather than retyped in JS.
    blocks.append("  const MATCHDAY_BETBETTER_EDGE_WARNING="
                  + json.dumps(document.get("edge_warning") or "",
                               ensure_ascii=False) + ";")

    text = path.read_text(encoding="utf-8")
    start, stop = text.index(BEGIN), text.index(END)
    generated = BEGIN + "\n" + "\n".join(blocks) + "\n"
    path.write_text(text[:start] + generated + text[stop:], encoding="utf-8", newline="\n")
    return f"regenerated {sum(len(b) for b in blocks)} bytes of rankings"


if __name__ == "__main__":
    print(build())
    sys.exit(0)
