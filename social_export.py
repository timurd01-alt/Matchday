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
    python social_export.py --twitter           # the Top 25 as postable blocks
    python social_export.py --js                # also refresh social/weekly-data.js
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
    parser.add_argument("--js", action="store_true",
                        help="also regenerate social/weekly-data.js for the canvas graphics")
    parser.add_argument("--twitter", action="store_true",
                        help="print the Top 25 as ready-to-paste posts, and write nothing")
    args = parser.parse_args(argv)

    try:
        payload = build(args.games, args.upsets)
    except ExportError as exc:
        print("social_export: %s" % exc, file=sys.stderr)
        return 1

    if args.twitter:
        for post in twitter_thread(payload):
            print("-" * 46)
            print(post)
            print("-" * 46)
            print("   %d/%d characters\n" % (len(post), POST_LIMIT))
        return 0

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

    # Separated by a blank line and nothing else, so each post can be selected
    # and pasted without stripping decoration off it first.
    thread_path = os.path.join(out_dir, "top25-thread.txt")
    with open(thread_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(twitter_thread(payload)) + "\n")
    print("wrote %s, %s and %s (%d games in window)"
          % (json_path, text_path, thread_path, payload["week"]["games_in_window"]))

    if args.js:
        window = week_window()
        with open(JS_FILE, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(weekly_data_js(payload, window))
        print("wrote %s" % JS_FILE)
    return 0




# ---------------------------------------------------------------------------
# social/weekly-data.js -- the canvas graphics' input
#
# That file was written by hand, and hand-written data rots silently. When this
# generator was added it still claimed a slate of Notre Dame v Miami, Texas at
# Ohio State, Alabama at Florida State and Syracuse at Tennessee. Checked
# against the handoff's 400 fixtures: two of those games do not exist anywhere
# in the schedule, and the other two are 12 and 19 September -- one and two
# weeks out. Its upset was still the 50.7%/44.1% coin flip an earlier and wrong
# reading of "upset" produced. Only the Top 25 happened to be current, and only
# because nothing had moved it yet.
#
# So the numbers are generated from the same functions the brief uses, and the
# only hand-maintained thing left is the logo artwork itself.
# ---------------------------------------------------------------------------

LOGO_DIR = os.path.join("social", "logos")
JS_FILE = os.path.join("social", "weekly-data.js")

# Mirrors short() in social/graphics.js so a name shortened here is one the
# renderer would have shortened the same way.
MASCOTS = (
    " Fighting Irish", " Crimson Tide", " Nittany Lions", " Red Raiders", " Golden Hurricane",
    " Scarlet Knights", " Demon Deacons", " Yellow Jackets", " Mountaineers", " Thundering Herd",
    " Rainbow Warriors", " Green Wave", " Blue Devils", " Golden Bears", " Wolf Pack",
    " Hilltoppers", " Buckeyes", " Commodores", " Wolverines", " Volunteers", " Cardinals",
    " Hurricanes", " Bulldogs", " Cougars", " Sooners", " Trojans", " Hawkeyes", " Huskies",
    " Mustangs", " Longhorns", " Aggies", " Tigers", " Ducks", " Utes", " Rebels", " Hoosiers",
    " Seminoles", " Broncos", " Badgers", " Cardinal", " Pirates", " Bobcats", " Vandals",
    " Cowboys", " Spartans", " Rockets", " Bruins", " Panthers", " Gamecocks", " Razorbacks",
    " Wildcats", " Knights", " Owls", " Bears", " Eagles", " Falcons", " Raiders", " Lions",
)


def short_name(name: str) -> str:
    out = str(name or "")
    for mascot in MASCOTS:
        if out.endswith(mascot):
            return out[: -len(mascot)]
    return out


def _slug(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def logo_map(names: list[str], logo_dir: str = LOGO_DIR) -> dict[str, str]:
    """Match team names to the committed artwork by normalised name.

    Both the full name and the shortened one are emitted, because graphics.js
    looks the logo up by whatever string it is about to draw -- the Top 25 draws
    full names, the slate draws short ones.
    """
    try:
        files = [f for f in os.listdir(logo_dir) if f.lower().endswith(".png")]
    except OSError:
        return {}
    by_slug = {_slug(os.path.splitext(f)[0]): f for f in files}
    mapping = {}
    for name in names:
        for candidate in (name, short_name(name)):
            slug = _slug(candidate)
            match = by_slug.get(slug)
            if match is None:
                match = next((f for s, f in by_slug.items() if s and slug.startswith(s)), None)
            if match:
                mapping[candidate] = "logos/%s" % match
                mapping[short_name(candidate).upper()] = "logos/%s" % match
    return mapping


def week_label(window: tuple[dt.datetime, dt.datetime]) -> str:
    """"WEEK 1", taken from the fixture payload's own stage labels.

    Falls back to a date when that payload has nothing to say, which is honest:
    a wrong week number on a graphic is worse than no week number.
    """
    start, end = window
    try:
        with open("data_ncaaf.json", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        payload = {}
    stages: dict[str, int] = {}
    for match in payload.get("matches") or []:
        kickoff = parse_kickoff(match.get("kickoff"))
        stage = match.get("stage")
        if kickoff and stage and start <= kickoff <= end:
            stages[str(stage)] = stages.get(str(stage), 0) + 1
    if stages:
        return max(stages.items(), key=lambda kv: kv[1])[0].upper()
    return "WEEK OF %s" % start.strftime("%b %d").upper()


def _et(kickoff_iso: str) -> str:
    """Kickoff as US Eastern, which is how a college audience reads a time."""
    moment = parse_kickoff(kickoff_iso)
    if moment is None:
        return ""
    # Second Sunday in March to first Sunday in November is EDT (UTC-4).
    eastern = moment - dt.timedelta(hours=4 if 3 <= moment.month <= 10 else 5)
    hour = eastern.hour % 12 or 12
    return "%s · %d:%02d %s ET" % (eastern.strftime("%a").upper(), hour, eastern.minute,
                                   "PM" if eastern.hour >= 12 else "AM")


def _hook(game: dict) -> str:
    """A factual one-liner, not invented colour commentary."""
    home_rank, away_rank = game.get("home_rank"), game.get("away_rank")
    if home_rank and away_rank:
        return "#%d vs #%d" % (away_rank, home_rank)
    if home_rank or away_rank:
        return "RANKED #%d ON THE ROAD" % away_rank if away_rank else "RANKED #%d AT HOME" % home_rank
    return "%s KICKOFF" % game.get("day", "").upper()


def weekly_data_js(payload: dict, window: tuple[dt.datetime, dt.datetime],
                   slate_size: int = 5) -> str:
    slate = payload["slate"][:slate_size]
    upsets = payload["upsets"]
    names = [row["team"] for row in payload["top25"]]
    for game in slate:
        names += [game["home"], game["away"]]
    for game in upsets[:1]:
        names += [game["home"], game["away"]]

    upset_block = None
    if upsets:
        top = upsets[0]
        dog = top["underdog"]
        fav = top["home"] if short_name(top["home"]) != short_name(dog) else top["away"]
        upset_block = {
            "eyebrow": "MODEL UPSET WATCH",
            "underdog": short_name(dog).upper(),
            "favorite": short_name(fav).upper(),
            "kickoff": _et(top["kickoff"]),
            "modelPct": top["underdog_model_pct"],
            "marketPct": top["underdog_market_pct"],
            "note": "The model gives %s %.1f%% where the market gives %.1f%%." % (
                short_name(dog), top["underdog_model_pct"], top["underdog_market_pct"]),
        }

    data = {
        "week": week_label(window),
        "season": "%s SEASON" % payload.get("season", ""),
        "published": payload.get("ranking_published_on"),
        "generated_at": payload.get("generated_at"),
        "logos": logo_map(names),
        "top25": [[row["team"], row["rating"]] for row in payload["top25"]],
        "upset": upset_block,
        "slate": [{
            "rank": i + 1,
            "away": short_name(game["away"]).upper(),
            "home": short_name(game["home"]).upper(),
            "time": _et(game["kickoff"]),
            "hook": _hook(game),
        } for i, game in enumerate(slate)],
    }
    return ("// GENERATED by social_export.py -- do not edit by hand.\n"
            "// Every number here comes from betbetter_picks.json, filtered to the\n"
            "// current playing week. Regenerate with: python social_export.py --js\n"
            "window.MATCHDAY_SOCIAL = %s;\n"
            % json.dumps(data, indent=2, ensure_ascii=False))

# ---------------------------------------------------------------------------
# Copy-paste output for X
#
# A 25-row list does not fit in one post: at roughly 17 characters a row it is
# comfortably past 280 before the header. So this packs rows into as few posts
# as will hold them and prints each one separately with its own character count,
# which is the number that actually decides whether a post can be sent.
#
# The limit is enforced here rather than trusted. Team names change length
# between weeks -- "SMU" one week, "Southern Mississippi" the next -- so a
# layout that fits today can silently overflow later, and the failure would show
# up as a rejected post rather than as anything visible in this file.
# ---------------------------------------------------------------------------

POST_LIMIT = 280
# Room kept free for the "(n/N)" counter appended to every post.
COUNTER_ROOM = 8


def _post_rows(payload: dict) -> list[str]:
    rows = []
    for row in payload["top25"]:
        rating = row["rating"]
        rows.append("%d. %s %s" % (
            row["rank"], short_name(row["team"]),
            ("%+.1f" % rating) if isinstance(rating, (int, float)) else "--"))
    return rows


def twitter_thread(payload: dict, limit: int = POST_LIMIT) -> list[str]:
    """The Top 25 as posts that each fit, header on the first one.

    Packs greedily and never splits a team across two posts. Raises rather than
    emitting an over-length post, because a silently truncated ranking is worse
    than a loud failure.
    """
    week = payload["week"]
    header = "Model Top 25 -- college football, week of %s\n%s\n" % (
        week["from"][:10], payload.get("basis") or "Model rating")
    footer = ("\nRatings solved from results, not votes. "
              "Full board at matchdayterminal.com")

    rows = _post_rows(payload)

    # Balanced rather than greedy. Packing each post to the brim leaves the
    # remainder in the last one, which is how the first version produced a
    # third post containing nothing but the sign-off -- a post nobody would
    # send. Find the fewest posts the rows fit in, then spread them evenly
    # across exactly that many, so the header and the sign-off always travel
    # with real content.
    def attempt(count: int) -> list[str] | None:
        size, extra = divmod(len(rows), count)
        chunks, at = [], 0
        for i in range(count):
            take = size + (1 if i < extra else 0)
            chunks.append(rows[at:at + take])
            at += take
        built = []
        for i, chunk in enumerate(chunks):
            body = "\n".join(chunk)
            post = (header + body) if i == 0 else body
            if i == count - 1:
                post += footer
            if len(post) + COUNTER_ROOM > limit:
                return None
            built.append(post)
        return built

    posts = None
    for count in range(1, len(rows) + 1):
        posts = attempt(count)
        if posts:
            break
    if not posts:
        raise ExportError("the Top 25 cannot be split into posts under %d characters" % limit)

    total = len(posts)
    numbered = ["%s\n(%d/%d)" % (post, i + 1, total) for i, post in enumerate(posts)]
    for i, post in enumerate(numbered):
        if len(post) > limit:
            raise ExportError("post %d/%d is %d characters, over the %d limit"
                              % (i + 1, total, len(post), limit))
    return numbered


if __name__ == "__main__":
    raise SystemExit(main())
