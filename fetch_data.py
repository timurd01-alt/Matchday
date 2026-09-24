"""
matchday fetcher  (v5)
----------------------
  College data APIs  -> NCAAF/NCAAM schedules + tables (shared free key)
  The Odds API       -> pregame win probabilities     (required key)
  SportsDataIO       -> dormant pregame overlay        (trial/licensed key)
  SportsGameOdds     -> fallback market context        (licensed key)

College football and men's college basketball are the only competitions.

The product is intentionally pregame/postgame rather than a live-score feed:
  * predictions lock before kickoff and are not rewritten during games;
  * results are fetched after kickoff for public grading;
  * odds are requested only for near-kickoff upcoming games and cached on disk.

Run:  python fetch_data.py          (once)
      python fetch_data.py --loop   (hourly result checks)
"""

import json, os, sys, time, datetime, re, unicodedata, urllib.request, urllib.error, urllib.parse, math, traceback, contextlib
import html
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from collections import defaultdict
import mfti_research
import forecast_ledger
import game_archive
import betbetter_handoff
import forecast_pause
import market_snapshots
import pregame_context
import provider_quota
import refresh_ncaaf_venues
from pick_integrity import is_official_pick_record
from advanced_metrics_store import attach_shadow_profiles
from provider_adapters import (ProviderError,
                               CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter,
                               SportsDataIOAdapter, SportsGameOddsAdapter, normalized_score,
                               season_form_from_matches, blend_season_history,
                               is_placeholder_team_name)

# Windows terminals default to a legacy codec that crashes on characters like the
# checkmark or accented player names. Force UTF-8 so background prints never crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
#  PRIVATE KEYS
#  - CFBD/CBBD power fixtures and tables; The Odds API powers probabilities
# ============================================================
try:
    from config_keys import ODDS_API_KEY
except Exception as _cfg_err:
    import os as _os
    if _os.path.exists("config_keys.py"):
        print(f"\n!! config_keys.py exists but could not be loaded: {_cfg_err}")
        print("!! Open it and check: straight double-quotes, one key per line, valid Python.\n")
    else:
        print("\n!! config_keys.py not found in this folder.")
        print("!! Check the exact filename (View > File name extensions in Explorer —")
        print("!! watch for config_keys.py.txt or config_keys(3).py) and that it sits")
        print("!! next to fetch_data.py.\n")
    ODDS_API_KEY = "PASTE_ODDS_API_KEY_IN_config_keys.py"
try:
    from config_keys import SPORTSDATAIO_KEY
except Exception:
    SPORTSDATAIO_KEY = os.environ.get("SPORTSDATAIO_KEY", "")
try:
    from config_keys import SPORTSDATAIO_PREGAME_ENABLED
except Exception:
    SPORTSDATAIO_PREGAME_ENABLED = os.environ.get("SPORTSDATAIO_PREGAME_ENABLED", "")
SPORTSDATAIO_PREGAME_ENABLED = str(SPORTSDATAIO_PREGAME_ENABLED).lower() in {
    "1", "true", "yes", "on"
}
try:
    from config_keys import SPORTSGAMEODDS_KEY
except Exception:
    SPORTSGAMEODDS_KEY = os.environ.get("SPORTSGAMEODDS_KEY", "")
try:
    from config_keys import CFBD_KEY, CBBD_KEY
except Exception:
    CFBD_KEY = os.environ.get("CFBD_KEY", "")
    CBBD_KEY = os.environ.get("CBBD_KEY", "")
# ============================================================

IDLE_MINUTES = 60
LIVE_SECONDS = 3600   # legacy local loop: in-progress games only need hourly result checks
ODDS_CACHE_MIN = 180  # one pregame market snapshot per competition window
OUT_FILE = "data.json"
MODEL_SIGNAL_SCHEMA = 8  # adds per-sport independent-probability calibration
PREDICTION_MODEL_VERSION = "v6-calibrated"

# ---- per-sport independent-probability calibration --------------------------
# predict() builds its independent read as a ratio of hand-weighted strength
# sums, sh/(sh+sa). That ratio is not fitted to outcomes, and its spread was
# tuned on the high-signal American sports; the same factor weights applied to
# a sport whose true single-game win probability rarely leaves 35-65% produce
# stated confidences far wider than the sport can support.
#
# Sports with no graded evidence stay at 1.0 (exact previous behavior). Do not
# add an entry here without a measured ledger to justify it -- an unmeasured
# calibration constant is the same mistake as an unmeasured factor weight.
PROB_CALIBRATION = {}
DEFAULT_PROB_CALIBRATION = 1.0


def _calibration_factor(comp_key):
    return float(PROB_CALIBRATION.get(comp_key, DEFAULT_PROB_CALIBRATION))


def _calibrate_probs(probs, factor):
    """Shrink a h/d/a percentage triplet toward an even home/away split.

    The draw leg is left untouched -- this corrects the strength-ratio's
    over-confident *side* read, not the draw rate, which is derived separately
    and has its own evidence. At factor 1.0 this is an exact no-op.
    """
    if factor >= 1.0:
        return dict(probs)
    h = float(probs.get("h") or 0.0)
    a = float(probs.get("a") or 0.0)
    mid = (h + a) / 2.0
    return _round_triplet({"h": mid + (h - mid) * factor,
                           "d": float(probs.get("d") or 0.0),
                           "a": mid + (a - mid) * factor})

# ---- competition selection --------------------------------------------------
# College football is the default. Launch with --ncaam (or MATCHDAY_COMP=NCAAM)
# for men's college basketball. These are the only two competitions.
COMPETITIONS = {
    "NCAAF": {"label": "College Football", "sport": "football", "fd": None, "odds": "americanfootball_ncaaf",
            "outright": "americanfootball_ncaaf_championship_winner", "tournament": False,
            "source": "cfbd", "has_draws": False},
    "NCAAM": {"label": "Men's College Basketball", "sport": "basketball", "fd": None, "odds": "basketball_ncaab",
            "outright": "basketball_ncaab_championship_winner", "tournament": False,
            "source": "cbbd", "has_draws": False},
}
# ---- the active competition -------------------------------------------------
# COMP_KEY is a module-level singleton, and ~15 further module-level values are
# derived from it: the market URLs, every per-competition cache path, the
# ratings/opening-odds/picks ledgers, and the news feed set.
#
# Those derivations used to run inline at import and never again, so assigning
# COMP_KEY left the module half-switched -- COMP_KEY reporting NCAAF while
# RATINGS_FILE still pointed at the World Cup ledger. Every caller that needed
# to switch competition hand-patched around that to a different depth:
# refresh_college_talent reset RATINGS_FILE and the _RATINGS cache,
# backfill_history and audit_model_vs_market reset neither, and nothing
# anywhere reset RSS_FEEDS. Tests carried the same hazard at scale -- 70
# assignments to COMP_KEY against 24 restores.
#
# _competition_state() below is now the single place any of it is derived, and
# set_competition() applies it atomically. Switching is an explicit call:
# assigning the attribute still only moves the key, and
# test_competition_switch.CallerDisciplineTests fails any production module
# that tries it.
_COMP_FLAGS = ("--ncaaf", "--ncaam")

try:
    from config_keys import COMPETITION as _COMP
except Exception:
    _COMP = "NCAAF"
for _flag in _COMP_FLAGS:      # last matching flag wins, as the if-chain did
    if _flag in sys.argv:
        _COMP = _flag[2:].upper()
_env = os.environ.get("MATCHDAY_COMP", "").upper()
if _env: _COMP = _env


def normalize_competition(key):
    """The COMP_KEY this module would use for `key`; unknown keys fall back to NCAAF."""
    text = str(key or "").upper()
    return text if text in COMPETITIONS else "NCAAF"


def _competition_state(key):
    """Every module-level value derived from the active competition.

    Both the import-time application further down and set_competition() apply
    this one dict, so the two cannot drift apart. RSS_FEEDS is built separately
    by _build_rss_feeds() because it needs helpers defined later in the module.
    """
    comp = COMPETITIONS[key]
    low = key.lower()
    return {
        "COMP_KEY": key,
        "COMP": comp,
        "ODDS_URL": (f"https://api.the-odds-api.com/v4/sports/{comp['odds']}/odds/"
                     "?regions=eu&markets=h2h&oddsFormat=decimal"),
        "OUTRIGHTS_URL": (f"https://api.the-odds-api.com/v4/sports/{comp['outright']}/odds/"
                          "?regions=eu&markets=outrights&oddsFormat=decimal"),
        "ODDS_CACHE_FILE": f"odds_market_cache_{low}.json",
        "OUTRIGHTS_CACHE_FILE": f"outrights_market_cache_{low}.json",
        "SPORTSDATAIO_PREGAME_CACHE_FILE": f"sportsdataio_pregame_{low}_cache.json",
        "PREGAME_CONTEXT_CACHE_FILE": f"pregame_{low}_cache.json",
        "SPORTSGAMEODDS_CACHE_FILE": f"sportsgameodds_{low}_cache.json",
        "OPEN_FILE": f"odds_open_{low}.json",          # first-seen ("opening") odds
        "RATINGS_FILE": f"ratings_{low}.json",
        "PICKS_FILE": f"picks_log_{low}.json",         # committed picks
        "_news_term": NEWS_TERMS.get(key, comp["label"]),
    }


def set_competition(key):
    """Point the whole module at `key`, derived values and caches together.

    Returns the normalized COMP_KEY. Safe to call repeatedly. The per-competition
    load caches (_RATINGS, _OPEN) and the market/news response caches are cleared,
    because each holds data for the competition that was active when it was filled.
    """
    resolved = normalize_competition(key)
    state = _competition_state(resolved)
    globals().update(state)
    globals()["RSS_FEEDS"] = _build_rss_feeds(resolved, state["COMP"], state["_news_term"])
    globals()["_RATINGS"] = None
    globals()["_OPEN"] = None
    _ODDS_CACHE.update({"t": 0.0, "data": {}})
    _OUT_CACHE.update({"t": 0.0, "data": []})
    _NEWS_CACHE.update({"t": 0.0, "data": []})
    return resolved


@contextlib.contextmanager
def competition(key):
    """Run a block against `key`, restoring the previous competition afterwards.

    The restore is the point: switching by assignment leaks the new competition
    into whatever runs next, which is how the test suite ended up with 70
    switches and 24 restores.
    """
    previous = COMP_KEY
    set_competition(key)
    try:
        yield COMP_KEY
    finally:
        set_competition(previous)


# Routing `fetch_data.COMP_KEY = ...` through set_competition() automatically was
# tried and deliberately rejected: it made an innocuous-looking assignment reset
# ~15 values and clear caches at a distance, which silently discarded the
# temp-file RATINGS_FILE override that RatingsLookupTests sets up and wrote test
# data into the tracked ratings_ncaam.json / ratings_ncaaf.json. Switching is an
# explicit call instead, and test_competition_switch_is_atomic asserts that
# production modules use it rather than assigning the attribute.

ODDS_FREE_QUOTA_URL = "https://api.the-odds-api.com/v4/sports/?apiKey="
PREGAME_ODDS_WINDOW_HOURS = 24
UA = {"User-Agent": "Mozilla/5.0 (matchday-terminal)"}

API_FOOTBALL_MAX_INJURIES = 8
SPORTSDATAIO_PREGAME_CACHE_MIN = 15
SPORTSDATAIO_PREGAME_STALE_MAX_HOURS = 6
# The free plan is capped at 2,500 returned objects per month across seven
# Matchday competitions. One request per competition per day, capped at eight
# events, remains inside that budget; hourly odds polling would not.
SPORTSGAMEODDS_CACHE_MIN = 1440
# Ceiling above is wall-clock only, and the cached rows are keyed by the
# fixture ids that were inside the 36h window when it was written. That set
# rolls forward continuously in a league that plays daily, so a fixture
# entering the window after the write found no row and got no market for up
# to a full day -- while the age check still reported the cache fresh and
# suppressed the request that would have covered it. Measured live
# 2026-08-20: zero markets on all 195 upcoming MLB fixtures with the
# overlay reporting "local cache". This floor lets an uncovered near-term
# fixture force one refresh, at most doubling a spend currently running at
# 218 of 2,500 monthly objects.
SPORTSGAMEODDS_REFRESH_MIN = 720
SPORTSGAMEODDS_STALE_MAX_HOURS = 30
SPORTSGAMEODDS_WINDOW_HOURS = 36

DIAG = []
_ODDS_CACHE = {"t": 0.0, "data": {}}
# Tracks whether the Odds API refused this run because its monthly quota is
# spent (vs. a transient error), so the UI can honestly say markets are
# temporarily unavailable instead of silently showing none. Reset per build.
MARKET_STATE = {"quota_out": False}

def _is_quota_error(exc):
    s = str(exc).lower()
    return "out_of_usage" in s or "usage quota" in s or "quota has been reached" in s
_OUT_CACHE  = {"t": 0.0, "data": []}
_NEWS_CACHE = {"t": 0.0, "data": []}
# Was 60: a championship-futures market barely moves hour to hour, so an
# hourly refresh bought nothing but quota risk -- 6 competitions carry an
# outright market (WC, NFL, NCAAF, NCAAM, MLB, NBA) sharing one 500/month
# Odds API key with every h2h call across all 12 competitions, so an outright
# market refreshing every subprocess run (previously effectively every run,
# since its on-disk cache was never actually restored between CI runs -- see
# deploy.yml's "Restore fetch state" step) could alone burn a quarter of the
# entire monthly budget in a single active day.
OUTRIGHTS_CACHE_MIN = 360
NEWS_CACHE_MIN = 20
NEWS_MAX_AGE_DAYS = 7
NEWS_FUTURE_TOLERANCE_HOURS = 24
COLLEGE_CACHE_MIN = 480  # eight-hour cache keeps both college feeds within a shared free-key quota
# Roster talent/recruiting changes far more slowly than schedules.  Keep the
# last successful whole-field snapshot for a week so a transient provider
# error or quota response cannot silently turn every college "class" edge
# into zero on the next published build.
COLLEGE_CLASS_CACHE_MIN = 10080  # seven days; stale data is still a safe fallback on provider failure
# Season player-stats leaders pull the *whole* field in one request (no
# per-team looping -- see CollegeFootballDataAdapter.leaders() /
# CollegeBasketballDataAdapter.leaders()), so it's cheap in call count but
# expensive in bytes (CFBD's is tens of MB). Player totals move slowly
# within a season, so this rides a much longer cache than the schedule
# bundle rather than refetching on the bundle's 8-hour cadence.
COLLEGE_LEADERS_CACHE_MIN = 1440  # 24 hours
COLLEGE_ADVANCED_CACHE_MIN = 1440  # one league-wide CFBD shadow refresh per day
NFLVERSE_TEAM_CODE_MAP = {"WSH": "WAS", "LAR": "LA"}
NEWS_TERMS = {"NCAAF": "college football", "NCAAM": "men's college basketball"}
NEWS_RELEVANCE = {
    "NCAAF": "college_football ncaa cfp bowl heisman alabama georgia ohio_state michigan notre_dame oregon texas usc lsu clemson penn_state florida_state tennessee oklahoma auburn hurricanes",
    "NCAAM": "college_basketball ncaa march_madness final_four duke north_carolina kansas_jayhawks kentucky uconn gonzaga houston_cougars purdue villanova arizona_wildcats michigan_state",
}
NEWS_STRONG_RELEVANCE = {
    "NCAAF": "college_football ncaa cfp heisman alabama ohio_state notre_dame penn_state florida_state",
    "NCAAM": "college_basketball ncaa march_madness final_four duke north_carolina kansas_jayhawks kentucky uconn gonzaga houston_cougars purdue",
}
# Bare city names (kansas/houston/arizona/etc) collide with a pro team from a
# DIFFERENT sport in the same city -- confirmed live 2026-07-26: NCAAM's feed
# (which lists "kansas" for Kansas Jayhawks) accepted an MLB Royals/Tigers
# recap because "Kansas City Royals" contains the whole word "kansas". Any
# headline/desc naming one of these OTHER-sport teams is rejected outright,
# even if some relevance term also matched, since real coverage of the
# target sport never needs to mention a different sport's franchise by name.
NEWS_CROSS_SPORT_VETO = {
    "NCAAF": "royals chiefs astros texans rockets nba nhl mlb",
    "NCAAM": "royals chiefs astros texans rockets cardinals diamondbacks suns nfl mlb nhl",
}


def _news_relevant(item):
    """Reject obvious cross-sport leakage from broad publisher feeds."""
    text = _clean(f"{item.get('headline', '')} {item.get('desc', '')}").lower()
    veto = NEWS_CROSS_SPORT_VETO.get(COMP_KEY)
    if veto and any(re.search(rf"\b{re.escape(term.replace('_', ' '))}\b", text) for term in veto.split()):
        return False
    terms = NEWS_RELEVANCE.get(COMP_KEY)
    if not terms:
        return True
    raw_source = _clean(item.get("source") or item.get("feed") or "").lower()
    if re.search(r"\b(reuters|associated press|ap news|^ap$)\b", raw_source):
        terms = NEWS_STRONG_RELEVANCE.get(COMP_KEY, terms)
    return any(re.search(rf"\b{re.escape(term.replace('_', ' '))}\b", text) for term in terms.split())


def _google_news_feed(source, site, term):
    q = urllib.parse.quote_plus(f"site:{site} {term}")
    return source, f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _build_rss_feeds(key, comp, news_term):
    """The news feed set for one competition.

    Was inline module-level code, which meant it was built once for whatever
    competition was active at import and never rebuilt -- the one piece of
    competition-scoped state no caller reset when switching. set_competition()
    calls this now, so a switch takes the news feeds with it.
    """
    feeds = []
    # College competitions take ESPN's public college feeds and nothing else.
    # The soccer outlets and the cross-sport Google News searches below covered
    # sports this site no longer publishes, and their college coverage arrived
    # as general sports headlines rather than college ones.
    #
    # Only the headline and the link are stored (see _rss_items): no article
    # text, no images, no bulk redistribution. ESPN is credited by name on every
    # item. See the ESPN sourcing rule in PROVIDER_COMPLIANCE.md.
    # Three outlets per sport, so diverseNews() has something to round-robin
    # across. One feed would have made "Latest from multiple sources" a label
    # for a single source.
    if key == "NCAAF":
        feeds.extend([
            ("ESPN College Football", "https://www.espn.com/espn/rss/ncf/news"),
            ("CBS Sports", "https://www.cbssports.com/rss/headlines/college-football/"),
            ("Yahoo Sports", "https://sports.yahoo.com/college-football/rss.xml"),
        ])
        return feeds
    if key == "NCAAM":
        feeds.extend([
            ("ESPN College Basketball", "https://www.espn.com/espn/rss/ncb/news"),
            ("CBS Sports", "https://www.cbssports.com/rss/headlines/college-basketball/"),
            ("Yahoo Sports", "https://sports.yahoo.com/college-basketball/rss.xml"),
        ])
        return feeds

    for source, site in (
        ("Reuters", "reuters.com"), ("Associated Press", "apnews.com"),
    ):
        feeds.append(_google_news_feed(source, site, news_term))
    return feeds


# ---- apply the competition resolved at the top of the module ----------------
# Deferred to here rather than done beside the flag parsing because
# _competition_state() reads NEWS_TERMS and _build_rss_feeds() needs
# _google_news_feed, both defined above. Assigned name by name rather than
# through globals().update() so every constant stays statically visible at the
# ~50 places in this module that read one.
_STATE = _competition_state(normalize_competition(_COMP))
COMP_KEY = _STATE["COMP_KEY"]
COMP = _STATE["COMP"]
ODDS_URL = _STATE["ODDS_URL"]
OUTRIGHTS_URL = _STATE["OUTRIGHTS_URL"]
ODDS_CACHE_FILE = _STATE["ODDS_CACHE_FILE"]
OUTRIGHTS_CACHE_FILE = _STATE["OUTRIGHTS_CACHE_FILE"]
SPORTSDATAIO_PREGAME_CACHE_FILE = _STATE["SPORTSDATAIO_PREGAME_CACHE_FILE"]
PREGAME_CONTEXT_CACHE_FILE = _STATE["PREGAME_CONTEXT_CACHE_FILE"]
SPORTSGAMEODDS_CACHE_FILE = _STATE["SPORTSGAMEODDS_CACHE_FILE"]
OPEN_FILE = _STATE["OPEN_FILE"]
RATINGS_FILE = _STATE["RATINGS_FILE"]
PICKS_FILE = _STATE["PICKS_FILE"]
_news_term = _STATE["_news_term"]
RSS_FEEDS = _build_rss_feeds(COMP_KEY, COMP, _news_term)
KO_PLAYOFF_ROUND = "Knockout phase play-offs"
KO_STAGES = {"LAST_32": "Round of 32", "ROUND_OF_32": "Round of 32", "PLAYOFFS": KO_PLAYOFF_ROUND, "PLAY_OFF_ROUND": KO_PLAYOFF_ROUND, "LAST_16": "Round of 16",
             "QUARTER_FINALS": "Quarter-finals", "QUARTER_FINAL": "Quarter-finals",
             "SEMI_FINALS": "Semi-finals", "SEMI_FINAL": "Semi-finals",
             "THIRD_PLACE": "Third-place playoff", "FINAL": "Final"}
KO_ORDER = ["Round of 32", KO_PLAYOFF_ROUND, "Round of 16", "Quarter-finals", "Semi-finals", "Third-place playoff", "Final"]


def canonical_knockout_round(stage):
    """Normalize legacy cached labels to the provider/UI round contract."""
    value = str(stage or "").strip()
    if value.lower() in {"knockout playoffs", "knockout phase playoffs",
                         "knockout phase play-offs"}:
        return KO_PLAYOFF_ROUND
    return value


def _scrub(s):
    """Mask API keys anywhere they might surface (error bodies, URLs, diagnostics)."""
    s = str(s)
    s = re.sub(r"((?:apiKey|api_token)=)[^&\s]+", r"\1***", s, flags=re.I)
    s = re.sub(r"(X-Auth-Token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+", r"\1***", s)
    s = re.sub(r"(x-apisports-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+", r"\1***", s)
    for k in (ODDS_API_KEY, SPORTSDATAIO_KEY, SPORTSGAMEODDS_KEY, CFBD_KEY, CBBD_KEY):
        if k and len(str(k)) > 8:
            s = s.replace(str(k), "***")
    return s


def _refresh_odds_quota_free():
    """Refresh a stale Odds API ledger through its documented zero-cost endpoint."""
    req = urllib.request.Request(f"{ODDS_FREE_QUOTA_URL}{ODDS_API_KEY}", headers=UA)
    with urllib.request.urlopen(req, timeout=25) as response:
        response.read()
        provider_quota.record_response("odds_api", response.headers,
                                       url=ODDS_FREE_QUOTA_URL)
        last_cost = response.headers.get("x-requests-last")
        if last_cost not in (None, "0", 0):
            raise RuntimeError("Odds API quota receipt endpoint unexpectedly reported a nonzero cost")


def _get(url, headers=None, provider=None):
    """`provider`, when given, gates the call against provider_quota's ledger
    and records whatever quota header the response carried -- see
    provider_quota.py. Confirmed live 2026-07-31: football-data.org and The
    Odds API both expose their remaining budget on every response, and The
    Odds API was already sitting at zero for the current period."""
    if provider:
        try:
            provider_quota.check(provider)
        except provider_quota.QuotaExceededError as exc:
            # The provider documents /v4/sports as zero-credit.  Use it to
            # reconcile stale/cold quota state before suppressing paid calls.
            if provider == "odds_api" and provider_quota.claim_free_probe(provider):
                try:
                    _refresh_odds_quota_free()
                    provider_quota.check(provider)
                except Exception as refresh_exc:
                    provider_quota.record_block(provider)
                    raise RuntimeError(_scrub(str(refresh_exc)))
            else:
                provider_quota.record_block(provider)
                raise RuntimeError(_scrub(str(exc)))
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            if provider:
                provider_quota.record_response(provider, r.headers, url=url)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: body = e.read().decode("utf-8")[:300]
        except Exception: body = ""
        if provider:
            provider_quota.record_response(provider, e.headers, body, url=url)
        raise RuntimeError(_scrub(f"HTTP {e.code} — {body or e.reason}"))


def _get_text(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def _clean(s):
    # Feeds double-encode entities ("Ducks&amp;#39;"), so unescape until stable:
    # a headline read "Oregon Ducks&#39; national title odds".
    s = re.sub(r"<[^>]+>", "", s or "")
    for _ in range(3):
        unescaped = html.unescape(s)
        if unescaped == s:
            break
        s = unescaped
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def _rfc_iso(s):
    try:
        return parsedate_to_datetime(s).astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        return ""


def _canon(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()  # drop accents
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)          # hyphens/punctuation -> space
    toks = [t for t in s.split() if t not in ("and", "the", "of")]  # drop connectors
    return " ".join(toks)


def norm(name):
    if not name: return ""
    s = _canon(name)
    swaps = {"korea republic": "south korea", "ir iran": "iran", "usa": "united states",
             "united states america": "united states",
             "cote d ivoire": "ivory coast",
             "cape verde islands": "cape verde", "turkiye": "turkey",
             "china pr": "china", "czechia": "czech republic"}
    return swaps.get(s, s)


def pair(a, b): return frozenset({norm(a), norm(b)})


def _name_match(a, b):
    a, b = norm(a), norm(b)
    if a == b: return True
    if a in b or b in a: return True            # "cape verde" ⊂ "cape verde islands"
    ta, tb = set(a.split()), set(b.split())
    return bool(ta) and bool(tb) and (ta <= tb or tb <= ta)


def find_odds(odds, home, away):
    """Exact pair first, then a fuzzy fallback that tolerates name variants."""
    rec = odds.get(pair(home, away))
    if rec: return rec, "exact"
    for k, r in odds.items():
        names = list(k)
        if len(names) != 2: continue
        n1, n2 = names
        if (_name_match(home, n1) and _name_match(away, n2)) or \
           (_name_match(home, n2) and _name_match(away, n1)):
            return r, "fuzzy"
    return None, "none"


def _resolve_score(m):
    """Return (home_goals, away_goals, winner) using regulation/ET score for the
    displayed scoreline, but resolving the winner via penalties if it went to a
    shootout. football-data's fullTime includes shootout tallies for some feeds,
    so we prefer regularTime + extraTime and read penalties separately."""
    sc = m.get("score", {}) or {}
    ft = sc.get("fullTime", {}) or {}
    reg = sc.get("regularTime", {}) or {}
    et  = sc.get("extraTime", {}) or {}
    pens = sc.get("penalties", {}) or {}
    # football-data reports extraTime as goals scored *during* extra time, not
    # the cumulative 120-minute score.  Add it to regularTime.  This also avoids
    # fullTime variants that include shootout kicks in the apparent scoreline.
    if all(reg.get(side) is not None and et.get(side) is not None for side in ("home", "away")):
        hg, ag = reg.get("home") + et.get("home"), reg.get("away") + et.get("away")
    elif reg.get("home") is not None:
        hg, ag = reg.get("home"), reg.get("away")
    else:
        hg, ag = ft.get("home"), ft.get("away")
    # 90-minute (regulation) result — the 1X2 betting market settles on this
    r90h = reg.get("home") if reg.get("home") is not None else ft.get("home")
    r90a = reg.get("away") if reg.get("away") is not None else ft.get("away")
    winner = None
    if hg is not None and ag is not None:
        if hg > ag: winner = "h"
        elif ag > hg: winner = "a"
        else:
            # level after 90/120 — decide on penalties if present
            ph, pa = pens.get("home"), pens.get("away")
            if ph is not None and pa is not None:
                winner = "h" if ph > pa else "a" if pa > ph else "d"
            else:
                winner = "d"
    return hg, ag, winner, (pens.get("home"), pens.get("away")), (r90h, r90a)


_OPEN = None

def pairkey(a, b):
    return "|".join(sorted([norm(a), norm(b)]))

def _load_open():
    global _OPEN
    if _OPEN is None:
        for path in (OPEN_FILE,):
            try:
                with open(path, encoding="utf-8") as f:
                    _OPEN = json.load(f)
                break
            except Exception:
                continue
        if _OPEN is None:
            _OPEN = {}
    return _OPEN

def _save_open():
    try:
        tmp = OPEN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_OPEN, f)
        os.replace(tmp, OPEN_FILE)
    except Exception as e:
        DIAG.append(f"odds_open save failed: {e}")


def _load_odds_market_cache():
    """Restore the last parsed market snapshot across one-shot CI processes."""
    if _ODDS_CACHE["t"]:
        return
    try:
        with open(ODDS_CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached.get("data"), dict):
            _ODDS_CACHE["t"] = float(cached.get("t") or 0)
            _ODDS_CACHE["data"] = cached["data"]
    except Exception:
        pass


def _save_odds_market_cache():
    try:
        tmp = ODDS_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_ODDS_CACHE, f)
        os.replace(tmp, ODDS_CACHE_FILE)
    except Exception as e:
        DIAG.append(f"odds market cache save failed: {e}")


def _load_outrights_cache():
    """_OUT_CACHE was in-memory only, so OUTRIGHTS_CACHE_MIN never actually
    throttled anything -- this process is one-shot per CI run (see
    _load_odds_market_cache above), so _OUT_CACHE["t"] reset to 0 on every
    single invocation and the "cached" branch in fetch_outrights() could
    never be taken. Confirmed live: every due sport's subprocess was calling
    the outrights endpoint on every run regardless of OUTRIGHTS_CACHE_MIN,
    burning real monthly Odds API quota for a cache that looked like it was
    working. Mirrors the odds h2h cache's disk persistence exactly."""
    if _OUT_CACHE["t"]:
        return
    try:
        with open(OUTRIGHTS_CACHE_FILE, encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached.get("data"), list):
            _OUT_CACHE["t"] = float(cached.get("t") or 0)
            _OUT_CACHE["data"] = cached["data"]
    except Exception:
        pass


def _save_outrights_cache():
    try:
        tmp = OUTRIGHTS_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_OUT_CACHE, f)
        os.replace(tmp, OUTRIGHTS_CACHE_FILE)
    except Exception as e:
        DIAG.append(f"outrights market cache save failed: {e}")


def fetch_odds():
    # This process is short-lived in CI, so the quota-saving cache must live
    # on disk rather than only in memory.
    _load_odds_market_cache()
    now = time.time()
    if _ODDS_CACHE["t"] and now - _ODDS_CACHE["t"] < ODDS_CACHE_MIN * 60:
        DIAG.append("odds: served from cache")
        return _ODDS_CACHE["data"]
    out = {}
    try:
        events = _get(f"{ODDS_URL}&apiKey={ODDS_API_KEY}", provider="odds_api")
    except Exception as e:
        if _is_quota_error(e):
            MARKET_STATE["quota_out"] = True
            DIAG.append("odds: FAILED — monthly quota exhausted")
        else:
            DIAG.append(f"odds: FAILED — {e}")
        return _ODDS_CACHE["data"] or out
    open_d = _load_open(); dirty = False
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        hs = {"home": 0.0, "draw": 0.0, "away": 0.0}; hn = 0; tot = {}
        home_book = []   # each bookmaker's implied home-win % (for disagreement)
        for bk in ev.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt.get("key") == "h2h":
                    pr = {}
                    for o in mkt.get("outcomes", []):
                        nm = o.get("name")
                        if nm == home: pr["home"] = o.get("price")
                        elif nm == away: pr["away"] = o.get("price")
                        else: pr["draw"] = o.get("price")
                    if len(pr) == 3 and all(pr.values()):
                        raw = {k: 1.0/v for k, v in pr.items()}; s = sum(raw.values())
                        for k in hs: hs[k] += raw[k]/s
                        home_book.append(raw["home"]/s*100)
                        hn += 1
                    elif (len(pr) == 2 and pr.get("home") and pr.get("away")
                          and not COMP.get("has_draws", True)):
                        # two-way market (NFL/NBA etc.) — no draw outcome
                        raw = {k: 1.0/v for k, v in pr.items()}; s = sum(raw.values())
                        hs["home"] += raw["home"]/s; hs["away"] += raw["away"]/s
                        home_book.append(raw["home"]/s*100)
                        hn += 1
                elif mkt.get("key") == "totals":
                    ov = un = ln = None
                    for o in mkt.get("outcomes", []):
                        ln = o.get("point", ln)
                        if o.get("name", "").lower() == "over": ov = o.get("price")
                        if o.get("name", "").lower() == "under": un = o.get("price")
                    if ov and un and ln is not None:
                        tot.setdefault(ln, {"o": [], "u": []})
                        ro, ru = 1.0/ov, 1.0/un; s = ro+ru
                        tot[ln]["o"].append(ro/s); tot[ln]["u"].append(ru/s)
        rec = {}
        if hn:
            rec["1x2"] = {"home_pct": round(hs["home"]/hn*100), "draw_pct": round(hs["draw"]/hn*100),
                          "away_pct": round(hs["away"]/hn*100), "books": hn,
                          "source": "The Odds API consensus",
                          "source_reference": "https://the-odds-api.com/",
                          "observed_at": datetime.datetime.fromtimestamp(
                              now, datetime.timezone.utc).isoformat().replace("+00:00", "Z")}
            # bookmaker disagreement: spread of the home-win % across books
            if len(home_book) >= 2:
                spread = round(max(home_book) - min(home_book))
                rec["1x2"]["spread"] = spread
                rec["1x2"]["spread_lo"] = round(min(home_book))
                rec["1x2"]["spread_hi"] = round(max(home_book))
                rec["1x2"]["confidence"] = ("tight" if spread <= 8 else "mixed" if spread <= 18 else "split")
            # odds movement vs the first time we ever saw this match
            k = pairkey(home, away)
            cur = {"h": rec["1x2"]["home_pct"], "d": rec["1x2"]["draw_pct"], "a": rec["1x2"]["away_pct"]}
            ov = open_d.get(k)
            if not ov:
                ov = {**cur, "ts": now}; open_d[k] = ov; dirty = True
            # latest reading = de facto closing line once the match kicks off
            last = ov.get("last")
            if not last or any(last.get(s) != cur[s] for s in ("h", "d", "a")):
                ov["last"] = {**cur, "ts": now}; dirty = True
            rec["1x2"]["open"] = {"h": ov["h"], "d": ov["d"], "a": ov["a"]}
            rec["1x2"]["move"] = {"h": cur["h"]-ov["h"], "d": cur["d"]-ov["d"], "a": cur["a"]-ov["a"]}
        if tot:
            ln = sorted(tot, key=lambda L: len(tot[L]["o"]), reverse=True)[0]
            o, u = tot[ln]["o"], tot[ln]["u"]
            rec["totals"] = {"line": ln, "over_pct": round(sum(o)/len(o)*100), "under_pct": round(sum(u)/len(u)*100)}
        if rec: out[pair(home, away)] = rec
    if dirty: _save_open()
    _ODDS_CACHE["t"] = now; _ODDS_CACHE["data"] = out
    _save_odds_market_cache()
    return out


