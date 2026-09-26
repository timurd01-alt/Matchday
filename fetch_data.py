"""
matchday fetcher  (v5)
----------------------
  College data APIs  -> NCAAF/NCAAM schedules + tables (shared free key)
  The Odds API       -> pregame market odds           (required key)
  SportsDataIO       -> dormant pregame overlay        (trial/licensed key)
  SportsGameOdds     -> fallback market context        (licensed key)

College football and men's college basketball are the only competitions.

The product is intentionally pregame/postgame rather than a live-score feed:
  * picks come from the Bet Better handoff (betbetter_handoff.py), not from here;
  * results are fetched after kickoff;
  * odds are requested only for near-kickoff upcoming games and cached on disk.

Run:  python fetch_data.py          (once)
      python fetch_data.py --loop   (hourly result checks)
"""

import json, os, sys, time, datetime, re, unicodedata, urllib.request, urllib.error, urllib.parse, traceback, contextlib
import html
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from collections import defaultdict
import game_archive
import betbetter_handoff
import market_snapshots
import pregame_context
import provider_quota
import refresh_ncaaf_venues
from provider_adapters import (ProviderError,
                               CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter,
                               SportsDataIOAdapter, SportsGameOddsAdapter, normalized_score,
                               season_form_from_matches, blend_season_history)

# Windows terminals default to a legacy codec that crashes on characters like the
# checkmark or accented player names. Force UTF-8 so background prints never crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
#  PRIVATE KEYS
#  - CFBD/CBBD power fixtures and tables; The Odds API powers market odds
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

# ---- competition selection --------------------------------------------------
# College football is the default. Launch with --ncaam (or MATCHDAY_COMP=NCAAM)
# for men's college basketball. These are the only two competitions.
COMPETITIONS = {
    "NCAAF": {"label": "College Football", "sport": "football", "fd": None, "odds": "americanfootball_ncaaf",
            "tournament": False,
            "source": "cfbd", "has_draws": False},
    "NCAAM": {"label": "Men's College Basketball", "sport": "basketball", "fd": None, "odds": "basketball_ncaab",
            "tournament": False,
            "source": "cbbd", "has_draws": False},
}
# ---- the active competition -------------------------------------------------
# COMP_KEY is a module-level singleton, and ~15 further module-level values are
# derived from it: the market URLs, every per-competition cache path, the
# opening-odds store, and the news feed set.
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
        "ODDS_CACHE_FILE": f"odds_market_cache_{low}.json",
        "SPORTSDATAIO_PREGAME_CACHE_FILE": f"sportsdataio_pregame_{low}_cache.json",
        "PREGAME_CONTEXT_CACHE_FILE": f"pregame_{low}_cache.json",
        "SPORTSGAMEODDS_CACHE_FILE": f"sportsgameodds_{low}_cache.json",
        "OPEN_FILE": f"odds_open_{low}.json",          # first-seen ("opening") odds
        "_news_term": NEWS_TERMS.get(key, comp["label"]),
    }


def set_competition(key):
    """Point the whole module at `key`, derived values and caches together.

    Returns the normalized COMP_KEY. Safe to call repeatedly. The per-competition
    load cache (_OPEN) and the market/news response caches are cleared,
    because each holds data for the competition that was active when it was filled.
    """
    resolved = normalize_competition(key)
    state = _competition_state(resolved)
    globals().update(state)
    globals()["RSS_FEEDS"] = _build_rss_feeds(resolved, state["COMP"], state["_news_term"])
    globals()["_OPEN"] = None
    _ODDS_CACHE.update({"t": 0.0, "data": {}})
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


ODDS_FREE_QUOTA_URL = "https://api.the-odds-api.com/v4/sports/?apiKey="
PREGAME_ODDS_WINDOW_HOURS = 24
UA = {"User-Agent": "Mozilla/5.0 (matchday-terminal)"}

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
_NEWS_CACHE = {"t": 0.0, "data": []}
NEWS_CACHE_MIN = 20
NEWS_MAX_AGE_DAYS = 7
NEWS_FUTURE_TOLERANCE_HOURS = 24
COLLEGE_CACHE_MIN = 480  # eight-hour cache keeps both college feeds within a shared free-key quota
# Season player-stats leaders pull the *whole* field in one request (no
# per-team looping -- see CollegeFootballDataAdapter.leaders() /
# CollegeBasketballDataAdapter.leaders()), so it's cheap in call count but
# expensive in bytes (CFBD's is tens of MB). Player totals move slowly
# within a season, so this rides a much longer cache than the schedule
# bundle rather than refetching on the bundle's 8-hour cadence.
COLLEGE_LEADERS_CACHE_MIN = 1440  # 24 hours
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
ODDS_CACHE_FILE = _STATE["ODDS_CACHE_FILE"]
SPORTSDATAIO_PREGAME_CACHE_FILE = _STATE["SPORTSDATAIO_PREGAME_CACHE_FILE"]
PREGAME_CONTEXT_CACHE_FILE = _STATE["PREGAME_CONTEXT_CACHE_FILE"]
SPORTSGAMEODDS_CACHE_FILE = _STATE["SPORTSGAMEODDS_CACHE_FILE"]
OPEN_FILE = _STATE["OPEN_FILE"]
_news_term = _STATE["_news_term"]
RSS_FEEDS = _build_rss_feeds(COMP_KEY, COMP, _news_term)
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


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        v = lo
    return max(lo, min(hi, v))


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


def _shadow_injury_count(match):
    details = (match.get("personnel") or {}).get("injury_details") or {}
    return sum(len(details.get(side) or []) for side in ("home", "away"))


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
        for table in sports_tables:
            for team in table.get("teams") or []:
                if team.get("name"):
                    name_map.setdefault(norm(team["name"]), team["name"])

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

    # Home/away split form is displayed in the team window.
    split_form = compute_split_form(training_matches)
    for m in matches:
        for side_key in ("home", "away"):
            rec = split_form.get(norm(m[side_key].get("name")))
            if rec:
                m[side_key]["form_home"] = rec["form_home"]
                m[side_key]["form_away"] = rec["form_away"]

    print("Fetching news…")
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
        if COMP_KEY == "NCAAF" and proj and not bracket:
            bracket = dict(proj) if isinstance(proj, dict) else proj
            if isinstance(bracket, dict):
                bracket["projection_current"] = True
            projection_current = True
            bracket_projection_current = True
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
    _betbetter = betbetter_handoff.attach_from_file(matches)
    if _betbetter["attached"]:
        DIAG.append(f"matchday live picks: attached {_betbetter['attached']}")
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
               "news": news, "news_scope": COMP_KEY, "bracket": bracket, "bracketology": bracketology,
               "third_race": third, "standings": standings, "scorers": scorers, "leaders": leaders, "team_of_tournament": None,
               "advancement": advancement,
               "markets_quota_out": MARKET_STATE["quota_out"],
               "quota_blocked_providers": blocked_providers,
               "diagnostics": [_scrub(x) for x in DIAG]}
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
    # outside the Actions run can read (this file's own data caches are the
    # only durable trace) and still exit 0, so a competition could silently
    # stop refreshing for hours with no visible signal.
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
