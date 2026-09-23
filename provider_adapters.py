"""Licensed-provider adapters for Matchday.

The adapters deliberately return Matchday's existing JSON shapes.  Provider
payloads stay isolated here so changing vendors never requires a UI rewrite.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import math
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from advanced_metrics import cfbd_advanced_team_profiles
import provider_quota


class ProviderError(RuntimeError):
    pass


CFBD_FREE_QUOTA_URL = "https://api.collegefootballdata.com/info"


def _refresh_cfbd_quota_free(headers, timeout=25):
    """Reconcile CFBD quota state through its documented zero-call endpoint."""
    req = urllib.request.Request(CFBD_FREE_QUOTA_URL, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        quota_headers = dict(response.headers.items())
        if not any(str(key).lower() == "x-calllimit-remaining" for key in quota_headers):
            remaining = payload.get("remainingCalls") if isinstance(payload, dict) else None
            if remaining is not None:
                quota_headers["x-calllimit-remaining"] = str(remaining)
        # Labelled explicitly: a zero-cost probe still belongs in the spend
        # breakdown, or the accounting quietly under-reports the month.
        provider_quota.record_response("cfbd", quota_headers,
                                       url="https://api.collegefootballdata.com/info")


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
            if provider == "cfbd" and provider_quota.claim_free_probe(provider):
                try:
                    _refresh_cfbd_quota_free(headers or {}, timeout)
                    provider_quota.check(provider)
                except Exception as refresh_exc:
                    provider_quota.record_block(provider)
                    raise ProviderError(str(refresh_exc)) from refresh_exc
            else:
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
                provider_quota.record_response(provider, response.headers, url=url)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if provider:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            provider_quota.record_response(provider, exc.headers, error_body, url=url)
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
# real Elo rating trained on other teams' results. There is no honest way to
# recover which team was meant, so the game is dropped instead.
PLACEHOLDER_TEAM_NAMES = {
    "unknown", "unk", "tbd", "tba", "to be determined", "undecided",
    "n/a", "na", "none", "null",
}


def is_placeholder_team_name(name):
    """True when `name` is a provider placeholder rather than a real team."""
    return " ".join(str(name or "").strip().lower().split()) in PLACEHOLDER_TEAM_NAMES


def _team_identity(value):
    """Provider-neutral team key for joining enrichment feeds to fixtures."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


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
            # ET is not a fixed UTC-5 offset: summer fixtures observe EDT.
            parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
        return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return str(value)


def _current_season(code, today=None):
    today = today or dt.date.today()
    # Basketball seasons are identified by their starting year.
    if code == "cbb" and today.month <= 6:
        return today.year - 1
    return today.year


SPORTSDATA_CODES = {"NCAAF": "cfb", "NCAAM": "cbb"}


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