# ---- public-rating factors ---------------------------------------------
# Weights for the ratings-based factors (tune freely; 0 disables a factor).
# Scaled so long-term class roughly balances in-tournament results.
FACTOR_WEIGHTS = {"fifa": 0.6, "squad_value": 0.35, "star": 0.2}
_RATINGS = None

def _load_ratings():
    global _RATINGS
    if _RATINGS is None:
        _RATINGS = {}
        try:
            path = RATINGS_FILE
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for name, rec in raw.items():
                if isinstance(rec, dict):
                    _RATINGS[norm(name)] = rec
        except Exception as e:
            DIAG.append(f"ratings: not loaded ({e})")
    return _RATINGS


def _save_ratings():
    """Persist enriched ratings so a later provider outage cannot erase them.

    Talent/recruiting and championship-market enrichment used to live only in
    this process's ``_RATINGS`` dictionary.  The deploy workflow dutifully
    committed ``ratings_*.json``, but those files never changed, so the next
    rate-limited run started from the old empty file and published a zero
    roster edge.  Atomic persistence makes the tracked ratings file the durable
    last-good state the workflow already expects it to be.
    """
    ratings = _load_ratings()
    tmp = RATINGS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(ratings, handle, ensure_ascii=False, indent=1, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, RATINGS_FILE)
    except OSError as exc:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        DIAG.append(f"ratings persistence failed: {_scrub(exc)}")

# Club-name suffixes/prefixes that provider feeds add or drop inconsistently
# (football-data.org's official strings vs. the shorter names ratings files
# are hand-written with) -- "Arsenal FC" vs "Arsenal", "FC Barcelona" vs
# "Barcelona". norm() deliberately doesn't touch these (it's shared by
# h2h/Elo pairing, where changing it has wider blast radius), so ratings
# lookups get their own lenient fallback instead.
_CLUB_SUFFIX_TOKENS = {"fc", "cf", "afc", "cfc", "sc", "ac", "ssc", "sd", "ud", "cd", "rc", "sv", "bc", "sk"}

def _strip_club_suffix(key):
    toks = key.split()
    while toks and toks[-1] in _CLUB_SUFFIX_TOKENS: toks.pop()
    while toks and toks[0] in _CLUB_SUFFIX_TOKENS: toks.pop(0)
    return " ".join(toks)

# Identity mismatches that neither norm() nor the club-suffix strip can bridge
# -- a real rename the live provider has adopted while a curated ratings file
# still uses the old name (Utah's NHL club dropped "Hockey Club" for
# "Mammoth" ahead of the 2025-26 season), or two legitimately different
# strings for the same club (Serie A's official provider name vs. the
# common name curated files are hand-written with). Checked both directions
# so it doesn't matter which side (file vs. live feed) has which spelling.
_NAME_ALIASES = {
    "utah hockey club": "utah mammoth",
    "inter milan": "fc internazionale milano",
}
_NAME_ALIASES_REV = {v: k for k, v in _NAME_ALIASES.items()}

def _ratings_lookup(name):
    """Find a team's ratings entry, tolerating club-suffix mismatches between
    the live fixture name and however the ratings file happens to spell it,
    plus a short list of known identity mismatches (renames, alternate
    official names) that no amount of string-normalizing alone can bridge."""
    ratings = _load_ratings()
    key = norm(name or "")
    rec = ratings.get(key)
    if rec is not None:
        return rec
    stripped = _strip_club_suffix(key)
    if stripped != key and stripped:
        rec = ratings.get(stripped)
        if rec is not None:
            return rec
        for other_key, other_rec in ratings.items():
            if other_key.startswith("_"):
                continue
            if _strip_club_suffix(other_key) == stripped:
                return other_rec
    alias = _NAME_ALIASES.get(key) or _NAME_ALIASES_REV.get(key)
    if alias:
        rec = ratings.get(alias)
        if rec is not None:
            return rec
    return None


# Tokens that make a school a genuinely DIFFERENT program from its bare
# namesake, not mascot noise to strip -- "Alabama State" and "Alabama A&M"
# are real, separate schools from "Alabama", not "Alabama" plus a mascot.
# Confirmed live 2026-07-26: with no guard, a national talent-composite feed
# (which covers every D1 team, not just this week's schedule) fed "Alabama
# A&M" through this resolver; "alabama a m" itself wasn't in known_names
# (Alabama A&M wasn't playing this week), so the prefix loop kept shortening
# past "a"/"m" and landed on the real "Alabama"'s own key -- silently
# overwriting the real Crimson Tide's talent-share rating with Alabama A&M's
# much weaker one right before a Week 1 Alabama vs East Carolina prediction,
# flipping Alabama's class score negative against an unranked opponent. The
# same collision risks every "X" vs "X State"/"X Tech"/"X A&M"/"X Southern"
# pair nationally (Ohio/Ohio State, Texas/Texas A&M/Texas Tech,
# Washington/Washington State, etc.).
_SCHOOL_DISTINGUISHER_TOKENS = {"state", "tech", "southern", "western", "eastern",
                                 "northern", "central", "international", "poly", "a", "m"}


def _resolve_known_name(raw_name, known_names):
    """Map a provider's own spelling of a team ("Alabama Crimson Tide" from a
    sportsbook, "Ball State Cardinals" from a talent/recruiting feed) back to
    whatever bare name the schedule feed uses for that same team ("Alabama"),
    so strength data lands on the exact ratings key predict() will look up.

    College sportsbooks and talent feeds routinely tack the mascot onto the
    school name while CFBD/CBBD's schedule endpoint uses the school name
    alone -- a straight norm() match never lands, so squad/star values silently
    get written to a key nothing ever reads (see Build 0725B). `known_names`
    is the set of normalized team names actually in this run's schedule;
    matching the LONGEST known name that is a token-prefix of the provider's
    string avoids collisions like "Texas" swallowing "Texas A&M" (checked
    longest-first, so "texas a m" matches before the shorter "texas" gets a
    chance to) -- but only up to the point a dropped token would strip off a
    real distinguishing identity (see _SCHOOL_DISTINGUISHER_TOKENS above);
    past that point this stops shortening and keeps the provider's full name,
    even if that means no match (better an unwritten rating than a wrong one).
    """
    key = norm(raw_name or "")
    if not known_names or key in known_names:
        return key
    toks = key.split()
    for cut in range(len(toks), 0, -1):
        if any(tok in _SCHOOL_DISTINGUISHER_TOKENS for tok in toks[cut:]):
            break
        candidate = " ".join(toks[:cut])
        if candidate in known_names:
            return candidate
    return key

def rating_boost(name):
    """Convert public ratings (FIFA rank, squad value, star value) into
    strength points. Unknown teams get neutral mid-pack defaults."""
    r = _ratings_lookup(name) or {}
    fifa_n = max(0.0, 10.0 - (r.get("fifa_rank", 45) - 1) * 0.18)   # rank 1 → 10, rank ~56 → 0
    val_n  = min(10.0, r.get("squad_value_m", 120) / 150.0)         # €1.5B squad → 10
    star_n = min(10.0, r.get("star_value_m", 25) / 20.0)            # €200M player → 10
    w = FACTOR_WEIGHTS
    return fifa_n*w["fifa"] + val_n*w["squad_value"] + star_n*w["star"]


# ---- weather (Open-Meteo, keyless) --------------------------------------
# WC2026 venues by city keyword -> (lat, lon). Matched against venue strings.
VENUE_COORDS = {
    "new york": (40.813, -74.074), "new jersey": (40.813, -74.074), "metlife": (40.813, -74.074),
    "dallas": (32.747, -97.093), "arlington": (32.747, -97.093), "at&t": (32.747, -97.093),
    "los angeles": (33.953, -118.339), "sofi": (33.953, -118.339), "inglewood": (33.953, -118.339),
    "san francisco": (37.403, -121.970), "santa clara": (37.403, -121.970), "levi": (37.403, -121.970),
    "seattle": (47.595, -122.331), "lumen": (47.595, -122.331),
    "boston": (42.090, -71.264), "foxborough": (42.090, -71.264), "gillette": (42.090, -71.264),
    "philadelphia": (39.900, -75.167), "lincoln": (39.900, -75.167),
    "miami": (25.958, -80.238), "hard rock": (25.958, -80.238),
    "atlanta": (33.755, -84.401), "mercedes": (33.755, -84.401),
    "houston": (29.684, -95.410), "nrg": (29.684, -95.410),
    "kansas": (39.048, -94.484), "arrowhead": (39.048, -94.484),
    "toronto": (43.633, -79.418), "bmo": (43.633, -79.418),
    "vancouver": (49.276, -123.112), "bc place": (49.276, -123.112),
    "mexico": (19.303, -99.150), "azteca": (19.303, -99.150),
    "guadalajara": (20.681, -103.462), "akron": (20.681, -103.462), "zapopan": (20.681, -103.462),
    "monterrey": (25.669, -100.244), "bbva": (25.669, -100.244), "guadalupe": (25.669, -100.244),
    # MLB parks / shared pro-sport cities. Indoor venues are still retained as
    # provenance; the UI can distinguish a forecast from a verified roof state.
    "wrigley": (41.948, -87.656), "guaranteed rate": (41.830, -87.634),
    "yankee stadium": (40.829, -73.926), "citi field": (40.757, -73.846),
    "fenway": (42.346, -71.097), "camden yards": (39.284, -76.622),
    "nationals park": (38.873, -77.007), "citizens bank": (39.906, -75.166),
    "pnc park": (40.447, -80.006), "progressive field": (41.496, -81.685),
    "comerica": (42.339, -83.049), "target field": (44.981, -93.278),
    "kauffman": (39.051, -94.480), "busch stadium": (38.623, -90.193),
    "great american": (39.097, -84.507), "american family field": (43.028, -87.971),
    "truist park": (33.890, -84.468), "loandepot": (25.778, -80.220),
    "tropicana field": (27.768, -82.653), "globe life": (32.747, -97.084),
    "minute maid": (29.757, -95.355), "coors field": (39.756, -104.994),
    "chase field": (33.445, -112.067), "petco": (32.707, -117.157),
    "dodger stadium": (34.074, -118.240), "angel stadium": (33.800, -117.883),
    "oracle park": (37.778, -122.389), "oakland coliseum": (37.752, -122.201),
    "t-mobile park": (47.591, -122.333),
    # Common top-flight soccer grounds (existing city keys cover many more).
    "old trafford": (53.463, -2.291), "anfield": (53.431, -2.961),
    "emirates stadium": (51.555, -0.108), "stamford bridge": (51.481, -0.191),
    "etihad stadium": (53.483, -2.200), "tottenham hotspur": (51.604, -0.067),
    "camp nou": (41.381, 2.123), "bernabeu": (40.453, -3.688),
    "san siro": (45.478, 9.124), "allianz arena": (48.219, 11.625),
    "signal iduna": (51.493, 7.452), "parc des princes": (48.842, 2.253),
    # Recent renames. venue_coords() substring-matches, so the retired
    # sponsor name never fires once a provider ships the current one:
    # "Rate Field" does not contain "guaranteed rate", and "Daikin Park"
    # does not contain "minute maid". Both parks silently lost weather.
    "rate field": (41.830, -87.634), "daikin park": (29.757, -95.355),
    "rogers centre": (43.641, -79.389),
    # Athletics' Sacramento home while the Las Vegas park is built.
    "sutter health park": (38.580, -121.513),
    # NFL homes. Only the handful of shared WC2026 grounds were mapped, so
    # 134 of 224 upcoming fixtures resolved to no coordinates at all.
    "acrisure": (40.447, -80.016), "allegiant": (36.091, -115.184),
    "bank of america stadium": (35.226, -80.853),
    "caesars superdome": (29.951, -90.081),
    "empower field": (39.744, -105.020), "everbank": (30.324, -81.637),
    "ford field": (42.340, -83.046), "highmark": (42.774, -78.787),
    "huntington bank field": (41.506, -81.700),
    "lambeau": (44.501, -88.062), "lucas oil": (39.760, -86.164),
    "m&t bank": (39.278, -76.623), "nissan stadium": (36.166, -86.771),
    "northwest stadium": (38.908, -76.864), "paycor": (39.095, -84.516),
    "raymond james": (27.976, -82.503), "soldier field": (41.862, -87.617),
    "state farm stadium": (33.528, -112.263), "u.s. bank stadium": (44.974, -93.258),
    # International series venues. Accent-tolerant prefixes ("bernab",
    # "maracan") match whether or not the provider sends the diacritic.
    "estadio banorte": (19.303, -99.150), "wembley": (51.556, -0.280),
    "stade de france": (48.924, 2.360), "maracan": (-22.912, -43.230),
    "melbourne cricket": (-37.820, 144.983), "bernab": (40.453, -3.688),
    "fc bayern munich stadium": (48.219, 11.625),
}
_WX_CACHE = {}

_COLLEGE_VENUE_COORDS = None


def _college_venue_coords(venue):
    """Exact stadium coordinates from the licensed CFBD venue snapshot.

    Only consulted after VENUE_COORDS, which is hand-verified and already
    covers every pro ground. The provider's file is a *college* venue list and
    is not authoritative outside that: its "Wrigley Field" row sits 8.6km from
    the real park, so letting it override a curated entry would corrupt
    coordinates that were already right.
    """
    global _COLLEGE_VENUE_COORDS
    if _COLLEGE_VENUE_COORDS is None:
        try:
            _COLLEGE_VENUE_COORDS = refresh_ncaaf_venues.load()
        except Exception:
            _COLLEGE_VENUE_COORDS = ({}, {})
    by_name_city, by_name = _COLLEGE_VENUE_COORDS
    if not by_name and not by_name_city:
        return None
    # Exact match on the full name, qualifier included. Names that map to
    # more than one real site were dropped at build time.
    exact = by_name.get(refresh_ncaaf_venues.normalize(venue))
    if exact:
        return exact
    base = refresh_ncaaf_venues.strip_qualifier(venue)
    city = refresh_ncaaf_venues.qualifier_city(venue)
    if base and city:
        return by_name_city.get(f"{base}|{city}")
    return None


# Competitions whose grounds the CFBD venue file actually covers. It is a
# college list and is not authoritative elsewhere -- its "Wrigley Field" row
# is 8.6km from the real park -- so pro competitions never consult it.
COLLEGE_VENUE_COMPETITIONS = {"NCAAF", "NCAAM"}


def venue_coords(venue):
    # For college fixtures the exact provider match must win outright. The
    # curated table matches by substring, and "Memorial Stadium (Lincoln,
    # NE)" contains the "lincoln" keyword -- which is Lincoln Financial
    # Field, putting a Nebraska home game's forecast in Philadelphia.
    if COMP_KEY in COLLEGE_VENUE_COMPETITIONS:
        exact = _college_venue_coords(venue)
        if exact:
            return exact
    v = (venue or "").lower()
    for key, ll in VENUE_COORDS.items():
        if key in v: return ll
    return None

def fetch_weather(matches):
    """Attach forecast weather to upcoming matches within the forecast window."""
    hits = 0
    for m in matches:
        if m.get("status") != "UPCOMING": continue
        ll = venue_coords(m.get("venue"))
        if not ll or not m.get("kickoff"): continue
        try:
            ko = datetime.datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00"))
        except Exception:
            continue
        days_out = (ko - datetime.datetime.now(datetime.timezone.utc)).days
        if not (0 <= days_out <= 7): continue
        date = ko.strftime("%Y-%m-%d")
        ck = (ll, date)
        if ck not in _WX_CACHE:
            # Open-Meteo is keyless and free, so a transient TLS/network blip
            # costs nothing to retry -- but the single-shot version cached the
            # None and wrote off every fixture at that park for the whole run.
            # Confirmed live 2026-08-20: five handshake timeouts in one MLB
            # run, each silently dropping a venue-date.
            url = (f"https://api.open-meteo.com/v1/forecast?latitude={ll[0]}&longitude={ll[1]}"
                   f"&hourly=temperature_2m,wind_speed_10m,precipitation_probability"
                   f"&start_date={date}&end_date={date}&timezone=UTC")
            _WX_CACHE[ck] = None
            for attempt in range(3):
                try:
                    _WX_CACHE[ck] = _get(url)
                    break
                except Exception as e:
                    if attempt == 2:
                        # One line per failing venue-date, not one per fixture.
                        note = f"weather: FAILED after 3 attempts — {e}"
                        if note not in DIAG:
                            DIAG.append(note)
                    else:
                        time.sleep(1.5 * (attempt + 1))
        d = _WX_CACHE[ck]
        if not d: continue
        try:
            hours = d["hourly"]["time"]
            idx = min(range(len(hours)),
                      key=lambda i: abs(datetime.datetime.fromisoformat(hours[i]).replace(tzinfo=datetime.timezone.utc) - ko))
            m["weather"] = {"temp_c": round(d["hourly"]["temperature_2m"][idx]),
                            "wind_kph": round(d["hourly"]["wind_speed_10m"][idx]),
                            "rain_pct": d["hourly"]["precipitation_probability"][idx],
                            "source": "Open-Meteo", "source_url": "https://open-meteo.com/"}
            hits += 1
        except Exception:
            continue
    if hits: DIAG.append(f"weather: {hits} matches")


def compute_rest(matches, training_matches=None):
    """Days since each team's previous match, attached per fixture side.

    Looks up each team's last-played date from training_matches (the full
    season, when the caller has one) rather than `matches` itself -- a sport
    with a narrow display window (BallDontLie's ~1-week lookback) would
    otherwise silently lose the rest signal across a bye week or break,
    since the actual previous game simply isn't in `matches` to find.
    Falls back to `matches` when no wider list is available.
    """
    history = defaultdict(list)
    for m in (training_matches if training_matches else matches):
        if m.get("kickoff") and m.get("status") in ("FINISHED", "LIVE"):
            for side in ("home", "away"):
                k = norm(m[side].get("name"))
                if k:
                    history[k].append(m["kickoff"])
    for kickoffs in history.values():
        kickoffs.sort()
    for m in matches:
        kickoff = m.get("kickoff")
        if not kickoff:
            continue
        for side in ("home", "away"):
            t = m[side]; k = norm(t.get("name"))
            prior = [ko for ko in history.get(k, ()) if ko < kickoff]
            if not prior:
                continue
            try:
                d1 = datetime.datetime.fromisoformat(prior[-1].replace("Z", "+00:00"))
                d2 = datetime.datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
                t["rest_days"] = max(0, round((d2 - d1).total_seconds() / 86400))
            except Exception:
                pass


def mark_stale_offseason_records(standings, tables, history, fixtures, competition):
    """Keep an offseason NFL record as a model prior, never as current UI."""
    if str(competition or "").upper() != "NFL":
        return False
    history_times = [_parse_kickoff(row.get("kickoff")) for row in history or []
                     if row.get("status") == "FINISHED"]
    fixture_times = [_parse_kickoff(row.get("kickoff")) for row in fixtures or []
                     if row.get("status") == "UPCOMING"]
    history_times = [value for value in history_times if value]
    fixture_times = [value for value in fixture_times if value]
    if not history_times or not fixture_times:
        return False
    # A 90-day gap cannot occur inside an NFL season. This detects the year
    # boundary without trusting provider season labels that roll over on
    # different dates.
    if (min(fixture_times) - max(history_times)).total_seconds() < 90 * 86400:
        return False
    for record in (standings or {}).values():
        record["season_stale"] = True
    for table in tables or []:
        for team in table.get("teams") or []:
            team["season_stale"] = True
    return True


def competition_season_context(history, fixtures, competition, now=None,
                               projection_current=False, standings=None):
    """Describe whether standings/brackets belong to the active season.

    July 1 is the rollover for fall-to-spring and fall/winter competitions;
    MLB is calendar-year. Results remain available regardless of this flag --
    it only governs season-position views such as tables and brackets.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    key = str(competition or "").upper()
    if key == "MLB":
        cutoff = datetime.datetime(now.year, 1, 1, tzinfo=datetime.timezone.utc)
    else:
        start_year = now.year if now.month >= 7 else now.year - 1
        cutoff = datetime.datetime(start_year, 7, 1, tzinfo=datetime.timezone.utc)

    def _after_cutoff(match):
        kickoff = _parse_kickoff((match or {}).get("kickoff"))
        return kickoff is not None and kickoff >= cutoff

    current_results = any(
        str((match or {}).get("status") or "").upper() in {"FINISHED", "LIVE"}
        and _after_cutoff(match) for match in (history or []))
    current_fixtures = any(
        str((match or {}).get("status") or "").upper() in {"UPCOMING", "SCHEDULED", "TIMED", "LIVE"}
        and _after_cutoff(match) for match in (fixtures or []))

    rows = []
    if isinstance(standings, dict):
        rows = list(standings.values())
    else:
        for table in standings or []:
            rows.extend((table or {}).get("teams") or [])
    record_fields = ("pld", "w", "d", "l", "gf", "ga", "pts")
    all_zero_preseason = bool(rows) and current_fixtures and all(
        not float(row.get(field) or 0)
        for row in rows for field in record_fields
    )
    standings_current = bool(current_results or all_zero_preseason)
    if current_results:
        basis = "current_results"
    elif all_zero_preseason:
        basis = "current_preseason"
    elif rows:
        basis = "stale_or_unverified"
    else:
        basis = "unavailable"
    return {
        "competition": key,
        "season_start_year": cutoff.year,
        "cutoff": cutoff.date().isoformat(),
        "current_results": current_results,
        "current_fixtures": current_fixtures,
        "standings_rows": len(rows),
        "all_zero_preseason": all_zero_preseason,
        "standings_current": standings_current,
        "standings_basis": basis,
        "projection_current": bool(projection_current),
        "position_views_current": bool(standings_current or projection_current),
        "results_preserved": True,
    }


def filter_current_season_views(standings, bracket, bracketology, season_context,
                                bracket_projection_current=False):
    """Hide unverified prior-season position views without removing results."""
    context = dict(season_context or {})
    suppressed = []
    if not context.get("standings_current"):
        kept = [table for table in (standings or [])
                if (table or {}).get("projection_current")]
        if len(kept) != len(standings or []):
            suppressed.append("standings")
        standings = kept
        if bracketology:
            suppressed.append("bracketology")
            bracketology = None
    cutoff_text = str(context.get("cutoff") or "")
    cutoff = _parse_kickoff(cutoff_text + "T00:00:00Z" if cutoff_text else None)
    bracket_matches = []
    if isinstance(bracket, list):
        for round_row in bracket:
            bracket_matches.extend((round_row or {}).get("matches") or [])
    bracket_has_current_fixture = bool(cutoff and any(
        (_parse_kickoff(match.get("kickoff")) or datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc)) >= cutoff
        for match in bracket_matches
    ))
    bracket_current = bool(bracket_projection_current or bracket_has_current_fixture)
    if bracket and not bracket_current:
        suppressed.append("bracket")
        bracket = [] if isinstance(bracket, list) else None
    context["suppressed_views"] = suppressed
    context["bracket_projection_current"] = bool(bracket_projection_current)
    context["bracket_current"] = bracket_current
    context["standings_visible"] = bool(standings)
    context["bracket_visible"] = bool(bracket)
    context["bracketology_visible"] = bool(bracketology)
    context["derived_positions_current"] = bool(context.get("standings_current"))
    return standings, bracket, bracketology, context


def compute_split_form(matches):
    """Last-5 form, split by venue. Overall `form` mixes home and away
    results, which hides teams that are much stronger at home than on the
    road (or vice versa) -- this derives the split from the same match
    list every provider already fills in, so it needs no new data source."""
    hist = defaultdict(list)
    for m in sorted(matches, key=lambda x: x.get("kickoff") or ""):
        if m.get("status") != "FINISHED": continue
        win = (m.get("score") or {}).get("winner")
        if win not in ("h", "a", "d"): continue
        hn, an = norm(m["home"]["name"]), norm(m["away"]["name"])
        hist[hn].append(("H", "W" if win == "h" else "D" if win == "d" else "L"))
        hist[an].append(("A", "W" if win == "a" else "D" if win == "d" else "L"))
    out = {}
    for name, log in hist.items():
        home_res = [r for s, r in log if s == "H"][-5:]
        away_res = [r for s, r in log if s == "A"][-5:]
        out[name] = {"form_home": " ".join(home_res), "form_away": " ".join(away_res)}
    return out


def normalize_match_results(matches):
    """Backfill winners without discarding richer provider score metadata.

    Soccer feeds can carry three distinct facts: the displayed score after
    regulation/extra time, the 90-minute score used by a 1X2 market, and a
    penalty-shootout winner.  Cached US-sports payloads generally carry only
    ``home``/``away``.  Normalization must support both shapes without reducing
    the richer one to the lowest common denominator.
    """
    for match in matches or []:
        score = match.get("score") or {}
        clean = normalized_score(score.get("home"), score.get("away"),
                                 match.get("status") == "FINISHED")
        for key in ("reg", "pens"):
            value = score.get(key)
            if isinstance(value, dict):
                clean[key] = {"home": value.get("home"), "away": value.get("away")}
        existing_winner = score.get("winner")
        if match.get("status") == "FINISHED" and existing_winner in ("h", "d", "a"):
            clean["winner"] = existing_winner
        elif match.get("status") == "FINISHED" and clean.get("winner") == "d":
            pens = clean.get("pens") or {}
            ph, pa = pens.get("home"), pens.get("away")
            if ph is not None and pa is not None and ph != pa:
                clean["winner"] = "h" if ph > pa else "a"
        match["score"] = clean
    return matches


SRS_MARGIN_CAP = {"NCAAF": 35, "NCAAM": 30}


def compute_srs(matches):
    """Opponent-adjusted rating derived only from provider-supplied results.

    A capped scoring margin limits blowout leverage. Ratings are recentered on
    zero after every iteration and shrunk toward neutral for small samples.
    The calculation creates a model feature, not a redistributable raw feed.
    """
    games = []
    cap = SRS_MARGIN_CAP.get(COMP_KEY, 20)
    counts = defaultdict(int)
    for match in matches or []:
        if match.get("status") != "FINISHED":
            continue
        score = match.get("score") or {}
        home_score, away_score = score.get("home"), score.get("away")
        if home_score is None or away_score is None:
            continue
        home_name, away_name = norm(match["home"].get("name")), norm(match["away"].get("name"))
        if not home_name or not away_name:
            continue
        margin = _clamp(float(home_score) - float(away_score), -cap, cap)
        games.append((home_name, away_name, margin))
        counts[home_name] += 1
        counts[away_name] += 1
    if not games:
        return {}
    ratings = {name: 0.0 for name in counts}
    for _ in range(30):
        totals = defaultdict(float)
        seen = defaultdict(int)
        for home_name, away_name, margin in games:
            totals[home_name] += margin + ratings[away_name]
            totals[away_name] += -margin + ratings[home_name]
            seen[home_name] += 1
            seen[away_name] += 1
        updated = {name: totals[name] / max(1, seen[name]) for name in ratings}
        center = sum(updated.values()) / max(1, len(updated))
        ratings = {name: value - center for name, value in updated.items()}
    # Twelve games is enough for a useful signal in the shortest schedules;
    # longer seasons continue to stabilize naturally through more opponents.
    return {name: {"rating": round(value * min(1.0, counts[name] / 12.0), 3),
                   "games": counts[name]}
            for name, value in ratings.items()}


def rating_parts(name):
    """Class factors broken out, for attribution."""
    r = _ratings_lookup(name) or {}
    fifa_n = max(0.0, 10.0 - (r.get("fifa_rank", 45) - 1) * 0.18)
    val_n  = min(10.0, r.get("squad_value_m", 120) / 150.0)
    star_n = min(10.0, r.get("star_value_m", 25) / 20.0)
    w = FACTOR_WEIGHTS
    return {"fifa": fifa_n*w["fifa"], "value": val_n*w["squad_value"], "star": star_n*w["star"]}


CLASS_SIGNAL_CONFIG = {
    "NCAAF": {
        "label": "Roster talent edge",
        "source": "247Sports Team Talent Composite via CollegeFootballData",
        "source_key": "cfbd_team_talent",
        "note": "Multi-year current-roster talent composite; it measures roster quality, not program prestige.",
    },
    "NCAAM": {
        "label": "Recruiting edge",
        "source": "CollegeBasketballData team recruiting ratings",
        "source_key": "cbbd_recruiting",
        "note": "Recruiting quality is a preseason prior, not a complete current-roster or transfer-portal measure.",
    },
}


def _college_talent_points(record):
    """Return only a documented college talent/recruiting signal.

    Championship futures deliberately do not qualify.  Older tests and
    hand-built college rating files predate provenance fields, so non-zero
    squad/star values remain a college-only compatibility fallback; live
    enrichment always writes ``talent_strength`` and ``talent_source``.
    """
    if not record or COMP_KEY not in {"NCAAF", "NCAAM"}:
        return 0.0
    expected = CLASS_SIGNAL_CONFIG[COMP_KEY]["source_key"]
    source = record.get("talent_source")
    if source and source != expected:
        return 0.0
    if record.get("talent_strength") is not None:
        return max(0.0, float(record.get("talent_strength") or 0.0))
    if source is None and (record.get("squad_value_m") or record.get("star_value_m")):
        rp = rating_parts_from_record(record)
        return rp["value"] + rp["star"]
    return 0.0


def rating_parts_from_record(record):
    """Value/star attribution for an already-resolved ratings record."""
    record = record or {}
    val_n = min(10.0, float(record.get("squad_value_m") or 0.0) / 150.0)
    star_n = min(10.0, float(record.get("star_value_m") or 0.0) / 20.0)
    return {"value": val_n * FACTOR_WEIGHTS["squad_value"],
            "star": star_n * FACTOR_WEIGHTS["star"]}


def class_signal_meta(home_name, away_name, match=None):
    """Describe what the displayed class/personnel comparison really means."""
    if COMP.get("sport") == "soccer":
        label, source = "Squad edge", "Curated squad and star-player values"
        available = []
        for name in (home_name, away_name):
            rec = _ratings_lookup(name) or {}
            available.append(bool(rec and (rec.get("squad_value_m") or rec.get("star_value_m")
                                           or rec.get("fifa_rank"))))
        note = "Squad value, star quality, and ranking are a preseason prior; missing clubs are not assigned a fabricated edge."
    elif COMP_KEY == "NFL":
        cfg = CLASS_SIGNAL_CONFIG["NFL"]
        charts = ((match or {}).get("personnel") or {}).get("depth_chart") or {}
        available = [bool(((charts.get(side) or {}).get("players") or []))
                     for side in ("home", "away")]
        label, source, note = cfg["label"], cfg["source"], cfg["note"]
    else:
        cfg = CLASS_SIGNAL_CONFIG.get(COMP_KEY, {
            "label": "Personnel edge", "source": None,
            "note": "No verified sport-specific personnel source is configured.",
        })
        label, source, note = cfg["label"], cfg.get("source"), cfg["note"]
        available = [bool(_college_talent_points(_ratings_lookup(name)))
                     for name in (home_name, away_name)]
    coverage = "complete" if all(available) else "partial" if any(available) else "unavailable"
    cfg = CLASS_SIGNAL_CONFIG.get(COMP_KEY, {}) if COMP.get("sport") != "soccer" else {}
    return {"label": label, "source": source, "available": coverage == "complete",
            "coverage": coverage, "home_available": available[0],
            "away_available": available[1], "note": note,
            "edge_available": cfg.get("edge_available", True),
            "coverage_label": cfg.get("coverage_label")}


# ---- in-house Elo (self-training, sport-agnostic) -----------------------
# One shared store across every competition: club names never collide with
# national-team or US-sport names, and it's actually correct for club
# soccer, since a team's Champions League form should carry into its
# league Elo. Starts at a neutral 1500 for any unseen team and only
# updates from finished results, so it self-corrects over the season
# instead of relying on a preseason snapshot like FIFA rank/squad value do.
#
# BUT: that "never collide" claim is false for US college sports, where
# the same bare school name fields both a football and a basketball team
# (e.g. "Ohio State", "Kansas", "Duke", "Kent State" are all D1 in both).
# A plain norm(name) key would let NCAAF's update_elo() and NCAAM's
# update_elo() silently overwrite/blend into the exact same bucket --
# confirmed live 2026-07-25: a real NCAAM build had already populated
# "kent state" with pure-basketball results (r=1602, n=34); the next NCAAF
# build would have folded football results into that same key, corrupting
# both sports' signal. Keys are scoped by COMP["sport"] instead of
# COMP_KEY so the intentional cross-competition sharing within one sport
# (a club's Champions League form carrying into its league Elo -- every
# soccer competition shares sport="soccer") keeps working, while sports
# that happen to reuse the same bare name (football vs basketball) no
# longer collide. NFL/NCAAF both share sport="football" and NBA/NCAAM
# both share sport="basketball" too, but their naming conventions never
# actually overlap (franchise names like "Kansas City Chiefs" vs bare
# school names like "Kansas"), so that sharing is safe.
ELO_FILE = "ratings_elo.json"
ELO_K = 24
ELO_HOME_ADV = 60          # rating-point home edge, used only in the expected-score calc
ELO_FULL_TRUST_GAMES = 15  # games tracked before Elo counts at full weight
# Bumped when the on-disk key format changes. _elo_key() moved from a plain
# norm(name) key to a "<sport>:<name>" key (see the comment block above), so
# any file written before this version is in the OLD unscoped format --
# _migrate_legacy_elo_store() below decides what to do with it.
ELO_STORE_VERSION = 2
_ELO = None

def _migrate_legacy_elo_store():
    """One-time reset for a pre-sport-scoping ratings_elo.json.

    Confirmed live 2026-07-26: the real file has 867 teams, ALL under bare
    norm(name) keys with no sport prefix at all (e.g. "kent state", "ohio
    state", "iowa state" sitting alongside soccer countries and MLB/NBA
    franchises in the same flat "teams" dict) -- meaning every _elo_key()
    lookup from the now-scoped code below silently misses, and
    elo_strength() has been returning (0.0, 0.0) for literally every team in
    every sport since the scoping fix landed, not just the college-shared
    names it was written to fix.

    Recovery was considered and rejected. The stored record for a name is a
    single (r, n) pair -- Elo's rating and game count -- with no memory of
    which competition/sport wrote each contribution. For any name used by
    exactly one sport historically (a soccer country, an MLB/NBA/NFL/NHL
    franchise -- these never collide with any other competition's naming,
    see the ELO_FILE comment above) the number is technically clean and
    could in principle be carried forward unchanged under its sport's new
    key. But there is no reliable way to tell those apart from the
    genuinely-contaminated subset (any bare school name shared by an
    NCAAF and NCAAM program, e.g. "kent state") purely from what's stored --
    doing so would require an independent, authoritative "does this school
    field both a D-I football and D-I basketball program" cross-reference
    that this codebase doesn't have on hand, and getting even one entry
    wrong would silently reintroduce exactly the bug being fixed here. Elo
    is explicitly designed to be self-training and self-correcting ("starts
    at neutral 1500 for any unseen team... self-corrects over the season"
    -- see this section's own docstring), so the cost of a clean reset is
    bounded and temporary (ELO_FULL_TRUST_GAMES=15 games to reach full
    confidence again), unlike the alternative of quietly keeping numbers
    that might already be a blended football+basketball trajectory and
    presenting them as this season's single-sport rating.

    The old file is archived (not deleted) to `<ELO_FILE minus .json>
    .legacy.json` alongside the reset, purely so nothing is silently
    thrown away -- it is never read back by any code path."""
    global _ELO
    legacy = _ELO if isinstance(_ELO, dict) else {}
    if legacy.get("teams") or legacy.get("seen"):
        try:
            archive_path = ELO_FILE.rsplit(".json", 1)[0] + ".legacy.json"
            if not os.path.exists(archive_path):
                with open(archive_path, "w", encoding="utf-8") as f:
                    json.dump(legacy, f, ensure_ascii=False, indent=1)
            DIAG.append(f"elo: migrated legacy unscoped store ({len(legacy.get('teams', {}))} "
                        f"team(s)) -- archived to {archive_path}, ratings_elo.json reset to fresh "
                        f"sport-scoped tracking (see _migrate_legacy_elo_store docstring)")
        except Exception as e:
            DIAG.append(f"elo: legacy archive failed ({e}) -- resetting anyway")
    _ELO = {"_version": ELO_STORE_VERSION, "teams": {}, "seen": {}}
    _save_elo()

def _load_elo():
    global _ELO
    if _ELO is None:
        try:
            with open(ELO_FILE, encoding="utf-8") as f:
                _ELO = json.load(f)
        except Exception:
            _ELO = {}
        if _ELO.get("_version") != ELO_STORE_VERSION:
            _migrate_legacy_elo_store()
        _ELO.setdefault("teams", {})
        _ELO.setdefault("seen", {})
    return _ELO

def _save_elo():
    try:
        tmp = ELO_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_ELO, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ELO_FILE)
    except Exception as e:
        DIAG.append(f"elo: save failed ({e})")

def _elo_key(name):
    """Sport-scoped team key -- see the ELO_FILE comment above for why a
    bare norm(name) isn't safe once US college sports are in the mix."""
    return f"{COMP.get('sport', '')}:{norm(name or '')}"

def update_elo(matches):
    """Fold newly-finished results into each team's rating. Idempotent —
    tracks processed match ids so a re-fetch of an already-finished match
    (common with the hourly cron) never double-counts it."""
    store = _load_elo()
    teams, seen = store["teams"], store["seen"]
    updated = 0
    # Provider ordering is not guaranteed. Elo is path-dependent, so always
    # consume results chronologically to keep ratings reproducible.
    ordered = sorted(matches, key=lambda m: (m.get("kickoff") or "", str(m.get("id") or "")))
    for m in ordered:
        if m.get("status") != "FINISHED": continue
        win = (m.get("score") or {}).get("winner")
        if win not in ("h", "a", "d"): continue
        mid = str(m.get("id") or "")
        if not mid: continue
        seen_key = f"{COMP_KEY}:{mid}"
        # Honor legacy raw ids so an upgrade never double-trains old results.
        if seen_key in seen or mid in seen: continue
        # Never train on a placeholder side: it creates a permanent fake team
        # whose rating is then subtracted from the real opponent's, and marking
        # it seen would bake that in (see PLACEHOLDER_TEAM_NAMES).
        if any(is_placeholder_team_name((m.get(side) or {}).get("name"))
               for side in ("home", "away")): continue
        hn, an = _elo_key(m["home"]["name"]), _elo_key(m["away"]["name"])
        rh = teams.setdefault(hn, {"r": 1500.0, "n": 0})
        ra = teams.setdefault(an, {"r": 1500.0, "n": 0})
        exp_h = 1 / (1 + 10 ** ((ra["r"] - (rh["r"] + ELO_HOME_ADV)) / 400))
        actual_h = 1.0 if win == "h" else 0.0 if win == "a" else 0.5
        delta = ELO_K * (actual_h - exp_h)
        rh["r"] += delta; ra["r"] -= delta
        rh["n"] += 1; ra["n"] += 1
        seen[seen_key] = True
        updated += 1
    if updated:
        DIAG.append(f"elo: updated {updated} result(s), {len(teams)} teams tracked")
        _save_elo()

def elo_strength(name):
    """Strength points from Elo, plus a 0..1 confidence that ramps up with
    games tracked -- a brand-new team contributes nothing and the model
    leans on FIFA rank/squad value/market strength instead, exactly like
    it does today."""
    rec = _load_elo()["teams"].get(_elo_key(name))
    if not rec or rec.get("n", 0) < 1:
        return 0.0, 0.0
    conf = min(1.0, rec["n"] / ELO_FULL_TRUST_GAMES)
    pts = (rec["r"] - 1500.0) / 60.0
    return pts, conf


def elo_games(name):
    """How many finished results the Elo store has folded in for this team."""
    rec = _load_elo()["teams"].get(_elo_key(name))
    return int((rec or {}).get("n", 0) or 0)


# The curated preseason file is a snapshot taken before a ball was thrown. It
# should hand over to real results, not keep a permanent share of the number:
# ratings_mlb.json still carried a hardcoded preseason order that ranked
# Baltimore 5th, and the old formula floored the curated term's weight at 50%
# forever, so a 51-55 Baltimore published the 4th-highest power rating in the
# league while the standings table beside it showed them 22nd.
POWER_PRIOR_FADE_GAMES = 40
# ... and the rating had no current-season term at all. Elo is deliberately
# deep-history (backfill_history.py seeds ~12 MLB seasons) with no
# season-boundary regression, so on its own it reads as a multi-season
# franchise identity rather than "how good is this team right now".
POWER_SEASON_MAX_WEIGHT = 0.45
POWER_SEASON_FULL_TRUST_GAMES = 40
POWER_SEASON_FULL_TRUST_BY_COMP = {
    # A college-football regular season is only 12 games. Requiring the
    # cross-sport 40-game default meant current results could claim at most
    # 13.5% of the rating before bowl season, regardless of how much evidence
    # the team had actually produced.
    "NCAAF": 12,
    "NCAAM": 30,
}


def _season_form_points(record):
    """This season's own results, on the same 5.0-is-average scale as Elo.

    Win rate only: it is the one measure every sport in this codebase reports
    the same way, and the scoring-margin equivalent already reaches the rating
    through Elo. Returns None before a game has been played, so preseason
    behaviour is unchanged.
    """
    if not record:
        return None
    played = int(record.get("pld") or 0)
    if played < 1:
        return None
    wins = float(record.get("w") or 0)
    draws = float(record.get("d") or 0)
    win_pct = _clamp((wins + 0.5 * draws) / played, 0.0, 1.0)
    return 5.0 + (win_pct - 0.5) * 10.0


def power_rating(name, record=None):
    """Public-facing power rating for team profiles/standings/watchability.

    Three signals, weighted by how much each has actually earned:

      curated preseason prior -- FIFA rank/squad value/recruiting talent.
        Only covers a fraction of teams in leagues like NCAAF/NCAAM and is
        frozen at a preseason snapshot, so it carries the rating before any
        results exist and fades out over POWER_PRIOR_FADE_GAMES.
      self-training Elo -- the same signal predict() reads for its own 'elo'
        factor, and the only one available for teams the curated file has
        never heard of.
      this season's record -- passed in by the standings builders that
        already computed it, capped at POWER_SEASON_MAX_WEIGHT so a hot start
        can't erase everything known about a team.
    """
    known = bool(_ratings_lookup(name))
    base = rating_boost(name)
    elo_pts, elo_conf = elo_strength(name)
    season = _season_form_points(record)
    season_w = 0.0
    if season is not None:
        played = int((record or {}).get("pld") or 0)
        full_trust_games = POWER_SEASON_FULL_TRUST_BY_COMP.get(
            COMP_KEY, POWER_SEASON_FULL_TRUST_GAMES)
        season_w = (POWER_SEASON_MAX_WEIGHT
                    * min(1.0, played / float(full_trust_games)))
    if not known:
        if elo_conf <= 0:
            # Nothing but the generic default and possibly a record.
            return season if season is not None else base
        elo_only = 5.0 + elo_pts
        return elo_only * (1 - season_w) + season * season_w if season_w else elo_only
    # Whatever the season term doesn't claim is split between the preseason
    # prior and Elo, with the prior retiring as results accumulate.
    prior_share = max(0.0, 1.0 - elo_games(name) / float(POWER_PRIOR_FADE_GAMES))
    if elo_conf <= 0:
        prior_share = 1.0
    prior_w = (1 - season_w) * prior_share
    elo_w = 1 - season_w - prior_w
    return base * prior_w + (5.0 + elo_pts) * elo_w + (season or 0.0) * season_w


# ---- head-to-head history (self-training, sport-agnostic) ---------------
H2H_FILE = "ratings_h2h.json"
H2H_FULL_TRUST_MEETINGS = 6
# See ELO_STORE_VERSION above -- _pair_key() moved from an unscoped
# "a|b" key to a "<sport>|a|b" key, so a file written before this version is
# in the old unscoped format. Same migration story as Elo (see
# _migrate_legacy_h2h_store), for the same reason: two D-I schools sharing a
# bare name across NCAAF/NCAAM can collide under the old key exactly the way
# Kent State did for Elo.
H2H_STORE_VERSION = 2
_H2H = None

def _migrate_legacy_h2h_store():
    """One-time reset for a pre-sport-scoping ratings_h2h.json -- same
    reasoning as _migrate_legacy_elo_store: confirmed live 2026-07-26, the
    real file has 5644 pairs, ALL keyed as plain "a|b" with no sport prefix
    (e.g. "mexico|south africa" alongside whatever NCAAF/NCAAM pairs it may
    also hold), so every _pair_key() lookup from the now-scoped code below
    misses and h2h_strength() has been returning (0.0, 0.0) for every pair
    in every sport, not just the college-shared-name pairs the scoping fix
    targeted.

    A stored pair entry is a capped list of up to 10 past meetings -- unlike
    Elo's single scalar, this WOULD in principle carry enough detail
    (date + which side was home + winner) to sometimes infer sport from
    context, but there is still no stored field naming which competition
    recorded each meeting, and the same "kansas"/"duke"-shaped ambiguity
    applies: a school-name pair with meetings logged under the old key could
    be all-football, all-basketball, or (most riskily) an interleaved blend
    of both if both sports' update_h2h() ever wrote into the same bucket --
    exactly what the old unscoped key made possible. Reset for the same
    reason given for Elo: self-training and bounded to rebuild
    (H2H_FULL_TRUST_MEETINGS=6 meetings to reach full confidence), instead of
    presenting possibly-blended history as one sport's own head-to-head
    record. Archived, not deleted, to `<H2H_FILE minus .json>.legacy.json`."""
    global _H2H
    legacy = _H2H if isinstance(_H2H, dict) else {}
    if legacy.get("pairs") or legacy.get("seen"):
        try:
            archive_path = H2H_FILE.rsplit(".json", 1)[0] + ".legacy.json"
            if not os.path.exists(archive_path):
                with open(archive_path, "w", encoding="utf-8") as f:
                    json.dump(legacy, f, ensure_ascii=False, indent=1)
            DIAG.append(f"h2h: migrated legacy unscoped store ({len(legacy.get('pairs', {}))} "
                        f"pair(s)) -- archived to {archive_path}, ratings_h2h.json reset to fresh "
                        f"sport-scoped tracking (see _migrate_legacy_h2h_store docstring)")
        except Exception as e:
            DIAG.append(f"h2h: legacy archive failed ({e}) -- resetting anyway")
    _H2H = {"_version": H2H_STORE_VERSION, "pairs": {}, "seen": {}}
    _save_h2h()

def _load_h2h():
    global _H2H
    if _H2H is None:
        try:
            with open(H2H_FILE, encoding="utf-8") as f:
                _H2H = json.load(f)
        except Exception:
            _H2H = {}
        if _H2H.get("_version") != H2H_STORE_VERSION:
            _migrate_legacy_h2h_store()
        _H2H.setdefault("pairs", {})
        _H2H.setdefault("seen", {})
    return _H2H

def _save_h2h():
    try:
        tmp = H2H_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_H2H, f, ensure_ascii=False, indent=1)
        os.replace(tmp, H2H_FILE)
    except Exception as e:
        DIAG.append(f"h2h: save failed ({e})")

