"""social_export.py -- the numbers behind the weekly X posts, as data.

Writes the week's figures for someone else to design from. It draws nothing:
there is no image, no font, no layout, and no dependency outside the standard
library -- which is also why nothing here can break the hourly deploy.

Two files per run, same content in two shapes:

    slate.json   machine-readable, for a designer's tooling
    brief.txt    the same numbers laid out to read and paste

## Everything is filtered to the current playing week

This is the part that actually needs care. The handoff carries picks for games
months out -- at the time of writing, 72 picks of which 13 were for 12 September
through 28 November, one of them a Thanksgiving weekend game. Ranking picks by
model probability without a date filter therefore puts a late-November fixture
on a graphic captioned "this week", which is the one mistake that makes the
whole post wrong.

`week_window()` runs from now to the end of the coming Monday, because a college
football week is Tuesday through Monday: it takes in Thursday and Friday
openers, the Saturday slate, and Sunday/Monday night games, and stops before the
following Tuesday. Games already kicked off are excluded -- a pregame number
next to a game in progress is not a preview.

## Why the slate is not ranked by the model

Asked for the games people care about, the model is the wrong instrument. The
`watchability` score already in the data is 40% team rating and 35% "how close
are the two probabilities", so it ranks a tight game between two unknowns above
a marquee one -- it answers "which game is competitive", not "which game will
people watch".

`fan_score()` answers the second question from what the ranking already carries:
each team earns points for being ranked (26 - rank) and for its conference tier,
and the pair is scored `2 * weaker + stronger`. Weighting the weaker side is the
whole trick -- a marquee game needs two real teams, so a top-five side hosting an
FCS opponent scores below two ranked teams meeting. It is editorial, it is meant
to be, and the inputs are printed alongside the output so a choice can be argued
with.

Usage:
    python social_export.py                     # writes into social/<year>-week-NN/
    python social_export.py --out somewhere/
    python social_export.py --print             # brief.txt to stdout, writes nothing
    python social_export.py --games 8 --upsets 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

SPORT = "ncaaf"
# Points a team contributes for its conference tier. A ranked team already earns
# far more than this; the tier is what separates two unranked-but-real teams
# from a body-bag opponent.
TIER_POINTS = {"power": 6, "group_of_five": 2}
RANKED_DEPTH = 25


class ExportError(RuntimeError):
    pass


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def week_window(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """From now to the end of the coming Monday.

    A college football week is Tuesday through Monday, so this covers the
    Thursday/Friday openers, Saturday, and the Sunday and Monday night games,
    and stops before the next Tuesday. On a Monday the window is the rest of
    that day, which is correct: those games are still this week's.
    """
    now = now or _utc_now()
    days_to_monday = (0 - now.weekday()) % 7
    monday = (now + dt.timedelta(days=days_to_monday)).date()
    end = dt.datetime.combine(monday, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)
    return now, end


def parse_kickoff(value: object) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def load_ranking() -> dict:
    import betbetter_handoff

    entry = betbetter_handoff.rankings(betbetter_handoff.load(), SPORT)
    if not isinstance(entry, dict) or not entry.get("available"):
        raise ExportError("no NCAAF ranking is published")
    return entry


def load_document() -> dict:
    import betbetter_handoff

    return betbetter_handoff.load() or {}


def team_points(name: str, by_name: dict[str, dict]) -> tuple[int, int | None]:
    """(points, rank-or-None) for one team."""
    row = by_name.get(name)
    if not row:
        return 0, None
    rank = row.get("rank")
    ranked = isinstance(rank, int) and rank <= RANKED_DEPTH
    points = ((RANKED_DEPTH + 1 - rank) * 2 if ranked else 0) + TIER_POINTS.get(row.get("tier"), 0)
    return points, (rank if ranked else None)


def fan_score(home_pts: int, away_pts: int) -> int:
    """Two real teams beat one great team and a tune-up.

    `2 * weaker + stronger` rather than a plain sum: a sum lets a single
    top-five side carry a game against an unrated opponent past two ranked
    teams playing each other, which is the opposite of what a viewer would pick.
    """
    return 2 * min(home_pts, away_pts) + max(home_pts, away_pts)


def weekly_games(document: dict, by_name: dict[str, dict],
                 window: tuple[dt.datetime, dt.datetime]) -> list[dict]:
    start, end = window
    out = []
    for pick in document.get("picks") or []:
        if not isinstance(pick, dict):
            continue
        kickoff = parse_kickoff(pick.get("kickoff"))
        if kickoff is None or not (start <= kickoff <= end):
            continue
        home, away = str(pick.get("home") or ""), str(pick.get("away") or "")
        home_pts, home_rank = team_points(home, by_name)
        away_pts, away_rank = team_points(away, by_name)
        model, market = pick.get("model_pct"), pick.get("market_pct")
        out.append({
            "kickoff": kickoff.isoformat().replace("+00:00", "Z"),
            "day": kickoff.strftime("%a"),
            "home": home,
            "away": away,
            "home_rank": home_rank,
            "away_rank": away_rank,
            "pick": pick.get("pick_name"),
            "model_pct": model,
            "market_pct": market,
            "edge_points": pick.get("edge_points"),
            "best_price": pick.get("best_price"),
            "sides": pick.get("sides") or [],
            "fan_score": fan_score(home_pts, away_pts),
        })
    out.sort(key=lambda g: (-g["fan_score"], g["kickoff"]))
    return out


def underdog_side(game: dict) -> dict | None:
    """The one side the market has as the underdog, or None.

    Exactly one per game: the market prices two sides, and only one of them can
    be below even money. That is what makes an upset a property of a game rather
    than of a pick.
    """
    sides = [s for s in (game.get("sides") or []) if isinstance(s, dict)]
    priced = [s for s in sides
              if isinstance(s.get("market_pct"), (int, float))
              and isinstance(s.get("model_pct"), (int, float))]
    if len(priced) != 2:
        return None
    dog = min(priced, key=lambda s: s["market_pct"])
    return dog if dog["market_pct"] < 50 else None


def weekly_upsets(games: list[dict], limit: int) -> list[dict]:
    """Games where the model rates the market's underdog far above the market.

    This asks a question about the *game*, not about the pick, and that
    distinction was worth getting wrong once. Filtering on the model's chosen
    side hides the clearest upset on the board: in Tulsa v Oklahoma State the
    model picks Oklahoma State, so a pick-side filter drops the game entirely --
    and misses that the model has Tulsa at 43.1% where the market has them at
    17.9%. The model does not have to pick the underdog outright to be saying
    something loudly about them.

    So: take each game's one underdog side and score the gap between the model
    and the market on it. One candidate per game, and only where the model is
    the more optimistic of the two.

    Derived from the already-filtered weekly list rather than the handoff's own
    upset_of_the_week, which looks seven days ahead on its own clock (so it can
    name a game outside this window) and, being written by the engine rather
    than recomputed, can still carry pre-correction numbers.
    """
    candidates = []
    for game in games:
        dog = underdog_side(game)
        if dog is None:
            continue
        gap = round(dog["model_pct"] - dog["market_pct"], 1)
        if gap <= 0:
            continue  # the model agrees with the market, or likes them less
        candidates.append(dict(
            game,
            underdog=dog.get("selection"),
            underdog_model_pct=dog["model_pct"],
            underdog_market_pct=dog["market_pct"],
            underdog_best_price=dog.get("best_price"),
            disagreement_points=gap,
        ))
    candidates.sort(key=lambda g: (-g["disagreement_points"], g["kickoff"]))
    return candidates[:limit]


def build(games_limit: int, upsets_limit: int) -> dict:
    ranking = load_ranking()
    rows = [r for r in (ranking.get("rankings") or []) if isinstance(r, dict)]
    by_name = {str(r.get("team_name")): r for r in rows}
    document = load_document()
    start, end = week_window()

    top25 = [{
        "rank": r.get("rank"),
        "team": r.get("team_name"),
        "rating": r.get("rating"),
        "conference": r.get("conference"),
        "sos": r.get("sos"),
        "record": "%s-%s" % (r.get("wins"), r.get("losses")),
    } for r in rows[:RANKED_DEPTH]]

    games = weekly_games(document, by_name, (start, end))
    return {
        "generated_at": _utc_now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "handoff_generated_at": document.get("generated_at"),
        "week": {
            "from": start.isoformat(timespec="minutes").replace("+00:00", "Z"),
            "to": end.isoformat(timespec="minutes").replace("+00:00", "Z"),
            "games_in_window": len(games),
            "picks_in_handoff": len(document.get("picks") or []),
        },
        "basis": (ranking.get("basis") or {}).get("label"),
        "ranking_published_on": ranking.get("published_on"),
        "season": ranking.get("season"),
        "top25": top25,
        "slate": games[:games_limit],
        "upsets": weekly_upsets(games, upsets_limit),
    }


def _pct(value: object) -> str:
    return ("%.1f%%" % value) if isinstance(value, (int, float)) else "--"


def brief(payload: dict) -> str:
    lines = []
    week = payload["week"]
    lines.append("COLLEGE MATCHDAY -- WEEK OF %s" % week["from"][:10])
    lines.append("Games from %s to %s (UTC)." % (week["from"], week["to"]))
    lines.append("%d of %d picks in the handoff fall in this window; the rest are later dates "
                 "and are excluded." % (week["games_in_window"], week["picks_in_handoff"]))
    lines.append("Ratings published %s -- %s." % (payload["ranking_published_on"], payload["basis"]))
    lines.append("")

    lines.append("== TOP 25 ==")
    lines.append("%-4s %-30s %-8s %-20s %s" % ("#", "TEAM", "RATING", "CONFERENCE", "SoS"))
    for row in payload["top25"]:
        rating = row["rating"]
        lines.append("%-4s %-30s %-8s %-20s %s" % (
            row["rank"], row["team"],
            ("%+.1f" % rating) if isinstance(rating, (int, float)) else "--",
            row["conference"] or "", row["sos"]))
    lines.append("")

    lines.append("== THIS WEEK'S GAMES ==")
    lines.append("%-5s %-32s %-32s %-8s %-8s %s" % ("DAY", "HOME", "AWAY", "MODEL", "MARKET", "PICK"))
    for game in payload["slate"]:
        home = ("#%d " % game["home_rank"] if game["home_rank"] else "") + game["home"]
        away = ("#%d " % game["away_rank"] if game["away_rank"] else "") + game["away"]
        lines.append("%-5s %-32s %-32s %-8s %-8s %s" % (
            game["day"], home[:32], away[:32],
            _pct(game["model_pct"]), _pct(game["market_pct"]), game["pick"]))
    lines.append("")

    lines.append("== UPSET WATCH ==")
    if not payload["upsets"]:
        lines.append("No game this week has the model backing a side the market has as an underdog.")
    for game in payload["upsets"]:
        lines.append("%-5s %s at %s" % (game["day"], game["away"], game["home"]))
        lines.append("      underdog %s -- model %s vs market %s (+%s pts)%s" % (
            game["underdog"], _pct(game["underdog_model_pct"]),
            _pct(game["underdog_market_pct"]), game["disagreement_points"],
            ("  best price %s" % game["underdog_best_price"])
            if game.get("underdog_best_price") else ""))
    lines.append("")
    lines.append("Data: CollegeFootballData. Ratings solved by Matchday. "
                 "Editorial, not advice.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None, help="output directory")
    parser.add_argument("--games", type=int, default=10, help="how many games to list")
    parser.add_argument("--upsets", type=int, default=3, help="how many upsets to list")
    parser.add_argument("--print", dest="to_stdout", action="store_true",
                        help="print the brief and write nothing")
    args = parser.parse_args(argv)

    try:
        payload = build(args.games, args.upsets)
    except ExportError as exc:
        print("social_export: %s" % exc, file=sys.stderr)
        return 1

    text = brief(payload)
    if args.to_stdout:
        print(text)
        return 0

    now = _utc_now()
    out_dir = args.out or os.path.join("social", "%d-week-%02d" % (
        now.isocalendar()[0], now.isocalendar()[1]))
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "slate.json")
    text_path = os.path.join(out_dir, "brief.txt")
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    with open(text_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")
    print("wrote %s and %s (%d games in window)"
          % (json_path, text_path, payload["week"]["games_in_window"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
