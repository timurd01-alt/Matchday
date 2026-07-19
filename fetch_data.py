"""
matchday fetcher  (v5)
----------------------
  football-data.org  -> fixtures + live scores       (required key)
  The Odds API       -> 1X2 + over/under odds         (required key)
  BALLDONTLIE        -> NBA/NFL/MLB fixtures + scores  (free launch key)
  College data APIs  -> NCAAF/NCAAM schedules + tables (shared free key)
  SportsDataIO       -> dormant development feeds       (trial/licensed key)
  Sportmonks         -> soccer detail + availability   (licensed token)

v5 adds LIVE lineups:
  * when any match is LIVE the loop refreshes every ~45s (scores + lineups);
    odds are cached for 5 min so your Odds API quota is safe.
  * subbed-off players are flagged; substitution events are logged.

Run:  python fetch_data.py          (once)
      python fetch_data.py --loop   (auto: 45s while live, else 5 min)
"""

import json, os, sys, time, datetime, re, unicodedata, urllib.request, urllib.error, urllib.parse, math
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from collections import defaultdict
from provider_adapters import (ProviderError, BallDontLieAdapter,
                               CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter,
                               SportsDataIOAdapter, SportmonksAdapter,
                               APISportsAdapter)

# Windows terminals default to a legacy codec that crashes on characters like the
# checkmark or accented player names. Force UTF-8 so background prints never crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
#  PRIVATE KEYS
#  - football-data.org + The Odds API power fixtures/probabilities
#  - SportsDataIO and Sportmonks replace the former public/ambiguous feeds
# ============================================================
try:
    from config_keys import FOOTBALL_DATA_KEY, ODDS_API_KEY
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
    FOOTBALL_DATA_KEY = "PASTE_FOOTBALL_DATA_KEY_IN_config_keys.py"
    ODDS_API_KEY = "PASTE_ODDS_API_KEY_IN_config_keys.py"
try:
    from config_keys import API_FOOTBALL_KEY
except Exception:
    API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
try:
    from config_keys import SPORTSDATAIO_KEY, SPORTMONKS_KEY
except Exception:
    SPORTSDATAIO_KEY = os.environ.get("SPORTSDATAIO_KEY", "")
    SPORTMONKS_KEY = os.environ.get("SPORTMONKS_KEY", "")
try:
    from config_keys import BALLDONTLIE_KEY
except Exception:
    BALLDONTLIE_KEY = os.environ.get("BALLDONTLIE_KEY", "")
try:
    from config_keys import CFBD_KEY, CBBD_KEY
except Exception:
    CFBD_KEY = os.environ.get("CFBD_KEY", "")
    CBBD_KEY = os.environ.get("CBBD_KEY", "")
# ============================================================

IDLE_MINUTES = 60     # refresh cadence when nothing is live (hourly)
LIVE_SECONDS = 45     # refresh cadence while a match is live
ODDS_CACHE_MIN = 5    # never hit the odds API more often than this
OUT_FILE = "data.json"

FD_BASE  = "https://api.football-data.org/v4"

