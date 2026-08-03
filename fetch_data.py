"""
matchday fetcher  (v5)
----------------------
  football-data.org  -> fixtures + final scores      (required key)
  The Odds API       -> pregame win probabilities     (required key)
  BALLDONTLIE        -> NBA/NFL/MLB fixtures + scores  (free launch key)
  College data APIs  -> NCAAF/NCAAM schedules + tables (shared free key)
  SportsDataIO       -> dormant development feeds       (trial/licensed key)
  Sportmonks         -> soccer detail + availability   (licensed token)

The product is intentionally pregame/postgame rather than a live-score feed:
  * predictions lock before kickoff and are not rewritten during games;
  * results are fetched after kickoff for public grading;
  * odds are requested only for near-kickoff upcoming games and cached on disk.

Run:  python fetch_data.py          (once)
      python fetch_data.py --loop   (hourly result checks)
"""

import json, os, sys, time, datetime, re, unicodedata, urllib.request, urllib.error, urllib.parse, math, traceback
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from collections import defaultdict
import mfti_research
import forecast_ledger
import market_snapshots
import pregame_context
import provider_quota
from advanced_metrics_store import attach_shadow_profiles
from mlb_challenger_store import attach_mlb_challenger_shadows
from mlb_model_promotion import apply_mlb_promotion, load_mlb_promotion_policy
from nfl_model_adjustment import apply_nfl_adjustment, load_nfl_adjustment_policy
from nfl_challenger_store import attach_nfl_challenger_shadows
from provider_adapters import (ProviderError, BallDontLieAdapter,
                               CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter, NflverseAdapter,
                               SportsDataIOAdapter, SportmonksAdapter,
                               APISportsAdapter, normalized_score,
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
    from config_keys import SPORTSDATAIO_KEY
except Exception:
    SPORTSDATAIO_KEY = os.environ.get("SPORTSDATAIO_KEY", "")
try:
    from config_keys import SPORTMONKS_KEY
except Exception:
    SPORTMONKS_KEY = os.environ.get("SPORTMONKS_KEY", "")
try:
    from config_keys import SPORTSDATAIO_PREGAME_ENABLED
except Exception:
    SPORTSDATAIO_PREGAME_ENABLED = os.environ.get("SPORTSDATAIO_PREGAME_ENABLED", "")
SPORTSDATAIO_PREGAME_ENABLED = str(SPORTSDATAIO_PREGAME_ENABLED).lower() in {
    "1", "true", "yes", "on"
}
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

IDLE_MINUTES = 60
LIVE_SECONDS = 3600   # legacy local loop: in-progress games only need hourly result checks
ODDS_CACHE_MIN = 180  # one pregame market snapshot per competition window
OUT_FILE = "data.json"
MODEL_SIGNAL_SCHEMA = 7  # adds capped, historically validated NFL calibrated-Elo adjustment

FD_BASE  = "https://api.football-data.org/v4"

# ---- competition selection --------------------------------------------------
# Default is the World Cup. To run the Champions League instead, either add
#     COMPETITION = "UCL"
# to config_keys.py, or launch with:  python fetch_data.py --ucl
COMPETITIONS = {
    "WC":  {"label": "World Cup 2026",   "sport": "soccer", "fd": "WC", "odds": "soccer_fifa_world_cup",
            "outright": "soccer_fifa_world_cup_winner", "tournament": True,
            "source": "fd", "has_draws": True, "single_elimination": True},
    # UCL's "outright" key below was removed after live verification against
    # The Odds API's own /v4/sports catalog (GET /v4/sports/?all=true, which
    # -- per their docs -- costs no usage credits, so this was checked for
    # real on 2026-07-25 without touching the exhausted monthly quota). That
    # catalog lists exactly 12 sport_keys with has_outrights=true across every
    # sport the account can see, and "soccer_uefa_champs_league_winner" is not
    # one of them (the only soccer entry present at all is
    # "soccer_fifa_world_cup_winner", used by WC above). The key had been
    # sitting in this dict since the initial commit, apparently guessed rather
    # than verified -- it was never reachable via the source-gated enrichment
    # path (apply_market_strength() only runs for sportsdataio/balldontlie/
    # cfbd/cbbd/apisports sources, and UCL's source is "fd"), but the
    # unconditional "fetch title odds for display" fallback later in build()
    # called fetch_outrights() with this fake key every single run regardless
    # -- a guaranteed-failing Odds-API request every ~hour this competition's
    # process ran, for a "title odds" UI panel that could therefore never
    # have shown real Champions League title-race data. Leaving the key out
    # makes fetch_outrights() take its normal, cheap "no outright market for
    # this competition" no-op path instead (see fetch_outrights()'s first
    # line) until/unless The Odds API actually adds this market.
    "UCL": {"label": "Champions League", "sport": "soccer", "fd": "CL", "odds": "soccer_uefa_champs_league",
            "outright": None, "tournament": False,
            "source": "fd", "has_draws": True},
    # Free launch feeds. BALLDONTLIE supplies real schedules and scores; paid
    # standings/player endpoints stay hidden when unavailable.
    "NFL": {"label": "NFL", "sport": "football", "fd": None, "odds": "americanfootball_nfl",
            "outright": "americanfootball_nfl_super_bowl_winner", "tournament": False,
            "source": "balldontlie", "has_draws": False},
    # EPL/LALIGA/SERIEA/BUNDESLIGA/LIGUE1's "outright" keys below were removed
    # for the same reason documented on UCL above: none of
    # "soccer_epl_winner" / "soccer_spain_la_liga_winner" /
    # "soccer_italy_serie_a_winner" / "soccer_germany_bundesliga_winner" /
    # "soccer_france_ligue_one_winner" exist in The Odds API's live
    # /v4/sports catalog (verified 2026-07-25, see UCL's comment above for
    # how). A domestic league's own championship-winner futures market
    # (the soccer equivalent of the americanfootball_nfl_super_bowl_winner
    # market these American leagues genuinely have) is simply not a market
    # this provider currently offers -- so apply_market_strength() cannot be
    # extended to these leagues via The Odds API the way it is for
    # NFL/NBA/MLB/NHL/NCAAF/NCAAM (see apply_market_strength()'s docstring
    # and the source-gated call site in build()). The real fix for these
    # leagues' ratings-coverage gap (most of a 18-20 team domestic table
    # having no ratings_<league>.json entry at all, so both sides of a
    # matchup involving an uncurated team fall back to the exact same flat
    # neutral defaults -- see rating_boost()/rating_parts()) has to be either
    # a genuinely different data source with real per-team squad-value/
    # strength coverage, or expanding the hand-curated ratings files
    # themselves; it is not "wire up an outright market" like it was for the
    # American sports, because no such market exists here to wire up.
    "EPL": {"label": "Premier League", "sport": "soccer", "fd": "PL", "odds": "soccer_epl",
            "outright": None, "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 3}},
    "LALIGA": {"label": "La Liga", "sport": "soccer", "fd": "PD", "odds": "soccer_spain_la_liga",
            "outright": None, "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 3}},
    "SERIEA": {"label": "Serie A", "sport": "soccer", "fd": "SA", "odds": "soccer_italy_serie_a",
            "outright": None, "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 3}},
    "BUNDESLIGA": {"label": "Bundesliga", "sport": "soccer", "fd": "BL1", "odds": "soccer_germany_bundesliga",
            "outright": None, "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 2}},
    "LIGUE1": {"label": "Ligue 1", "sport": "soccer", "fd": "FL1", "odds": "soccer_france_ligue_one",
            "outright": None, "tournament": False,
            "source": "fd", "has_draws": True, "league_zones": {"ucl": 4, "uel": 1, "rel": 2}},
    "NCAAF": {"label": "College Football", "sport": "football", "fd": None, "odds": "americanfootball_ncaaf",
            "outright": "americanfootball_ncaaf_championship_winner", "tournament": False,
            "source": "cfbd", "has_draws": False},
    "NCAAM": {"label": "Men's College Basketball", "sport": "basketball", "fd": None, "odds": "basketball_ncaab",
            "outright": "basketball_ncaab_championship_winner", "tournament": False,
            "source": "cbbd", "has_draws": False},
    "MLB": {"label": "MLB", "sport": "baseball", "fd": None, "odds": "baseball_mlb",
            "outright": "baseball_mlb_world_series_winner", "tournament": False,
            "source": "balldontlie", "has_draws": False},
    "NHL": {"label": "NHL", "sport": "hockey", "fd": None, "odds": "icehockey_nhl",
            "outright": "icehockey_nhl_championship_winner", "tournament": False,
            "source": "sportsdataio", "has_draws": False},
    "NBA": {"label": "NBA", "sport": "basketball", "fd": None, "odds": "basketball_nba",
            "outright": "basketball_nba_championship_winner", "tournament": False,
            "source": "balldontlie", "has_draws": False},
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
            "?regions=eu&markets=h2h&oddsFormat=decimal")
ODDS_CACHE_FILE = f"odds_market_cache_{COMP_KEY.lower()}.json"
OUTRIGHTS_CACHE_FILE = f"outrights_market_cache_{COMP_KEY.lower()}.json"
PREGAME_ODDS_WINDOW_HOURS = 3
UA = {"User-Agent": "Mozilla/5.0 (matchday-terminal)"}

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_CACHE_FILE = f"api_football_box_cache_{COMP_KEY.lower()}.json"
API_FOOTBALL_DAYS_BACK = 10     # recent finished matches to enrich with box scores
API_FOOTBALL_MAX_STATS = 18     # safety cap for the free daily request budget
# Lineups share the same free-plan request budget as box stats (100/day,
# across every soccer competition using this key), so this gets its own
# smaller, separate cap rather than doubling the existing one. Lineups are
# also fetched for a different window than stats: they're posted shortly
# before kickoff, so upcoming fixtures near kickoff matter here in a way
# they don't for stats (which only exist once a game has actually started).
API_FOOTBALL_LINEUP_DAYS_BACK = 2
API_FOOTBALL_LINEUP_PRE_KICKOFF_HOURS = 2
API_FOOTBALL_MAX_LINEUPS = 10
# Injuries share the same budget too, so this is the smallest cap of the
# three. Unlike stats (only exist once a game starts) or lineups (posted
# ~1h before kickoff), injury/team-news reports firm up over the days before
# a match and have zero predictive value once it's FINISHED, so the window
# looks forward from now rather than back from kickoff or from full time.
API_FOOTBALL_INJURY_PRE_KICKOFF_HOURS = 72
API_FOOTBALL_MAX_INJURIES = 8
SPORTSDATAIO_PREGAME_CACHE_FILE = f"sportsdataio_pregame_{COMP_KEY.lower()}_cache.json"
SPORTSDATAIO_PREGAME_CACHE_MIN = 15
SPORTSDATAIO_PREGAME_STALE_MAX_HOURS = 6

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
OUTRIGHTS_URL = (f"https://api.the-odds-api.com/v4/sports/{COMP['outright']}/odds/"
                 "?regions=eu&markets=outrights&oddsFormat=decimal")
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
BALLDONTLIE_CACHE_MIN = 10
BALLDONTLIE_ACTIVE_CACHE_MIN = 2
BALLDONTLIE_SEASON_CACHE_MIN = 240  # season-to-date pull re-pages the whole season; cache for hours
APISPORTS_CACHE_MIN = 30  # api-sports.io free tier caps at 100 req/day per sport
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
# nflverse-data's stats_player release is a public, unauthenticated GitHub
# release CSV (no API key, no per-request quota) that moves slowly within a
# season -- one CSV covers the whole league, refreshed by nflverse on their
# own schedule, not ours. Cache for a day so build() doesn't re-download a
# multi-hundred-KB file every run for data that barely changes hour to hour.
NFLVERSE_LEADERS_CACHE_MIN = 1440  # 24 hours
NEWS_TERMS = {
    "WC": "FIFA World Cup", "UCL": "UEFA Champions League",
    "EPL": "Premier League soccer", "LALIGA": "La Liga soccer",
    "SERIEA": "Serie A soccer", "BUNDESLIGA": "Bundesliga soccer",
    "LIGUE1": "Ligue 1 soccer", "NFL": "NFL", "NCAAF": "college football", "NCAAM": "men's college basketball",
    "NBA": "NBA", "MLB": "MLB baseball", "NHL": "NHL hockey",
}
_EPL_CLUBS = "premier_league epl arsenal aston_villa bournemouth brentford brighton chelsea crystal_palace everton fulham liverpool manchester_city manchester_united newcastle nottingham_forest sunderland tottenham west_ham wolves leeds burnley"
_LALIGA_CLUBS = "la_liga laliga real_madrid barcelona atletico_madrid sevilla valencia villarreal real_sociedad athletic_bilbao real_betis girona celta_vigo osasuna mallorca getafe rayo_vallecano"
_SERIEA_CLUBS = "serie_a juventus inter_milan ac_milan napoli roma lazio atalanta fiorentina bologna torino udinese genoa sassuolo"
_BUNDESLIGA_CLUBS = "bundesliga bayern_munich borussia_dortmund rb_leipzig bayer_leverkusen eintracht_frankfurt wolfsburg borussia_monchengladbach freiburg union_berlin hoffenheim stuttgart mainz augsburg werder_bremen"
_LIGUE1_CLUBS = "ligue_1 psg paris_saint_germain marseille lyon monaco lille nice rennes lens strasbourg toulouse"
_UCL_CLUBS = "champions_league ucl uefa " + " ".join([_EPL_CLUBS, _LALIGA_CLUBS, _SERIEA_CLUBS, _BUNDESLIGA_CLUBS, _LIGUE1_CLUBS])
NEWS_RELEVANCE = {
    "NFL": "nfl super_bowl quarterback touchdown chiefs eagles bills ravens bengals browns steelers texans colts jaguars titans broncos chargers raiders cowboys giants commanders packers lions vikings bears falcons panthers saints buccaneers cardinals rams 49ers seahawks jets dolphins patriots",
    "NCAAF": "college_football ncaa cfp bowl heisman alabama georgia ohio_state michigan notre_dame oregon texas usc lsu clemson penn_state florida_state tennessee oklahoma auburn hurricanes",
    "NCAAM": "college_basketball ncaa march_madness final_four duke north_carolina kansas_jayhawks kentucky uconn gonzaga houston_cougars purdue villanova arizona_wildcats michigan_state",
    "NBA": "nba basketball lebron giannis luka curry durant jokic wembanyama celtics lakers knicks nets 76ers raptors bulls cavaliers pistons pacers bucks heat magic hawks hornets wizards warriors clippers nuggets timberwolves thunder blazers jazz mavericks rockets grizzlies pelicans spurs suns kings",
    "MLB": "mlb baseball world_series yankees red_sox blue_jays orioles rays guardians tigers twins white_sox royals astros mariners rangers athletics angels braves mets phillies nationals marlins cubs cardinals brewers reds pirates dodgers padres giants diamondbacks rockies",
    "NHL": "nhl hockey stanley_cup bruins sabres red_wings panthers canadiens senators lightning maple_leafs hurricanes blue_jackets devils islanders rangers flyers penguins capitals blackhawks avalanche stars wild predators blues jets ducks flames oilers kings sharks kraken canucks golden_knights",
    "EPL": _EPL_CLUBS, "LALIGA": _LALIGA_CLUBS, "SERIEA": _SERIEA_CLUBS,
    "BUNDESLIGA": _BUNDESLIGA_CLUBS, "LIGUE1": _LIGUE1_CLUBS, "UCL": _UCL_CLUBS,
    "WC": "world_cup fifa national_team qualifier brazil argentina france england spain germany portugal netherlands belgium croatia morocco japan mexico usmnt",
}
NEWS_STRONG_RELEVANCE = {
    "NFL": "nfl super_bowl quarterback touchdown chiefs eagles ravens bengals steelers texans colts jaguars titans broncos chargers raiders cowboys commanders packers vikings buccaneers 49ers seahawks patriots",
    "NCAAF": "college_football ncaa cfp heisman alabama ohio_state notre_dame penn_state florida_state",
    "NCAAM": "college_basketball ncaa march_madness final_four duke north_carolina kansas_jayhawks kentucky uconn gonzaga houston_cougars purdue",
    "NBA": "nba basketball lebron giannis luka curry durant jokic wembanyama celtics lakers knicks 76ers raptors cavaliers pistons pacers bucks warriors clippers nuggets timberwolves thunder mavericks grizzlies pelicans spurs",
    "MLB": "mlb baseball world_series yankees red_sox blue_jays orioles guardians white_sox royals astros mariners braves mets phillies marlins cubs brewers pirates dodgers padres diamondbacks rockies",
    "NHL": "nhl hockey stanley_cup bruins sabres red_wings canadiens senators lightning maple_leafs blue_jackets devils islanders flyers penguins capitals blackhawks avalanche predators kraken canucks golden_knights",
    "EPL": "premier_league epl arsenal chelsea liverpool manchester_city manchester_united tottenham newcastle",
    "LALIGA": "la_liga laliga real_madrid barcelona atletico_madrid",
    "SERIEA": "serie_a juventus inter_milan ac_milan napoli roma",
    "BUNDESLIGA": "bundesliga bayern_munich borussia_dortmund",
    "LIGUE1": "ligue_1 psg paris_saint_germain marseille",
    "UCL": "champions_league ucl uefa real_madrid manchester_city bayern_munich barcelona liverpool psg",
    "WC": "world_cup fifa national_team",
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
    "NBA": "royals chiefs astros texans nfl mlb nhl",
    "MLB": "chiefs texans nfl nhl",
    "NHL": "royals chiefs astros texans nfl mlb",
    "EPL": "nfl mlb nba nhl fantasy_football touchdown quarterback",
    "LALIGA": "nfl mlb nba nhl fantasy_football touchdown quarterback",
    "SERIEA": "nfl mlb nba nhl fantasy_football touchdown quarterback",
    "BUNDESLIGA": "nfl mlb nba nhl fantasy_football touchdown quarterback",
    "LIGUE1": "nfl mlb nba nhl fantasy_football touchdown quarterback",
    "UCL": "nfl mlb nba nhl fantasy_football touchdown quarterback",
}


def _news_relevant(item):
    """Reject obvious cross-sport leakage from broad publisher feeds.

    Confirmed live 2026-07-26: soccer competitions (EPL/UCL/LaLiga/SerieA/
    Bundesliga/Ligue1/WC) had no entry in NEWS_RELEVANCE at all, so
    `terms = NEWS_RELEVANCE.get(COMP_KEY)` was None and this returned True
    unconditionally for every soccer feed -- zero filtering. That let NFL
    fantasy-football and MLB trade-deadline articles from the broad
    site:cbssports.com/site:foxsports.com Google News searches straight onto
    EPL/UCL's News tab. Added real club/league term lists for every soccer
    competition, same shape as the US sports already had.
    """
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
    s = re.sub(r"((?:apiKey|api_token)=)[^&\s]+", r"\1***", s, flags=re.I)
    s = re.sub(r"(X-Auth-Token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+", r"\1***", s)
    s = re.sub(r"(x-apisports-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+", r"\1***", s)
    for k in (FOOTBALL_DATA_KEY, ODDS_API_KEY, API_FOOTBALL_KEY,
              SPORTSDATAIO_KEY, SPORTMONKS_KEY, BALLDONTLIE_KEY,
              CFBD_KEY, CBBD_KEY):
        if k and len(str(k)) > 8:
            s = s.replace(str(k), "***")
    return s


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
            provider_quota.record_block(provider)
            raise RuntimeError(_scrub(str(exc)))
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            if provider:
                provider_quota.record_response(provider, r.headers)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: body = e.read().decode("utf-8")[:300]
        except Exception: body = ""
        if provider:
            provider_quota.record_response(provider, e.headers, body)
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
    return _get(f"{FD_BASE}/competitions/{COMP["fd"]}/matches", {"X-Auth-Token": FOOTBALL_DATA_KEY}, provider="football_data").get("matches", [])


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


def fetch_football_data_historical_season(comp_key, season):
    """One-time historical pull for backfill_history.py -- NOT used by
    build()/fetch_raw_matches(), which always wants the live/current season.

    football-data.org's free plan supports `?season=YYYY` on `/matches`
    (live-verified 2026-07-26: `?season=2023` on PL returned the complete
    380-match 2023-24 season in one call, `resultSet.played` confirming full
    coverage) but only back to season 2023 -- season 2022 and earlier 403 on
    this plan for every competition, including the 2022 World Cup itself, so
    backfill_history.py's plan never asks this function for a season before
    2023 (2022 is covered by API-FOOTBALL instead -- see
    fetch_api_football_historical_season below -- to avoid double-counting
    the seasons both providers can reach, 2023/2024, into Elo).
    """
    fd_code = COMPETITIONS[comp_key]["fd"]
    url = f"{FD_BASE}/competitions/{fd_code}/matches?season={season}&status=FINISHED"
    raw = _get(url, {"X-Auth-Token": FOOTBALL_DATA_KEY}, provider="football_data").get("matches", [])
    matches = []
    for m in raw:
        h = m.get("homeTeam") or {}
        a = m.get("awayTeam") or {}
        if not h.get("name") or not a.get("name"):
            continue
        hg, ag, win, pens, _reg = _resolve_score(m)
        matches.append({
            "id": str(m.get("id")), "kickoff": m.get("utcDate"),
            "status": "FINISHED" if m.get("status") == "FINISHED" else "UPCOMING",
            "home": {"name": h["name"]}, "away": {"name": a["name"]},
            "score": {"home": hg, "away": ag,
                      "pens": ({"home": pens[0], "away": pens[1]} if pens[0] is not None else None),
                      "winner": win},
        })
    matches.sort(key=lambda match: match.get("kickoff") or "")
    return matches


def compute_standings(raw):
    T = defaultdict(lambda: {"group": None, "pld": 0, "w": 0, "d": 0, "l": 0,
                             "gf": 0, "ga": 0, "pts": 0, "results": []})
    for m in raw:
        h = (m.get("homeTeam") or {}).get("name"); a = (m.get("awayTeam") or {}).get("name")
        if not h or not a: continue
        # touch both teams so every scheduled team gets a row even with 0
        # games played -- otherwise a domestic league with no fixtures
        # finished yet (preseason) ends up with an empty T, and no amount of
        # zones-bypassing in build_league_table can fix a table with zero rows
        T[norm(h)]; T[norm(a)]
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
                    "pts": s.get("pts", 0), "form": s.get("form", ""),
                    "rating": round(power_rating(t.get("name"), s), 2)}

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


SRS_MARGIN_CAP = {"NFL": 28, "NCAAF": 35, "NBA": 30, "NCAAM": 30,
                  "MLB": 8, "NHL": 5}


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
    "MLB": {
        "label": "Personnel edge",
        "source": None,
        "source_key": None,
        "note": "Requires probable starters, confirmed batting orders, and bullpen availability; the configured feed does not provide them.",
    },
    "NFL": {
        "label": "Roster edge",
        "source": None,
        "source_key": None,
        "note": "Requires current depth charts and player-availability data; the configured feed does not provide full roster coverage.",
    },
    "NBA": {
        "label": "Star / rotation edge",
        "source": None,
        "source_key": None,
        "note": "Requires current rotations, active-player quality, and availability; the configured feed does not provide full coverage.",
    },
    "NHL": {
        "label": "Roster / goalie edge",
        "source": None,
        "source_key": None,
        "note": "Requires current lines, starting goalie, and player availability before it can be treated as a real personnel signal.",
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


def class_signal_meta(home_name, away_name):
    """Describe what the displayed class/personnel comparison really means."""
    if COMP.get("sport") == "soccer":
        label, source = "Squad edge", "Curated squad and star-player values"
        available = []
        for name in (home_name, away_name):
            rec = _ratings_lookup(name) or {}
            available.append(bool(rec and (rec.get("squad_value_m") or rec.get("star_value_m")
                                           or rec.get("fifa_rank"))))
        note = "Squad value, star quality, and ranking are a preseason prior; missing clubs are not assigned a fabricated edge."
    else:
        cfg = CLASS_SIGNAL_CONFIG.get(COMP_KEY, {
            "label": "Personnel edge", "source": None,
            "note": "No verified sport-specific personnel source is configured.",
        })
        label, source, note = cfg["label"], cfg.get("source"), cfg["note"]
        available = [bool(_college_talent_points(_ratings_lookup(name)))
                     for name in (home_name, away_name)]
    coverage = "complete" if all(available) else "partial" if any(available) else "unavailable"
    return {"label": label, "source": source, "available": coverage == "complete",
            "coverage": coverage, "home_available": available[0],
            "away_available": available[1], "note": note}


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
        season_w = (POWER_SEASON_MAX_WEIGHT
                    * min(1.0, played / float(POWER_SEASON_FULL_TRUST_GAMES)))
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
    mk = (markets or {}).get("1x2") or {}
    market_gap_pct = None
    # Default closed, not open: with no market to check the underdog pick
    # against, the only thing allowed to flip the pick to the dog is real
    # box-score dominance (strong_box_override below). Odds are now gated to
    # within 3h of kickoff to save quota, so "no market yet" is the common
    # case for most of a match's display life, not a rare edge case -- an
    # open-by-default gate here would mean the model's riskiest calls (upset
    # picks) go out with no safety check most of the time.
    market_gate = False
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
        "box_score_edge": round(box_score_edge, 3),
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
    american = COMP["sport"] != "soccer"
    american_cfg = {
        "NFL": {"full": 10, "margin": 10.0, "home": 0.50, "rest": 7},
        "NCAAF": {"full": 10, "margin": 14.0, "home": 0.45, "rest": 7},
        "NBA": {"full": 20, "margin": 12.0, "home": 0.40, "rest": 2},
        "NCAAM": {"full": 18, "margin": 10.0, "home": 0.45, "rest": 2},
        "MLB": {"full": 30, "margin": 2.5, "home": 0.25, "rest": 1},
        "NHL": {"full": 20, "margin": 1.5, "home": 0.25, "rest": 2},
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
    # Soccer's pts/gd/form are correctly zero pre-season too (they're read
    # directly with no reliability gate at all, unlike the American branch),
    # so the same starved-of-signal problem hits soccer predictions just as
    # hard -- a full domestic-league table takes ~34-38 games, but a team is
    # clearly no longer a blank slate a few weeks in, so 12 games (roughly a
    # third of a season) is used as "established" here rather than the full
    # table length.
    full = float(american_cfg["full"]) if american else 12.0
    home_pld = max(0, int(home.get("pld") or 0)) if home else 0
    away_pld = max(0, int(away.get("pld") or 0)) if away else 0
    avg_reliability = min(1.0, ((home_pld + away_pld) / 2.0) / full)
    prior_boost = 1.0 + (1.0 - avg_reliability) * 0.6

    def parts(s, adv):
        if not s: return {"base": 1.0, "adv": adv}
        form_str = (s.get("form_home") if adv else s.get("form_away")) or s.get("form", "")
        fp = _weighted_form_score(form_str)
        rest = s.get("rest_days")
        rp = rating_parts(s.get("name"))
        rating_record = _ratings_lookup(s.get("name")) or {}
        elo_pts, elo_conf = elo_strength(s.get("name"))
        # Unknown teams (no ratings-file entry, even after the club-suffix
        # fallback) receive no invented class prior rather than a default --
        # true of both branches below. The American branch already gated its
        # single combined "class" figure on this; soccer's fifa/value/star
        # were applied unconditionally (see rating_boost()/rating_parts()'s
        # neutral fallback: fifa_rank=45, squad_value_m=120, star_value_m=25),
        # so two teams with no curated entry -- common for any domestic-league
        # club outside the hand-curated top few per league -- silently got the
        # exact same non-zero "class" figure, which looks like real signal but
        # is a coin-flip default wearing a rating's clothes. Gating it to zero
        # for real unknowns is honest: it hands the matchup to the signals
        # that ARE real for every team (pts/gd/form/elo) instead of padding
        # both sides with an identical phantom number.
        known_rating = bool(rating_record)
        if american:
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
            # College futures and recruiting/talent are correlated, so the
            # market signal remains a small independent cross-check there.
            # Pro sports have no verified roster-quality feed today, making
            # market power their full (but explicitly named) long-term prior.
            market_scale = 0.35 if COMP_KEY in {"NCAAF", "NCAAM"} else 1.0
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
                # rp["fifa"] is a soccer-only signal -- American sports never
                # populate a real fifa_rank (apply_recruiting_strength/
                # apply_market_strength only ever write squad_value_m/
                # star_value_m, so fifa_rank stays at rating_parts()'s
                # neutral default forever). Including it here added an
                # identical, non-differentiating constant to BOTH sides'
                # class figure -- dead weight that only diluted the one
                # real signal (value/star, both talent-share derived)
                # preseason predictions have to work with.
                "class": talent_points * prior_boost,
                "market_power": market_points * market_scale * prior_boost,
                "rank": poll_prior * prior_boost,
                "srs": _clamp(float(s.get("srs") or 0) / american_cfg["margin"], -1.5, 1.5) * 2.4 * srs_conf,
                "elo": elo_pts * elo_conf * prior_boost,
                "rest": (0.0 if rest is None else
                         _clamp((rest - american_cfg["rest"]) * 0.08, -0.35, 0.35)),
            }
        class_scale = prior_boost if known_rating else 0.0
        return {"base": 1.0, "pts": (s.get("pts") or 0)*0.6, "gd": (s.get("gd") or 0)*0.25,
                "form": fp*0.5, "adv": adv,
                "fifa": rp["fifa"]*class_scale, "value": rp["value"]*class_scale, "star": rp["star"]*class_scale,
                "elo": elo_pts*elo_conf*prior_boost,
                "rest": 0.0 if rest is None else max(-0.6, min(0.45, (rest - 4) * 0.15))}
    home_adv = 0.0 if neutral_venue else (american_cfg["home"] if american else 1.2)
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
    if american:
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
    # StrengthFloorTests, for the regression coverage). Soccer's branch never
    # had its own "base" touched this session (still 1.0) and empirically
    # doesn't produce sums anywhere near this floor for real data, so it keeps
    # the original epsilon-only floor; only the American branch, where this
    # was actually validated (0/224 cached NFL fixtures now round to a
    # >=99%/<=1% split, down from 33/224, with the same-session confidence
    # improvement over the pre-fix baseline still intact), gets the higher one.
    strength_floor = 1.5 if american else 0.1
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
        sh = max(strength_floor, sh - inj_h)
        sa = max(strength_floor, sa - inj_a)
    # factor attribution: how much each factor tilts home-vs-away (strength pts)
    keys = set(ph) | set(pa)
    why = {k: round(ph.get(k, 0) - pa.get(k, 0), 2) for k in keys if k != "base"}
    if not american:
        why["class"] = round(why.pop("fifa", 0) + why.pop("value", 0) + why.pop("star", 0), 2)
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
        # Third occurrence of the same knockout-detection bug fixed above --
        # this one damps the prediction toward a 50/50 split for "one-off
        # knockouts" but was misfiring on every domestic league match too
        # (a league's "Regular Season"/"Matchday N" stage never starts with
        # "group" either), flattening every single EPL/LaLiga/SerieA/
        # Bundesliga/Ligue1 prediction toward a coin flip before the draw
        # carve-out even runs.
        if _is_knockout_stage((m.get("stage") or "").lower()): damp = 0.12
        wx = m.get("weather") or {}
        if wx.get("temp_c", 0) >= 32 or wx.get("wind_kph", 0) >= 30:
            damp = max(damp, 0.10)
    if damp:
        mean = (sh + sa) / 2
        sh, sa = sh + (mean - sh)*damp, sa + (mean - sa)*damp
    # Draw probability was a flat 0.26 for every match regardless of how
    # lopsided the two sides are -- real soccer draws happen far less often
    # in a genuine mismatch than in an even game. Scale it down as the
    # pre-draw split moves away from 50/50, same shape as the rest of this
    # function's clamped-linear adjustments; 0.26 at a dead-even split,
    # tapering to 0.12 at a maximally lopsided one.
    if two_way:
        draw = 0.0
    else:
        pre_draw_gap = abs(sh / max(0.1, sh + sa) - 0.5) * 2.0  # 0 even .. 1 maximal
        draw = 0.26 - _clamp(pre_draw_gap, 0.0, 1.0) * 0.14
    tot = sh+sa
    model = {"h": round(sh/tot*(1-draw)*100), "a": round(sa/tot*(1-draw)*100), "d": round(draw*100)}
    mk = markets.get("1x2")
    market_weight = _market_blend_weight(mk)
    raw_blend = ({"h": round(model["h"]*(1-market_weight) + mk["home_pct"]*market_weight),
                  "d": round(model["d"]*(1-market_weight) + mk["draw_pct"]*market_weight),
                  "a": round(model["a"]*(1-market_weight) + mk["away_pct"]*market_weight)}
                 if mk else dict(model))
    raw_blend = _round_triplet(raw_blend)
    regulation_probs, upset = _upset_adjustment(home, away, markets, m, why, raw_blend, two_way=two_way)

    knockout = bool(m and COMP.get("sport") == "soccer" and COMP.get("single_elimination")
                    and _is_knockout_stage(m.get("stage")))
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
    name = {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[pick]
    edge, note = None, "no market to compare against"
    if mk:
        mm = {"h": mk["home_pct"], "d": mk["draw_pct"], "a": mk["away_pct"]}
        edge = regulation_probs[regulation_pick] - mm[regulation_pick]
        note = ("advancement forecast; market comparison uses regulation 1X2" if knockout
                else "upset formula triggered — volatility makes the underdog playable" if upset.get("triggered")
                else "favorite, but upset watch" if upset.get("score", 0) >= 60 and pick != upset.get("candidate")
                else "model agrees with the market" if abs(edge) < 6
                else f"model rates this {'higher' if edge > 0 else 'lower'} than the market")
    elif knockout:
        note = "two-way advancement forecast; no regulation market to compare"
    elif upset.get("triggered"):
        note = "upset formula triggered — volatility makes the underdog playable"
    mkt_pull = (regulation_probs[regulation_pick] - model[regulation_pick]) if mk else 0
    # ---- predicted margin/spread ------------------------------------------
    # Matchday's own point/goal-margin estimate (not copied from a
    # sportsbook) -- derived from the official win/draw/loss probabilities
    # already computed above via the standard odds<->margin relationship
    # (margin = scale * log10(odds ratio)), not a new model. `scale` reuses
    # american_cfg["margin"] -- already each American sport's tuned typical
    # single-game point/goal-margin unit -- for NFL/NCAAF/NBA/NCAAM/MLB/NHL,
    # and a real average soccer winning margin (~1.3 goals) for two-way
    # soccer probabilities alike. Works identically preseason, since it only
    # needs the probabilities predict() already produces at pld=0.
    h_frac = _clamp(official_probs["h"] / max(1e-6, official_probs["h"] + official_probs["a"]), 0.02, 0.98)
    margin_scale = float(american_cfg["margin"]) if american else 1.3
    margin_pts = round(margin_scale * math.log10(h_frac / (1 - h_frac)), 1)
    margin_unit = ({"NFL": "points", "NCAAF": "points", "NBA": "points", "NCAAM": "points",
                    "MLB": "runs", "NHL": "goals"}.get(COMP_KEY, "points") if american else "goals")
    if abs(margin_pts) < 0.05:
        margin_label = "Even matchup"
        margin_favored = None
    else:
        margin_favored = "h" if margin_pts > 0 else "a"
        fav_name = home.get("name") if margin_pts > 0 else away.get("name")
        margin_label = (f"{fav_name} by {abs(margin_pts):.1f}" if american else
                         f"{'+' if margin_pts >= 0 else ''}{margin_pts:.1f} goals")
    predicted_margin = {"value": margin_pts, "unit": margin_unit,
                         "favored": margin_favored, "label": margin_label}
    sample = {"home": int(home.get("pld") or 0), "away": int(away.get("pld") or 0)}
    min_sample = min(sample.values())
    any_stale = bool(home.get("season_stale") or away.get("season_stale"))
    quality_level = ("preseason" if min_sample == 0 or any_stale else "early"
                     if american and min_sample < american_cfg["full"] else "established")
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
    class_meta = class_signal_meta(home.get("name"), away.get("name"))
    return {"pick": pick, "pick_name": name, "confidence": confidence,
            "base_pick": base_pick, "base_pick_name": {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[base_pick],
            "model": model, "base_blend": raw_blend, "blend": official_probs, "adjusted": official_probs,
            "is_knockout": knockout, "advancement": advancement,
            "regulation_pick": regulation_pick,
            "regulation_pick_name": {"h": home.get("name"), "a": away.get("name"), "d": "Draw"}[regulation_pick],
            "regulation_confidence": regulation_probs[regulation_pick],
            "regulation_probs": regulation_probs,
            "edge": edge, "note": note, "why": why, "damp_pct": round(damp*100),
            "mkt_pull": mkt_pull, "market_weight": market_weight,
            "upset": upset, "data_quality": data_quality, "predicted_margin": predicted_margin,
            "class_meta": class_meta}


LEAGUE_AVG_TOTAL = {"NFL": 44.5, "NCAAF": 55.0, "NBA": 224.0, "NCAAM": 140.0,
                     "MLB": 8.6, "NHL": 6.0}


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


# -------- API-FOOTBALL : box-score team statistics ------------------------
def _api_football_get(path, params=None):
    if not API_FOOTBALL_KEY:
        raise RuntimeError("missing API_FOOTBALL_KEY")
    q = urllib.parse.urlencode(params or {})
    url = API_FOOTBALL_BASE + path + (("?" + q) if q else "")
    headers = dict(UA)
    headers["x-apisports-key"] = API_FOOTBALL_KEY
    return _get(url, headers)


# league ids for API-FOOTBALL's /fixtures?league=...&season=... -- confirmed
# live 2026-07-26 against the real endpoint (each returned the right
# competition name and a plausible match count for a completed season: WC 59
# FT/AET/PEN fixtures for 2022 -- Qatar vs Ecuador opener through the Croatia
# vs Morocco third-place match; UCL 203; EPL/La Liga/Ligue 1 380; Serie A
# 381; Bundesliga 308). Used only by backfill_history.py, and only for
# season 2022 there (API-FOOTBALL's free plan works for seasons 2022-2024,
# 2021 and 2025 both fail -- confirmed live the same day) -- domestic
# leagues/UCL's 2023-2025 seasons come from football-data.org instead (see
# fetch_football_data_historical_season above) to avoid double-counting the
# 2023/2024 seasons both providers can reach.
API_FOOTBALL_LEAGUE_ID = {"WC": 1, "UCL": 2, "EPL": 39, "LALIGA": 140,
                           "SERIEA": 135, "BUNDESLIGA": 78, "LIGUE1": 61}
_AF_FINISHED_STATUSES = {"FT", "AET", "PEN"}


def fetch_api_football_historical_season(comp_key, season):
    """One-time historical pull for backfill_history.py -- shares the same
    API-FOOTBALL key/quota as box scores, lineups, and injuries, but this is
    a bulk historical pull (one /fixtures call, budgeted separately -- see
    PROVIDER_COMPLIANCE.md), a meaningfully different usage pattern than
    those hourly per-fixture calls.

    No `status=` filter is sent -- API-FOOTBALL's dash-joined status-list
    query syntax wasn't live-verified, so this fetches the whole season and
    filters client-side on `fixture.status.short` instead, treating FT/AET/
    PEN as finished (a knockout-stage match decided in extra time or on
    penalties is still a real final result) and everything else (NS, PST,
    CANC, ...) as not finished.
    """
    league = API_FOOTBALL_LEAGUE_ID.get(comp_key)
    if not league:
        raise RuntimeError(f"no API-FOOTBALL league id mapped for {comp_key}")
    payload = _api_football_get("/fixtures", {"league": league, "season": season})
    rows = payload.get("response") if isinstance(payload, dict) else []
    matches = []
    for row in rows or []:
        fx = row.get("fixture") or {}
        teams = row.get("teams") or {}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        if not home.get("name") or not away.get("name"):
            continue
        status_short = (fx.get("status") or {}).get("short") or ""
        finished = status_short in _AF_FINISHED_STATUSES
        goals = row.get("goals") or {}
        score = normalized_score(goals.get("home"), goals.get("away"), finished)
        if finished and score.get("winner") == "d":
            pen = (row.get("score") or {}).get("penalty") or {}
            ph, pa = pen.get("home"), pen.get("away")
            if ph is not None and pa is not None and ph != pa:
                score["winner"] = "h" if ph > pa else "a"
        matches.append({
            "id": f"af-{fx.get('id')}", "kickoff": fx.get("date"),
            "status": "FINISHED" if finished else "UPCOMING",
            "home": {"name": str(home.get("name"))}, "away": {"name": str(away.get("name"))},
            "score": score,
        })
    matches.sort(key=lambda match: match.get("kickoff") or "")
    return matches


def _load_box_cache():
    try:
        with open(API_FOOTBALL_CACHE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("dates", {})
            d.setdefault("stats", {})
            d.setdefault("lineups", {})
            d.setdefault("injuries", {})
            return d
    except Exception:
        pass
    return {"dates": {}, "stats": {}, "lineups": {}, "injuries": {}}


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


def _parse_af_lineups(payload, m):
    """API-FOOTBALL /fixtures/lineups -> the same {home,away,subs} shape the
    Sportmonks adapter already produces, so the frontend pitch view doesn't
    need to know which provider supplied it."""
    rows = payload.get("response") or []
    if len(rows) < 2:
        return None
    sides = {}
    subs = []
    for row in rows:
        tname = ((row.get("team") or {}).get("name")) or ""
        side = "home" if _name_match(tname, m["home"]["name"]) else ("away" if _name_match(tname, m["away"]["name"]) else "")
        if not side:
            continue
        xi = [{"n": (p.get("player") or {}).get("number") or "",
               "name": (p.get("player") or {}).get("name") or "", "out": False}
              for p in (row.get("startXI") or []) if (p.get("player") or {}).get("name")]
        if len(xi) < 7:
            continue
        sides[side] = {"formation": row.get("formation") or "", "xi": xi[:11]}
        subs.extend((p.get("player") or {}).get("name") or "" for p in (row.get("substitutes") or []))
    if "home" not in sides or "away" not in sides:
        return None
    return {"home": sides["home"], "away": sides["away"], "subs": [s for s in subs if s]}


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


def _hours_until_kickoff(m, now):
    try:
        ko = datetime.datetime.fromisoformat((m.get("kickoff") or "").replace("Z", "+00:00"))
        return (ko - now).total_seconds() / 3600.0
    except Exception:
        return None


def fetch_api_football_box_scores(matches):
    """Attach m['stats_extra'] for LIVE/recent-FINISHED soccer matches, and
    m['lineups'] for LIVE, near-kickoff UPCOMING, and very-recent FINISHED
    matches -- the only currently-active lineup source, since Sportmonks
    (the licensed alternative) needs a key that isn't configured and every
    other provider adapter hardcodes lineups to None. Both share the same
    free-plan request budget (100/day across every soccer competition using
    this key), so lineups get their own smaller cap and shorter window
    rather than doubling the existing stats budget.

    API-FOOTBALL uses its own fixture ids, so we first fetch fixtures by date
    (shared between stats and lineups to avoid duplicate requests), fuzzy-
    match the teams, then fetch /fixtures/statistics and /fixtures/lineups
    for matched fixtures. Results are cached to protect the daily limit.
    """
    if COMP.get("sport") != "soccer":
        return
    if not API_FOOTBALL_KEY:
        DIAG.append("box stats(API-FOOTBALL): missing API_FOOTBALL_KEY")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date()
    stat_targets, lineup_targets = [], []
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
            stat_targets.append(m)
        hrs = _hours_until_kickoff(m, now)
        if (status == "LIVE"
                or (status == "FINISHED" and 0 <= age <= API_FOOTBALL_LINEUP_DAYS_BACK)
                or (status == "UPCOMING" and hrs is not None and 0 <= hrs <= API_FOOTBALL_LINEUP_PRE_KICKOFF_HOURS)):
            lineup_targets.append(m)
    stat_targets = sorted(stat_targets, key=lambda x: x.get("kickoff") or "", reverse=True)[:API_FOOTBALL_MAX_STATS]
    lineup_targets = sorted(lineup_targets, key=lambda x: x.get("kickoff") or "", reverse=True)[:API_FOOTBALL_MAX_LINEUPS]
    if not stat_targets and not lineup_targets:
        DIAG.append("box stats(API-FOOTBALL): no live/recent/upcoming fixtures")
        return

    cache = _load_box_cache()
    attached = 0
    matched = 0
    date_requests = 0
    stat_requests = 0
    now_ts = time.time()

    all_dates = {_match_date_utc(m) for m in (stat_targets + lineup_targets) if _match_date_utc(m)}
    events_by_date = {}
    for d in sorted(all_dates):
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

    for m in stat_targets:
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

    lineup_matched = 0
    lineup_attached = 0
    lineup_requests = 0
    for m in lineup_targets:
        d = _match_date_utc(m)
        fid = _af_fixture_id_for_match(m, events_by_date.get(d) or [])
        if not fid:
            continue
        lineup_matched += 1
        fid = str(fid)
        lrec = (cache.get("lineups") or {}).get(fid)
        # Lineups are announced once and don't change after kickoff, so a
        # cache hit of any age is trusted for a FINISHED/LIVE match; only
        # a still-UPCOMING fixture needs re-checking (lineups may not be
        # posted yet on an earlier pass).
        if lrec and (m.get("status") != "UPCOMING" or now_ts - float(lrec.get("t") or 0) < 900):
            lineups = lrec.get("lineups")
        else:
            try:
                payload = _api_football_get("/fixtures/lineups", {"fixture": fid})
                lineups = _parse_af_lineups(payload, m)
                cache.setdefault("lineups", {})[fid] = {"t": now_ts, "lineups": lineups}
                lineup_requests += 1
            except Exception as e:
                DIAG.append(f"lineups(API-FOOTBALL): fixture {fid} FAILED — {_scrub(e)}")
                lineups = lrec.get("lineups") if lrec else None
        if lineups:
            m["lineups"] = lineups
            lineup_attached += 1

    _save_box_cache(cache)
    DIAG.append(f"box stats(API-FOOTBALL): matched {matched}, attached {attached}, requests {date_requests}+{stat_requests}")
    DIAG.append(f"lineups(API-FOOTBALL): matched {lineup_matched}, attached {lineup_attached}, requests {lineup_requests}")


def fetch_api_football_injuries(matches):
    """Attach m['injuries'] for LIVE and pre-kickoff UPCOMING soccer matches
    from API-FOOTBALL's /injuries endpoint -- feeding predict()'s existing
    injury-weighting nudge (fetch_data.py, the `w = {...}.get(COMP_KEY, 1.5)`
    block) real data for soccer for the first time; every soccer adapter
    path previously left m['injuries'] at its empty default.

    Shares the same free-plan key and 100/day budget as
    fetch_api_football_box_scores() above, and -- as long as this is called
    right after that function in build() -- reuses its 'dates' cache entries
    (same on-disk cache file, same 6h freshness window) instead of re-fetching
    /fixtures by date, so a normal run costs zero extra requests just to
    resolve fixture ids.

    Only LIVE and near-kickoff UPCOMING fixtures are targeted: injuries are
    forward-looking team news with no predictive value (and no quota worth
    spending) once a match is FINISHED, unlike box stats/lineups which are
    also useful as a post-match record.
    """
    if COMP.get("sport") != "soccer":
        return
    if not API_FOOTBALL_KEY:
        DIAG.append("injuries(API-FOOTBALL): missing API_FOOTBALL_KEY")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    targets = []
    for m in matches:
        status = m.get("status")
        if status == "LIVE":
            targets.append(m)
            continue
        if status == "UPCOMING":
            hrs = _hours_until_kickoff(m, now)
            if hrs is not None and 0 <= hrs <= API_FOOTBALL_INJURY_PRE_KICKOFF_HOURS:
                targets.append(m)
    # soonest kickoff first -- if the daily cap bites, the fixtures closest
    # to being locked in for a prediction are the ones worth spending on
    targets = sorted(targets, key=lambda x: x.get("kickoff") or "")[:API_FOOTBALL_MAX_INJURIES]
    if not targets:
        DIAG.append("injuries(API-FOOTBALL): no live/pre-kickoff fixtures")
        return

    cache = _load_box_cache()
    now_ts = time.time()
    all_dates = {_match_date_utc(m) for m in targets if _match_date_utc(m)}
    events_by_date = {}
    date_requests = 0
    for d in sorted(all_dates):
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
            DIAG.append(f"injuries(API-FOOTBALL): fixture date {d} FAILED — {_scrub(e)}")
            events_by_date[d] = rec.get("events") if rec else []

    matched = 0
    attached = 0
    inj_requests = 0
    for m in targets:
        d = _match_date_utc(m)
        fid = _af_fixture_id_for_match(m, events_by_date.get(d) or [])
        if not fid:
            continue
        matched += 1
        fid = str(fid)
        irec = (cache.get("injuries") or {}).get(fid)
        if irec and now_ts - float(irec.get("t") or 0) < 6 * 3600:
            injuries = irec.get("injuries")
        else:
            try:
                payload = _api_football_get("/injuries", {"fixture": fid})
                injuries = _parse_af_injuries(payload, m, fid)
                cache.setdefault("injuries", {})[fid] = {"t": now_ts, "injuries": injuries}
                inj_requests += 1
            except Exception as e:
                DIAG.append(f"injuries(API-FOOTBALL): fixture {fid} FAILED — {_scrub(e)}")
                injuries = irec.get("injuries") if irec else None
        if injuries is not None:
            m["injuries"] = injuries
            m.setdefault("personnel", {})["injuries_feed_checked"] = True
            m.setdefault("pregame_provenance", []).append({
                "input": "injuries", "source": "API-FOOTBALL",
                "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            })
            attached += 1

    _save_box_cache(cache)
    DIAG.append(f"injuries(API-FOOTBALL): matched {matched}, attached {attached}, requests {date_requests}+{inj_requests}")


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
        if not profiles:
            return None
        payload = {
            "schema_version": 1,
            "generated_at": _utc_now().isoformat().replace("+00:00", "Z"),
            "sport": "NCAAF",
            "source": result.get("source") or "CollegeFootballData /stats/season/advanced",
            "license": "active CFBD API tier",
            "shadow_only": True,
            "coverage": {"season": result.get("season"), "teams": len(profiles), "garbage_time_excluded": True},
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
                     "form": r.get("form", ""), "pos": None, "_official": r.get("pos"), "qual": "",
                     "rating": round(power_rating(name_map.get(t, t), r), 2)})
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


def _is_espn(item, label=None):
    """True if this news item is ESPN-branded under any spelling.

    ESPN is excluded outright everywhere in the news pipeline (see
    PROVIDER_COMPLIANCE.md -- no licensed ESPN developer feed). An exact
    `label == "ESPN"` check only catches the one canonical string that
    _source_label() itself produces (from the "espn fc" fix-up); it misses
    every other ESPN-branded source string Google News' <source> tag can
    hand back for syndicated/regional ESPN content -- "ESPN.com", "ESPN NFL
    Nation", "ESPN Deportes", "ESPN India", lowercase "espn", etc. Check the
    raw source/feed fields too, not just the post-_source_label() label, so
    nothing ESPN-branded slips through before normalization collapses it.
    """
    candidates = [label, item.get("source"), item.get("feed")]
    return any(re.search(r"\bespn\b", str(c), re.IGNORECASE) for c in candidates if c)


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
        if _is_espn(item, item["source"]):
            # ESPN is excluded outright, not just deprioritized -- otherwise a
            # stale ESPN item sitting in a previous run's cached data.json
            # (loaded via _load_previous_news for feed-diversity carryover)
            # would keep resurfacing here even though add_item() already
            # rejects it on fresh intake. _is_espn() matches any ESPN-branded
            # source string, not just an exact "ESPN" label -- see its
            # docstring for why the exact-match version wasn't enough.
            continue
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
        if _is_espn(item, item["source"]):
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

def _current_soccer_season_label():
    """European club season label ("2025-26"), by the same Aug-start
    convention every domestic league/UCL actually uses. WC only runs one
    short window every four years, so this label is mostly a no-op there --
    harmless, since a reset can only ever fire between two WC tournaments
    fetched years apart, never mid-tournament."""
    today = datetime.date.today()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def _load_player_db():
    try:
        with open(PLAYER_DB_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {"_matches": [], "players": {}}

def update_player_db(matches):
    """Fold finished matches' lineups + scores into the per-competition player DB.
    Tracks apps, starts, clean sheets (team conceded 0 while player started),
    and role from the formation. Idempotent per match id.

    Resets to a blank slate at each season boundary (see
    _current_soccer_season_label): this file previously had no season concept
    at all, so it would have kept accumulating a single club's clean sheets
    across every season forever, past and future blended into one number --
    dishonest for a feature literally named "Team of the TOURNAMENT". Caught
    while investigating why UCL's 2025-26 season (already finished) couldn't
    show real defenders: the fix for THAT was a data-availability gap
    (backfill_lineups.py, blocked by provider plan tier), but this is a
    separate, real bug this file always had, worth fixing at the same time
    rather than letting next season quietly inherit this one's numbers.
    """
    if COMP["sport"] != "soccer":
        return None
    db = _load_player_db()
    season = _current_soccer_season_label()
    if db.get("_season") != season:
        db = {"_matches": [], "players": {}}
    db["_season"] = season
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


def build_weekly_awards(matches):
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

    recent = []
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        ko = _dt(m.get("kickoff"))
        sc = m.get("score") or {}
        if not ko or ko < window or sc.get("home") is None or sc.get("away") is None:
            continue
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
        (hits if pr["pick"] == winner else misses).append(row)
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


# fetch_api_football_box_scores() now attaches m['lineups'] from
# API-FOOTBALL's free-tier /fixtures/lineups (2026-07-25) -- the first real,
# currently-fetching lineup source since ESPN's was removed for licensing
# reasons (Sportmonks, the other source this codebase knows how to use,
# still needs a key that isn't configured). Gate the defense/keeper backfill
# on this explicitly rather than on the player DB happening to be empty: a
# prior fix (2026-07-20) tried to make the backfill "stay dormant" without a
# real lineup source, but stale entries from when ESPN lineups WERE flowing
# kept silently feeding it anyway, since nothing actually enforced the
# dormancy. Coverage is intentionally narrow per run (LIVE, near-kickoff
# upcoming, and matches finished within the last 2 days, capped at 10
# fixtures) to protect the shared 100/day free-plan quota, so the player DB
# builds up gradually across runs rather than backfilling a full season at
# once -- defender/keeper rankings should be treated as still-warming-up
# until more matches have been captured.
LINEUP_BACKFILL_ENABLED = True


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
    # A balanced model XI is a 4-3-3: the old caps allowed 12 players
    # (3 FWD + 4 MID + 4 DEF + 1 GK) while still labeling the result an XI.
    caps = {"FWD": 3, "MID": 3, "DEF": 4, "GK": 1}
    xi = []
    for role, cap in caps.items():
        xi += [p for p in ranked if p["role"] == role][:cap]
    bench = [p for p in ranked if p not in xi][:5]
    # Fill missing DEF/GK from the player DB via clean sheets -- but only when
    # LINEUP_BACKFILL_ENABLED says a real lineup source is actually active.
    # Never fall back to "the file happens to have entries in it": stale data
    # from a since-removed provider must never silently resurface here.
    db = _load_player_db() if LINEUP_BACKFILL_ENABLED else {}
    backfilled = 0
    if LINEUP_BACKFILL_ENABLED and db.get("players"):
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
                xi_names.add(norm(r["name"])); need -= 1; backfilled += 1
    DIAG.append(f"team of tournament: {len(xi)} players "
                f"({', '.join(sorted(set(p['role'] for p in xi)))})")
    note = "Attack ranked by goals, assists and team strength."
    note += (" Defence and goalkeeper ranked by clean sheets from accumulated lineups."
              if backfilled else
              " Defenders and keepers only appear once one registers a goal or assist this"
              " tournament — we don't have a lineup data source to rank them by clean sheets"
              " yet, so we don't fake it.")
    return {"xi": xi, "bench": bench, "v": 2, "note": note}

def fetch_scorers():
    try:
        d = _get(f"{FD_BASE}/competitions/{COMP["fd"]}/scorers?limit=20", {"X-Auth-Token": FOOTBALL_DATA_KEY}, provider="football_data")
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
PICK_SCHEMA_VERSION = 2
MODEL_CODE_MARKER = "matchday-predictor-integrity-2026-07"
WC_RESULT_MIGRATION_FILE = "wc_result_migration.json"

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


def _lock_decision(match, now=None):
    """Classify a fixture without ever turning post-kickoff data into a pick."""
    status = str((match or {}).get("status") or "").upper()
    kickoff = _parse_kickoff((match or {}).get("kickoff"))
    if status != "UPCOMING":
        return {"state": "quarantine", "reason": f"first_seen_{status.lower() or 'unknown'}",
                "status_at_lock": status or None, "kickoff": kickoff}
    if kickoff is None:
        return {"state": "wait", "reason": "missing_or_unparseable_kickoff",
                "status_at_lock": status, "kickoff": None}
    current = _utc_now(now)
    lead_seconds = (kickoff - current).total_seconds()
    if lead_seconds < 0:
        return {"state": "quarantine", "reason": "past_due_upcoming",
                "status_at_lock": status, "kickoff": kickoff, "lead_seconds": lead_seconds}
    competition = str((match or {}).get("_comp") or COMP_KEY).upper()
    lock_hours = pregame_context.lock_window_hours(competition)
    if lead_seconds > lock_hours * 3600:
        return {"state": "wait", "reason": "outside_lock_window",
                "status_at_lock": status, "kickoff": kickoff, "lead_seconds": lead_seconds,
                "lock_window_hours": lock_hours}
    return {"state": "eligible", "reason": "verified_pregame_window",
            "status_at_lock": status, "kickoff": kickoff, "lead_seconds": lead_seconds,
            "locked_at": current, "lock_window_hours": lock_hours}


def _record_is_official(rec):
    try:
        lead = float(rec.get("lead_time_seconds"))
    except (TypeError, ValueError):
        return False
    locked_at = _parse_kickoff(rec.get("locked_at"))
    kickoff = _parse_kickoff(rec.get("kickoff"))
    if locked_at is None or kickoff is None:
        return False
    calculated_lead = (kickoff - locked_at).total_seconds()
    # Records created before sport-aware lock windows retain the historically
    # published 12-hour boundary; new records freeze their own window.
    try:
        lock_hours = float(rec.get("lock_window_hours", LOCK_WINDOW_HOURS))
    except (TypeError, ValueError):
        return False
    return bool(rec.get("schema_ver") == PICK_SCHEMA_VERSION
                and rec.get("model_code_marker") == MODEL_CODE_MARKER
                and rec.get("fixture_id")
                and rec.get("integrity_eligible") is True
                and rec.get("integrity_status") == "verified"
                and rec.get("status_at_lock") == "UPCOMING"
                and 0 <= lead <= lock_hours * 3600
                and abs(calculated_lead - lead) <= 1.0
                and isinstance(rec.get("prediction_snapshot"), dict)
                and isinstance(rec.get("input_snapshot"), dict))


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
    comparison_pick = prediction.get("regulation_pick") or prediction.get("pick")
    locked_at = decision["locked_at"].isoformat().replace("+00:00", "Z")
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
        "market_snapshot_at": locked_at if market.get("home_pct") is not None else None,
        "market_gap": upset.get("market_gap_pct"),
        "upset_snapshot": {"candidate": upset.get("candidate_name"),
                           "class": upset.get("upset_class"),
                           "market_dog_pct": upset.get("market_dog_pct"),
                           "model_dog_pct": upset.get("model_dog_pct"),
                           "upset_edge": upset.get("upset_edge"),
                           "radar": upset.get("radar"),
                           "standings_candidate": upset.get("standings_candidate"),
                           "standings_gap_pct": upset.get("standings_gap_pct"),
                           "gate": "open" if upset.get("triggered") else ("blocked" if upset.get("blocked") else "none"),
                           "box_score_edge": upset.get("box_score_edge")},
        "box_score_available": bool(match.get("stats_extra") or match.get("stats")),
        "data_availability": availability,
        "damp_pct": prediction.get("damp_pct"), "mkt_pull": prediction.get("mkt_pull"),
        "model_ver": "v4-integrity-advancement", "model_code_marker": MODEL_CODE_MARKER,
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
    if snap.get("is_knockout") is True:
        return True
    return bool(COMP.get("sport") == "soccer" and COMP.get("single_elimination")
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
    reg = sc_obj.get("reg") or {}
    market_result = _side_result(reg.get("home"), reg.get("away"))
    if market_result is None:
        if is_knockout and COMP.get("has_draws"):
            # Do not guess a soccer 1X2 settlement from an extra-time score.
            market_result = (locked_pick or {}).get("market_result")
        else:
            # Non-draw moneylines (and ordinary final scores) settle on the winner.
            market_result = ultimate
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


def _load_wc_result_migration():
    if COMP_KEY != "WC":
        return {}
    try:
        with open(WC_RESULT_MIGRATION_FILE, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload.get("fixtures") or {}
    except Exception as exc:
        DIAG.append(f"WC result migration unavailable: {exc}")
        return {}


def _apply_wc_result_migration(picks):
    fixtures = _load_wc_result_migration()
    changed = False
    for rec in picks.values():
        fixture_id = str(rec.get("fixture_id") or "")
        migrated = fixtures.get(fixture_id)
        if not migrated:
            continue
        score = migrated.get("score") or {}
        before = (rec.get("score"), rec.get("result"), rec.get("market_result"),
                  rec.get("model_hit"), rec.get("market_hit"),
                  rec.get("result_snapshot"), rec.get("result_verification"))
        match = {"stage": rec.get("stage"), "score": score}
        model_result, market_result = _scorecard_results(match, rec)
        _refresh_record_result(rec, score, source=migrated.get("source") or "wc_result_migration",
                               observed_at=migrated.get("verified_at"))
        if model_result:
            _apply_scorecard_grade(rec, model_result, market_result)
        rec["result_verification"] = {"status": "authoritative_result_verified",
                                      "source": migrated.get("source"),
                                      "verified_at": migrated.get("verified_at")}
        after = (rec.get("score"), rec.get("result"), rec.get("market_result"),
                 rec.get("model_hit"), rec.get("market_hit"),
                 rec.get("result_snapshot"), rec.get("result_verification"))
        changed = changed or before != after
    return changed


def _apply_scorecard_grade(rec, model_result, market_result):
    """Apply model and 1X2 market grades without touching the score string."""
    rec["model_result"] = model_result
    rec["result"] = model_result  # compatibility with the existing scorecard UI
    rec["model_hit"] = (rec.get("pick") == model_result)
    if market_result:
        rec["market_result"] = market_result
        rec["market_hit"] = (rec.get("market_pick") == market_result) if rec.get("market_pick") else None
    else:
        # Never preserve a legacy ultimate-winner market grade when the actual
        # regulation settlement is unknown.
        rec["market_result"] = None
        rec["market_hit"] = None
    if rec.get("upset_candidate"):
        rec["upset_hit"] = (rec.get("upset_candidate") == model_result)
    knockout = rec.get("outcome_basis") == "ultimate_winner" or _is_advancement_fixture({}, rec)
    probs = (rec.get("advancement_probs") or {}) if knockout else (rec.get("regulation_probs") or rec.get("probs") or {})
    if knockout:
        rec["brier3"] = None
        rec["log_loss"] = None
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

def _hours_to_kickoff(m):
    """None if kickoff is missing/unparseable, else hours from now to kickoff
    (negative once kickoff has passed)."""
    try:
        ko = datetime.datetime.fromisoformat(str(m.get("kickoff") or "").replace("Z", "+00:00"))
    except Exception:
        return None
    return (ko - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600.0

def update_scorecard(matches):
    """Lock a pick once the match is within LOCK_WINDOW_HOURS of kickoff, so
    the model can use as much pre-game information as possible (form, injuries,
    near-game market odds) right up to a fair cutoff; grade it once finished.
    Picks themselves are never rewritten after they lock — market-comparison
    fields backfill once odds appear if they weren't in yet at lock time.
    A fixture first seen after kickoff is never admitted to the official record."""
    picks = _load_picks(); dirty = _quarantine_legacy_records(picks)
    expected_locks = set()
    expected_grades = set()
    dirty = _apply_wc_result_migration(picks) or dirty
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
            comparison_pick = rec.get("regulation_pick") or rec.get("pick")
            rec["pick_mkt"] = ({"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}.get(comparison_pick)
                                if mk.get("home_pct") is not None else None)
            rec["value_side"] = value_side; rec["value_edge"] = value_edge; rec["value_mkt"] = value_mkt
            rec["value_name"] = ({"h": rec["home"], "a": rec["away"], "d": "Draw"}.get(value_side) if value_side else None)
            rec["post_lock_market_snapshot"] = {"h": mk.get("home_pct"), "d": mk.get("draw_pct"), "a": mk.get("away_pct")}
            rec["market_backfilled_at"] = _utc_now().isoformat().replace("+00:00", "Z")
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
            # closing-line value: did the market move toward our pick after we locked it?
            close = (_load_open().get(pairkey(rec["home"], rec["away"])) or {}).get("last")
            comparison_pick = rec.get("regulation_pick") or rec.get("pick")
            if close and rec.get("pick_mkt") is not None and comparison_pick in ("h", "d", "a"):
                rec["clv"] = round(close[comparison_pick] - rec["pick_mkt"], 1)
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
    legacy_graded = [p for p in quarantined if p.get("result")]
    mk_graded = [p for p in graded if p.get("market_hit") is not None]
    disagree = [p for p in graded if p.get("market_pick") and p.get("pick") != p.get("market_pick")]
    rows = []
    for source in sorted(picks.values(), key=lambda p: p.get("kickoff") or "", reverse=True):
        row = _json_safe(source)
        if not _record_is_official(source):
            row["stage"] = f"Legacy/unverified · {row.get('stage') or 'Fixture'}"
            row["integrity_label"] = "no provable pregame timestamp — counted in the all-time total, excluded from the verified record"
            row["legacy"] = True
        rows.append(row)
    # Brier score on the pick side (0 = perfect, <0.2 = well calibrated)
    briers = [((p.get("confidence") or 0)/100.0 - (1.0 if p.get("model_hit") else 0.0))**2 for p in graded]
    briers3 = [p.get("brier3") for p in graded if p.get("brier3") is not None]
    logloss = [p.get("log_loss") for p in graded if p.get("log_loss") is not None]
    advancement_briers = [p.get("brier_advancement") for p in graded if p.get("brier_advancement") is not None]
    advancement_logloss = [p.get("log_loss_advancement") for p in graded if p.get("log_loss_advancement") is not None]
    upset_watched = [p for p in graded if p.get("upset_candidate")
                     and (p.get("upset_snapshot") or {}).get("radar")
                     and (p.get("upset_snapshot") or {}).get("standings_gap_pct") is not None]
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
    # favorite vs. underdog: was the picked side's own predicted probability >= 50%?
    # (a plurality winner below 50% only happens in three-way soccer markets.)
    favorite_picks = [p for p in graded if (p.get("confidence") or 0) >= 50]
    underdog_picks = [p for p in graded if (p.get("confidence") or 0) < 50]
    favorite_underdog = {"favorite": {"n": len(favorite_picks), "hits": sum(1 for p in favorite_picks if p.get("model_hit"))},
                         "underdog": {"n": len(underdog_picks), "hits": sum(1 for p in underdog_picks if p.get("model_hit"))}}
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
    signal_quality = {k: _signal(k) for k in
                      ("class", "market_power", "form", "gd", "rest", "pts", "record", "margin", "rank", "srs", "elo")}
    # error review: recent misses with their captured evidence
    misses = [{"home": p.get("home"), "away": p.get("away"), "pick": p.get("pick"),
               "score": p.get("score"), "upset": (p.get("upset_snapshot") or {}).get("candidate"),
               "gap": p.get("market_gap")}
              for p in sorted(graded, key=lambda x: x.get("kickoff") or "", reverse=True)
              if not p.get("model_hit")][:10]
    value_summary = {"all": _vs(vals), "chances": _vs(chances),
                      "pending": sum(1 for p in official if p.get("value_side") and not p.get("result"))}
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
                            "pending": len(quarantined) - len(legacy_graded),
                            "model_hits": legacy_hits,
                            "label": "Legacy/unverified — excluded from official record"},
            "legacy": {"graded": len(legacy_graded), "model_hits": legacy_hits,
                       "accuracy": round(legacy_hits / len(legacy_graded) * 100, 1) if legacy_graded else None,
                       "market_graded": len(legacy_market),
                       "market_hits": sum(1 for p in legacy_market if p.get("market_hit"))},
            "market_graded": len(mk_graded),
            "market_hits": sum(1 for p in mk_graded if p.get("market_hit")),
            "disagree": len(disagree),
            "disagree_hits": sum(1 for p in disagree if p.get("model_hit")),
            "brier": round(sum(briers)/len(briers), 3) if briers else None,
            "brier3": round(sum(briers3)/len(briers3), 3) if briers3 else None,
            "log_loss": round(sum(logloss)/len(logloss), 3) if logloss else None,
            "advancement_graded": len(advancement_briers),
            "brier_advancement": round(sum(advancement_briers)/len(advancement_briers), 3) if advancement_briers else None,
            "log_loss_advancement": round(sum(advancement_logloss)/len(advancement_logloss), 3) if advancement_logloss else None,
            "calibration": calib,
            "home_away": home_away,
            "favorite_underdog": favorite_underdog,
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
    if SPORTSDATAIO_PREGAME_ENABLED:
        try:
            attached = adapter.attach_pregame(matches)
            DIAG.append(f"SportsDataIO availability: {attached['injuries']} player labels, "
                        f"{attached['lineups']} lineup(s)")
            for error in attached.get("errors") or []:
                DIAG.append(f"SportsDataIO {error.get('input')} unavailable: "
                            f"{_scrub(error.get('error'))}")
        except ProviderError as exc:
            DIAG.append(f"SportsDataIO availability unavailable on this plan: {_scrub(exc)}")
    else:
        DIAG.append("SportsDataIO availability: disabled until a live redistribution tier is confirmed")
    return adapter, matches, st, tables


US_PRO_STANDINGS_GROUPS = {
    "MLB": {
        "American League East": ["New York Yankees", "Boston Red Sox", "Toronto Blue Jays", "Tampa Bay Rays", "Baltimore Orioles"],
        "American League Central": ["Cleveland Guardians", "Detroit Tigers", "Kansas City Royals", "Minnesota Twins", "Chicago White Sox"],
        "American League West": ["Houston Astros", "Seattle Mariners", "Texas Rangers", "Los Angeles Angels", "Oakland Athletics", "Athletics"],
        "National League East": ["Atlanta Braves", "Miami Marlins", "New York Mets", "Philadelphia Phillies", "Washington Nationals"],
        "National League Central": ["Chicago Cubs", "Cincinnati Reds", "Milwaukee Brewers", "Pittsburgh Pirates", "St. Louis Cardinals"],
        "National League West": ["Arizona Diamondbacks", "Colorado Rockies", "Los Angeles Dodgers", "San Diego Padres", "San Francisco Giants"],
    },
    "NFL": {
        "AFC East": ["Buffalo Bills", "Miami Dolphins", "New England Patriots", "New York Jets"],
        "AFC North": ["Baltimore Ravens", "Cincinnati Bengals", "Cleveland Browns", "Pittsburgh Steelers"],
        "AFC South": ["Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars", "Tennessee Titans"],
        "AFC West": ["Denver Broncos", "Kansas City Chiefs", "Las Vegas Raiders", "Los Angeles Chargers"],
        "NFC East": ["Dallas Cowboys", "New York Giants", "Philadelphia Eagles", "Washington Commanders"],
        "NFC North": ["Chicago Bears", "Detroit Lions", "Green Bay Packers", "Minnesota Vikings"],
        "NFC South": ["Atlanta Falcons", "Carolina Panthers", "New Orleans Saints", "Tampa Bay Buccaneers"],
        "NFC West": ["Arizona Cardinals", "Los Angeles Rams", "San Francisco 49ers", "Seattle Seahawks"],
    },
    "NBA": {
        "Eastern Conference": ["Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls", "Cleveland Cavaliers", "Detroit Pistons", "Indiana Pacers", "Miami Heat", "Milwaukee Bucks", "New York Knicks", "Orlando Magic", "Philadelphia 76ers", "Toronto Raptors", "Washington Wizards"],
        "Western Conference": ["Dallas Mavericks", "Denver Nuggets", "Golden State Warriors", "Houston Rockets", "Los Angeles Clippers", "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Minnesota Timberwolves", "New Orleans Pelicans", "Oklahoma City Thunder", "Phoenix Suns", "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Utah Jazz"],
    },
}


def _pro_standings_pct(team):
    played = max(1.0, float(team.get("pld") or 0))
    return (float(team.get("w") or 0) + 0.5 * float(team.get("d") or 0)) / played


def _group_us_pro_standings(tables, competition):
    """Return conventional pro-league standings groups, never model-sorted.

    Some free providers expose results but no division metadata. Pro-league
    membership is fixed league structure, so a local map is safer than showing
    a fabricated flat table. Unknown expansion/renamed teams remain visible in
    an explicit unassigned table instead of silently disappearing.
    """
    layout = US_PRO_STANDINGS_GROUPS.get(competition)
    if not layout:
        return tables
    rows = {}
    for table in tables or []:
        if table.get("table_type") == "power_ratings":
            continue
        for team in table.get("teams") or []:
            if team.get("name") and not is_placeholder_team_name(team.get("name")):
                rows[norm(team["name"])] = dict(team)
    membership = {norm(name): group for group, names in layout.items() for name in names}
    grouped = {group: [] for group in layout}
    unassigned = []
    for key, team in rows.items():
        group = membership.get(key)
        (grouped[group] if group else unassigned).append(team)
    payload = []
    for group in layout:
        teams = grouped[group]
        if not teams:
            continue
        teams.sort(key=lambda t: (-_pro_standings_pct(t),
                                  -float(t.get("gd") or 0), str(t.get("name") or "")))
        for i, team in enumerate(teams, 1):
            team["pos"] = i
            team["group"] = group
            team["win_pct"] = round(_pro_standings_pct(team), 6)
        payload.append({"group": group, "table_type": "official_standings", "teams": teams})
    if unassigned:
        unassigned.sort(key=lambda t: (-_pro_standings_pct(t),
                                       str(t.get("name") or "")))
        for i, team in enumerate(unassigned, 1):
            team["pos"] = i
            team["group"] = "League standings"
            team["win_pct"] = round(_pro_standings_pct(team), 6)
        payload.append({"group": "League standings", "table_type": "official_standings", "teams": unassigned})
    return payload


def _append_power_ratings_table(tables):
    teams = [dict(team) for table in tables or []
             if table.get("table_type") != "power_ratings"
             for team in table.get("teams") or []]
    seen, unique = set(), []
    for team in teams:
        key = norm(team.get("name"))
        if key and key not in seen:
            seen.add(key)
            unique.append(team)
    teams = unique
    teams.sort(key=lambda t: (-float(t.get("rating") or 0), str(t.get("name") or "")))
    for i, team in enumerate(teams, 1):
        team["pos"] = i
    return list(tables or []) + ([{"group": "Power Ratings", "table_type": "power_ratings", "teams": teams}] if teams else [])


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


def _balldontlie_cache_seconds(matches, now=None):
    """Use a short schedule cache around games, a longer one otherwise."""
    current = now or datetime.datetime.now(datetime.timezone.utc)
    for match in matches or []:
        if match.get("status") == "LIVE":
            return BALLDONTLIE_ACTIVE_CACHE_MIN * 60
        if match.get("status") != "UPCOMING":
            continue
        kickoff = _parse_kickoff(match.get("kickoff"))
        if kickoff is None:
            continue
        hours = (kickoff - current).total_seconds() / 3600.0
        if -8 <= hours <= 4:
            return BALLDONTLIE_ACTIVE_CACHE_MIN * 60
    return BALLDONTLIE_CACHE_MIN * 60


def fetch_balldontlie_bundle():
    """Fetch real free-tier schedules/scores without paid-only substitutions."""
    adapter = BallDontLieAdapter(BALLDONTLIE_KEY, COMP_KEY)
    cache_file = f"balldontlie_games_{COMP_KEY.lower()}_cache.json"
    matches = None
    try:
        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as handle:
                cached_matches = json.load(handle)
            cache_age = time.time() - os.path.getmtime(cache_file)
            if cache_age < _balldontlie_cache_seconds(cached_matches):
                matches = cached_matches
                DIAG.append("BALLDONTLIE fixtures: local cache")
    except Exception:
        matches = None
    schedule_fetched_live = matches is None
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

    if schedule_fetched_live:
        # Give the free tier's rate-limit window room to breathe before the
        # much longer season-to-date pagination starts below -- schedule()
        # just made several rapid requests of its own.
        time.sleep(BallDontLieAdapter.SEASON_PAGE_DELAY_SEC)

    # schedule()'s narrow window keeps the display list fresh but starves
    # standings/SRS/Elo of real season sample size. Pull season-to-date
    # results separately, cached for hours since a full pull re-pages
    # through the whole season (see BallDontLieAdapter.season_games).
    season_cache_file = f"balldontlie_season_{COMP_KEY.lower()}_cache.json"
    season_matches = None
    try:
        if (os.path.exists(season_cache_file)
                and time.time() - os.path.getmtime(season_cache_file) < BALLDONTLIE_SEASON_CACHE_MIN * 60):
            with open(season_cache_file, encoding="utf-8") as handle:
                season_matches = json.load(handle)
            DIAG.append("BALLDONTLIE season-to-date: local cache")
    except Exception:
        season_matches = None
    if season_matches is None:
        try:
            season_matches = adapter.season_games()
            tmp = season_cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(season_matches, handle, ensure_ascii=False)
            os.replace(tmp, season_cache_file)
            DIAG.append(f"BALLDONTLIE season-to-date: fetched {len(season_matches)} finished games")
        except ProviderError as e:
            if os.path.exists(season_cache_file):
                with open(season_cache_file, encoding="utf-8") as handle:
                    season_matches = json.load(handle)
                DIAG.append(f"BALLDONTLIE season-to-date: stale cache after provider limit/error — {_scrub(e)}")
            else:
                # Better a narrow-window standings table than none at all.
                season_matches = matches
                DIAG.append(f"BALLDONTLIE season-to-date: unavailable, using display window — {_scrub(e)}")

    st, tables = compute_us_sport_standings(season_matches)
    adapter._model_history = season_matches
    DIAG.append(f"BALLDONTLIE fixtures: {len(matches)} in free-tier display window")
    DIAG.append(f"BALLDONTLIE standings: {sum(r['pld'] for r in st.values())} team-games from "
                f"{len(season_matches)} season-to-date finished games (no standings endpoint on free tier)")
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
    if COMP_KEY == "NBA":
        # NBA's /standings endpoint doesn't expose points-for/against (unlike
        # NFL's), so the adapter leaves gf/ga at 0 -- derive real per-team
        # scoring averages from finished games instead, same approach the
        # CFBD/CBBD adapters already use.
        agg = {}
        for row in matches:
            if row.get("status") != "FINISHED":
                continue
            sc = row.get("score") or {}
            hs, as_ = sc.get("home"), sc.get("away")
            if hs is None or as_ is None:
                continue
            for name, gf, ga in ((row["home"]["name"], hs, as_), (row["away"]["name"], as_, hs)):
                a = agg.setdefault(name.lower(), {"gf": 0, "ga": 0, "pld": 0})
                a["gf"] += gf; a["ga"] += ga; a["pld"] += 1
        for key, rec in st.items():
            a = agg.get(key)
            if a and a["pld"]:
                rec["gf"], rec["ga"] = a["gf"], a["ga"]
        for table in tables:
            for team in table.get("teams") or []:
                a = agg.get((team.get("name") or "").lower())
                if a and a["pld"]:
                    team["gf"], team["ga"] = a["gf"], a["ga"]
        DIAG.append(f"API-Sports NBA: derived real gf/ga for {sum(1 for a in agg.values() if a['pld'])} teams from finished games")
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
    cache_file = f"college_{COMP_KEY.lower()}_bundle_v7_cache.json"
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
    normalize_match_results(all_matches)
    # Retain the complete licensed season only in memory for local aggregate
    # model training; the public dashboard still receives the bounded window.
    adapter._model_history = all_matches
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


def fetch_nflverse_leaders():
    """Cache NFL season player-stat leaders from nflverse-data's public,
    unauthenticated `stats_player` release (CC BY 4.0; ESPN's separate
    `espn_data` release is never touched -- see NflverseAdapter's docstring
    in provider_adapters.py and PROVIDER_COMPLIANCE.md).

    Mirrors fetch_college_leaders()'s cache-then-fetch-then-fall-back-to-
    stale-cache-on-provider-error shape so an nflverse hiccup degrades to
    the last good leaderboard instead of blanking the panel.
    """
    cache_file = "nflverse_leaders_cache.json"
    leaders = None
    try:
        if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < NFLVERSE_LEADERS_CACHE_MIN * 60:
            with open(cache_file, encoding="utf-8") as handle:
                leaders = json.load(handle)
            DIAG.append("nflverse leaders: local cache")
    except Exception:
        leaders = None
    if leaders is None:
        try:
            leaders = NflverseAdapter().leaders()
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(leaders, handle, ensure_ascii=False)
            os.replace(tmp, cache_file)
            count = sum(len(c.get("leaders") or []) for c in (leaders.get("categories") or []))
            DIAG.append(f"nflverse leaders: fetched {count} leaderboard entries across "
                        f"{len(leaders.get('categories') or [])} categories (season {leaders.get('season')})")
        except ProviderError as exc:
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as handle:
                    leaders = json.load(handle)
                DIAG.append(f"nflverse leaders: stale cache after provider limit/error — {_scrub(exc)}")
            else:
                DIAG.append(f"nflverse leaders unavailable: {_scrub(exc)}")
                leaders = {}
    return leaders


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
            } for match in near}
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
        for key in ("injuries_shadow", "lineups", "personnel", "pregame_provenance"):
            if row.get(key):
                match[key] = row[key]
    return {"injuries": sum(_shadow_injury_count(match) for match in near),
            "lineups": sum(bool(match.get("lineups")) for match in near)}


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
    snapshots = []
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
        snapshots.append({
            "fixture_id": str(match.get("id")), "competition": COMP_KEY,
            "kickoff": match.get("kickoff"), "observed_at": observed_at,
            "market_type": "1x2" if len(keys) == 3 else "moneyline",
            "odds_format": "probability",
            "outcomes": {key: float(market[source_keys[key]]) / 100.0 for key in keys},
            "source_snapshot_id": market.get("snapshot_id") or
                                  f"{match.get('id')}:{observed_at}",
        })
    if not snapshots:
        return 0
    # Replaying a cache is not a new provider fetch. Keeping the batch fetch
    # time tied to the newest actual quote also makes identical cache replays
    # deduplicate in the append-only ledger.
    fetched_at = max(snapshot["observed_at"] for snapshot in snapshots)
    try:
        result = market_snapshots.append_batch("market_snapshot_ledger.jsonl", {
            "source": "The Odds API consensus",
            "authorization_basis": "licensed",
            "source_reference": "https://the-odds-api.com/",
            "fetched_at": fetched_at, "snapshots": snapshots,
        }, recorded_at=now.isoformat())
        DIAG.append(f"market ledger: {'appended' if result['created'] else 'deduplicated'} "
                    f"{len(snapshots)} pregame snapshot(s)")
    except (OSError, ValueError) as exc:
        DIAG.append(f"market ledger: snapshot rejected — {_scrub(exc)}")
    return len(snapshots)



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
        if COMP_KEY in US_PRO_STANDINGS_GROUPS:
            sports_tables = _group_us_pro_standings(sports_tables, COMP_KEY)
            # Keep match hydration/model inputs aligned with the official table
            # group and within-group rank shown to users.
            for table in sports_tables:
                for team in table.get("teams") or []:
                    rec = st.get(norm(team.get("name")))
                    if rec is not None:
                        rec["group"] = table.get("group")
                        rec["pos"] = team.get("pos")
        print(f"  got {len(matches)} fixtures ({provider_name})")
        training_matches = normalize_match_results(
            getattr(sports_adapter, "_model_history", matches))
        srs_ratings = compute_srs(training_matches) if COMP["sport"] != "soccer" else {}
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
    else:
        raw = fetch_raw_matches(); print(f"  got {len(raw)} raw fixtures")
        st = compute_standings(raw)
        matches = build_matches(raw, st)
        training_matches = normalize_match_results(matches)
        name_map = {}
        for m in raw:
            for t in (m.get("homeTeam"), m.get("awayTeam")):
                if t and t.get("name"): name_map[norm(t["name"])] = t["name"]

    DIAG.append(f"ratings: {len(_load_ratings())} teams loaded")
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
    record_market_snapshots(matches)

    if COMP["sport"] == "soccer":
        print("Fetching soccer detail (Sportmonks)…")
        fetch_sportmonks_enrichment(matches)
        print("Fetching soccer box scores + lineups (API-FOOTBALL)…")
        fetch_api_football_box_scores(matches)
        # Injuries run right after box scores/lineups above, on purpose --
        # it reuses that call's just-refreshed 'dates' fixture-id cache
        # (see fetch_api_football_injuries()'s docstring) instead of paying
        # for a second /fixtures lookup against the same shared daily quota.
        print("Fetching soccer injuries (API-FOOTBALL)…")
        fetch_api_football_injuries(matches)
    elif COMP.get("source") != "sportsdataio":
        print("Fetching sport-specific personnel context (SportsDataIO)…")
        fetch_sportsdataio_pregame_overlay(matches)

    venue_shadow = pregame_context.derive_venue_context(matches, training_matches, COMP["sport"])
    if venue_shadow.get("matches"):
        DIAG.append(f"venue context shadow: {venue_shadow['matches']} match(es), production weight 0")

    # for US sports, pull championship odds first and fold them into team strength
    # so predictions use market-implied strength (their soccer-value equivalent)
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
    if COMP.get("source") in {"sportsdataio", "balldontlie", "cfbd", "cbbd", "apisports"} and COMP.get("outright"):
        print("Fetching championship odds (team strength)…")
        title = fetch_outrights(code_map)
        apply_market_strength(title, known_names)

    if COMP.get("source") in {"sportsdataio", "balldontlie", "cfbd", "cbbd", "apisports"}:
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
                    team["rating"] = round(power_rating(team["name"]), 2)
        # Official standings stay record-sorted. Model opinion gets its own
        # clearly labeled, league-wide table instead of replacing division rank.
        if COMP_KEY in US_PRO_STANDINGS_GROUPS:
            sports_tables = _append_power_ratings_table(sports_tables)

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
    if COMP_KEY == "NFL":
        challenger = attach_nfl_challenger_shadows(matches)
        if challenger.get("matches"):
            DIAG.append(f"NFL learned challenger shadow: {challenger['matches']} match(es), production weight 0")
    elif COMP_KEY == "MLB":
        challenger = attach_mlb_challenger_shadows(matches)
        if challenger.get("matches"):
            DIAG.append(f"MLB run-strength challenger shadow: {challenger['matches']} match(es), production weight 0")
    mlb_promotion_policy = load_mlb_promotion_policy() if COMP_KEY == "MLB" else None
    nfl_adjustment_policy = load_nfl_adjustment_policy() if COMP_KEY == "NFL" else None
    promoted_matches = 0
    for m in matches:
        m["prediction"] = predict(m["home"], m["away"], m["markets"], m)
        context = m.get("pregame_context") or {}
        m["prediction"]["publication_state"] = (
            "lock_candidate" if context.get("phase") == "lock_window" else "preliminary")
        m["prediction"]["lock_readiness"] = context
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
        if mlb_promotion_policy and apply_mlb_promotion(m, m["prediction"], mlb_promotion_policy):
            promoted_matches += 1
        if nfl_adjustment_policy and apply_nfl_adjustment(m, m["prediction"], nfl_adjustment_policy):
            promoted_matches += 1
        m["prediction"]["totals"] = predict_totals(m["home"], m["away"], m["markets"])
        m["watchability"] = compute_watchability(m)
    if promoted_matches:
        label = "NFL calibrated-Elo historical pilot" if COMP_KEY == "NFL" else "MLB reviewed challenger blend"
        DIAG.append(f"{label} applied to {promoted_matches} match(es)")
    print(f"  merged odds onto {merged} fixtures ({fuzzy} via name-variant match) · predictions on all {len(matches)}")

    print("Fetching title odds + news…")
    if title is None:
        title = fetch_outrights(code_map)
    if not title:
        title = estimate_title_odds(matches, code_map)
        if title:
            DIAG.append(f"title race: no market odds available, estimated from model ratings for {len(title)} teams")
    news = fetch_news()
    bracket = build_bracket(raw)
    third = third_race(st, name_map, code_map) if COMP["tournament"] else []

    # This groups-from-`st` builder predates the American-sports providers and
    # was only ever meant for soccer's GROUP_-tagged group stages (World Cup/
    # UCL). cfbd/cbbd/sportsdataio/balldontlie/apisports all tag each team
    # with its own real conference/division via the SAME "group" field, so
    # this fired for them too and its output silently WON over the adapter's
    # own sports_tables in the `if not standings: ...` fallback chain below --
    # even though sports_tables is the adapter's correctly-sorted, fully
    # populated table (win_pct, record, qual) and this rebuild drops all of
    # that down to a narrow field list. Worse, it sorted by `x["pos"] or 99`,
    # but CollegeFootballDataAdapter/CollegeBasketballDataAdapter's `model`
    # dict (this function's `st`) held every team's position frozen at the
    # pre-sort None (see the fix in provider_adapters.py's standings()) --
    # every team fell back to 99 either way, and Python's stable sort just
    # kept the API response order, live-observed as leagues that looked
    # completely unordered. Skip this generic path for the providers that
    # already return a real, sorted, fully-populated table of their own.
    groups = defaultdict(list)
    if COMP.get("source") not in {"cfbd", "cbbd", "sportsdataio", "balldontlie", "apisports"}:
        for t, r in st.items():
            gkey = r.get("group")
            if gkey:
                groups[gkey].append({
                    "name": name_map.get(t, t.title()), "code": code_map.get(t, ""),
                    "pos": r.get("pos"), "pld": r["pld"], "w": r["w"], "d": r["d"], "l": r["l"],
                    "gf": r["gf"], "ga": r["ga"], "gd": r["gd"], "pts": r["pts"], "form": r["form"],
                    "rating": round(power_rating(name_map.get(t, t)), 2),
                    "season_stale": bool(r.get("season_stale"))})
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
            is_projected = bool(ranks[0].get("projected"))
            rank_rows = [{"name": r["name"], "code": r["code"], "pos": r["rank"],
                          "pld": None, "w": None, "d": None, "l": None, "gf": None, "ga": None,
                          "gd": None, "pts": None, "form": "", "record": r["record"],
                          "qual": ({"status": f"CFP {r['rank']}", "note": "projected playoff seed (straight seeding)"} if COMP_KEY == "NCAAF" and not is_projected and r["rank"] <= 12 else "")}
                         for r in ranks]
            # A real poll and a recruiting-talent projection are different
            # kinds of claim -- labeling them the same ("Matchday Top 25")
            # would present a model estimate as if it were the real AP/
            # Coaches poll. See CFBD/CBBD's own rankings()/_projected_ranking()
            # for why this shows up at all: no real current-season poll AND
            # the season hasn't started yet (confirmed live 2026-07-26, off-
            # season fallback used to keep reaching backward into an already-
            # finished season's final poll instead).
            group_label = "Way-too-early Top 25 (model projection)" if is_projected else "Matchday Top 25"
            standings = [{"group": group_label, "teams": rank_rows}] + (standings or [])
        if COMP_KEY == "NCAAF" and proj and not bracket:
            bracket = proj
    if COMP_KEY == "NCAAM":
        bracketology = build_ncaam_bracketology(sports_tables)
    scorecard = update_scorecard(matches)
    apply_locked_picks(matches)
    # Top-level marker survives immutable legacy prediction snapshots and lets
    # multi_fetch detect that an otherwise fresh JSON file predates a model
    # input/schema change. Bump only when every sport needs one clean rebuild.
    for m in matches:
        m["model_signal_schema"] = MODEL_SIGNAL_SCHEMA
    weekly_awards = build_weekly_awards(matches)
    try:
        from generate_posts import publish_recap_if_due
        post = publish_recap_if_due(COMP_KEY, COMP["label"], scorecard, weekly_awards)
        if post:
            DIAG.append(f"posts: published '{post['title']}'")
    except Exception as e:
        DIAG.append(f"posts: skipped — {e}")
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
    elif COMP.get("source") in {"cfbd", "cbbd"} and sports_adapter:
        print(f"Fetching season leaders ({provider_name})…")
        leaders = fetch_college_leaders(sports_adapter, provider_name)
    elif COMP_KEY == "NFL":
        # Independent of NFL's schedule/score source (BALLDONTLIE): nflverse
        # is a separate, unauthenticated, public CC-BY-4.0 feed added purely
        # for player-stat leaders, so it applies regardless of which
        # provider is filling `matches` for this competition.
        print("Fetching season leaders (nflverse)…")
        leaders = fetch_nflverse_leaders()

    live = sum(1 for m in matches if m["status"] == "LIVE")
    source_note = "sample" if COMP.get("source") == "sportsdataio" else "live"
    fixture_count_check = _check_and_record_fixture_count(COMP_KEY, len(matches))
    payload = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "fixture_count_check": fixture_count_check,
               "source_note": source_note, "competition": COMP["label"], "comp_key": COMP_KEY, "matches": matches,
               "title_odds": title, "news": news, "news_scope": COMP_KEY, "bracket": bracket, "bracketology": bracketology,
               "third_race": third, "standings": standings, "scorers": scorers, "leaders": leaders, "team_of_tournament": build_team_of_tournament(matches, scorers, standings), "scorecard": scorecard,
               "advancement": compute_advancement(matches, st, name_map, code_map),
               "weekly_awards": weekly_awards,
               "markets_quota_out": MARKET_STATE["quota_out"],
               "quota_blocked_providers": list(provider_quota.BLOCKED_THIS_RUN),
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
