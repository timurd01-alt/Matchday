"""Licensed-provider adapters for Matchday.

The adapters deliberately return Matchday's existing JSON shapes.  Provider
payloads stay isolated here so changing vendors never requires a UI rewrite.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
import urllib.parse
import urllib.request


class ProviderError(RuntimeError):
    pass


def _get_json(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Matchday/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ProviderError(str(exc)) from exc


def _number(value, default=0):
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return default


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


def _short_code(name):
    words = [word for word in str(name or "").replace("-", " ").split() if word]
    return "".join(word[0] for word in words[:4]).upper() or str(name or "")[:4].upper()


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
                    ("Assists", "Assists", False), ("GoaltendingSavePercentage", "Save percentage", False)],
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
        self.key, self.getter = api_key, getter or _get_json
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
        matches = []
        now = dt.datetime.now(dt.timezone.utc)
        for row in self._games:
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
        if not rows and self.season > 2000:
            rows = self._get("/records", {"year": self.season - 1, "classification": "fbs"})
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
                    "win_pct": w / max(1, pld), "league_win_pct": int(conf.get("wins") or 0) / max(1, int(conf.get("games") or 0)), "qual": ""}
            grouped.setdefault(group, []).append(item)
            model[name.lower()] = {**item, "group": group}
        tables = []
        for group, teams in grouped.items():
            teams.sort(key=lambda x: (-x["win_pct"], -x["gd"], x["name"]))
            for index, team in enumerate(teams, 1): team["pos"] = index
            tables.append({"group": group, "teams": teams})
        return model, sorted(tables, key=lambda x: x["group"])

    def rankings(self, standings_payload):
        if self._cached_rankings is not None:
            return self._cached_rankings
        payload = self._get("/rankings", {"year": self.season, "seasonType": "regular"})
        def collect(rows):
            found = []
            for week in rows if isinstance(rows, list) else []:
                for poll in week.get("polls") or []:
                    priority = 0 if "playoff" in str(poll.get("poll") or "").lower() else 1 if "ap top" in str(poll.get("poll") or "").lower() else 2
                    found.append((int(week.get("season") or 0), int(week.get("week") or 0), -priority, poll))
            return found
        candidates = collect(payload)
        if not candidates and self.season > 2000:
            candidates = collect(self._get("/rankings", {"year": self.season - 1, "seasonType": "postseason"}))
        if candidates:
            poll = sorted(candidates, reverse=True, key=lambda x: x[:3])[0][3]
            ranks = [{"rank": int(row.get("rank") or 0), "name": row.get("school") or "", "code": _short_code(row.get("school")), "record": ""}
                     for row in (poll.get("ranks") or [])[:25] if row.get("school")]
        else:
            ranks = []
        self._cached_rankings = (ranks, SportsDataIOAdapter._cfp_projection(ranks) if len(ranks) >= 12 else None)
        return self._cached_rankings

    def attach_availability(self, matches): return 0
    def leaders(self): return {}


class CollegeBasketballDataAdapter:
    BASE = "https://api.collegebasketballdata.com"

    def __init__(self, api_key, getter=None, today=None):
        if not api_key:
            raise ProviderError("missing CBBD_KEY")
        self.key, self.getter = api_key, getter or _get_json
        self.today = today or dt.date.today()
        self.season = self.today.year
        self._games = []
        self._d1_teams = set()

    def _get(self, path, params=None):
        url = self.BASE + path
        if params: url += "?" + urllib.parse.urlencode(params)
        return self.getter(url, {"Authorization": f"Bearer {self.key}", "User-Agent": "Matchday/1.0"})

    def schedule(self):
        team_rows = self._get("/teams")
        self._d1_teams = {str(row.get("school")) for row in team_rows if row.get("school") and row.get("conference")}
        # The endpoint deliberately caps responses at 3,000 rows. Four bounded
        # season windows retrieve the complete Division I schedule without loss.
        windows = ((f"{self.season - 1}-10-01T00:00:00Z", f"{self.season - 1}-12-01T00:00:00Z"),
                   (f"{self.season - 1}-12-01T00:00:00Z", f"{self.season}-02-01T00:00:00Z"),
                   (f"{self.season}-02-01T00:00:00Z", f"{self.season}-04-01T00:00:00Z"),
                   (f"{self.season}-04-01T00:00:00Z", f"{self.season}-05-16T00:00:00Z"))
        by_id = {}
        for start, end in windows:
            chunk = self._get("/games", {"season": self.season, "startDateRange": start, "endDateRange": end})
            for row in chunk if isinstance(chunk, list) else []:
                by_id[str(row.get("id"))] = row
        rows = list(by_id.values())
        self._games = [row for row in rows if row.get("homeTeam") in self._d1_teams or row.get("awayTeam") in self._d1_teams] if isinstance(rows, list) else []
        matches = []
        for row in self._games:
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
            for i, team in enumerate(teams,1): team["pos"]=i
            tables.append({"group":group,"teams":teams})
        return model, sorted(tables,key=lambda x:x["group"])

    def rankings(self, standings_payload):
        teams=[dict(team) for group in standings_payload for team in group.get("teams",[])];teams.sort(key=lambda x:(-x["win_pct"],-x["gd"],x["name"]))
        return ([{"rank":i,"name":team["name"],"code":team.get("code") or "","record":team.get("record") or ""} for i,team in enumerate(teams[:25],1)],None)
    def attach_availability(self, matches): return 0
    def leaders(self): return {}


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
        self.getter = getter or _get_json
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

    @staticmethod
    def _team(row, side):
        team = row.get(side) if isinstance(row.get(side), dict) else {}
        name = (team.get("full_name") or team.get("display_name") or
                row.get(f"{side}_name") or team.get("name"))
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
        if "final" in status_key or status_key in {"completed", "closed", "post"}:
            status = "FINISHED"
        elif any(token in status_key for token in ("progress", "quarter", "inning", "halftime", "live")):
            status = "LIVE"
        else:
            status = "UPCOMING"
        if self.competition == "MLB":
            home_score = (row.get("home_team_data") or {}).get("runs")
            away_score = (row.get("away_team_data") or {}).get("runs")
            minute = f"{row.get('period') or ''} {row.get('display_clock') or ''}".strip()
        else:
            home_score = row.get("home_team_score")
            away_score = row.get("visitor_team_score")
            minute = str(row.get("time") or raw_status or "") if status == "LIVE" else ""
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
        self.getter = getter or _get_json
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