def _pair_key(a, b):
    # Scoped by sport for the same reason as _elo_key above: two D1 schools
    # (or a school + something else) can meet in more than one US college
    # sport under the identical bare name pair, and a soccer/UCL "same club,
    # different competition" meeting should still share history the way
    # H2H already intends for that case.
    return f"{COMP.get('sport', '')}|" + "|".join(sorted([a, b]))

def update_h2h(matches):
    """Record each finished result into a persistent per-pair meeting log,
    capped to the most recent 10. Starts empty for a fresh pair and
    accumulates for as long as the site stays live -- same self-training
    shape as Elo."""
    store = _load_h2h()
    pairs, seen = store["pairs"], store["seen"]
    updated = 0
    ordered = sorted(matches, key=lambda m: (m.get("kickoff") or "", str(m.get("id") or "")))
    for m in ordered:
        if m.get("status") != "FINISHED": continue
        win = (m.get("score") or {}).get("winner")
        if win not in ("h", "a", "d"): continue
        mid = str(m.get("id") or "")
        if not mid: continue
        seen_key = f"{COMP_KEY}:{mid}"
        if seen_key in seen or mid in seen: continue
        # Same placeholder guard as update_elo() -- a "unknown vs unknown"
        # pair is a meeting between two teams that don't exist.
        if any(is_placeholder_team_name((m.get(side) or {}).get("name"))
               for side in ("home", "away")): continue
        hn, an = norm(m["home"]["name"]), norm(m["away"]["name"])
        log = pairs.setdefault(_pair_key(hn, an), [])
        log.append({"date": m.get("kickoff") or "", "home": hn, "winner": win})
        log.sort(key=lambda r: r.get("date") or "")
        pairs[_pair_key(hn, an)] = log[-10:]
        seen[seen_key] = True
        updated += 1
    if updated:
        DIAG.append(f"h2h: recorded {updated} result(s), {len(pairs)} pairs tracked")
        _save_h2h()

def h2h_strength(home_name, away_name):
    """How much `home_name` has historically outperformed `away_name` in
    this exact matchup: a small capped nudge (comparable in size to the
    rest-days factor, not a dominant one -- H2H is a weak-to-moderate
    predictor at best and easily confounded with general team quality),
    plus a 0..1 confidence that ramps up with meetings recorded."""
    hn, an = norm(home_name or ""), norm(away_name or "")
    log = _load_h2h()["pairs"].get(_pair_key(hn, an)) or []
    if not log:
        return 0.0, 0.0
    score = 0.0
    for rec in log:
        w = rec.get("winner")
        if w == "d": continue
        rec_home_is_hn = (rec.get("home") == hn)
        hn_won = (w == "h") == rec_home_is_hn
        score += 1.0 if hn_won else -1.0
    conf = min(1.0, len(log) / H2H_FULL_TRUST_MEETINGS)
    pts = max(-1.0, min(1.0, score / len(log))) * 0.8
    return pts, conf


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        v = lo
    return max(lo, min(hi, v))


def _round_triplet(vals):
    """Round a pct triplet while keeping the total near 100."""
    raw = {k: max(0.0, float(vals.get(k, 0) or 0)) for k in ("h", "d", "a")}
    total = sum(raw.values()) or 1.0
    normed = {k: raw[k] / total * 100.0 for k in raw}
    rounded = {k: int(round(normed[k])) for k in raw}
    drift = 100 - sum(rounded.values())
    if drift:
        # Give the rounding remainder to the biggest decimal remainder.
        order = sorted(raw, key=lambda k: (normed[k] - int(normed[k])), reverse=(drift > 0))
        for k in order[:abs(drift)]:
            rounded[k] += 1 if drift > 0 else -1
    return rounded


def _temperature_scale_pct(probs, temp, two_way=False):
    temp = _clamp(temp, 1.0, 2.2)
    keys = ("h", "a") if two_way else ("h", "d", "a")
    powered = {}
    for k in keys:
        # Keep tiny non-zero mass so a side never mathematically disappears.
        p = max(0.002, float(probs.get(k, 0) or 0) / 100.0)
        powered[k] = p ** (1.0 / temp)
    total = sum(powered.values()) or 1.0
    out = {"h": 0, "d": 0, "a": 0}
    out.update({k: powered[k] / total * 100.0 for k in keys})
    return _round_triplet(out)


def _low_goal_probability(markets, draw_pct, m=None):
    totals = (markets or {}).get("totals") or {}
    if totals.get("under_pct") is not None:
        return _clamp(float(totals.get("under_pct") or 0) / 100.0, 0.20, 0.85)
    stage = ((m or {}).get("stage") or "").lower()
    # Same fix as _upset_adjustment's knockout check below: a domestic
    # league's "Regular Season" stage doesn't start with "group" either, so
    # the old check wrongly treated every league match as knockout-risky.
    knockout = _is_knockout_stage(stage)
    # No totals market available: use draw pressure + knockout caution as a proxy.
    return _clamp(0.42 + (float(draw_pct or 0) / 100.0) * 0.42 + (0.06 if knockout else 0.0), 0.35, 0.72)


def _side_name_for(home, away, side):
    return {"h": (home or {}).get("name") or "Home", "a": (away or {}).get("name") or "Away", "d": "Draw"}.get(side, "—")


def _scorecard_upset_bias():
    """Tiny self-training nudge from the local pick log.

    It only activates after there are enough graded high-upset-score matches.
    If previous high-upset candidates won more often than their stated adjusted
    probability, future upset candidates get a small probability bump. If not,
    the bump turns negative. This keeps the model learning without becoming random.
    """
    try:
        picks = _load_picks()
        graded = [p for p in picks.values() if _record_is_official(p)
                  and p.get("result") and p.get("upset_candidate")
                  and (p.get("upset_snapshot") or {}).get("radar")
                  and (p.get("upset_snapshot") or {}).get("standings_gap_pct") is not None
                  and p.get("upset_score") is not None]
        grp = [p for p in graded if float(p.get("upset_score") or 0) >= 60]
        if len(grp) < 8:
            return 0.0
        hit_rate = sum(1 for p in grp if p.get("upset_hit")) / len(grp)
        avg_prob = sum(float(p.get("upset_candidate_pct") or 0) / 100.0 for p in grp) / len(grp)
        return _clamp((hit_rate - avg_prob) * 0.25, -0.06, 0.08)
    except Exception:
        return 0.0


UNDERDOG_EDGE_THRESHOLDS = {"NCAAF": 8.0, "NCAAM": 8.0}


def _upset_adjustment(home, away, markets, m, why, blend, two_way=False,
                      model_probs=None):
    """Return adjusted probabilities plus an upset profile.

    Formula idea:
      T = 1 + 0.60(variance) + 0.25(draw_prob) + 0.20(low_goal_prob)
      P'_i = P_i^(1/T) / sum(P_j^(1/T))

    Then the underdog may become the official pick only when it is close enough
    after scaling and the upset score is genuinely high.
    """
    if two_way:
        draw_prob = 0.0
    else:
        draw_prob = _clamp(float(blend.get("d", 0) or 0) / 100.0, 0.0, 0.55)

    hp = float(blend.get("h", 0) or 0)
    ap = float(blend.get("a", 0) or 0)
    mk = (markets or {}).get("1x2") or {}
    market_available = mk.get("home_pct") is not None and mk.get("away_pct") is not None
    # An underdog is a market classification, not whichever side happens to
    # trail after the model and market have already been blended together.
    # Falling back to the blended ordering keeps watch-only volatility useful
    # when no market exists, but such a candidate can never trigger a pregame
    # official upset pick (market_gate remains closed below).
    if market_available:
        fav = "h" if float(mk.get("home_pct") or 0) >= float(mk.get("away_pct") or 0) else "a"
    else:
        fav = "h" if hp >= ap else "a"
    dog = "a" if fav == "h" else "h"
    fav_pct = max(hp, ap)
    dog_pct = min(hp, ap)
    margin = max(0.0, fav_pct - dog_pct) / 100.0
    low_goal = _low_goal_probability(markets, blend.get("d", 0), m)
    stage = ((m or {}).get("stage") or "").lower()
    # Regression: this used to treat ANY stage string not literally starting
    # with "group" as knockout -- correct for tournament group-vs-knockout
    # formats (WC/UCL), but every domestic league match's stage is something
    # like "Regular Season", which also doesn't start with "group", so this
    # silently flagged every single EPL/LaLiga/SerieA/Bundesliga/Ligue1 match
    # as knockout-risky. Reuse the real knockout-stage allowlist instead
    # (_is_knockout_stage's marker list: "round of", "quarter", "semi",
    # "final", etc.) -- unlike the single_elimination gate used elsewhere in
    # this file for bracket rendering, this only cares whether THIS stage is
    # a real do-or-die single match, which is true for UCL's knockout rounds
    # too even though UCL as a whole isn't flagged single_elimination.
    knockout = _is_knockout_stage(stage)

    # Variance rises when favorites are weak, teams are close, draw pressure is high,
    # totals point lower, or the fixture is knockout-style.
    fav_softness = _clamp((52.0 - fav_pct) / 22.0, 0.0, 1.0)
    closeness = _clamp((18.0 - (fav_pct - dog_pct)) / 18.0, 0.0, 1.0)
    variance = _clamp(
        0.30 * fav_softness +
        0.24 * closeness +
        0.22 * _clamp(draw_prob / 0.34, 0.0, 1.0) +
        0.16 * _clamp((low_goal - 0.48) / 0.24, 0.0, 1.0) +
        (0.08 if knockout else 0.0),
        0.0, 1.0
    )
    temp = 1.0 + 0.60 * variance + 0.25 * draw_prob + 0.20 * low_goal
    adjusted = _temperature_scale_pct(blend, temp, two_way=two_way)

    # Momentum is direction-aware: positive why values favor home, negative favor away.
    directional = float((why or {}).get("form", 0) or 0) + 0.55 * float((why or {}).get("gd", 0) or 0) + 0.25 * float((why or {}).get("pts", 0) or 0)
    dog_momentum = directional if dog == "h" else -directional
    dog_momentum = _clamp(dog_momentum / 8.0, 0.0, 0.18)
    fav_fragility = _clamp((48.0 - fav_pct) / 28.0, 0.0, 0.18)

    learn_bias = _scorecard_upset_bias()
    if learn_bias:
        # Move a small amount of probability between favorite and dog, preserving total.
        shift = round(learn_bias * 100)
        if shift:
            adjusted[dog] = int(_clamp(adjusted[dog] + shift, 1, 97))
            adjusted[fav] = int(_clamp(adjusted[fav] - shift, 1, 97))
            adjusted = _round_triplet(adjusted)

    fav_adj = float(adjusted.get(fav, 0) or 0) / 100.0
    dog_adj = float(adjusted.get(dog, 0) or 0) / 100.0
    adj_margin = max(0.0, fav_adj - dog_adj)

    raw_score = 100.0 * dog_adj * (1.0 - adj_margin) * (1.0 + draw_prob) * (1.0 + low_goal) * (1.0 + dog_momentum) * (1.0 + fav_fragility)
    upset_score = int(round(_clamp(raw_score, 0, 100)))
    market_gap_pct = None
    # Default closed, not open: odds are gated to near kickoff to save quota,
    # so "no market yet" is common. Without a no-vig market benchmark there
    # is no defensible way to classify a side as the market underdog or prove
    # that Matchday has an independent edge on it.
    market_gate = False
    market_quality_gate = False
    independent_edge = None
    independent_dog_pct = None
    independent_lead_pct = None
    edge_threshold = float(UNDERDOG_EDGE_THRESHOLDS.get(COMP_KEY, 8.0))
    box_score_edge = 0.0
    if market_available:
        dog_market = float(mk.get("home_pct") if dog == "h" else mk.get("away_pct") or 0)
        fav_market = float(mk.get("home_pct") if fav == "h" else mk.get("away_pct") or 0)
        market_gap_pct = abs(fav_market - dog_market)
        independent = model_probs or blend
        independent_dog_pct = float(independent.get(dog, 0) or 0)
        other_outcomes = ("h", "a") if two_way else ("h", "d", "a")
        independent_lead_pct = independent_dog_pct - max(
            float(independent.get(side, 0) or 0) for side in other_outcomes if side != dog
        )
        independent_edge = independent_dog_pct - dog_market
        books = mk.get("books")
        spread = mk.get("spread")
        enough_books = books is None or int(books or 0) >= 2
        coherent_market = spread is None or float(spread) <= 18.0
        has_actual_underdog = market_gap_pct >= 1.0
        market_quality_gate = bool(has_actual_underdog and enough_books and coherent_market)
        market_gate = bool(independent_edge >= edge_threshold and market_quality_gate)

    # Box-score pressure remains descriptive only. It must never turn live
    # match information into a record that is presented as a pregame pick.
    st = (m or {}).get("stats_extra") or (m or {}).get("stats") or {}
    try:
        hs, ads = st.get("home") or {}, st.get("away") or {}
        def _n(x):
            import re
            mt = re.search(r"-?\d+(?:\.\d+)?", str(x or ""))
            return float(mt.group(0)) if mt else 0.0
        home_pressure = _n(hs.get("shots_on_target"))*4 + _n(hs.get("shots"))*1.2 + _n(hs.get("corners"))*1.4 + _n(str(hs.get("possession", "")).replace("%", ""))*0.08 - _n(hs.get("red_cards"))*4
        away_pressure = _n(ads.get("shots_on_target"))*4 + _n(ads.get("shots"))*1.2 + _n(ads.get("corners"))*1.4 + _n(str(ads.get("possession", "")).replace("%", ""))*0.08 - _n(ads.get("red_cards"))*4
        total_pressure = max(1.0, abs(home_pressure) + abs(away_pressure))
        dog_pressure = home_pressure if dog == "h" else away_pressure
        fav_pressure = away_pressure if dog == "h" else home_pressure
        box_score_edge = max(0.0, (dog_pressure - fav_pressure) / total_pressure)
    except Exception:
        box_score_edge = 0.0

    independent_pick_gate = independent_lead_pct is not None and independent_lead_pct >= 1.0
    if two_way:
        playability_gate = dog_adj >= 0.44
    else:
        adjusted_leader = max(float(adjusted.get(side, 0) or 0) / 100.0 for side in ("h", "d", "a"))
        playability_gate = dog_adj >= 0.30 and dog_adj >= adjusted_leader - 0.05

    # Require at least two separately attributed production factors to point
    # toward the market underdog. Research-only advanced profiles remain at
    # zero weight and are deliberately not counted here.
    dog_direction = 1.0 if dog == "h" else -1.0
    supporting_signals = sorted(
        key for key, value in (why or {}).items()
        if key != "base" and dog_direction * float(value or 0) > 0.05
    )
    evidence_gate = len(supporting_signals) >= 2

    # Baseball and hockey outcomes hinge unusually strongly on the named
    # starter. Do not freeze an official upset pick from a candidate/proxy.
    # Preliminary forecasts can still surface the candidate as blocked.
    personnel_gate = True
    personnel_blockers = []
    personnel = (m or {}).get("personnel") or {}
    if COMP_KEY == "MLB" and not personnel.get("starting_pitchers_confirmed"):
        personnel_gate = False
        personnel_blockers.append("confirmed starting pitchers missing")
    elif COMP_KEY == "NHL" and not personnel.get("starting_goalies_confirmed"):
        personnel_gate = False
        personnel_blockers.append("confirmed starting goalies missing")

    candidate_profile = bool(independent_pick_gate and playability_gate and upset_score >= 60)
    base_trigger = bool(candidate_profile and market_gate and evidence_gate and personnel_gate)
    strong_box_override = (upset_score >= 75 and box_score_edge >= 0.35)
    # Live box-score dominance is retained as a descriptive signal, but never
    # turns post-kickoff information into an official pregame selection.
    trigger = base_trigger
    blocked = bool(candidate_profile and not trigger)

    reasons = []
    if independent_pick_gate: reasons.append("independent model ranks the market underdog first")
    if independent_edge is not None and independent_edge >= edge_threshold:
        reasons.append(f"model edge {independent_edge:.0f} pts")
    if draw_prob >= 0.24: reasons.append("draw pressure")
    if low_goal >= 0.55: reasons.append("low-scoring profile")
    if closeness >= 0.55: reasons.append("narrow team gap")
    if dog_momentum >= 0.07: reasons.append("underdog momentum")
    if learn_bias > 0.005: reasons.append("scorecard boost")
    if blocked and independent_edge is not None and independent_edge < edge_threshold:
        reasons.append(f"edge below {edge_threshold:.0f}-pt {COMP_KEY} gate")
    if blocked and not market_quality_gate: reasons.append("market quality gate closed")
    if blocked and not evidence_gate: reasons.append("fewer than two supporting model factors")
    if blocked and personnel_blockers: reasons.extend(personnel_blockers)
    if not reasons: reasons.append("favorite profile is cleaner")

    # ---- standings + market upset classification --------------------------
    # Radar is narrower than generic game volatility. It requires BOTH a
    # clearly weaker team in the current standings and a meaningful model
    # disagreement with the market on that same team.
    def _standings_strength(team):
        try:
            played = float(team.get("pld") or 0)
            if played < 5:
                return None
            if two_way:
                return _clamp(float(team.get("w") or 0) / played, 0.0, 1.0)
            # Soccer points per game, normalized to the same 0..1 scale.
            return _clamp(float(team.get("pts") or 0) / (3.0 * played), 0.0, 1.0)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    home_standing = _standings_strength(home)
    away_standing = _standings_strength(away)
    standings_candidate = None
    standings_gap_pct = None
    if home_standing is not None and away_standing is not None:
        standings_gap_pct = round(abs(home_standing - away_standing) * 100.0, 1)
        if standings_gap_pct >= 12:
            standings_candidate = "h" if home_standing < away_standing else "a"

    # The market must call that lower-standing team the underdog too.
    mkt_dog_pct = None
    market_dog = None
    if mk and mk.get("home_pct") is not None and mk.get("away_pct") is not None:
        m_side = "h" if float(mk.get("home_pct") or 0) >= float(mk.get("away_pct") or 0) else "a"
        m_dog = "a" if m_side == "h" else "h"
        market_dog = m_dog
        mkt_dog_pct = float(mk.get("home_pct") if m_dog == "h" else mk.get("away_pct") or 0)
    # class: pickem (>40) / live dog (25-40) / real dog (12-25) / heavy dog (<12)
    if mkt_dog_pct is None:
        upset_class = "unknown"
    elif mkt_dog_pct > 40:
        upset_class = "pickem"
    elif mkt_dog_pct >= 25:
        upset_class = "minor"      # a live underdog; win = minor upset
    elif mkt_dog_pct >= 12:
        upset_class = "solid"      # real underdog; win = solid upset
    else:
        upset_class = "major"      # heavy underdog; win = major upset
    # the model's edge on the underdog = does OUR number beat the market's?
    model_dog_pct = (float(adjusted.get(market_dog, 0) or 0)
                     if market_dog else float(adjusted.get(dog, 0) or 0))
    upset_edge = None if mkt_dog_pct is None else round(model_dog_pct - mkt_dog_pct, 1)
    # radar fires ONLY when it's a genuine underdog (not a pickem) AND the model
    # rates that underdog meaningfully above the market — a live, underpriced dog.
    radar = bool(
        standings_candidate is not None and
        market_dog == standings_candidate and
        dog == standings_candidate and
        upset_class in ("minor", "solid", "major") and
        (upset_edge or 0) >= 8
    )
    return adjusted, {
        "candidate": dog,
        "candidate_name": _side_name_for(home, away, dog),
        "favorite": fav,
        "favorite_name": _side_name_for(home, away, fav),
        "score": upset_score,
        "upset_class": upset_class,
        "market_dog_pct": None if mkt_dog_pct is None else round(mkt_dog_pct, 1),
        "model_dog_pct": round(model_dog_pct, 1),
        "upset_edge": upset_edge,
        "radar": radar,
        "standings_candidate": standings_candidate,
        "standings_gap_pct": standings_gap_pct,
        "standings_sample_ok": home_standing is not None and away_standing is not None,
        "temperature": round(temp, 2),
        "variance_pct": int(round(variance * 100)),
        "low_goal_pct": int(round(low_goal * 100)),
        "draw_pct": int(round(draw_prob * 100)),
        "favorite_pct": int(round(fav_adj * 100)),
        "candidate_pct": int(round(dog_adj * 100)),
        "margin_pct": int(round(adj_margin * 100)),
        "learn_bias_pct": round(learn_bias * 100, 1),
        "market_gap_pct": None if market_gap_pct is None else round(market_gap_pct, 1),
        "market_gate": bool(market_gate),
        "market_quality_gate": bool(market_quality_gate),
        "independent_model_dog_pct": (None if independent_dog_pct is None
                                      else round(independent_dog_pct, 1)),
        "independent_model_lead_pct": (None if independent_lead_pct is None
                                       else round(independent_lead_pct, 1)),
        "independent_edge": None if independent_edge is None else round(independent_edge, 1),
        "edge_threshold": edge_threshold,
        "independent_pick_gate": bool(independent_pick_gate),
        "playability_gate": bool(playability_gate),
        "evidence_gate": bool(evidence_gate),
        "supporting_signals": supporting_signals,
        "personnel_gate": bool(personnel_gate),
        "personnel_blockers": personnel_blockers,
        "box_score_edge": round(box_score_edge, 3),
        "strong_box_signal": bool(strong_box_override),
        "blocked": bool(blocked),
        "triggered": bool(trigger),
        "reason": " · ".join(reasons)
    }


