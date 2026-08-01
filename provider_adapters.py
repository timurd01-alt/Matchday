"""Licensed-provider adapters for Matchday.

The adapters deliberately return Matchday's existing JSON shapes.  Provider
payloads stay isolated here so changing vendors never requires a UI rewrite.
"""

from __future__ import annotations

import csv
import datetime as dt
import functools
import json
import math
import time
import urllib.parse
import urllib.request

from advanced_metrics import cfbd_advanced_team_profiles
import provider_quota


class ProviderError(RuntimeError):
    pass


def _get_json(url, headers=None, timeout=25, provider=None):
    """`provider`, when given, gates the call against provider_quota's ledger
    before it fires and records whatever quota header this response carried
    afterward -- see provider_quota.py for why. Callers that never pass it
    (tests, or a provider provider_quota doesn't know about) behave exactly
    as before."""
    if provider:
        try:
            provider_quota.check(provider)
        except provider_quota.QuotaExceededError as exc:
            # Surface as the same ProviderError every existing caller already
            # falls back gracefully on -- a pre-flight refusal should look
            # exactly like any other provider failure to code that never
            # needs to know the difference.
            provider_quota.record_block(provider)
            raise ProviderError(str(exc)) from exc
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Matchday/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            if provider:
                provider_quota.record_response(provider, response.headers)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if provider:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            provider_quota.record_response(provider, exc.headers, error_body)
        raise ProviderError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


def _get_csv_text(url, headers=None, timeout=25, provider=None):
    if provider:
        try:
            provider_quota.check(provider)
        except provider_quota.QuotaExceededError as exc:
            provider_quota.record_block(provider)
            raise ProviderError(str(exc)) from exc
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Matchday/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            if provider:
                provider_quota.record_response(provider, response.headers)
            return text
    except urllib.error.HTTPError as exc:
        if provider:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            provider_quota.record_response(provider, exc.headers, error_body)
        raise ProviderError(str(exc)) from exc
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


def _number(value, default=0):
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return default


# Strings a provider sends for a fixture slot it has no real club for -- an
# unmapped/exhibition game, or a bracket slot whose participant isn't decided
# yet. These are not team names: accepted as one, a placeholder becomes a
# franchise that accrues real win-loss records in the standings table and a
# real Elo rating trained on other teams' results (confirmed live: a single
# BALLDONTLIE MLB game with both sides named "Unknown" produced a 31st MLB
# "team" with a 1-1 record and an Elo entry with n=2). There is no honest way
# to recover which club was meant, so the game is dropped instead.
PLACEHOLDER_TEAM_NAMES = {
    "unknown", "unk", "tbd", "tba", "to be determined", "undecided",
    "n/a", "na", "none", "null",
}


def is_placeholder_team_name(name):
    """True when `name` is a provider placeholder rather than a real team."""
    return " ".join(str(name or "").strip().lower().split()) in PLACEHOLDER_TEAM_NAMES