# ---- competition selection --------------------------------------------------
# Default is the World Cup. To run the Champions League instead, either add
#     COMPETITION = "UCL"
# to config_keys.py, or launch with:  python fetch_data.py --ucl
COMPETITIONS = {
    "WC":  {"label": "World Cup 2026",   "sport": "soccer", "fd": "WC", "odds": "soccer_fifa_world_cup",
            "outright": "soccer_fifa_world_cup_winner", "espn": "fifa.world", "tournament": True,
            "source": "fd", "has_draws": True},
    "UCL": {"label": "Champions League", "sport": "soccer", "fd": "CL", "odds": "soccer_uefa_champs_league",
            "outright": "soccer_uefa_champs_league_winner", "espn": "uefa.champions", "tournament": False,
            "source": "fd", "has_draws": True},
    # Free launch feeds. BALLDONTLIE supplies real schedules and scores; paid
    # standings/player endpoints stay hidden when unavailable.
    "NFL": {"label": "NFL", "sport": "football", "fd": None, "odds": "americanfootball_nfl",
            "outright": "americanfootball_nfl_super_bowl_winner", "espn": "nfl", "tournament": False,
            "source": "apisports", "has_draws": False},
    "EPL": {"label": "Premier League", "sport": "soccer", "fd": "PL", "odds": "soccer_epl",
            "outright": "soccer_epl_winner", "espn": "eng.1", "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 3}},
    "LALIGA": {"label": "La Liga", "sport": "soccer", "fd": "PD", "odds": "soccer_spain_la_liga",
            "outright": "soccer_spain_la_liga_winner", "espn": "esp.1", "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 3}},
    "SERIEA": {"label": "Serie A", "sport": "soccer", "fd": "SA", "odds": "soccer_italy_serie_a",
            "outright": "soccer_italy_serie_a_winner", "espn": "ita.1", "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 3}},
    "BUNDESLIGA": {"label": "Bundesliga", "sport": "soccer", "fd": "BL1", "odds": "soccer_germany_bundesliga",
            "outright": "soccer_germany_bundesliga_winner", "espn": "ger.1", "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 2}},
    "LIGUE1": {"label": "Ligue 1", "sport": "soccer", "fd": "FL1", "odds": "soccer_france_ligue_one",
            "outright": "soccer_france_ligue_one_winner", "espn": "fra.1", "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 2}},
    "NCAAF": {"label": "College Football", "sport": "football", "fd": None, "odds": "americanfootball_ncaaf",
            "outright": "americanfootball_ncaaf_championship_winner", "espn": "college-football", "tournament": False,
            "source": "cfbd", "has_draws": False},
    "NCAAM": {"label": "Men's College Basketball", "sport": "basketball", "fd": None, "odds": "basketball_ncaab",
            "outright": "basketball_ncaab_championship_winner", "espn": "mens-college-basketball", "tournament": False,
            "source": "cbbd", "has_draws": False},
    "MLB": {"label": "MLB", "sport": "baseball", "fd": None, "odds": "baseball_mlb",
            "outright": "baseball_mlb_world_series_winner", "espn": "mlb", "tournament": False,
            "source": "balldontlie", "has_draws": False},
    "NHL": {"label": "NHL", "sport": "hockey", "fd": None, "odds": "icehockey_nhl",
            "outright": "icehockey_nhl_championship_winner", "espn": "nhl", "tournament": False,
            "source": "sportsdataio", "has_draws": False},
    "NBA": {"label": "NBA", "sport": "basketball", "fd": None, "odds": "basketball_nba",
            "outright": "basketball_nba_championship_winner", "espn": "nba", "tournament": False,
            "source": "apisports", "has_draws": False},
}
try:
    from config_keys import COMPETITION as _COMP
except Exception:
    _COMP = "WC"
if "--ucl" in sys.argv: _COMP = "UCL"
if "--wc" in sys.argv:  _COMP = "WC"
if "--nfl" in sys.argv: _COMP = "NFL"
if "--nba" in sys.argv: _COMP = "NBA"
if "--ncaaf" in sys.argv: _COMP = "NCAAF"
if "--ncaam" in sys.argv: _COMP = "NCAAM"
if "--epl" in sys.argv: _COMP = "EPL"
if "--laliga" in sys.argv: _COMP = "LALIGA"
if "--seriea" in sys.argv: _COMP = "SERIEA"
if "--bundesliga" in sys.argv: _COMP = "BUNDESLIGA"
if "--ligue1" in sys.argv: _COMP = "LIGUE1"
if "--mlb" in sys.argv: _COMP = "MLB"
if "--nhl" in sys.argv: _COMP = "NHL"
_env = os.environ.get("MATCHDAY_COMP", "").upper()
if _env: _COMP = _env
COMP_KEY = str(_COMP).upper() if str(_COMP).upper() in COMPETITIONS else "WC"
COMP = COMPETITIONS[COMP_KEY]

ODDS_URL = (f"https://api.the-odds-api.com/v4/sports/{COMP['odds']}/odds/"
            "?regions=eu&markets=h2h,totals&oddsFormat=decimal")
ESPN_SB  = f"https://site.api.espn.com/apis/site/v2/sports/{COMP['sport']}/{COMP['espn']}/scoreboard?limit=300"
ESPN_SUM = "https://site.api.espn.com/apis/site/v2/sports/" + COMP['sport'] + "/" + COMP['espn'] + "/summary?event={id}"
UA = {"User-Agent": "Mozilla/5.0 (matchday-terminal)"}

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_CACHE_FILE = f"api_football_box_cache_{COMP_KEY.lower()}.json"
API_FOOTBALL_DAYS_BACK = 10     # recent finished matches to enrich with box scores
API_FOOTBALL_MAX_STATS = 18     # safety cap for the free daily request budget

DIAG = []
_ODDS_CACHE = {"t": 0.0, "data": {}}
_OUT_CACHE  = {"t": 0.0, "data": []}
_NEWS_CACHE = {"t": 0.0, "data": []}
OUTRIGHTS_URL = (f"https://api.the-odds-api.com/v4/sports/{COMP['outright']}/odds/"
                 "?regions=eu&markets=outrights&oddsFormat=decimal")
ESPN_NEWS = f"https://site.api.espn.com/apis/site/v2/sports/{COMP['sport']}/{COMP['espn']}/news"
OUTRIGHTS_CACHE_MIN = 60
NEWS_CACHE_MIN = 20
BALLDONTLIE_CACHE_MIN = 10
APISPORTS_CACHE_MIN = 30  # api-sports.io free tier caps at 100 req/day per sport
COLLEGE_CACHE_MIN = 480  # eight-hour cache keeps both college feeds within a shared free-key quota
NEWS_TERMS = {
    "WC": "FIFA World Cup", "UCL": "UEFA Champions League",
    "EPL": "Premier League soccer", "LALIGA": "La Liga soccer",
    "SERIEA": "Serie A soccer", "BUNDESLIGA": "Bundesliga soccer",
    "LIGUE1": "Ligue 1 soccer", "NFL": "NFL", "NCAAF": "college football", "NCAAM": "men's college basketball",
    "NBA": "NBA", "MLB": "MLB baseball", "NHL": "NHL hockey",
}
NEWS_RELEVANCE = {
    "NFL": "nfl super_bowl quarterback touchdown chiefs eagles bills ravens bengals browns steelers texans colts jaguars titans broncos chargers raiders cowboys giants commanders packers lions vikings bears falcons panthers saints buccaneers cardinals rams 49ers seahawks jets dolphins patriots",
    "NCAAF": "college_football ncaa cfp bowl heisman alabama georgia ohio_state michigan notre_dame oregon texas usc lsu clemson penn_state florida_state tennessee oklahoma auburn hurricanes",
    "NCAAM": "college_basketball ncaa march_madness final_four duke north_carolina kansas kentucky uconn gonzaga houston purdue villanova arizona michigan_state",
    "NBA": "nba basketball lebron giannis luka curry durant jokic wembanyama celtics lakers knicks nets 76ers raptors bulls cavaliers pistons pacers bucks heat magic hawks hornets wizards warriors clippers nuggets timberwolves thunder blazers jazz mavericks rockets grizzlies pelicans spurs suns kings",
    "MLB": "mlb baseball world_series yankees red_sox blue_jays orioles rays guardians tigers twins white_sox royals astros mariners rangers athletics angels braves mets phillies nationals marlins cubs cardinals brewers reds pirates dodgers padres giants diamondbacks rockies",
    "NHL": "nhl hockey stanley_cup bruins sabres red_wings panthers canadiens senators lightning maple_leafs hurricanes blue_jackets devils islanders rangers flyers penguins capitals blackhawks avalanche stars wild predators blues jets ducks flames oilers kings sharks kraken canucks golden_knights",
}
NEWS_STRONG_RELEVANCE = {
    "NFL": "nfl super_bowl quarterback touchdown chiefs eagles ravens bengals steelers texans colts jaguars titans broncos chargers raiders cowboys commanders packers vikings buccaneers 49ers seahawks patriots",
    "NCAAF": "college_football ncaa cfp heisman alabama ohio_state notre_dame penn_state florida_state",
    "NCAAM": "college_basketball ncaa march_madness final_four duke north_carolina kansas kentucky uconn gonzaga houston purdue",
    "NBA": "nba basketball lebron giannis luka curry durant jokic wembanyama celtics lakers knicks 76ers raptors cavaliers pistons pacers bucks warriors clippers nuggets timberwolves thunder mavericks grizzlies pelicans spurs",
    "MLB": "mlb baseball world_series yankees red_sox blue_jays orioles guardians white_sox royals astros mariners braves mets phillies marlins cubs brewers pirates dodgers padres diamondbacks rockies",
    "NHL": "nhl hockey stanley_cup bruins sabres red_wings canadiens senators lightning maple_leafs blue_jackets devils islanders flyers penguins capitals blackhawks avalanche predators kraken canucks golden_knights",
}


def _news_relevant(item):
    """Reject obvious cross-sport leakage from broad publisher feeds."""
    terms = NEWS_RELEVANCE.get(COMP_KEY)
    if not terms:
        return True
    raw_source = _clean(item.get("source") or item.get("feed") or "").lower()
    if re.search(r"\b(reuters|associated press|ap news|^ap$)\b", raw_source):
        terms = NEWS_STRONG_RELEVANCE.get(COMP_KEY, terms)
    text = _clean(f"{item.get('headline', '')} {item.get('desc', '')}").lower()
    return any(re.search(rf"\b{re.escape(term.replace('_', ' '))}\b", text) for term in terms.split())


def _google_news_feed(source, site, term):
    q = urllib.parse.quote_plus(f"site:{site} {term}")
    return source, f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


_news_term = NEWS_TERMS.get(COMP_KEY, COMP["label"])
RSS_FEEDS = []
if COMP["sport"] == "soccer":
    # Strong direct football feeds, then competition-specific source searches.
    RSS_FEEDS.extend([
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/football/rss"),
        ("Sky Sports", "https://www.skysports.com/rss/12040"),
        ("CBS Sports", "https://www.cbssports.com/rss/headlines/soccer/"),
        ("FOX Sports", "https://api.foxsports.com/v1/rss?tag=soccer"),
    ])

# These source-specific searches work across every sport and keep one outlet
# from taking over when a league's direct RSS feed is unavailable.
for _source, _site in (
    ("Reuters", "reuters.com"), ("Associated Press", "apnews.com"),
    ("CBS Sports", "cbssports.com"), ("FOX Sports", "foxsports.com"),
    ("NBC Sports", "nbcsports.com"), ("Yahoo Sports", "sports.yahoo.com"),
):
    RSS_FEEDS.append(_google_news_feed(_source, _site, _news_term))
if COMP_KEY == "WC":
    RSS_FEEDS.append(_google_news_feed("FIFA", "fifa.com", _news_term))
KO_STAGES = {"LAST_32": "Round of 32", "ROUND_OF_32": "Round of 32", "PLAYOFFS": "Knockout playoffs", "PLAY_OFF_ROUND": "Knockout playoffs", "LAST_16": "Round of 16",
             "QUARTER_FINALS": "Quarter-finals", "QUARTER_FINAL": "Quarter-finals",
             "SEMI_FINALS": "Semi-finals", "SEMI_FINAL": "Semi-finals",
             "THIRD_PLACE": "Third-place playoff", "FINAL": "Final"}
KO_ORDER = ["Round of 32", "Knockout playoffs", "Round of 16", "Quarter-finals", "Semi-finals", "Third-place playoff", "Final"]


def _scrub(s):
    """Mask API keys anywhere they might surface (error bodies, URLs, diagnostics)."""
    s = str(s)
    s = re.sub(r"(apiKey=)[A-Za-z0-9]+", r"\1***", s)
    s = re.sub(r"(X-Auth-Token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+", r"\1***", s)
    s = re.sub(r"(x-apisports-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+", r"\1***", s)
    for k in (FOOTBALL_DATA_KEY, ODDS_API_KEY, API_FOOTBALL_KEY):
        if k and len(str(k)) > 8:
            s = s.replace(str(k), "***")
    return s


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: body = e.read().decode("utf-8")[:300]
        except Exception: body = ""
        raise RuntimeError(_scrub(f"HTTP {e.code} — {body or e.reason}"))


def _get_text(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def _clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s.replace("&nbsp;", " ")).strip()


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


def fetch_raw_matches():
    return _get(f"{FD_BASE}/competitions/{COMP["fd"]}/matches", {"X-Auth-Token": FOOTBALL_DATA_KEY}).get("matches", [])


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
    # displayed scoreline: prefer ET if present, else regulation, else fullTime
    if et.get("home") is not None:
        hg, ag = et.get("home"), et.get("away")
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



def compute_standings(raw):
    T = defaultdict(lambda: {"group": None, "pld": 0, "w": 0, "d": 0, "l": 0,
                             "gf": 0, "ga": 0, "pts": 0, "results": []})
    for m in raw:
        h = (m.get("homeTeam") or {}).get("name"); a = (m.get("awayTeam") or {}).get("name")
        if not h or not a: continue
        if m.get("group"): T[norm(h)]["group"] = m["group"]; T[norm(a)]["group"] = m["group"]
        hs, as_, _win, _, _r90 = _resolve_score(m)
        if m.get("status") in ("FINISHED", "IN_PLAY", "PAUSED", "LIVE") and hs is not None and as_ is not None:
            for t, gf, ga in [(norm(h), hs, as_), (norm(a), as_, hs)]:
                r = T[t]; r["pld"] += 1; r["gf"] += gf; r["ga"] += ga
                if gf > ga: r["w"] += 1; r["pts"] += 3; res = "W"
                elif gf < ga: r["l"] += 1; res = "L"
                else: r["d"] += 1; r["pts"] += 1; res = "D"  # group stage: draw stands
                r["results"].append((m.get("utcDate") or "", res))
    for t, r in T.items():
        r["results"].sort(key=lambda x: x[0])
        r["form"] = " ".join(res for _, res in r["results"][-5:]); r["gd"] = r["gf"] - r["ga"]
    bg = defaultdict(list)
    for t, r in T.items():
        if r["group"]: bg[r["group"]].append(t)
    for grp, ts in bg.items():
        ts.sort(key=lambda t: (-T[t]["pts"], -T[t]["gd"], -T[t]["gf"]))
        for i, t in enumerate(ts, 1): T[t]["pos"] = i
    return T


def pretty_group(g):
    return (g or "").replace("GROUP_", "Group ").replace("_", " ").title() if g else ""


def build_matches(raw, st):
    smap = {"FINISHED": "FINISHED", "IN_PLAY": "LIVE", "PAUSED": "LIVE", "LIVE": "LIVE"}
    out = []
    for m in raw:
        h = m.get("homeTeam") or {}; a = m.get("awayTeam") or {}
        if not h.get("name") or not a.get("name"): continue
        hg, ag, _win, _pens, _reg = _resolve_score(m)
        sh = st.get(norm(h["name"]), {}); sa = st.get(norm(a["name"]), {})

        def side(t, s):
            return {"name": t.get("name"), "code": t.get("tla") or "",
                    "group": pretty_group(s.get("group")), "pos": s.get("pos"),
                    "pld": s.get("pld", 0), "w": s.get("w", 0), "d": s.get("d", 0), "l": s.get("l", 0),
                    "gf": s.get("gf", 0), "ga": s.get("ga", 0), "gd": s.get("gd", 0),
                    "pts": s.get("pts", 0), "form": s.get("form", "")}

        out.append({"id": str(m.get("id")),
                    "stage": pretty_group(m.get("group")) or (m.get("stage", "") or "").replace("_", " ").title(),
                    "kickoff": m.get("utcDate"), "status": smap.get(m.get("status"), "UPCOMING"),
                    "minute": (m.get("minute") if isinstance(m.get("minute"), int) else None),
                    "venue": m.get("venue") or "", "home": side(h, sh), "away": side(a, sa),
                    "score": {"home": hg, "away": ag,
                              "pens": ({"home": _pens[0], "away": _pens[1]} if _pens[0] is not None else None),
                              "reg": ({"home": _reg[0], "away": _reg[1]} if _reg[0] is not None else None),
                              "winner": _win},
                    "markets": {}, "prediction": None, "h2h": [], "stats_extra": None,
                    "injuries": {"home": [], "away": []}, "lineups": None})
    return out


OPEN_FILE = f"odds_open_{COMP_KEY.lower()}.json"   # first-seen ("opening") odds, per competition
LEGACY_OPEN = "odds_open.json"
_OPEN = None

def pairkey(a, b):
    return "|".join(sorted([norm(a), norm(b)]))

def _load_open():
    global _OPEN
    if _OPEN is None:
        for path in ([OPEN_FILE, LEGACY_OPEN] if COMP_KEY == "WC" else [OPEN_FILE]):
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


def fetch_odds():
    # serve from cache to protect the free quota
    now = time.time()
    if now - _ODDS_CACHE["t"] < ODDS_CACHE_MIN * 60 and _ODDS_CACHE["data"]:
        DIAG.append("odds: served from cache")
        return _ODDS_CACHE["data"]
    out = {}
    try:
        events = _get(f"{ODDS_URL}&apiKey={ODDS_API_KEY}")
    except Exception as e:
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
                          "away_pct": round(hs["away"]/hn*100), "books": hn}
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
    return out


# ---- public-rating factors ---------------------------------------------
# Weights for the ratings-based factors (tune freely; 0 disables a factor).
# Scaled so long-term class roughly balances in-tournament results.
FACTOR_WEIGHTS = {"fifa": 0.6, "squad_value": 0.35, "star": 0.2}
RATINGS_FILE = f"ratings_{COMP_KEY.lower()}.json" if COMP_KEY != "WC" else "ratings.json"
RATINGS_FALLBACK = "ratings.json"
_RATINGS = None

def _load_ratings():
    global _RATINGS
    if _RATINGS is None:
        _RATINGS = {}
        try:
            path = RATINGS_FILE if os.path.exists(RATINGS_FILE) else RATINGS_FALLBACK
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for name, rec in raw.items():
                if isinstance(rec, dict):
                    _RATINGS[norm(name)] = rec
        except Exception as e:
            DIAG.append(f"ratings: not loaded ({e})")
    return _RATINGS

def rating_boost(name):
    """Convert public ratings (FIFA rank, squad value, star value) into
    strength points. Unknown teams get neutral mid-pack defaults."""
    r = _load_ratings().get(norm(name or "")) or {}
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
}
_WX_CACHE = {}

def venue_coords(venue):
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
            try:
                url = (f"https://api.open-meteo.com/v1/forecast?latitude={ll[0]}&longitude={ll[1]}"
                       f"&hourly=temperature_2m,wind_speed_10m,precipitation_probability"
                       f"&start_date={date}&end_date={date}&timezone=UTC")
                _WX_CACHE[ck] = _get(url)
            except Exception as e:
                DIAG.append(f"weather: FAILED — {e}"); _WX_CACHE[ck] = None
        d = _WX_CACHE[ck]
        if not d: continue
        try:
            hours = d["hourly"]["time"]
            idx = min(range(len(hours)),
                      key=lambda i: abs(datetime.datetime.fromisoformat(hours[i]).replace(tzinfo=datetime.timezone.utc) - ko))
            m["weather"] = {"temp_c": round(d["hourly"]["temperature_2m"][idx]),
                            "wind_kph": round(d["hourly"]["wind_speed_10m"][idx]),
                            "rain_pct": d["hourly"]["precipitation_probability"][idx]}
            hits += 1
        except Exception:
            continue
    if hits: DIAG.append(f"weather: {hits} matches")


def compute_rest(matches):
    """Days since each team's previous match, attached per fixture side."""
    played = {}
    for m in sorted(matches, key=lambda x: x.get("kickoff") or ""):
        for side in ("home", "away"):
            t = m[side]; k = norm(t.get("name"))
            prev = played.get(k)
            if prev and m.get("kickoff"):
                try:
                    d1 = datetime.datetime.fromisoformat(prev.replace("Z", "+00:00"))
                    d2 = datetime.datetime.fromisoformat(m["kickoff"].replace("Z", "+00:00"))
                    t["rest_days"] = max(0, round((d2 - d1).total_seconds() / 86400))
                except Exception:
                    pass
            if m.get("kickoff") and m.get("status") in ("FINISHED", "LIVE"):
                played[k] = m["kickoff"]


def rating_parts(name):
    """Class factors broken out, for attribution."""
    r = _load_ratings().get(norm(name or "")) or {}
    fifa_n = max(0.0, 10.0 - (r.get("fifa_rank", 45) - 1) * 0.18)
    val_n  = min(10.0, r.get("squad_value_m", 120) / 150.0)
    star_n = min(10.0, r.get("star_value_m", 25) / 20.0)
    w = FACTOR_WEIGHTS
    return {"fifa": fifa_n*w["fifa"], "value": val_n*w["squad_value"], "star": star_n*w["star"]}


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
    knockout = bool(stage and not stage.startswith("group"))
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
        graded = [p for p in picks.values()
                  if p.get("result") and p.get("upset_candidate") and p.get("upset_score") is not None]
        grp = [p for p in graded if float(p.get("upset_score") or 0) >= 60]
        if len(grp) < 8:
            return 0.0
        hit_rate = sum(1 for p in grp if p.get("upset_hit")) / len(grp)
        avg_prob = sum(float(p.get("upset_candidate_pct") or 0) / 100.0 for p in grp) / len(grp)
        return _clamp((hit_rate - avg_prob) * 0.25, -0.06, 0.08)
    except Exception:
        return 0.0


def _upset_adjustment(home, away, markets, m, why, blend, two_way=False):
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
    fav = "h" if hp >= ap else "a"
    dog = "a" if fav == "h" else "h"
    fav_pct = max(hp, ap)
    dog_pct = min(hp, ap)
    margin = max(0.0, fav_pct - dog_pct) / 100.0
    low_goal = _low_goal_probability(markets, blend.get("d", 0), m)
    stage = ((m or {}).get("stage") or "").lower()
    knockout = bool(stage and not stage.startswith("group"))

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
    mk = (markets or {}).get("1x2") or {}
    market_gap_pct = None
    market_gate = True
    box_score_edge = 0.0
    if mk and mk.get("home_pct") is not None and mk.get("away_pct") is not None:
        market_side = "h" if float(mk.get("home_pct") or 0) >= float(mk.get("away_pct") or 0) else "a"
        if market_side != dog:
            dog_market = float(mk.get("home_pct") if dog == "h" else mk.get("away_pct") or 0)
            fav_market = float(mk.get("home_pct") if market_side == "h" else mk.get("away_pct") or 0)
            market_gap_pct = abs(fav_market - dog_market)
            market_gate = market_gap_pct <= 12

    # A large market gap can only be overridden by real box-score dominance.
    # Pregame fixtures normally have no box score, so they stay as upset watch only.
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

    base_trigger = (dog_adj >= fav_adj - 0.05 and upset_score >= 65 and fav_adj < 0.46)
    strong_box_override = (upset_score >= 75 and box_score_edge >= 0.35)
    trigger = bool(base_trigger and (market_gate or strong_box_override))
    blocked = bool(base_trigger and not trigger)

    reasons = []
    if fav_adj < 0.46: reasons.append("favorite below 46%")
    if draw_prob >= 0.24: reasons.append("draw pressure")
    if low_goal >= 0.55: reasons.append("low-scoring profile")
    if closeness >= 0.55: reasons.append("narrow team gap")
    if dog_momentum >= 0.07: reasons.append("underdog momentum")
    if learn_bias > 0.005: reasons.append("scorecard boost")
    if blocked and market_gap_pct is not None: reasons.append(f"market gap {market_gap_pct:.0f} pts blocks override")
    if not reasons: reasons.append("favorite profile is cleaner")

    # ---- statistically-correct upset classification -----------------------
    # An upset is defined by the MARKET: the underdog is whoever the market prices
    # lower, and upset magnitude comes from the underdog's market win probability,
    # not from volatility. Thresholds match standard betting conventions.
    mkt_dog_pct = None
    if mk and mk.get("home_pct") is not None and mk.get("away_pct") is not None:
        m_side = "h" if float(mk.get("home_pct") or 0) >= float(mk.get("away_pct") or 0) else "a"
        m_dog = "a" if m_side == "h" else "h"
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
    model_dog_pct = float(adjusted.get(dog, 0) or 0)
    upset_edge = None if mkt_dog_pct is None else round(model_dog_pct - mkt_dog_pct, 1)
    # radar fires ONLY when it's a genuine underdog (not a pickem) AND the model
    # rates that underdog meaningfully above the market — a live, underpriced dog.
    radar = bool(upset_class in ("minor", "solid", "major") and (upset_edge or 0) >= 6)
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
        "box_score_edge": round(box_score_edge, 3),
        "blocked": bool(blocked),
        "triggered": bool(trigger),
        "reason": " · ".join(reasons)
    }


def predict(home, away, markets, m=None):
    two_way = not COMP.get("has_draws", True)
    def parts(s, adv):
        if not s: return {"base": 1.0, "adv": adv}
        fp = sum({"W": 3, "D": 1, "L": 0}.get(r, 0) for r in (s.get("form", "").split()))
        rest = s.get("rest_days")
        rp = rating_parts(s.get("name"))
        return {"base": 1.0, "pts": (s.get("pts") or 0)*0.6, "gd": (s.get("gd") or 0)*0.25,
                "form": fp*0.5, "adv": adv,
                "fifa": rp["fifa"], "value": rp["value"], "star": rp["star"],
                "rest": 0.0 if rest is None else max(-0.6, min(0.45, (rest - 4) * 0.15))}
    ph, pa = parts(home, 1.2), parts(away, 0.0)
    sh, sa = max(0.1, sum(ph.values())), max(0.1, sum(pa.values()))
    # Injury/availability nudge: reduce a team's strength when key players are
    # OUT. Deliberately small and capped — the market already prices injuries, and
    # we blend 50/50 with it, so this only needs to catch the rare case the odds
    # underrate. Per-sport weight: one player swings basketball far more than
    # baseball. Only hard "out" statuses count (not questionable/day-to-day).
    inj_h = inj_a = 0.0
    if m:
        w = {"NBA": 2.2, "NHL": 1.2, "NFL": 1.6, "MLB": 0.7}.get(COMP_KEY, 1.5)  # soccer default 1.5
        def _out_count(lst):
            n = 0
            for p in (lst or []):
                s = str(p).lower()
                if "(out" in s or "(inactive" in s or s.endswith("out)") or "(o)" in s:
                    n += 1
            return n
        injd = m.get("injuries") or {}
        oh, oa = _out_count(injd.get("home")), _out_count(injd.get("away"))
        # each key absence costs `w` strength pts, capped so it nudges not swings
        inj_h = min(oh, 3) * w
        inj_a = min(oa, 3) * w
        sh = max(0.1, sh - inj_h)
        sa = max(0.1, sa - inj_a)
    # factor attribution: how much each factor tilts home-vs-away (strength pts)
    keys = set(ph) | set(pa)
    why = {k: round(ph.get(k, 0) - pa.get(k, 0), 2) for k in keys if k != "base"}
    why["class"] = round(why.pop("fifa", 0) + why.pop("value", 0) + why.pop("star", 0), 2)
    if inj_h or inj_a:
        # positive = injuries hurt away more (helps home), matching other factors' sign
        why["injuries"] = round(inj_a - inj_h, 2)
    # Anomaly: one-off knockouts and extreme conditions are less predictable.
    # Take the LARGER effect, never stack — the market's odds already price
    # much of this in, and we blend with them, so stacking over-corrects.
    damp = 0.0
    if m:
        stage = (m.get("stage") or "")
        if stage and not stage.lower().startswith("group"): damp = 0.12
        wx = m.get("weather") or {}
        if wx.get("temp_c", 0) >= 32 or wx.get("wind_kph", 0) >= 30:
            damp = max(damp, 0.10)
    if damp:
        mean = (sh + sa) / 2
        sh, sa = sh + (mean - sh)*damp, sa + (mean - sa)*damp
    draw = 0.0 if two_way else 0.26
    tot = sh+sa
    model = {"h": round(sh/tot*(1-draw)*100), "a": round(sa/tot*(1-draw)*100), "d": round(draw*100)}
    mk = markets.get("1x2")
    raw_blend = ({"h": round((model["h"]+mk["home_pct"])/2), "d": round((model["d"]+mk["draw_pct"])/2),
              "a": round((model["a"]+mk["away_pct"])/2)} if mk else dict(model))
    raw_blend = _round_triplet(raw_blend)
    adjusted, upset = _upset_adjustment(home, away, markets, m, why, raw_blend, two_way=two_way)

    outcomes = ("h", "a") if two_way else ("h", "d", "a")
    base_pick = max(outcomes, key=lambda k: raw_blend[k])
    pick = upset["candidate"] if upset.get("triggered") else max(outcomes, key=lambda k: adjusted[k])
    name = {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[pick]
    edge, note = None, "no market to compare against"
    if mk:
        mm = {"h": mk["home_pct"], "d": mk["draw_pct"], "a": mk["away_pct"]}
        edge = adjusted[pick] - mm[pick]
        note = ("upset formula triggered — volatility makes the underdog playable" if upset.get("triggered")
                else "favorite, but upset watch" if upset.get("score", 0) >= 60 and pick != upset.get("candidate")
                else "model agrees with the market" if abs(edge) < 6
                else f"model rates this {'higher' if edge > 0 else 'lower'} than the market")
    elif upset.get("triggered"):
        note = "upset formula triggered — volatility makes the underdog playable"
    mkt_pull = (adjusted[pick] - model[pick]) if mk else 0
    return {"pick": pick, "pick_name": name, "confidence": adjusted[pick],
            "base_pick": base_pick, "base_pick_name": {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[base_pick],
            "model": model, "base_blend": raw_blend, "blend": adjusted, "adjusted": adjusted,
            "edge": edge, "note": note, "why": why, "damp_pct": round(damp*100),
            "mkt_pull": mkt_pull, "upset": upset}


# -------- ESPN lineups + live subs + injuries (keyless) ------------------
def _bucket(abbr):
    a = (abbr or "").upper()
    if a.startswith("G"): return "GK"
    if a.startswith("D"): return "DEF"
    if a.startswith("F"): return "FWD"
    return "MID"


def _espn_side(roster):
    starters = [p for p in roster if p.get("starter")]
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    starters.sort(key=lambda p: order[_bucket((p.get("position") or {}).get("abbreviation"))])
    xi = []
    for p in starters[:11]:
        ath = p.get("athlete") or {}
        nm = ath.get("lastName") or (ath.get("displayName") or "").split(" ")[-1]
        out = bool(p.get("subbedOut") or p.get("subbed_out"))
        xi.append({"n": p.get("jersey") or "", "name": nm, "out": out})
    return xi


def _espn_subs(d, home_name, away_name):
    subs = []
    for ev in (d.get("keyEvents") or d.get("commentary") or []):
        typ = ((ev.get("type") or {}).get("text") or ev.get("playType") or "")
        txt = (ev.get("text") or "")
        if "substitut" in (typ + " " + txt).lower():
            clk = ((ev.get("clock") or {}).get("displayValue")) or ""
            tname = ((ev.get("team") or {}).get("displayName")) or ""
            side = "home" if norm(tname) == norm(home_name) else ("away" if norm(tname) == norm(away_name) else "")
            subs.append({"min": clk, "side": side, "text": (txt or "Substitution")[:70]})
    return subs



# -------- API-FOOTBALL : box-score team statistics ------------------------
def _api_football_get(path, params=None):
    if not API_FOOTBALL_KEY:
        raise RuntimeError("missing API_FOOTBALL_KEY")
    q = urllib.parse.urlencode(params or {})
    url = API_FOOTBALL_BASE + path + (("?" + q) if q else "")
    headers = dict(UA)
    headers["x-apisports-key"] = API_FOOTBALL_KEY
    return _get(url, headers)


def _load_box_cache():
    try:
        with open(API_FOOTBALL_CACHE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("dates", {})
            d.setdefault("stats", {})
            return d
    except Exception:
        pass
    return {"dates": {}, "stats": {}}


def _save_box_cache(cache):
    try:
        tmp = API_FOOTBALL_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        os.replace(tmp, API_FOOTBALL_CACHE_FILE)
    except Exception as e:
        DIAG.append(f"box stats cache save failed: {_scrub(e)}")


def _match_date_utc(m):
    try:
        return datetime.datetime.fromisoformat((m.get("kickoff") or "").replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return ""


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


def _af_fixture_id_for_match(m, events):
    target = pair(m["home"]["name"], m["away"]["name"])
    # Exact pair first.
    for ev in events:
        teams = ev.get("teams") or {}
        hn = ((teams.get("home") or {}).get("name")) or ""
        an = ((teams.get("away") or {}).get("name")) or ""
        if hn and an and pair(hn, an) == target:
            return ((ev.get("fixture") or {}).get("id"))
    # Softer fuzzy fallback.
    for ev in events:
        teams = ev.get("teams") or {}
        hn = ((teams.get("home") or {}).get("name")) or ""
        an = ((teams.get("away") or {}).get("name")) or ""
        if (hn and an and
            ((_name_match(hn, m["home"]["name"]) and _name_match(an, m["away"]["name"])) or
             (_name_match(hn, m["away"]["name"]) and _name_match(an, m["home"]["name"])))):
            return ((ev.get("fixture") or {}).get("id"))
    return None


def fetch_api_football_box_scores(matches):
    """Attach m['stats_extra'] for LIVE and recent FINISHED soccer matches.

    API-FOOTBALL uses its own fixture ids, so we first fetch fixtures by date,
    fuzzy-match the teams, then fetch /fixtures/statistics for matched fixtures.
    Results are cached to protect the free daily request limit.
    """
    if COMP.get("sport") != "soccer":
        return
    if not API_FOOTBALL_KEY:
        DIAG.append("box stats(API-FOOTBALL): missing API_FOOTBALL_KEY")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date()
    targets = []
    for m in matches:
        status = m.get("status")
        mdate_s = _match_date_utc(m)
        if not mdate_s:
            continue
        try:
            mdate = datetime.date.fromisoformat(mdate_s)
        except Exception:
            continue
        age = (today - mdate).days
        if status == "LIVE" or (status == "FINISHED" and 0 <= age <= API_FOOTBALL_DAYS_BACK):
            targets.append(m)
    targets = sorted(targets, key=lambda x: x.get("kickoff") or "", reverse=True)[:API_FOOTBALL_MAX_STATS]
    if not targets:
        DIAG.append("box stats(API-FOOTBALL): no live/recent finished fixtures")
        return

    cache = _load_box_cache()
    attached = 0
    matched = 0
    date_requests = 0
    stat_requests = 0
    now_ts = time.time()

    events_by_date = {}
    for d in sorted({_match_date_utc(m) for m in targets if _match_date_utc(m)}):
        rec = (cache.get("dates") or {}).get(d)
        if rec and now_ts - float(rec.get("t") or 0) < 6 * 3600:
            events_by_date[d] = rec.get("events") or []
            continue
        try:
            payload = _api_football_get("/fixtures", {"date": d})
            events = payload.get("response") or []
            events_by_date[d] = events
            cache.setdefault("dates", {})[d] = {"t": now_ts, "events": events}
            date_requests += 1
        except Exception as e:
            DIAG.append(f"box stats(API-FOOTBALL): fixture date {d} FAILED — {_scrub(e)}")
            events_by_date[d] = rec.get("events") if rec else []

    for m in targets:
        d = _match_date_utc(m)
        fid = _af_fixture_id_for_match(m, events_by_date.get(d) or [])
        if not fid:
            continue
        matched += 1
        fid = str(fid)
        srec = (cache.get("stats") or {}).get(fid)
        # Final stats are stable; live stats refresh for the active match.
        live = m.get("status") == "LIVE"
        if srec and ((not live) or now_ts - float(srec.get("t") or 0) < 90):
            stats = srec.get("stats_extra")
        else:
            try:
                payload = _api_football_get("/fixtures/statistics", {"fixture": fid})
                stats = _parse_af_stats(payload, m, fid)
                cache.setdefault("stats", {})[fid] = {"t": now_ts, "stats_extra": stats}
                stat_requests += 1
            except Exception as e:
                DIAG.append(f"box stats(API-FOOTBALL): stats {fid} FAILED — {_scrub(e)}")
                stats = srec.get("stats_extra") if srec else None
        if stats:
            m["stats_extra"] = stats
            # Alias for the upset model; older patches looked at m['stats'].
            m["stats"] = stats
            attached += 1

    _save_box_cache(cache)
    DIAG.append(f"box stats(API-FOOTBALL): matched {matched}, attached {attached}, requests {date_requests}+{stat_requests}")



ESPN_STAT_MAP = {
    "totalShots": "shots", "shotsOnTarget": "shots_on_target",
    "possessionPct": "possession", "wonCorners": "corners",
    "foulsCommitted": "fouls", "offsides": "offsides", "saves": "saves",
    "yellowCards": "yellow_cards", "redCards": "red_cards",
}

def _espn_stats(d, m):
    """Parse the boxscore statistics block from an ESPN summary payload."""
    teams = ((d.get("boxscore") or {}).get("teams")) or []
    if not teams:
        # fallback: header.competitions[].competitors[].statistics
        comps = ((d.get("header") or {}).get("competitions")) or []
        alt = []
        for comp in comps:
            for c in (comp.get("competitors") or []):
                team = c.get("team") or {}
                alt.append({"team": {"displayName": team.get("displayName") or team.get("name") or ""},
                            "homeAway": c.get("homeAway"),
                            "statistics": c.get("statistics") or []})
        teams = alt
    if not teams:
        return None
    out = {"home": {}, "away": {}, "source": "ESPN"}
    got = 0
    for t in teams:
        tname = ((t.get("team") or {}).get("displayName")) or ""
        side = ("home" if _name_match(tname, m["home"]["name"])
                else "away" if _name_match(tname, m["away"]["name"])
                else (t.get("homeAway") if t.get("homeAway") in ("home", "away") else ""))
        if not side:
            continue
        for st in (t.get("statistics") or []):
            key = ESPN_STAT_MAP.get(st.get("name"))
            if key:
                out[side][key] = _num_from_stat(st.get("displayValue"))
        if out[side]:
            got += 1
    return out if got == 2 else None


def fetch_espn(matches):
    try:
        today = datetime.date.today()
        d1 = (today - datetime.timedelta(days=6)).strftime("%Y%m%d"); d2 = (today + datetime.timedelta(days=12)).strftime("%Y%m%d")
        sb = _get(f"{ESPN_SB}&dates={d1}-{d2}", UA)
    except Exception as e:
        DIAG.append(f"lineups(ESPN): scoreboard FAILED — {e}"); return

    pair_to_id = {}
    for ev in sb.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        names = {c.get("homeAway"): ((c.get("team") or {}).get("displayName"))
                 for c in comp.get("competitors", [])}
        if names.get("home") and names.get("away"):
            pair_to_id[pair(names["home"], names["away"])] = ev.get("id")
    DIAG.append(f"lineups(ESPN): scoreboard matched {len(pair_to_id)} fixtures")

    soon = sorted([m for m in matches if m["status"] in ("LIVE", "UPCOMING")],
                  key=lambda m: m["kickoff"] or "")[:14]
    recent_fin = sorted([m for m in matches if m["status"] == "FINISHED"],
                        key=lambda m: m["kickoff"] or "", reverse=True)[:20]
    soon = soon + [m for m in recent_fin if m not in soon]
    got = 0; stats_got = 0; stats_absent = 0; first = True
    for m in soon:
        eid = pair_to_id.get(pair(m["home"]["name"], m["away"]["name"]))
        if not eid: continue
        try:
            d = _get(ESPN_SUM.format(id=eid), UA)
        except Exception as e:
            if first: DIAG.append(f"lineups(ESPN): summary FAILED — {e}"); first = False
            continue
        rosters = d.get("rosters") or []
        if first:
            _bx = d.get("boxscore") or {}
            _keys = ",".join(sorted(d.keys()))[:120]
            DIAG.append(f"lineups(ESPN): sample event -> {len(rosters)} rosters, "
                        f"keyEvents={len(d.get('keyEvents') or [])}")
            DIAG.append(f"box probe: payload keys=[{_keys}]")
            DIAG.append(f"box probe: boxscore.teams={len((_bx.get('teams') or []))} "
                        f"boxscore.players={len((_bx.get('players') or []))} "
                        f"has boxscore={'boxscore' in d}")
            first = False
        hr = next((r for r in rosters if r.get("homeAway") == "home"), None)
        ar = next((r for r in rosters if r.get("homeAway") == "away"), None)
        if hr and ar and hr.get("roster") and ar.get("roster"):
            hx, ax = _espn_side(hr["roster"]), _espn_side(ar["roster"])
            if len(hx) >= 7 and len(ax) >= 7:
                m["lineups"] = {
                    "home": {"formation": hr.get("formation") or "", "xi": hx},
                    "away": {"formation": ar.get("formation") or "", "xi": ax},
                    "subs": _espn_subs(d, m["home"]["name"], m["away"]["name"]),
                }
                got += 1
        for blk in (d.get("injuries") or []):
            tn = norm((blk.get("team") or {}).get("displayName")); people = []
            for it in blk.get("injuries", []):
                ath = (it.get("athlete") or {}).get("displayName")
                stt = (it.get("status") or (it.get("type") or {}).get("description") or "out")
                if ath: people.append(f"{ath} ({stt})")
            if people:
                if tn == norm(m["home"]["name"]): m["injuries"]["home"] = people
                elif tn == norm(m["away"]["name"]): m["injuries"]["away"] = people
        if m["status"] in ("LIVE", "FINISHED") and not m.get("stats_extra"):
            sx = _espn_stats(d, m)
            if sx:
                m["stats_extra"] = sx; stats_got += 1
            else:
                stats_absent += 1
    DIAG.append(f"lineups(ESPN): attached to {got} fixtures")
    total_fin = len([m for m in matches if m["status"] in ("LIVE","FINISHED")])
    DIAG.append(f"box stats(ESPN): attached {stats_got}/{total_fin} recent"
                + (f" · no stats block on {stats_absent}" if stats_absent else "")
                + (" · none attached — check ESPN coverage for this competition" if stats_got==0 and total_fin else ""))


# -------- The Odds API : tournament winner (outrights) -------------------
def apply_market_strength(outrights):
    """For sports without squad values (NFL/NBA/MLB/NHL/NCAAF), derive team
    strength from championship odds — the market's own valuation of each team.
    A 20%-title team is objectively strong; a 0.3% team is weak. This is the
    honest equivalent of soccer squad values, sourced live from the odds you
    already fetch. Writes into the in-memory ratings so predict() uses it."""
    if COMP.get("source") not in {"sportsdataio", "balldontlie"} or not outrights:
        return
    mx = max((o["pct"] for o in outrights), default=0) or 1
    ratings = _load_ratings()  # this is the live _RATINGS dict predict() reads
    changed = 0
    for o in outrights:
        key = norm(o["team"])
        share = o["pct"] / mx
        val_m = round(share ** 0.7 * 1000)
        star_m = round(share ** 0.7 * 110)
        rec = ratings.get(key)
        if rec is None:
            rec = next((v for k, v in ratings.items()
                        if not k.startswith("_") and (key in k or k in key)), None)
        if isinstance(rec, dict):
            rec["squad_value_m"] = val_m
            rec["star_value_m"] = star_m
            rec["market_pct"] = o["pct"]
            changed += 1
    if changed:
        DIAG.append(f"market strength: enriched {changed} teams from championship odds")


def fetch_outrights(code_map):
    if not COMP.get("outright"):
        DIAG.append("title odds: no outright market for this competition"); return []
    now = time.time()
    if now - _OUT_CACHE["t"] < OUTRIGHTS_CACHE_MIN * 60 and _OUT_CACHE["data"]:
        DIAG.append("title odds: cached"); return _OUT_CACHE["data"]
    try:
        events = _get(f"{OUTRIGHTS_URL}&apiKey={ODDS_API_KEY}")
    except Exception as e:
        DIAG.append(f"title odds: FAILED — {e}"); return _OUT_CACHE["data"] or []
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
    DIAG.append(f"title odds: {len(out)} teams")
    return out


# -------- knockout bracket + best-third race ------------------------------
def build_league_table(st, name_map, code_map, zones=None):
    """One-table league standings. zones (from the competition config) marks
    European/relegation places for domestic leagues; without zones, Swiss-model
    Champions-League chips apply for 24+ team fields."""
    rows = []
    for t, r in st.items():
        # Domestic leagues should show their complete table before opening day.
        # Tournament/league-phase tables still wait for actual participation.
        if r.get("pld", 0) < 1 and not zones: continue
        rows.append({"name": name_map.get(t, t.title()), "code": code_map.get(t, ""),
                     "pld": r["pld"], "w": r["w"], "d": r["d"], "l": r["l"],
                     "gf": r["gf"], "ga": r["ga"], "gd": r["gd"], "pts": r["pts"],
                     "form": r.get("form", ""), "pos": None, "_official": r.get("pos"), "qual": ""})
    if not rows:
        return []
    rows.sort(key=lambda x: ((x.get("_official") or 99), -x["pts"], -x["gd"], -x["gf"], x["name"]))
    n = len(rows)
    season_started = any((row.get("pld") or 0) > 0 for row in rows)
    for i, row in enumerate(rows):
        row["pos"] = row.get("_official") or (i + 1)
        row.pop("_official", None)
        if zones and season_started:
            ucl, uel, rel = zones.get("ucl", 0), zones.get("uel", 0), zones.get("rel", 0)
            if i < ucl:
                row["qual"] = {"status": "UCL", "note": "Champions League places"}
            elif i < ucl + uel:
                row["qual"] = {"status": "UEL", "note": "Europa League place"}
            elif rel and i >= n - rel:
                row["qual"] = {"status": "REL", "note": "relegation zone"}
        elif n >= 24:
            if i < 8:
                row["qual"] = {"status": "R16", "note": "Top 8 — straight to the Round of 16"}
            elif i < 24:
                row["qual"] = {"status": "Playoffs", "note": "Places 9-24 enter the knockout playoff round"}
            else:
                row["qual"] = {"status": "Out", "note": "Places 25-36 are eliminated"}
    return [{"group": "League phase", "teams": rows}]


def build_bracket(raw):
    smap = {"FINISHED": "FINISHED", "IN_PLAY": "LIVE", "PAUSED": "LIVE", "LIVE": "LIVE"}
    rounds = defaultdict(list)
    for m in raw:
        rn = KO_STAGES.get(m.get("stage"))
        if not rn: continue
        h = m.get("homeTeam") or {}; a = m.get("awayTeam") or {}
        ft = (m.get("score", {}) or {}).get("fullTime", {}) or {}
        rounds[rn].append({"home": h.get("name") or "TBD", "away": a.get("name") or "TBD",
                           "score": {"home": ft.get("home"), "away": ft.get("away")},
                           "status": smap.get(m.get("status"), "UPCOMING"), "kickoff": m.get("utcDate")})
    return [{"round": rn, "matches": rounds[rn]} for rn in KO_ORDER if rounds.get(rn)]


def third_race(st, name_map, code_map):
    rows = []
    for t, r in st.items():
        if r.get("pos") == 3:
            rows.append({"team": name_map.get(t, t.title()), "code": code_map.get(t, ""),
                         "group": pretty_group(r.get("group")), "pts": r["pts"],
                         "gd": r["gd"], "gf": r["gf"]})
    rows.sort(key=lambda x: (-x["pts"], -x["gd"], -x["gf"]))
    for i, row in enumerate(rows): row["in"] = i < 8
    return rows


# -------- ESPN news + RSS feeds (keyless) : diverse updates --------------
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
    """Keep RSS diversity during --loop if one refresh only returns ESPN."""
    try:
        with open(f"data_{COMP_KEY.lower()}.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        # Files written before news was scoped by sport may contain headlines
        # inherited from whichever competition last overwrote data.json.
        if old.get("news_scope") != COMP_KEY:
            return []
        arr = old.get("news") or []
        if isinstance(arr, list):
            return arr[:80]
    except Exception:
        pass
    return []


def _balanced_news(items, limit=48):
    """Interleave sources so one outlet cannot take over the News tab."""
    cleaned, seen = [], set()
    for item in items:
        if not item.get("headline"):
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
    for item in sorted(cleaned, key=lambda x: x.get("published") or "", reverse=True):
        by_src[item.get("source") or "News"].append(item)

    # Put non-ESPN outlets first so the first screen is diverse, while ESPN remains included.
    srcs = sorted(by_src, key=lambda s: (s == "ESPN", s.lower()))
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
        if not item.get("headline"):
            return False
        item = dict(item)
        if not _news_relevant(item):
            return False
        item["source"] = _source_label(item)
        if item["source"] == "ESPN":
            return False
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
            for it in entries:
                title = _child_text(it, "title")
                if not title:
                    continue
                src = _source_from_entry(it, feed_name)
                desc = _child_text(it, "description", "summary", "content")
                pub = _child_text(it, "pubDate", "published", "updated")
                ok = add_item({"headline": _clean(title),
                               "desc": _clean(desc)[:180],
                               "published": _rfc_iso(pub) or pub,
                               "link": _entry_link(it),
                               "source": src,
                               "feed": feed_name})
                n += 1 if ok else 0
                if n >= 6:
                    break
            DIAG.append(f"news {feed_name}: {n}")
        except Exception as e:
            DIAG.append(f"news {feed_name}: FAILED — {e}")

    previous = _load_previous_news()
    current_sources = {_source_label(x) for x in items if x.get("headline")}
    previous_sources = {_source_label(x) for x in previous if x.get("headline")}

    # This is the important loop fix: a temporary RSS failure should not replace
    # a diverse feed with ESPN-only data in data.json.
    if len(current_sources) <= 1 and len(previous_sources) > 1:
        DIAG.append("news: RSS returned one source; preserved previous diverse feed")
        merged = _balanced_news(items + previous, limit=48)
    else:
        merged = _balanced_news(items + previous, limit=48)
        if previous and previous_sources - current_sources:
            DIAG.append("news: merged previous feed to preserve source diversity")

    DIAG.append("news sources: " + ", ".join(sorted({_source_label(x) for x in merged})[:12]))
    _NEWS_CACHE["t"] = now; _NEWS_CACHE["data"] = merged
    return merged

# -------------------------------------------------------------------------


# ---- player database (accumulates from lineups + results, per competition) ----
PLAYER_DB_FILE = f"player_db_{COMP_KEY.lower()}.json"

def _formation_roles(formation, n_players):
    """Map XI list order to roles using the formation string.
    Convention across feeds: GK first, then defenders, mids, forwards per formation
    segments, e.g. '4-2-3-1' -> 1 GK, 4 DEF, then mids, last segment FWD."""
    try:
        segs = [int(x) for x in str(formation or "").split("-") if x.strip().isdigit()]
    except Exception:
        segs = []
    roles = ["GK"]
    if segs and sum(segs) == n_players - 1:
        for i, seg in enumerate(segs):
            role = "DEF" if i == 0 else ("FWD" if i == len(segs) - 1 else "MID")
            roles += [role] * seg
    else:
        roles += ["DEF"] * 4 + ["MID"] * 3 + ["FWD"] * (max(0, n_players - 8))
    return roles[:n_players]

def _load_player_db():
    try:
        with open(PLAYER_DB_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {"_matches": [], "players": {}}

def update_player_db(matches):
    """Fold finished matches' lineups + scores into the per-competition player DB.
    Tracks apps, starts, clean sheets (team conceded 0 while player started),
    and role from the formation. Idempotent per match id."""
    if COMP["sport"] != "soccer":
        return None
    db = _load_player_db()
    seen = set(db.get("_matches", []))
    added = 0
    for m in matches:
        mid = str(m.get("id"))
        if m.get("status") != "FINISHED" or mid in seen:
            continue
        sc = m.get("score") or {}
        if sc.get("home") is None:
            continue
        lus = m.get("lineups") or {}
        got_any = False
        for side, opp_goals, team in (("home", sc.get("away"), m["home"]["name"]),
                                      ("away", sc.get("home"), m["away"]["name"])):
            lu = lus.get(side) or {}
            xi = lu.get("xi") or []
            if not xi:
                continue
            roles = _formation_roles(lu.get("formation"), len(xi))
            cs = (opp_goals == 0)
            for idx, p in enumerate(xi):
                nm = (p.get("name") or "").strip()
                if not nm:
                    continue
                key = norm(nm) + "|" + norm(team)
                rec = db["players"].setdefault(key, {"name": nm, "team": team,
                                                     "role": roles[idx] if idx < len(roles) else "MID",
                                                     "apps": 0, "starts": 0, "clean_sheets": 0})
                rec["apps"] += 1; rec["starts"] += 1
                if cs and roles[idx] in ("GK", "DEF"):
                    rec["clean_sheets"] += 1
                got_any = True
        if got_any:
            seen.add(mid); added += 1
    db["_matches"] = sorted(seen)
    if added:
        with open(PLAYER_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=1)
    DIAG.append(f"player db: {len(db['players'])} players from {len(seen)} matches (+{added} new)")
    return db


def build_team_of_tournament(matches, scorers, standings):
    """Honest impact XI from real data: players ranked by goals, assists and team
    strength, grouped by their REAL positions (from football-data). Lines we have
    no data for (e.g. goalkeepers rarely score) are simply not shown — we never
    relabel an attacker into a fake slot."""
    if not scorers:
        return None
    def role_of(p):
        pos = (p.get("position") or "").lower()
        if "keeper" in pos or pos == "goalkeeper": return "GK"
        if "defen" in pos or "back" in pos: return "DEF"
        if "midfield" in pos: return "MID"
        if pos: return "FWD"
        return "FWD"  # scorers with unknown position are overwhelmingly attackers
    ranked = []
    for s in scorers:
        g, a = s.get("goals", 0), s.get("assists", 0)
        pld = max(1, s.get("played", 1))
        impact = g * 3 + a * 2
        score = impact + (impact / pld) * 2.0 + rating_boost(s.get("team")) * 0.4
        ranked.append({"name": s.get("name"), "team": s.get("team"), "code": s.get("code"),
                       "goals": g, "assists": a, "played": s.get("played", 0),
                       "role": role_of(s), "score": round(score, 1)})
    ranked.sort(key=lambda x: -x["score"])
    caps = {"FWD": 3, "MID": 4, "DEF": 4, "GK": 1}
    xi = []
    for role, cap in caps.items():
        xi += [p for p in ranked if p["role"] == role][:cap]
    bench = [p for p in ranked if p not in xi][:5]
    # fill missing DEF/GK from the player DB via clean sheets (real defensive data)
    db = _load_player_db()
    if db.get("players"):
        have = {p["role"]: sum(1 for q in xi if q["role"] == p["role"]) for p in xi}
        pool = sorted(db["players"].values(),
                      key=lambda r: (-r.get("clean_sheets", 0), -r.get("starts", 0)))
        xi_names = {norm(p["name"] or "") for p in xi}
        for role, cap in (("DEF", 4), ("GK", 1)):
            need = cap - sum(1 for q in xi if q["role"] == role)
            for r in pool:
                if need <= 0: break
                if r.get("role") != role or r.get("clean_sheets", 0) < 1: continue
                if norm(r["name"]) in xi_names: continue
                xi.append({"name": r["name"], "team": r["team"], "code": "",
                           "goals": 0, "assists": 0, "played": r.get("starts", 0),
                           "role": role, "score": r.get("clean_sheets", 0),
                           "cs": r.get("clean_sheets", 0)})
                xi_names.add(norm(r["name"])); need -= 1
    DIAG.append(f"team of tournament: {len(xi)} players "
                f"({', '.join(sorted(set(p['role'] for p in xi)))})")
    return {"xi": xi, "bench": bench, "v": 2,
            "note": "Attack ranked by goals, assists and team strength. Defence and goalkeeper ranked by clean sheets from accumulated lineups — real defensive data, honestly sourced."}

def fetch_scorers():
    try:
        d = _get(f"{FD_BASE}/competitions/{COMP["fd"]}/scorers?limit=20", {"X-Auth-Token": FOOTBALL_DATA_KEY})
    except Exception as e:
        DIAG.append(f"scorers: FAILED — {e}"); return []
    out = []
    for s in d.get("scorers", []):
        pl = s.get("player", {}) or {}; tm = s.get("team", {}) or {}
        out.append({"name": pl.get("name"), "team": tm.get("name"), "code": tm.get("tla") or "",
                    "goals": s.get("goals") or 0, "assists": s.get("assists") or 0,
                    "played": s.get("playedMatches") or 0,
                    "position": pl.get("position") or pl.get("section") or ""})
    DIAG.append(f"scorers: {len(out)}")
    return out


PICKS_FILE = f"picks_log_{COMP_KEY.lower()}.json"   # committed picks, per competition
LEGACY_PICKS = "picks_log.json"

def _load_picks():
    for path in ([PICKS_FILE, LEGACY_PICKS] if COMP_KEY == "WC" else [PICKS_FILE]):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}

def _save_picks(p):
    try:
        tmp = PICKS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
        os.replace(tmp, PICKS_FILE)
    except Exception as e:
        DIAG.append(f"picks save failed: {e}")

def _market_fields(pr, mk):
    """Derive the market-comparison fields for a pick from current market odds.
    Shared by the initial lock and the later backfill (odds often aren't fetched
    yet when a pick first locks, since fetch_odds() is gated to near kickoff)."""
    market_pick = market_pct = value_side = value_edge = value_mkt = None
    if mk.get("home_pct") is not None:
        trio = {"h": mk["home_pct"], "d": mk["draw_pct"], "a": mk["away_pct"]}
        market_pick = max(trio, key=trio.get); market_pct = trio[market_pick]
        # parallel value signal: biggest model-vs-market gap, if it clears +6
        edges = {k: (pr.get("model") or {}).get(k, 0) - trio[k] for k in trio}
        vs = max(edges, key=edges.get)
        if edges[vs] >= 6:
            value_side, value_edge, value_mkt = vs, round(edges[vs]), trio[vs]
    return market_pick, market_pct, value_side, value_edge, value_mkt


def update_scorecard(matches):
    """Lock a pick the first time we see an upcoming match; grade it once finished.
    Picks themselves are never rewritten — but market comparison fields backfill
    once odds appear, since a pick often locks well before its 24h odds window."""
    picks = _load_picks(); dirty = False
    for m in matches:
        mid = str(m.get("id"))
        pr = m.get("prediction"); mk = (m.get("markets") or {}).get("1x2") or {}
        if m.get("status") == "UPCOMING" and pr and mid not in picks:
            market_pick, market_pct, value_side, value_edge, value_mkt = _market_fields(pr, mk)
            upset = pr.get("upset") or {}
            probs = pr.get("adjusted") or pr.get("blend") or pr.get("model") or {}
            picks[mid] = {"home": m["home"]["name"], "away": m["away"]["name"],
                          "stage": m.get("stage"), "kickoff": m.get("kickoff"),
                          "pick": pr.get("pick"), "pick_name": pr.get("pick_name"),
                          "confidence": pr.get("confidence"), "edge": pr.get("edge"),
                          "base_pick": pr.get("base_pick"), "base_pick_name": pr.get("base_pick_name"),
                          "probs": {"h": probs.get("h"), "d": probs.get("d"), "a": probs.get("a")},
                          "market_pick": market_pick, "market_pct": market_pct,
                          "pick_mkt": ({"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}.get(pr.get("pick"))
                                       if mk.get("home_pct") is not None else None),
                          "value_side": value_side, "value_edge": value_edge, "value_mkt": value_mkt,
                          "value_name": ({"h": m["home"]["name"], "a": m["away"]["name"], "d": "Draw"}.get(value_side) if value_side else None),
                          "upset_candidate": upset.get("candidate"), "upset_name": upset.get("candidate_name"),
                          "upset_score": upset.get("score"), "upset_candidate_pct": upset.get("candidate_pct"),
                          "upset_triggered": upset.get("triggered"), "upset_temperature": upset.get("temperature"),
                          "upset_reason": upset.get("reason"),
                          # ---- deep-dive capture (evidence for later analysis) ----
                          "factor_snapshot": {k: round(float(v), 2) for k, v in (pr.get("why") or {}).items()},
                          "market_snapshot": ({"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}
                                              if mk.get("home_pct") is not None else None),
                          "market_gap": upset.get("market_gap_pct"),
                          "upset_snapshot": {"candidate": upset.get("candidate_name"),
                                             "class": upset.get("upset_class"),
                                             "market_dog_pct": upset.get("market_dog_pct"),
                                             "model_dog_pct": upset.get("model_dog_pct"),
                                             "upset_edge": upset.get("upset_edge"),
                                             "radar": upset.get("radar"),
                                             "gate": "open" if upset.get("triggered") else ("blocked" if upset.get("blocked") else "none"),
                                             "box_score_edge": upset.get("box_score_edge")},
                          "box_score_available": bool(m.get("stats_extra") or m.get("stats")),
                          "damp_pct": pr.get("damp_pct"), "mkt_pull": pr.get("mkt_pull"),
                          "model_ver": "v3-upset", "result": None}
            dirty = True
        elif (m.get("status") == "UPCOMING" and mid in picks and picks[mid].get("result") is None
              and picks[mid].get("market_pick") is None and mk.get("home_pct") is not None):
            # odds weren't available when this pick locked (fetch_odds() only runs
            # within 24h of kickoff) — backfill the market-comparison fields now
            # that they exist. The pick itself (side/confidence) never changes.
            rec = picks[mid]
            market_pick, market_pct, value_side, value_edge, value_mkt = _market_fields(pr or {}, mk)
            rec["market_pick"] = market_pick; rec["market_pct"] = market_pct
            rec["pick_mkt"] = ({"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}.get(rec.get("pick"))
                                if mk.get("home_pct") is not None else None)
            rec["value_side"] = value_side; rec["value_edge"] = value_edge; rec["value_mkt"] = value_mkt
            rec["value_name"] = ({"h": rec["home"], "a": rec["away"], "d": "Draw"}.get(value_side) if value_side else None)
            rec["market_snapshot"] = {"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}
            dirty = True
        elif (m.get("status") == "FINISHED" and mid in picks and picks[mid].get("result") is not None
              and (m.get("score") or {}).get("reg")):
            # one-time correction: regrade to the 90-minute market if the old rule differed
            reg = m["score"]["reg"]
            if reg.get("home") is not None:
                res90 = ("h" if reg["home"] > reg["away"] else "a" if reg["away"] > reg["home"] else "d")
                rec = picks[mid]
                if rec.get("result") != res90:
                    rec["result"] = res90
                    rec["model_hit"] = (rec.get("pick") == res90)
                    if rec.get("market_pick"):
                        rec["market_hit"] = (rec.get("market_pick") == res90)
                    DIAG.append(f"regraded to 90-min market: {rec.get('home','?')} v {rec.get('away','?')} -> {res90}")
                    dirty = True
        elif m.get("status") == "FINISHED" and mid in picks and picks[mid].get("result") is None:
            sc_obj = (m.get("score") or {})
            sh = sc_obj.get("home"); sa = sc_obj.get("away")
            if sh is None or sa is None:
                continue
            # 1X2 settles on the 90-minute result: level after regulation = DRAW wins,
            # regardless of extra time or penalties (the market convention)
            reg = sc_obj.get("reg") or {}
            r9h = reg.get("home"); r9a = reg.get("away")
            if r9h is not None and r9a is not None:
                res = "h" if r9h > r9a else "a" if r9a > r9h else "d"
            else:
                res = sc_obj.get("winner") or ("h" if sh > sa else "a" if sa > sh else "d")
            rec = picks[mid]
            pens = sc_obj.get("pens")
            score_str = f"{sh}-{sa}" + (f" ({pens['home']}-{pens['away']} pens)" if pens else "")
            # consistency guard: a shown scoreline that is NOT level cannot grade as a
            # draw. Only a genuine pens/ET game (level in regulation) may be a draw.
            if res == "d" and sh != sa and not pens:
                res = "h" if sh > sa else "a"
            rec["result"] = res; rec["score"] = score_str
            rec["model_hit"] = (rec.get("pick") == res)
            rec["market_hit"] = (rec.get("market_pick") == res) if rec.get("market_pick") else None
            if rec.get("upset_candidate"):
                rec["upset_hit"] = (rec.get("upset_candidate") == res)
            probs = rec.get("probs") or {}
            if probs:
                y = {"h": 1.0 if res == "h" else 0.0, "d": 1.0 if res == "d" else 0.0, "a": 1.0 if res == "a" else 0.0}
                try:
                    rec["brier3"] = round(sum(((float(probs.get(k) or 0) / 100.0) - y[k]) ** 2 for k in ("h", "d", "a")), 3)
                    rec["log_loss"] = round(-math.log(max(0.001, float(probs.get(res) or 0) / 100.0)), 3)
                except Exception:
                    pass
            # closing-line value: did the market move toward our pick after we locked it?
            if rec.get("value_side"):
                rec["value_hit"] = (rec["value_side"] == res)
            close = (_load_open().get(pairkey(rec["home"], rec["away"])) or {}).get("last")
            if close and rec.get("pick_mkt") is not None and rec.get("pick") in ("h", "d", "a"):
                rec["clv"] = round(close[rec["pick"]] - rec["pick_mkt"], 1)
            dirty = True
    if dirty:
        _save_picks(picks)
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
                _p["result"] = "h" if _h > _a else "a"
                if "pick" in _p:
                    _p["model_hit"] = (_p.get("pick") == _p["result"])
                if _p.get("market_pick"):
                    _p["market_hit"] = (_p.get("market_pick") == _p["result"])
                healed = True
    if healed:
        _save_picks(picks)
        DIAG.append("scorecard: healed legacy draw mis-gradings")
    graded = [p for p in picks.values() if p.get("result")]
    mk_graded = [p for p in graded if p.get("market_hit") is not None]
    disagree = [p for p in graded if p.get("market_pick") and p.get("pick") != p.get("market_pick")]
    rows = sorted(picks.values(), key=lambda p: p.get("kickoff") or "", reverse=True)
    # Brier score on the pick side (0 = perfect, <0.2 = well calibrated)
    briers = [((p.get("confidence") or 0)/100.0 - (1.0 if p.get("model_hit") else 0.0))**2 for p in graded]
    briers3 = [p.get("brier3") for p in graded if p.get("brier3") is not None]
    logloss = [p.get("log_loss") for p in graded if p.get("log_loss") is not None]
    upset_watched = [p for p in graded if p.get("upset_candidate")]
    upset_triggered = [p for p in upset_watched if p.get("upset_triggered")]
    # calibration bands: stated confidence vs actual hit rate
    bands = [("<45", 0, 45), ("45-55", 45, 55), ("55-65", 55, 65), ("65+", 65, 101)]
    calib = []
    for lbl, lo, hi in bands:
        grp = [p for p in graded if lo <= (p.get("confidence") or 0) < hi]
        if grp: calib.append({"band": lbl, "n": len(grp), "hits": sum(1 for p in grp if p.get("model_hit"))})
    clvs = [p["clv"] for p in graded if p.get("clv") is not None]
    vals = [p for p in graded if p.get("value_side")]
    chances = [p for p in vals if p.get("value_side") != p.get("pick")]
    def _vs(grp):
        return {"n": len(grp), "hits": sum(1 for p in grp if p.get("value_hit")),
                "be": round(sum(p.get("value_mkt") or 0 for p in grp)/len(grp)) if grp else None}
    # signal quality: when a factor favored our pick, did the pick hit?
    def _signal(name):
        rel = [p for p in graded if isinstance(p.get("factor_snapshot"), dict)
               and abs(float(p["factor_snapshot"].get(name, 0))) >= 0.5]
        favored = [p for p in rel if (float(p["factor_snapshot"].get(name, 0)) > 0) == (p.get("pick") == "h")]
        return {"n": len(favored), "hits": sum(1 for p in favored if p.get("model_hit"))} if favored else {"n": 0, "hits": 0}
    signal_quality = {k: _signal(k) for k in ("class", "form", "gd", "rest", "pts")}
    # error review: recent misses with their captured evidence
    misses = [{"home": p.get("home"), "away": p.get("away"), "pick": p.get("pick"),
               "score": p.get("score"), "upset": (p.get("upset_snapshot") or {}).get("candidate"),
               "gap": p.get("market_gap")}
              for p in sorted(graded, key=lambda x: x.get("kickoff") or "", reverse=True)
              if not p.get("model_hit")][:10]
    value_summary = {"all": _vs(vals), "chances": _vs(chances),
                     "pending": sum(1 for p in picks.values() if p.get("value_side") and not p.get("result"))}
    upset_summary = {
        "watched": len(upset_watched),
        "hits": sum(1 for p in upset_watched if p.get("upset_hit")),
        "triggered": len(upset_triggered),
        "triggered_hits": sum(1 for p in upset_triggered if p.get("upset_hit")),
        "avg_score": round(sum(float(p.get("upset_score") or 0) for p in upset_watched)/len(upset_watched), 1) if upset_watched else None
    }
    _mh = sum(1 for p in graded if p.get("model_hit"))
    DIAG.append(f"scorecard record: {_mh}/{len(graded)} model hits")
    return {"graded": len(graded), "pending": len(picks) - len(graded),
            "model_hits": _mh,
            "market_graded": len(mk_graded),
            "market_hits": sum(1 for p in mk_graded if p.get("market_hit")),
            "disagree": len(disagree),
            "disagree_hits": sum(1 for p in disagree if p.get("model_hit")),
            "brier": round(sum(briers)/len(briers), 3) if briers else None,
            "brier3": round(sum(briers3)/len(briers3), 3) if briers3 else None,
            "log_loss": round(sum(logloss)/len(logloss), 3) if logloss else None,
            "calibration": calib,
            "clv_n": len(clvs), "clv_avg": round(sum(clvs)/len(clvs), 1) if clvs else None,
            "clv_beat": sum(1 for c in clvs if c > 0),
            "value": value_summary, "signal_quality": signal_quality, "misses": misses, "upset": upset_summary,
            "picks": rows[:80]}


def qual_scenarios(teams, third_in=None, third_out=None):
    """Top-2 qualification status per team, reconciled with the best-thirds race."""
    def rem(t): return max(0, 3 - (t.get("pld") or 0))
    def guaranteed(t, others):
        P = t["pts"]; return sum(1 for o in others if o["pts"] + 3*rem(o) > P) <= 1
    def eliminated(t, others):
        maxT = t["pts"] + 3*rem(t); return sum(1 for o in others if o["pts"] > maxT) >= 2
    for t in teams:
        others = [o for o in teams if o is not t]
        if guaranteed(t, others):
            t["qual"] = {"status": "q", "note": "Through"}
        elif eliminated(t, others):
            nk = norm(t.get("name"))
            if third_in and nk in third_in:
                t["qual"] = {"status": "q", "note": "Through as 3rd"}
            elif third_out is not None and nk not in (third_in or set()) and nk in third_out:
                t["qual"] = {"status": "out", "note": "Out — 3rd-place race"}
            elif (t.get("pos") == 3 and third_in is None):
                t["qual"] = {"status": "live", "note": "In 3rd-place race"}
            else:
                t["qual"] = {"status": "out", "note": "Eliminated"}
        else:
            note = "In contention"
            if rem(t) > 0:
                t2 = {**t, "pts": t["pts"] + 3, "pld": (t.get("pld") or 0) + 1}
                if guaranteed(t2, others):
                    note = "Win to go through"
            t["qual"] = {"status": "live", "note": note}
    return teams




def _espn_seed_chip(seed):
    if not seed:
        return ""
    if COMP_KEY == "NBA":
        if seed <= 6: return {"status": f"Seed {seed}", "note": "direct playoff seed"}
        if seed <= 10: return {"status": "Play-in", "note": "seeds 7-10 enter the play-in tournament"}
        return ""
    if seed <= 7: return {"status": f"Seed {seed}", "note": "current playoff seed"}
    return ""


def fetch_espn_rankings():
    """College rankings used as a public rating input and Top 25 display.

    College football also receives a projected 12-team CFP path. NCAAM never
    consumes an editorial bracket here; its field is built from raw team data.
    """
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{COMP['sport']}/{COMP['espn']}/rankings")
    try:
        d = _get(url)
    except Exception as e:
        DIAG.append(f"rankings: FAILED — {e}")
        return [], None
    polls = d.get("rankings") or []
    poll = next((p for p in polls if "CFP" in (p.get("name") or "").upper() or "PLAYOFF" in (p.get("name") or "").upper()), None)            or next((p for p in polls if "AP" in (p.get("name") or "").upper()), None)            or (polls[0] if polls else None)
    if not poll:
        DIAG.append("rankings: none published yet")
        return [], None
    ranks = []
    for r in (poll.get("ranks") or [])[:25]:
        team = r.get("team") or {}
        ranks.append({"rank": r.get("current"), "name": team.get("displayName") or team.get("name") or "",
                      "code": team.get("abbreviation") or "", "record": r.get("recordSummary") or ""})
    DIAG.append(f"rankings: {poll.get('name')} — {len(ranks)} teams")
    # self-maintaining ratings: rank feeds the model exactly like fifa_rank
    try:
        ratings = {"_note": f"Auto-refreshed each fetch from {poll.get('name')} — do not hand-edit ranks; "
                            "they are overwritten. Unranked teams default to rank 40 in the model."}
        for r in ranks:
            if r["rank"] and r["name"]:
                ratings[r["name"]] = {"fifa_rank": int(r["rank"]), "squad_value_m": 0, "star_value_m": 0}
        with open(RATINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(ratings, f, indent=1, ensure_ascii=False)
    except Exception as e:
        DIAG.append(f"rankings->ratings write skipped: {e}")
    # projected CFP bracket: straight seeding, seeds 1-4 byes, 5v12 6v11 7v10 8v9
    bracket = None
    if COMP_KEY == "NCAAF" and len(ranks) >= 12:
        top = ranks[:12]
        def mrow(a, b):
            return {"home": f"({a['rank']}) {a['name']}", "away": f"({b['rank']}) {b['name']}",
                    "score": {"home": None, "away": None}, "status": "UPCOMING", "kickoff": None}
        first = [mrow(top[4], top[11]), mrow(top[5], top[10]), mrow(top[6], top[9]), mrow(top[7], top[8])]
        byes = [{"home": f"({t['rank']}) {t['name']}", "away": "First-round winner",
                 "score": {"home": None, "away": None}, "status": "UPCOMING", "kickoff": None} for t in top[:4]]
        bracket = [{"round": "CFP First Round (projection)", "matches": first},
                   {"round": "CFP Quarter-finals (projection)", "matches": byes},
                   {"round": "Semi-finals (projection)", "matches": []},
                   {"round": "Championship (projection)", "matches": []}]
    return ranks, bracket


LEADER_CATEGORY_KEYS = {
    "NFL": ["passingYards", "passingTouchdowns", "rushingYards", "receivingYards"],
    "NCAAF": ["passingYards", "passingTouchdowns", "rushingYards", "receivingYards"],
    "NCAAM": ["pointsPerGame", "reboundsPerGame", "assistsPerGame", "blocksPerGame"],
    "NBA": ["pointsPerGame", "reboundsPerGame", "assistsPerGame", "blocksPerGame"],
    "MLB": ["homeRuns", "avg", "RBIs", "strikeouts"],
    "NHL": ["points", "goals", "assists", "savePct"],
}


def fetch_espn_leaders():
    """Return a compact, sport-native season-leader snapshot for the UI."""
    wanted = LEADER_CATEGORY_KEYS.get(COMP_KEY)
    if not wanted:
        return {}
    now_year = datetime.datetime.now(datetime.timezone.utc).year
    for season in (now_year, now_year - 1):
        url = (f"https://sports.core.api.espn.com/v2/sports/{COMP['sport']}"
               f"/leagues/{COMP['espn']}/seasons/{season}/types/2/leaders"
               "?lang=en&region=us")
        try:
            raw = _get(url, UA)
        except Exception as e:
            DIAG.append(f"espn leaders {season}: FAILED — {e}")
            continue
        categories = {c.get("name"): c for c in (raw.get("categories") or [])}
        if not any((categories.get(key) or {}).get("leaders") for key in wanted):
            DIAG.append(f"espn leaders {season}: no populated categories")
            continue
        out = []
        for key in wanted:
            category = categories.get(key) or {}
            rows = []
            for leader in (category.get("leaders") or [])[:3]:
                ref = ((leader.get("athlete") or {}).get("$ref") or "").replace("http://", "https://")
                if not ref:
                    continue
                try:
                    athlete = _get(ref, UA)
                except Exception:
                    continue
                name = athlete.get("displayName") or athlete.get("fullName")
                if name:
                    rows.append({"name": name, "value": leader.get("displayValue") or leader.get("value")})
            if rows:
                out.append({
                    "key": key,
                    "label": category.get("displayName") or key,
                    "abbr": category.get("shortDisplayName") or category.get("abbreviation") or "",
                    "leaders": rows,
                })
        if out:
            DIAG.append(f"espn leaders: {len(out)} categories for {season}")
            return {"season": season, "source": "ESPN", "categories": out}
    return {}


def fetch_espn_standings():
    """Standings for ESPN-sourced sports (NFL, NBA, NCAAF). Returns
    (st_for_model, standings_payload). Maps US-sport records onto the fields the
    model reads: pts ~ wins*3+ties, gd ~ point differential scaled, form from streak."""
    url = (f"https://site.api.espn.com/apis/v2/sports/{COMP['sport']}/{COMP['espn']}/standings")
    try:
        d = _get(url)
    except Exception as e:
        DIAG.append(f"espn standings: FAILED — {e}")
        return {}, []
    st, payload = {}, []
    groups = d.get("children") or []
    for conf in groups:
        for div in (conf.get("children") or [conf]):
            div_name = div.get("name") or conf.get("name") or "League"
            rows = []
            for e in ((div.get("standings") or {}).get("entries")) or []:
                team = e.get("team") or {}
                name = team.get("displayName") or ""
                stats = {s.get("name"): s for s in (e.get("stats") or [])}
                def val(k, default=0):
                    v = (stats.get(k) or {}).get("value")
                    return default if v is None else v
                w, l, t = int(val("wins")), int(val("losses")), int(val("ties"))
                diff = float(val("pointDifferential"))
                win_pct = float(val("winPercent", (w / max(1, w + l + t))))
                league_win_pct = float(val("leagueWinPercent", win_pct))
                avg_pf = float(val("avgPointsFor", 0))
                avg_pa = float(val("avgPointsAgainst", 0))
                # ESPN reports per-game differential for NBA, season total for NFL —
                # normalize both onto the model's soccer-like scale
                gd_model = round(diff if abs(diff) <= 20 else diff / 10.0, 1)
                seed = int(val("playoffSeat", 0) or val("playoffSeed", 0))
                streak = float(val("streak"))
                form = (("W " * min(5, int(abs(streak)))) if streak > 0
                        else ("L " * min(5, int(abs(streak))))).strip()
                key = norm(name)
                pld = w + l + t
                # normalize points to a ~14-game baseline so an 82-game NBA season
                # and a 17-game NFL season feed the model on the same scale
                pts_model = round((w * 3 + t) * 14.0 / max(1, pld), 1) if pld else 0
                st[key] = {"group": div_name, "pld": pld, "w": w, "d": t, "l": l,
                           "gf": int(val("pointsFor")), "ga": int(val("pointsAgainst")),
                           "gd": gd_model, "pts": pts_model,
                           "form": form, "pos": None, "win_pct": win_pct,
                           "league_win_pct": league_win_pct, "avg_pf": avg_pf, "avg_pa": avg_pa}
                rows.append({"name": name, "code": team.get("abbreviation") or "",
                             "pos": None, "pld": w + l + t, "w": w, "d": t, "l": l,
                             "gf": int(val("pointsFor")), "ga": int(val("pointsAgainst")),
                             "gd": int(diff), "pts": w * 3 + t, "form": form,
                             "record": f"{w}-{l}" + (f"-{t}" if t else ""),
                             "win_pct": win_pct, "league_win_pct": league_win_pct,
                             "avg_pf": avg_pf, "avg_pa": avg_pa,
                             "qual": (_espn_seed_chip(seed))})
            rows.sort(key=lambda x: (-x["pts"], -x["gd"]))
            for i, r in enumerate(rows): r["pos"] = i + 1
            if rows:
                payload.append({"group": div_name, "teams": rows})
    DIAG.append(f"espn standings: {sum(len(g['teams']) for g in payload)} teams in {len(payload)} divisions")
    return st, payload


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


def fetch_espn_fixtures():
    """Fixture source for sports football-data doesn't carry (NFL, NBA, …).
    Produces the same match shape the UI already reads."""
    today = datetime.date.today()
    if COMP_KEY == "NCAAM":
        # This ESPN league accepts month/season dates but rejects date ranges.
        # Pull the previous/current/next month so live and near-term games stay
        # complete without requesting an entire 5,000+ game season.
        events_by_id = {}
        for offset in (-1, 0, 1):
            anchor = (today.replace(day=15) + datetime.timedelta(days=32 * offset)).replace(day=1)
            try:
                month = _get(ESPN_SB + f"&groups=50&limit=1000&dates={anchor.strftime('%Y%m')}")
                for ev in (month.get("events") or []):
                    events_by_id[str(ev.get("id"))] = ev
            except Exception as e:
                DIAG.append(f"espn fixtures {anchor.strftime('%Y-%m')}: FAILED — {e}")
        d = {"events": list(events_by_id.values())}
    else:
        d1 = (today - datetime.timedelta(days=8)).strftime("%Y%m%d")
        d2 = (today + datetime.timedelta(days=30)).strftime("%Y%m%d")
        try:
            d = _get(ESPN_SB + f"&dates={d1}-{d2}")
        except Exception as e:
            DIAG.append(f"espn fixtures: FAILED — {e}"); return []
    out = []
    for ev in d.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        home = away = None
        for c in comp.get("competitors", []):
            team = c.get("team") or {}
            side = {"name": team.get("displayName"), "code": team.get("abbreviation") or "",
                    "pts": None, "gd": None, "form": "", "pos": None, "group": None}
            sc = c.get("score")
            try: side["_score"] = int(sc) if sc not in (None, "") else None
            except (TypeError, ValueError): side["_score"] = None
            if c.get("homeAway") == "home": home = side
            else: away = side
        if not home or not away or not home["name"] or not away["name"]:
            continue
        st = ((ev.get("status") or {}).get("type") or {})
        state = st.get("state")
        status = "LIVE" if state == "in" else "FINISHED" if state == "post" else "UPCOMING"
        minute = (ev.get("status") or {}).get("displayClock") if status == "LIVE" else None
        wk = (ev.get("week") or {}).get("number")
        out.append({"id": str(ev.get("id")), "stage": (f"Week {wk}" if wk else COMP["label"]),
                    "venue": ((comp.get("venue") or {}).get("fullName") or ""),
                    "kickoff": ev.get("date"), "status": status, "minute": minute,
                    "score": {"home": home.pop("_score"), "away": away.pop("_score")},
                    "home": home, "away": away, "markets": {}, "lineups": None,
                    "h2h": [], "injuries": {"home": [], "away": []}})
    DIAG.append(f"espn fixtures: {len(out)}")
    return out


def fetch_sportsdataio_bundle():
    """Fetch licensed US/college schedules and standings in Matchday shapes."""
    adapter = SportsDataIOAdapter(SPORTSDATAIO_KEY, COMP_KEY)
    all_matches = adapter.schedule()
    today = datetime.datetime.now(datetime.timezone.utc)
    start = today - datetime.timedelta(days=8)
    end = today + datetime.timedelta(days=45)
    matches = []
    for match in all_matches:
        try:
            kickoff = datetime.datetime.fromisoformat((match.get("kickoff") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if start <= kickoff <= end:
            matches.append(match)
    st, tables = adapter.standings()
    # Provider adapters do not know Matchday's punctuation-insensitive keying.
    st = {norm(name): row for name, row in st.items()}
    DIAG.append(f"SportsDataIO fixtures: {len(matches)} in display window ({len(all_matches)} season total)")
    DIAG.append(f"SportsDataIO standings: {sum(len(g.get('teams') or []) for g in tables)} teams")
    try:
        attached = adapter.attach_availability(matches)
        DIAG.append(f"SportsDataIO availability: {attached} player labels")
    except ProviderError as exc:
        DIAG.append(f"SportsDataIO availability unavailable on this plan: {_scrub(exc)}")
    return adapter, matches, st, tables


def fetch_balldontlie_bundle():
    """Fetch real free-tier schedules/scores without paid-only substitutions."""
    adapter = BallDontLieAdapter(BALLDONTLIE_KEY, COMP_KEY)
    cache_file = f"balldontlie_games_{COMP_KEY.lower()}_cache.json"
    matches = None
    try:
        if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < BALLDONTLIE_CACHE_MIN * 60:
            with open(cache_file, encoding="utf-8") as handle:
                matches = json.load(handle)
            DIAG.append("BALLDONTLIE fixtures: local cache")
    except Exception:
        matches = None
    if matches is None:
        try:
            matches = adapter.schedule()
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(matches, handle, ensure_ascii=False)
            os.replace(tmp, cache_file)
        except ProviderError:
            # A stale cache is preferable to blanking the dashboard on a 429.
            if not os.path.exists(cache_file):
                raise
            with open(cache_file, encoding="utf-8") as handle:
                matches = json.load(handle)
            DIAG.append("BALLDONTLIE fixtures: stale cache after provider limit/error")
    st, tables = adapter.standings()
    DIAG.append(f"BALLDONTLIE fixtures: {len(matches)} in free-tier display window")
    DIAG.append("BALLDONTLIE standings/leaders: unavailable on free tier")
    return adapter, matches, st, tables


def fetch_apisports_bundle():
    """Fetch NFL/NBA schedules+standings via API-Sports (api-sports.io).

    Same account/key as API_FOOTBALL_KEY — no separate signup needed.
    """
    adapter = APISportsAdapter(API_FOOTBALL_KEY, COMP_KEY)
    cache_file = f"apisports_games_{COMP_KEY.lower()}_cache.json"
    matches = None
    try:
        if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < APISPORTS_CACHE_MIN * 60:
            with open(cache_file, encoding="utf-8") as handle:
                matches = json.load(handle)
            DIAG.append("API-Sports fixtures: local cache")
    except Exception:
        matches = None
    if matches is None:
        try:
            matches = adapter.schedule()
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(matches, handle, ensure_ascii=False)
            os.replace(tmp, cache_file)
        except ProviderError:
            if not os.path.exists(cache_file):
                raise
            with open(cache_file, encoding="utf-8") as handle:
                matches = json.load(handle)
            DIAG.append("API-Sports fixtures: stale cache after provider limit/error")
    st, tables = adapter.standings()
    DIAG.append(f"API-Sports fixtures: {len(matches)} loaded")
    return adapter, matches, st, tables


def fetch_college_bundle():
    """Fetch licensed college data with a quota-safe, resilient local cache."""
    if COMP_KEY == "NCAAF":
        adapter = CollegeFootballDataAdapter(CFBD_KEY)
        provider_name = "CollegeFootballData"
    else:
        adapter = CollegeBasketballDataAdapter(CBBD_KEY)
        provider_name = "CollegeBasketballData"
    cache_file = f"college_{COMP_KEY.lower()}_bundle_v4_cache.json"
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
            if not os.path.exists(cache_file):
                raise
            with open(cache_file, encoding="utf-8") as handle:
                bundle = json.load(handle)
            DIAG.append(f"{provider_name}: stale cache after provider limit/error")
    all_matches = bundle.get("matches") or []
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
    matches = [match for _, match in sorted(past, key=lambda item: item[0])[-40:]]
    matches += [match for _, match in sorted(future, key=lambda item: item[0])[:160]]
    matches.sort(key=lambda match: match.get("kickoff") or "")
    DIAG.append(f"{provider_name} fixtures: {len(matches)} in display window ({len(all_matches)} season total)")
    DIAG.append(f"{provider_name} standings: {sum(len(g.get('teams') or []) for g in tables)} teams")
    return adapter, matches, st, tables


def fetch_sportmonks_enrichment(matches):
    """Attach licensed soccer stats, lineups and availability when configured."""
    if not SPORTMONKS_KEY:
        DIAG.append("Sportmonks enrichment: key not configured")
        return
    try:
        attached = SportmonksAdapter(SPORTMONKS_KEY).enrich(matches, _name_match)
        DIAG.append(f"Sportmonks enrichment: attached {attached} fixtures")
    except ProviderError as exc:
        DIAG.append(f"Sportmonks enrichment failed: {_scrub(exc)}")



def compute_advancement(matches, st, name_map, code_map):
    """Model-derived advancement odds: roll the strength model through the
    remaining knockout rounds. Current-round matchups are exact; later rounds
    use a field-weighted average opponent (honest approximation, no fixed
    bracket-path assumption)."""
    if not COMP["tournament"]:
        return []
    ko = [m for m in matches if m.get("stage") and not m["stage"].lower().startswith("group")
          and m.get("status") in ("UPCOMING", "LIVE")
          and m["home"].get("name") and m["away"].get("name")
          and "winner" not in (m["home"]["name"] or "").lower()
          and "winner" not in (m["away"]["name"] or "").lower()]
    if not ko:
        return []
    # the earliest unresolved knockout round = current round
    order = {r: i for i, r in enumerate(KO_ORDER)}
    ko.sort(key=lambda m: order.get(m.get("stage"), 99))
    cur_stage = ko[0].get("stage")
    cur = [m for m in ko if m.get("stage") == cur_stage and cur_stage != "Third-place playoff"]
    rounds_after = [r for r in KO_ORDER if order.get(r, 99) > order.get(cur_stage, -1)
                    and r != "Third-place playoff"]

    def s_of(team):
        rec = st.get(norm(team.get("name")), {}) if isinstance(st, dict) else {}
        base = 1.0 + rec.get("pts", 0)*0.6 + rec.get("gd", 0)*0.25
        fp = sum({"W": 3, "D": 1, "L": 0}.get(r, 0) for r in (rec.get("form", "").split()))
        return max(0.1, base + fp*0.5 + rating_boost(team.get("name")))

    def p_beat(sa, sb):
        p = sa / (sa + sb)
        return 0.5 + (p - 0.5) * 0.88   # knockout variance damp

    strength, codes = {}, {}
    prob = {}
    for m in cur:
        for side, opp in (("home", "away"), ("away", "home")):
            t = m[side]; k = norm(t["name"])
            strength[k] = s_of(t)
            codes[k] = t.get("code") or code_map.get(k, "")
    for m in cur:
        hk, ak = norm(m["home"]["name"]), norm(m["away"]["name"])
        ph = p_beat(strength[hk], strength[ak])
        prob[hk] = ph; prob[ak] = 1 - ph

    rows = {k: {"team": name_map.get(k, k.title()), "code": codes.get(k, ""),
                "stages": {}} for k in prob}
    if rounds_after:
        for k in prob: rows[k]["stages"][rounds_after[0]] = prob[k]
    else:
        # the Final itself is the current round
        for k in prob: rows[k]["stages"]["Champion"] = prob[k]
    # later rounds vs the probability-weighted field
    p_now = dict(prob)
    for idx, r in enumerate(rounds_after[1:] + (["Champion"] if rounds_after else [])):
        p_next = {}
        for k in p_now:
            tot_w = sum(p_now[o] for o in p_now if o != k)
            if tot_w <= 0:
                p_next[k] = p_now[k]; continue
            exp_win = sum(p_now[o] * p_beat(strength[k], strength[o]) for o in p_now if o != k) / tot_w
            p_next[k] = p_now[k] * exp_win
        p_now = p_next
        for k in p_now: rows[k]["stages"][r] = p_now[k]
    out = []
    for k, r in rows.items():
        r["stages"] = {sg: round(v*100, 1) for sg, v in r["stages"].items()}
        r["win"] = r["stages"].get("Champion", 0)
        out.append(r)
    out.sort(key=lambda x: -x["win"])
    DIAG.append(f"advancement: {len(out)} teams from {cur_stage}")
    return out


def build():
    DIAG.clear()
    print("Fetching fixtures…")
    sports_adapter = None
    if COMP.get("source") in {"sportsdataio", "balldontlie", "cfbd", "cbbd", "apisports"}:
        raw = []
        if COMP.get("source") == "balldontlie":
            sports_adapter, matches, st, sports_tables = fetch_balldontlie_bundle()
            provider_name = "BALLDONTLIE"
        elif COMP.get("source") == "apisports":
            sports_adapter, matches, st, sports_tables = fetch_apisports_bundle()
            provider_name = "API-Sports"
        elif COMP.get("source") in {"cfbd", "cbbd"}:
            sports_adapter, matches, st, sports_tables = fetch_college_bundle()
            provider_name = "CollegeFootballData" if COMP_KEY == "NCAAF" else "CollegeBasketballData"
        else:
            sports_adapter, matches, st, sports_tables = fetch_sportsdataio_bundle()
            provider_name = "SportsDataIO"
        print(f"  got {len(matches)} fixtures ({provider_name})")
        name_map = {}
        for m in matches:
            for t in (m["home"], m["away"]):
                name_map[norm(t["name"])] = t["name"]
                rec = st.get(norm(t["name"]))
                if rec:  # hydrate the model's inputs from real standings
                    t["pts"], t["gd"], t["form"] = rec["pts"], rec["gd"], rec["form"]
                    t["group"], t["pos"] = rec["group"], rec.get("pos")
        for table in sports_tables:
            for team in table.get("teams") or []:
                if team.get("name"):
                    name_map.setdefault(norm(team["name"]), team["name"])
    else:
        raw = fetch_raw_matches(); print(f"  got {len(raw)} raw fixtures")
        st = compute_standings(raw)
        matches = build_matches(raw, st)
        name_map = {}
        for m in raw:
            for t in (m.get("homeTeam"), m.get("awayTeam")):
                if t and t.get("name"): name_map[norm(t["name"])] = t["name"]

    DIAG.append(f"ratings: {len(_load_ratings())} teams loaded")
    compute_rest(matches)
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
    ODDS_WINDOW_HOURS = 24  # conserve the Odds API's monthly quota — only worth
                            # spending a call once a match is imminent
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    def _due_for_odds(m):
        if m.get("status") == "LIVE":
            return True
        try:
            ko = datetime.datetime.fromisoformat(str(m.get("kickoff") or "").replace("Z", "+00:00"))
        except Exception:
            return False
        return (ko - now_utc).total_seconds() <= ODDS_WINDOW_HOURS * 3600
    if any(_due_for_odds(m) for m in matches):
        odds = fetch_odds()
    else:
        odds = {}
        DIAG.append(f"odds: skipped — nothing within {ODDS_WINDOW_HOURS}h (conserving quota)")
    merged = 0; fuzzy = 0
    for m in matches:
        rec, how = find_odds(odds, m["home"]["name"], m["away"]["name"])
        if rec:
            m["markets"] = rec; merged += 1
            if how == "fuzzy": fuzzy += 1

    if COMP["sport"] == "soccer":
        print("Fetching soccer detail (Sportmonks)…")
        fetch_sportmonks_enrichment(matches)

    # for US sports, pull championship odds first and fold them into team strength
    # so predictions use market-implied strength (their soccer-value equivalent)
    code_map = {}
    for m in matches:
        code_map[norm(m["home"]["name"])] = m["home"]["code"]
        code_map[norm(m["away"]["name"])] = m["away"]["code"]
    title = None
    if COMP.get("source") in {"sportsdataio", "balldontlie", "cfbd", "cbbd", "apisports"} and COMP.get("outright"):
        print("Fetching championship odds (team strength)…")
        title = fetch_outrights(code_map)
        apply_market_strength(title)

    # predictions run AFTER all stats/lineups so the model can use them this run
    for m in matches:
        m["prediction"] = predict(m["home"], m["away"], m["markets"], m)
    print(f"  merged odds onto {merged} fixtures ({fuzzy} via name-variant match) · predictions on all {len(matches)}")

    print("Fetching title odds + news…")
    if title is None:
        title = fetch_outrights(code_map)
    news = fetch_news()
    bracket = build_bracket(raw)
    third = third_race(st, name_map, code_map) if COMP["tournament"] else []

    groups = defaultdict(list)
    for t, r in st.items():
        gkey = r.get("group")
        if gkey:
            groups[gkey].append({
                "name": name_map.get(t, t.title()), "code": code_map.get(t, ""),
                "pos": r.get("pos"), "pld": r["pld"], "w": r["w"], "d": r["d"], "l": r["l"],
                "gf": r["gf"], "ga": r["ga"], "gd": r["gd"], "pts": r["pts"], "form": r["form"]})
    third_in = {norm(x.get("team")) for x in third if x.get("in")} or None
    third_out = {norm(x.get("team")) for x in third if not x.get("in")} if third else None
    def _annotate(teams):
        return qual_scenarios(teams, third_in, third_out) if COMP["tournament"] else teams
    standings = [{"group": pretty_group(g), "teams": _annotate(sorted(groups[g], key=lambda x: (x["pos"] or 99)))}
                 for g in sorted(groups)]
    if not standings and COMP["sport"] == "soccer":
        standings = build_league_table(st, name_map, code_map, COMP.get("league_zones"))
    if not standings and COMP.get("source") in {"sportsdataio", "balldontlie", "cfbd", "cbbd", "apisports"}:
        standings = sports_tables
    bracketology = None
    if COMP_KEY in ("NCAAF", "NCAAM") and COMP.get("source") in {"sportsdataio", "cfbd", "cbbd"}:
        ranks, proj = sports_adapter.rankings(sports_tables) if sports_adapter else ([], None)
        if ranks:
            rank_rows = [{"name": r["name"], "code": r["code"], "pos": r["rank"],
                          "pld": None, "w": None, "d": None, "l": None, "gf": None, "ga": None,
                          "gd": None, "pts": None, "form": "", "record": r["record"],
                          "qual": ({"status": f"CFP {r['rank']}", "note": "projected playoff seed (straight seeding)"} if COMP_KEY == "NCAAF" and r["rank"] <= 12 else "")}
                         for r in ranks]
            standings = [{"group": "Matchday Top 25", "teams": rank_rows}] + (standings or [])
        if COMP_KEY == "NCAAF" and proj and not bracket:
            bracket = proj
    if COMP_KEY == "NCAAM":
        bracketology = build_ncaam_bracketology(sports_tables)
    scorecard = update_scorecard(matches)
    update_player_db(matches)
    scorers = []
    if COMP.get("fd"):
        print("Fetching top scorers…")
        scorers = fetch_scorers()
    leaders = {}
    if COMP.get("source") == "sportsdataio":
        print("Fetching season leaders (SportsDataIO)…")
        try:
            leaders = sports_adapter.leaders() if sports_adapter else {}
        except ProviderError as exc:
            DIAG.append(f"SportsDataIO leaders unavailable on this plan: {_scrub(exc)}")
            leaders = {}

    live = sum(1 for m in matches if m["status"] == "LIVE")
    source_note = "sample" if COMP.get("source") == "sportsdataio" else "live"
    payload = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "source_note": source_note, "competition": COMP["label"], "comp_key": COMP_KEY, "matches": matches,
               "title_odds": title, "news": news, "news_scope": COMP_KEY, "bracket": bracket, "bracketology": bracketology,
               "third_race": third, "standings": standings, "scorers": scorers, "leaders": leaders, "team_of_tournament": build_team_of_tournament(matches, scorers, standings), "scorecard": scorecard,
               "advancement": compute_advancement(matches, st, name_map, code_map),
               "diagnostics": [_scrub(x) for x in DIAG]}
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
    if not FOOTBALL_DATA_KEY or not ODDS_API_KEY or "PASTE_" in FOOTBALL_DATA_KEY or "PASTE_" in ODDS_API_KEY:
        print("\n  Stop: keys not loaded — fix config_keys.py (see the !! lines above).\n"); sys.exit(1)
    loop = "--loop" in sys.argv
    while True:
        live = 0
        try: live = build()
        except Exception as e: print("  ! fetch failed this round:", e)
        if not loop: break
        if live:
            print(f"LIVE — refreshing in {LIVE_SECONDS}s  (Ctrl+C to stop)")
            time.sleep(LIVE_SECONDS)
        else:
            print(f"Idle — refreshing in {IDLE_MINUTES} min  (Ctrl+C to stop)")
            time.sleep(IDLE_MINUTES * 60)


if __name__ == "__main__":
    main()
