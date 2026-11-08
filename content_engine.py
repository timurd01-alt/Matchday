"""content_engine.py -- the facts behind every Matchday social post, as typed items.

Phase 1 of the X/TikTok content bot. It decides *what* there is to say this
week and records where every number came from. It publishes nothing, renders
nothing, needs no credentials and no dependency outside the standard library,
so it cannot break the hourly deploy.

Every item carries:

    kind        one of KINDS
    key         stable dedupe id -- a publisher posts a key once, ever
    facts       the numbers, copied from the source, never recomputed for style
    source      file + sha256 of the exact block the facts were read from
    expires_at  after this the item is withdrawn, never posted late
    caption     a plain draft (<= 280 chars, link included) for X
    caveat      the source's own caveat, where it states one

Why the hard parts are hard
---------------------------

**Expiry is per item, and it is the earliest moment the post becomes wrong.**
An upset list expires at the *first* listed kickoff, not the last: a post
calling a game an upset pick after that game has started is no longer a
preview. A Top 25 expires when the next edition is due.

**Stale input says nothing.** If the handoff is older than MAX_HANDOFF_AGE the
engine emits no handoff-derived item at all and says why in `withheld`. A quiet
or stale week must produce an empty queue; a bot that always finds something
to post invents work to justify the trigger (AGENTS.md, Self-development loops).

**The hit rate is never shown on its own.** The scorecard's own caveat forbids
it: the cards are mostly heavy favourites. A scorecard item always carries the
expected rate and the versus-market record beside it, and states the misses.

**Picks here are live shadow forecasts, not official receipts.** The handoff
says so in `publication`, and every pick-bearing item repeats it in `caveat`.

Studio editions
---------------

`studio_edition()` writes the version-2 "edition" JSON that Matchday Studio's
"Load edition" button reads (Top 25 ratings, Top 25 ballot, 5 matchups, 3
upsets), with logos inlined from social/logos as data URIs, so a graphic is a
click rather than 60 retyped team names. It is built only when every list the
studio requires is complete; a partial edition is not written.

Usage:
    python content_engine.py                      # summary of this week's queue
    python content_engine.py --json               # full queue to stdout
    python content_engine.py --out DIR            # DIR/content_queue.json (+ studio edition)
    python content_engine.py --now 2026-11-05T15:00:00Z
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import json
import os
import sys
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

import social_export
import trdlab_handoff

BASE_URL = "https://matchdayterminal.com/"
MAX_CAPTION = 280
X_LINK_WEIGHT = 23
# Basketball mascots social_export's football list does not carry. Matched as
# whole trailing words, longest first, so "Iowa State Cyclones" -> "Iowa State".
EXTRA_MASCOTS = (
    " Ragin' Cajuns", " Warhawks", " Skyhawks", " Colonels", " Bearkats", " Great Danes", " Blue Hose", " Golden Flashes", " Fighting Illini", " Tar Heels", " Blue Devils", " Gators",
    " Cyclones", " Jayhawks", " Boilermakers", " Bluejays", " Red Storm", " Golden Eagles",
    " Gaels", " Zags", " Hokies", " Cavaliers", " Terrapins", " Orange", " Friars",
    " Musketeers", " Shockers", " Flyers", " Billikens", " Rams", " Mountaineers",
    " Horned Frogs", " Sun Devils", " Beavers", " Buffaloes", " Gophers", " Golden Gophers",
    " Cornhuskers", " Hawkeyes", " Penguins", " Bonnies", " Hoyas", " Wolfpack", " Lobos", " Aztecs", " Gamecocks",
    " Mean Green", " Roadrunners", " Miners", " Hornets", " Monarchs", " Dukes",
    " Bearcats", " Red Raiders", " Razorbacks", " Mustangs", " Pirates", " Owls",
    " Ramblers", " Explorers", " Pilots", " Toreros", " Dons", " Waves", " Anteaters",
    " Tritons", " Highlanders", " Matadors", " 49ers", " Bulls", " Blue Raiders",
    " Hilltoppers", " Racers", " Salukis", " Redbirds", " Sycamores", " Panthers",
    " Hawks", " Golden Grizzlies", " Phoenix", " Titans", " Vikings", " Norse",
    " Mastodons", " Jaguars", " Paladins", " Spiders", " Rebels", " Volunteers",
    " Commodores", " Seminoles", " Yellow Jackets", " Demon Deacons", " Orangemen",
)
# The handoff is rebuilt at least weekly by the Sunday ship. Past this it is
# last week's news and nothing derived from it is posted.
MAX_HANDOFF_AGE = dt.timedelta(days=8)
# A published Top 25 is an edition for one week.
EDITION_LIFETIME = dt.timedelta(days=7)
# A finished week's upset calls stay reportable for this long after the last game.
RESULTS_LIFETIME = dt.timedelta(days=4)
ARTICLE_LIFETIME = dt.timedelta(days=14)
SPORT_LABELS = {"ncaaf": "College football", "ncaam": "Men's college basketball"}
KINDS = (
    "power_top25", "ballot_top25", "slate_preview", "upset_watch",
    "game_of_the_week", "upset_results", "scorecard", "article", "bracketology",
)
BRACKETOLOGY_PATH = "bracketology_ncaam.json"
# The early phase is a preseason guess the site badges as such; it is not
# something to broadcast. Posts start once the projection is in season.
BRACKETOLOGY_PHASES = ("in_season", "championship_week", "official")
SLATE_SIZE = 5
UPSET_SIZE = 3
STUDIO_VERSION = 2
STUDIO_EDITION_MAX = 38
STUDIO_FOOTER_MAX = 44
STUDIO_NAME_MAX = 30
STUDIO_DETAIL_MAX = 36
LOGO_DIR = Path(__file__).resolve().parent / "social" / "logos"
# Studio-corrected artwork that wins over social/logos for the graphics only
# (Iowa's committed mark is black, invisible on the studio's dark background).
LOGO_OVERRIDE_DIR = Path(__file__).resolve().parent / "social" / "studio" / "logo-overrides"

# Feeds name a school by its brand ("UConn", "App State", "UTSA"); the logo
# files are named by the full school ("connecticut", "appalachianState"). Keys
# are slugs of the mascot-less name, values are logo file stems. Prefix
# matching cannot bridge these: "uconn" shares no prefix with "connecticut".
LOGO_ALIASES = {
    "uconn": "connecticut",
    "appstate": "appalachianState",
    "louisiana": "louisianaLafayette",
    "ulmonroe": "louisianaMonroe",
    "utsa": "texasSanAntonio",
    "utmartin": "tennesseeMartin",
    "mcneese": "mcNeeseState",
    "nicholls": "nichollsState",
    "samhouston": "samHoustonState",
    "selouisiana": "southeasternLouisiana",
    "thecitadel": "citadel",
    "ualbany": "albany",
    "grambling": "gramblingState",
    "presbyterian": "presbyterianCollege",
    "easttexasam": "eastTexasAAndM",
    "sanjosestate": "sanJoseState",
    "sanjosstate": "sanJoseState",  # "San Jos� State": an upstream decode lost the accent
}
# A 1x1 transparent PNG. The studio requires an image for every team; a team
# with no committed artwork gets this and is listed in the edition's warnings.
BLANK_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)


@dataclasses.dataclass
class ContentItem:
    kind: str
    key: str
    sport: str
    title: str
    facts: dict[str, Any]
    source: dict[str, Any]
    expires_at: str
    link: str
    caption: str
    caveat: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------------------- helpers

def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: object) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            moment = dt.datetime.combine(dt.date.fromisoformat(text[:10]), dt.time())
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def digest(block: object) -> str:
    """sha256 of a block's canonical JSON, so a post can be traced to its exact input."""
    raw = json.dumps(block, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source(path: str, pointer: str, block: object, generated_at: object) -> dict[str, Any]:
    return {"file": path, "pointer": pointer, "sha256": digest(block),
            "generated_at": generated_at}


def _pct(value: object) -> str:
    return "%.1f%%" % float(value) if isinstance(value, (int, float)) else "n/a"


def link(view: str, sport: str, campaign: str, platform: str = "x") -> str:
    query = urllib.parse.urlencode({
        "sport": sport, "view": view, "utm_source": platform,
        "utm_medium": "organic_social", "utm_campaign": campaign,
    })
    return f"{BASE_URL}?{query}"


def x_length(text: str) -> int:
    """Length as X counts it: every link is wrapped to t.co and weighs 23."""
    return sum(X_LINK_WEIGHT if word.startswith(("https://", "http://")) else len(word)
               for word in text.split(" ")) + text.count(" ")


def fit(text: str, limit: int = MAX_CAPTION) -> str:
    """Keep a caption under X's limit without ever cutting its trailing URL."""
    text = " ".join(str(text).split())
    if x_length(text) <= limit:
        return text
    head, sep, tail = text.rpartition(" ")
    if sep and tail.startswith(("https://", "http://")):
        room = limit - X_LINK_WEIGHT - 2
        return head[:room].rstrip(" ,.;:-") + "… " + tail
    return text[: limit - 1].rstrip(" ,.;:-") + "…"


def short(name: object) -> str:
    """School name without its mascot, matching the longest mascot first.

    Longest first across both lists: "Marquette Golden Eagles" ends with
    " Eagles" too, and stripping that first leaves "Marquette Golden".
    """
    text = str(name or "")
    for mascot in _MASCOTS:
        if text.endswith(mascot) and len(text) > len(mascot):
            school = text[: -len(mascot)]
            # A two-word mascot whose first word is a colour or descriptor:
            # "Army Black Knights" matches " Knights" and would leave "Army Black".
            head, _, last = school.rpartition(" ")
            if head and last in MASCOT_MODIFIERS:
                return head
            return school
    return text


# Words that begin two-word mascots. "Green" is deliberately absent: Bowling
# Green is a school, and Mean Green is listed whole.
MASCOT_MODIFIERS = frozenset({
    "Golden", "Black", "Blue", "Purple", "Fighting", "Red", "River", "Scarlet", "Yellow",
    "Rainbow", "Thundering", "Demon", "Flying", "Sun", "Horned", "Nittany", "Mean", "Tar",
    "Delta", "Ragin'", "Crimson",
})
_MASCOTS = tuple(sorted(set(social_export.MASCOTS) | set(EXTRA_MASCOTS), key=len, reverse=True))


# --------------------------------------------------------------------------- item builders

def power_top25(document: dict, sport: str, now: dt.datetime, path: str) -> list[ContentItem]:
    entry = (document.get("rankings") or {}).get(sport) or {}
    rows = [r for r in entry.get("rankings") or [] if isinstance(r, dict)][:25]
    published = parse_time(entry.get("published_on"))
    if not entry.get("available") or len(rows) < 25 or published is None:
        return []
    expires = published + EDITION_LIFETIME
    if now >= expires:
        return []
    top = [{
        "rank": r.get("rank"), "team": r.get("team_name"), "rating": r.get("rating"),
        "record": "%s-%s" % (r.get("wins"), r.get("losses"))
        if r.get("wins") is not None else None,
        "movement": r.get("movement"), "conference": r.get("conference"),
    } for r in rows]
    leaders = ", ".join("%d %s" % (r["rank"], short(r["team"])) for r in top[:5])
    label = SPORT_LABELS[sport]
    url = link("groups", sport, "power_top25")
    basis = (entry.get("basis") or {}).get("label") if isinstance(entry.get("basis"), dict) else None
    return [ContentItem(
        kind="power_top25", key=f"power_top25:{sport}:{entry['published_on']}", sport=sport,
        title=f"{label} power rating Top 25 — {entry['published_on']}",
        facts={"published_on": entry["published_on"], "season": entry.get("season"),
               "basis": basis, "rows": top},
        source=_source(path, f"rankings.{sport}", entry, document.get("generated_at")),
        expires_at=_iso(expires), link=url,
        caption=fit(f"{label} power rating Top 25 ({entry['published_on']}): {leaders}. "
                    f"Full 25 with ratings and schedule strength: {url}"),
        caveat="Matchday's own opponent-adjusted rating, not the AP or CFP poll.",
    )]


def ballot_top25(document: dict, sport: str, now: dt.datetime, path: str) -> list[ContentItem]:
    entry = (document.get("ballots") or {}).get(sport) or {}
    rows = [r for r in entry.get("rankings") or [] if isinstance(r, dict)][:25]
    published = parse_time(entry.get("published_on"))
    if not entry.get("available") or len(rows) < 25 or published is None:
        return []
    expires = published + EDITION_LIFETIME
    if now >= expires:
        return []
    top = [{"rank": r.get("rank"), "team": r.get("team_name"),
            "record": (r.get("resume") or {}).get("record")} for r in rows]
    leaders = ", ".join("%d %s" % (r["rank"], short(r["team"])) for r in top[:5])
    url = link("groups", sport, "ballot_top25")
    return [ContentItem(
        kind="ballot_top25", key=f"ballot_top25:{sport}:{entry['published_on']}", sport=sport,
        title=f"Matchday Top 25 ballot — {entry['published_on']}",
        facts={"published_on": entry["published_on"], "basis": entry.get("basis"), "rows": top},
        source=_source(path, f"ballots.{sport}", entry, document.get("generated_at")),
        expires_at=_iso(expires), link=url,
        caption=fit(f"This week's Matchday Top 25 ballot: {leaders}. Agree or disagree? {url}"),
        caveat="A human ballot judged on resume, not the model's rating order.",
    )]


def _weekly_games(document: dict, now: dt.datetime) -> tuple[list[dict], dict[str, dict]]:
    """This week's football games, filtered exactly as the weekly export filters them."""
    ranking = (document.get("rankings") or {}).get("ncaaf") or {}
    rows = [r for r in ranking.get("rankings") or [] if isinstance(r, dict)]
    by_name = {str(r.get("team_name")): r for r in rows}
    start, end = social_export.week_window(now)
    games = social_export.weekly_games(document, by_name, (start, end))
    if not games and start.weekday() == 0:
        games = social_export.weekly_games(document, by_name, (start, end + dt.timedelta(days=7)))
    return games, by_name


def _game_fact(game: dict) -> dict[str, Any]:
    return {
        "kickoff": game.get("kickoff"), "kickoff_et": social_export._et(game.get("kickoff") or ""),
        "away": game.get("away"), "home": game.get("home"),
        "away_rank": game.get("away_rank"), "home_rank": game.get("home_rank"),
        "pick": game.get("pick"), "model_pct": game.get("model_pct"),
        "market_pct": game.get("market_pct"),
    }


def _live_caveat(document: dict) -> str:
    reason = (document.get("publication") or {}).get("reason")
    return reason or "Live model read, not a frozen pick. It can move before kickoff."


def slate_preview(document: dict, now: dt.datetime, path: str) -> list[ContentItem]:
    games, _ = _weekly_games(document, now)
    chosen = games[:SLATE_SIZE]
    if not chosen:
        return []
    facts = [_game_fact(g) for g in chosen]
    first = min(parse_time(g["kickoff"]) for g in chosen)
    lines = "; ".join("%s at %s" % (short(g["away"]), short(g["home"])) for g in facts[:3])
    url = link("matches", "ncaaf", "slate_preview")
    week_key = "%d-W%02d" % first.isocalendar()[:2]
    return [ContentItem(
        kind="slate_preview", key=f"slate_preview:ncaaf:{week_key}", sport="ncaaf",
        title="Top 5 college football games this week",
        facts={"games": facts, "ranking": "fan_score (editorial: ranked teams and conference tier)"},
        source=_source(path, "picks[week window]", [g for g in chosen], document.get("generated_at")),
        expires_at=_iso(first), link=url,
        caption=fit(f"Five games to clear your calendar for: {lines} and more. "
                    f"Model reads and market prices for each: {url}"),
        caveat="Editorial watchlist ranked for stakes, not by the model. " + _live_caveat(document),
    )]


def upset_watch(document: dict, now: dt.datetime, path: str) -> list[ContentItem]:
    games, by_name = _weekly_games(document, now)
    featured = (document.get("upset_of_the_week") or {}).get("pick")
    upsets = social_export.weekly_upsets(games, by_name, UPSET_SIZE, featured=featured)
    if not upsets:
        return []
    facts = []
    for g in upsets:
        fact = _game_fact(g)
        fact.update(underdog=g["underdog"], underdog_model_pct=g["underdog_model_pct"],
                    underdog_market_pct=g["underdog_market_pct"],
                    disagreement_points=g["disagreement_points"])
        facts.append(fact)
    first = min(parse_time(g["kickoff"]) for g in upsets)
    lead = facts[0]
    url = link("matches", "ncaaf", "upset_watch")
    keys = ",".join(sorted("%s@%s" % (f["away"], f["home"]) for f in facts))
    return [ContentItem(
        kind="upset_watch", key=f"upset_watch:ncaaf:{hashlib.sha1(keys.encode()).hexdigest()[:12]}",
        sport="ncaaf", title="Upset Watch",
        facts={"games": facts},
        source=_source(path, "picks[week window, underdog sides]", upsets, document.get("generated_at")),
        expires_at=_iso(first), link=url,
        caption=fit(f"Upset Watch: the model gives {short(lead['underdog'])} "
                    f"{_pct(lead['underdog_model_pct'])}; the market says "
                    f"{_pct(lead['underdog_market_pct'])}. "
                    f"Would you take the dog? Forecast, not betting advice. {url}"),
        caveat="Forecasting, not betting advice. " + _live_caveat(document),
    )]


def game_of_the_week(document: dict, now: dt.datetime, path: str) -> list[ContentItem]:
    block = document.get("game_of_the_week") or {}
    game = block.get("game") or {}
    kickoff = parse_time(game.get("kickoff"))
    home, away = game.get("home") or {}, game.get("away") or {}
    if not block.get("available") or kickoff is None or kickoff <= now:
        return []
    if not home.get("team") or not away.get("team"):
        return []
    sport = "ncaam" if str(game.get("competition")).upper() == "NCAAM" else "ncaaf"
    url = link("matches", sport, "game_of_the_week")
    facts = {
        "kickoff": game["kickoff"], "kickoff_et": social_export._et(game["kickoff"]),
        "away": away["team"], "away_rank": away.get("rank"), "away_record": away.get("record"),
        "home": home["team"], "home_rank": home.get("rank"), "home_record": home.get("record"),
        "model_pick": game.get("model_pick"), "model_pct": game.get("model_pct"),
        "market_pct": game.get("market_pct"),
    }
    rank = lambda r: "#%s " % r if r else ""
    return [ContentItem(
        kind="game_of_the_week", key=f"game_of_the_week:{sport}:{game.get('event_id')}",
        sport=sport, title="Game of the Week",
        facts=facts,
        source=_source(path, "game_of_the_week", block, document.get("generated_at")),
        expires_at=_iso(kickoff), link=url,
        caption=fit(f"Game of the Week: {rank(away.get('rank'))}{short(away['team'])} at "
                    f"{rank(home.get('rank'))}{short(home['team'])}, {facts['kickoff_et']}. "
                    f"Model: {short(game.get('model_pick'))} {_pct(game.get('model_pct'))} "
                    f"(market {_pct(game.get('market_pct'))}). {url}"),
        caveat=block.get("caveat") or _live_caveat(document),
    )]


def upset_results(document: dict, now: dt.datetime, path: str) -> list[ContentItem]:
    """Last recorded week's upset calls, graded -- wins and misses alike."""
    block = document.get("upset_of_the_week") or {}
    picks = [p for p in block.get("picks") or [] if isinstance(p, dict)]
    if not block.get("recorded") or not picks:
        return []
    if any(p.get("result") not in ("won", "lost") for p in picks):
        return []  # not every call is settled; a partial scoreline is not reported
    last = max((parse_time(p.get("kickoff")) for p in picks), default=None)
    if last is None:
        return []
    expires = last + RESULTS_LIFETIME
    if now >= expires:
        return []
    won = sum(p["result"] == "won" for p in picks)
    facts = [{k: p.get(k) for k in ("sport", "home", "away", "selection", "model_pct",
                                    "market_pct", "result", "home_score", "away_score")}
             for p in picks]
    sport = picks[0].get("sport") or "ncaaf"
    url = link("score", sport, "upset_results")
    names = "; ".join("%s %s" % (short(p["selection"]), p["result"]) for p in facts)
    return [ContentItem(
        kind="upset_results", key=f"upset_results:{block.get('week')}", sport=sport,
        title=f"Upset calls graded — {block.get('week')}",
        facts={"week": block.get("week"), "won": won, "lost": len(picks) - won, "calls": facts},
        source=_source(path, "upset_of_the_week", block, document.get("generated_at")),
        expires_at=_iso(expires), link=url,
        caption=fit(f"Last week's upset calls: {won} of {len(picks)} came in ({names}). "
                    f"Every call stays on the record, hits and misses: {url}"),
        caveat="Underdog calls are expected to lose more often than they win.",
    )]


def scorecard(document: dict, sport: str, now: dt.datetime, path: str) -> list[ContentItem]:
    sports = ((document.get("scorecard") or {}).get("sports") or {})
    card = sports.get(sport) or {}
    record = card.get("record") or {}
    market = (card.get("versus_market") or {}).get("beat_market") or {}
    generated = parse_time(document.get("generated_at"))
    if not card.get("available") or not card.get("reportable") or generated is None:
        return []
    needed = ("picks", "wins", "losses", "hit_rate_pct", "expected_hit_rate_pct")
    if any(not isinstance(record.get(k), (int, float)) for k in needed):
        return []
    if not isinstance(market.get("hit_rate_pct"), (int, float)):
        return []  # the hit rate is never shown without the market comparison
    vm = card.get("versus_market") or {}
    disagreed = vm.get("disagreed_with_market") or {}
    facts = {
        "picks": record["picks"], "wins": record["wins"], "losses": record["losses"],
        "hit_rate_pct": record["hit_rate_pct"],
        "expected_hit_rate_pct": record["expected_hit_rate_pct"],
        "confidence_interval_pct": record.get("confidence_interval_pct"),
        "beat_market_pct": market["hit_rate_pct"],
        "beat_market_picks": market.get("picks"),
        "beat_market_basis": market.get("basis"),
        "disagreed_with_market": {k: disagreed.get(k) for k in ("picks", "wins", "losses",
                                                                 "hit_rate_pct")},
        "lock_rule": (card.get("lock_policy") or {}).get("rule"),
    }
    label = SPORT_LABELS[sport]
    url = link("score", sport, "scorecard")
    return [ContentItem(
        kind="scorecard", key=f"scorecard:{sport}:{record['picks']}", sport=sport,
        title=f"{label} scorecard — {record['picks']} locked picks",
        facts=facts,
        source=_source(path, f"scorecard.sports.{sport}", card, document.get("generated_at")),
        expires_at=_iso(generated + EDITION_LIFETIME), link=url,
        caption=fit(f"{label} receipts: {record['wins']}-{record['losses']} on picks locked an "
                    f"hour before kickoff, {_pct(record['hit_rate_pct'])} against "
                    f"{_pct(record['expected_hit_rate_pct'])} expected. Closer than the market "
                    f"price on {_pct(market['hit_rate_pct'])} of picks. Every miss is public: {url}"),
        caveat=(document.get("scorecard") or {}).get("caveat"),
    )]


def articles(posts: object, now: dt.datetime, path: str) -> list[ContentItem]:
    if not isinstance(posts, list):
        return []
    out = []
    for post in posts:
        if not isinstance(post, dict) or not post.get("slug") or not post.get("title"):
            continue
        published = parse_time(post.get("date"))
        if published is None or now >= published + ARTICLE_LIFETIME or published > now:
            continue
        url = f"{BASE_URL}posts/{urllib.parse.quote(str(post['slug']))}.html"
        out.append(ContentItem(
            kind="article", key=f"article:{post['slug']}", sport=str(post.get("comp") or ""),
            title=str(post["title"]), facts={"summary": post.get("summary"), "date": post.get("date")},
            source=_source(path, f"[slug={post['slug']}]", post, post.get("date")),
            expires_at=_iso(published + ARTICLE_LIFETIME), link=url,
            caption=fit(f"{post['title']}. {post.get('summary') or ''} {url}"),
        ))
    return out


def bracketology(document: object, now: dt.datetime, path: str) -> list[ContentItem]:
    """The projected (or official) No. 1 seeds, once the projection is in season."""
    if not isinstance(document, dict) or document.get("mock"):
        return []
    if document.get("phase") not in BRACKETOLOGY_PHASES:
        return []
    valid_until = parse_time(document.get("valid_until"))
    if valid_until is None or now >= valid_until:
        return []
    ones = sorted((f for f in document.get("field") or []
                   if isinstance(f, dict) and f.get("seed") == 1 and f.get("team_name")),
                  key=lambda f: f.get("overall_seed") or 99)
    if len(ones) < 4:
        return []
    official = document.get("phase") == "official"
    label = "Official No. 1 seeds" if official else "Projected No. 1 seeds"
    teams = ", ".join(f"{short(f['team_name'])} ({f.get('region')})" for f in ones[:4])
    beta = "" if document.get("calibrated") or official else " Beta projection."
    url = link("bracket", "ncaam", "bracketology")
    caveat = None if official else "Matchday's own projection, not the NCAA selection committee."
    return [ContentItem(
        kind="bracketology", key=f"bracketology:ncaam:{document.get('build_id')}", sport="ncaam",
        title=label,
        facts={"phase": document.get("phase"), "as_of": document.get("as_of"),
               "calibrated": bool(document.get("calibrated")),
               "simulations": document.get("simulations"),
               "one_seeds": [{"team": f["team_name"], "region": f.get("region"),
                              "overall_seed": f.get("overall_seed")} for f in ones[:4]]},
        source=_source(path, "field[seed=1]", ones[:4], document.get("as_of")),
        expires_at=_iso(valid_until), link=url,
        caption=fit(f"{label}: {teams}.{beta} The full field and every team's odds: {url}"),
        caveat=caveat,
    )]


# --------------------------------------------------------------------------- queue

def build_queue(now: dt.datetime | None = None, root: str | os.PathLike[str] = ".") -> dict[str, Any]:
    """Every postable item right now, plus what was withheld and why."""
    now = now or _utc_now()
    root = Path(root)
    handoff_path = root / trdlab_handoff.DEFAULT_HANDOFF_PATH
    withheld: list[dict[str, str]] = []
    items: list[ContentItem] = []

    document = trdlab_handoff.load(str(handoff_path), str(root / trdlab_handoff.DEFAULT_WITHHELD_PATH))
    generated = parse_time((document or {}).get("generated_at"))
    if document is None:
        withheld.append({"scope": "handoff", "reason": "trdlab_picks.json is absent"})
    elif generated is None or now - generated > MAX_HANDOFF_AGE:
        withheld.append({"scope": "handoff", "reason":
                         f"handoff generated_at {document.get('generated_at')!r} is older than "
                         f"{MAX_HANDOFF_AGE.days} days; nothing derived from it is posted"})
    else:
        name = trdlab_handoff.DEFAULT_HANDOFF_PATH
        for sport in SPORT_LABELS:
            items += power_top25(document, sport, now, name)
            items += ballot_top25(document, sport, now, name)
            items += scorecard(document, sport, now, name)
        items += slate_preview(document, now, name)
        items += upset_watch(document, now, name)
        items += game_of_the_week(document, now, name)
        items += upset_results(document, now, name)

    try:
        posts = json.loads((root / "posts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        posts = []
    items += articles(posts, now, "posts.json")
    try:
        bracket = json.loads((root / BRACKETOLOGY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bracket = None
    items += bracketology(bracket, now, BRACKETOLOGY_PATH)

    items = [i for i in items if parse_time(i.expires_at) > now]
    return {
        "generated_at": _iso(now),
        "handoff_generated_at": (document or {}).get("generated_at"),
        "items": [i.to_dict() for i in items],
        "withheld": withheld,
    }


# --------------------------------------------------------------------------- studio

def _logo_index(logo_dir: Path, override_dir: Path | None = None) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for directory in (logo_dir, override_dir):
        if directory is None:
            continue
        try:
            index.update({social_export._slug(p.stem): p for p in Path(directory).glob("*.png")})
        except OSError:
            pass
    return index


def _ascii(text: str) -> str:
    """Drop accents so "San José" and "San Jose" share one slug."""
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")


def logo_for(team: str, index: dict[str, Path]) -> Path | None:
    """Exact match on full or mascot-less name first, then the *longest* prefix.

    Longest, not first: "Ohio State Buckeyes" starts with both "ohio" and
    "ohiostate", and taking whichever file the directory listed first is how a
    graphic gets the wrong school's logo.
    """
    for candidate in (team, short(team)):
        slug = social_export._slug(_ascii(candidate))
        hit = index.get(slug) or index.get(social_export._slug(LOGO_ALIASES.get(slug, "")))
        if hit:
            return hit
    slug = social_export._slug(team)
    prefixes = [s for s in index if s and slug.startswith(s)]
    return index[max(prefixes, key=len)] if prefixes else None


def _studio_team(team: str, index: dict[str, Path], missing: list[str]) -> dict[str, str]:
    path = logo_for(team, index)
    if path is None:
        missing.append(team)
        src = BLANK_PNG
    else:
        src = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    key = path.stem if path else social_export._slug(team)
    return {"team": key, "name": short(team).upper()[:STUDIO_NAME_MAX], "src": src}


def studio_edition(queue: dict[str, Any], logo_dir: Path = LOGO_DIR,
                   override_dir: Path | None = LOGO_OVERRIDE_DIR) -> dict[str, Any] | None:
    """A Matchday Studio version-2 edition, or None if any required list is short.

    The studio refuses an edition without exactly 25 rankings and 5 matchups,
    and treats ballot (25) and upsets (3) as optional-but-exact. Mirrored here
    so the file always loads.
    """
    by_kind = {(i["kind"], i["sport"]): i for i in queue.get("items", [])}
    power = by_kind.get(("power_top25", "ncaaf"))
    slate = by_kind.get(("slate_preview", "ncaaf"))
    if not power or not slate or len(slate["facts"]["games"]) < SLATE_SIZE:
        return None
    index = _logo_index(Path(logo_dir), override_dir)
    missing: list[str] = []
    day = parse_time(power["facts"]["published_on"])
    stamp = f"{day:%b} {day.day}, {day.year}".upper()
    rankings = [dict(_studio_team(r["team"], index, missing), detail="%.2f" % r["rating"])
                for r in power["facts"]["rows"]]
    matchups = [{"left": _studio_team(g["away"], index, missing),
                 "right": _studio_team(g["home"], index, missing),
                 "detail": g["kickoff_et"][:STUDIO_DETAIL_MAX]}
                for g in slate["facts"]["games"][:SLATE_SIZE]]
    edition: dict[str, Any] = {
        "version": STUDIO_VERSION, "mode": "rankings",
        "edition": stamp[:STUDIO_EDITION_MAX], "footer": "WHO MAKES YOUR LIST?",
        "rankings": rankings, "matchups": matchups,
    }
    ballot = by_kind.get(("ballot_top25", "ncaaf"))
    if ballot and len(ballot["facts"]["rows"]) == 25:
        edition["ballot"] = [dict(_studio_team(r["team"], index, missing), detail="")
                             for r in ballot["facts"]["rows"]]
        edition["ballotEdition"] = stamp[:STUDIO_EDITION_MAX]
        edition["ballotFooter"] = "AGREE OR DISAGREE?"
    upsets = by_kind.get(("upset_watch", "ncaaf"))
    if upsets and len(upsets["facts"]["games"]) == UPSET_SIZE:
        # Studio layout: left is the favourite on alert, right the challenger.
        rows = []
        for g in upsets["facts"]["games"]:
            dog = g["underdog"]
            fav = g["home"] if dog == g["away"] else g["away"]
            rows.append({"left": _studio_team(fav, index, missing),
                         "right": _studio_team(dog, index, missing),
                         "detail": g["kickoff_et"][:STUDIO_DETAIL_MAX]})
        edition["upsets"] = rows
        edition["upsetFooter"] = "WHICH FAVORITE GOES DOWN?"
    edition["_matchday"] = {
        "generated_at": queue.get("generated_at"),
        "sources": sorted({i["source"]["sha256"] for i in (power, slate, ballot, upsets) if i}),
        "missing_logos": sorted(set(missing)),
    }
    return edition


# --------------------------------------------------------------------------- cli

def _summary(queue: dict[str, Any]) -> str:
    lines = [f"Content queue at {queue['generated_at']} "
             f"(handoff {queue.get('handoff_generated_at')})"]
    if not queue["items"]:
        lines.append("No postable content right now. Nothing to post; do not invent any.")
    for item in queue["items"]:
        lines.append(f"\n[{item['kind']}] {item['key']}  (expires {item['expires_at']})")
        lines.append(f"  {item['caption']}")
    for entry in queue["withheld"]:
        lines.append(f"\nwithheld {entry['scope']}: {entry['reason']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--now", help="evaluate as of this UTC time (ISO 8601)")
    parser.add_argument("--json", action="store_true", help="print the full queue as JSON")
    parser.add_argument("--out", help="write content_queue.json and studio-edition.json here")
    args = parser.parse_args(argv)
    now = parse_time(args.now) if args.now else None
    if args.now and now is None:
        parser.error("--now must be an ISO 8601 time")
    queue = build_queue(now)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "content_queue.json").write_text(
            json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        edition = studio_edition(queue)
        if edition is not None:
            (out / "studio-edition.json").write_text(json.dumps(edition), encoding="utf-8")
        print(f"wrote {out / 'content_queue.json'} ({len(queue['items'])} items)"
              + (f" and {out / 'studio-edition.json'}" if edition else "; no complete studio edition"))
    if args.json:
        print(json.dumps(queue, indent=2, ensure_ascii=False))
    elif not args.out:
        print(_summary(queue))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