class SportsGameOddsAdapter:
    """Quota-bounded pregame market overlay for the provider's free tier.

    The Events payload also contains event/player metadata, but the `players`
    object is the set referenced by offered props -- it is not a confirmed
    lineup or an injury report.  This adapter therefore attaches only venue
    metadata and a bookmaker-derived game market.  Provider-level consensus
    fields are deliberately ignored because the free payload includes ESPN
    BET; Matchday recomputes consensus from explicitly non-ESPN books.
    """

    BASE = "https://api.sportsgameodds.com/v2"
    LEAGUES = {"NCAAF": "NCAAF", "NCAAM": "NCAAB"}
    MAX_EVENTS = 8
    MONTHLY_RESERVE = 100

    def __init__(self, api_key, competition, getter=None):
        if not api_key or "PASTE_" in str(api_key):
            raise ProviderError("missing SPORTSGAMEODDS_KEY")
        if competition not in self.LEAGUES:
            raise ProviderError(f"unsupported SportsGameOdds competition: {competition}")
        self.key = str(api_key).strip()
        self.competition = competition
        self.league = self.LEAGUES[competition]
        self.getter = getter or _get_json

    def _get(self, path, params=None):
        url = self.BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self.getter(url, {
            "x-api-key": self.key,
            "User-Agent": "Matchday/1.0",
        })

    def remaining_monthly_entities(self):
        payload = self._get("/account/usage")
        data = payload.get("data") if isinstance(payload, dict) else {}
        limits = data.get("rateLimits") if isinstance(data, dict) else {}
        month = limits.get("per-month") if isinstance(limits, dict) else {}
        try:
            maximum = int(month.get("max-entities"))
            current = int(month.get("current-entities"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ProviderError("SportsGameOdds monthly usage counters unavailable") from exc
        return max(0, maximum - current)

    def upcoming_events(self, starts_after, starts_before, limit=None):
        remaining = self.remaining_monthly_entities()
        event_cap = self.MAX_EVENTS
        request_limit = min(int(limit or event_cap), event_cap)
        # The usage request itself counts as at least one object. Preserve a
        # real reserve plus the maximum size of the event response before the
        # second request is allowed to fire.
        if remaining <= self.MONTHLY_RESERVE + request_limit:
            raise ProviderError(
                f"SportsGameOdds monthly object reserve reached ({remaining} remaining)"
            )
        odd_ids = "points-home-game-ml-home,points-away-game-ml-away"
        payload = self._get("/events", {
            "leagueID": self.league,
            "started": "false",
            "cancelled": "false",
            "startsAfter": starts_after,
            "startsBefore": starts_before,
            "oddID": odd_ids,
            "includeOpposingOdds": "false",
            "limit": request_limit,
        })
        rows = payload.get("data") if isinstance(payload, dict) else None
        return [row for row in (rows or []) if isinstance(row, dict)]

    @staticmethod
    def _american_implied(value):
        try:
            price = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        if price <= -100:
            return abs(price) / (abs(price) + 100.0)
        if price >= 100:
            return 100.0 / (price + 100.0)
        return None

    @staticmethod
    def _outcome_odds(event, side, has_draws):
        period = "reg" if has_draws else "game"
        bet_type = "ml3way" if has_draws else "ml"
        for odd in (event.get("odds") or {}).values():
            if not isinstance(odd, dict):
                continue
            if (odd.get("periodID") == period and odd.get("betTypeID") == bet_type
                    and odd.get("sideID") == side and odd.get("statID") == "points"):
                return odd
        return {}

    @classmethod
    def market(cls, event, has_draws=False, observed_at=None):
        sides = ("home", "draw", "away") if has_draws else ("home", "away")
        by_side = {}
        for side in sides:
            odd = cls._outcome_odds(event, side, has_draws)
            prices = {}
            for book_id, quote in (odd.get("byBookmaker") or {}).items():
                # Matchday's standing ESPN exclusion applies even when ESPN
                # BET arrives indirectly inside an otherwise permitted API.
                if "espn" in str(book_id).lower() or not isinstance(quote, dict):
                    continue
                if quote.get("available") is False:
                    continue
                implied = cls._american_implied(quote.get("odds"))
                if implied is not None:
                    prices[str(book_id)] = implied
            by_side[side] = prices
        common = set.intersection(*(set(by_side[side]) for side in sides)) if sides else set()
        if not common:
            return None
        normalized = {side: [] for side in sides}
        home_book = []
        for book_id in sorted(common):
            raw = {side: by_side[side][book_id] for side in sides}
            total = sum(raw.values())
            if total <= 0:
                continue
            for side in sides:
                normalized[side].append(raw[side] / total)
            home_book.append(raw["home"] / total * 100.0)
        if not home_book:
            return None
        averages = {side: sum(values) / len(values) * 100.0
                    for side, values in normalized.items()}
        floors = {side: int(math.floor(value)) for side, value in averages.items()}
        remainder = 100 - sum(floors.values())
        order = sorted(sides, key=lambda side: averages[side] - floors[side], reverse=True)
        for side in order[:max(0, remainder)]:
            floors[side] += 1
        market = {
            "home_pct": floors["home"],
            "draw_pct": floors.get("draw", 0),
            "away_pct": floors["away"],
            "books": len(home_book),
            "observed_at": observed_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": "SportsGameOdds consensus",
            "source_reference": "https://sportsgameodds.com/",
            "provider_event_id": event.get("eventID"),
            "espn_excluded": True,
        }
        if len(home_book) >= 2:
            spread = round(max(home_book) - min(home_book))
            market.update({
                "spread": spread,
                "spread_lo": round(min(home_book)),
                "spread_hi": round(max(home_book)),
                "confidence": "tight" if spread <= 8 else "mixed" if spread <= 18 else "split",
            })
        return market

    @staticmethod
    def _team_values(team):
        names = team.get("names") if isinstance(team, dict) else {}
        return [team.get("teamID"), names.get("long"), names.get("medium"), names.get("short")]

    @classmethod
    def _same_team(cls, provider_team, match_team):
        wanted = {_team_identity((match_team or {}).get(key)) for key in ("name", "code")}
        wanted.discard("")
        candidates = {_team_identity(value) for value in cls._team_values(provider_team or {})}
        candidates.discard("")
        if wanted & candidates:
            return True
        # teamID appends the league (NEW_YORK_YANKEES_MLB); accepting a
        # prefix only when the complete fixture name is present avoids loose
        # city/nickname matches and cross-team collisions.
        full = _team_identity((match_team or {}).get("name"))
        return bool(full and any(value.startswith(full) for value in candidates))

    @staticmethod
    def _event_time(event):
        # The provider carries the kickoff on the `status` object, not at the
        # top level and not on `info` (confirmed live 2026-08-20: `info` holds
        # only venue metadata). Without this the whole function returned None
        # for every event, which silently killed the `teams_and_start_time`
        # join strategy -- so an MLB doubleheader, the exact case _event_join
        # promises never to guess at, produced two same-pair candidates and
        # was rejected as ambiguous instead of being separated by start time.
        info = event.get("info") if isinstance(event.get("info"), dict) else {}
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        return _iso_utc(event.get("startsAt") or event.get("startTime") or
                        event.get("scheduled") or status.get("startsAt") or
                        status.get("startTime") or info.get("startsAt") or
                        info.get("startTime"))

    @staticmethod
    def _match_provider_ids(match):
        values = (match.get("provider_event_id"), match.get("provider_id"), match.get("id"))
        return {str(value) for value in values if value not in (None, "")}

    @classmethod
    def _event_join(cls, events, match):
        """Return one exact event and a receipt; never guess a doubleheader."""
        candidates = []
        for event in events:
            teams = event.get("teams") or {}
            if (cls._same_team(teams.get("home") or {}, match.get("home") or {}) and
                    cls._same_team(teams.get("away") or {}, match.get("away") or {})):
                candidates.append(event)
        receipt = {
            "match_provider_ids": sorted(cls._match_provider_ids(match)),
            "match_kickoff": _iso_utc(match.get("kickoff")),
            "candidate_event_ids": [event.get("eventID") for event in candidates],
        }
        if not candidates:
            return None, {**receipt, "status": "rejected", "reason": "team_pair_not_found"}

        wanted_ids = cls._match_provider_ids(match)
        id_matches = [event for event in candidates
                      if str(event.get("eventID")) in wanted_ids]
        if len(id_matches) == 1:
            event = id_matches[0]
            return event, {**receipt, "status": "matched", "strategy": "provider_event_id",
                           "provider_event_id": event.get("eventID"),
                           "provider_start": cls._event_time(event)}

        kickoff = _iso_utc(match.get("kickoff"))
        time_matches = [event for event in candidates
                        if kickoff and cls._event_time(event) == kickoff]
        if len(time_matches) == 1:
            event = time_matches[0]
            return event, {**receipt, "status": "matched", "strategy": "teams_and_start_time",
                           "provider_event_id": event.get("eventID"),
                           "provider_start": cls._event_time(event)}
        if len(candidates) == 1:
            event = candidates[0]
            event_time = cls._event_time(event)
            if kickoff and event_time and kickoff != event_time:
                return None, {**receipt, "status": "rejected", "reason": "start_time_mismatch",
                              "provider_start": event_time}
            return event, {**receipt, "status": "matched", "strategy": "unique_team_pair",
                           "provider_event_id": event.get("eventID"),
                           "provider_start": event_time}
        return None, {**receipt, "status": "rejected",
                      "reason": "ambiguous_same_team_fixture"}

    @classmethod
    def _event_for_match(cls, events, match):
        event, _ = cls._event_join(events, match)
        return event

    def attach_pregame(self, matches, events, observed_at=None, has_draws=False):
        attached = venues = 0
        for match in matches:
            event, join_receipt = self._event_join(events, match)
            if not event:
                if join_receipt.get("reason") == "ambiguous_same_team_fixture":
                    match.setdefault("pregame_provenance", []).append({
                        "input": "fixture_join", "source": "SportsGameOdds",
                        "join": join_receipt, "fetched_at": observed_at,
                    })
                continue
            info = event.get("info") or {}
            venue = info.get("venue")
            if not match.get("venue") and isinstance(venue, dict):
                venue = venue.get("name") or venue.get("displayName")
            if not match.get("venue") and isinstance(venue, str) and venue.strip():
                match["venue"] = venue.strip()
                venues += 1
            existing = (match.get("markets") or {}).get("1x2")
            market = None if existing else self.market(event, has_draws, observed_at)
            if market:
                match.setdefault("markets", {})["1x2"] = market
                attached += 1
            match.setdefault("pregame_provenance", []).append({
                "input": "market" if market else "event_metadata",
                "source": "SportsGameOdds",
                "source_reference": "https://sportsgameodds.com/",
                "fetched_at": observed_at,
                "provider_event_id": event.get("eventID"),
                "join": join_receipt,
                "espn_excluded": True,
            })
        return {"markets": attached, "venues": venues}


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

    def attach_availability(self, matches):
        """Attach licensed injury/availability labels when the feed includes them."""
        # The league OpenAPI specs expose the cross-team injury list from the
        # projections product as InjuredPlayers.
        rows = self._get_product("projections", "InjuredPlayers")
        by_team = {}
        for row in rows if isinstance(rows, list) else []:
            team = str(row.get("Team") or row.get("TeamKey") or "")
            name = row.get("Name") or row.get("PlayerName") or ""
            status = row.get("InjuryStatus") or row.get("Status") or "Unavailable"
            if team and name:
                by_team.setdefault(team.lower(), []).append({
                    "player_id": row.get("PlayerID") or row.get("GlobalPlayerID"),
                    "name": str(name), "status": str(status),
                    "position": str(row.get("Position") or ""),
                    "body_part": str(row.get("BodyPart") or row.get("InjuryBodyPart") or ""),
                    "updated_at": _iso_utc(row.get("Updated") or row.get("UpdatedDate") or
                                             row.get("LastUpdated")),
                })
        # CFBD/CBBD fixture abbreviations are not SportsDataIO team keys.
        # Resolve both providers through normalized full team names.
        def team_key(value):
            return re.sub(r"[^a-z0-9]", "", str(value or "").lower())
        aliases = {}
        for provider_code, provider_name in self.teams().items():
            aliases[team_key(provider_code)] = str(provider_code).lower()
            aliases[team_key(provider_name)] = str(provider_code).lower()
        attached = 0
        for match in matches:
            personnel = match.setdefault("personnel", {})
            personnel["injuries_feed_checked"] = True
            for side in ("home", "away"):
                team = match.get(side) or {}
                code = aliases.get(team_key(team.get("code"))) or \
                       aliases.get(team_key(team.get("name"))) or \
                       str(team.get("code") or "").lower()
                people = by_team.get(code) or []
                if people:
                    details = people[:20]
                    match.setdefault("injuries_shadow", {"home": [], "away": []})[side] = [
                        f"{person['name']} ({person['status']})" for person in details[:12]
                    ]
                    personnel.setdefault("injury_details", {"home": [], "away": []})[side] = details
                    attached += len(people[:12])
            match.setdefault("pregame_provenance", []).append({
                "input": "injuries", "source": "SportsDataIO",
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            })
        return attached

    def attach_pregame(self, matches):
        """Overlay licensed availability."""
        errors = []
        try:
            attached = self.attach_availability(matches)
        except ProviderError as exc:
            attached = 0
            errors.append({"input": "injuries", "error": str(exc)})
        return {"injuries": attached, "lineups": 0, "errors": errors}

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
            poll_name = str(poll.get("poll") or "National Poll")
            ranks = [{"rank": int(row.get("rank") or 0), "name": row.get("school") or "", "code": _short_code(row.get("school")), "record": ""}
                     for row in (poll.get("ranks") or [])[:25] if row.get("school")]
            for row in ranks:
                row["poll_name"] = poll_name
        elif not season_started:
            ranks = self._projected_ranking()
        else:
            ranks = []
        is_real_poll = bool(ranks) and not ranks[0].get("projected")
        cfp = self._cfp_projection(ranks) if is_real_poll and len(ranks) >= 12 else None
        self._cached_rankings = (ranks, cfp)
        return self._cached_rankings

    @staticmethod
    def _cfp_projection(ranks):
        """Preserve the poll-based bracket without depending on another provider."""
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

    def advanced_team_metrics(self, season=None):
        """Licensed CFBD opponent/context-aware season metrics in one call.

        This intentionally uses `/stats/season/advanced`, not a named third-
        party rating. The returned values are shadow research inputs and do
        not alter the production prediction weights.

        `season` overrides the current season. These metrics are derived from
        plays that have actually been run, so the current season answers with
        nothing until enough of it has been played; the caller uses this to ask
        for the last completed season instead of showing no profile at all.
        """
        year = int(season or self.season)
        rows = self._get("/stats/season/advanced", {
            "year": year,
            "excludeGarbageTime": "true",
        })
        return {
            "season": year,
            "source": "CollegeFootballData /stats/season/advanced",
            "profiles": cfbd_advanced_team_profiles(rows if isinstance(rows, list) else []),
        }

    def venues(self):
        """Licensed stadium coordinates for weather lookup, in one call.

        College venue names are not unique -- several schools share a bare
        "Memorial Stadium" -- so a hand-built keyword table cannot resolve
        them, and resolving by home team instead attaches the wrong forecast
        to a neutral-site game (TCU hosting in Dublin, Notre Dame at Lambeau).
        The provider publishes the coordinates directly, which removes the
        guess entirely. Slow-moving data: fetched once and persisted.
        """
        rows = self._get("/venues")
        venues = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            name = str(row.get("name") or "").strip()
            if not name or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                continue
            venues.append({
                "name": name,
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "dome": bool(row.get("dome")),
                "city": str(row.get("city") or "").strip(),
                "state": str(row.get("state") or "").strip(),
            })
        return venues


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
            poll_name = str(rows[0].get("pollType") or "National Poll") if rows else "National Poll"
            ranks = [{"rank": row["ranking"], "name": row["team"], "code": _short_code(row["team"]), "record": ""}
                     for row in rows[:25]]
            for row in ranks:
                row["poll_name"] = poll_name
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