FORM_RECENCY_WEIGHTS = [0.5, 0.65, 0.8, 0.9, 1.0]  # oldest -> most recent, within the last-5 window


def _two_way_advancement_probs(regulation_probs):
    """Condition a 1X2 forecast on one of the two teams advancing."""
    home = max(0.0, float((regulation_probs or {}).get("h") or 0))
    away = max(0.0, float((regulation_probs or {}).get("a") or 0))
    decisive = home + away
    if decisive <= 0:
        return {"h": 50, "a": 50}
    home_pct = int(round(home / decisive * 100))
    return {"h": home_pct, "a": 100 - home_pct}

def _weighted_form_score(form_str):
    """Recency-weighted W/D/L score: a result from 5 games ago counts less
    than one from last week. Scaled so a run of identical results matches
    the old flat sum exactly (5 wins -> 15, same as before), so this is a
    drop-in replacement rather than a re-tuning of the `form` weight."""
    games = (form_str or "").split()
    if not games: return 0.0
    weights = FORM_RECENCY_WEIGHTS[-len(games):]
    vals = [{"W": 3, "D": 1, "L": 0}.get(r, 0) for r in games]
    wsum = sum(weights) or 1.0
    return sum(v*w for v, w in zip(vals, weights)) / wsum * len(games)


def _market_blend_weight(market):
    """How much to trust the consensus, based on evidence already collected.

    A deep, tightly grouped market is a stronger prior than one or two books
    disagreeing sharply. Keep the range deliberately narrow until the locked
    scorecard has enough observations to learn these weights per sport.
    """
    if not market:
        return 0.0
    books = max(0, int(market.get("books") or 0))
    spread = market.get("spread")
    weight = 0.40 + min(books, 8) * 0.02
    if spread is not None:
        spread = float(spread)
        if spread <= 8:
            weight += 0.04
        elif spread > 18:
            weight -= 0.10
        elif spread > 12:
            weight -= 0.04
    return round(_clamp(weight, 0.30, 0.60), 2)