def _ordinal_period(n):
    """'3rd inning' not '3 0:00' -- BALLDONTLIE's free tier doesn't expose a
    reliable live clock for these sports, so show the period number in the
    sport's own vocabulary instead of a clock that can't be trusted."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def normalized_score(home, away, finished=False):
    """Return Matchday's score contract, including a result only when final.

    Keeping this normalization at the provider boundary lets every downstream
    model learn from the same licensed game feed without calling another data
    source or guessing the state of an unfinished game.
    """
    home_score = _number(home, None)
    away_score = _number(away, None)
    score = {"home": home_score, "away": away_score}
    if finished and home_score is not None and away_score is not None:
        score["winner"] = "h" if home_score > away_score else "a" if away_score > home_score else "d"
    return score


def _iso_utc(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            # SportsDataIO league feeds document unqualified game times as ET.
            parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5)))
        return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return str(value)


def _current_season(code, today=None):
    today = today or dt.date.today()
    # Basketball and hockey seasons are identified by their starting year.
    if code in {"nba", "nhl", "cbb"} and today.month <= 6:
        return today.year - 1
    return today.year


SPORTSDATA_CODES = {
    "NFL": "nfl", "NCAAF": "cfb", "NCAAM": "cbb",
    "NBA": "nba", "MLB": "mlb", "NHL": "nhl",
}


# The generic first-letter algorithm below isn't just occasionally wrong, it
# collides: "Michigan State" and "Mississippi State" both reduce to "MS", and
# the initials for a lot of major "___ State" programs don't match how they're
# actually known (real usage is "MSU"/"OSU"/"PSU"/"FSU", not first-letters).
# Not a general solution -- a full curated table for 130+ FBS/360+ D1 hoops
# programs is its own project -- just the handful of nationally visible
# schools most likely to appear in Top 25s and marquee matchups, confirmed
# against how each program is actually abbreviated in real broadcasts/press.
_SHORT_CODE_OVERRIDES = {
    "michigan state": "MSU", "mississippi state": "MSST", "ohio state": "OSU",
    "penn state": "PSU", "florida state": "FSU", "oregon state": "ORST",
    "arizona state": "ASU", "iowa state": "ISU", "kansas state": "KSU",
    "oklahoma state": "OKST", "washington state": "WSU", "san diego state": "SDSU",
    "fresno state": "FRES", "boise state": "BSU", "colorado state": "CSU",
    "utah state": "USU", "new mexico state": "NMSU", "texas state": "TXST",
    "georgia state": "GAST", "app state": "APP", "appalachian state": "APP",
    "arkansas state": "ARST", "ball state": "BALL", "kent state": "KENT",
    "michigan tech": "MTU", "texas a&m": "TAMU", "texas tech": "TTU",
}


def _short_code(name):
    key = str(name or "").strip().lower()
    if key in _SHORT_CODE_OVERRIDES:
        return _SHORT_CODE_OVERRIDES[key]
    words = [word for word in str(name or "").replace("-", " ").split() if word]
    return "".join(word[0] for word in words[:4]).upper() or str(name or "")[:4].upper()


# ---- multi-season college form -----------------------------------------
# A college football season is only 12-13 games, and before Week 1 there is no
# sample at all -- so record and scoring margin, two of the model's main
# in-season signals, are either thin or entirely absent for the games people
# most want read. These helpers summarise several seasons of real results into
# one recency-weighted view. Weights are newest-first: the season in progress
# counts fully, the one before it a little over half, the one before that under
# a third, because roster turnover makes older seasons weaker evidence without
# making them worthless.
SEASON_RECENCY_WEIGHTS = (1.0, 0.55, 0.30)


def season_form_from_matches(matches):
    """Per-team wins/losses/ties and points for/against from finished games.

    Takes the *normalized* match shape every adapter's schedule() already
    returns, so one implementation serves both college providers despite their
    raw payloads differing.
    """
    agg = {}
    for match in matches or []:
        if match.get("status") != "FINISHED":
            continue
        score = match.get("score") or {}
        home_pts, away_pts = score.get("home"), score.get("away")
        if home_pts is None or away_pts is None:
            continue
        home_pts, away_pts = _number(home_pts, 0), _number(away_pts, 0)
        for side, opp_side, pf, pa in (("home", "away", home_pts, away_pts),
                                       ("away", "home", away_pts, home_pts)):
            name = ((match.get(side) or {}).get("name") or "").strip()
            if not name:
                continue
            rec = agg.setdefault(name, {"w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0, "games": 0})
            rec["w" if pf > pa else "l" if pa > pf else "t"] += 1
            rec["pf"] += pf
            rec["pa"] += pa
            rec["games"] += 1
    return agg


def blend_season_history(seasons):
    """Combine per-season aggregates into one recency-weighted view.

    `seasons` is an iterable of (year, aggregate) newest-first, where each
    aggregate is season_form_from_matches() output. Returns
    {team_lower: {multi_win_pct, multi_margin, multi_games, multi_seasons}}.

    Rates are weighted by weight x games, so a season a team barely played
    (or one still in its opening weeks) contributes proportionally rather than
    counting the same as a completed one.
    """
    blended = {}
    for index, (year, agg) in enumerate(seasons or []):
        weight = (SEASON_RECENCY_WEIGHTS[index] if index < len(SEASON_RECENCY_WEIGHTS)
                  else SEASON_RECENCY_WEIGHTS[-1] / (index - len(SEASON_RECENCY_WEIGHTS) + 2))
        for name, rec in (agg or {}).items():
            games = int(rec.get("games") or 0)
            if games < 1:
                continue
            slot = blended.setdefault(name.lower(), {
                "_name": name, "_wp_num": 0.0, "_mg_num": 0.0, "_den": 0.0,
                "multi_games": 0, "multi_seasons": [],
            })
            wins = float(rec.get("w") or 0) + 0.5 * float(rec.get("t") or 0)
            margin = (float(rec.get("pf") or 0) - float(rec.get("pa") or 0)) / games
            mass = weight * games
            slot["_wp_num"] += (wins / games) * mass
            slot["_mg_num"] += margin * mass
            slot["_den"] += mass
            slot["multi_games"] += games
            if year not in slot["multi_seasons"]:
                slot["multi_seasons"].append(year)
    out = {}
    for key, slot in blended.items():
        if slot["_den"] <= 0:
            continue
        out[key] = {
            "name": slot["_name"],
            "multi_win_pct": round(slot["_wp_num"] / slot["_den"], 5),
            "multi_margin": round(slot["_mg_num"] / slot["_den"], 4),
            "multi_games": slot["multi_games"],
            "multi_seasons": sorted(slot["multi_seasons"], reverse=True),
        }
    return out


class SportsDataIOAdapter:
    BASE = "https://api.sportsdata.io/v3"

    def __init__(self, api_key, competition, getter=None):
        if not api_key:
            raise ProviderError("missing SPORTSDATAIO_KEY")
        if competition not in SPORTSDATA_CODES:
            raise ProviderError(f"unsupported SportsDataIO competition: {competition}")
        self.key = api_key
        self.competition = competition
        self.code = SPORTSDATA_CODES[competition]
        self.getter = getter or _get_json
        self.season = _current_season(self.code)
        self._teams = None

    def _get(self, resource):
        return self._get_product("scores", resource)

    def _get_product(self, product, resource):
        url = f"{self.BASE}/{self.code}/{product}/json/{resource}"
        return self.getter(url, {"Ocp-Apim-Subscription-Key": self.key,
                                 "User-Agent": "Matchday/1.0"})

    def teams(self):
        if self._teams is not None:
            return self._teams
        rows = self._get("Teams")
        out = {}
        for row in rows if isinstance(rows, list) else []:
            code = row.get("Key") or row.get("Team") or row.get("Abbreviation")
            name = row.get("FullName") or row.get("Name") or row.get("School") or code
            if code:
                out[str(code)] = str(name)
        self._teams = out
        return out

    def schedule(self):
        resource = (f"Schedules/{self.season}" if self.code == "nfl"
                    else f"Games/{self.season}")
        rows = self._get(resource)
        team_names = self.teams()
        matches = [self._match(row, team_names) for row in rows if isinstance(row, dict)]
        matches = [match for match in matches if match]
        matches.sort(key=lambda match: match.get("kickoff") or "")
        return matches

    def _match(self, row, team_names):
        home_code = row.get("HomeTeam") or row.get("HomeTeamKey") or row.get("HomeTeamName")
        away_code = row.get("AwayTeam") or row.get("AwayTeamKey") or row.get("AwayTeamName")
        home_name = (row.get("HomeTeamName") or row.get("HomeTeamFullName") or
                     team_names.get(str(home_code), home_code))
        away_name = (row.get("AwayTeamName") or row.get("AwayTeamFullName") or
                     team_names.get(str(away_code), away_code))
        if not home_name or not away_name:
            return None
        raw_status = str(row.get("Status") or "Scheduled").lower()
        if raw_status in {"inprogress", "in progress", "halftime", "delayed", "suspended"}:
            status = "LIVE"
        elif raw_status in {"final", "f/ot", "f/so", "completed", "closed"}:
            status = "FINISHED"
        else:
            status = "UPCOMING"
        home_score = row.get("HomeScore", row.get("HomeTeamRuns"))
        away_score = row.get("AwayScore", row.get("AwayTeamRuns"))
        week = row.get("Week") or row.get("Round") or row.get("Day")
        clock = row.get("TimeRemaining") or row.get("TimeRemainingMinutes")
        period = row.get("Quarter") or row.get("Period") or row.get("Inning")
        minute = ""
        if status == "LIVE":
            minute = " ".join(str(x) for x in (period, clock) if x not in (None, ""))
        venue = (row.get("StadiumDetails") or {}).get("Name") if isinstance(row.get("StadiumDetails"), dict) else None
        venue = venue or row.get("StadiumName") or row.get("Venue") or ""
        game_id = row.get("GameID") or row.get("GlobalGameID") or row.get("ScoreID")
        return {
            "id": f"sdio-{self.code}-{game_id}",
            "provider_id": game_id,
            "stage": f"Week {week}" if week not in (None, "") and self.code in {"nfl", "cfb"} else str(row.get("SeasonTypeName") or ""),
            "venue": venue,
            "kickoff": _iso_utc(row.get("DateTimeUTC") or row.get("DateTime") or row.get("Day")),
            "status": status, "minute": minute or None,
            "score": normalized_score(home_score, away_score, status == "FINISHED"),
            "home": {"name": str(home_name), "code": str(home_code or ""), "pts": None, "gd": None,
                     "form": "", "pos": None, "group": None},
            "away": {"name": str(away_name), "code": str(away_code or ""), "pts": None, "gd": None,
                     "form": "", "pos": None, "group": None},
            "markets": {}, "lineups": None, "h2h": [],
            "injuries": {"home": [], "away": []}, "data_source": "SportsDataIO",
        }

    def standings(self):
        resource = (f"Standings/{self.season}" if self.code in {"nfl", "nba", "mlb", "nhl"}
                    else f"TeamSeasonStats/{self.season}")
        rows = self._get(resource)
        model, grouped = {}, {}
        for row in rows if isinstance(rows, list) else []:
            name = row.get("Name") or row.get("TeamName") or row.get("School") or row.get("Team")
            if not name:
                continue
            code = row.get("Team") or row.get("Key") or row.get("TeamKey") or ""
            conference = row.get("Conference") or row.get("ConferenceName") or "League"
            division = row.get("Division") or row.get("DivisionName") or ""
            group = " ".join(str(x) for x in (conference, division) if x).strip() or "League"
            wins = int(_number(row.get("Wins"), 0)); losses = int(_number(row.get("Losses"), 0))
            ties = int(_number(row.get("Ties"), 0)); played = wins + losses + ties
            pf = _number(row.get("PointsFor", row.get("RunsScored", row.get("GoalsFor"))), 0)
            pa = _number(row.get("PointsAgainst", row.get("RunsAgainst", row.get("GoalsAgainst"))), 0)
            avg_pf = _number(row.get("PointsPerGameFor", row.get("RunsPerGame", row.get("GoalsPerGame"))), 0)
            avg_pa = _number(row.get("PointsPerGameAgainst", row.get("OpponentRunsPerGame", row.get("OpponentGoalsPerGame"))), 0)
            if not avg_pf and played: avg_pf = pf / played
            if not avg_pa and played: avg_pa = pa / played
            win_pct = _number(row.get("Percentage", row.get("WinPercentage")), wins / max(1, played))
            if win_pct > 1: win_pct /= 100
            conf_w = int(_number(row.get("ConferenceWins"), wins))
            conf_l = int(_number(row.get("ConferenceLosses"), losses))
            conf_pct = conf_w / max(1, conf_w + conf_l)
            streak_n = int(_number(row.get("Streak"), 0))
            form = (("W " * min(5, streak_n)) if streak_n > 0 else ("L " * min(5, abs(streak_n)))).strip()
            diff = pf - pa
            gd_model = round(diff if abs(diff) <= 20 else diff / 10.0, 1)
            pts_model = round((wins * 3 + ties) * 14.0 / max(1, played), 1) if played else 0
            pos = int(_number(row.get("ConferenceRank", row.get("DivisionRank", row.get("Rank"))), 0)) or None
            item = {"name": str(name), "code": str(code), "pos": pos, "pld": played,
                    "w": wins, "d": ties, "l": losses, "gf": pf, "ga": pa, "gd": diff,
                    "pts": wins * 3 + ties, "form": form,
                    "record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
                    "win_pct": win_pct, "league_win_pct": conf_pct,
                    "avg_pf": round(avg_pf, 2), "avg_pa": round(avg_pa, 2), "qual": ""}
            grouped.setdefault(group, []).append(item)
            model[str(name).lower()] = {"group": group, "pld": played, "w": wins, "d": ties,
                "l": losses, "gf": pf, "ga": pa, "gd": gd_model, "pts": pts_model,
                "form": form, "pos": pos, "win_pct": win_pct, "league_win_pct": conf_pct,
                "avg_pf": avg_pf, "avg_pa": avg_pa}
        payload = []
        for group, teams in grouped.items():
            teams.sort(key=lambda x: (x["pos"] or 999, -x["pts"], -x["gd"]))
            for index, team in enumerate(teams, 1):
                team["pos"] = team["pos"] or index
            payload.append({"group": group, "teams": teams})
        return model, sorted(payload, key=lambda x: x["group"])

    def rankings(self, standings_payload):
        if self.competition not in {"NCAAF", "NCAAM"}:
            return [], None
        teams = [dict(team) for group in standings_payload for team in group.get("teams", [])]
        teams.sort(key=lambda x: (-float(x.get("win_pct") or 0), -float(x.get("gd") or 0), -(x.get("w") or 0)))
        ranks = [{"rank": i, "name": team["name"], "code": team.get("code") or "",
                  "record": team.get("record") or ""} for i, team in enumerate(teams[:25], 1)]
        return ranks, self._cfp_projection(ranks) if self.competition == "NCAAF" else None

    def attach_availability(self, matches):
        """Attach licensed injury/availability labels when the feed includes them."""
        resources = ["Injuries"]
        if self.code == "nfl":
            weeks = [int(match.get("stage", "").replace("Week ", "")) for match in matches
                     if str(match.get("stage") or "").startswith("Week ")
                     and str(match.get("stage") or "").replace("Week ", "").isdigit()]
            if weeks:
                resources = [f"Injuries/{self.season}/{max(weeks)}"]
        rows = self._get_product("stats", resources[0])
        by_team = {}
        for row in rows if isinstance(rows, list) else []:
            team = str(row.get("Team") or row.get("TeamKey") or "")
            name = row.get("Name") or row.get("PlayerName") or ""
            status = row.get("InjuryStatus") or row.get("Status") or "Unavailable"
            if team and name:
                by_team.setdefault(team.lower(), []).append(f"{name} ({status})")
        attached = 0
        for match in matches:
            for side in ("home", "away"):
                code = str((match.get(side) or {}).get("code") or "").lower()
                people = by_team.get(code) or []
                if people:
                    match.setdefault("injuries", {"home": [], "away": []})[side] = people[:12]
                    attached += len(people[:12])
        return attached

    def leaders(self):
        """Return sport-native season leaders from licensed player stats."""
        definitions = {
            "NFL": [("PassingYards", "Passing yards", False), ("PassingTouchdowns", "Passing TDs", False),
                    ("RushingYards", "Rushing yards", False), ("ReceivingYards", "Receiving yards", False)],
            "NCAAF": [("PassingYards", "Passing yards", False), ("PassingTouchdowns", "Passing TDs", False),
                      ("RushingYards", "Rushing yards", False), ("ReceivingYards", "Receiving yards", False)],
            "NBA": [("Points", "Points per game", True), ("Rebounds", "Rebounds per game", True),
                    ("Assists", "Assists per game", True), ("BlockedShots", "Blocks per game", True)],
            "NCAAM": [("Points", "Points per game", True), ("Rebounds", "Rebounds per game", True),
                      ("Assists", "Assists per game", True), ("BlockedShots", "Blocks per game", True)],
            "MLB": [("HomeRuns", "Home runs", False), ("BattingAverage", "Batting average", False),
                    ("RunsBattedIn", "Runs batted in", False), ("PitchingStrikeouts", "Strikeouts", False)],
            "NHL": [("Points", "Points", False), ("Goals", "Goals", False),
                    ("Assists", "Assists", False), ("GoaltendingSavePercentage", "Save percentage", False),
                    # offense/defense extras confirmed live on the same
                    # PlayerSeasonStats call, 2026-07-25 -- no new request.
                    ("PlusMinus", "Plus/minus", False), ("Hits", "Hits", False),
                    ("Takeaways", "Takeaways", False), ("ShotsOnGoal", "Shots on goal", False)],
        }
        wanted = definitions.get(self.competition) or []
        if not wanted:
            return {}
        rows = self._get_product("stats", f"PlayerSeasonStats/{self.season}")
        categories = []
        for field, label, per_game in wanted:
            ranked = []
            for row in rows if isinstance(rows, list) else []:
                value = _number(row.get(field), 0)
                games = max(1, int(_number(row.get("Games", row.get("GamesPlayed")), 1)))
                value = value / games if per_game else value
                name = row.get("Name") or row.get("PlayerName") or ""
                if name and value:
                    ranked.append((float(value), str(name)))
            ranked.sort(reverse=True)
            leaders = [{"name": name, "value": round(value, 1) if per_game else value}
                       for value, name in ranked[:3]]
            if leaders:
                categories.append({"key": field, "label": label, "abbr": "", "leaders": leaders})
        return {"season": self.season, "source": "SportsDataIO", "categories": categories} if categories else {}

    @staticmethod
    def _cfp_projection(ranks):
        if len(ranks) < 12:
            return None
        def match(a, b):
            return {"home": f"({a['rank']}) {a['name']}", "away": f"({b['rank']}) {b['name']}",
                    "score": {"home": None, "away": None}, "status": "UPCOMING", "kickoff": None}
        first = [match(ranks[4], ranks[11]), match(ranks[5], ranks[10]),
                 match(ranks[6], ranks[9]), match(ranks[7], ranks[8])]
        byes = [{"home": f"({team['rank']}) {team['name']}", "away": "First-round winner",
                 "score": {"home": None, "away": None}, "status": "UPCOMING", "kickoff": None}
                for team in ranks[:4]]
        return [{"round": "CFP First Round (model projection)", "matches": first},
                {"round": "CFP Quarter-finals (model projection)", "matches": byes}]


class CollegeFootballDataAdapter:
    BASE = "https://api.collegefootballdata.com"

    def __init__(self, api_key, getter=None, today=None):
        if not api_key:
            raise ProviderError("missing CFBD_KEY")
        self.key, self.getter = api_key, getter or functools.partial(_get_json, provider="cfbd")
        self.today = today or dt.date.today()
        self.season = self.today.year
        self._games = []
        self._cached_rankings = None

    def _get(self, path, params=None):
        url = self.BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.getter(url, {"Authorization": f"Bearer {self.key}", "User-Agent": "Matchday/1.0"})

    def schedule(self):
        rows = self._get("/games", {"year": self.season, "seasonType": "regular", "classification": "fbs"})
        self._games = rows if isinstance(rows, list) else []
        return self._matches_from_rows(self._games)

    def historical_matches(self, year):
        """One completed prior season, in the same normalized match shape.

        Feeds season_form_from_matches(). A finished season never changes, so
        callers are expected to cache the result rather than re-request it.
        """
        rows = self._get("/games", {"year": year, "seasonType": "regular", "classification": "fbs"})
        return self._matches_from_rows(rows if isinstance(rows, list) else [])

    def _matches_from_rows(self, rows):
        matches = []
        now = dt.datetime.now(dt.timezone.utc)
        for row in rows:
            home, away = row.get("homeTeam"), row.get("awayTeam")
            if not home or not away:
                continue
            kickoff = _iso_utc(row.get("startDate"))
            try:
                kickoff_dt = dt.datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            except Exception:
                kickoff_dt = now + dt.timedelta(days=1)
            if row.get("completed"):
                status = "FINISHED"
            elif kickoff_dt <= now and row.get("homePoints") is not None:
                status = "LIVE"
            else:
                status = "UPCOMING"
            matches.append({
                "id": f"cfbd-{row.get('id')}", "provider_id": row.get("id"),
                "stage": f"Week {row.get('week')}" if row.get("week") else str(row.get("seasonType") or "Regular Season").title(),
                "venue": row.get("venue") or "", "kickoff": kickoff, "status": status,
                "minute": "Live" if status == "LIVE" else None,
                "score": normalized_score(row.get("homePoints"), row.get("awayPoints"), status == "FINISHED"),
                "home": {"name": home, "code": _short_code(home), "pts": None, "gd": None, "form": "", "pos": None, "group": row.get("homeConference")},
                "away": {"name": away, "code": _short_code(away), "pts": None, "gd": None, "form": "", "pos": None, "group": row.get("awayConference")},
                "markets": {}, "lineups": None, "h2h": [], "injuries": {"home": [], "away": []},
                "data_source": "CollegeFootballData",
            })
        matches.sort(key=lambda match: match.get("kickoff") or "")
        return matches

    def standings(self):
        rows = self._get("/records", {"year": self.season, "classification": "fbs"})
        stale = False
        if not rows and self.season > 2000:
            rows = self._get("/records", {"year": self.season - 1, "classification": "fbs"})
            stale = True  # this is last season's final record, not a current-season sample
        scoring = {}
        for game in self._games:
            if not game.get("completed"):
                continue
            for team_key, opp_key, pts_key, opp_pts_key in (("homeTeam", "awayTeam", "homePoints", "awayPoints"), ("awayTeam", "homeTeam", "awayPoints", "homePoints")):
                name = game.get(team_key)
                if name:
                    rec = scoring.setdefault(name, [0, 0]);rec[0] += _number(game.get(pts_key), 0);rec[1] += _number(game.get(opp_pts_key), 0)
        model, grouped = {}, {}
        for row in rows if isinstance(rows, list) else []:
            name, group = row.get("team"), row.get("conference") or "FBS"
            total, conf = row.get("total") or {}, row.get("conferenceGames") or {}
            if not name or str(row.get("classification") or "fbs").lower() != "fbs":
                continue
            w, l, ties = int(total.get("wins") or 0), int(total.get("losses") or 0), int(total.get("ties") or 0)
            pld = int(total.get("games") or (w + l + ties)); pf, pa = scoring.get(name, [0, 0]); diff = pf - pa
            item = {"name": name, "code": _short_code(name), "pos": None, "pld": pld, "w": w, "d": ties, "l": l,
                    "gf": pf, "ga": pa, "gd": diff, "pts": w * 3 + ties, "form": "", "record": f"{w}-{l}" + (f"-{ties}" if ties else ""),
                    "win_pct": w / max(1, pld), "league_win_pct": int(conf.get("wins") or 0) / max(1, int(conf.get("games") or 0)), "qual": "",
                    "season_stale": stale}
            grouped.setdefault(group, []).append(item)
            model[name.lower()] = {**item, "group": group}
        tables = []
        for group, teams in grouped.items():
            teams.sort(key=lambda x: (-x["win_pct"], -x["gd"], x["name"]))
            for index, team in enumerate(teams, 1):
                team["pos"] = index
                # `model[name]` was snapshotted via {**item, ...} BEFORE this
                # sort ran, so it kept pos=None forever -- any caller reading
                # the model dict (fetch_data.py's generic groups-from-matches
                # builder does) got every team's real position back as None.
                model[team["name"].lower()]["pos"] = index
            tables.append({"group": group, "teams": teams})
        return model, sorted(tables, key=lambda x: x["group"])

    def rankings(self, standings_payload):
        if self._cached_rankings is not None:
            return self._cached_rankings
        # Real games actually played for the CURRENT tracked season is the
        # off-season signal, not "does a poll exist" -- a fallback to last
        # season's postseason poll always succeeds once that poll happened
        # (it's historical, immutable), which meant this kept showing an
        # already-finished season's final rankings for the entire off-season
        # ("no one cares" per the live user report 2026-07-26) instead of
        # ever preferring a real signal about the season that's actually
        # coming up. Zero completed games this season (checked before making
        # any /rankings call, using schedule()'s own self._games) means the
        # season hasn't started -- a real preseason poll may still exist
        # (checked first, below) and is always preferred when it does; only
        # when even that doesn't exist yet does this fall back to a
        # blended projection instead of presenting an old poll as though it
        # were the ranking for the season nobody has played yet.
        season_started = any(row.get("completed") for row in self._games)
        payload = self._get("/rankings", {"year": self.season, "seasonType": "regular"})
        def collect(rows):
            found = []
            for week in rows if isinstance(rows, list) else []:
                for poll in week.get("polls") or []:
                    priority = 0 if "playoff" in str(poll.get("poll") or "").lower() else 1 if "ap top" in str(poll.get("poll") or "").lower() else 2
                    found.append((int(week.get("season") or 0), int(week.get("week") or 0), -priority, poll))
            return found
        candidates = collect(payload)
        if not candidates and season_started and self.season > 2000:
            candidates = collect(self._get("/rankings", {"year": self.season - 1, "seasonType": "postseason"}))
        if candidates:
            poll = sorted(candidates, reverse=True, key=lambda x: x[:3])[0][3]
            ranks = [{"rank": int(row.get("rank") or 0), "name": row.get("school") or "", "code": _short_code(row.get("school")), "record": ""}
                     for row in (poll.get("ranks") or [])[:25] if row.get("school")]
        elif not season_started:
            ranks = self._projected_ranking()
        else:
            ranks = []
        is_real_poll = bool(ranks) and not ranks[0].get("projected")
        cfp = SportsDataIOAdapter._cfp_projection(ranks) if is_real_poll and len(ranks) >= 12 else None
        self._cached_rankings = (ranks, cfp)
        return self._cached_rankings

    def _projected_ranking(self):
        """Way-too-early Top 25 blending roster talent and recent results.

        The prior season's final poll is a performance input, not a poll being
        carried forward and relabeled.  Both inputs are converted to a 0..1
        rank score before blending (55% performance, 45% talent), so their
        unrelated native scales cannot dominate one another.  This gives
        proven teams meaningful carryover while roster quality still matters
        during an offseason with transfers, graduations, and coaching changes.

        Used only when the season hasn't started yet and no real poll (current or
        preseason) exists either -- a model-derived estimate, same honest
        posture as estimate_title_odds() in fetch_data.py, clearly marked
        `"projected": True` so callers can label it differently from a real
        poll rather than presenting it as one."""
        try:
            talent = self.talent()
        except ProviderError:
            talent = {}

        performance = {}
        if self.season > 2000:
            try:
                rows = self._get("/rankings", {"year": self.season - 1, "seasonType": "postseason"})
                polls = []
                for week in rows if isinstance(rows, list) else []:
                    for poll in week.get("polls") or []:
                        label = str(poll.get("poll") or "").lower()
                        priority = 0 if "playoff" in label else 1 if "ap top" in label else 2
                        polls.append((int(week.get("week") or 0), -priority, poll))
                if polls:
                    poll = max(polls, key=lambda item: item[:2])[2]
                    performance = {
                        row["school"]: int(row.get("rank") or 0)
                        for row in (poll.get("ranks") or [])
                        if row.get("school") and 1 <= int(row.get("rank") or 0) <= 25
                    }
            except (ProviderError, TypeError, ValueError):
                performance = {}

        if not talent and not performance:
            return []
        talent_ranked = sorted(talent, key=lambda name: (-talent[name], name))
        talent_count = len(talent_ranked)
        talent_score = {
            name: (talent_count - index) / max(1, talent_count - 1)
            for index, name in enumerate(talent_ranked)
        }
        scores = {}
        for name in set(talent) | set(performance):
            recent = (26 - performance[name]) / 25 if name in performance else 0.0
            scores[name] = 0.55 * recent + 0.45 * talent_score.get(name, 0.0)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
        return [{"rank": i, "name": name, "code": _short_code(name), "record": "Preseason", "projected": True}
                for i, (name, _score) in enumerate(ranked, 1)]

    def attach_availability(self, matches): return 0

    @staticmethod
    def _reshape_player_stats(rows, team_filter=None):
        """Turn CFBD's long category/statType/stat rows into one object per player.

        /stats/player/season returns a row per player per stat type (e.g.
        category="passing", statType="YDS", stat="3200") rather than a wide
        per-player table. Reshape it once here into {name, position, team,
        conference, stats: {category: {statType: value}}} so leaders() (and
        any future per-player consumer) doesn't have to re-derive this shape
        from raw rows.
        """
        players = {}
        for row in rows if isinstance(rows, list) else []:
            player_id, name, team = row.get("playerId"), row.get("player"), row.get("team")
            if not player_id or not name:
                continue
            if team_filter and team not in team_filter:
                continue
            entry = players.setdefault(player_id, {
                "player_id": player_id, "name": name, "position": row.get("position") or "",
                "team": team or "", "conference": row.get("conference") or "", "stats": {},
            })
            category, stat_type = str(row.get("category") or "").lower(), str(row.get("statType") or "")
            if category and stat_type:
                entry["stats"].setdefault(category, {})[stat_type] = _number(row.get("stat"), 0)
        return players

    def leaders(self):
        """Season leaders from CFBD's licensed per-player stat feed.

        `team` is optional on /stats/player/season (year is the only
        required filter), so this pulls the whole field in a single request
        rather than looping per team -- one call, the same request-count
        footprint as talent(), just a much larger payload (the response
        covers FBS *and* lower-division programs, so it needs its own
        classification filter -- see below). A second, much smaller
        /records call recovers the FBS team list so leaders stay restricted
        to FBS players, mirroring the classification filter standings()
        already applies. fetch_college_bundle's caller in fetch_data.py
        gives this result its own disk cache so the large pull doesn't
        happen on every build() run.
        """
        definitions = [
            ("passing", "YDS", "PassingYards", "Passing yards"),
            ("passing", "TD", "PassingTouchdowns", "Passing TDs"),
            ("rushing", "YDS", "RushingYards", "Rushing yards"),
            ("receiving", "YDS", "ReceivingYards", "Receiving yards"),
            # /stats/player/season's unfiltered pull already includes a
            # "defensive" category (confirmed live 2026-07-25: 60k+ rows for
            # the 2025 season, same request as the offensive categories
            # above) -- no second call needed for defensive leaders.
            ("defensive", "TOT", "Tackles", "Tackles"),
            ("defensive", "SACKS", "Sacks", "Sacks"),
            ("defensive", "TFL", "TacklesForLoss", "Tackles for loss"),
            ("defensive", "PD", "PassesDefended", "Passes defended"),
        ]
        records = self._get("/records", {"year": self.season, "classification": "fbs"})
        fbs_teams = ({row.get("team") for row in records
                      if isinstance(row, dict) and str(row.get("classification") or "").lower() == "fbs"}
                     if isinstance(records, list) else set())
        rows = self._get("/stats/player/season", {"year": self.season})
        players = self._reshape_player_stats(rows, fbs_teams)
        categories = []
        for category, stat_type, field_key, label in definitions:
            ranked = sorted(
                ((player["stats"].get(category, {}).get(stat_type), player["name"])
                 for player in players.values()
                 if player["stats"].get(category, {}).get(stat_type)),
                reverse=True)
            leaders = [{"name": name, "value": value} for value, name in ranked[:3]]
            if leaders:
                categories.append({"key": field_key, "label": label, "abbr": "", "leaders": leaders})
        return {"season": self.season, "source": "CollegeFootballData", "categories": categories} if categories else {}

    def talent(self, seasons_back=3):
        """247Sports Team Talent Composite, averaged across the last few
        seasons that actually have data, not just the most recent one.

        Confirmed live 2026-07-26: `/talent?year=2026` returns zero rows this
        far ahead of the season (the composite isn't published yet), and a
        single-season read is noisy in general -- a program's roster quality
        is more honestly read as a multi-year level than one snapshot, and
        this also naturally subsumes the old single-year fallback (skip
        years with no data, keep walking back) instead of only trying
        exactly one prior year.

        `seasons_back`: how many YEARS WITH REAL DATA to average (not how
        many years back to search) -- an unpublished current season is
        skipped entirely rather than counted as a thin/empty data point.
        """
        sums, counts = {}, {}
        years_with_data = 0
        year = self.season
        while years_with_data < seasons_back and year > 2000:
            rows = self._get("/talent", {"year": year})
            found = False
            for row in rows if isinstance(rows, list) else []:
                name, score = row.get("team"), row.get("talent")
                if name and score:
                    sums[name] = sums.get(name, 0.0) + float(score)
                    counts[name] = counts.get(name, 0) + 1
                    found = True
            if found:
                years_with_data += 1
            year -= 1
        return {name: sums[name] / counts[name] for name in sums}

    def advanced_team_metrics(self):
        """Licensed CFBD opponent/context-aware season metrics in one call.

        This intentionally uses `/stats/season/advanced`, not a named third-
        party rating. The returned values are shadow research inputs and do
        not alter the production prediction weights.
        """
        rows = self._get("/stats/season/advanced", {
            "year": self.season,
            "excludeGarbageTime": "true",
        })
        return {
            "season": self.season,
            "source": "CollegeFootballData /stats/season/advanced",
            "profiles": cfbd_advanced_team_profiles(rows if isinstance(rows, list) else []),
        }


class CollegeBasketballDataAdapter:
    BASE = "https://api.collegebasketballdata.com"

    def __init__(self, api_key, getter=None, today=None):
        if not api_key:
            raise ProviderError("missing CBBD_KEY")
        self.key, self.getter = api_key, getter or functools.partial(_get_json, provider="cbbd")
        self.today = today or dt.date.today()
        # CBBD numbers a season by its ENDING year (confirmed live 2026-07-26:
        # season=2026 held the real Oct 2025-Apr 2026 schedule/polls) -- unlike
        # _current_season()'s starting-year convention used elsewhere. New
        # seasons start being published under the next ending year from
        # around August, well before games tip off in November.
        self.season = self.today.year if self.today.month < 8 else self.today.year + 1
        self._games = []
        self._d1_teams = set()
        self._cached_rankings = None

    def _get(self, path, params=None):
        url = self.BASE + path
        if params: url += "?" + urllib.parse.urlencode(params)
        return self.getter(url, {"Authorization": f"Bearer {self.key}", "User-Agent": "Matchday/1.0"})

    def _season_rows(self, season):
        # The endpoint deliberately caps responses at 3,000 rows. Four bounded
        # season windows retrieve the complete Division I schedule without loss.
        windows = ((f"{season - 1}-10-01T00:00:00Z", f"{season - 1}-12-01T00:00:00Z"),
                   (f"{season - 1}-12-01T00:00:00Z", f"{season}-02-01T00:00:00Z"),
                   (f"{season}-02-01T00:00:00Z", f"{season}-04-01T00:00:00Z"),
                   (f"{season}-04-01T00:00:00Z", f"{season}-05-16T00:00:00Z"))
        by_id = {}
        for start, end in windows:
            chunk = self._get("/games", {"season": season, "startDateRange": start, "endDateRange": end})
            for row in chunk if isinstance(chunk, list) else []:
                by_id[str(row.get("id"))] = row
        rows = list(by_id.values())
        return [row for row in rows
                if row.get("homeTeam") in self._d1_teams or row.get("awayTeam") in self._d1_teams]

    def schedule(self):
        team_rows = self._get("/teams")
        self._d1_teams = {str(row.get("school")) for row in team_rows if row.get("school") and row.get("conference")}
        self._games = self._season_rows(self.season)
        return self._matches_from_rows(self._games)

    def historical_matches(self, year):
        """One completed prior season, in the same normalized match shape.

        Costs four windowed requests per season (see _season_rows), so callers
        must cache this -- a finished season never changes.
        """
        if not getattr(self, "_d1_teams", None):
            team_rows = self._get("/teams")
            self._d1_teams = {str(row.get("school")) for row in team_rows if row.get("school") and row.get("conference")}
        return self._matches_from_rows(self._season_rows(year))

    def _matches_from_rows(self, rows):
        matches = []
        for row in rows:
            home, away = row.get("homeTeam"), row.get("awayTeam")
            if not home or not away: continue
            raw = str(row.get("status") or "").lower()
            status = "FINISHED" if raw == "final" else "LIVE" if raw in {"in_progress", "live", "halftime"} else "UPCOMING"
            matches.append({"id": f"cbbd-{row.get('id')}", "provider_id": row.get("id"), "stage": str(row.get("seasonType") or "Regular Season").replace("_", " ").title(),
                "venue": row.get("venue") or "", "kickoff": _iso_utc(row.get("startDate")), "status": status, "minute": raw if status == "LIVE" else None,
                "score": normalized_score(row.get("homePoints"), row.get("awayPoints"), status == "FINISHED"),
                "home": {"name": home, "code": _short_code(home), "pts": None, "gd": None, "form": "", "pos": None, "group": row.get("homeConference")},
                "away": {"name": away, "code": _short_code(away), "pts": None, "gd": None, "form": "", "pos": None, "group": row.get("awayConference")},
                "markets": {}, "lineups": None, "h2h": [], "injuries": {"home": [], "away": []}, "data_source": "CollegeBasketballData"})
        matches.sort(key=lambda match: match.get("kickoff") or "")
        return matches

    def standings(self):
        records = {}
        for game in self._games:
            if str(game.get("status") or "").lower() != "final": continue
            hp, ap = _number(game.get("homePoints"), 0), _number(game.get("awayPoints"), 0)
            for name, group, pf, pa in ((game.get("homeTeam"), game.get("homeConference"), hp, ap), (game.get("awayTeam"), game.get("awayConference"), ap, hp)):
                if not name or name not in self._d1_teams: continue
                rec = records.setdefault(name, {"group": group or "Division I", "w": 0, "l": 0, "pf": 0, "pa": 0})
                rec["w" if pf > pa else "l"] += 1;rec["pf"] += pf;rec["pa"] += pa
        model, grouped = {}, {}
        for name, rec in records.items():
            pld = rec["w"] + rec["l"]; diff = rec["pf"] - rec["pa"]
            item = {"name": name, "code": _short_code(name), "pos": None, "pld": pld, "w": rec["w"], "d": 0, "l": rec["l"],
                    "gf": rec["pf"], "ga": rec["pa"], "gd": diff, "pts": rec["w"] * 3, "form": "", "record": f"{rec['w']}-{rec['l']}",
                    "win_pct": rec["w"] / max(1, pld), "league_win_pct": rec["w"] / max(1, pld), "qual": ""}
            grouped.setdefault(rec["group"], []).append(item);model[name.lower()] = {**item, "group": rec["group"]}
        tables=[]
        for group, teams in grouped.items():
            teams.sort(key=lambda x:(-x["win_pct"],-x["gd"],x["name"]));
            for i, team in enumerate(teams,1):
                team["pos"]=i
                # model[name] was snapshotted via {**item,...} before this sort
                # ran, so it kept pos=None forever -- see the identical fix and
                # comment in CollegeFootballDataAdapter.standings().
                model[team["name"].lower()]["pos"]=i
            tables.append({"group":group,"teams":teams})
        return model, sorted(tables,key=lambda x:x["group"])

    def rankings(self, standings_payload):
        """Real AP Top 25 / Coaches Poll from CBBD's own /rankings endpoint.

        This used to sort every D1 team by raw win percentage, with no
        strength-of-schedule or conference-quality adjustment -- a small
        mid-major that runs up a gaudy record against weak competition (e.g.
        32-2 in the MAC) would outrank blue bloods that go through brutal
        high-major schedules. CBBD publishes the real weekly polls (confirmed
        live 2026-07-26, same shape CFBD uses for NCAAF's real CFP/AP
        rankings) -- use those instead, same as NCAAF already does.
        """
        if self._cached_rankings is not None:
            return self._cached_rankings
        # Same off-season fix as CFBD's rankings(): falling back to last
        # season's poll always succeeds once that poll happened (it's
        # historical), which meant this kept showing an already-finished
        # season's final ranking for the entire off-season instead of ever
        # preferring the upcoming season. Zero "final" games this season
        # means it hasn't started -- prefer a blended projection over
        # presenting last season's poll as the upcoming season's ranking.
        season_started = any(str(row.get("status") or "").lower() == "final" for row in self._games)
        def collect(season):
            rows = self._get("/rankings", {"season": season, "seasonType": "regular"})
            found = []
            for row in rows if isinstance(rows, list) else []:
                if row.get("ranking") is None or not row.get("team"):
                    continue
                poll = str(row.get("pollType") or "").lower()
                priority = 0 if "ap top" in poll else 1 if "coaches" in poll else 2
                found.append((int(row.get("week") or 0), -priority, row))
            return found
        candidates = collect(self.season)
        if not candidates and season_started and self.season > 2000:
            candidates = collect(self.season - 1)
        if candidates:
            top_week, top_priority = max((w, p) for w, p, _ in candidates)
            rows = [row for w, p, row in candidates if w == top_week and p == top_priority]
            rows.sort(key=lambda r: r["ranking"])
            ranks = [{"rank": row["ranking"], "name": row["team"], "code": _short_code(row["team"]), "record": ""}
                     for row in rows[:25]]
        elif not season_started:
            ranks = self._projected_ranking()
        else:
            ranks = []
        self._cached_rankings = (ranks, None)
        return self._cached_rankings

    def _projected_ranking(self):
        """Way-too-early Top 25 blending recruiting and recent results.

        The prior season's final poll is normalized as a performance input,
        not carried forward as the new season's poll.  A 55% performance / 45%
        recruiting blend lets proven teams survive roster-projection blind
        spots while still accounting for offseason turnover.  The result is
        clearly marked `"projected": True` and either signal can stand alone
        when the other feed is unavailable.
        """
        try:
            recruiting = self.recruiting()
        except ProviderError:
            recruiting = {}

        performance = {}
        if self.season > 2000:
            try:
                rows = self._get("/rankings", {"season": self.season - 1, "seasonType": "postseason"})
                candidates = []
                for row in rows if isinstance(rows, list) else []:
                    rank, name = row.get("ranking"), row.get("team")
                    if rank is None or not name:
                        continue
                    poll = str(row.get("pollType") or "").lower()
                    priority = 0 if "ap top" in poll else 1 if "coaches" in poll else 2
                    candidates.append((int(row.get("week") or 0), -priority, row))
                if candidates:
                    top_week, top_priority = max((week, priority) for week, priority, _ in candidates)
                    performance = {
                        row["team"]: int(row["ranking"])
                        for week, priority, row in candidates
                        if week == top_week and priority == top_priority
                        and 1 <= int(row["ranking"]) <= 25
                    }
            except (ProviderError, TypeError, ValueError):
                performance = {}

        if not recruiting and not performance:
            return []
        recruiting_ranked = sorted(recruiting, key=lambda name: (-recruiting[name], name))
        recruiting_count = len(recruiting_ranked)
        recruiting_score = {
            name: (recruiting_count - index) / max(1, recruiting_count - 1)
            for index, name in enumerate(recruiting_ranked)
        }
        scores = {}
        for name in set(recruiting) | set(performance):
            recent = (26 - performance[name]) / 25 if name in performance else 0.0
            scores[name] = 0.55 * recent + 0.45 * recruiting_score.get(name, 0.0)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
        return [{"rank": i, "name": name, "code": _short_code(name), "record": "Preseason", "projected": True}
                for i, (name, _score) in enumerate(ranked, 1)]

    def attach_availability(self, matches): return 0

    def leaders(self):
        """Season leaders from CBBD's licensed per-player stat feed.

        Unlike CFBD, CBBD's /stats/player/season is already one row per
        player -- a wide format with pre-computed advanced metrics -- so no
        long-format reshape is needed here, just per-game rate stats and
        top-3 ranking. `team` is optional (season is the only required
        filter), so this pulls the whole field in a single request rather
        than looping per team -- the same request-count footprint as
        recruiting(). A second, much smaller /teams call recovers the
        Division I team list so leaders stay restricted to D1 players,
        mirroring schedule()'s own filter. fetch_college_bundle's caller in
        fetch_data.py gives this result its own disk cache so the large
        pull doesn't happen on every build() run.
        """
        definitions = [
            ("points", "PointsPerGame", "Points per game"),
            ("rebounds", "ReboundsPerGame", "Rebounds per game"),
            ("assists", "AssistsPerGame", "Assists per game"),
            ("blocks", "BlocksPerGame", "Blocks per game"),
            # steals/turnovers are flat numeric fields on the same row
            # (confirmed live 2026-07-25, unlike rebounds' nested {"total":...}
            # shape) -- same call, no new request.
            ("steals", "StealsPerGame", "Steals per game"),
            ("turnovers", "TurnoversPerGame", "Turnovers per game"),
        ]
        team_rows = self._get("/teams")
        d1_teams = ({str(row.get("school")) for row in team_rows
                     if isinstance(row, dict) and row.get("school") and row.get("conference")}
                    if isinstance(team_rows, list) else set())
        rows = self._get("/stats/player/season", {"season": self.season})
        ranked_by_field = {field: [] for field, _, _ in definitions}
        for row in rows if isinstance(rows, list) else []:
            name, team = row.get("name"), row.get("team")
            if not name or (d1_teams and team not in d1_teams):
                continue
            games = max(1, int(_number(row.get("games"), 1)))
            totals = {
                "points": _number(row.get("points"), 0),
                "rebounds": _number((row.get("rebounds") or {}).get("total"), 0),
                "assists": _number(row.get("assists"), 0),
                "blocks": _number(row.get("blocks"), 0),
                "steals": _number(row.get("steals"), 0),
                "turnovers": _number(row.get("turnovers"), 0),
            }
            for field in ranked_by_field:
                total = totals.get(field, 0)
                if total:
                    ranked_by_field[field].append((total / games, name))
        categories = []
        for field, key, label in definitions:
            ranked = sorted(ranked_by_field.get(field, []), reverse=True)
            leaders = [{"name": name, "value": round(value, 1)} for value, name in ranked[:3]]
            if leaders:
                categories.append({"key": key, "label": label, "abbr": "", "leaders": leaders})
        return {"season": self.season, "source": "CollegeBasketballData", "categories": categories} if categories else {}

    def recruiting(self):
        """Recruiting class rating, for roster-quality coverage across the
        Division I field -- not just the teams with March Madness futures
        odds. Same account/key as the rest of this adapter."""
        rows = self._get("/recruiting/teams", {"year": self.season})
        out = {}
        for row in rows if isinstance(rows, list) else []:
            name, score = row.get("team"), row.get("rating")
            if name and score:
                out[str(name)] = float(score)
        if not out and self.season > 2000:
            rows = self._get("/recruiting/teams", {"year": self.season - 1})
            for row in rows if isinstance(rows, list) else []:
                name, score = row.get("team"), row.get("rating")
                if name and score:
                    out[str(name)] = float(score)
        return out


class NflverseAdapter:
    """Season player-stat leaders from nflverse-data's "Player Summary Stats"
    release (release tag `stats_player`, one CSV per season/season-type,
    built with R's `nflfastR::calculate_stats()` from play-by-play data).

    Licensing: the nflverse-data repository is CC BY 4.0
    (https://github.com/nflverse/nflverse-data, confirmed against the repo's
    actual LICENSE file via the GitHub API on 2026-07-25, SPDX `CC-BY-4.0`)
    -- attribution is required, see the nflverse credit on `legal.html`.

    ESPN exclusion: nflverse-data also publishes a *separate* release, tag
    `espn_data` ("ESPN Stats" -- ESPN Total QBR, `qbr_season_level.csv` /
    `qbr_week_level.csv`). That is a different release with different asset
    names; this adapter's `RELEASE_BASE` is pinned to `stats_player` only and
    never touches `espn_data`. `stats_player`'s own columns were checked for
    ESPN provenance (no ESPN-named column, no "espn" substring found in any
    2025-season row) -- it is nflfastR-derived, not ESPN-sourced. Matchday's
    standing rule bars ESPN-originated data through any path (see
    PROVIDER_COMPLIANCE.md's "Launch rules"); do not repoint `RELEASE_BASE`
    at `espn_data`, and re-verify this note if nflverse ever restructures
    `stats_player` to blend in another provider's columns.
    """
    RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player"

    def __init__(self, getter=None, today=None):
        self.getter = getter or _get_csv_text
        self.today = today or dt.date.today()
        # NFL season labeling: the season that kicks off in September of
        # year Y runs into February of Y+1, so from January through August
        # the "current" (most recently completed or in-progress) season is
        # still Y-1 -- e.g. in July, the prior September's season is still
        # the one with real data; the new season's file doesn't exist yet.
        self.season = self.today.year if self.today.month >= 9 else self.today.year - 1

    def _rows(self, season):
        url = f"{self.RELEASE_BASE}/stats_player_reg_{season}.csv"
        text = self.getter(url, {"User-Agent": "Matchday/1.0"})
        return list(csv.DictReader((text or "").splitlines()))

    def leaders(self):
        """Top-3-per-category season leaders, mirroring CFBD/CBBD's shape.

        Rows with a blank `player_id` are team-level aggregate artifacts
        (e.g. a season-total penalties row with no player attached, seen in
        a live 2025 pull) rather than real players, and are dropped before
        ranking. nflverse's `stats_player_reg_<season>.csv` already carries
        one row per player for the season (no per-team split rows for
        players traded mid-season), so no further de-duplication is needed.
        """
        definitions = [
            ("passing_yards", "PassingYards", "Passing yards"),
            ("passing_tds", "PassingTouchdowns", "Passing TDs"),
            ("rushing_yards", "RushingYards", "Rushing yards"),
            ("rushing_tds", "RushingTouchdowns", "Rushing TDs"),
            ("receiving_yards", "ReceivingYards", "Receiving yards"),
            ("receiving_tds", "ReceivingTouchdowns", "Receiving TDs"),
            # defensive columns confirmed live on the same CSV, 2026-07-25 --
            # no second release/request needed for defensive leaders.
            ("def_sacks", "Sacks", "Sacks"),
            ("def_interceptions", "Interceptions", "Interceptions"),
            ("def_tackles_solo", "SoloTackles", "Solo tackles"),
            ("def_tackles_for_loss", "TacklesForLoss", "Tackles for loss"),
            ("def_qb_hits", "QBHits", "QB hits"),
        ]
        rows = self._rows(self.season)
        players = [row for row in rows if (row.get("player_id") or "").strip()
                   and (row.get("player_display_name") or "").strip()]
        categories = []
        for field, key, label in definitions:
            ranked = sorted(
                ((_number(row.get(field), 0), row["player_display_name"])
                 for row in players if _number(row.get(field), 0)),
                reverse=True)
            leaders = [{"name": name, "value": value} for value, name in ranked[:3]]
            if leaders:
                categories.append({"key": key, "label": label, "abbr": "", "leaders": leaders})
        return {"season": self.season, "source": "nflverse (CC BY 4.0)", "categories": categories} if categories else {}


class BallDontLieAdapter:
    """Free-tier adapter for real NBA, NFL and MLB schedules/scores.

    BALLDONTLIE's free plan exposes games but not standings or player-stat
    endpoints.  Those unsupported sections intentionally return empty values
    instead of being filled with trial or inferred data.
    """

    BASE = "https://api.balldontlie.io"
    CODES = {"NBA": "nba", "NFL": "nfl", "MLB": "mlb"}
    # Rough regular-season start per sport, used only to bound season_games()'s
    # date range. A day or two off just means a few preseason/spring-training
    # rows get pulled in — schedule() filters those out by stage.
    SEASON_START = {"NFL": (9, 1), "NBA": (10, 1), "MLB": (3, 20)}
    # Keep season_games()'s pagination well under the free tier's 5 req/min
    # limit -- this client has no automatic retry/backoff, and this call is
    # cached for hours (see fetch_balldontlie_bundle), so pacing it slowly
    # costs nothing in practice.
    SEASON_PAGE_DELAY_SEC = 13

    def __init__(self, api_key, competition, getter=None, today=None):
        if not api_key:
            raise ProviderError("missing BALLDONTLIE_KEY")
        if competition not in self.CODES:
            raise ProviderError(f"unsupported BALLDONTLIE competition: {competition}")
        self.key = api_key
        self.competition = competition
        self.code = self.CODES[competition]
        self.getter = getter or functools.partial(_get_json, provider="balldontlie")
        self.today = today or dt.date.today()
        self.season = _current_season(self.code, self.today)

    def _get(self, path, params=None):
        pairs = []
        for key, value in (params or {}).items():
            if isinstance(value, (list, tuple)):
                pairs.extend((key, item) for item in value)
            elif value is not None:
                pairs.append((key, value))
        url = f"{self.BASE}{path}"
        if pairs:
            url += "?" + urllib.parse.urlencode(pairs)
        return self.getter(url, {"Authorization": self.key, "User-Agent": "Matchday/1.0"})

    def schedule(self):
        # A bounded date window keeps the free 5 req/min tier useful.  NFL and
        # NBA need a longer horizon during their off-seasons; MLB plays daily.
        back = 7
        forward = {"NFL": 150, "NBA": 130, "MLB": 14}[self.competition]
        dates = [(self.today + dt.timedelta(days=offset)).isoformat()
                 for offset in range(-back, forward + 1)]
        rows, cursor = [], None
        for _ in range(4):
            params = {"dates[]": dates, "per_page": 100, "cursor": cursor}
            payload = self._get(f"/{self.code}/v1/games", params)
            page = payload.get("data") if isinstance(payload, dict) else []
            rows.extend(page or [])
            cursor = (payload.get("meta") or {}).get("next_cursor") if isinstance(payload, dict) else None
            if not cursor:
                break
        matches = [self._match(row) for row in rows if isinstance(row, dict)]
        matches = [match for match in matches if match]
        matches.sort(key=lambda match: match.get("kickoff") or "")
        return matches

    def season_games(self, max_pages=20):
        """Season-to-date finished games, for standings/SRS/Elo training.

        schedule()'s narrow date window is sized for keeping the free tier's
        *display* list fresh; the free plan has no standings endpoint (see
        class docstring), so recovering real win-loss records means paging
        back through the whole season here instead of the last ~week.

        A page failure always raises (after one backed-off retry) rather than
        returning whatever pages happened to load so far -- the caller caches
        this result for hours, so silently accepting a partial season would
        mean standings/SRS look confidently "established" while actually
        being truncated to whatever loaded before a rate limit hit. Raising
        lets the caller's existing stale-cache/narrow-window fallback take
        over instead, which is honest about being incomplete.
        """
        month, day = self.SEASON_START.get(self.competition, (1, 1))
        start = dt.date(self.season, month, day)
        if start > self.today:
            start = dt.date(self.season - 1, month, day)
        dates = [(start + dt.timedelta(days=offset)).isoformat()
                 for offset in range(0, max(0, (self.today - start).days) + 1)]
        rows, cursor = [], None
        for page in range(max_pages):
            if page:
                time.sleep(self.SEASON_PAGE_DELAY_SEC)
            params = {"dates[]": dates, "per_page": 100, "cursor": cursor}
            payload = None
            for attempt in range(2):
                try:
                    payload = self._get(f"/{self.code}/v1/games", params)
                    break
                except ProviderError as exc:
                    last_exc = exc
                    if attempt == 0:
                        time.sleep(self.SEASON_PAGE_DELAY_SEC * 3)
            if payload is None:
                raise ProviderError(f"season_games: page {page} failed after retry: {last_exc}")
            page_rows = payload.get("data") if isinstance(payload, dict) else []
            rows.extend(page_rows or [])
            cursor = (payload.get("meta") or {}).get("next_cursor") if isinstance(payload, dict) else None
            if not cursor:
                break
        matches = [self._match(row) for row in rows if isinstance(row, dict)]
        matches = [match for match in matches
                   if match and not any(tag in (match.get("stage") or "").lower()
                                         for tag in ("preseason", "spring"))]
        matches.sort(key=lambda match: match.get("kickoff") or "")
        return matches

    def historical_season(self, year, max_pages=20):
        """A full PAST completed season, for the one-time historical Elo
        backfill (backfill_history.py) -- distinct from season_games()'s
        date-windowed, current-season-only pull. Uses the `seasons[]` filter
        directly rather than a date range, since a past season's real start/
        end dates aren't worth re-deriving when the API already supports
        filtering by season number.

        Same retry-once-then-raise contract as season_games(): a page
        failure never silently caches a truncated season, since the caller
        folds this straight into Elo and a partial season would train on an
        incomplete, wrongly-ordered slice of real history.
        """
        rows, cursor = [], None
        for page in range(max_pages):
            if page:
                time.sleep(self.SEASON_PAGE_DELAY_SEC)
            params = {"seasons[]": str(year), "per_page": 100, "cursor": cursor}
            payload = None
            for attempt in range(2):
                try:
                    payload = self._get(f"/{self.code}/v1/games", params)
                    break
                except ProviderError as exc:
                    last_exc = exc
                    if attempt == 0:
                        time.sleep(self.SEASON_PAGE_DELAY_SEC * 3)
            if payload is None:
                raise ProviderError(f"historical_season({year}): page {page} failed after retry: {last_exc}")
            page_rows = payload.get("data") if isinstance(payload, dict) else []
            rows.extend(page_rows or [])
            cursor = (payload.get("meta") or {}).get("next_cursor") if isinstance(payload, dict) else None
            if not cursor:
                break
        matches = [self._match(row) for row in rows if isinstance(row, dict)]
        matches = [match for match in matches
                   if match and not any(tag in (match.get("stage") or "").lower()
                                         for tag in ("preseason", "spring"))]
        matches.sort(key=lambda match: match.get("kickoff") or "")
        return matches

    @staticmethod
    def _team(row, side):
        team = row.get(side) if isinstance(row.get(side), dict) else {}
        name = (team.get("full_name") or team.get("display_name") or
                row.get(f"{side}_name") or team.get("name"))
        # A placeholder is no more usable than a missing name -- blank it so
        # _match()'s existing empty-name check drops the game (see
        # PLACEHOLDER_TEAM_NAMES).
        if is_placeholder_team_name(name):
            name = ""
        return {
            "name": str(name or ""),
            "code": str(team.get("abbreviation") or ""),
            "pts": None, "gd": None, "form": "", "pos": None, "group": None,
        }

    def _match(self, row):
        away_key = "visitor_team" if self.competition in {"NBA", "NFL"} else "away_team"
        home, away = self._team(row, "home_team"), self._team(row, away_key)
        if not home["name"] or not away["name"]:
            return None
        raw_status = str(row.get("status") or "").strip()
        status_key = raw_status.lower().replace("_", " ")
        # A postponed/cancelled/suspended game will never produce a real
        # score or a further status change from the provider -- treated as
        # "UPCOMING" (the prior fallback), it lingered forever past its
        # kickoff instead of resolving, and its kickoff timestamp being in
        # the past made it fall straight to _lock_decision()'s
        # "past_due_upcoming" quarantine without ever getting a chance to
        # lock or grade. Map it to FINISHED (a status every caller already
        # understands) but force a null score below so update_scorecard()'s
        # "score is None -> skip grading" check keeps it from being graded
        # as a fabricated 0-0 result.
        not_played = any(token in status_key for token in ("postponed", "cancelled", "canceled", "suspended"))
        if not_played:
            status = "FINISHED"
        elif "final" in status_key or status_key in {"completed", "closed", "post"}:
            status = "FINISHED"
        elif any(token in status_key for token in ("progress", "quarter", "inning", "halftime", "live")):
            status = "LIVE"
        else:
            status = "UPCOMING"
        period_word = {"MLB": "inning", "NBA": "quarter", "NFL": "quarter"}.get(self.competition, "period")
        period_label = _ordinal_period(row.get("period"))
        minute = f"{period_label} {period_word}" if status == "LIVE" and period_label else ""
        if self.competition == "MLB":
            home_score = None if not_played else (row.get("home_team_data") or {}).get("runs")
            away_score = None if not_played else (row.get("away_team_data") or {}).get("runs")
        else:
            home_score = None if not_played else row.get("home_team_score")
            away_score = None if not_played else row.get("visitor_team_score")
        if self.competition == "NFL" and row.get("week") not in (None, ""):
            stage = f"Week {row['week']}"
        elif row.get("postseason"):
            stage = "Postseason"
        else:
            stage = str(row.get("season_type") or "Regular Season").replace("_", " ").title()
        return {
            "id": f"bdl-{self.code}-{row.get('id')}", "provider_id": row.get("id"),
            "stage": stage, "venue": row.get("venue") or "",
            "kickoff": _iso_utc(row.get("datetime") or row.get("date")),
            "status": status, "minute": minute or None,
            "score": normalized_score(home_score, away_score, status == "FINISHED"),
            "home": home, "away": away, "markets": {}, "lineups": None, "h2h": [],
            "injuries": {"home": [], "away": []}, "data_source": "BALLDONTLIE",
        }

    def standings(self):
        return {}, []

    def attach_availability(self, matches):
        return 0

    def leaders(self):
        return {}


class APISportsAdapter:
    """API-Sports (api-sports.io) adapter for NBA and NFL.

    Same account/key family as API_FOOTBALL_KEY — the free plan covers every
    API-Sports product, so no separate signup or key is needed. NBA's
    /standings doesn't expose points-for/against, so goal-difference for
    that sport stays 0; win/loss/record are still real.
    """

    BASES = {"NBA": "https://v2.nba.api-sports.io", "NFL": "https://v1.american-football.api-sports.io"}
    NFL_LEAGUE_ID = 1
    # API-Sports' NFL game/standings payloads have no team "code" field
    # (unlike NBA, which does), so map the 32 fixed team names ourselves.
    NFL_CODES = {
        "Buffalo Bills": "BUF", "Miami Dolphins": "MIA", "New England Patriots": "NE", "New York Jets": "NYJ",
        "Baltimore Ravens": "BAL", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Pittsburgh Steelers": "PIT",
        "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Tennessee Titans": "TEN",
        "Denver Broncos": "DEN", "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
        "Dallas Cowboys": "DAL", "New York Giants": "NYG", "Philadelphia Eagles": "PHI", "Washington Commanders": "WAS",
        "Chicago Bears": "CHI", "Detroit Lions": "DET", "Green Bay Packers": "GB", "Minnesota Vikings": "MIN",
        "Atlanta Falcons": "ATL", "Carolina Panthers": "CAR", "New Orleans Saints": "NO", "Tampa Bay Buccaneers": "TB",
        "Arizona Cardinals": "ARI", "Los Angeles Rams": "LAR", "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA",
    }

    def __init__(self, api_key, competition, getter=None, today=None):
        if not api_key:
            raise ProviderError("missing API_FOOTBALL_KEY")
        if competition not in self.BASES:
            raise ProviderError(f"unsupported API-Sports competition: {competition}")
        self.key = api_key
        self.competition = competition
        self.base = self.BASES[competition]
        self.getter = getter or functools.partial(_get_json, provider="api_football")
        self.today = today or dt.date.today()
        self.season = _current_season("nba" if competition == "NBA" else "nfl", self.today)

    def _get(self, path, params=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.getter(url, {"x-apisports-key": self.key, "User-Agent": "Matchday/1.0"})

    def _games(self, season):
        params = ({"league": self.NFL_LEAGUE_ID, "season": season} if self.competition == "NFL"
                  else {"season": season})
        payload = self._get("/games", params)
        rows = payload.get("response") if isinstance(payload, dict) else []
        return rows or []

    def schedule(self):
        # NBA/NFL seasons are named by their starting year; between a season
        # ending and the next one being scheduled, both the current and prior
        # guess can come up empty, so walk back a couple of years.
        rows = self._games(self.season) or self._games(self.season - 1) or self._games(self.season - 2)
        matches = [self._match(row) for row in rows]
        matches = [m for m in matches if m]
        matches.sort(key=lambda m: m.get("kickoff") or "")
        return matches

    @staticmethod
    def _status(text):
        key = str(text or "").strip().lower()
        if "final" in key or "finished" in key:
            return "FINISHED"
        if any(tok in key for tok in ("progress", "quarter", "half", "live", " play")):
            return "LIVE"
        return "UPCOMING"

    def _code(self, team, name):
        return team.get("code") or (self.NFL_CODES.get(name) if self.competition == "NFL" else None) or _short_code(name)

    def _match(self, row):
        if self.competition == "NFL":
            game, teams, scores = row.get("game") or {}, row.get("teams") or {}, row.get("scores") or {}
            home_t, away_t = teams.get("home") or {}, teams.get("away") or {}
            status = self._status((game.get("status") or {}).get("long"))
            ts = (game.get("date") or {}).get("timestamp")
            kickoff = (dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")
                       if ts else _iso_utc((game.get("date") or {}).get("date")))
            home_score = (scores.get("home") or {}).get("total")
            away_score = (scores.get("away") or {}).get("total")
            week = game.get("week")
            stage = f"Week {week}" if week and str(week).isdigit() else str(week or game.get("stage") or "Regular Season")
            venue = (game.get("venue") or {}).get("name") or ""
            gid = game.get("id")
        else:
            teams, scores = row.get("teams") or {}, row.get("scores") or {}
            home_t, away_t = teams.get("home") or {}, teams.get("visitors") or {}
            status = self._status((row.get("status") or {}).get("long"))
            kickoff = _iso_utc((row.get("date") or {}).get("start"))
            home_score = (scores.get("home") or {}).get("points")
            away_score = (scores.get("visitors") or {}).get("points")
            stage = "Regular Season" if row.get("stage") in (1, "1", None) else "Postseason"
            venue = (row.get("arena") or {}).get("name") or ""
            gid = row.get("id")
        if not home_t.get("name") or not away_t.get("name"):
            return None
        return {
            "id": f"apis-{self.competition.lower()}-{gid}", "provider_id": gid,
            "stage": stage, "venue": venue, "kickoff": kickoff, "status": status, "minute": None,
            "score": normalized_score(home_score, away_score, status == "FINISHED"),
            "home": {"name": str(home_t.get("name") or ""), "code": str(self._code(home_t, home_t.get("name") or "")),
                     "pts": None, "gd": None, "form": "", "pos": None, "group": None},
            "away": {"name": str(away_t.get("name") or ""), "code": str(self._code(away_t, away_t.get("name") or "")),
                     "pts": None, "gd": None, "form": "", "pos": None, "group": None},
            "markets": {}, "lineups": None, "h2h": [], "injuries": {"home": [], "away": []},
            "data_source": "API-Sports",
        }

    def _standings_rows(self):
        for season in (self.season, self.season - 1, self.season - 2):
            params = ({"league": self.NFL_LEAGUE_ID, "season": season} if self.competition == "NFL"
                      else {"league": "standard", "season": season})
            payload = self._get("/standings", params)
            rows = payload.get("response") if isinstance(payload, dict) else []
            if rows:
                return rows
        return []

    def standings(self):
        grouped = {}
        for row in self._standings_rows():
            team = row.get("team") or {}
            name = team.get("name")
            if not name:
                continue
            if self.competition == "NFL":
                w = int(_number(row.get("won"), 0)); l = int(_number(row.get("lost"), 0))
                ties = int(_number(row.get("ties"), 0))
                pf = _number((row.get("points") or {}).get("for"), 0)
                pa = _number((row.get("points") or {}).get("against"), 0)
                group = row.get("division") or row.get("conference") or "NFL"
            else:
                w = int(_number((row.get("win") or {}).get("home"), 0)) + int(_number((row.get("win") or {}).get("away"), 0))
                l = int(_number((row.get("loss") or {}).get("home"), 0)) + int(_number((row.get("loss") or {}).get("away"), 0))
                ties, pf, pa = 0, 0, 0
                group = ((row.get("conference") or {}).get("name") or "NBA").title()
            code = self._code(team, name)
            played = w + l + ties
            win_pct = w / max(1, played)
            item = {"name": str(name), "code": str(code), "pos": None, "pld": played,
                    "w": w, "d": ties, "l": l, "gf": pf, "ga": pa, "gd": pf - pa,
                    "pts": w * 3 + ties, "form": "",
                    "record": f"{w}-{l}" + (f"-{ties}" if ties else ""),
                    "win_pct": win_pct, "league_win_pct": win_pct, "qual": ""}
            grouped.setdefault(group, []).append(item)
        tables, model = [], {}
        for group, teams in grouped.items():
            teams.sort(key=lambda x: (-x["win_pct"], -x["gd"], x["name"]))
            for i, t in enumerate(teams, 1):
                t["pos"] = i
                model[t["name"].lower()] = {**t, "group": group}
            tables.append({"group": group, "teams": teams})
        return model, sorted(tables, key=lambda x: x["group"])

    def attach_availability(self, matches):
        return 0

    def leaders(self):
        return {}


class SportmonksAdapter:
    BASE = "https://api.sportmonks.com/v3/football"

    def __init__(self, api_key, getter=None):
        if not api_key:
            raise ProviderError("missing SPORTMONKS_KEY")
        self.key = api_key
        self.getter = getter or _get_json

    def _get(self, path, params=None):
        query = dict(params or {})
        query["api_token"] = self.key
        return self.getter(f"{self.BASE}{path}?{urllib.parse.urlencode(query)}",
                           {"User-Agent": "Matchday/1.0"})

    def enrich(self, matches, name_match):
        dates = sorted({str(match.get("kickoff") or "")[:10] for match in matches
                        if match.get("status") in {"LIVE", "FINISHED", "UPCOMING"}
                        and str(match.get("kickoff") or "")[:10]})
        attached = 0
        for day in dates[-10:]:
            payload = self._get(f"/fixtures/date/{day}", {
                "include": "participants;scores;statistics.type;lineups.player;events;sidelined.player"
            })
            for fixture in payload.get("data") or []:
                participants = fixture.get("participants") or []
                home = next((p for p in participants if (p.get("meta") or {}).get("location") == "home"), None)
                away = next((p for p in participants if (p.get("meta") or {}).get("location") == "away"), None)
                if not home or not away:
                    continue
                match = next((m for m in matches if name_match(home.get("name"), m["home"]["name"])
                              and name_match(away.get("name"), m["away"]["name"])), None)
                if not match:
                    continue
                self._attach_fixture(match, fixture, home.get("id"), away.get("id"))
                attached += 1
        return attached

    def _attach_fixture(self, match, fixture, home_id, away_id):
        stats = {"home": {}, "away": {}, "source": "Sportmonks", "fixture_id": fixture.get("id")}
        stat_map = {"shots-total": "shots", "shots-on-target": "shots_on_target",
                    "ball-possession": "possession", "corners": "corners", "fouls": "fouls",
                    "offsides": "offsides", "saves": "saves", "yellowcards": "yellow_cards",
                    "redcards": "red_cards"}
        for row in fixture.get("statistics") or []:
            participant = row.get("participant_id")
            side = "home" if participant == home_id else "away" if participant == away_id else None
            type_row = row.get("type") or {}
            key = stat_map.get(str(type_row.get("code") or type_row.get("name") or "").lower().replace(" ", "-"))
            if side and key:
                stats[side][key] = _number((row.get("data") or {}).get("value", row.get("value")), 0)
        if stats["home"] and stats["away"]:
            match["stats_extra"] = stats
            match["stats"] = stats

        lineups = fixture.get("lineups") or []
        sides = {"home": [], "away": []}
        for row in lineups:
            participant = row.get("team_id") or row.get("participant_id")
            side = "home" if participant == home_id else "away" if participant == away_id else None
            player = row.get("player") or {}
            if side and row.get("type_id") in (None, 11) and (row.get("formation_position") or row.get("position_id")):
                sides[side].append({"n": row.get("jersey_number") or "",
                                    "name": player.get("display_name") or player.get("name") or "", "out": False})
        if len(sides["home"]) >= 7 and len(sides["away"]) >= 7:
            match["lineups"] = {"home": {"formation": "", "xi": sides["home"][:11]},
                                "away": {"formation": "", "xi": sides["away"][:11]}, "subs": []}

        for row in fixture.get("sidelined") or []:
            participant = row.get("participant_id") or row.get("team_id")
            side = "home" if participant == home_id else "away" if participant == away_id else None
            player = row.get("player") or {}
            if side and player.get("name"):
                reason = row.get("category") or row.get("reason") or "unavailable"
                match.setdefault("injuries", {"home": [], "away": []})[side].append(f"{player['name']} ({reason})")