def predict(home, away, markets, m=None, neutral_venue=False):
    two_way = not COMP.get("has_draws", True)
    american_cfg = {
        "NCAAF": {"full": 10, "margin": 14.0, "home": 0.45, "rest": 7},
        "NCAAM": {"full": 18, "margin": 10.0, "home": 0.45, "rest": 2},
    }.get(COMP_KEY, {"full": 15, "margin": 10.0, "home": 0.35, "rest": 3})

    # When a season has barely started, record/margin/form/srs are all
    # near-zero by construction (reliability scales with games played, and
    # there's nothing to measure yet) -- so the persistent, sample-independent
    # priors (class/rank/elo) end up carrying the entire signal, but at their
    # normal fixed weight, which was tuned assuming record/margin/form are
    # also contributing. That flattened even a real on-paper blowout (a P4
    # power vs. a bottom-tier team) toward a near-coin-flip prediction in
    # preseason. Lean harder on the priors exactly when the sample-dependent
    # signals have the least to say, tapering back to 1x (no change at all)
    # once the season is established -- this is a no-op for every
    # already-passing established-season test/scenario.
    full = float(american_cfg["full"])
    home_pld = max(0, int(home.get("pld") or 0)) if home else 0
    away_pld = max(0, int(away.get("pld") or 0)) if away else 0
    avg_reliability = min(1.0, ((home_pld + away_pld) / 2.0) / full)
    prior_boost = 1.0 + (1.0 - avg_reliability) * 0.6

    def parts(s, adv):
        if not s: return {"base": 1.0, "adv": adv}
        form_str = (s.get("form_home") if adv else s.get("form_away")) or s.get("form", "")
        fp = _weighted_form_score(form_str)
        rest = s.get("rest_days")
        rating_record = _ratings_lookup(s.get("name")) or {}
        elo_pts, elo_conf = elo_strength(s.get("name"))
        # Unknown teams (no ratings-file entry) receive no invented class
        # prior: _college_talent_points() is zero without a record.
        if True:
            pld = max(0, int(s.get("pld") or 0))
            reliability = min(1.0, pld / float(american_cfg["full"]))
            if s.get("season_stale"):
                # provider had no current-season games yet and fell back to
                # last season's final record -- still a useful long-term prior
                # (good programs tend to stay good), but it's a year old and
                # shouldn't carry the same confidence as an in-progress sample
                reliability *= 0.25
            win_pct = s.get("win_pct")
            if win_pct is None and pld:
                win_pct = float(s.get("w") or 0) / pld
            win_pct = 0.5 if win_pct is None else _clamp(win_pct, 0.0, 1.0)
            gf, ga = s.get("gf"), s.get("ga")
            margin = ((float(gf) - float(ga)) / pld
                      if pld and gf is not None and ga is not None and (gf or ga) else 0.0)
            form_games = len((form_str or "").split())
            form_center = form_games * 1.5
            srs_games = int(s.get("srs_games") or 0)
            srs_conf = min(1.0, srs_games / 12.0)
            poll_rank = s.get("model_rank")
            poll_prior = (max(0.0, 26.0 - float(poll_rank)) / 25.0 * 2.0
                          if poll_rank else 0.0)
            talent_points = _college_talent_points(rating_record)
            market_points = max(0.0, float(rating_record.get("market_strength") or 0.0))
            # Futures and recruiting/talent are correlated, so the market
            # signal remains a small independent cross-check.
            market_scale = 0.35
            # Whatever confidence the current season hasn't earned is offered to
            # the recency-weighted multi-season history, when the provider layer
            # supplied one (college only today -- see
            # fetch_college_season_history). This is strictly additive: at
            # reliability 1.0 the depth term is multiplied by zero and the two
            # lines below are exactly what they were before, so no established
            # in-season prediction moves. What changes is preseason and the
            # opening weeks, where record/margin used to contribute nothing at
            # all and a 13-game sport had to lean entirely on talent and polls.
            depth_gap = max(0.0, 1.0 - reliability)
            multi_wp, multi_mg = s.get("multi_win_pct"), s.get("multi_margin")
            multi_conf = (min(1.0, int(s.get("multi_games") or 0) / (float(american_cfg["full"]) * 2.0))
                          if multi_wp is not None else 0.0)
            depth_w = depth_gap * multi_conf
            record_signal = (win_pct - 0.5) * reliability
            margin_signal = _clamp(margin / american_cfg["margin"], -1.5, 1.5) * reliability
            if depth_w > 0:
                record_signal += (float(multi_wp) - 0.5) * depth_w
                margin_signal += _clamp(float(multi_mg or 0.0) / american_cfg["margin"], -1.5, 1.5) * depth_w
            return {
                "base": 4.0,
                "record": record_signal * 8.0,
                "margin": margin_signal * 2.0,
                "form": (fp - form_center) * 0.22 * reliability if form_games else 0.0,
                "adv": american_cfg["home"] if adv else 0.0,
                "class": talent_points * prior_boost,
                "market_power": market_points * market_scale * prior_boost,
                "rank": poll_prior * prior_boost,
                "srs": _clamp(float(s.get("srs") or 0) / american_cfg["margin"], -1.5, 1.5) * 2.4 * srs_conf,
                "elo": elo_pts * elo_conf * prior_boost,
                "rest": (0.0 if rest is None else
                         _clamp((rest - american_cfg["rest"]) * 0.08, -0.35, 0.35)),
            }
    home_adv = 0.0 if neutral_venue else american_cfg["home"]
    ph, pa = parts(home, home_adv), parts(away, 0.0)
    # A flat "base" anchor identical on both sides mathematically caps how
    # far ANY signal, however lopsided, can push the sh/(sh+sa) ratio --
    # necessary in-season (StrengthFloorTests: a merely-bad-but-not-
    # historically-hopeless team shouldn't read as a mathematical
    # impossibility), but the same anchor also caps a genuine preseason
    # blowout at an unrealistically modest split, since class/rank/elo are
    # the ONLY signal preseason has and nothing else dilutes this anchor's
    # relative weight yet (confirmed against real 2025 CFBD talent shares:
    # even with _talent_share_curve's steeper falloff above, Florida
    # State's real share vs New Mexico State's tops out around a 67/33
    # read with "base" left untouched -- the anchor itself, not the curve,
    # is what's left capping it). Ease the anchor back specifically when
    # BOTH conditions hold: there's essentially no in-season sample yet
    # (prior_boost elevated -- a no-op once real games start, exactly like
    # prior_boost itself is) AND the class gap is unambiguous, not a close
    # call the recruiting/talent data can barely separate (real 2025 spot
    # check: Illinois-vs-UAB's class gap sits well below GAP_LO and
    # correctly stays untouched here, matching how modest their actual
    # recruiting-talent gap really is). Only "class" -- the one signal that
    # is actually non-zero and meaningful preseason -- feeds the gap; a
    # true in-season StrengthFloorTests-style gap is already diluted by
    # real record/margin/srs by the time it would reach GAP_LO, so this
    # essentially never engages once games have been played.
    if True:
        # Either a real talent prior or the separately attributed futures
        # prior may reveal a large preseason mismatch.  Keeping both in this
        # anchor calculation preserves the previous conservative-floor
        # behavior without calling market opinion "class."
        persistent_gap = abs((ph.get("class", 0.0) + ph.get("market_power", 0.0))
                             - (pa.get("class", 0.0) + pa.get("market_power", 0.0)))
        GAP_LO, GAP_HI = 3.0, 8.0  # calibrated against real 2025 CFBD/CBBD spot checks -- see tests
        extremity = _clamp((persistent_gap - GAP_LO) / (GAP_HI - GAP_LO), 0.0, 1.0)
        preseason_factor = _clamp((prior_boost - 1.0) / 0.6, 0.0, 1.0)
        shrink = extremity * preseason_factor * 0.85
        if shrink:
            ph["base"] *= (1 - shrink)
            pa["base"] *= (1 - shrink)
    # Floor guards against a non-positive strength score reaching the sh/(sh+sa)
    # ratio below -- but a flat 0.1 (tuned back when the American branch's
    # "base" anchor was 8.0, so crossing zero required a huge negative swing
    # and this floor was an all-but-unreachable safety net) turned into a real
    # bug once that base was reduced to 4.0 this session: a merely bad-but-
    # ordinary team (e.g. a real 5-12 NFL season) now routinely lands with a
    # slightly-negative raw sum and gets clamped to the exact same 0.1 as a
    # historically dreadful team, collapsing what should be an ~80/20 read
    # into a false-certainty 99/1 (confirmed against real cached NFL fixtures:
    # Jaguars(13-5) vs Browns(5-12) and Chargers(11-7) vs Cardinals(3-14) both
    # rounded to 99/1 under the new base with the old floor, vs. a sane ~80/20
    # hand-reconstructed at the old base -- see EloSportScopeTests' sibling,
    # StrengthFloorTests, for the regression coverage).
    strength_floor = 1.5
    sh, sa = max(strength_floor, sum(ph.values())), max(strength_floor, sum(pa.values()))
    # H2H is inherently pairwise (depends on both teams at once), so unlike
    # the other factors it can't be split into independent home/away parts
    # -- applied directly as a small capped nudge from the home side's
    # perspective, same asymmetric-adjustment pattern as injuries below.
    h2h_pts, h2h_conf = h2h_strength(home.get("name"), away.get("name"))
    h2h_adj = h2h_pts * h2h_conf
    sh += h2h_adj
    # Injury/availability nudge: reduce a team's strength when key players are
    # OUT. Deliberately small and capped — the market already prices injuries, and
    # we blend 50/50 with it, so this only needs to catch the rare case the odds
    # underrate. Only hard "out" statuses count (not questionable/day-to-day).
    inj_h = inj_a = 0.0
    if m:
        w = 1.5
        def _out_count(lst):
            n = 0
            for p in (lst or []):
                s = str(p).lower()
                if ("(out" in s or "(inactive" in s or "(injured reserve" in s or
                        "(suspension" in s or "(suspended" in s or
                        s.endswith("out)") or "(o)" in s):
                    n += 1
            return n
        injd = m.get("injuries") or {}
        oh, oa = _out_count(injd.get("home")), _out_count(injd.get("away"))
        # each key absence costs `w` strength pts, capped so it nudges not swings
        inj_h = min(oh, 3) * w
        inj_a = min(oa, 3) * w
        sh = max(strength_floor, sh - inj_h)
        sa = max(strength_floor, sa - inj_a)
    # factor attribution: how much each factor tilts home-vs-away (strength pts)
    keys = set(ph) | set(pa)
    why = {k: round(ph.get(k, 0) - pa.get(k, 0), 2) for k in keys if k != "base"}
    if inj_h or inj_a:
        # positive = injuries hurt away more (helps home), matching other factors' sign
        why["injuries"] = round(inj_a - inj_h, 2)
    if h2h_adj:
        why["h2h"] = round(h2h_adj, 2)
    # Anomaly: one-off knockouts and extreme conditions are less predictable.
    # Take the LARGER effect, never stack — the market's odds already price
    # much of this in, and we blend with them, so stacking over-corrects.
    damp = 0.0
    if m:
        if _is_knockout_stage((m.get("stage") or "").lower()): damp = 0.12
        wx = m.get("weather") or {}
        if wx.get("temp_c", 0) >= 32 or wx.get("wind_kph", 0) >= 30:
            damp = max(damp, 0.10)
    if damp:
        mean = (sh + sa) / 2
        sh, sa = sh + (mean - sh)*damp, sa + (mean - sa)*damp
    draw = 0.0
    tot = sh+sa
    model = {"h": round(sh/tot*(1-draw)*100), "a": round(sa/tot*(1-draw)*100), "d": round(draw*100)}
    # Calibrate the independent read BEFORE the market blend. The over-
    # confidence being corrected here belongs to the strength ratio, not to
    # the consensus price -- shrinking after the blend would damp the market's
    # information too, which is the one input with a track record.
    model = _calibrate_probs(model, _calibration_factor(COMP_KEY))
    mk = markets.get("1x2")
    market_weight = _market_blend_weight(mk)
    raw_blend = ({"h": round(model["h"]*(1-market_weight) + mk["home_pct"]*market_weight),
                  "d": round(model["d"]*(1-market_weight) + mk["draw_pct"]*market_weight),
                  "a": round(model["a"]*(1-market_weight) + mk["away_pct"]*market_weight)}
                 if mk else dict(model))
    raw_blend = _round_triplet(raw_blend)
    regulation_probs, upset = _upset_adjustment(
        home, away, markets, m, why, raw_blend, two_way=two_way,
        model_probs=model,
    )

    knockout = _is_advancement_fixture(m or {})
    regulation_outcomes = ("h", "a") if two_way else ("h", "d", "a")
    regulation_pick = max(regulation_outcomes, key=lambda k: regulation_probs[k])
    advancement = _two_way_advancement_probs(regulation_probs) if knockout else None
    if knockout:
        outcomes = ("h", "a")
        base_advancement = _two_way_advancement_probs(raw_blend)
        base_pick = max(outcomes, key=lambda k: base_advancement[k])
        candidate = upset.get("candidate")
        pick = candidate if upset.get("triggered") and candidate in outcomes else max(outcomes, key=lambda k: advancement[k])
        official_probs = {"h": advancement["h"], "d": 0, "a": advancement["a"]}
        confidence = advancement[pick]
    else:
        outcomes = regulation_outcomes
        base_pick = max(outcomes, key=lambda k: raw_blend[k])
        pick = upset["candidate"] if upset.get("triggered") else max(outcomes, key=lambda k: regulation_probs[k])
        official_probs = regulation_probs
        confidence = regulation_probs[pick]
    # The official selection and the side used for a regulation 1X2 comparison
    # are identical for ordinary fixtures, including an upset override.  An
    # advancement forecast instead needs its separately frozen regulation side.
    market_comparison_pick = regulation_pick if knockout else pick
    name = {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[pick]
    edge, note = None, "no market to compare against"
    if mk:
        mm = {"h": mk["home_pct"], "d": mk["draw_pct"], "a": mk["away_pct"]}
        edge = regulation_probs[market_comparison_pick] - mm[market_comparison_pick]
        note = ("advancement forecast; market comparison uses regulation 1X2" if knockout
                else "upset formula triggered — volatility makes the underdog playable" if upset.get("triggered")
                else "favorite, but upset watch" if upset.get("score", 0) >= 60 and pick != upset.get("candidate")
                else "model agrees with the market" if abs(edge) < 6
                else f"model rates this {'higher' if edge > 0 else 'lower'} than the market")
    elif knockout:
        note = "two-way advancement forecast; no regulation market to compare"
    elif upset.get("triggered"):
        note = "upset formula triggered — volatility makes the underdog playable"
    mkt_pull = (regulation_probs[market_comparison_pick] - model[market_comparison_pick]) if mk else 0
    # ---- predicted margin/spread ------------------------------------------
    # Matchday's own point/goal-margin estimate (not copied from a
    # sportsbook) -- derived from the official win/draw/loss probabilities
    # already computed above via the standard odds<->margin relationship
    # (margin = scale * log10(odds ratio)), not a new model. `scale` reuses
    # american_cfg["margin"], each sport's tuned typical single-game margin.
    # Works identically preseason, since it only needs the probabilities
    # predict() already produces at pld=0.
    h_frac = _clamp(official_probs["h"] / max(1e-6, official_probs["h"] + official_probs["a"]), 0.02, 0.98)
    margin_scale = float(american_cfg["margin"])
    margin_pts = round(margin_scale * math.log10(h_frac / (1 - h_frac)), 1)
    margin_unit = "points"
    if abs(margin_pts) < 0.05:
        margin_label = "Even matchup"
        margin_favored = None
    else:
        margin_favored = "h" if margin_pts > 0 else "a"
        fav_name = home.get("name") if margin_pts > 0 else away.get("name")
        margin_label = f"{fav_name} by {abs(margin_pts):.1f}"
    predicted_margin = {"value": margin_pts, "unit": margin_unit,
                         "favored": margin_favored, "label": margin_label}
    sample = {"home": int(home.get("pld") or 0), "away": int(away.get("pld") or 0)}
    min_sample = min(sample.values())
    any_stale = bool(home.get("season_stale") or away.get("season_stale"))
    quality_level = ("preseason" if min_sample == 0 or any_stale else "early"
                     if min_sample < american_cfg["full"] else "established")
    signals = [key for key in ("class", "market_power", "record", "margin", "form", "rank", "srs", "elo", "rest", "injuries")
               if abs(float(why.get(key) or 0)) > 0.001]
    if mk:
        signals.append("market")
    data_quality = {"level": quality_level, "games": sample,
                    "signals": signals, "market_available": bool(mk),
                    "market_books": int((mk or {}).get("books") or 0),
                    "market_spread": (mk or {}).get("spread"),
                    "market_weight": market_weight,
                    "note": ("Limited current-season evidence; probability is intentionally conservative."
                             if quality_level != "established" else
                             "Current-season sample and opponent-adjusted results are available.")}
    class_meta = class_signal_meta(home.get("name"), away.get("name"), m)
    return {"pick": pick, "pick_name": name, "confidence": confidence,
            "model_version": PREDICTION_MODEL_VERSION,
            "model_signal_schema": MODEL_SIGNAL_SCHEMA,
            "base_pick": base_pick, "base_pick_name": {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[base_pick],
            "model": model, "base_blend": raw_blend, "blend": official_probs, "adjusted": official_probs,
            "is_knockout": knockout, "advancement": advancement,
            "regulation_pick": regulation_pick,
            "market_comparison_pick": market_comparison_pick,
            "market_comparison_basis": "regulation_1x2",
            "regulation_pick_name": {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[regulation_pick],
            "regulation_confidence": regulation_probs[regulation_pick],
            "regulation_probs": regulation_probs,
            "edge": edge, "note": note, "why": why, "damp_pct": round(damp*100),
            "mkt_pull": mkt_pull, "market_weight": market_weight,
            "upset": upset, "data_quality": data_quality, "predicted_margin": predicted_margin,
            "class_meta": class_meta}


LEAGUE_AVG_TOTAL = {"NCAAF": 55.0, "NCAAM": 140.0}


def _preseason_expected_total(home, away):
    """Rating/talent-based total estimate for true preseason (pld==0 for
    either side, so there's no real gf/ga history yet to average). Real
    sportsbooks already post totals lines for Week 1 games with 0-0
    records (the 2026-07-25 blowout-confidence screenshots showed real
    o57.5/o55.5 NCAAF lines on exactly this kind of fixture) -- returning
    nothing here, which predict_totals() used to do unconditionally, is a
    worse answer than a rating-based estimate. Reuses power_rating() (the
    same curated-class + self-training-Elo blend predict() itself reads
    for its own "class"/"elo" factors) rather than inventing a new signal.

    A team with no curated rating AND no self-training Elo history at all
    contributes no real signal here either (rating_boost() still returns a
    numeric default in that case, but it's a generic placeholder, not a
    real read on this team -- see rating_parts()'s own known_rating gate
    in predict(), same reasoning), so it's treated as exactly neutral
    rather than dragging the estimate toward rating_boost()'s arbitrary
    default. power_rating()'s own Elo-blended neutral point (5.0, the
    center of "5.0 + elo_pts" at elo_pts==0) is reused as the neutral
    constant once a team DOES have real signal. Nudging the league-average
    baseline by how far this matchup's combined rating sits from that
    midpoint is deliberately modest and capped -- this is a heuristic
    total estimate, not a scoring-margin model."""
    baseline = 2.6 if COMP["sport"] == "soccer" else LEAGUE_AVG_TOTAL.get(COMP_KEY)
    if baseline is None:
        return None
    neutral = 5.0

    def _signal(side):
        name = (side or {}).get("name")
        if not name:
            return None
        elo_pts, elo_conf = elo_strength(name)
        if not _ratings_lookup(name) and elo_conf <= 0:
            return None  # no real signal at all -- stay neutral, don't
                          # let rating_boost()'s generic default drag it
        return power_rating(name)
    hr, ar = _signal(home), _signal(away)
    if hr is None and ar is None:
        return round(baseline, 2)
    combined_edge = _clamp(((hr if hr is not None else neutral) +
                            (ar if ar is not None else neutral)) / 2.0 - neutral, -4.0, 4.0)
    return round(baseline * (1 + combined_edge * 0.03), 2)


def predict_totals(home, away, markets):
    """Expected combined goals/points, shown independently alongside the
    market's over/under line (not blended into it) -- same "show our work,
    don't just parrot the market" spirit as the 1X2 model. A deliberately
    simple heuristic, matching predict()'s style, rather than a full
    Poisson/normal distribution model.

    Prefers each side's own scoring/conceding rate this season once real
    games have been played; falls back to _preseason_expected_total's
    rating-based estimate at pld==0 (see its docstring) instead of
    returning nothing, exactly like predict() itself now leans on
    class/rank/elo before any record/margin/form sample exists.
    """
    def rate(side, key):
        pld = side.get("pld") or 0
        val = side.get(key)
        # a literal 0 total over real games played means the data source
        # doesn't provide this stat (no team goes a whole season scoreless),
        # not that the team is genuinely averaging zero -- treat as missing
        if not pld or val is None or val == 0:
            return None
        return val / pld
    h_gf, h_ga = rate(home, "gf"), rate(home, "ga")
    a_gf, a_ga = rate(away, "gf"), rate(away, "ga")
    if None in (h_gf, h_ga, a_gf, a_ga):
        exp_total = _preseason_expected_total(home, away)
        if exp_total is None:
            return None  # unknown sport/competition and no real rates either
        basis = "preseason_rating"
    else:
        exp_total = round((h_gf + a_ga) / 2 + (a_gf + h_ga) / 2, 2)
        basis = "season_rate"
    result = {"expected": exp_total, "basis": basis}
    mk = markets.get("totals")
    if mk and mk.get("line") is not None:
        line = float(mk["line"])
        gap = exp_total - line
        # scale by the gap RELATIVE to the line, not an absolute goal/point
        # count, so this behaves consistently for soccer (~2.5 line) and
        # high-scoring sports (~220 line) alike
        rel_gap = (gap / line) if line else 0
        over_pct = max(15, min(85, round(50 + rel_gap * 150)))
        result.update({"line": line, "gap": round(gap, 2),
                        "pick": "over" if over_pct >= 50 else "under",
                        "over_pct": over_pct, "under_pct": 100 - over_pct,
                        "market_over_pct": mk.get("over_pct"), "market_under_pct": mk.get("under_pct")})
    return result


def compute_watchability(m):
    """0-100 'how big a game is this' score, built entirely from data the
    match already carries -- team class/power rating (are real names
    playing), how close the model's own probabilities are (competitive
    vs. a foregone conclusion), upset drama, and knockout/playoff stakes.
    No new data source; used to surface marquee matchups on the All
    Sports screen instead of every fixture from every sport at once."""
    pr = m.get("prediction") or {}
    adj = pr.get("adjusted") or pr.get("blend") or {}
    home_r = (m.get("home") or {}).get("rating")
    away_r = (m.get("away") or {}).get("rating")
    quality = min(100.0, (home_r + away_r) * 6) if home_r is not None and away_r is not None else 0.0
    vals = sorted((float(adj.get(k) or 0) for k in ("h", "d", "a") if k in adj), reverse=True)
    closeness = max(0.0, 100.0 - (vals[0] - vals[1]) * 2) if len(vals) >= 2 else 0.0
    upset_score = float((pr.get("upset") or {}).get("score") or 0)
    stage = (m.get("stage") or "").lower()
    stakes = 100.0 if stage and not stage.startswith("group") else 0.0
    score = quality * 0.4 + closeness * 0.35 + upset_score * 0.15 + stakes * 0.1
    return round(min(100.0, max(0.0, score)), 1)


_DURABLE_PREGAME_FIELDS = (
    "weather", "injuries", "lineups", "personnel", "pregame_provenance",
    "venue_context",
)


def _pregame_snapshot_signature(match):
    return {
        "home": norm((match.get("home") or {}).get("name")),
        "away": norm((match.get("away") or {}).get("name")),
        "kickoff": str(match.get("kickoff") or ""),
    }


def restore_pregame_snapshots(matches, path=None):
    """Restore last-known personnel/context before live overlays refresh it.

    Fixture providers rebuild match dictionaries from scratch. Without this
    layer, a transient empty response erased a previously observed lineup,
    injury report, starter, or weather forecast. The cache is normalized and
    fixture-bound; it never carries context across a team or kickoff change.
    """
    path = path or PREGAME_CONTEXT_CACHE_FILE
    try:
        with open(path, encoding="utf-8") as handle:
            cached = json.load(handle)
    except Exception:
        return 0
    rows = cached.get("fixtures") if isinstance(cached, dict) else None
    if not isinstance(rows, dict):
        return 0
    restored = 0
    for match in matches:
        row = rows.get(str(match.get("id")))
        if not isinstance(row, dict) or row.get("signature") != _pregame_snapshot_signature(match):
            continue
        fields = row.get("fields") or {}
        touched = False
        for key in _DURABLE_PREGAME_FIELDS:
            value = fields.get(key)
            if value not in (None, {}, []):
                match[key] = value
                touched = True
        if touched:
            match["pregame_snapshot"] = {
                "first_observed_at": row.get("first_observed_at"),
                "last_changed_at": row.get("last_changed_at"),
                "restored": True,
            }
            restored += 1
    return restored


def save_pregame_snapshots(matches, path=None, now=None):
    """Persist material pregame observations and retain their first receipt."""
    path = path or PREGAME_CONTEXT_CACHE_FILE
    stamp = now or datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        with open(path, encoding="utf-8") as handle:
            previous = json.load(handle).get("fixtures") or {}
    except Exception:
        previous = {}
    fixtures = {}
    for match in matches:
        if match.get("status") not in {"UPCOMING", "LIVE"}:
            continue
        key = str(match.get("id"))
        fields = {name: _json_safe(match.get(name)) for name in _DURABLE_PREGAME_FIELDS
                  if match.get(name) not in (None, {}, [])}
        old = previous.get(key) if isinstance(previous.get(key), dict) else {}
        changed = old.get("fields") != fields or old.get("signature") != _pregame_snapshot_signature(match)
        fixtures[key] = {
            "signature": _pregame_snapshot_signature(match),
            "fields": fields,
            "first_observed_at": old.get("first_observed_at") or stamp,
            "last_changed_at": stamp if changed else old.get("last_changed_at") or stamp,
        }
        match["pregame_snapshot"] = {
            "first_observed_at": fixtures[key]["first_observed_at"],
            "last_changed_at": fixtures[key]["last_changed_at"],
            "restored": bool(match.get("pregame_snapshot", {}).get("restored")),
        }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"schema_ver": 1, "updated": stamp, "fixtures": fixtures}, handle,
                  ensure_ascii=False)
    os.replace(tmp, path)
    return len(fixtures)


def _num_from_stat(v):
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return v
    mt = re.search(r"-?\d+(?:\.\d+)?", str(v))
    if not mt:
        return 0
    n = float(mt.group(0))
    return int(n) if n.is_integer() else n


def _stat_lookup(stats, *names):
    # API-FOOTBALL labels can vary slightly, so match normalized type names.
    by_norm = {_canon(k): v for k, v in (stats or {}).items()}
    for nm in names:
        key = _canon(nm)
        if key in by_norm:
            return by_norm[key]
    return None


def _parse_af_stats(payload, m, fixture_id):
    rows = payload.get("response") or []
    if len(rows) < 2:
        return None
    out = {"home": {}, "away": {}, "source": "API-FOOTBALL", "fixture_id": fixture_id}
    got = 0
    for row in rows:
        tname = ((row.get("team") or {}).get("name")) or ""
        side = "home" if _name_match(tname, m["home"]["name"]) else ("away" if _name_match(tname, m["away"]["name"]) else "")
        if not side:
            continue
        raw = {x.get("type"): x.get("value") for x in (row.get("statistics") or []) if x.get("type")}
        s = out[side]
        s["shots"] = _num_from_stat(_stat_lookup(raw, "Total Shots", "Shots Total"))
        s["shots_on_target"] = _num_from_stat(_stat_lookup(raw, "Shots on Goal", "Shots on Target"))
        s["possession"] = _num_from_stat(_stat_lookup(raw, "Ball Possession", "Possession"))
        s["corners"] = _num_from_stat(_stat_lookup(raw, "Corner Kicks", "Corners"))
        s["fouls"] = _num_from_stat(_stat_lookup(raw, "Fouls"))
        s["offsides"] = _num_from_stat(_stat_lookup(raw, "Offsides"))
        s["saves"] = _num_from_stat(_stat_lookup(raw, "Goalkeeper Saves", "Saves"))
        s["yellow_cards"] = _num_from_stat(_stat_lookup(raw, "Yellow Cards"))
        s["red_cards"] = _num_from_stat(_stat_lookup(raw, "Red Cards"))
        got += 1
    if got < 2:
        return None
    return out


def _parse_af_injuries(payload, m, fixture_id):
    """API-FOOTBALL /injuries -> {home:[...], away:[...]} strings shaped like
    every other adapter's m['injuries'] (see SportsDataIOAdapter.attach_availability
    in provider_adapters.py: "Name (Status)"), so predict()'s injury nudge
    reads it the same way regardless of source.

    API-FOOTBALL's own `player.type` is authoritative on availability:
    "Missing Fixture" is a confirmed absence (this also covers suspensions --
    a suspended player is just as certainly missing the fixture as an injured
    one). Anything else ("Questionable" is the common case) is a doubt, not
    a confirmed one. predict()'s _out_count() only credits a literal "(out"
    substring (deliberately excluding day-to-day doubts), so only the
    confirmed kind gets tagged "Out" here -- a doubtful player is tagged with
    its own type instead and correctly falls through uncounted.
    """
    rows = payload.get("response") or []
    out = {"home": [], "away": [], "source": "API-FOOTBALL", "fixture_id": fixture_id}
    # Confirmed live on 2026-07-25 (fixture 1494712): API-FOOTBALL's own
    # /injuries response repeats every row verbatim (14 rows for 7 distinct
    # players, identical player id and fixture id each time) -- a
    # provider-side duplication, not a fluke of one fixture. Dedupe by
    # player id (falling back to name when a row is missing one) so the same
    # absence doesn't get double-counted by predict()'s _out_count(), which
    # would otherwise silently double the injury-nudge weight per player.
    seen = set()
    for row in rows:
        tname = ((row.get("team") or {}).get("name")) or ""
        side = "home" if _name_match(tname, m["home"]["name"]) else ("away" if _name_match(tname, m["away"]["name"]) else "")
        if not side:
            continue
        player = row.get("player") or {}
        name = player.get("name") or ""
        if not name:
            continue
        dedupe_key = (side, player.get("id") or name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ptype = str(player.get("type") or "").strip()
        reason = str(player.get("reason") or "").strip()
        confirmed = ptype.lower() == "missing fixture"
        label = "Out" if confirmed else (ptype or "Questionable")
        tag = f"{label} - {reason}" if reason else label
        out[side].append(f"{name} ({tag})")
    return out


def _talent_share_curve(share):
    """Map a team's talent/market share of the national max (0..1) to a
    0..1 scaling factor for squad_value_m/star_value_m -- shared by
    apply_recruiting_strength() and apply_market_strength() (both
    American-sports-only; soccer's ratings come from a real curated file,
    not this transform).

    A flat share**0.7 (concave) protects a genuinely competitive team from
    being crushed just for sitting below the national ceiling -- necessary
    so a good G5 program playing a middling P4 team doesn't get treated as
    hopeless (the MSU-vs-Toledo history, Build 0725B). But the same curve
    also over-protects a genuine bottom-of-FBS/bottom-of-D1 team: real 2025
    CFBD data puts San Jose State's share of the national max at ~0.52 and
    UMass at ~0.49, yet real 2026 Week 1 sportsbook lines price USC and
    Rutgers as ~99% favorites against them -- 0.7 is too gentle at the true
    low end. Below COMPETITIVE_FLOOR the curve steepens sharply instead, so
    that tier pulls apart from the blue-bloods instead of blurring toward
    them. COMPETITIVE_FLOOR (0.58) was picked from the real data's own gap:
    every 2025 "good G5/mid-major" spot check (Boise State 0.61, Toledo
    0.62, Marshall 0.59, Memphis 0.67) sits at or above it, while every
    real "true bottom-tier" 2026 Week 1 opponent in the reported blowouts
    (San Jose State 0.52, UAB 0.54, Massachusetts 0.49, New Mexico State
    0.40) sits below it -- so a team at or above the floor is completely
    unaffected (identical output to the old flat curve; the ceiling test
    at share==1.0 is unchanged), and only a team the real data itself
    calls "true bottom-tier" gets the steeper falloff."""
    share = _clamp(share, 0.0, 1.0)
    floor = 0.58
    if share >= floor:
        return share ** 0.7
    return (floor ** 0.7) * ((share / floor) ** 4.5 if floor else 0.0)


def apply_recruiting_strength(team_scores, known_names=None):
    """Derive team strength from CFBD/CBBD's own recruiting-talent data --
    same account/key already licensed for schedules and standings, no new
    provider. Covers the whole D1 field, not just the handful of teams with
    championship futures odds, which is why this runs before (and gets
    partially overwritten by) apply_market_strength for whichever teams do
    have live market data.

    `known_names` (the schedule's own normalized team names, when available)
    resolves any "School Mascot"-style name a provider hands back to the bare
    school name the schedule/predict() actually key off of -- see
    _resolve_known_name."""
    if not team_scores:
        DIAG.append("recruiting/talent strength: provider returned 0 teams (check plan/endpoint access)")
        return
    mx = max(team_scores.values(), default=0) or 1
    ratings = _load_ratings()
    changed = 0
    for name, score in team_scores.items():
        key = _resolve_known_name(name, known_names)
        share = max(0.0, score) / mx
        # scaled to the actual saturation points rating_boost()/rating_parts()
        # use (squad_value_m 1500 -> 10, star_value_m 200 -> 10) so the nation's
        # best-talent team reaches the true ceiling instead of undershooting it
        # -- undershooting flattened the gap between a middling P4 team and a
        # good G5 team almost to nothing. See _talent_share_curve for why a
        # single flat exponent stops there instead of also fixing a true
        # bottom-tier team's own separate problem (overprotection).
        curved = _talent_share_curve(share)
        val_m = round(curved * 1500)
        star_m = round(curved * 200)
        rec = _ratings_lookup(key)
        if rec is None:
            rec = {"fifa_rank": 45, "squad_value_m": 0, "star_value_m": 0}
            ratings[key] = rec
        rec["squad_value_m"] = val_m
        rec["star_value_m"] = star_m
        # Source-tagged strength keeps real talent/recruiting distinct from
        # championship-futures market opinion, even if market enrichment
        # refreshes the legacy generic value fields later in this build.
        rec["talent_strength"] = round(
            (val_m / 150.0) * FACTOR_WEIGHTS["squad_value"]
            + (star_m / 20.0) * FACTOR_WEIGHTS["star"], 4)
        rec["talent_source"] = ("cfbd_team_talent" if COMP_KEY == "NCAAF"
                                else "cbbd_recruiting" if COMP_KEY == "NCAAM"
                                else "unknown_recruiting")
        changed += 1
    if changed:
        _save_ratings()
        DIAG.append(f"recruiting/talent strength: applied to {changed} teams")


# -------- The Odds API : tournament winner (outrights) -------------------
def apply_market_strength(outrights, known_names=None):
    """Derive a separately attributed market-power signal from title futures.

    A 20%-title team is market-rated more strongly than a 0.3% team, but that
    is not the same thing as roster talent. The legacy generic value fields
    remain for public power-rating compatibility; ``market_strength`` lets
    predict() use and label the signal without calling market opinion class.

    Creates a fresh ratings entry when a team has none, rather than only
    enriching a pre-existing one — college sports especially had no reliable
    pre-seeded file to enrich in the first place (see _ratings_lookup).

    `known_names`: see apply_recruiting_strength -- sportsbooks return college
    outright entries as "School Mascot" ("Alabama Crimson Tide"), which never
    matches the schedule feed's bare school name ("Alabama") on its own."""
    if COMP.get("source") not in {"sportsdataio", "balldontlie", "cfbd", "cbbd"} or not outrights:
        return
    mx = max((o["pct"] for o in outrights), default=0) or 1
    ratings = _load_ratings()  # this is the live _RATINGS dict predict() reads
    changed = 0
    for o in outrights:
        key = _resolve_known_name(o["team"], known_names)
        share = o["pct"] / mx
        # see apply_recruiting_strength/_talent_share_curve: scaled to the
        # actual 10/10 ceiling (squad_value_m 1500, star_value_m 200)
        # instead of undershooting it, with the same steeper-below-the-
        # competitive-floor curve for a true bottom-tier team's market odds.
        curved = _talent_share_curve(share)
        val_m = round(curved * 1500)
        star_m = round(curved * 200)
        rec = _ratings_lookup(key)
        if rec is None:
            rec = {"fifa_rank": 45, "squad_value_m": 0, "star_value_m": 0}
            ratings[key] = rec
        rec["squad_value_m"] = val_m
        rec["star_value_m"] = star_m
        rec["market_pct"] = o["pct"]
        rec["market_strength"] = round(
            (val_m / 150.0) * FACTOR_WEIGHTS["squad_value"]
            + (star_m / 20.0) * FACTOR_WEIGHTS["star"], 4)
        changed += 1
    if changed:
        DIAG.append(f"market strength: applied to {changed} teams from championship odds")


def fetch_college_class_strength(adapter, kind):
    """Fetch a slow-changing college class signal with last-good fallback.

    ``kind`` is ``talent`` (NCAAF) or ``recruiting`` (NCAAM). A fresh cache
    saves quota; if a refresh later fails, even a stale last-good snapshot is
    preferable to publishing a sudden all-zero talent field.
    """
    if kind not in {"talent", "recruiting"}:
        raise ValueError(f"unsupported college class kind: {kind}")
    cache_file = f"college_{COMP_KEY.lower()}_{kind}_cache.json"
    cached = {}
    try:
        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as handle:
                payload = json.load(handle)
            cached = payload.get("data") if isinstance(payload, dict) else {}
            cached = cached if isinstance(cached, dict) else {}
            age = time.time() - float(payload.get("t") or os.path.getmtime(cache_file))
            if cached and age < COLLEGE_CLASS_CACHE_MIN * 60:
                DIAG.append(f"{kind} strength: cached ({len(cached)} teams)")
                return cached
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        DIAG.append(f"{kind} strength cache ignored: {_scrub(exc)}")
        cached = {}

    try:
        data = getattr(adapter, kind)()
        if not data:
            raise ProviderError(f"{kind} endpoint returned 0 teams")
        payload = {"t": time.time(), "data": data}
        tmp = cache_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, cache_file)
        DIAG.append(f"{kind} strength: refreshed ({len(data)} teams)")
        return data
    except (ProviderError, OSError, ValueError, TypeError) as exc:
        if cached:
            DIAG.append(f"{kind} strength: refresh failed; using last-good cache ({_scrub(exc)})")
            return cached
        raise


def refresh_college_advanced_metrics(adapter, output_path=None):
    """Refresh NCAAF's licensed CFBD advanced profile as shadow-only data."""
    if COMP_KEY != "NCAAF" or adapter is None:
        return None
    path = output_path or "advanced_metrics_ncaaf.json"
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < COLLEGE_ADVANCED_CACHE_MIN * 60:
            with open(path, encoding="utf-8") as handle:
                cached = json.load(handle)
            if cached.get("schema_version") == 1 and cached.get("shadow_only") is True:
                return cached
    except Exception as exc:
        DIAG.append(f"CFBD advanced cache unreadable: {_scrub(exc)}")
    try:
        result = adapter.advanced_team_metrics()
        profiles = result.get("profiles") or {}
        season_role = "current"
        if not profiles:
            # These metrics are derived from plays that have been run, so from
            # the end of one season until well into the next the current-season
            # query answers with nothing -- and returning None here dropped the
            # research panel for every NCAAF fixture on the board through the
            # whole offseason. The last completed season comes from the same
            # licensed endpoint and is exactly what the NFL profile already
            # falls back to. The season and its role travel in the receipt
            # below, so a prior season is never shown as current form.
            prior_season = int(result.get("season") or 0) - 1
            prior = adapter.advanced_team_metrics(season=prior_season) if prior_season > 0 else {}
            profiles = prior.get("profiles") or {}
            if not profiles:
                return None
            result = prior
            season_role = "prior_completed"
        payload = {
            "schema_version": 1,
            "generated_at": _utc_now().isoformat().replace("+00:00", "Z"),
            "sport": "NCAAF",
            "source": result.get("source") or "CollegeFootballData /stats/season/advanced",
            "license": "active CFBD API tier",
            "shadow_only": True,
            "coverage": {"season": result.get("season"), "season_role": season_role,
                         "teams": len(profiles), "garbage_time_excluded": True},
            "profiles": profiles,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        return payload
    except Exception as exc:
        DIAG.append(f"CFBD advanced metrics unavailable: {_scrub(exc)}")
        try:
            with open(path, encoding="utf-8") as handle:
                stale = json.load(handle)
            return stale if stale.get("schema_version") == 1 and stale.get("shadow_only") is True else None
        except Exception:
            return None


def estimate_title_odds(matches, code_map):
    """Model-derived 'who's favored to win it all' fallback for when real
    championship-odds market data isn't available -- fetch_outrights()
    returns an empty list for EVERY competition right now (The Odds API's
    outrights quota is exhausted, per MARKET_STATE["quota_out"]), which
    left the Title race panel with nothing to show even preseason, when
    users are "all eager to know who is favored" despite no market odds
    existing yet. Ranks every team appearing in this run's full schedule
    by power_rating() -- the same curated-class + self-training-Elo blend
    predict() itself already reads, not a new signal -- and reshapes that
    into the exact title_odds shape the frontend's _v4TitleRows() already
    expects (team/code/pct). Applies to every competition's schedule the
    same way, not just NCAAF/NCAAM -- whatever rating data already exists
    for that sport (curated class file, market-derived ratings, or bare
    Elo) is what participates; this doesn't backfill soccer's separate,
    already-flagged partial ratings-coverage gap.

    Explicitly marked is_estimate=True (and source="model") on every row
    so this is never mistaken for a real market read once live odds
    return -- fetch_outrights()'s real rows carry neither field, so a
    consumer can tell the two apart without any schema change."""
    names = set()
    for m in matches:
        for side in (m.get("home"), m.get("away")):
            if side and side.get("name"):
                names.add(side["name"])
    if not names:
        return []
    scores = {name: power_rating(name) for name in names}
    # softmax-style share so the gap between teams' ratings matters, not
    # just their rank -- a heuristic temperature, not a calibrated
    # probability model (this is explicitly an estimate, not a real
    # market read, and is labeled as such below)
    TEMP = 0.9
    exps = {name: math.exp(score * TEMP) for name, score in scores.items()}
    total = sum(exps.values()) or 1.0
    rows = [{"team": name, "code": code_map.get(norm(name), ""),
              "pct": round(exps[name] / total * 100, 1),
              "is_estimate": True, "source": "model"}
             for name in names]
    rows.sort(key=lambda r: -r["pct"])
    return rows


def fetch_outrights(code_map):
    if not COMP.get("outright"):
        DIAG.append("title odds: no outright market for this competition"); return []
    _load_outrights_cache()
    now = time.time()
    if now - _OUT_CACHE["t"] < OUTRIGHTS_CACHE_MIN * 60 and _OUT_CACHE["data"]:
        DIAG.append("title odds: cached"); return _OUT_CACHE["data"]
    try:
        events = _get(f"{OUTRIGHTS_URL}&apiKey={ODDS_API_KEY}", provider="odds_api")
    except Exception as e:
        if _is_quota_error(e):
            MARKET_STATE["quota_out"] = True
            DIAG.append("title odds: FAILED — monthly quota exhausted")
        else:
            DIAG.append(f"title odds: FAILED — {e}")
        return _OUT_CACHE["data"] or []
    agg = defaultdict(list)
    for ev in events:
        for bk in ev.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt.get("key") != "outrights": continue
                raw = {o.get("name"): 1.0 / o["price"]
                       for o in mkt.get("outcomes", []) if o.get("price")}
                s = sum(raw.values())
                if s > 0:
                    for nm, r in raw.items(): agg[nm].append(r / s)
    out = [{"team": nm, "code": code_map.get(norm(nm), ""),
            "pct": round(sum(a) / len(a) * 100, 1)} for nm, a in agg.items()]
    out.sort(key=lambda x: -x["pct"])
    # movement since first sighting (self-logged, like match odds)
    tfile = f"title_open_{COMP_KEY.lower()}.json"
    topen = {}
    try:
        with open(tfile, encoding="utf-8") as f: topen = json.load(f)
    except Exception: pass
    dirty = False
    for x in out:
        k = norm(x["team"])
        if k not in topen:
            topen[k] = x["pct"]; dirty = True
        x["open"] = topen[k]
        x["move"] = round(x["pct"] - topen[k], 1)
        x["dec"] = round(100.0 / x["pct"], 2) if x["pct"] else None   # implied decimal odds
    if dirty:
        try:
            tmp = tfile + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f: json.dump(topen, f)
            os.replace(tmp, tfile)
        except Exception as e:
            DIAG.append(f"title open save failed: {e}")
    _OUT_CACHE["t"] = now; _OUT_CACHE["data"] = out
    _save_outrights_cache()
    DIAG.append(f"title odds: {len(out)} teams")
    return out


# -------- ESPN news + RSS feeds (keyless) : diverse updates --------------
def _news_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(text)
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _news_is_fresh(item, now=None):
    """Reject stale or undated headlines before cache/diversity processing."""
    published = _news_datetime((item or {}).get("published"))
    if published is None:
        return False
    current = _utc_now(now)
    age = current - published
    return (-datetime.timedelta(hours=NEWS_FUTURE_TOLERANCE_HOURS)
            <= age <= datetime.timedelta(days=NEWS_MAX_AGE_DAYS))


def _news_sort_key(item):
    return _news_datetime((item or {}).get("published")) or datetime.datetime.min.replace(
        tzinfo=datetime.timezone.utc)


def _tag(el):
    return str(el.tag).split("}")[-1].lower()


def _child_text(el, *names):
    want = {n.lower() for n in names}
    for ch in list(el):
        if _tag(ch) in want:
            return (ch.text or "").strip()
    return ""


def _entry_link(el):
    # RSS item link text
    link = _child_text(el, "link")
    if link:
        return link.strip()
    # Atom link href
    for ch in list(el):
        if _tag(ch) == "link" and ch.attrib.get("href"):
            return ch.attrib.get("href", "").strip()
    return ""


def _source_from_entry(el, fallback):
    # Google News RSS usually includes <source>Original Outlet</source>
    src = _child_text(el, "source")
    return _clean(src) or fallback


def _source_label(item):
    """Return one clean source name so the UI can keep sources balanced."""
    src = _clean(item.get("source") or item.get("feed") or "News")
    low = src.lower()
    fixes = {
        "associated press": "AP",
        "ap news": "AP",
        "theguardian.com": "The Guardian",
        "guardian": "The Guardian",
        "bbc": "BBC Sport",
        "bbc sport": "BBC Sport",
        "espn fc": "ESPN",
    }
    for k, v in fixes.items():
        if k in low:
            return v
    return src[:38] if src else "News"


def _news_key(item):
    h = re.sub(r"\s+", " ", (item.get("headline") or "").lower()).strip()
    link = (item.get("link") or "").split("?")[0].split("#")[0].strip().lower()
    return (h, link)


def _load_previous_news():
    """Keep RSS diversity during --loop if one refresh only returns ESPN.

    Re-checks _news_relevant() on every carried-forward item, not just fresh
    ones -- confirmed live 2026-07-26: an item accepted back when a
    competition had no relevance filtering at all (every soccer competition,
    before that gap was fixed the same day) would otherwise keep getting
    merged forward by fetch_news() indefinitely, since only freshly-fetched
    items ever passed through add_item()'s relevance check. That's exactly
    why EPL/UCL's News tab kept showing the same NFL/MLB pollution run after
    run even once the underlying filtering gap was fixed and fresh fetches
    were working again -- the OLD accepted items were never re-validated
    against the new rules, just carried forward as "previous" forever.
    """
    try:
        with open(f"data_{COMP_KEY.lower()}.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        # Files written before news was scoped by sport may contain headlines
        # inherited from whichever competition last overwrote data.json.
        if old.get("news_scope") != COMP_KEY:
            return []
        arr = old.get("news") or []
        if isinstance(arr, list):
            return [item for item in arr[:80]
                    if _news_relevant(item) and _news_is_fresh(item)]
    except Exception:
        pass
    return []


def _balanced_news(items, limit=48):
    """Interleave sources so one outlet cannot take over the News tab."""
    cleaned, seen = [], set()
    for item in items:
        if not item.get("headline") or not _news_is_fresh(item):
            continue
        item = dict(item)
        item["source"] = _source_label(item)
        item.setdefault("feed", item["source"])
        item.setdefault("competition", COMP_KEY)
        item.setdefault("sport", COMP["sport"])
        item.setdefault("desc", "")
        item.setdefault("published", "")
        item.setdefault("link", "")
        k = _news_key(item)
        if k in seen:
            continue
        seen.add(k)
        cleaned.append(item)

    by_src = defaultdict(list)
    for item in sorted(cleaned, key=_news_sort_key, reverse=True):
        by_src[item.get("source") or "News"].append(item)

    srcs = sorted(by_src, key=lambda s: s.lower())
    out, row = [], 0
    while len(out) < limit and srcs:
        moved = False
        for src in srcs:
            if row < len(by_src[src]):
                out.append(by_src[src][row])
                moved = True
                if len(out) >= limit:
                    break
        if not moved:
            break
        row += 1
    return out


def fetch_news():
    now = time.time()
    if now - _NEWS_CACHE["t"] < NEWS_CACHE_MIN * 60 and _NEWS_CACHE["data"]:
        return _NEWS_CACHE["data"]

    items, seen = [], set()

    def add_item(item):
        if not item.get("headline") or not _news_is_fresh(item):
            return False
        item = dict(item)
        if not _news_relevant(item):
            return False
        item["source"] = _source_label(item)
        item.setdefault("competition", COMP_KEY)
        item.setdefault("sport", COMP["sport"])
        k = _news_key(item)
        if k in seen:
            return False
        seen.add(k)
        items.append(item)
        return True

    # RSS + Google News backups. Failures are allowed; old diverse items are merged below.
    for feed_name, url in RSS_FEEDS:
        try:
            root = ET.fromstring(_get_text(url, UA)); n = 0
            entries = [el for el in root.iter() if _tag(el) in ("item", "entry")]
            candidates = []
            for it in entries:
                title = _child_text(it, "title")
                if not title:
                    continue
                src = _source_from_entry(it, feed_name)
                desc = _child_text(it, "description", "summary", "content")
                pub = _child_text(it, "pubDate", "published", "updated")
                candidates.append({"headline": _clean(title),
                                   "desc": _clean(desc)[:180],
                                   "published": _rfc_iso(pub) or pub,
                                   "link": _entry_link(it),
                                   "source": src,
                                   "feed": feed_name})
            # Some search feeds return evergreen/archive pages ahead of recent
            # reporting. Sort first, then apply the six-item publisher cap.
            for candidate in sorted(candidates, key=_news_sort_key, reverse=True):
                ok = add_item(candidate)
                n += 1 if ok else 0
                if n >= 6:
                    break
            DIAG.append(f"news {feed_name}: {n}")
        except Exception as e:
            DIAG.append(f"news {feed_name}: FAILED — {e}")

    previous = _load_previous_news()
    current_sources = {_source_label(x) for x in items if x.get("headline")}
    previous_sources = {_source_label(x) for x in previous if x.get("headline")}

    # Carry prior headlines only when the current refresh genuinely lacks
    # source coverage. Fresh multi-source results must replace the old batch.
    if len(current_sources) <= 1 and len(previous_sources) > 1:
        DIAG.append("news: RSS returned one source; preserved previous diverse feed")
        merged = _balanced_news(items + previous, limit=48)
    else:
        merged = _balanced_news(items, limit=48)

    DIAG.append("news sources: " + ", ".join(sorted({_source_label(x) for x in merged})[:12]))
    _NEWS_CACHE["t"] = now; _NEWS_CACHE["data"] = merged
    return merged

# -------------------------------------------------------------------------


# ---- player database (accumulates from lineups + results, per competition) ----

def build_weekly_awards(matches, scorecard=None):
    """Four storylines from the last 7 days of finished results -- a "come
    back Monday to see what happened" hook for Community, built entirely
    from data every match already carries (score, prediction, upset
    profile). No new data source, no manual curation."""
    now = datetime.datetime.now(datetime.timezone.utc)
    window = now - datetime.timedelta(days=7)

    def _dt(iso):
        try:
            return datetime.datetime.fromisoformat(str(iso or "").replace("Z", "+00:00"))
        except Exception:
            return None

    verified = None
    if isinstance(scorecard, dict):
        verified = {
            str(pick.get("fixture_id")): pick
            for pick in (scorecard.get("picks") or [])
            if pick.get("fixture_id") is not None
            and pick.get("integrity_eligible") is True
            and pick.get("integrity_status") == "verified"
            and pick.get("legacy") is not True
        }
    recent = []
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        ko = _dt(m.get("kickoff"))
        sc = m.get("score") or {}
        if not ko or ko < window or sc.get("home") is None or sc.get("away") is None:
            continue
        if verified is not None:
            locked = verified.get(str(m.get("id")))
            if not locked:
                continue
            # Awards are public accountability claims. Reconstruct their model
            # evidence from the immutable lock receipt, never a finished
            # fixture's freshly recalculated prediction.
            m = dict(m)
            snapshot = locked.get("prediction_snapshot")
            if isinstance(snapshot, dict):
                m["prediction"] = _json_safe(snapshot)
            else:
                m["prediction"] = {
                    "pick": locked.get("pick"), "pick_name": locked.get("pick_name"),
                    "confidence": locked.get("confidence"), "edge": locked.get("edge"),
                    "upset": locked.get("upset_snapshot") or {},
                }
            m["_official_pick"] = locked
        recent.append(m)
    if not recent:
        return None

    def _margin(m):
        sc = m["score"]
        return abs((sc.get("home") or 0) - (sc.get("away") or 0))

    def _side_name(m, side):
        return {"h": m["home"]["name"], "a": m["away"]["name"], "d": "Draw"}.get(side)

    # biggest upset: the actual winner was the pre-match underdog, ranked
    # by how unlikely the model/market thought that winner was
    upsets = []
    for m in recent:
        up = (m.get("prediction") or {}).get("upset") or {}
        winner = (m.get("score") or {}).get("winner")
        if winner and winner != "d" and up.get("candidate") and winner == up["candidate"]:
            upsets.append((up.get("score") or 0, m, up))
    biggest_upset = None
    if upsets:
        upsets.sort(key=lambda x: -x[0])
        score, m, up = upsets[0]
        biggest_upset = {"home": m["home"]["name"], "away": m["away"]["name"],
                          "score_line": f"{m['score']['home']}-{m['score']['away']}",
                          "winner": up.get("candidate_name"), "upset_score": score,
                          "market_pct": up.get("market_dog_pct")}

    # model's best call / biggest miss this week, from graded predictions
    hits, misses = [], []
    for m in recent:
        pr = m.get("prediction") or {}
        winner = (m.get("score") or {}).get("winner")
        if not winner or not pr.get("pick"):
            continue
        row = (pr.get("edge") or 0, pr.get("confidence") or 0, m, pr, winner)
        official = m.get("_official_pick")
        if official is None:
            model_hit = pr["pick"] == winner
        elif isinstance(official.get("model_hit"), bool):
            model_hit = official["model_hit"]
        elif isinstance(official.get("result"), bool):
            model_hit = official["result"]
        elif str(official.get("result") or "").lower() in {"h", "a", "d"}:
            model_hit = str(official.get("result")).lower() == str(official.get("pick")).lower()
        elif str(official.get("result") or "").lower() in {"hit", "correct", "won", "win", "true"}:
            model_hit = True
        elif str(official.get("result") or "").lower() in {"miss", "incorrect", "lost", "loss", "false"}:
            model_hit = False
        else:
            # A verified receipt without a grade is not public evidence of a
            # hit or miss yet, even if the displayed score suggests one.
            continue
        (hits if model_hit else misses).append(row)
    best_call = None
    if hits:
        hits.sort(key=lambda x: -(x[0] or 0))
        edge, conf, m, pr, _ = hits[0]
        best_call = {"home": m["home"]["name"], "away": m["away"]["name"],
                      "pick": pr.get("pick_name"), "confidence": conf, "edge": edge}
    biggest_miss = None
    if misses:
        misses.sort(key=lambda x: -x[1])
        edge, conf, m, pr, winner = misses[0]
        biggest_miss = {"home": m["home"]["name"], "away": m["away"]["name"],
                         "pick": pr.get("pick_name"), "confidence": conf,
                         "actual": _side_name(m, winner)}

    closest = min(recent, key=_margin)
    closest_match = {"home": closest["home"]["name"], "away": closest["away"]["name"],
                      "score_line": f"{closest['score']['home']}-{closest['score']['away']}",
                      "margin": _margin(closest)}

    return {"window_days": 7, "matches_considered": len(recent),
            "biggest_upset": biggest_upset, "best_call": best_call,
            "biggest_miss": biggest_miss, "closest_match": closest_match}


LEGACY_PICKS = "picks_log.json"
PICK_SCHEMA_VERSION = 2
MODEL_CODE_MARKER = "matchday-predictor-integrity-2026-07"
FIXTURE_COUNT_HISTORY_FILE = "fixture_count_history.json"
FIXTURE_COUNT_HISTORY_LEN = 8
FIXTURE_COUNT_MIN_TRAILING = 5      # don't flag naturally-small competitions
FIXTURE_COUNT_ANOMALY_RATIO = 0.4   # current count below 40% of trailing average is suspicious


def _load_fixture_count_history():
    try:
        with open(FIXTURE_COUNT_HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _check_and_record_fixture_count(comp_key, current_count):
    """Flags a provider silently returning far fewer fixtures than usual --
    a 200 OK with 3 games instead of the usual 15 raises no error anywhere
    else in the pipeline, so this is the one place that would ever notice.
    Doesn't fail the build (a real short slate -- byes, an off week -- is
    legitimate and shouldn't block deployment); it only makes the anomaly
    loudly visible in DIAG and the payload, instead of quietly shipping as
    if nothing changed."""
    history = _load_fixture_count_history()
    trailing = history.get(comp_key) or []
    trailing_avg = sum(trailing) / len(trailing) if trailing else None
    anomaly = (
        trailing_avg is not None
        and trailing_avg >= FIXTURE_COUNT_MIN_TRAILING
        and current_count < trailing_avg * FIXTURE_COUNT_ANOMALY_RATIO
    )
    if anomaly:
        DIAG.append(
            f"fixture count anomaly: {current_count} fixtures this run vs. "
            f"trailing average {trailing_avg:.1f} over last {len(trailing)} run(s)"
        )
    trailing.append(current_count)
    history[comp_key] = trailing[-FIXTURE_COUNT_HISTORY_LEN:]
    try:
        tmp = FIXTURE_COUNT_HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=1)
        os.replace(tmp, FIXTURE_COUNT_HISTORY_FILE)
    except Exception as e:
        DIAG.append(f"fixture count history save failed: {e}")
    return {"current": current_count,
            "trailing_avg": round(trailing_avg, 1) if trailing_avg is not None else None,
            "anomaly": bool(anomaly)}


def _json_safe(value):
    """Return a detached JSON-safe copy suitable for an immutable ledger."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _utc_now(now=None):
    value = now or datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _parse_kickoff(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # A timezone-free time cannot establish a fair UTC lock boundary.
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(datetime.timezone.utc)


FORECAST_PAUSE_MESSAGE = forecast_pause.PAUSE_MESSAGE


def _forecast_publication_paused(competition=None):
    """Site-wide publication pause. No competition is exempt from it."""
    return forecast_pause.paused(competition)


def _set_prediction_publication_state(match, prediction):
    """Publish a normal forecast label or replace paused MLB output with a shell."""
    prediction = prediction if isinstance(prediction, dict) else {}
    context = (match or {}).get("pregame_context") or {}
    competition = str((match or {}).get("_comp") or COMP_KEY).upper()
    status = str((match or {}).get("status") or "").upper()
    if _forecast_publication_paused(competition) and status != "FINISHED":
        # Do not merely label the regular prediction: API consumers historically
        # read pick/confidence/probability fields without checking publication
        # state. Clear the production output into a minimal shell. The separate
        # match-level mlb_challenger_shadow remains available for research.
        prediction.clear()
        prediction.update({
            "publication_state": "paused",
            "publication_message": FORECAST_PAUSE_MESSAGE,
            "official_publication_eligible": False,
            "research_shadow_available": bool((match or {}).get("mlb_challenger_shadow")),
        })
        if isinstance(match, dict):
            match.pop("watchability", None)
    else:
        prediction["publication_state"] = (
            "lock_candidate" if context.get("phase") == "lock_window" else "preliminary")
    prediction["lock_readiness"] = context
    return prediction


def _enforce_forecast_pause_after_locked_picks(matches):
    """Hide legacy upcoming locks without touching finished receipts."""
    paused = 0
    for match in matches or []:
        competition = str((match or {}).get("_comp") or COMP_KEY).upper()
        status = str((match or {}).get("status") or "").upper()
        if status == "FINISHED" or not _forecast_publication_paused(competition):
            continue
        match["prediction"] = _set_prediction_publication_state(
            match, match.get("prediction"))
        paused += 1
    return paused


def _lock_decision(match, now=None):
    """Classify a fixture without ever turning post-kickoff data into a pick."""
    status = str((match or {}).get("status") or "").upper()
    kickoff = _parse_kickoff((match or {}).get("kickoff"))
    if status != "UPCOMING":
        return {"state": "quarantine", "reason": f"first_seen_{status.lower() or 'unknown'}",
                "status_at_lock": status or None, "kickoff": kickoff}
    competition = str((match or {}).get("_comp") or COMP_KEY).upper()
    # Product safety pause: published forecasting is on hold site-wide while
    # the model is rebuilt on the Bet Better data engine (see forecast_pause).
    # No competition is exempt. Do not admit a new receipt to the official
    # immutable pick ledger -- a paused pick that was never shown must not later
    # be graded as though it had been. Existing receipts still flow through
    # apply_locked_picks() and every historical grading path below.
    if _forecast_publication_paused(competition):
        return {"state": "wait", "reason": "official_forecasts_paused",
                "status_at_lock": status, "kickoff": kickoff,
                "publication_state": "paused"}
    if kickoff is None:
        return {"state": "wait", "reason": "missing_or_unparseable_kickoff",
                "status_at_lock": status, "kickoff": None}
    current = _utc_now(now)
    lead_seconds = (kickoff - current).total_seconds()
    if lead_seconds < 0:
        return {"state": "quarantine", "reason": "past_due_upcoming",
                "status_at_lock": status, "kickoff": kickoff, "lead_seconds": lead_seconds}
    lock_hours = pregame_context.lock_window_hours(competition)
    if lead_seconds > lock_hours * 3600:
        return {"state": "wait", "reason": "outside_lock_window",
                "status_at_lock": status, "kickoff": kickoff, "lead_seconds": lead_seconds,
                "lock_window_hours": lock_hours}
    return {"state": "eligible", "reason": "verified_pregame_window",
            "status_at_lock": status, "kickoff": kickoff, "lead_seconds": lead_seconds,
            "locked_at": current, "lock_window_hours": lock_hours}


def _record_is_official(rec):
    # Keep grading and every downstream publisher on one integrity boundary.
    # Historical receipts without a frozen sport-aware window retain the
    # original 12-hour default through this shared validator.
    return is_official_pick_record(
        rec,
        schema_version=PICK_SCHEMA_VERSION,
        model_code_marker=MODEL_CODE_MARKER,
        default_lock_window_hours=LOCK_WINDOW_HOURS,
    )


def _quarantine_legacy_records(picks):
    """Move unverifiable entries aside while preserving every original field.

    Moving the key lets the same fixture receive a new verified lock when it
    eventually enters the 12-hour publication window. The legacy payload remains
    in the ledger and in the scorecard's separate unverified summary.
    """
    changed = False
    for key in list(picks):
        rec = picks.get(key)
        if not isinstance(rec, dict) or _record_is_official(rec):
            continue
        before = (rec.get("fixture_id"), rec.get("integrity_eligible"),
                  rec.get("integrity_status"), rec.get("quarantine_reason"))
        rec.setdefault("fixture_id", str(key).split("legacy:")[-1])
        rec["integrity_eligible"] = False
        rec["integrity_status"] = "quarantined"
        rec.setdefault("quarantine_reason", "legacy_missing_lock_provenance")
        if not str(key).startswith("legacy:"):
            legacy_key = f"legacy:{key}"
            if legacy_key in picks:
                # This fixture is ALREADY quarantined under its legacy key --
                # seeing it again under its plain key means something outside
                # the pipeline re-introduced it (a re-run seed/import step, a
                # restored backup). Suffixing to "legacy:<id>:2" here would
                # store the same pick twice and count it twice in the
                # scorecard's legacy/all-time tally; a real second opinion on
                # one fixture is impossible, since a fixture locks at most
                # once. Drop the reintroduced copy and keep the record already
                # in the ledger, which has been through grading/self-heal (the
                # re-added copies observed 2026-07-27 carried stale
                # penalty-inflated scorelines this pass had already fixed).
                del picks[key]
                DIAG.append(f"scorecard: dropped duplicate re-seeded pick for fixture {key}")
                changed = True
                continue
            picks[legacy_key] = rec
            del picks[key]
            changed = True
        after = (rec.get("fixture_id"), rec.get("integrity_eligible"),
                 rec.get("integrity_status"), rec.get("quarantine_reason"))
        changed = changed or before != after
    return changed


def _locked_input_snapshot(match):
    fields = ("id", "stage", "kickoff", "status", "venue", "home", "away",
              "markets", "weather", "injuries", "lineups", "h2h", "stats", "stats_extra",
              "data_source", "advanced_metrics", "advanced_metrics_meta", "nfl_challenger_shadow",
              "mlb_challenger_shadow",
              "personnel", "personnel_shadow", "pregame_context", "pregame_provenance",
              "venue_context",
              "model_signal_schema")
    return _json_safe({"competition": COMP_KEY,
                       "competition_config": COMP,
                       "match": {key: (match or {}).get(key) for key in fields}})

def _load_picks():
    for path in ([PICKS_FILE, LEGACY_PICKS] if COMP_KEY == "WC" else [PICKS_FILE]):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}

def _save_picks(p):
    """Atomically persist the integrity ledger or fail the whole fetch.

    A ledger write is not optional output: allowing this error to be swallowed
    lets fresh predictions deploy while their official locks disappear.
    """
    tmp = PICKS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, PICKS_FILE)
    except Exception as e:
        DIAG.append(f"picks save failed: {e}")
        raise RuntimeError(f"could not persist {PICKS_FILE}") from e


def _forecast_ledger_path():
    """Keep test/temp ledgers beside their patched picks file."""
    directory = os.path.dirname(os.path.abspath(PICKS_FILE))
    return os.path.join(directory, f"forecast_ledger_{COMP_KEY.lower()}.jsonl")


def _market_fields(pr, mk):
    """Derive the market-comparison fields for a pick from current market odds.
    Shared by the initial lock and the later backfill (odds often aren't fetched
    yet when a pick first locks, since fetch_odds() is gated to near kickoff)."""
    market_pick = market_pct = value_side = value_edge = value_mkt = None
    if mk.get("home_pct") is not None:
        trio = {"h": mk["home_pct"], "d": mk["draw_pct"], "a": mk["away_pct"]}
        market_pick = max(trio, key=trio.get); market_pct = trio[market_pick]
        # Knockout official picks use advancement odds, but a 1X2 benchmark is
        # always compared with the separately preserved regulation forecast.
        regulation = pr.get("regulation_probs") or pr.get("model") or {}
        edges = {k: regulation.get(k, 0) - trio[k] for k in trio}
        vs = max(edges, key=edges.get)
        if edges[vs] >= 6:
            value_side, value_edge, value_mkt = vs, round(edges[vs]), trio[vs]
    return market_pick, market_pct, value_side, value_edge, value_mkt


def _market_comparison_side(rec):
    """Frozen side whose regulation result is comparable with a 1X2 market."""
    if not isinstance(rec, dict):
        return None
    explicit = rec.get("market_comparison_pick")
    if explicit in ("h", "d", "a"):
        return explicit
    # Backward compatibility for receipts written before the explicit field.
    if rec.get("outcome_basis") == "ultimate_winner" or (rec.get("prediction_snapshot") or {}).get("is_knockout"):
        side = rec.get("regulation_pick")
    else:
        side = rec.get("pick")
    return side if side in ("h", "d", "a") else None


def _market_snapshot_receipt(market, recorded_at):
    """Return a same-lock receipt only when quote time is provably pre-lock."""
    if not isinstance(market, dict) or market.get("home_pct") is None:
        return None
    observed_at = market.get("observed_at")
    observed = _parse_kickoff(observed_at)
    recorded = _parse_kickoff(recorded_at)
    if observed is None or recorded is None or observed > recorded:
        return None
    return {
        "source": market.get("source") or "The Odds API consensus",
        "source_reference": market.get("source_reference") or "https://the-odds-api.com/",
        "observed_at": observed_at,
        "recorded_at": recorded_at,
        "snapshot_id": market.get("snapshot_id"),
        "books": market.get("books"),
        "spread": market.get("spread"),
    }


def _lock_market_comparable(rec):
    """True only for a market quote captured no later than this forecast lock."""
    if not isinstance(rec, dict) or not isinstance(rec.get("market_snapshot"), dict):
        return False
    receipt = rec.get("market_snapshot_receipt") or {}
    observed = _parse_kickoff(receipt.get("observed_at") or rec.get("market_snapshot_at"))
    recorded = _parse_kickoff(receipt.get("recorded_at") or rec.get("market_snapshot_recorded_at")
                              or rec.get("locked_at"))
    locked = _parse_kickoff(rec.get("locked_at"))
    kickoff = _parse_kickoff(rec.get("kickoff"))
    return bool(observed and recorded and locked and kickoff
                and observed <= recorded <= locked < kickoff
                and not rec.get("market_backfilled_at"))


def _market_agreement_split(records):
    """Summarize like-for-like regulation accuracy by market agreement."""
    comparable = [p for p in records if _market_comparison_side(p) in ("h", "d", "a")
                  and p.get("market_pick") in ("h", "d", "a")
                  and isinstance(p.get("market_comparison_hit"), bool)]
    agreed = [p for p in comparable if _market_comparison_side(p) == p.get("market_pick")]
    disagreed = [p for p in comparable if _market_comparison_side(p) != p.get("market_pick")]
    return {
        "agree": {"n": len(agreed),
                  "hits": sum(1 for p in agreed if p.get("market_comparison_hit"))},
        "disagree": {"n": len(disagreed),
                     "hits": sum(1 for p in disagreed if p.get("market_comparison_hit"))},
    }


def _is_value_chance(rec):
    """True when the best regulation value side differs from our comparable side."""
    return bool(rec.get("value_side") in ("h", "d", "a")
                and rec.get("value_side") != _market_comparison_side(rec))


def _pending_value_count(records):
    """Count only value signals supported by a market present at model lock."""
    return sum(1 for rec in records
               if rec.get("value_side") and not rec.get("result")
               and _lock_market_comparable(rec)
               and _market_comparison_side(rec) in ("h", "d", "a"))


def _signal_quality(records, name):
    """Accuracy when a directional factor favored the selected team.

    Draw selections have no home/away direction and must not be silently
    treated as away picks.
    """
    relevant = [p for p in records if p.get("pick") in ("h", "a")
                and isinstance(p.get("factor_snapshot"), dict)
                and abs(float(p["factor_snapshot"].get(name, 0))) >= 0.5]
    favored = [p for p in relevant
               if (float(p["factor_snapshot"].get(name, 0)) > 0) == (p.get("pick") == "h")]
    return ({"n": len(favored), "hits": sum(1 for p in favored if p.get("model_hit"))}
            if favored else {"n": 0, "hits": 0})


def _probability_metric_summary(records):
    """Return probability metrics with their exact contributing cohorts."""
    briers = [((float(p["confidence"]) / 100.0) -
               (1.0 if p.get("model_hit") else 0.0)) ** 2
              for p in records if isinstance(p.get("confidence"), (int, float))]
    briers3 = [p.get("brier3") for p in records if p.get("brier3") is not None]
    logloss = [p.get("log_loss") for p in records if p.get("log_loss") is not None]
    advancement_briers = [p.get("brier_advancement") for p in records
                          if p.get("brier_advancement") is not None]
    advancement_logloss = [p.get("log_loss_advancement") for p in records
                           if p.get("log_loss_advancement") is not None]
    def mean(values):
        return round(sum(values) / len(values), 3) if values else None
    return {
        "brier": mean(briers), "brier_graded": len(briers),
        "brier3": mean(briers3), "brier3_graded": len(briers3),
        "log_loss": mean(logloss), "log_loss_graded": len(logloss),
        "brier_advancement": mean(advancement_briers),
        "advancement_graded": len(advancement_briers),
        "log_loss_advancement": mean(advancement_logloss),
        "log_loss_advancement_graded": len(advancement_logloss),
    }


def _closing_market_from_ledger(rec, path="market_snapshot_ledger.jsonl"):
    """Latest pre-kickoff v2 market consensus for this exact oriented fixture."""
    try:
        snapshots = market_snapshots.fixture_snapshots(
            path, rec.get("fixture_id"), rec.get("kickoff"), rec.get("competition") or COMP_KEY)
    except (OSError, ValueError):
        return None, None
    kickoff = _parse_kickoff(rec.get("kickoff"))
    eligible = []
    for snapshot in snapshots:
        participants = snapshot.get("participants") or {}
        if snapshot.get("schema_version") != market_snapshots.SCHEMA_VERSION:
            continue
        if str((participants.get("home") or {}).get("name") or "") != str(rec.get("home") or ""):
            continue
        if str((participants.get("away") or {}).get("name") or "") != str(rec.get("away") or ""):
            continue
        observed = _parse_kickoff(snapshot.get("observed_at"))
        recorded = _parse_kickoff(snapshot.get("recorded_at"))
        if not kickoff or not observed or not recorded or observed >= kickoff or recorded >= kickoff:
            continue
        eligible.append(snapshot)
    if not eligible:
        return None, None
    latest_by_source = {}
    for snapshot in eligible:
        source = str(snapshot.get("source") or "unknown")
        current = latest_by_source.get(source)
        marker = (snapshot.get("observed_at"), snapshot.get("recorded_at"), snapshot.get("event_id"))
        if current is None or marker > (current.get("observed_at"), current.get("recorded_at"), current.get("event_id")):
            latest_by_source[source] = snapshot
    selected = list(latest_by_source.values())
    outcomes = set((selected[0].get("no_vig_probabilities") or {}).keys())
    selected = [snapshot for snapshot in selected
                if set((snapshot.get("no_vig_probabilities") or {}).keys()) == outcomes]
    if not selected:
        return None, None
    probabilities = {side: round(sum(float(snapshot["no_vig_probabilities"][side])
                                          for snapshot in selected) / len(selected) * 100, 3)
                     for side in outcomes}
    receipt = {"sources": sorted(str(snapshot.get("source") or "unknown") for snapshot in selected),
               "source_count": len(selected),
               "event_ids": [snapshot.get("event_id") for snapshot in selected],
               "observed_at": [snapshot.get("observed_at") for snapshot in selected]}
    return probabilities, receipt


def _make_pick_record(match, prediction, market, decision, history=()):
    # This is the fixture's live prediction object. Mark it in place so the
    # UI and the immutable snapshot agree during the same build pass.
    prediction = prediction if isinstance(prediction, dict) else {}
    prediction["publication_state"] = "locked"
    prediction["lock_readiness"] = _json_safe(match.get("pregame_context"))
    availability = {
        "market": "available" if market.get("home_pct") is not None else "unavailable",
        "box_score": "available" if (match.get("stats_extra") or match.get("stats")) else "unavailable",
        "lineups": "available" if match.get("lineups") else "unavailable",
        "injuries": "available" if _injury_data_available(match) else "unavailable",
        "weather": "available" if match.get("weather") else "unavailable",
        "personnel": "available" if match.get("personnel") else "unavailable",
        "venue_context": "available" if match.get("venue_context") else "unavailable",
    }
    prediction["data_availability"] = availability
    market_pick, market_pct, value_side, value_edge, value_mkt = _market_fields(prediction, market)
    upset = prediction.get("upset") or {}
    probs = prediction.get("adjusted") or prediction.get("blend") or prediction.get("model") or {}
    regulation = prediction.get("regulation_probs") or probs
    comparison_pick = (prediction.get("market_comparison_pick")
                       or (prediction.get("regulation_pick") if prediction.get("is_knockout")
                           else prediction.get("pick")))
    locked_at = decision["locked_at"].isoformat().replace("+00:00", "Z")
    market_receipt = _market_snapshot_receipt(market, locked_at)
    rec = {
        "schema_ver": PICK_SCHEMA_VERSION,
        "fixture_id": str(match.get("id")),
        "competition": COMP_KEY,
        "home": match["home"]["name"], "away": match["away"]["name"],
        "stage": match.get("stage"), "kickoff": match.get("kickoff"),
        "pick": prediction.get("pick"), "pick_name": prediction.get("pick_name"),
        "confidence": prediction.get("confidence"), "edge": prediction.get("edge"),
        "base_pick": prediction.get("base_pick"), "base_pick_name": prediction.get("base_pick_name"),
        "probs": {"h": probs.get("h"), "d": probs.get("d"), "a": probs.get("a")},
        "advancement_probs": _json_safe(prediction.get("advancement")),
        "regulation_probs": {"h": regulation.get("h"), "d": regulation.get("d"), "a": regulation.get("a")},
        "regulation_pick": prediction.get("regulation_pick") or prediction.get("pick"),
        "market_comparison_pick": comparison_pick,
        "market_comparison_basis": "regulation_1x2",
        "outcome_basis": "ultimate_winner" if prediction.get("is_knockout") else "regulation",
        "market_basis": "regulation_1x2",
        "market_pick": market_pick, "market_pct": market_pct,
        "pick_mkt": ({"h": market.get("home_pct"), "d": market.get("draw_pct"), "a": market.get("away_pct")}.get(comparison_pick)
                     if market.get("home_pct") is not None else None),
        "value_side": value_side, "value_edge": value_edge, "value_mkt": value_mkt,
        "value_name": ({"h": match["home"]["name"], "a": match["away"]["name"], "d": "Draw"}.get(value_side)
                       if value_side else None),
        "upset_candidate": upset.get("candidate"), "upset_name": upset.get("candidate_name"),
        "upset_score": upset.get("score"), "upset_candidate_pct": upset.get("candidate_pct"),
        "upset_triggered": upset.get("triggered"), "upset_temperature": upset.get("temperature"),
        "upset_reason": upset.get("reason"),
        "factor_snapshot": {k: round(float(v), 2) for k, v in (prediction.get("why") or {}).items()},
        "market_snapshot": ({"h": market.get("home_pct"), "d": market.get("draw_pct"), "a": market.get("away_pct")}
                            if market.get("home_pct") is not None else None),
        "market_snapshot_at": (market_receipt or {}).get("observed_at"),
        "market_snapshot_recorded_at": locked_at if market.get("home_pct") is not None else None,
        "market_snapshot_receipt": market_receipt,
        "market_gap": upset.get("market_gap_pct"),
        "upset_snapshot": {"candidate": upset.get("candidate_name"),
                           "class": upset.get("upset_class"),
                           "market_dog_pct": upset.get("market_dog_pct"),
                           "model_dog_pct": upset.get("model_dog_pct"),
                           "upset_edge": upset.get("upset_edge"),
                           "independent_model_dog_pct": upset.get("independent_model_dog_pct"),
                           "independent_model_lead_pct": upset.get("independent_model_lead_pct"),
                           "independent_edge": upset.get("independent_edge"),
                           "edge_threshold": upset.get("edge_threshold"),
                           "supporting_signals": upset.get("supporting_signals"),
                           "personnel_gate": upset.get("personnel_gate"),
                           "personnel_blockers": upset.get("personnel_blockers"),
                           "radar": upset.get("radar"),
                           "standings_candidate": upset.get("standings_candidate"),
                           "standings_gap_pct": upset.get("standings_gap_pct"),
                           "gate": "open" if upset.get("triggered") else ("blocked" if upset.get("blocked") else "none"),
                           "box_score_edge": upset.get("box_score_edge")},
        "box_score_available": bool(match.get("stats_extra") or match.get("stats")),
        "data_availability": availability,
        "damp_pct": prediction.get("damp_pct"), "mkt_pull": prediction.get("mkt_pull"),
        "model_ver": PREDICTION_MODEL_VERSION, "model_code_marker": MODEL_CODE_MARKER,
        "model_signal_schema": match.get("model_signal_schema") or MODEL_SIGNAL_SCHEMA,
        "reproducibility": {"model_version": PREDICTION_MODEL_VERSION,
                            "model_signal_schema": match.get("model_signal_schema") or MODEL_SIGNAL_SCHEMA,
                            "probability_basis": "advancement" if prediction.get("is_knockout") else "regulation",
                            "market_comparison_basis": "regulation_1x2",
                            "market_comparison_pick": comparison_pick},
        "locked_at": locked_at,
        "lead_time_seconds": round(float(decision["lead_seconds"]), 3),
        "lead_time_hours": round(float(decision["lead_seconds"]) / 3600.0, 6),
        "lock_window_hours": float(decision.get("lock_window_hours") or
                                     pregame_context.lock_window_hours(COMP_KEY)),
        "status_at_lock": decision["status_at_lock"],
        "integrity_eligible": True, "integrity_status": "verified",
        "integrity_reason": decision["reason"],
        "prediction_snapshot": _json_safe(prediction),
        "input_snapshot": _locked_input_snapshot(match),
        # Research-only and immutable: this captures exactly what MFTI could
        # reconstruct at the official pregame lock without affecting the pick.
        "mfti_shadow": _json_safe(
            mfti_research.build_shadow_receipt(
                match, prediction, history, locked_at
            )
        ),
        "result": None, "model_result": None, "market_result": None,
    }
    return rec


def apply_locked_picks(matches):
    """Overwrite the live-recomputed prediction with the locked pick from the
    picks log, for any match that has already locked (see update_scorecard's
    LOCK_WINDOW_HOURS).

    predict() reruns on every match on every fetch — including matches that
    are within their lock window, live, or long finished — using Elo/H2H
    trained on all results seen so far. Without this, a match's displayed
    pick could keep drifting after it locked (right up through kickoff and
    even after full time), contradicting the frozen, graded record in the
    picks log. This makes that frozen entry win everywhere once it exists."""
    picks = _load_picks()
    for m in matches:
        rec = picks.get(str(m.get("id")))
        snapshot = (rec or {}).get("prediction_snapshot")
        if not rec or not _record_is_official(rec) or not isinstance(snapshot, dict):
            continue
        # Replace the entire object.  Selective overlays previously left live
        # factors, narrative and data-quality fields mixed into a locked pick.
        m["prediction"] = _json_safe(snapshot)
        # Older valid receipts predate this display marker.  Mark only the
        # detached in-memory copy; never rewrite their stored lock snapshot.
        m["prediction"]["publication_state"] = "locked"


# Legacy boundary used only to validate already-published records that predate
# sport-aware windows. New locks use pregame_context.lock_window_hours().
LOCK_WINDOW_HOURS = 12.0

_KNOCKOUT_STAGE_MARKERS = (
    "knockout", "playoff", "postseason", "round of", "last ",
    "quarter", "semi", "final", "third place",
)


def _side_result(home_score, away_score):
    if home_score is None or away_score is None:
        return None
    return "h" if home_score > away_score else "a" if away_score > home_score else "d"


def _is_knockout_stage(stage):
    label = " ".join(str(stage or "").strip().lower().replace("_", "-").split())
    return bool(label) and any(marker in label for marker in _KNOCKOUT_STAGE_MARKERS)


def _is_advancement_fixture(match, locked_pick=None):
    stage = (match or {}).get("stage") or (locked_pick or {}).get("stage")
    snap = (locked_pick or {}).get("prediction_snapshot") or {}
    competition = str((locked_pick or {}).get("competition") or
                      (match or {}).get("_comp") or COMP_KEY).upper()
    label = " ".join(str(stage or "").strip().lower().replace("_", " ").split())
    # UCL's Final is unambiguously a single match. Earlier knockout stages can
    # be two-legged; this competition rule deliberately overrides stale legacy
    # snapshots that once marked every knockout-stage leg as advancement.
    if competition == "UCL":
        return label == "final"
    if snap.get("is_knockout") is True or (locked_pick or {}).get("outcome_basis") == "ultimate_winner":
        return True
    config = COMPETITIONS.get(competition, COMP)
    return bool(config.get("sport") == "soccer" and config.get("single_elimination")
                and _is_knockout_stage(stage))


def _scorecard_results(match, locked_pick=None):
    """Return separate (model, market) settlement results.

    Tournament knockout model picks are graded by the team that ultimately wins
    or advances after extra time or penalties. The 1X2 market comparison remains
    settled on the regulation result. Neither result changes the stored score.
    """
    sc_obj = match.get("score") or {}
    shown_home, shown_away = sc_obj.get("home"), sc_obj.get("away")
    pens = sc_obj.get("pens") or {}

    ultimate = sc_obj.get("winner")
    if ultimate not in ("h", "d", "a"):
        ultimate = _side_result(shown_home, shown_away)
    if ultimate == "d" and pens.get("home") is not None and pens.get("away") is not None:
        ultimate = _side_result(pens.get("home"), pens.get("away"))

    is_knockout = _is_advancement_fixture(match, locked_pick)
    competition = str((locked_pick or {}).get("competition") or
                      (match or {}).get("_comp") or COMP_KEY).upper()
    config = COMPETITIONS.get(competition, COMP)
    reg = sc_obj.get("reg") or {}
    market_result = _side_result(reg.get("home"), reg.get("away"))
    if market_result is None:
        if is_knockout and config.get("has_draws"):
            # Do not guess a soccer 1X2 settlement from an extra-time score.
            market_result = (locked_pick or {}).get("market_result")
        else:
            # Non-draw moneylines (and ordinary final scores) settle on the winner.
            market_result = ultimate
    # A tied NFL game is a push for the two-way moneyline benchmark. Keep the
    # model's winner forecast as a miss, but exclude the market from grading.
    if competition == "NFL" and ultimate == "d":
        market_result = None
    model_result = ultimate if is_knockout else (market_result or ultimate)
    return model_result, market_result


def _score_snapshot(score, observed_at=None, source="provider"):
    score = score or {}
    return {"display": {"home": score.get("home"), "away": score.get("away")},
            "regulation": _json_safe(score.get("reg")),
            "penalties": _json_safe(score.get("pens")),
            "ultimate_winner": score.get("winner"),
            "observed_at": observed_at or _utc_now().isoformat().replace("+00:00", "Z"),
            "source": source}


def _score_string(score):
    score = score or {}
    home, away = score.get("home"), score.get("away")
    if home is None or away is None:
        return None
    text = f"{home}-{away}"
    pens = score.get("pens") or {}
    if pens.get("home") is not None and pens.get("away") is not None:
        text += f" ({pens['home']}-{pens['away']} pens)"
    return text


def _refresh_record_result(rec, score, source="provider", observed_at=None):
    """Refresh factual result metadata; never rewrite the locked prediction."""
    rendered = _score_string(score)
    if rendered is not None:
        previous = rec.get("result_snapshot")
        current = _score_snapshot(score, observed_at=observed_at, source=source)
        if previous and previous != current:
            history = rec.setdefault("result_corrections", [])
            comparable_previous = {k: v for k, v in previous.items() if k != "observed_at"}
            comparable_current = {k: v for k, v in current.items() if k != "observed_at"}
            if comparable_previous != comparable_current:
                history.append(previous)
        rec["score"] = rendered
        rec["result_snapshot"] = current


def _apply_scorecard_grade(rec, model_result, market_result):
    """Apply model and 1X2 market grades without touching the score string."""
    rec["model_result"] = model_result
    rec["result"] = model_result  # compatibility with the existing scorecard UI
    rec["model_hit"] = (rec.get("pick") == model_result)
    if market_result:
        rec["market_result"] = market_result
        rec["market_hit"] = (rec.get("market_pick") == market_result) if rec.get("market_pick") else None
        comparison_side = _market_comparison_side(rec)
        rec["market_comparison_hit"] = ((comparison_side == market_result)
                                        if comparison_side else None)
    else:
        # Never preserve a legacy ultimate-winner market grade when the actual
        # regulation settlement is unknown.
        rec["market_result"] = None
        rec["market_hit"] = None
        rec["market_comparison_hit"] = None
    if rec.get("upset_candidate"):
        rec["upset_hit"] = (rec.get("upset_candidate") == model_result)
    knockout = _is_advancement_fixture({}, rec)
    probs = (rec.get("advancement_probs") or {}) if knockout else (rec.get("regulation_probs") or rec.get("probs") or {})
    # Clear derived metrics before recomputing so a changed/corrected settlement
    # cannot retain an incompatible value from an earlier grade.
    rec["brier3"] = None
    rec["log_loss"] = None
    rec["brier_advancement"] = None
    rec["log_loss_advancement"] = None
    if knockout:
        if all(probs.get(k) is not None for k in ("h", "a")) and model_result in ("h", "a"):
            y = {"h": 1.0 if model_result == "h" else 0.0,
                 "a": 1.0 if model_result == "a" else 0.0}
            try:
                rec["brier_advancement"] = round(sum(
                    ((float(probs[k]) / 100.0) - y[k]) ** 2 for k in ("h", "a")), 3)
                rec["log_loss_advancement"] = round(
                    -math.log(max(0.001, float(probs[model_result]) / 100.0)), 3)
            except Exception:
                pass
    elif probs:
        y = {"h": 1.0 if model_result == "h" else 0.0,
             "d": 1.0 if model_result == "d" else 0.0,
             "a": 1.0 if model_result == "a" else 0.0}
        try:
            rec["brier3"] = round(sum(((float(probs.get(k) or 0) / 100.0) - y[k]) ** 2 for k in ("h", "d", "a")), 3)
            rec["log_loss"] = round(-math.log(max(0.001, float(probs.get(model_result) or 0) / 100.0)), 3)
        except Exception:
            pass
    if rec.get("value_side") and market_result:
        rec["value_hit"] = (rec.get("value_side") == market_result)
    elif rec.get("value_side"):
        rec["value_hit"] = None


def _refresh_record_clv(rec):
    """Recompute reproducible CLV, removing stale or ineligible stored values."""
    before = (rec.get("clv"), rec.get("closing_market_snapshot"),
              rec.get("closing_market_receipt"))
    side = _market_comparison_side(rec)
    eligible = (_lock_market_comparable(rec) and side in ("h", "d", "a")
                and rec.get("pick_mkt") is not None)
    close = receipt = None
    if eligible:
        close, receipt = _closing_market_from_ledger(rec)
        eligible = isinstance(close, dict) and close.get(side) is not None
    if eligible:
        rec["clv"] = round(float(close[side]) - float(rec["pick_mkt"]), 1)
        rec["closing_market_snapshot"] = close
        rec["closing_market_receipt"] = receipt
    else:
        rec.pop("clv", None)
        rec.pop("closing_market_snapshot", None)
        rec.pop("closing_market_receipt", None)
    after = (rec.get("clv"), rec.get("closing_market_snapshot"),
             rec.get("closing_market_receipt"))
    return before != after


def _refresh_market_comparison_grade(rec):
    """Backfill the regulation-side model grade on older locked receipts."""
    before = rec.get("market_comparison_hit")
    side = _market_comparison_side(rec)
    result = rec.get("market_result")
    rec["market_comparison_hit"] = ((side == result)
                                    if side in ("h", "d", "a") and result in ("h", "d", "a")
                                    else None)
    return before != rec.get("market_comparison_hit")

def update_scorecard(matches):
    """Lock a pick once the match is within LOCK_WINDOW_HOURS of kickoff, so
    the model can use as much pre-game information as possible (form, injuries,
    near-game market odds) right up to a fair cutoff; grade it once finished.
    Picks themselves are never rewritten after they lock — market-comparison
    fields backfill once odds appear if they weren't in yet at lock time.
    A fixture first seen after kickoff is never admitted to the official record."""
    picks = _load_picks()
    dirty = _quarantine_legacy_records(picks)
    expected_locks = set()
    expected_grades = set()
    by_fixture = defaultdict(list)
    for key, stored in picks.items():
        fixture_id = str(stored.get("fixture_id") or ("" if str(key).startswith("legacy:") else key))
        if fixture_id:
            by_fixture[fixture_id].append(stored)
    for m in matches:
        mid = str(m.get("id"))
        pr = m.get("prediction"); mk = (m.get("markets") or {}).get("1x2") or {}
        decision = _lock_decision(m)
        score = m.get("score") or {}
        if (m.get("status") == "FINISHED"
                and score.get("home") is not None and score.get("away") is not None
                and _record_is_official(picks.get(mid) or {})):
            expected_grades.add(mid)
        if pr and decision["state"] == "eligible":
            expected_locks.add(mid)
        should_lock = bool(pr and mid not in picks and decision["state"] == "eligible")
        if should_lock:
            prior_official = [
                stored for stored in picks.values()
                if isinstance(stored, dict) and _record_is_official(stored)
                and stored.get("result") in ("h", "d", "a")
            ]
            picks[mid] = _make_pick_record(m, pr, mk, decision, history=prior_official)
            by_fixture[mid].append(picks[mid])
            dirty = True
        elif (m.get("status") == "UPCOMING" and mid in picks and _record_is_official(picks[mid])
              and picks[mid].get("result") is None and picks[mid].get("market_pick") is None
              and mk.get("home_pct") is not None):
            # odds weren't available when this pick locked (fetch_odds() only runs
            # close to kickoff) — backfill the market-comparison fields now
            # that they exist. The pick itself (side/confidence) never changes.
            rec = picks[mid]
            locked_prediction = rec.get("prediction_snapshot") or {}
            market_pick, market_pct, value_side, value_edge, value_mkt = _market_fields(locked_prediction, mk)
            rec["market_pick"] = market_pick; rec["market_pct"] = market_pct
            comparison_pick = _market_comparison_side(rec)
            rec["pick_mkt"] = ({"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}.get(comparison_pick)
                                if mk.get("home_pct") is not None else None)
            rec["value_side"] = value_side; rec["value_edge"] = value_edge; rec["value_mkt"] = value_mkt
            rec["value_name"] = ({"h": rec["home"], "a": rec["away"], "d": "Draw"}.get(value_side) if value_side else None)
            rec["post_lock_market_snapshot"] = {"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}
            rec["market_backfilled_at"] = _utc_now().isoformat().replace("+00:00", "Z")
            rec["post_lock_market_receipt"] = {
                "source": mk.get("source") or "The Odds API consensus",
                "source_reference": mk.get("source_reference") or "https://the-odds-api.com/",
                "observed_at": mk.get("observed_at"),
                "recorded_at": rec["market_backfilled_at"], "snapshot_id": mk.get("snapshot_id"),
                "books": mk.get("books"), "spread": mk.get("spread")}
            dirty = True
        elif m.get("status") == "FINISHED" and mid in picks and picks[mid].get("result") is not None:
            # Keep previously graded picks aligned with the split settlement rule:
            # ultimate winner for knockout model picks, regulation for 1X2 markets.
            rec = picks[mid]
            model_res, market_res = _scorecard_results(m, rec)
            if model_res:
                before = (rec.get("score"), rec.get("result"), rec.get("market_result"),
                          rec.get("model_hit"), rec.get("market_hit"),
                          rec.get("value_hit"), rec.get("upset_hit"))
                _refresh_record_result(rec, m.get("score") or {})
                _apply_scorecard_grade(rec, model_res, market_res)
                after = (rec.get("score"), rec.get("result"), rec.get("market_result"),
                         rec.get("model_hit"), rec.get("market_hit"),
                         rec.get("value_hit"), rec.get("upset_hit"))
                if before != after:
                    DIAG.append(f"regraded model/market outcomes: {rec.get('home','?')} v {rec.get('away','?')} -> {model_res}/{market_res}")
                    dirty = True
        elif m.get("status") == "FINISHED" and mid in picks and picks[mid].get("result") is None:
            sc_obj = (m.get("score") or {})
            sh = sc_obj.get("home"); sa = sc_obj.get("away")
            if sh is None or sa is None:
                continue
            rec = picks[mid]
            model_res, market_res = _scorecard_results(m, rec)
            if not model_res:
                continue
            _refresh_record_result(rec, sc_obj)
            _apply_scorecard_grade(rec, model_res, market_res)
            dirty = True
    # Regrade every stored version of a provider-present fixture, including a
    # quarantined legacy entry that was moved out of the active fixture key.
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        mid = str(m.get("id"))
        score = m.get("score") or {}
        if score.get("home") is None or score.get("away") is None:
            continue
        for rec in by_fixture.get(mid, []):
            model_res, market_res = _scorecard_results(m, rec)
            if not model_res:
                continue
            before = (rec.get("score"), rec.get("result"), rec.get("market_result"),
                      rec.get("model_hit"), rec.get("market_hit"))
            _refresh_record_result(rec, score)
            _apply_scorecard_grade(rec, model_res, market_res)
            after = (rec.get("score"), rec.get("result"), rec.get("market_result"),
                     rec.get("model_hit"), rec.get("market_hit"))
            dirty = dirty or before != after
    # CLV availability can lag the first result fetch. Re-evaluate every graded
    # official receipt on every build and remove any value whose lock quote was
    # later marked backfilled/stale or can no longer be reproduced.
    for rec in picks.values():
        if _record_is_official(rec) and rec.get("result") in ("h", "d", "a"):
            dirty = _refresh_market_comparison_grade(rec) or dirty
            dirty = _refresh_record_clv(rec) or dirty
    if dirty:
        _save_picks(picks)
    # A successful fetch is allowed to deploy only if every fixture currently
    # inside the lock window exists both in memory and in the file just written.
    # This converts the historical silent "predictions visible, ledger absent"
    # state into a loud failed job that the scheduler retries.
    if expected_locks or expected_grades:
        persisted = _load_picks()
        missing = sorted(mid for mid in expected_locks
                         if not _record_is_official(picks.get(mid) or {})
                         or not _record_is_official(persisted.get(mid) or {}))
        if missing:
            raise RuntimeError("official pick lock persistence check failed: " + ", ".join(missing))
        ungraded = sorted(mid for mid in expected_grades
                          if (persisted.get(mid) or {}).get("result") not in ("h", "d", "a")
                          or not isinstance((persisted.get(mid) or {}).get("model_hit"), bool)
                          or not (persisted.get(mid) or {}).get("score"))
        if ungraded:
            raise RuntimeError("official pick grading persistence check failed: " + ", ".join(ungraded))
    # self-heal: correct any stored grading where a non-level scoreline was saved as
    # a draw (legacy corruption from penalty-inflated scores). Runs over ALL picks,
    # not just those in this fetch, so old rounds outside the fetch window get fixed.
    healed = False
    for _p in picks.values():
        _sc = str(_p.get("score") or "")
        if _p.get("result") == "d" and "-" in _sc and "pen" not in _sc.lower():
            try:
                _h, _a = (int(x) for x in _sc.split("(")[0].strip().split("-"))
            except Exception:
                continue
            if _h != _a:
                previous_result = _p.get("result")
                _p["result"] = "h" if _h > _a else "a"
                if "pick" in _p:
                    _p["model_hit"] = (_p.get("pick") == _p["result"])
                # A displayed ET score cannot reconstruct the 90-minute market
                # settlement, so preserve the existing market grade here. Current
                # fixtures are corrected above from their explicit regulation score.
                _p.setdefault("grading_corrections", []).append({
                    "field": "result",
                    "previous": previous_result,
                    "corrected": _p["result"],
                    "reason": "non-level scoreline mis-graded as draw (legacy penalty-inflated score)",
                    "corrected_at": _utc_now().isoformat().replace("+00:00", "Z"),
                })
                healed = True
    if healed:
        _save_picks(picks)
        DIAG.append("scorecard: healed legacy draw mis-gradings")
    ledger_state = forecast_ledger.sync_pick_records(
        _forecast_ledger_path(), picks.values(), COMP_KEY
    )
    if ledger_state.get("appended"):
        DIAG.append(f"forecast ledger: appended {ledger_state['appended']} event(s)")
    official = [p for p in picks.values() if _record_is_official(p)]
    quarantined = [p for p in picks.values() if not _record_is_official(p)]
    graded = [p for p in official if p.get("result")]
    # Some quarantined receipts retain a historical result for auditability but
    # do not describe a verifiable event target. In particular, an old UCL
    # per-leg "advancement" pick cannot be settled from that leg's result. Keep
    # those rows visible, but never let them enter any accuracy denominator.
    non_gradable_reasons = {"legacy_ucl_advancement_target_unverifiable"}
    non_gradable = [p for p in quarantined
                    if p.get("quarantine_reason") in non_gradable_reasons]
    legacy_graded = [p for p in quarantined if p.get("result")
                     and p.get("quarantine_reason") not in non_gradable_reasons]
    mk_graded = [p for p in graded if p.get("market_hit") is not None
                 and p.get("market_comparison_hit") is not None
                 and _lock_market_comparable(p)]
    later_market_graded = [p for p in graded if p.get("market_hit") is not None and not _lock_market_comparable(p)]
    disagree = [p for p in mk_graded if p.get("market_pick")
                and _market_comparison_side(p) != p.get("market_pick")]
    rows = []
    for source in sorted(picks.values(), key=lambda p: p.get("kickoff") or "", reverse=True):
        row = _json_safe(source)
        if not _record_is_official(source):
            incompatible = source.get("quarantine_reason") in non_gradable_reasons
            row["stage"] = f"{'Excluded/unverifiable' if incompatible else 'Legacy/unverified'} · {row.get('stage') or 'Fixture'}"
            row["integrity_label"] = ("advancement target cannot be verified — excluded from every accuracy total"
                                      if incompatible else
                                      "no provable pregame timestamp — counted in the all-time total, excluded from the verified record")
            row["legacy"] = True
        rows.append(row)
    probability_metrics = _probability_metric_summary(graded)
    # Score every genuine market underdog identified by the locked receipt,
    # not only the exceptionally narrow subset that fired the live radar.
    # Requiring `radar` here left the scorecard empty even while the ledger
    # contained settled underdog forecasts. Pick'ems and unknown markets stay
    # excluded by the immutable classification captured at lock time.
    upset_watched = [p for p in graded if p.get("upset_candidate")
                     and (p.get("upset_snapshot") or {}).get("class")
                     in ("minor", "solid", "major")]
    upset_triggered = [p for p in upset_watched if p.get("upset_triggered")]
    # calibration bands: stated confidence vs actual hit rate
    bands = [("<50", 0, 50), ("50-60", 50, 60), ("60-70", 60, 70),
             ("70-80", 70, 80), ("80-90", 80, 90), ("90+", 90, 101)]
    calib = []
    for lbl, lo, hi in bands:
        grp = [p for p in graded if lo <= (p.get("confidence") or 0) < hi]
        if grp: calib.append({"band": lbl, "n": len(grp), "hits": sum(1 for p in grp if p.get("model_hit"))})
    # home vs. away: hit rate when the pick was the home side vs. the away side
    home_picks = [p for p in graded if p.get("pick") == "h"]
    away_picks = [p for p in graded if p.get("pick") == "a"]
    home_away = {"home": {"n": len(home_picks), "hits": sum(1 for p in home_picks if p.get("model_hit"))},
                 "away": {"n": len(away_picks), "hits": sum(1 for p in away_picks if p.get("model_hit"))}}
    # Agreement is settlement-aware and avoids inventing an "underdog" label
    # for 3-way draws or pick'em markets. Later/backfilled quotes are excluded.
    market_agreement = _market_agreement_split(mk_graded)
    clvs = [p["clv"] for p in graded if p.get("clv") is not None]
    vals = [p for p in mk_graded if p.get("value_side")]
    chances = [p for p in vals if _is_value_chance(p)]
    def _vs(grp):
        return {"n": len(grp), "hits": sum(1 for p in grp if p.get("value_hit")),
                "be": round(sum(p.get("value_mkt") or 0 for p in grp)/len(grp)) if grp else None}
    # signal quality: when a factor favored our pick, did the pick hit?
    signal_quality = {k: _signal_quality(graded, k) for k in
                      ("class", "market_power", "form", "gd", "rest", "pts", "record", "margin", "rank", "srs", "elo")}
    # error review: recent misses with their captured evidence
    misses = [{"home": p.get("home"), "away": p.get("away"), "pick": p.get("pick"),
               "score": p.get("score"), "upset": (p.get("upset_snapshot") or {}).get("candidate"),
               "gap": p.get("market_gap")}
              for p in sorted(graded, key=lambda x: x.get("kickoff") or "", reverse=True)
              if not p.get("model_hit")][:10]
    value_summary = {"all": _vs(vals), "chances": _vs(chances),
                      "pending": _pending_value_count(official)}
    upset_summary = {
        "watched": len(upset_watched),
        "hits": sum(1 for p in upset_watched if p.get("upset_hit")),
        "triggered": len(upset_triggered),
        "triggered_hits": sum(1 for p in upset_triggered if p.get("upset_hit")),
        "avg_score": round(sum(float(p.get("upset_score") or 0) for p in upset_watched)/len(upset_watched), 1) if upset_watched else None
    }
    _mh = sum(1 for p in graded if p.get("model_hit"))
    DIAG.append(f"scorecard record: {_mh}/{len(graded)} model hits")
    legacy_hits = sum(1 for p in legacy_graded if p.get("model_hit"))
    legacy_market = [p for p in legacy_graded if p.get("market_hit") is not None]
    # Combined "all-time" tally = verified pregame-locked picks + legacy/
    # migrated picks that have a real graded result. This is deliberately
    # kept separate from `graded`/`model_hits` above (the strict, official,
    # leakage-safe number _record_is_official() gates) rather than folding
    # legacy picks into it -- an independent audit found the legacy cluster
    # includes picks migrated from local test-machine history with no
    # recoverable proof of pregame timing, so they can't honestly be
    # relabeled "verified". This total exists purely for transparency: shown
    # separately, clearly labeled, so the public record isn't silently
    # padded with unverifiable picks even when they happen to be accurate.
    combined_graded = len(graded) + len(legacy_graded)
    combined_hits = _mh + legacy_hits
    return {"record_scope": "verified_pregame_picks_only",
            "graded": len(graded), "pending": len(official) - len(graded),
            "model_hits": _mh,
            "combined": {"graded": combined_graded, "model_hits": combined_hits,
                         "accuracy": round(combined_hits / combined_graded * 100, 1) if combined_graded else None,
                         "verified_graded": len(graded), "verified_hits": _mh,
                         "legacy_graded": len(legacy_graded), "legacy_hits": legacy_hits,
                         "note": "Includes legacy/migrated picks without recoverable proof of pregame "
                                 "timing alongside verified pregame-locked picks. See the pick log below "
                                 "for which is which."},
            "quarantined": {"total": len(quarantined), "graded": len(legacy_graded),
                            "pending": sum(1 for p in quarantined if not p.get("result")),
                            "model_hits": legacy_hits,
                            "label": "Legacy/unverified — excluded from official record"},
            "excluded": len(non_gradable),
            "legacy": {"graded": len(legacy_graded), "model_hits": legacy_hits,
                       "accuracy": round(legacy_hits / len(legacy_graded) * 100, 1) if legacy_graded else None,
                       "market_graded": len(legacy_market),
                       "market_hits": sum(1 for p in legacy_market if p.get("market_hit"))},
            "market_graded": len(mk_graded),
            "market_hits": sum(1 for p in mk_graded if p.get("market_hit")),
            "post_lock_market_graded": len(later_market_graded),
            "post_lock_market_hits": sum(1 for p in later_market_graded if p.get("market_hit")),
            "disagree": len(disagree),
            "disagree_hits": sum(1 for p in disagree if p.get("market_comparison_hit")),
            **probability_metrics,
            "calibration": calib,
            "home_away": home_away,
            "market_agreement": market_agreement,
            "clv_n": len(clvs), "clv_avg": round(sum(clvs)/len(clvs), 1) if clvs else None,
            "clv_beat": sum(1 for c in clvs if c > 0),
            "value": value_summary, "signal_quality": signal_quality, "misses": misses, "upset": upset_summary,
            "picks": rows[:80]}


def build_ncaam_bracketology(standings_payload):
    """Create Matchday's transparent 68-team projection from raw results.

    This intentionally does not ingest ESPN bracketology. ESPN is only the
    transport for records and scoring data. The beta score will be eligible for
    a "calibrated" label only after historical tournament backtesting exists.
    """
    if COMP_KEY != "NCAAM":
        return None

    def team_score(row):
        games = max(1, int(row.get("pld") or 0))
        win_pct = float(row.get("win_pct") if row.get("win_pct") is not None
                        else (row.get("w") or 0) / games)
        conf_pct = float(row.get("league_win_pct") if row.get("league_win_pct") is not None else win_pct)
        margin = float(row.get("avg_pf") or 0) - float(row.get("avg_pa") or 0)
        if not margin:
            margin = float(row.get("gd") or 0)
        margin_norm = max(0.0, min(1.0, (margin + 15.0) / 30.0))
        return round(100.0 * (0.55 * win_pct + 0.25 * conf_pct + 0.20 * margin_norm), 1)

    conferences = []
    all_rows = []
    seen = set()
    for group in standings_payload or []:
        name = group.get("group") or "Conference"
        rows = []
        for raw in group.get("teams") or []:
            key = norm(raw.get("name"))
            if not key or key in seen or not (raw.get("pld") or 0):
                continue
            seen.add(key)
            row = dict(raw)
            row["conference"] = name
            row["model_score"] = team_score(row)
            rows.append(row)
            all_rows.append(row)
        if rows:
            rows.sort(key=lambda r: (-r["model_score"], -(r.get("w") or 0)))
            conferences.append((name, rows))
    if len(all_rows) < 68:
        DIAG.append(f"bracketology: only {len(all_rows)} eligible teams")
        return None

    auto = [rows[0] for _, rows in conferences]
    auto_keys = {norm(r.get("name")) for r in auto}
    remaining = sorted((r for r in all_rows if norm(r.get("name")) not in auto_keys),
                       key=lambda r: (-r["model_score"], -(r.get("w") or 0)))
    at_large = remaining[:max(0, 68 - len(auto))]
    bubble = remaining[max(0, 68 - len(auto)):max(0, 68 - len(auto)) + 8]

    for row in auto:
        row["bid"] = "Auto"
    for row in at_large:
        row["bid"] = "At-large"
    field = sorted(auto + at_large, key=lambda r: (-r["model_score"], -(r.get("w") or 0)))[:68]

    ff_auto = sorted(auto, key=lambda r: r["model_score"])[:4]
    ff_at_large = sorted(at_large, key=lambda r: r["model_score"])[:4]

    def pair_four(rows, kind):
        rows = sorted(rows, key=lambda r: r["model_score"])
        pairs = [(rows[0], rows[3]), (rows[1], rows[2])] if len(rows) >= 4 else []
        games, placeholders = [], []
        for i, (a, b) in enumerate(pairs, 1):
            pid = f"{kind.lower().replace('-', '')}-{i}"
            placeholders.append({"placeholder": True, "id": pid,
                                 "name": f"{a['name']} / {b['name']}",
                                 "code": "FF", "record": "First Four",
                                 "conference": "Play-in", "bid": "First Four",
                                 "model_score": round((a["model_score"] + b["model_score"]) / 2, 1)})
            games.append({"id": pid, "kind": kind, "teams": [a, b]})
        return games, placeholders

    auto_games, auto_slots = pair_four(ff_auto, "Automatic bids")
    at_games, at_slots = pair_four(ff_at_large, "At-large bids")
    first_four = auto_games + at_games
    first_four_keys = {norm(t.get("name")) for g in first_four for t in g["teams"]}
    direct = [r for r in field if norm(r.get("name")) not in first_four_keys]
    slots = sorted(direct + auto_slots + at_slots, key=lambda r: -r["model_score"])

    regions = {name: [] for name in ("East", "West", "South", "Midwest")}
    region_names = list(regions)
    slot_lookup = {}
    for i, row in enumerate(slots[:64]):
        seed = i // 4 + 1
        order = region_names if seed % 2 else list(reversed(region_names))
        region = order[i % 4]
        item = {"seed": seed, "name": row.get("name"), "code": row.get("code") or "",
                "record": row.get("record") or f"{row.get('w', 0)}-{row.get('l', 0)}",
                "conference": row.get("conference") or "", "bid": row.get("bid") or "At-large",
                "model_score": row.get("model_score")}
        regions[region].append(item)
        if row.get("placeholder"):
            slot_lookup[row["id"]] = {"seed": seed, "region": region}
    for game in first_four:
        game.update(slot_lookup.get(game["id"], {}))
        game["teams"] = [{"name": t.get("name"), "code": t.get("code") or "",
                          "record": t.get("record") or f"{t.get('w', 0)}-{t.get('l', 0)}",
                          "conference": t.get("conference") or "", "model_score": t.get("model_score")}
                         for t in game["teams"]]

    last_four_byes = sorted((r for r in at_large if norm(r.get("name")) not in first_four_keys),
                            key=lambda r: r["model_score"])[:4]
    slim = lambda r: {"name": r.get("name"), "code": r.get("code") or "",
                      "record": r.get("record") or f"{r.get('w', 0)}-{r.get('l', 0)}",
                      "conference": r.get("conference") or "", "model_score": r.get("model_score")}
    DIAG.append(f"bracketology: {len(auto)} auto + {len(at_large)} at-large = {len(field)} teams")
    return {
        "version": "beta-0.1", "field_size": len(field),
        "methodology": "55% overall win rate · 25% conference win rate · 20% adjusted scoring margin",
        "source_note": "Matchday projection from raw team results; no editorial bracket feed",
        "regions": regions, "first_four": first_four,
        "last_four_byes": [slim(r) for r in last_four_byes],
        "first_four_out": [slim(r) for r in bubble[:4]],
        "next_four_out": [slim(r) for r in bubble[4:8]],
    }


def _pro_standings_pct(team):
    played = max(1.0, float(team.get("pld") or 0))
    return (float(team.get("w") or 0) + 0.5 * float(team.get("d") or 0)) / played


def _matchday_top_25(tables):
    """Rank college teams by Matchday's own public power-rating signal.

    This is deliberately independent of the provider poll. The rating already
    blends the preseason class/talent prior, self-training Elo, and current
    season results with sample-size-aware weights.
    """
    teams = [dict(team) for table in tables or []
             if table.get("table_type") not in {"official_poll", "matchday_top_25"}
             for team in table.get("teams") or []]
    seen, unique = set(), []
    for team in teams:
        key = norm(team.get("name"))
        if key and key not in seen and not is_placeholder_team_name(team.get("name")):
            seen.add(key)
            unique.append(team)
    # Keep the established power rating as the backbone, then let current-
    # season opponent-adjusted SRS claim up to 25% of the ordering as its
    # sample grows. Rank-normalizing both signals avoids mixing Elo/rating and
    # point-margin units directly. Before games are played, SRS has zero
    # weight and the preseason list remains fully reproducible.
    def percentile_ranks(rows, value):
        ordered = sorted(rows, key=lambda team: (-float(value(team) or 0),
                                                  str(team.get("name") or "")))
        count = max(1, len(ordered) - 1)
        return {norm(team.get("name")): (len(ordered) - 1 - index) / count
                for index, team in enumerate(ordered)}

    rating_pct = percentile_ranks(unique, lambda team: team.get("rating"))
    srs_teams = [team for team in unique if int(team.get("srs_games") or 0) > 0]
    srs_pct = percentile_ranks(srs_teams, lambda team: team.get("srs"))
    for team in unique:
        key = norm(team.get("name"))
        srs_weight = (0.25 * min(1.0, int(team.get("srs_games") or 0) / 12.0)
                      if key in srs_pct else 0.0)
        team["ranking_score"] = round(
            rating_pct.get(key, 0.0) * (1.0 - srs_weight)
            + srs_pct.get(key, 0.0) * srs_weight, 6)
    unique.sort(key=lambda team: (-float(team.get("ranking_score") or 0),
                                  str(team.get("name") or "")))
    rows = unique[:25]
    for rank, team in enumerate(rows, 1):
        team["pos"] = rank
    return {"group": "Matchday Top 25", "table_type": "matchday_top_25",
            "projection_current": True, "teams": rows}


def compute_us_sport_standings(matches):
    """Derive win-loss(-tie) records, point differential and recent form
    directly from finished game results. Used when the provider's free tier
    doesn't expose a standings endpoint (BallDontLie) -- same `pts = wins*3 +
    ties` scale the API-Sports adapter used, so predict()'s strength formula
    behaves the same regardless of which provider is actually active. No
    provider's result rows do not include division metadata; fixed pro-league
    structure is applied later by _group_us_pro_standings()."""
    T = defaultdict(lambda: {"name": "", "w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0, "results": []})
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        sc = m.get("score") or {}
        hs, as_ = sc.get("home"), sc.get("away")
        if hs is None or as_ is None:
            continue
        # Second line of defence behind the provider boundary: cached game
        # files written by an earlier build can still hold placeholder-named
        # sides, and crediting one invents a team in the standings table
        # (see PLACEHOLDER_TEAM_NAMES in provider_adapters).
        if any(is_placeholder_team_name((m.get(side) or {}).get("name"))
               for side in ("home", "away")):
            continue
        for side, pf, pa in ((m["home"], hs, as_), (m["away"], as_, hs)):
            key = norm(side.get("name"))
            if not key:
                continue
            r = T[key]
            r["name"] = side.get("name")
            r["code"] = side.get("code") or r.get("code") or ""
            r["pf"] += pf; r["pa"] += pa
            if pf > pa: r["w"] += 1; res = "W"
            elif pf < pa: r["l"] += 1; res = "L"
            else: r["t"] += 1; res = "T"
            r["results"].append((m.get("kickoff") or "", res))
    model = {}
    for key, r in T.items():
        r["results"].sort(key=lambda x: x[0])
        played = r["w"] + r["l"] + r["t"]
        model[key] = {"name": r["name"], "code": r.get("code") or "", "pld": played, "w": r["w"], "l": r["l"], "d": r["t"],
                      "gf": r["pf"], "ga": r["pa"], "gd": r["pf"] - r["pa"], "pts": r["w"] * 3 + r["t"],
                      "form": " ".join(res for _, res in r["results"][-5:]), "group": "", "pos": None,
                      "rating": round(power_rating(r["name"], {"pld": played, "w": r["w"], "l": r["l"], "d": r["t"]}), 2)}
    ranked = sorted(model.values(), key=lambda rec: (-_pro_standings_pct(rec), -rec["gd"]))
    for i, rec in enumerate(ranked, 1):
        rec["pos"] = i
    tables = [{"group": "", "teams": ranked}] if ranked else []
    return model, tables


def fetch_college_bundle():
    """Fetch licensed college data with a quota-safe, resilient local cache."""
    if COMP_KEY == "NCAAF":
        adapter = CollegeFootballDataAdapter(CFBD_KEY)
        provider_name = "CollegeFootballData"
    else:
        adapter = CollegeBasketballDataAdapter(CBBD_KEY)
        provider_name = "CollegeBasketballData"
    # Bumped v4 -> v5 2026-07-26: this cache blob embeds adapter.rankings()'s
    # already-computed result (see below), not just raw provider data. CBBD's
    # rankings() changed from a raw win-percent sort to a real AP Top 25 pull
    # the same day -- an in-window (COLLEGE_CACHE_MIN, 8h) cached blob from
    # before that fix, restored via CI's actions/cache step, kept serving the
    # OLD computed ranking (the "Miami OH is #1" bug) for the entire TTL
    # AFTER the fix was already live and deployed, because this file's own
    # freshness check has nothing to do with when the code last changed.
    # Bumped v5 -> v6 same day: rankings() itself changed again (a real
    # preseason/current poll now beats an off-season fallback to an already-
    # finished season's final poll -- confirmed live NCAAF's Week 1 2026
    # season hasn't started yet, so this now correctly returns a real
    # talent-based "Preseason" projection led by Alabama/Georgia/Ohio State
    # instead of last season's CFP field). Changing the filename is what
    # actually invalidates it; bump this suffix again any time this bundle's
    # cached CONTENT (not just its raw inputs) changes shape or computation.
    # Bumped v6 -> v7 2026-07-27: both NCAAF and NCAAM way-too-early lists now
    # blend the prior final poll with recruiting/roster talent instead of using
    # recruiting alone. The cached ranking must be recomputed immediately.
    # Bumped v7 -> v8 2026-08-23: poll rows now retain their real poll name so
    # the UI can show AP/CFP separately from Matchday's model Top 25.
    cache_file = f"college_{COMP_KEY.lower()}_bundle_v8_cache.json"
    bundle = None
    try:
        if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < COLLEGE_CACHE_MIN * 60:
            with open(cache_file, encoding="utf-8") as handle:
                bundle = json.load(handle)
            DIAG.append(f"{provider_name}: local cache")
    except Exception:
        bundle = None
    if bundle is None:
        try:
            all_matches = adapter.schedule()
            st, tables = adapter.standings()
            ranks, projection = adapter.rankings(tables)
            bundle = {"matches": all_matches, "standings_model": st, "tables": tables,
                      "rankings": ranks, "projection": projection}
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(bundle, handle, ensure_ascii=False)
            os.replace(tmp, cache_file)
        except ProviderError:
            # Preserve the last successful launch payload through a quota or provider outage.
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as handle:
                    bundle = json.load(handle)
                DIAG.append(f"{provider_name}: stale cache after provider limit/error")
            else:
                # No bundle cache either: rebuild from the last published payload
                # rather than raising, which froze data_ncaaf.json for ten days in
                # September 2026 (see schedule_fallback.py).
                import schedule_fallback
                bundle = schedule_fallback.last_good_bundle(COMP_KEY) if COMP_KEY == "NCAAF" else None
                if bundle is None:
                    raise
                DIAG.append(f"{provider_name}: provider unavailable and no bundle cache; "
                            f"rebuilt from the last published payload "
                            f"({len(bundle['matches'])} fixtures, {len(bundle.get('history') or [])} "
                            f"engine results as history)")
            bundle["_stale"] = True
    all_matches = bundle.get("matches") or []
    normalize_match_results(all_matches)
    # A cached bundle never learns a result, and CFBD's quota can be spent for
    # weeks. Final scores only, for fixtures already on this schedule -- see
    # score_fallback.py and the 2026-09-12 amendment in PROVIDER_COMPLIANCE.md.
    if COMP_KEY == "NCAAF":
        try:
            import score_fallback
            filled = score_fallback.settle(all_matches, COMP_KEY)
            DIAG.append(f"final-score fallback: settled {filled['settled']} of "
                        f"{filled['candidates']} past fixture(s) across {filled['days']} day(s)"
                        + (f"; {len(filled['errors'])} day(s) failed" if filled["errors"] else ""))
        except Exception as exc:
            DIAG.append(f"final-score fallback: skipped ({exc})")
        # A stale schedule also keeps the kickoff times it had when it froze --
        # often the placeholder used before a time is announced.
        if bundle.get("_stale"):
            try:
                import schedule_fallback
                moved = schedule_fallback.refresh_kickoffs(all_matches, COMP_KEY)
                DIAG.append(f"kickoff-time fallback: updated {moved['updated']} of "
                            f"{moved['candidates']} upcoming fixture(s) across {moved['days']} day(s)"
                            + (f"; {len(moved['errors'])} day(s) failed" if moved["errors"] else ""))
            except Exception as exc:
                DIAG.append(f"kickoff-time fallback: skipped ({exc})")
    # Retain the complete licensed season only in memory for local aggregate
    # model training; the public dashboard still receives the bounded window.
    adapter._model_history = all_matches + list(bundle.get("history") or [])
    st = {norm(name): row for name, row in (bundle.get("standings_model") or {}).items()}
    tables = bundle.get("tables") or []
    adapter._cached_rankings = (bundle.get("rankings") or [], bundle.get("projection"))
    now = datetime.datetime.now(datetime.timezone.utc)
    past, future = [], []
    for match in all_matches:
        try:
            kickoff = datetime.datetime.fromisoformat((match.get("kickoff") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        (past if kickoff <= now else future).append((kickoff, match))
    # Keep the dashboard responsive: enough recent context plus the nearest slate,
    # while standings and projections still use the complete season bundle.
    # A 160-fixture window is barely two weeks of college football (Week 1 alone
    # is ~99 FBS games), which is why the published slate kept stopping at Week
    # 2. Roughly a month of scheduled games is a far more useful horizon, and a
    # fixture serializes to ~2KB that gzips heavily, so this stays a modest
    # transfer cost for a much larger published schedule.
    future_window = {"NCAAF": 420, "NCAAM": 300}.get(COMP_KEY, 160)
    matches = [match for _, match in sorted(past, key=lambda item: item[0])[-40:]]
    matches += [match for _, match in sorted(future, key=lambda item: item[0])[:future_window]]
    matches.sort(key=lambda match: match.get("kickoff") or "")
    try:
        history = fetch_college_season_history(adapter, provider_name, all_matches)
        applied = apply_season_history(history, st, tables)
        DIAG.append(f"{provider_name} history: applied to {applied} standings rows")
    except Exception as exc:
        # A thin sample is a degraded prediction, not a broken build.
        DIAG.append(f"{provider_name} history: skipped ({exc})")
    DIAG.append(f"{provider_name} fixtures: {len(matches)} in display window ({len(all_matches)} season total)")
    DIAG.append(f"{provider_name} standings: {sum(len(g.get('teams') or []) for g in tables)} teams")
    return adapter, matches, st, tables


COLLEGE_HISTORY_SEASONS = 3   # the season in progress plus two completed ones


def fetch_college_season_history(adapter, provider_name, current_matches):
    """Recency-weighted multi-season form for the current college field.

    A college football season is 12-13 games and a college basketball season
    ~30, so a single season is a thin basis for record and scoring-margin --
    and in the weeks before a season opens there is no sample at all, which is
    exactly when the schedule is full of games people want a read on.

    Completed seasons are immutable, so each one is fetched at most once ever
    and kept in a cache with no TTL. Only the season in progress comes from
    this run's live schedule. That keeps the ongoing provider cost at zero
    extra requests per build once the cache is warm -- worth stating plainly
    because CBBD charges four windowed requests per season (see
    CollegeBasketballDataAdapter._season_rows).
    """
    cache_file = f"college_{COMP_KEY.lower()}_history_cache.json"
    try:
        with open(cache_file, encoding="utf-8") as handle:
            cached = json.load(handle)
    except Exception:
        cached = {}
    if not isinstance(cached, dict):
        cached = {}
    seasons = [(adapter.season, season_form_from_matches(current_matches))]
    fetched = []
    for offset in range(1, COLLEGE_HISTORY_SEASONS):
        year = adapter.season - offset
        key = str(year)
        if key in cached:
            seasons.append((year, cached[key]))
            continue
        try:
            agg = season_form_from_matches(adapter.historical_matches(year))
        except ProviderError as exc:
            DIAG.append(f"{provider_name} history: {year} unavailable ({exc})")
            continue
        except Exception as exc:
            DIAG.append(f"{provider_name} history: {year} failed ({exc})")
            continue
        if not agg:
            # Distinguish "provider has no data for this year" from a failure:
            # don't cache an empty year, or a provider gap becomes permanent.
            DIAG.append(f"{provider_name} history: {year} returned no completed games")
            continue
        cached[key] = agg
        fetched.append(year)
        seasons.append((year, agg))
    if fetched:
        try:
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(cached, handle, ensure_ascii=False)
            os.replace(tmp, cache_file)
        except Exception as exc:
            DIAG.append(f"{provider_name} history: cache write failed ({exc})")
    history = blend_season_history(seasons)
    covered = sorted((year for year, agg in seasons if agg), reverse=True)
    wanted = COLLEGE_HISTORY_SEASONS
    if fetched:
        source = f"fetched {fetched}"
    elif len(covered) >= wanted:
        source = "cache warm"
    else:
        # Saying "cache warm" here hid the fact that prior seasons were missing
        # because the provider refused them, which is the difference between a
        # deep sample and today's single-season one.
        source = f"only {len(covered)}/{wanted} seasons available"
    DIAG.append(f"{provider_name} history: {len(history)} teams across seasons {covered} ({source})")
    return history


def apply_season_history(history, standings_model, tables):
    """Attach the multi-season summary to every standings row that has one."""
    applied = 0
    rows = list((standings_model or {}).values())
    for table in tables or []:
        rows.extend(table.get("teams") or [])
    for row in rows:
        entry = history.get(str(row.get("name") or "").lower())
        if not entry:
            continue
        row["multi_win_pct"] = entry["multi_win_pct"]
        row["multi_margin"] = entry["multi_margin"]
        row["multi_games"] = entry["multi_games"]
        row["multi_seasons"] = entry["multi_seasons"]
        applied += 1
    return applied


def fetch_college_leaders(adapter, provider_name):
    """Cache CFBD/CBBD season player-stat leaders separately from the schedule bundle.

    adapter.leaders() pulls the whole league's player-season stats in one
    request -- cheap in call count (matches talent()/recruiting()'s per-run
    budget) but not in bytes, so it gets its own long-lived cache
    (COLLEGE_LEADERS_CACHE_MIN) instead of riding the 8-hour schedule
    bundle's TTL, and a provider outage/quota hit falls back to the last
    good leaders payload rather than blanking the panel.
    """
    cache_file = f"college_{COMP_KEY.lower()}_leaders_cache.json"
    leaders = None
    try:
        if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < COLLEGE_LEADERS_CACHE_MIN * 60:
            with open(cache_file, encoding="utf-8") as handle:
                leaders = json.load(handle)
            DIAG.append(f"{provider_name} leaders: local cache")
    except Exception:
        leaders = None
    if leaders is None:
        try:
            leaders = adapter.leaders()
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(leaders, handle, ensure_ascii=False)
            os.replace(tmp, cache_file)
            count = sum(len(c.get("leaders") or []) for c in (leaders.get("categories") or []))
            DIAG.append(f"{provider_name} leaders: fetched {count} leaderboard entries across "
                        f"{len(leaders.get('categories') or [])} categories")
        except ProviderError as exc:
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as handle:
                    leaders = json.load(handle)
                DIAG.append(f"{provider_name} leaders: stale cache after provider limit/error — {_scrub(exc)}")
            else:
                DIAG.append(f"{provider_name} leaders unavailable: {_scrub(exc)}")
                leaders = {}
    return leaders


def _sportsdataio_cache_identity(match):
    return {
        "fixture_id": str(match.get("id") or ""),
        "kickoff": match.get("kickoff"),
        "home": {"name": (match.get("home") or {}).get("name"),
                 "code": (match.get("home") or {}).get("code")},
        "away": {"name": (match.get("away") or {}).get("name"),
                 "code": (match.get("away") or {}).get("code")},
    }


def _merge_sportsdataio_cached_pregame(match, row, *, stale=False):
    """Restore cached detail while failing confirmation closed.

    Confirmation survives only a fresh cache row bound to the exact fixture,
    with both lineup sides present and (for MLB) both starting pitchers
    explicitly confirmed. Older cache shapes remain usable as unconfirmed
    research detail but can never open a readiness gate.
    """
    if not isinstance(row, dict):
        return
    detached = _json_safe(row)
    exact_fixture = detached.get("fixture_identity") == _sportsdataio_cache_identity(match)
    lineups = detached.get("lineups") if isinstance(detached.get("lineups"), dict) else None
    personnel = detached.get("personnel") if isinstance(detached.get("personnel"), dict) else {}
    schedule_matches = bool(
        lineups and _parse_kickoff(lineups.get("scheduled_at"))
        and _parse_kickoff(lineups.get("scheduled_at")) == _parse_kickoff(match.get("kickoff")))
    sides_confirmed = bool(lineups and all(
        isinstance(lineups.get(side), dict)
        and bool((lineups.get(side) or {}).get("xi"))
        and (lineups.get(side) or {}).get("confirmed") is True
        for side in ("home", "away")))
    pitchers_confirmed = True
    if str(COMP_KEY).upper() == "MLB":
        pitchers = personnel.get("starting_pitchers") or {}
        pitchers_confirmed = all(
            isinstance(pitchers.get(side), dict)
            and pitchers[side].get("confirmed") is True
            for side in ("home", "away"))
    confirmed = bool(not stale and exact_fixture and schedule_matches
                     and sides_confirmed and pitchers_confirmed)
    if lineups:
        lineups["confirmed"] = confirmed
        for side in ("home", "away"):
            if isinstance(lineups.get(side), dict):
                lineups[side]["confirmed"] = confirmed
                if not confirmed:
                    for player in lineups[side].get("xi") or []:
                        if isinstance(player, dict):
                            player["confirmed"] = False
        match["lineups"] = lineups
    if personnel:
        for key in list(personnel):
            if key.endswith("_confirmed"):
                personnel[key] = bool(personnel[key] and confirmed)
        for group in ("starting_pitchers", "starting_goalies"):
            for item in (personnel.get(group) or {}).values():
                if isinstance(item, dict) and not confirmed:
                    item["confirmed"] = False
        # Merge, do not replace. This overlay runs after the SportsGameOdds
        # overlay and the bullpen-rest proxy, so assigning the cached dict
        # wholesale silently dropped starter_candidates, market_listed_hitters
        # and bullpen from every fixture the licensed cache also covered.
        match.setdefault("personnel", {}).update(personnel)
    if detached.get("injuries_shadow"):
        match["injuries_shadow"] = detached["injuries_shadow"]
    provenance = list(detached.get("pregame_provenance") or [])
    provenance.append({"input": "cached_pregame_confirmation", "source": "SportsDataIO",
                       "confirmed": confirmed,
                       "status": "stale_cache" if stale else
                                 "exact_fixture_cache" if exact_fixture else "identity_unverified_cache"})
    match["pregame_provenance"] = provenance


def fetch_sportsdataio_pregame_overlay(matches):
    """Add licensed late information without replacing each sport's fixture feed.

    Only fixtures inside 72 hours are sent through the overlay.  A normalized
    cache avoids repeatedly spending provider quota and is safe to restore in
    CI because it contains derived fields, never the API key.
    """
    if COMP_KEY not in {"NFL", "NBA", "MLB", "NHL", "NCAAF", "NCAAM"}:
        return {"injuries": 0, "lineups": 0}
    if not SPORTSDATAIO_PREGAME_ENABLED:
        DIAG.append("pregame overlay: disabled until a live redistribution tier is confirmed")
        return {"injuries": 0, "lineups": 0}
    if not SPORTSDATAIO_KEY or "PASTE_" in str(SPORTSDATAIO_KEY):
        DIAG.append("pregame overlay: SportsDataIO key not configured")
        return {"injuries": 0, "lineups": 0}
    now = datetime.datetime.now(datetime.timezone.utc)
    near = []
    for match in matches:
        kickoff = _parse_kickoff(match.get("kickoff"))
        if match.get("status") == "UPCOMING" and kickoff:
            hours = (kickoff - now).total_seconds() / 3600
            if 0 <= hours <= 72:
                near.append(match)
    if not near:
        DIAG.append("pregame overlay: no upcoming fixture inside 72h")
        return {"injuries": 0, "lineups": 0}

    cached = None
    cached_is_stale = False
    try:
        if (os.path.exists(SPORTSDATAIO_PREGAME_CACHE_FILE) and
                time.time() - os.path.getmtime(SPORTSDATAIO_PREGAME_CACHE_FILE) <
                SPORTSDATAIO_PREGAME_CACHE_MIN * 60):
            with open(SPORTSDATAIO_PREGAME_CACHE_FILE, encoding="utf-8") as handle:
                cached = json.load(handle)
    except Exception:
        cached = None
    if cached is None:
        try:
            result = SportsDataIOAdapter(SPORTSDATAIO_KEY, COMP_KEY).attach_pregame(near)
            cached = {str(match.get("id")): {
                key: match.get(key) for key in
                ("injuries_shadow", "lineups", "personnel", "pregame_provenance")
            } | {"fixture_identity": _sportsdataio_cache_identity(match)} for match in near}
            tmp = SPORTSDATAIO_PREGAME_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(cached, handle, ensure_ascii=False)
            os.replace(tmp, SPORTSDATAIO_PREGAME_CACHE_FILE)
            DIAG.append(f"pregame overlay: {result['injuries']} availability rows, "
                        f"{result['lineups']} lineups")
            for error in result.get("errors") or []:
                DIAG.append(f"pregame overlay {error.get('input')} unavailable"
                            f"{f' for {error.get('date')}' if error.get('date') else ''}: "
                            f"{_scrub(error.get('error'))}")
            return result
        except ProviderError as exc:
            try:
                age_seconds = time.time() - os.path.getmtime(SPORTSDATAIO_PREGAME_CACHE_FILE)
                if age_seconds > SPORTSDATAIO_PREGAME_STALE_MAX_HOURS * 3600:
                    raise OSError("pregame cache exceeds bounded stale window")
                with open(SPORTSDATAIO_PREGAME_CACHE_FILE, encoding="utf-8") as handle:
                    cached = json.load(handle)
                cached_is_stale = True
                DIAG.append(f"pregame overlay: stale cache after provider error — {_scrub(exc)}")
            except Exception:
                DIAG.append(f"pregame overlay unavailable on this plan — {_scrub(exc)}")
                return {"injuries": 0, "lineups": 0}
    else:
        DIAG.append("pregame overlay: local cache")
    for match in near:
        row = cached.get(str(match.get("id"))) if isinstance(cached, dict) else None
        if not isinstance(row, dict):
            continue
        _merge_sportsdataio_cached_pregame(match, row, stale=cached_is_stale)
    return {"injuries": sum(_shadow_injury_count(match) for match in near),
            "lineups": sum(bool(match.get("lineups")) for match in near)}


def _merge_sportsgameodds_overlay(match, row):
    """Restore only normalized, non-ESPN fields from the quota-saving cache."""
    if not isinstance(row, dict):
        return {"markets": 0, "venues": 0, "starting_pitchers": 0, "lineups": 0,
                "starter_candidates": 0}
    markets = venues = pitchers = lineups = candidates = 0
    incoming = (row.get("markets") or {}).get("1x2")
    if incoming and not (match.get("markets") or {}).get("1x2"):
        match.setdefault("markets", {})["1x2"] = incoming
        markets = 1
    if row.get("venue") and not match.get("venue"):
        match["venue"] = row["venue"]
        venues = 1
    cached_personnel = row.get("personnel") or {}
    personnel = match.setdefault("personnel", {})
    # Schema-v2 caches mislabeled prop-derived names as canonical starters and
    # lineups. Never restore those keys, even from a bounded stale cache.
    if cached_personnel.get("starter_candidates") and not personnel.get("starter_candidates"):
        personnel["starter_candidates"] = cached_personnel["starter_candidates"]
        candidates += 1
    if cached_personnel.get("market_listed_hitters") and not personnel.get("market_listed_hitters"):
        personnel["market_listed_hitters"] = cached_personnel["market_listed_hitters"]
    provenance = match.setdefault("pregame_provenance", [])
    for item in row.get("pregame_provenance") or []:
        if item not in provenance:
            provenance.append(item)
    return {"markets": markets, "venues": venues,
            "starting_pitchers": pitchers, "lineups": lineups,
            "starter_candidates": candidates}


def fetch_sportsgameodds_overlay(matches):
    """Fill market gaps and infer MLB personnel from the licensed odds feed.

    SportsGameOdds is a fallback, not another hourly poll. The primary Odds
    API remains untouched when it returned a market. MLB player props arrive
    inside the same paid event objects, so a 24-hour normalized cache can
    retain carefully labelled starter/active-hitter inferences without extra
    entity spend. They are never represented as confirmed team sheets.
    """
    if COMP_KEY not in SportsGameOddsAdapter.LEAGUES:
        return {"markets": 0, "venues": 0}
    if not SPORTSGAMEODDS_KEY or "PASTE_" in str(SPORTSGAMEODDS_KEY):
        DIAG.append("SportsGameOdds overlay: key not configured")
        return {"markets": 0, "venues": 0}
    now = datetime.datetime.now(datetime.timezone.utc)
    near = []
    for match in matches:
        kickoff = _parse_kickoff(match.get("kickoff"))
        if match.get("status") == "UPCOMING" and kickoff:
            hours = (kickoff - now).total_seconds() / 3600
            if 0 <= hours <= SPORTSGAMEODDS_WINDOW_HOURS:
                near.append(match)
    targets = near if COMP_KEY == "MLB" else [
        match for match in near if not (match.get("markets") or {}).get("1x2")]
    if not targets:
        DIAG.append("SportsGameOdds overlay: no missing near-term market")
        result = {"markets": 0, "venues": 0}
        if COMP_KEY == "MLB":
            result.update({"starting_pitchers": 0, "lineups": 0,
                           "starter_candidates": 0})
        return result

    cached = None
    try:
        with open(SPORTSGAMEODDS_CACHE_FILE, encoding="utf-8") as handle:
            candidate = json.load(handle)
        age = time.time() - float(candidate.get("t") or 0)
        schema_ok = COMP_KEY != "MLB" or candidate.get("schema_ver") == 3
        if schema_ok and age < SPORTSGAMEODDS_CACHE_MIN * 60:
            cached = candidate
            rows = candidate.get("matches") or {}
            uncovered = [match for match in targets
                         if str(match.get("id")) not in rows]
            if uncovered and age >= SPORTSGAMEODDS_REFRESH_MIN * 60:
                # Serving this cache would silently return nothing for these
                # fixtures until the ceiling expired. Spend one request.
                cached = None
                DIAG.append(f"SportsGameOdds overlay: cache misses "
                            f"{len(uncovered)} near-term fixture(s); refreshing")
    except Exception:
        cached = None

    if cached is None:
        observed_at = now.isoformat().replace("+00:00", "Z")
        try:
            adapter = SportsGameOddsAdapter(SPORTSGAMEODDS_KEY, COMP_KEY)
            venue_was_missing = {str(match.get("id")): not bool(match.get("venue"))
                                 for match in targets}
            events = adapter.upcoming_events(
                observed_at,
                (now + datetime.timedelta(hours=SPORTSGAMEODDS_WINDOW_HOURS))
                .isoformat().replace("+00:00", "Z"),
            )
            result = adapter.attach_pregame(
                targets, events, observed_at=observed_at,
                has_draws=bool(COMP.get("has_draws")),
            )
            cached = {"schema_ver": 3, "t": time.time(), "observed_at": observed_at, "matches": {
                str(match.get("id")): {
                    "markets": {"1x2": (match.get("markets") or {}).get("1x2")}
                               if ((match.get("markets") or {}).get("1x2") or {}).get("source")
                               == "SportsGameOdds consensus" else {},
                    "venue": match.get("venue") if venue_was_missing.get(str(match.get("id"))) else None,
                    "pregame_provenance": [item for item in match.get("pregame_provenance") or []
                                             if item.get("source") == "SportsGameOdds"],
                    "personnel": {
                        "starter_candidates": (match.get("personnel") or {})
                            .get("starter_candidates"),
                        "market_listed_hitters": (match.get("personnel") or {})
                            .get("market_listed_hitters"),
                    },
                } for match in targets
            }}
            tmp = SPORTSGAMEODDS_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(cached, handle, ensure_ascii=False)
            os.replace(tmp, SPORTSGAMEODDS_CACHE_FILE)
            DIAG.append(f"SportsGameOdds overlay: {result['markets']} market(s), "
                        f"{result['venues']} venue(s), "
                        f"{result.get('starter_candidates', 0)} starter candidate(s), "
                        f"{result.get('lineups', 0)} inferred lineup(s), {len(events)} object(s)")
            return result
        except ProviderError as exc:
            try:
                with open(SPORTSGAMEODDS_CACHE_FILE, encoding="utf-8") as handle:
                    candidate = json.load(handle)
                age = time.time() - float(candidate.get("t") or 0)
                if COMP_KEY == "MLB" and candidate.get("schema_ver") != 3:
                    raise OSError("SportsGameOdds MLB cache predates personnel schema")
                if age > SPORTSGAMEODDS_STALE_MAX_HOURS * 3600:
                    raise OSError("SportsGameOdds cache exceeds bounded stale window")
                cached = candidate
                DIAG.append(f"SportsGameOdds overlay: bounded stale cache after provider error — {_scrub(exc)}")
            except Exception:
                DIAG.append(f"SportsGameOdds overlay unavailable — {_scrub(exc)}")
                return {"markets": 0, "venues": 0, "starting_pitchers": 0,
                        "lineups": 0, "starter_candidates": 0}
    else:
        DIAG.append("SportsGameOdds overlay: local cache")

    totals = {"markets": 0, "venues": 0, "starting_pitchers": 0, "lineups": 0,
              "starter_candidates": 0}
    rows = cached.get("matches") if isinstance(cached, dict) else {}
    for match in targets:
        added = _merge_sportsgameodds_overlay(match, (rows or {}).get(str(match.get("id"))))
        for key in totals:
            totals[key] += added[key]
    return totals


def _has_injuries(match):
    injuries = match.get("injuries") or {}
    return isinstance(injuries, dict) and any(injuries.get(side) for side in ("home", "away"))


def _shadow_injury_count(match):
    details = (match.get("personnel") or {}).get("injury_details") or {}
    return sum(len(details.get(side) or []) for side in ("home", "away"))


def _injury_data_available(match):
    return (_has_injuries(match) or
            bool((match.get("personnel") or {}).get("injuries_feed_checked")))


def record_market_snapshots(matches):
    """Persist authorized pregame consensus probabilities for later CLV/audits."""
    now = datetime.datetime.now(datetime.timezone.utc)
    batches = defaultdict(list)
    for match in matches:
        kickoff = _parse_kickoff(match.get("kickoff"))
        market = (match.get("markets") or {}).get("1x2") or {}
        if match.get("status") != "UPCOMING" or not kickoff or now >= kickoff:
            continue
        keys = ("h", "a") if not COMP.get("has_draws") else ("h", "d", "a")
        source_keys = {"h": "home_pct", "d": "draw_pct", "a": "away_pct"}
        if any(market.get(source_keys[key]) is None for key in keys):
            continue
        observed_at = market.get("observed_at")
        if not observed_at and _ODDS_CACHE.get("t"):
            observed_at = datetime.datetime.fromtimestamp(
                float(_ODDS_CACHE["t"]), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        if not observed_at:
            continue
        snapshot = {
            "fixture_id": str(match.get("id")), "competition": COMP_KEY,
            "kickoff": match.get("kickoff"), "observed_at": observed_at,
            "participants": {
                "home": {"id": str((match.get("home") or {}).get("code") or norm((match.get("home") or {}).get("name"))),
                         "name": (match.get("home") or {}).get("name")},
                "away": {"id": str((match.get("away") or {}).get("code") or norm((match.get("away") or {}).get("name"))),
                         "name": (match.get("away") or {}).get("name")},
            },
            "market_type": "1x2" if len(keys) == 3 else "moneyline",
            "odds_format": "probability",
            "outcomes": {key: float(market[source_keys[key]]) / 100.0 for key in keys},
            "source_snapshot_id": market.get("snapshot_id") or
                                  f"{match.get('id')}:{observed_at}",
        }
        source = market.get("source") or "The Odds API consensus"
        source_reference = market.get("source_reference") or "https://the-odds-api.com/"
        batches[(source, source_reference)].append(snapshot)
    if not batches:
        return 0
    total = 0
    for (source, source_reference), snapshots in batches.items():
        # Replaying a cache is not a new provider fetch. Keeping each batch's
        # fetch time tied to its actual quote also makes cache replays dedupe.
        fetched_at = max(snapshot["observed_at"] for snapshot in snapshots)
        try:
            result = market_snapshots.append_batch("market_snapshot_ledger.jsonl", {
                "source": source,
                "authorization_basis": "licensed",
                "source_reference": source_reference,
                "fetched_at": fetched_at, "snapshots": snapshots,
            }, recorded_at=now.isoformat())
            DIAG.append(f"market ledger ({source}): "
                        f"{'appended' if result['created'] else 'deduplicated'} "
                        f"{len(snapshots)} pregame snapshot(s)")
            total += len(snapshots)
        except (OSError, ValueError) as exc:
            DIAG.append(f"market ledger ({source}): snapshot rejected — {_scrub(exc)}")
    return total



def _due_for_odds(match, now_utc=None):
    """Only upcoming fixtures close enough to produce a lockable pregame pick.

    In-progress, finished, and past-kickoff fixtures must never spend an odds
    credit: once kickoff arrives the public ledger, not a changing market,
    is the source of truth.
    """
    if match.get("status") != "UPCOMING":
        return False
    try:
        kickoff = datetime.datetime.fromisoformat(
            str(match.get("kickoff") or "").replace("Z", "+00:00"))
    except Exception:
        return False
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    seconds = (kickoff - now_utc).total_seconds()
    return 0 < seconds <= PREGAME_ODDS_WINDOW_HOURS * 3600


def build():
    DIAG.clear()
    provider_quota.BLOCKED_THIS_RUN.clear()
    MARKET_STATE["quota_out"] = False
    print("Fetching fixtures…")
    raw = []
    sports_adapter, matches, st, sports_tables = fetch_college_bundle()
    provider_name = "CollegeFootballData" if COMP_KEY == "NCAAF" else "CollegeBasketballData"
    if True:
        print(f"  got {len(matches)} fixtures ({provider_name})")
        training_matches = normalize_match_results(
            getattr(sports_adapter, "_model_history", matches))
        mark_stale_offseason_records(st, sports_tables, training_matches, matches, COMP_KEY)
        srs_ratings = compute_srs(training_matches)
        # Match cards already receive SRS below. Put the same evidence on the
        # standings rows so the independent college Top 25 can compare every
        # FBS/D1 team, including teams outside this run's display window.
        if COMP_KEY in {"NCAAF", "NCAAM"}:
            for table in sports_tables:
                for team in table.get("teams") or []:
                    srs = srs_ratings.get(norm(team.get("name")))
                    if srs:
                        team["srs"], team["srs_games"] = srs["rating"], srs["games"]
                        rec = st.get(norm(team.get("name")))
                        if rec is not None:
                            rec["srs"], rec["srs_games"] = srs["rating"], srs["games"]
        rank_map = {}
        if COMP_KEY in ("NCAAF", "NCAAM") and sports_adapter:
            try:
                provider_ranks, _ = sports_adapter.rankings(sports_tables)
                rank_map = {norm(row.get("name")): row for row in provider_ranks}
            except ProviderError as exc:
                DIAG.append(f"{provider_name} rankings unavailable: {_scrub(exc)}")
        name_map = {}
        for m in matches:
            for t in (m["home"], m["away"]):
                name_map[norm(t["name"])] = t["name"]
                rec = st.get(norm(t["name"]))
                if rec:  # hydrate the model's inputs from real standings
                    t["pts"], t["gd"], t["form"] = rec["pts"], rec["gd"], rec["form"]
                    t["group"], t["pos"] = rec["group"], rec.get("pos")
                    t["gf"], t["ga"], t["pld"] = rec.get("gf", 0), rec.get("ga", 0), rec.get("pld", 0)
                    for field in ("w", "d", "l", "record", "win_pct", "avg_pf", "avg_pa", "season_stale"):
                        if field in rec:
                            t[field] = rec[field]
                srs = srs_ratings.get(norm(t["name"]))
                if srs:
                    t["srs"], t["srs_games"] = srs["rating"], srs["games"]
                if norm(t["name"]) in rank_map:
                    rank_record = rank_map[norm(t["name"])]
                    t["model_rank"] = rank_record.get("rank")
                    t["rank_source"] = ("model_projection" if rank_record.get("projected")
                                        else "poll")
                # class/power-rating ("rating") is intentionally NOT set here.
                # power_rating() reads the same ratings store that
                # apply_recruiting_strength()/apply_market_strength() enrich
                # further down this function (talent/recruiting data, then
                # championship odds) -- computing it this early captured
                # teams before that enrichment ran, so the number shown to
                # users (and fed to Sandbox/watchability) was permanently one
                # step behind what predict() itself used later in the same
                # run. See the recompute pass after apply_market_strength().
        for table in sports_tables:
            for team in table.get("teams") or []:
                if team.get("name"):
                    name_map.setdefault(norm(team["name"]), team["name"])

    DIAG.append(f"ratings: {len(_load_ratings())} teams loaded")
    restored_context = restore_pregame_snapshots(matches)
    if restored_context:
        DIAG.append(f"pregame snapshots: restored last-known context for {restored_context} match(es)")
    compute_rest(matches, training_matches)
    print("Fetching weather…")
    fetch_weather(matches)
    # prune odds-history entries that belong to no fixture in this competition
    # (cleans NFL entries inherited by the legacy-file migration)
    try:
        if len(matches) >= 20:
            names = set()
            for _m in matches:
                names.add(norm(_m["home"]["name"])); names.add(norm(_m["away"]["name"]))
            od = _load_open()
            bad = [k for k in list(od.keys())
                   if "|" in k and not (k.split("|")[0] in names or k.split("|")[1] in names)]
            if bad:
                for k in bad: od.pop(k, None)
                _save_open()
                DIAG.append(f"odds history: pruned {len(bad)} foreign entries")
    except Exception as e:
        DIAG.append(f"odds prune skipped: {e}")
    print("Fetching odds…")
    if any(_due_for_odds(m) for m in matches):
        odds = fetch_odds()
    else:
        odds = {}
        DIAG.append(f"odds: skipped — no upcoming game within {PREGAME_ODDS_WINDOW_HOURS}h")
    merged = 0; fuzzy = 0
    for m in matches:
        rec, how = find_odds(odds, m["home"]["name"], m["away"]["name"])
        if rec:
            m["markets"] = rec; merged += 1
            if how == "fuzzy": fuzzy += 1
    print("Fetching fallback market context (SportsGameOdds)…")
    fetch_sportsgameodds_overlay(matches)
    record_market_snapshots(matches)

    print("Fetching sport-specific personnel context (SportsDataIO)…")
    fetch_sportsdataio_pregame_overlay(matches)

    venue_shadow = pregame_context.derive_venue_context(matches, training_matches, COMP["sport"])
    if venue_shadow.get("matches"):
        DIAG.append(f"venue context shadow: {venue_shadow['matches']} match(es), production weight 0")
    saved_context = save_pregame_snapshots(matches)
    if saved_context:
        DIAG.append(f"pregame snapshots: retained {saved_context} active fixture(s)")

    # pull championship odds first and fold them into team strength so
    # predictions use market-implied strength
    code_map = {}
    for m in matches:
        code_map[norm(m["home"]["name"])] = m["home"]["code"]
        code_map[norm(m["away"]["name"])] = m["away"]["code"]
    known_names = set(name_map.keys())
    if COMP_KEY == "NCAAF" and sports_adapter:
        try:
            print("Fetching team talent composite (CFBD)…")
            apply_recruiting_strength(fetch_college_class_strength(sports_adapter, "talent"), known_names)
        except ProviderError as exc:
            DIAG.append(f"{provider_name} talent unavailable: {_scrub(exc)}")
    elif COMP_KEY == "NCAAM" and sports_adapter:
        try:
            print("Fetching recruiting ratings (CBBD)…")
            apply_recruiting_strength(fetch_college_class_strength(sports_adapter, "recruiting"), known_names)
        except ProviderError as exc:
            DIAG.append(f"{provider_name} recruiting unavailable: {_scrub(exc)}")

    title = None
    if COMP.get("outright"):
        print("Fetching championship odds (team strength)…")
        title = fetch_outrights(code_map)
        apply_market_strength(title, known_names)

    if True:
        # class/power-rating, computed now that apply_recruiting_strength()/
        # apply_market_strength() above have folded this run's talent and
        # championship-odds data into the ratings store predict() reads --
        # doing this any earlier (see the loop that hydrates standings above)
        # showed users a rating captured before that enrichment landed, even
        # though predict() itself (later still, once training/predictions
        # run) always saw the enriched numbers.
        for m in matches:
            for t in (m["home"], m["away"]):
                t["rating"] = round(power_rating(t["name"]), 2)
        # Same enrichment for the standings/conference tables so the
        # Groups/Standings tab can show the model's strength rating next to
        # the actual win-loss record it's sorted by, instead of only
        # surfacing that rating inside individual match cards.
        for table in sports_tables:
            for team in table.get("teams") or []:
                if team.get("name"):
                    team["rating"] = round(power_rating(team["name"], team), 2)

    # train the self-updating factors (Elo, H2H) on this run's finished
    # results, and derive home/away split form -- all from the same
    # `matches` list every provider already fills in, before predictions run
    update_elo(training_matches)
    update_h2h(training_matches)
    split_form = compute_split_form(training_matches)
    for m in matches:
        for side_key in ("home", "away"):
            rec = split_form.get(norm(m[side_key].get("name")))
            if rec:
                m[side_key]["form_home"] = rec["form_home"]
                m[side_key]["form_away"] = rec["form_away"]

    # Advanced metrics remain shadow-only until the frozen research protocol
    # promotes a learned challenger. NCAAF can refresh directly from its
    # already-approved league-wide CFBD endpoint; other sports consume
    # profiles built by build_advanced_metrics.py from approved downloads.
    if COMP_KEY == "NCAAF" and sports_adapter:
        refresh_college_advanced_metrics(sports_adapter)

    # Build an auditable, sport-aware readiness receipt. Personnel and venue
    # additions stay at zero production weight until prospective promotion.
    pregame_context.attach_personnel_shadows(matches, COMP["sport"])
    readiness = pregame_context.attach_pregame_context(matches, COMP_KEY, COMP["sport"])
    DIAG.append("pregame readiness: " + ", ".join(
        f"{key}={value}" for key, value in readiness.items() if value))

    # predictions run AFTER all stats/lineups so the model can use them this run
    shadow = attach_shadow_profiles(matches, COMP_KEY, COMP["sport"])
    if shadow.get("matches"):
        DIAG.append(f"advanced metrics shadow: {shadow['teams']} team profiles on {shadow['matches']} match(es)")
    for m in matches:
        m["prediction"] = predict(m["home"], m["away"], m["markets"], m)
        m["prediction"] = _set_prediction_publication_state(m, m["prediction"])
        if m["prediction"].get("publication_state") == "paused":
            continue
        # Real, not simulated: reruns the same predict() with the home-
        # advantage term zeroed, so the Sandbox's "neutral venue" toggle
        # shows an actual model output rather than a client-side guess.
        # Skipped once a match is finished (nothing left to toggle) and left
        # out of the locked prediction_snapshot the same way -- apply_locked_picks()
        # replaces this whole dict for locked matches, so it only ever
        # appears on a still-adjustable, not-yet-locked forecast.
        if m.get("status") != "FINISHED":
            m["prediction"]["neutral_venue_probs"] = predict(
                m["home"], m["away"], m["markets"], m, neutral_venue=True
            )["adjusted"]
        m["prediction"]["totals"] = predict_totals(m["home"], m["away"], m["markets"])
        m["watchability"] = compute_watchability(m)
    print(f"  merged odds onto {merged} fixtures ({fuzzy} via name-variant match) · predictions on all {len(matches)}")

    print("Fetching title odds + news…")
    if title is None:
        title = fetch_outrights(code_map)
    if not title:
        title = estimate_title_odds(matches, code_map)
        if title:
            DIAG.append(f"title race: no market odds available, estimated from model ratings for {len(title)} teams")
    news = fetch_news()
    bracket = []
    third = []

    standings = sports_tables
    bracketology = None
    projection_current = False
    bracket_projection_current = False
    if True:
        ranks, proj = sports_adapter.rankings(sports_tables) if sports_adapter else ([], None)
        if ranks:
            is_projected = bool(ranks[0].get("projected"))
            rank_rows = [{"name": r["name"], "code": r["code"], "pos": r["rank"],
                          "pld": None, "w": None, "d": None, "l": None, "gf": None, "ga": None,
                          "gd": None, "pts": None, "form": "", "record": r["record"],
                          "qual": ({"status": f"CFP {r['rank']}", "note": "projected playoff seed (straight seeding)"} if COMP_KEY == "NCAAF" and not is_projected and r["rank"] <= 12 else "")}
                         for r in ranks]
            if not is_projected:
                poll_name = str(ranks[0].get("poll_name") or "National Poll")
                poll_table = {"group": poll_name, "table_type": "official_poll",
                              "teams": rank_rows}
                standings = [poll_table] + (standings or [])
        model_table = _matchday_top_25(sports_tables)
        if model_table["teams"]:
            projection_current = True
            standings = [model_table] + (standings or [])
        if COMP_KEY == "NCAAF" and proj and not bracket:
            bracket = dict(proj) if isinstance(proj, dict) else proj
            if isinstance(bracket, dict):
                bracket["projection_current"] = True
            projection_current = True
            bracket_projection_current = True
    if COMP_KEY == "NCAAM":
        bracketology = build_ncaam_bracketology(sports_tables)
    season_context = competition_season_context(
        training_matches, matches, COMP_KEY,
        projection_current=projection_current, standings=standings,
    )
    standings, bracket, bracketology, season_context = filter_current_season_views(
        standings, bracket, bracketology, season_context,
        bracket_projection_current=bracket_projection_current,
    )
    if not season_context["derived_positions_current"]:
        third = []
        for view in ("third_race", "advancement"):
            if view not in season_context["suppressed_views"]:
                season_context["suppressed_views"].append(view)
    if season_context["suppressed_views"]:
        DIAG.append("season context: suppressed stale " + ", ".join(
            season_context["suppressed_views"]))
    scorecard = update_scorecard(matches)
    apply_locked_picks(matches)
    # A historical upcoming lock may predate the pause. Keep its immutable
    # receipt for later grading, but never republish its official model output.
    _enforce_forecast_pause_after_locked_picks(matches)
    _betbetter = betbetter_handoff.attach_from_file(matches)
    if _betbetter["attached"]:
        DIAG.append(f"matchday live picks: attached {_betbetter['attached']}")
    # Top-level marker survives immutable legacy prediction snapshots and lets
    # multi_fetch detect that an otherwise fresh JSON file predates a model
    # input/schema change. Bump only when every sport needs one clean rebuild.
    for m in matches:
        m["model_signal_schema"] = MODEL_SIGNAL_SCHEMA
    weekly_awards = build_weekly_awards(matches, scorecard)
    try:
        from generate_posts import publish_recap_if_due
        post = publish_recap_if_due(COMP_KEY, COMP["label"], scorecard, weekly_awards)
        if post:
            DIAG.append(f"posts: published '{post['title']}'")
    except Exception as e:
        DIAG.append(f"posts: skipped — {e}")
    scorers = []
    leaders = {}
    if sports_adapter:
        print(f"Fetching season leaders ({provider_name})…")
        leaders = fetch_college_leaders(sports_adapter, provider_name)

    live = sum(1 for m in matches if m["status"] == "LIVE")
    source_note = "live"
    fixture_count_check = _check_and_record_fixture_count(COMP_KEY, len(matches))
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    source_provider = COMP.get("source")
    blocked_providers = list(provider_quota.BLOCKED_THIS_RUN)
    source_state = ("quota_limited" if source_provider in blocked_providers
                    else "partial" if blocked_providers else "fresh")
    advancement = []
    # Archive the finished games before the payload that holds them is
    # overwritten. Costs no provider call -- these were already fetched -- and
    # record_build() swallows its own errors so the deploy never fails here.
    archived = game_archive.record_build(COMP_KEY, matches, source_provider or "")
    if archived.get("added"):
        DIAG.append(f"archive: +{archived['added']} finished game(s) for {COMP_KEY}")
    if archived.get("conflicts"):
        DIAG.append(f"archive: {archived['conflicts']} score revision(s) refused; see archive/conflicts.jsonl")

    payload = {"updated": generated_at,
               "source_freshness": {
                   "state": source_state,
                   "generated_at": generated_at,
                   "last_successful_at": generated_at if source_state != "quota_limited" else None,
                   "primary_provider": source_provider,
                   "quota_blocked_providers": blocked_providers,
                   "fallback_age_hours": 0,
                   "note": ("Primary provider was quota-limited; retained fields may come from bounded caches."
                            if source_state == "quota_limited" else
                            "Some optional provider signals were quota-limited."
                            if source_state == "partial" else
                            "This competition build completed without a quota refusal."),
               },
               "fixture_count_check": fixture_count_check,
               "season_context": season_context,
               "source_note": source_note, "competition": COMP["label"], "comp_key": COMP_KEY, "matches": matches,
               "title_odds": title, "news": news, "news_scope": COMP_KEY, "bracket": bracket, "bracketology": bracketology,
               "third_race": third, "standings": standings, "scorers": scorers, "leaders": leaders, "team_of_tournament": None, "scorecard": scorecard,
               "advancement": advancement,
               "weekly_awards": weekly_awards,
               "markets_quota_out": MARKET_STATE["quota_out"],
               "quota_blocked_providers": blocked_providers,
               "diagnostics": [_scrub(x) for x in DIAG]}
    payload["forecast_publication"] = forecast_pause.publication_decision(COMP_KEY)
    payload["betbetter_handoff"] = _betbetter
    for out in (OUT_FILE, f"data_{COMP_KEY.lower()}.json"):
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out)

    print("\n--- diagnostics ---")
    for d in DIAG: print("  " + d)
    print(f"Wrote {OUT_FILE}  ✓  (live matches: {live})\n")
    return live


def main():
    if not ODDS_API_KEY or "PASTE_" in ODDS_API_KEY:
        print("\n  Stop: keys not loaded — fix config_keys.py (see the !! lines above).\n"); sys.exit(1)
    loop = "--loop" in sys.argv
    # A caught build() exception here used to only print to a CI log nobody
    # outside the Actions run can read (this file's own picks/data caches
    # are the only durable trace) and still exit 0, so a competition could
    # silently stop locking/grading picks for hours with no visible signal.
    # Persist what happened to a small per-competition file instead so the
    # next run -- or anyone inspecting the repo -- can see whether recent
    # runs are actually failing here, and clear it the moment a run succeeds
    # so a fixed, healthy competition doesn't keep showing a stale failure.
    failure_file = f"fetch_failure_{COMP_KEY.lower()}.json"
    while True:
        live = 0
        try:
            live = build()
            if os.path.exists(failure_file):
                os.remove(failure_file)
        except Exception as e:
            print("  ! fetch failed this round:", e)
            try:
                tmp = failure_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"comp": COMP_KEY,
                               "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                               "error": _scrub(e), "traceback": _scrub(traceback.format_exc())}, f, ensure_ascii=False, indent=2)
                os.replace(tmp, failure_file)
            except Exception:
                pass  # diagnostics are best-effort; never let this mask the original failure
        if not loop: break
        if live:
            print(f"Result pending — checking again in {LIVE_SECONDS // 60} min  (Ctrl+C to stop)")
            time.sleep(LIVE_SECONDS)
        else:
            print(f"Idle — refreshing in {IDLE_MINUTES} min  (Ctrl+C to stop)")
            time.sleep(IDLE_MINUTES * 60)


if __name__ == "__main__":
    main()
